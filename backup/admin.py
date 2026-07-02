from django.contrib import admin

from .models import BackupRecord, PiholeConfig


@admin.register(PiholeConfig)
class PiholeConfigAdmin(admin.ModelAdmin):
    list_display = ["name", "backup_frequency", "is_active", "last_successful_backup"]
    list_filter = ["is_active", "backup_frequency"]
    readonly_fields = ["last_successful_backup", "last_backup_error", "created_at", "updated_at"]


@admin.register(BackupRecord)
class BackupRecordAdmin(admin.ModelAdmin):
    list_display = ["filename", "config", "status", "file_size", "is_manual", "created_at"]
    list_filter = ["status", "is_manual", "config"]
    readonly_fields = ["file_path", "checksum", "created_at"]
    search_fields = ["filename"]
