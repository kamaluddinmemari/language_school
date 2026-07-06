from django.contrib import admin
from .models import LevelTest, LevelTestPriceSetting


@admin.register(LevelTestPriceSetting)
class LevelTestPriceSettingAdmin(admin.ModelAdmin):
    list_display = ('price', 'updated_at')


@admin.register(LevelTest)
class LevelTestAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'national_code', 'phone', 'status', 'age_group', 'level', 'display_evaluator_name')
    list_filter = ('status', 'age_group')
    search_fields = ('first_name', 'last_name', 'phone', 'national_code')
