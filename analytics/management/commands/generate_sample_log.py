"""Генерує демо-лог-файл для тестування."""
import random
from datetime import datetime, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand


PATHS = ["/", "/about", "/products", "/api/users", "/api/orders",
         "/login", "/logout", "/static/main.css", "/blog/post-1", "/contact"]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/118.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0) AppleWebKit/605.1.15 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Mobile",
    "curl/7.68.0",
]
STATUSES = [200, 200, 200, 200, 200, 301, 302, 404, 404, 500]


class Command(BaseCommand):
    help = "Генерує демо access.log для тестування"

    def add_arguments(self, parser):
        parser.add_argument("--lines", type=int, default=1000)
        parser.add_argument("--out", type=str, default="sample_data/access.log")

    def handle(self, *args, **opts):
        lines = opts["lines"]
        out = Path(opts["out"])
        out.parent.mkdir(parents=True, exist_ok=True)

        start = datetime(2024, 6, 1, 0, 0, 0)
        with out.open("w") as fp:
            for i in range(lines):
                ts = start + timedelta(seconds=i * 30 + random.randint(0, 30))
                ip = f"192.168.{random.randint(1, 5)}.{random.randint(1, 255)}"
                method = random.choice(["GET", "GET", "GET", "POST"])
                path = random.choice(PATHS)
                status = random.choice(STATUSES)
                size = random.randint(100, 50000) if status < 400 else 0
                ua = random.choice(USER_AGENTS)
                line = (
                    f'{ip} - - [{ts.strftime("%d/%b/%Y:%H:%M:%S")} +0300] '
                    f'"{method} {path} HTTP/1.1" {status} {size} '
                    f'"-" "{ua}"\n'
                )
                fp.write(line)

        self.stdout.write(self.style.SUCCESS(f"Згенеровано {lines} рядків у {out}"))
