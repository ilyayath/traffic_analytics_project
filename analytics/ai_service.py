"""
Інтеграція з Anthropic Claude API для інтелектуального аналізу логів.

Функціональність: генерація текстового звіту-аналізу на основі
агрегованих метрик лог-файлу. ШІ отримує статистику і повертає
людиномовний аналіз з рекомендаціями.

Ключ API зберігається у змінній середовища ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def analyze_log_with_ai(overview: dict, log_name: str) -> str:
    """
    Надсилає агреговану статистику лог-файлу до Anthropic Claude
    і повертає текстовий аналіз з рекомендаціями.

    Якщо API-ключ не налаштовано — повертає fallback-повідомлення.
    """
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not api_key:
        return _fallback_analysis(overview, log_name)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        prompt = (
            f"Ти — експерт з аналізу веб-трафіку. Проаналізуй статистику "
            f"access-логу '{log_name}' і надай короткий звіт (5-8 речень) "
            f"з ключовими спостереженнями та рекомендаціями.\n\n"
            f"Статистика:\n{json.dumps(overview, indent=2, ensure_ascii=False)}"
        )

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        return message.content[0].text

    except ImportError:
        logger.warning("anthropic package not installed")
        return _fallback_analysis(overview, log_name)
    except Exception as exc:
        logger.warning("AI analysis failed: %s", exc)
        return _fallback_analysis(overview, log_name)


def _fallback_analysis(overview: dict, log_name: str) -> str:
    """
    Rule-based аналіз як fallback коли API недоступний.
    Показує, що система працює навіть без зовнішнього API.
    """
    total = overview.get("total_requests", 0)
    unique = overview.get("unique_visitors", 0)
    error_rate = overview.get("error_rate", 0)
    avg_size = overview.get("avg_response_size", 0)
    total_traffic = overview.get("total_traffic", 0)

    lines = [f"Аналіз лог-файлу '{log_name}':"]

    if total == 0:
        return "Лог-файл порожній або не містить валідних записів."

    lines.append(
        f"Оброблено {total:,} запитів від {unique:,} унікальних IP-адрес. "
        f"Загальний обсяг переданих даних: {total_traffic:,} байт."
    )

    if error_rate > 0.1:
        lines.append(
            f"УВАГА: доля серверних помилок (5xx) складає {error_rate:.1%}, "
            f"що значно перевищує допустимий рівень 5%. "
            f"Рекомендовано перевірити журнали помилок веб-сервера."
        )
    elif error_rate > 0.05:
        lines.append(
            f"Частка серверних помилок ({error_rate:.1%}) знаходиться "
            f"на межі допустимого. Рекомендовано моніторинг."
        )
    else:
        lines.append(
            f"Частка серверних помилок ({error_rate:.1%}) у межах норми."
        )

    if unique > 0:
        ratio = total / unique
        if ratio > 10:
            lines.append(
                f"Середня кількість запитів на відвідувача: {ratio:.1f}. "
                f"Це свідчить про активне використання ресурсу."
            )
        else:
            lines.append(
                f"Середня кількість запитів на відвідувача: {ratio:.1f}."
            )

    if avg_size > 100000:
        lines.append(
            f"Середній розмір відповіді ({avg_size / 1024:.1f} КБ) великий. "
            f"Рекомендовано перевірити стиснення (gzip) і оптимізацію зображень."
        )

    lines.append(
        "(Аналіз виконано без AI API. Для розширеного аналізу "
        "додайте ANTHROPIC_API_KEY у .env)"
    )

    return " ".join(lines)
