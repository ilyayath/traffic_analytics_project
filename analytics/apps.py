from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "analytics"
    verbose_name = "Аналітика веб-трафіку"

    def ready(self):
        # Підключаємо Observer-и
        from . import signals  # noqa: F401
