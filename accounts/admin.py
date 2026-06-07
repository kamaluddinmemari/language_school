from django.contrib import admin


from django.contrib import admin
from .models import User, ClassRequest


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['username', 'full_name', 'role', 'phone']
    list_filter = ['role']
    search_fields = ['username', 'first_name', 'last_name', 'phone']

    def full_name(self, obj):
        return obj.get_full_name()


@admin.register(ClassRequest)
class ClassRequestAdmin(admin.ModelAdmin):
    list_display = ['student', 'language_level', 'status', 'payment_status', 'created_at']
    list_filter = ['status', 'payment_status']
    search_fields = ['student__username', 'language']
# Register your models here.
