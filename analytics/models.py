"""
Моделі даних для системи аналітики веб-трафіку.

LogFile     — завантажений лог-файл
LogEntry    — окремий запис з лог-файлу
Report      — звіт користувача
ReportSection — секція звіту (рекурсивна, реалізує Composite на рівні даних)
"""
from django.db import models
from django.urls import reverse
from django.conf import settings

class LogFile(models.Model):
    """Завантажений користувачем лог-файл."""

    STATUS_CHOICES = [
        ("pending", "Очікує обробки"),
        ("processing", "Обробляється"),
        ("done", "Оброблено"),
        ("error", "Помилка"),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="log_files",
        verbose_name="Користувач",
        null=True,
    )
    name = models.CharField(max_length=255, verbose_name="Назва")
    file = models.FileField(upload_to="logs/", verbose_name="Файл")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="Завантажено")
    processed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    total_lines = models.PositiveIntegerField(default=0)
    parsed_lines = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "Лог-файл"
        verbose_name_plural = "Лог-файли"

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def get_absolute_url(self):
        return reverse("analytics:logfile_detail", args=[self.pk])

    @property
    def parse_rate(self) -> float:
        """Відсоток успішно розпарсених рядків."""
        if self.total_lines == 0:
            return 0.0
        return self.parsed_lines / self.total_lines


class LogEntry(models.Model):
    """Окремий запис із лог-файлу (Apache/Nginx combined format)."""

    log_file = models.ForeignKey(
        LogFile, on_delete=models.CASCADE, related_name="entries"
    )
    ip_address = models.GenericIPAddressField()
    timestamp = models.DateTimeField(db_index=True)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=2048)
    status_code = models.PositiveSmallIntegerField(db_index=True)
    response_size = models.PositiveIntegerField(default=0)
    referer = models.CharField(max_length=2048, blank=True)
    user_agent = models.TextField(blank=True)
    # Розпарсені поля з User-Agent
    browser = models.CharField(max_length=100, blank=True, db_index=True)
    os_family = models.CharField(max_length=100, blank=True, db_index=True)
    device_type = models.CharField(max_length=20, blank=True, db_index=True)

    class Meta:
        verbose_name = "Запис логу"
        verbose_name_plural = "Записи логу"
        indexes = [
            models.Index(fields=["status_code", "timestamp"]),
            models.Index(fields=["log_file", "timestamp"]),
        ]

    def __str__(self):
        return f"{self.ip_address} {self.method} {self.path} [{self.status_code}]"

    @property
    def is_error(self) -> bool:
        return self.status_code >= 500

    @property
    def is_client_error(self) -> bool:
        return 400 <= self.status_code < 500


class Report(models.Model):
    """Звіт, який групує секції з аналітикою."""

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    log_file = models.ForeignKey(
        LogFile, on_delete=models.CASCADE, related_name="reports"
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Звіт"
        verbose_name_plural = "Звіти"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("analytics:report_detail", args=[self.pk])

    @property
    def root_sections(self):
        """Повертає тільки секції верхнього рівня (без батька)."""
        return self.sections.filter(parent__isnull=True).order_by("position")


class ReportSection(models.Model):
    """
    Секція звіту. Реалізує Composite Pattern:
    кожна секція може містити дочірні секції (parent → children).

    Використання:
        - chart  : секція-лист з графіком (Chart.js)
        - table  : секція-лист з таблицею
        - group  : композит-контейнер для інших секцій
    """

    SECTION_TYPES = [
        ("group", "Група секцій"),
        ("chart", "Графік"),
        ("table", "Таблиця"),
        ("metric", "Метрика"),
    ]

    CHART_KINDS = [
        ("line", "Лінійний"),
        ("bar", "Стовпчастий"),
        ("pie", "Кругова"),
        ("doughnut", "Кільцева"),
    ]

    report = models.ForeignKey(
        Report, on_delete=models.CASCADE, related_name="sections"
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    title = models.CharField(max_length=255)
    section_type = models.CharField(max_length=20, choices=SECTION_TYPES)
    chart_kind = models.CharField(
        max_length=20, choices=CHART_KINDS, blank=True
    )
    # JSON з даними для рендера: для chart — {labels: [...], data: [...]},
    # для table — {headers: [...], rows: [[...]]}, для metric — {value, unit}
    payload = models.JSONField(default=dict, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "Секція звіту"
        verbose_name_plural = "Секції звіту"

    def __str__(self):
        prefix = "  " * self.depth
        return f"{prefix}{self.title} ({self.get_section_type_display()})"

    @property
    def depth(self) -> int:
        """Глибина у дереві секцій (для відступів у шаблоні)."""
        depth = 0
        node = self.parent
        while node is not None:
            depth += 1
            node = node.parent
        return depth

    @property
    def is_leaf(self) -> bool:
        return self.section_type != "group"

    @property
    def payload_dom_id(self) -> str:
        return f"payload-{self.pk}"


class Notification(models.Model):
    """Лог сповіщень, які надсилав Observer (для аудиту/UI)."""

    KIND_CHOICES = [
        ("upload_done", "Файл оброблено"),
        ("anomaly", "Виявлено аномалію"),
        ("upload_failed", "Помилка обробки"),
    ]

    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    subject = models.CharField(max_length=255)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    log_file = models.ForeignKey(
        LogFile, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Сповіщення"
        verbose_name_plural = "Сповіщення"

    def __str__(self):
        return f"[{self.get_kind_display()}] {self.subject}"
