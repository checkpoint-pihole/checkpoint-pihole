from django.apps import AppConfig


class BackupConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "backup"
    verbose_name = "Checkpoint Pi-hole"
