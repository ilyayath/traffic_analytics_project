"""Юніт-тести для системи аналітики."""
import io
from datetime import datetime, timezone

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .composite import CompositeSection, LeafSection, build_tree_from_orm
from .facades import TrafficAnalyticsFacade
from .models import LogEntry, LogFile, Notification, Report, ReportSection
from .pandas_service import PandasAnalyticsService
from .parsers import parse_line


SAMPLE_LOG = b"""\
192.168.1.10 - - [10/Oct/2023:13:55:36 +0300] "GET /index.html HTTP/1.1" 200 2326 "http://example.com/" "Mozilla/5.0 (Windows NT 10.0; Win64) Chrome/118.0"
192.168.1.10 - - [10/Oct/2023:13:55:40 +0300] "GET /about HTTP/1.1" 200 1024 "-" "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0)"
192.168.1.11 - - [10/Oct/2023:14:00:00 +0300] "POST /api/login HTTP/1.1" 500 50 "-" "curl/7.68.0"
192.168.1.12 - - [10/Oct/2023:14:01:00 +0300] "GET /missing HTTP/1.1" 404 0 "-" "Mozilla/5.0"
broken line that should be skipped
"""


def make_log_file(name="test.log", content=SAMPLE_LOG):
    return SimpleUploadedFile(name, content, content_type="text/plain")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ModelsTest(TestCase):
    def test_log_file_status_default(self):
        lf = LogFile.objects.create(name="x", file=make_log_file())
        self.assertEqual(lf.status, "pending")
        self.assertEqual(lf.parse_rate, 0.0)

    def test_log_entry_error_props(self):
        lf = LogFile.objects.create(name="x", file=make_log_file())
        e = LogEntry.objects.create(
            log_file=lf, ip_address="1.1.1.1",
            timestamp=datetime.now(tz=timezone.utc),
            method="GET", path="/", status_code=500,
        )
        self.assertTrue(e.is_error)
        self.assertFalse(e.is_client_error)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
class ParserTest(TestCase):
    def test_parse_valid_line(self):
        line = SAMPLE_LOG.decode().split("\n")[0]
        e = parse_line(line)
        self.assertIsNotNone(e)
        self.assertEqual(e.ip_address, "192.168.1.10")
        self.assertEqual(e.method, "GET")
        self.assertEqual(e.path, "/index.html")
        self.assertEqual(e.status_code, 200)

    def test_parse_invalid_line_returns_none(self):
        self.assertIsNone(parse_line("garbage"))
        self.assertIsNone(parse_line(""))


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------
class FacadeTest(TestCase):
    def setUp(self):
        self.facade = TrafficAnalyticsFacade()

    def test_upload_and_process_creates_entries(self):
        lf = self.facade.upload_and_process(make_log_file(), name="test.log")
        self.assertEqual(lf.status, "done")
        self.assertEqual(lf.parsed_lines, 4)  # 4 валідні рядки
        self.assertEqual(lf.total_lines, 5)   # 5 рядків (4 валідні + 1 garbage)
        self.assertEqual(lf.entries.count(), 4)

    def test_overview(self):
        lf = self.facade.upload_and_process(make_log_file(), name="t.log")
        ov = self.facade.get_overview(lf)
        self.assertEqual(ov["total_requests"], 4)
        self.assertEqual(ov["unique_visitors"], 3)
        self.assertGreater(ov["error_rate"], 0)

    def test_chart_data_kinds(self):
        lf = self.facade.upload_and_process(make_log_file(), name="t.log")
        for kind in ["status", "paths", "browsers", "devices", "timeline"]:
            data = self.facade.get_chart_data(lf, kind)
            self.assertIn("labels", data)
            self.assertIn("data", data)

    def test_chart_data_invalid_kind_raises(self):
        lf = self.facade.upload_and_process(make_log_file(), name="t.log")
        with self.assertRaises(ValueError):
            self.facade.get_chart_data(lf, "wrong")

    def test_build_report_creates_tree(self):
        lf = self.facade.upload_and_process(make_log_file(), name="t.log")
        report = self.facade.build_report(lf)
        # Перевіряємо що Composite-структура створилась
        self.assertGreater(report.sections.count(), 0)
        roots = report.root_sections
        self.assertGreater(len(roots), 0)
        # У кожної кореневої групи є діти
        for root in roots:
            if root.section_type == "group":
                self.assertGreater(root.children.count(), 0)


# ---------------------------------------------------------------------------
# Composite (GoF-обгортка)
# ---------------------------------------------------------------------------
class CompositeTest(TestCase):
    def test_leaf_count(self):
        leaf = LeafSection("a", "metric", {"value": 1})
        self.assertEqual(leaf.total_leaves(), 1)

    def test_composite_recursive_count(self):
        root = CompositeSection("root")
        sub = CompositeSection("sub")
        sub.add(LeafSection("l1", "metric", {}))
        sub.add(LeafSection("l2", "metric", {}))
        root.add(sub)
        root.add(LeafSection("l3", "metric", {}))
        self.assertEqual(root.total_leaves(), 3)

    def test_leaf_cannot_have_children(self):
        leaf = LeafSection("x", "metric", {})
        with self.assertRaises(TypeError):
            leaf.add(LeafSection("y", "metric", {}))

    def test_build_tree_from_orm(self):
        facade = TrafficAnalyticsFacade()
        lf = facade.upload_and_process(make_log_file(), name="t.log")
        report = facade.build_report(lf)
        tree = build_tree_from_orm(report)
        self.assertGreater(tree.total_leaves(), 0)
        self.assertIn(report.title, tree.render())


# ---------------------------------------------------------------------------
# Observer (signals)
# ---------------------------------------------------------------------------
class ObserverTest(TestCase):
    def test_email_sent_on_processing_done(self):
        facade = TrafficAnalyticsFacade()
        mail.outbox = []
        lf = facade.upload_and_process(make_log_file(), name="t.log")
        # Перевіряємо що сповіщення збережене у БД
        self.assertTrue(
            Notification.objects.filter(log_file=lf, kind="upload_done").exists()
        )
        # Email відправлено
        self.assertGreaterEqual(len(mail.outbox), 1)
        self.assertIn(lf.name, mail.outbox[0].subject)

    def test_anomaly_detected(self):
        # Файл, де 50% запитів — 5xx (вище порогу)
        log = (
            b'1.1.1.1 - - [10/Oct/2023:13:55:36 +0300] "GET / HTTP/1.1" 500 0 "-" "x"\n'
            b'1.1.1.1 - - [10/Oct/2023:13:55:37 +0300] "GET / HTTP/1.1" 200 0 "-" "x"\n'
        )
        facade = TrafficAnalyticsFacade()
        lf = facade.upload_and_process(make_log_file(content=log), name="anomaly.log")
        self.assertTrue(
            Notification.objects.filter(log_file=lf, kind="anomaly").exists()
        )

    def test_no_anomaly_when_clean(self):
        log = b'1.1.1.1 - - [10/Oct/2023:13:55:36 +0300] "GET / HTTP/1.1" 200 0 "-" "x"\n'
        facade = TrafficAnalyticsFacade()
        lf = facade.upload_and_process(make_log_file(content=log), name="clean.log")
        self.assertFalse(
            Notification.objects.filter(log_file=lf, kind="anomaly").exists()
        )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
class ViewsTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user("testuser", password="testpass123")
        self.client.login(username="testuser", password="testpass123")

    def test_dashboard_renders(self):
        response = self.client.get(reverse("analytics:dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_upload_view_get(self):
        response = self.client.get(reverse("analytics:upload"))
        self.assertEqual(response.status_code, 200)

    def test_upload_view_post(self):
        response = self.client.post(
            reverse("analytics:upload"),
            {"name": "test", "file": make_log_file()},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(LogFile.objects.exists())


    def test_chart_data_endpoint(self):
        facade = TrafficAnalyticsFacade()
        lf = facade.upload_and_process(make_log_file(), name="t.log")
        lf.user = self.user
        lf.save(update_fields=["user"])
        response = self.client.get(
            reverse("analytics:chart_data", args=[lf.pk, "status"])
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("labels", data)


# ---------------------------------------------------------------------------
# Pandas service
# ---------------------------------------------------------------------------
class PandasServiceTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user("testuser2", password="testpass123")
        self.client.login(username="testuser2", password="testpass123")
        self.facade = TrafficAnalyticsFacade()
        self.service = PandasAnalyticsService()
        self.lf = self.facade.upload_and_process(make_log_file(), name="t.log")
        self.lf.user = self.user
        self.lf.save(update_fields=["user"])

    def test_to_dataframe_returns_records(self):
        df = self.service.to_dataframe(self.lf)
        self.assertEqual(len(df), 4)
        self.assertIn("status_code", df.columns)
        self.assertIn("timestamp", df.columns)

    def test_resample_1h(self):
        result = self.service.resample_traffic(self.lf, freq="1h")
        self.assertIn("labels", result)
        self.assertIn("data", result)
        self.assertEqual(sum(result["data"]), 4)  # всього 4 запити

    def test_resample_empty(self):
        empty_lf = LogFile.objects.create(name="empty", file=make_log_file())
        result = self.service.resample_traffic(empty_lf)
        self.assertEqual(result["labels"], [])

    def test_rolling_anomalies_finds_spike(self):
        # Лог зі сплеском помилок у короткому вікні
        log = b"".join(
            f'1.1.1.1 - - [10/Oct/2023:13:55:{i:02d} +0300] "GET / HTTP/1.1" 500 0 "-" "x"\n'.encode()
            for i in range(10)
        )
        lf = self.facade.upload_and_process(make_log_file(content=log), name="spike.log")
        result = self.service.rolling_error_rate(lf, window="1min", threshold=0.5)
        self.assertGreater(len(result["spikes"]), 0)

    def test_paths_status_pivot(self):
        pivot = self.service.paths_status_pivot(self.lf)
        self.assertFalse(pivot.empty)
        self.assertIn("total", pivot.columns)

    def test_excel_export_produces_valid_workbook(self):
        data = self.service.export_to_excel(self.lf)
        self.assertGreater(len(data), 1000)  # реальний файл, не пустий
        # Перевіряємо що це справді xlsx (zip із PK у заголовку)
        self.assertEqual(data[:2], b"PK")

    def test_excel_endpoint(self):
        response = self.client.get(
            reverse("analytics:export_excel", args=[self.lf.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_resample_endpoint(self):
        response = self.client.get(
            reverse("analytics:resample", args=[self.lf.pk]) + "?freq=1h"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("labels", response.json())

    # --- Нові методи: aggregate / status_over_time / heatmap / histogram / top_ips ---

    def test_aggregate_by_method(self):
        result = self.service.aggregate(self.lf, group_by="method")
        self.assertIn("GET", result["labels"])
        self.assertEqual(result["filtered_count"], 4)

    def test_aggregate_with_filter(self):
        result = self.service.aggregate(
            self.lf, group_by="method",
            filters={"status_class": "5xx", "method": "all"},
        )
        # У SAMPLE_LOG є один 500 POST — після фільтра має лишитись 1
        self.assertEqual(result["filtered_count"], 1)
        self.assertEqual(sum(result["data"]), 1)

    def test_aggregate_by_status_class(self):
        result = self.service.aggregate(self.lf, group_by="status_class")
        self.assertIn("2xx", result["labels"])
        self.assertIn("4xx", result["labels"])
        self.assertIn("5xx", result["labels"])

    def test_status_over_time_returns_all_classes(self):
        result = self.service.status_over_time(self.lf, freq="1h")
        self.assertIn("series", result)
        self.assertEqual(set(result["series"].keys()), {"2xx", "3xx", "4xx", "5xx"})

    def test_heatmap_shape(self):
        result = self.service.hour_weekday_heatmap(self.lf)
        self.assertEqual(len(result["matrix"]), 7)
        self.assertEqual(len(result["matrix"][0]), 24)
        self.assertEqual(len(result["weekdays"]), 7)

    def test_histogram_returns_bins(self):
        result = self.service.response_size_histogram(self.lf)
        self.assertEqual(len(result["labels"]), len(result["data"]))

    def test_top_ips(self):
        result = self.service.top_ips(self.lf, top=5)
        self.assertGreater(len(result["labels"]), 0)
        # Має бути відсортовано за спаданням
        self.assertEqual(result["data"], sorted(result["data"], reverse=True))

    def test_aggregate_endpoint(self):
        response = self.client.get(
            reverse("analytics:aggregate", args=[self.lf.pk]) + "?group_by=browser"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("labels", data)
        self.assertEqual(data["group_by"], "browser")

    def test_heatmap_endpoint(self):
        response = self.client.get(reverse("analytics:heatmap", args=[self.lf.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("matrix", response.json())

    def test_status_timeseries_endpoint(self):
        response = self.client.get(
            reverse("analytics:status_timeseries", args=[self.lf.pk]) + "?freq=1h"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("series", response.json())
