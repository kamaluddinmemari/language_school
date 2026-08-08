from rest_framework import serializers
from .models import Book, BookSale, BookStockAddition


class BookSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    stock_value = serializers.ReadOnlyField()
    predicted_need = serializers.ReadOnlyField()
    total_sales_quantity = serializers.ReadOnlyField()
    total_sales_revenue = serializers.ReadOnlyField()
    total_stock_added = serializers.ReadOnlyField()
    total_units_acquired = serializers.ReadOnlyField()
    total_cost = serializers.ReadOnlyField()
    cost_of_goods_sold = serializers.ReadOnlyField()
    total_profit = serializers.ReadOnlyField()
    updated_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = Book
        fields = [
            'id', 'title', 'category', 'category_display',
            'initial_stock', 'current_stock', 'predicted_students', 'predicted_need',
            'unit_price', 'purchase_price', 'stock_value',
            'total_sales_quantity', 'total_sales_revenue',
            'total_stock_added', 'total_units_acquired', 'total_cost', 'cost_of_goods_sold', 'total_profit',
            'created_at', 'updated_at', 'updated_at_jalali',
        ]
        read_only_fields = ['created_at', 'updated_at']


class BookSaleSerializer(serializers.ModelSerializer):
    sold_at_jalali = serializers.ReadOnlyField()
    total_price = serializers.ReadOnlyField()
    sold_by_name = serializers.SerializerMethodField()

    class Meta:
        model = BookSale
        fields = ['id', 'book', 'quantity', 'unit_price_at_sale', 'total_price', 'sold_by', 'sold_by_name', 'sold_at', 'sold_at_jalali']
        read_only_fields = ['unit_price_at_sale', 'sold_by', 'sold_at']

    def get_sold_by_name(self, obj):
        return f"{obj.sold_by.first_name} {obj.sold_by.last_name}" if obj.sold_by else '—'


class SellBookSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)


class AddBookStockSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)


class BookStockAdditionSerializer(serializers.ModelSerializer):
    added_at_jalali = serializers.ReadOnlyField()
    added_by_name = serializers.SerializerMethodField()

    class Meta:
        model = BookStockAddition
        fields = ['id', 'book', 'quantity', 'added_by', 'added_by_name', 'added_at', 'added_at_jalali']
        read_only_fields = ['added_by', 'added_at']

    def get_added_by_name(self, obj):
        return f"{obj.added_by.first_name} {obj.added_by.last_name}" if obj.added_by else '—'
