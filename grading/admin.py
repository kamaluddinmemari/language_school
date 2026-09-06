from django.contrib import admin
from .models import GradeFieldSetting, GradePassingSetting, StudentGrade


@admin.register(GradeFieldSetting)
class GradeFieldSettingAdmin(admin.ModelAdmin):
    list_display = ['age_group', 'field_key', 'title', 'is_active', 'max_score', 'order']
    list_filter = ['age_group', 'is_active']


@admin.register(GradePassingSetting)
class GradePassingSettingAdmin(admin.ModelAdmin):
    list_display = ['age_group', 'passing_score']


@admin.register(StudentGrade)
class StudentGradeAdmin(admin.ModelAdmin):
    list_display = ['student', 'class_slot', 'term', 'total_score', 'is_fail', 'is_finalized']
    list_filter = ['is_finalized', 'is_fail', 'age_group']
    search_fields = ['student__first_name', 'student__last_name', 'student__national_code']
