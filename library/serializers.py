from rest_framework import serializers
from .models import Book, BookSale


class BookSaleSerializer(serializers.ModelSerializer):
    sold_at_jalali = serializers.ReadOnlyField()
    total_price = serializers.ReadOnlyField()
    sold_by_name = serializers.SerializerMethodField()

    class Meta:
        model = BookSale
        fields = ['id', 'book', 'quantity', 'unit_price_at_sale', 'total_price', 'sold_by_name', 'sold_at', 'sold_at_jalali']

    def get_sold_by_name(self, obj):
        if not obj.sold_by:
            return None
        return f"{obj.sold_by.first_name} {obj.sold_by.last_name}"


class BookSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    stock_value = serializers.ReadOnlyField()
    predicted_need = serializers.ReadOnlyField()
    total_sales_quantity = serializers.ReadOnlyField()
    total_sales_revenue = serializers.ReadOnlyField()
    updated_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = Book
        fields = [
            'id', 'title', 'category', 'category_display',
            'initial_stock', 'current_stock', 'predicted_students', 'unit_price',
            'stock_value', 'predicted_need', 'total_sales_quantity', 'total_sales_revenue',
            'created_at', 'updated_at', 'updated_at_jalali',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def create(self, validated_data):
        # موقع ساخت کتاب جدید، موجودی فعلی همیشه از موجودی اولیه شروع می‌شود
        validated_data['current_stock'] = validated_data.get('initial_stock', 0)
        return super().create(validated_data)


class SellBookSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)
