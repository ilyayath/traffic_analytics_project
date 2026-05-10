"""
Views — тонкий шар, який делегує всю бізнес-логіку фасаду.
Це канонічна перевага Facade: views не знають про парсери, агрегацію тощо.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .facades import TrafficAnalyticsFacade
from .models import LogFile, Notification, Report


facade = TrafficAnalyticsFacade()


class UploadForm(forms.Form):
    name = forms.CharField(max_length=255, label="Назва", required=False)
    file = forms.FileField(label="Лог-файл")


@login_required
def dashboard(request):
    """Головна сторінка — список файлів + останні сповіщення."""
    return render(request, "analytics/dashboard.html", {
        "log_files": LogFile.objects.all()[:10],
        "notifications": Notification.objects.all()[:5],
        "total_files": LogFile.objects.count(),
        "total_reports": Report.objects.count(),
    })


@require_http_methods(["GET", "POST"])
@login_required
@require_http_methods(["GET", "POST"])
def upload_log(request):
    if request.method == "POST":
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            f = form.cleaned_data["file"]
            name = form.cleaned_data["name"] or f.name
            try:
                log_file = facade.upload_and_process(f, name=name)
                messages.success(
                    request,
                    f"Файл '{log_file.name}' оброблено: "
                    f"{log_file.parsed_lines}/{log_file.total_lines} рядків.",
                )
                return redirect(log_file.get_absolute_url())
            except Exception as exc:  # noqa: BLE001
                messages.error(request, f"Помилка обробки: {exc}")
    else:
        form = UploadForm()
    return render(request, "analytics/upload.html", {"form": form})


@login_required
def logfile_list(request):
    return render(request, "analytics/logfile_list.html", {
        "log_files": LogFile.objects.all(),
    })


@login_required
def logfile_detail(request, pk):
    log_file = get_object_or_404(LogFile, pk=pk)
    overview = facade.get_overview(log_file)
    return render(request, "analytics/logfile_detail.html", {
        "log_file": log_file,
        "overview": overview,
        "reports": log_file.reports.all(),
    })


@require_http_methods(["POST"])
@login_required
@require_http_methods(["POST"])
def build_report(request, pk):
    log_file = get_object_or_404(LogFile, pk=pk)
    report = facade.build_report(log_file)
    messages.success(request, f"Створено звіт: {report.title}")
    return redirect(report.get_absolute_url())


@login_required
def report_detail(request, pk):
    report = get_object_or_404(Report, pk=pk)
    return render(request, "analytics/report_detail.html", {
        "report": report,
        "root_sections": report.root_sections,
    })


@login_required
def chart_data(request, pk, kind):
    """JSON-endpoint для динамічного оновлення графіків."""
    log_file = get_object_or_404(LogFile, pk=pk)
    try:
        data = facade.get_chart_data(log_file, kind)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(data)


@login_required
def notification_list(request):
    return render(request, "analytics/notification_list.html", {
        "notifications": Notification.objects.all(),
    })


# -------------------- pandas-сервіси --------------------
def _extract_filters(request) -> dict:
    """Витягає фільтри з GET-параметрів."""
    return {
        "status_class": request.GET.get("status_class", "all"),
        "method": request.GET.get("method", "all"),
        "from": request.GET.get("from") or None,
        "to": request.GET.get("to") or None,
        "path_contains": request.GET.get("path_contains") or None,
    }


@login_required
def export_excel(request, pk):
    """Завантажити Excel-звіт."""
    log_file = get_object_or_404(LogFile, pk=pk)
    data = facade.export_excel(log_file)
    response = HttpResponse(
        data,
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    safe_name = log_file.name.replace(" ", "_").rsplit(".", 1)[0]
    response["Content-Disposition"] = (
        f'attachment; filename="report_{safe_name}.xlsx"'
    )
    return response


def resample_data(request, pk):
    """JSON-ендпоінт для time-series resample. ?freq=1h"""
    log_file = get_object_or_404(LogFile, pk=pk)
    freq = request.GET.get("freq", "1h")
    return JsonResponse(
        facade.resample_traffic(log_file, freq=freq, filters=_extract_filters(request))
    )


def rolling_anomalies(request, pk):
    """JSON-ендпоінт для rolling anomaly detection."""
    log_file = get_object_or_404(LogFile, pk=pk)
    window = request.GET.get("window", "10min")
    try:
        threshold = float(request.GET.get("threshold", "0.1"))
    except ValueError:
        threshold = 0.1
    return JsonResponse(
        facade.rolling_anomalies(log_file, window=window, threshold=threshold)
    )


def aggregate_data(request, pk):
    """Універсальна агрегація з фільтрами. ?group_by=browser&status_class=2xx&method=GET"""
    log_file = get_object_or_404(LogFile, pk=pk)
    group_by = request.GET.get("group_by", "method")
    return JsonResponse(
        facade.aggregate(log_file, group_by=group_by, filters=_extract_filters(request))
    )


def status_timeseries(request, pk):
    log_file = get_object_or_404(LogFile, pk=pk)
    freq = request.GET.get("freq", "1h")
    return JsonResponse(
        facade.status_over_time(log_file, freq=freq, filters=_extract_filters(request))
    )


def heatmap_data(request, pk):
    log_file = get_object_or_404(LogFile, pk=pk)
    return JsonResponse(
        facade.hour_weekday_heatmap(log_file, filters=_extract_filters(request))
    )


def histogram_data(request, pk):
    log_file = get_object_or_404(LogFile, pk=pk)
    return JsonResponse(
        facade.response_size_histogram(log_file, filters=_extract_filters(request))
    )


def top_ips_data(request, pk):
    log_file = get_object_or_404(LogFile, pk=pk)
    return JsonResponse(
        facade.top_ips(log_file, filters=_extract_filters(request))
    )


@login_required
def ai_analyze(request, pk):
    """Ендпоінт для AI-аналізу лог-файлу."""
    log_file = get_object_or_404(LogFile, pk=pk)
    analysis = facade.ai_analyze(log_file)
    return JsonResponse({"analysis": analysis})
