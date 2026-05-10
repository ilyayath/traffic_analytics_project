"""
Парсер access.log у форматі Apache/Nginx Combined Log Format.

Приклад рядка:
127.0.0.1 - - [10/Oct/2023:13:55:36 +0300] "GET /index.html HTTP/1.1" 200 2326 \
"http://example.com/" "Mozilla/5.0 (Windows NT 10.0) ..."
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Optional

from dateutil import parser as dateparser
from user_agents import parse as parse_ua


# Регулярний вираз для combined log format
LOG_PATTERN = re.compile(
    r'(?P<ip>\S+) \S+ \S+ '
    r'\[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<path>\S+) (?P<protocol>[^"]+)" '
    r'(?P<status>\d{3}) (?P<size>\d+|-) '
    r'"(?P<referer>[^"]*)" '
    r'"(?P<ua>[^"]*)"'
)


@dataclass
class ParsedEntry:
    """Структура з результатом парсингу одного рядка."""
    ip_address: str
    timestamp: datetime
    method: str
    path: str
    status_code: int
    response_size: int
    referer: str
    user_agent: str
    browser: str
    os_family: str
    device_type: str


def _device_type(ua) -> str:
    if ua.is_mobile:
        return "mobile"
    if ua.is_tablet:
        return "tablet"
    if ua.is_pc:
        return "desktop"
    if ua.is_bot:
        return "bot"
    return "other"


def parse_line(line: str) -> Optional[ParsedEntry]:
    """Парсить один рядок логу. Повертає None, якщо формат не підходить."""
    line = line.strip()
    if not line:
        return None
    m = LOG_PATTERN.match(line)
    if not m:
        return None

    try:
        # dateutil робить timestamp більш гнучким
        timestamp = dateparser.parse(m.group("time").replace(":", " ", 1))
    except (ValueError, TypeError):
        return None

    size_raw = m.group("size")
    size = int(size_raw) if size_raw.isdigit() else 0

    ua_string = m.group("ua")
    ua = parse_ua(ua_string)

    return ParsedEntry(
        ip_address=m.group("ip"),
        timestamp=timestamp,
        method=m.group("method"),
        path=m.group("path")[:2048],
        status_code=int(m.group("status")),
        response_size=size,
        referer=m.group("referer")[:2048],
        user_agent=ua_string,
        browser=ua.browser.family[:100],
        os_family=ua.os.family[:100],
        device_type=_device_type(ua),
    )


def parse_file(file_obj) -> Iterator[ParsedEntry]:
    """
    Генератор: ітерує по файлу і повертає ParsedEntry для коректних рядків.
    Невалідні рядки тихо пропускаються (статистика йде в LogFile.parsed_lines).
    """
    for raw in file_obj:
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8", errors="replace")
            except Exception:
                continue
        entry = parse_line(raw)
        if entry is not None:
            yield entry
