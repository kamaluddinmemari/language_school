from django.contrib import admin
from .models import Book, BookSale


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'current_stock', 'unit_price', 'predicted_students')
    list_filter = ('category',)


@admin.register(BookSale)
class BookSaleAdmin(admin.ModelAdmin):
    list_display = ('book', 'quantity', 'unit_price_at_sale', 'sold_by', 'sold_at')
