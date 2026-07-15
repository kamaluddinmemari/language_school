from django.contrib import admin
from .models import NewLead, UnregisteredStudent, UnregisteredStudentFollowup, Debtor, DebtorFollowup, DiscountedPerson


@admin.register(NewLead)
class NewLeadAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'phone', 'status', 'created_at')
    list_filter = ('status',)


@admin.register(UnregisteredStudent)
class UnregisteredStudentAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'class_level', 'status', 'created_at')
    list_filter = ('status',)


@admin.register(Debtor)
class DebtorAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'debt_amount', 'status', 'created_at')
    list_filter = ('status',)


admin.site.register(UnregisteredStudentFollowup)
admin.site.register(DebtorFollowup)


@admin.register(DiscountedPerson)
class DiscountedPersonAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'national_code', 'discount_percent', 'valid_until', 'created_at')
