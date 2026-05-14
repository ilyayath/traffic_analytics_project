"""
Інтеграція ШІ для аналізу логів.

Пріоритет: Ollama (локальна модель) → Anthropic API → rule-based fallback.
"""
from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error

from django.conf import settings

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:latest"


def analyze_log_with_ai(overview: dict, log_name: str) -> str:
    """
    Аналізує статистику лог-файлу через AI.
    Спочатку пробує Ollama (локально), потім Anthropic, потім fallback.
    """
    prompt = (
        f"Ти — експерт з аналізу веб-трафіку. Проаналізуй статистику "
        f"access-логу '{log_name}' і надай короткий звіт (5-8 речень) "
        f"українською мовою з ключовими спостереженнями та рекомендаціями.\n\n"
        f"Статистика:\n{json.dumps(overview, indent=2, ensure_ascii=False)}"
    )

    # 1. Спроба Ollama (локальна модель)
    result = _try_ollama(prompt)
    if result:
        return result

    # 2. Спроба Anthropic API
    result = _try_anthropic(prompt)
    if result:
        return result

    # 3. Rule-based fallback
    return _fallback_analysis(overview, log_name)


def _try_ollama(prompt: str) -> str | None:
    """Виклик локальної моделі через Ollama REST API."""
    try:
        payload = json.dumps({
            "model": "mistral:latest",
            "prompt": prompt,
            "stream": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "").strip() or None
    except urllib.error.URLError:
        logger.info("Ollama not available at %s", OLLAMA_URL)
        return None
    except Exception as exc:
        logger.warning("Ollama error: %s", exc)
        return None

def _try_anthropic(prompt: str) -> str | None:
    """Виклик Anthropic Claude API (якщо є ключ)."""
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as exc:
        logger.warning("Anthropic call failed: %s", exc)
    return None


def _fallback_analysis(overview: dict, log_name: str) -> str:
    """Rule-based аналіз коли AI недоступний."""
    total = overview.get("total_requests", 0)
    unique = overview.get("unique_visitors", 0)
    error_rate = overview.get("error_rate", 0)
    avg_size = overview.get("avg_response_size", 0)
    total_traffic = overview.get("total_traffic", 0)

    if total == 0:
        return "Лог-файл порожній або не містить валідних записів."

    lines = [f"Аналіз лог-файлу '{log_name}':"]
    lines.append(
        f"Оброблено {total:,} запитів від {unique:,} унікальних IP-адрес. "
        f"Загальний обсяг переданих даних: {total_traffic:,} байт."
    )

    if error_rate > 0.1:
        lines.append(
            f"УВАГА: доля серверних помилок (5xx) складає {error_rate:.1%}, "
            f"що значно перевищує допустимий рівень. "
            f"Рекомендовано перевірити журнали помилок веб-сервера."
        )
    elif error_rate > 0.05:
        lines.append(
            f"Частка серверних помилок ({error_rate:.1%}) на межі допустимого. "
            f"Рекомендовано моніторинг."
        )
    else:
        lines.append(f"Частка серверних помилок ({error_rate:.1%}) у межах норми.")

    if unique > 0:
        ratio = total / unique
        lines.append(f"Середня кількість запитів на відвідувача: {ratio:.1f}.")

    if avg_size > 100000:
        lines.append(
            f"Середній розмір відповіді ({avg_size / 1024:.1f} КБ) великий. "
            f"Рекомендовано перевірити стиснення (gzip)."
        )

    lines.append(
        "(AI-модель недоступна. Встановіть Ollama і запустіть 'ollama pull mistral' "
        "або додайте ANTHROPIC_API_KEY у .env)"
    )
    return " ".join(lines)