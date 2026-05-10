"""
Facade Pattern — приховує складну взаємодію підсистем
(парсер, ORM, агрегація, побудова звіту) за єдиним простим API.

Замість того, щоб views/команди безпосередньо смикали ORM, парсер,
агрегатор тощо — вони викликають один із методів TrafficAnalyticsFacade.

Це теж канонічний приклад Facade із методички, тільки замість
TaskService у нас декілька внутрішніх сервісів.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from typing import Iterable

from django.db import transaction
from django.db.models import Count, Sum, Avg, Q
from django.utils import timezone

from .models import LogFile, LogEntry, Report, ReportSection
from .parsers import parse_file, ParsedEntry
from .pandas_service import PandasAnalyticsService


# ---------------------------------------------------------------------------
# Внутрішні сервіси (підсистеми, які приховує фасад)
# ---------------------------------------------------------------------------
class _LogIngestionService:
    """Відповідає за збереження записів логу в БД."""

    BATCH_SIZE = 500

    def ingest(self, log_file: LogFile) -> tuple[int, int]:
        """Парсить файл і зберігає записи. Повертає (total, parsed)."""
        total = 0
        parsed = 0
        batch: list[LogEntry] = []

        with log_file.file.open("rb") as fp:
            for raw_line in fp:
                total += 1
                entry = self._line_to_entry(log_file, raw_line)
                if entry is None:
                    continue
                batch.append(entry)
                parsed += 1
                if len(batch) >= self.BATCH_SIZE:
                    LogEntry.objects.bulk_create(batch)
                    batch = []

        if batch:
            LogEntry.objects.bulk_create(batch)
        return total, parsed

    @staticmethod
    def _line_to_entry(log_file: LogFile, raw) -> LogEntry | None:
        from .parsers import parse_line
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        parsed = parse_line(raw)
        if parsed is None:
            return None
        return LogEntry(
            log_file=log_file,
            ip_address=parsed.ip_address,
            timestamp=parsed.timestamp,
            method=parsed.method,
            path=parsed.path,
            status_code=parsed.status_code,
            response_size=parsed.response_size,
            referer=parsed.referer,
            user_agent=parsed.user_agent,
            browser=parsed.browser,
            os_family=parsed.os_family,
            device_type=parsed.device_type,
        )


class _AggregationService:
    """Робить агрегацію статистики через ORM."""

    def overview(self, log_file: LogFile) -> dict:
        qs = log_file.entries.all()
        total = qs.count()
        if total == 0:
            return {
                "total_requests": 0,
                "unique_visitors": 0,
                "total_traffic": 0,
                "avg_response_size": 0,
                "error_rate": 0,
            }
        errors = qs.filter(status_code__gte=500).count()
        return {
            "total_requests": total,
            "unique_visitors": qs.values("ip_address").distinct().count(),
            "total_traffic": qs.aggregate(s=Sum("response_size"))["s"] or 0,
            "avg_response_size": qs.aggregate(a=Avg("response_size"))["a"] or 0,
            "error_rate": errors / total if total else 0,
        }

    def status_distribution(self, log_file: LogFile) -> dict:
        qs = (
            log_file.entries.values("status_code")
            .annotate(c=Count("id"))
            .order_by("status_code")
        )
        # Групуємо по класах: 2xx, 3xx, 4xx, 5xx
        groups = defaultdict(int)
        for row in qs:
            cls = f"{row['status_code'] // 100}xx"
            groups[cls] += row["c"]
        labels = sorted(groups.keys())
        return {"labels": labels, "data": [groups[k] for k in labels]}

    def top_paths(self, log_file: LogFile, limit: int = 10) -> dict:
        rows = (
            log_file.entries.values("path")
            .annotate(c=Count("id"))
            .order_by("-c")[:limit]
        )
        return {
            "labels": [r["path"][:60] for r in rows],
            "data": [r["c"] for r in rows],
        }

    def browsers(self, log_file: LogFile, limit: int = 8) -> dict:
        rows = (
            log_file.entries.exclude(browser="")
            .values("browser")
            .annotate(c=Count("id"))
            .order_by("-c")[:limit]
        )
        return {
            "labels": [r["browser"] for r in rows],
            "data": [r["c"] for r in rows],
        }

    def devices(self, log_file: LogFile) -> dict:
        rows = (
            log_file.entries.values("device_type")
            .annotate(c=Count("id"))
            .order_by("-c")
        )
        return {
            "labels": [r["device_type"] or "невідомо" for r in rows],
            "data": [r["c"] for r in rows],
        }

    def traffic_timeline(self, log_file: LogFile) -> dict:
        """Запити по годинах."""
        from django.db.models.functions import TruncHour
        rows = (
            log_file.entries.annotate(h=TruncHour("timestamp"))
            .values("h")
            .annotate(c=Count("id"))
            .order_by("h")
        )
        return {
            "labels": [r["h"].strftime("%Y-%m-%d %H:00") for r in rows],
            "data": [r["c"] for r in rows],
        }


class _ReportBuilderService:
    """Формує дерево секцій звіту (демонструє Composite на рівні даних)."""

    def __init__(self, aggregator: _AggregationService):
        self.agg = aggregator

    @transaction.atomic
    def build(self, log_file: LogFile, title: str | None = None) -> Report:
        report = Report.objects.create(
            log_file=log_file,
            title=title or f"Звіт по {log_file.name}",
            description="Автоматично згенерований звіт по результатах парсингу.",
        )
        # Композиція: групи містять листи (графіки/метрики)
        overview = ReportSection.objects.create(
            report=report, title="Загальний огляд",
            section_type="group", position=0,
        )
        ov = self.agg.overview(log_file)
        ReportSection.objects.create(
            report=report, parent=overview, title="Всього запитів",
            section_type="metric", position=0,
            payload={"value": ov["total_requests"], "unit": "запитів"},
        )
        ReportSection.objects.create(
            report=report, parent=overview, title="Унікальні відвідувачі",
            section_type="metric", position=1,
            payload={"value": ov["unique_visitors"], "unit": "IP"},
        )
        ReportSection.objects.create(
            report=report, parent=overview, title="Доля помилок",
            section_type="metric", position=2,
            payload={"value": round(ov["error_rate"] * 100, 2), "unit": "%"},
        )

        traffic = ReportSection.objects.create(
            report=report, title="Трафік", section_type="group", position=1,
        )
        ReportSection.objects.create(
            report=report, parent=traffic, title="Трафік у часі",
            section_type="chart", chart_kind="line", position=0,
            payload=self.agg.traffic_timeline(log_file),
        )
        ReportSection.objects.create(
            report=report, parent=traffic, title="Розподіл статус-кодів",
            section_type="chart", chart_kind="doughnut", position=1,
            payload=self.agg.status_distribution(log_file),
        )

        audience = ReportSection.objects.create(
            report=report, title="Аудиторія", section_type="group", position=2,
        )
        ReportSection.objects.create(
            report=report, parent=audience, title="Браузери",
            section_type="chart", chart_kind="pie", position=0,
            payload=self.agg.browsers(log_file),
        )
        ReportSection.objects.create(
            report=report, parent=audience, title="Пристрої",
            section_type="chart", chart_kind="bar", position=1,
            payload=self.agg.devices(log_file),
        )

        content = ReportSection.objects.create(
            report=report, title="Контент", section_type="group", position=3,
        )
        ReportSection.objects.create(
            report=report, parent=content, title="Топ-10 URL",
            section_type="table", position=0,
            payload={
                "headers": ["URL", "Запитів"],
                "rows": list(zip(
                    self.agg.top_paths(log_file)["labels"],
                    self.agg.top_paths(log_file)["data"],
                )),
            },
        )
        return report


# ---------------------------------------------------------------------------
# ФАСАД — публічне API
# ---------------------------------------------------------------------------
class TrafficAnalyticsFacade:
    """
    Єдина точка входу для аналітики.

    Приклад використання:
        facade = TrafficAnalyticsFacade()
        log_file = facade.upload_and_process(file_obj, name="access.log")
        report = facade.build_report(log_file)
        stats = facade.get_overview(log_file)
    """

    def __init__(self):
        self._ingestion = _LogIngestionService()
        self._aggregation = _AggregationService()
        self._reports = _ReportBuilderService(self._aggregation)
        self._pandas = PandasAnalyticsService()

    # --- Завантаження та обробка ---------------------------------------
    @transaction.atomic
    def upload_and_process(self, file_obj, name: str) -> LogFile:
        log_file = LogFile.objects.create(name=name, file=file_obj, status="pending")
        return self.process(log_file)

    def process(self, log_file: LogFile) -> LogFile:
        log_file.status = "processing"
        log_file.save(update_fields=["status"])
        try:
            total, parsed = self._ingestion.ingest(log_file)
            log_file.total_lines = total
            log_file.parsed_lines = parsed
            log_file.status = "done"
            log_file.processed_at = timezone.now()
            log_file.save()
        except Exception as exc:  # noqa: BLE001
            log_file.status = "error"
            log_file.error_message = str(exc)
            log_file.save(update_fields=["status", "error_message"])
            raise
        return log_file

    # --- Агрегація -----------------------------------------------------
    def get_overview(self, log_file: LogFile) -> dict:
        return self._aggregation.overview(log_file)

    def get_chart_data(self, log_file: LogFile, kind: str) -> dict:
        """Повертає дані для конкретного графіка (зручно для AJAX)."""
        mapping = {
            "status": self._aggregation.status_distribution,
            "paths": self._aggregation.top_paths,
            "browsers": self._aggregation.browsers,
            "devices": self._aggregation.devices,
            "timeline": self._aggregation.traffic_timeline,
        }
        if kind not in mapping:
            raise ValueError(f"Unknown chart kind: {kind}")
        return mapping[kind](log_file)

    # --- Звіти ---------------------------------------------------------
    def build_report(self, log_file: LogFile, title: str | None = None) -> Report:
        return self._reports.build(log_file, title=title)

    # --- Розширена аналітика на pandas --------------------------------
    def resample_traffic(
        self, log_file: LogFile, freq: str = "1h",
        filters: dict | None = None,
    ) -> dict:
        """Time-series resample (1min/5min/1h/1D)."""
        return self._pandas.resample_traffic(log_file, freq=freq, filters=filters)

    def rolling_anomalies(
        self,
        log_file: LogFile,
        window: str = "10min",
        threshold: float = 0.1,
    ) -> dict:
        """Виявлення аномалій ковзним вікном."""
        return self._pandas.rolling_error_rate(
            log_file, window=window, threshold=threshold
        )

    def aggregate(
        self, log_file: LogFile, group_by: str = "method",
        filters: dict | None = None, top: int = 10,
    ) -> dict:
        """Універсальна агрегація з вибором поля групування і фільтрами."""
        return self._pandas.aggregate(
            log_file, group_by=group_by, filters=filters, top=top
        )

    def status_over_time(
        self, log_file: LogFile, freq: str = "1h",
        filters: dict | None = None,
    ) -> dict:
        return self._pandas.status_over_time(log_file, freq=freq, filters=filters)

    def hour_weekday_heatmap(
        self, log_file: LogFile, filters: dict | None = None,
    ) -> dict:
        return self._pandas.hour_weekday_heatmap(log_file, filters=filters)

    def response_size_histogram(
        self, log_file: LogFile, filters: dict | None = None,
    ) -> dict:
        return self._pandas.response_size_histogram(log_file, filters=filters)

    def top_ips(
        self, log_file: LogFile, top: int = 10,
        filters: dict | None = None,
    ) -> dict:
        return self._pandas.top_ips(log_file, top=top, filters=filters)

    def export_excel(self, log_file: LogFile) -> bytes:
        """Експорт повного звіту в Excel."""
        return self._pandas.export_to_excel(log_file)

    # --- AI-аналіз ------------------------------------------------
    def ai_analyze(self, log_file: LogFile) -> str:
        """Інтелектуальний аналіз логу через Anthropic API (або fallback)."""
        from .ai_service import analyze_log_with_ai
        overview = self.get_overview(log_file)
        return analyze_log_with_ai(overview, log_file.name)
