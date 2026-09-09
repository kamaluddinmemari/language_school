from django.contrib import admin

from .models import OfficeQrToken


@admin.register(OfficeQrToken)
class OfficeQrTokenAdmin(admin.ModelAdmin):
    list_display = ('id', 'token', 'is_active', 'created_at', 'updated_at')
    list_filter = ('is_active',)
    readonly_fields = ('token', 'created_at', 'updated_at')
