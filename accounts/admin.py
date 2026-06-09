from django.contrib import admin
from .models import User, ClassRequest, OTPCode, PriceSetting


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['username', 'get_full_name', 'role', 'phone', 'teacher_level']
    list_filter = ['role']
    search_fields = ['username', 'first_name', 'last_name', 'phone']


@admin.register(ClassRequest)
class ClassRequestAdmin(admin.ModelAdmin):
    list_display = ['student', 'class_type', 'language_level', 'status', 'payment_status', 'total_price', 'created_at']
    list_filter = ['status', 'payment_status', 'class_type']
    search_fields = ['student__username', 'language_level']


@admin.register(PriceSetting)
class PriceSettingAdmin(admin.ModelAdmin):
    list_display = ['one_hour_price', 'one_half_hour_price', 'teacher_share_percent', 'school_share_percent', 'updated_at']


@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = ['user', 'code', 'purpose', 'is_used', 'created_at']