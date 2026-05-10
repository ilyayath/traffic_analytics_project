from django.urls import path
from . import views

app_name = "analytics"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("upload/", views.upload_log, name="upload"),
    path("logs/", views.logfile_list, name="logfile_list"),
    path("logs/<int:pk>/", views.logfile_detail, name="logfile_detail"),
    path("logs/<int:pk>/build-report/", views.build_report, name="build_report"),
    path("reports/<int:pk>/", views.report_detail, name="report_detail"),
    path("logs/<int:pk>/chart/<str:kind>/", views.chart_data, name="chart_data"),
    path("logs/<int:pk>/excel/", views.export_excel, name="export_excel"),
    path("logs/<int:pk>/resample/", views.resample_data, name="resample"),
    path("logs/<int:pk>/anomalies/", views.rolling_anomalies, name="anomalies"),
    path("logs/<int:pk>/aggregate/", views.aggregate_data, name="aggregate"),
    path("logs/<int:pk>/status-timeseries/", views.status_timeseries, name="status_timeseries"),
    path("logs/<int:pk>/heatmap/", views.heatmap_data, name="heatmap"),
    path("logs/<int:pk>/histogram/", views.histogram_data, name="histogram"),
    path("logs/<int:pk>/top-ips/", views.top_ips_data, name="top_ips"),
    path("logs/<int:pk>/ai-analyze/", views.ai_analyze, name="ai_analyze"),
    path("notifications/", views.notification_list, name="notification_list"),
]
