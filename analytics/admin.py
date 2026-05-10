from django.contrib import admin
from .models import LogFile, LogEntry, Report, ReportSection, Notification


@admin.register(LogFile)
class LogFileAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "uploaded_at", "parsed_lines", "total_lines")
    list_filter = ("status",)
    search_fields = ("name",)


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "ip_address", "method", "path", "status_code")
    list_filter = ("status_code", "method", "device_type", "browser")
    search_fields = ("ip_address", "path")
    date_hierarchy = "timestamp"


class ReportSectionInline(admin.TabularInline):
    model = ReportSection
    extra = 0


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("title", "log_file", "created_at")
    inlines = [ReportSectionInline]


@admin.register(ReportSection)
class ReportSectionAdmin(admin.ModelAdmin):
    list_display = ("title", "report", "section_type", "parent", "position")
    list_filter = ("section_type",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("kind", "subject", "created_at", "log_file")
    list_filter = ("kind",)
    readonly_fields = ("created_at",)
