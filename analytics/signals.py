"""
Observer Pattern через сигнали Django.

Коли LogFile змінює статус на 'done' — спрацьовує post_save сигнал,
який:
  1) Надсилає email адміну (як у методичці).
  2) Перевіряє наявність аномалій (напр., > 5% 5xx-помилок) і у разі
     виявлення — надсилає окреме сповіщення.

Кожен підписник (handler) — це самостійний "спостерігач" над тією самою
подією, що відповідає класичному GoF Observer.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import LogFile, Notification

logger = logging.getLogger(__name__)


# Кастомний сигнал — спостерігачі можуть слухати "файл повністю оброблено"
# окремо від низькорівневого post_save.
from django.dispatch import Signal
log_file_processed = Signal()  # kwargs: log_file


# ---------------------------------------------------------------------------
# Підписники (Observers)
# ---------------------------------------------------------------------------
@receiver(post_save, sender=LogFile)
def on_log_file_saved(sender, instance: LogFile, created, **kwargs):
    """Низькорівневий слухач: ловить факт переходу у статус 'done'."""
    if instance.status == "done":
        # Не дублюємо при кожному збереженні: дивимось чи вже
        # надсилали повідомлення для цього файлу.
        already_notified = Notification.objects.filter(
            log_file=instance, kind="upload_done"
        ).exists()
        if not already_notified:
            log_file_processed.send(sender=LogFile, log_file=instance)


@receiver(log_file_processed)
def notify_admin_email(sender, log_file: LogFile, **kwargs):
    """Спостерігач №1: відсилає email адміну (приклад із методички)."""
    subject = f"[Analytics] Файл оброблено: {log_file.name}"
    message = (
        f"Файл '{log_file.name}' успішно оброблено.\n"
        f"Розпарсено: {log_file.parsed_lines} з {log_file.total_lines} рядків "
        f"({log_file.parse_rate:.1%})."
    )
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [settings.ADMIN_EMAIL],
            fail_silently=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Email notification failed: %s", exc)

    Notification.objects.create(
        kind="upload_done",
        subject=subject,
        message=message,
        log_file=log_file,
    )


@receiver(log_file_processed)
def detect_traffic_anomalies(sender, log_file: LogFile, **kwargs):
    """Спостерігач №2: окремий — перевіряє долю 5xx помилок."""
    threshold = getattr(settings, "ANOMALY_ERROR_THRESHOLD", 0.05)
    total = log_file.entries.count()
    if total == 0:
        return
    errors = log_file.entries.filter(status_code__gte=500).count()
    rate = errors / total
    if rate < threshold:
        return
    subject = f"[Analytics] Аномалія: {rate:.1%} серверних помилок у {log_file.name}"
    message = (
        f"Файл '{log_file.name}' містить {errors} 5xx-помилок із {total} запитів "
        f"({rate:.1%}), що перевищує поріг {threshold:.1%}."
    )
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [settings.ADMIN_EMAIL],
            fail_silently=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Anomaly email failed: %s", exc)

    Notification.objects.create(
        kind="anomaly",
        subject=subject,
        message=message,
        log_file=log_file,
    )
