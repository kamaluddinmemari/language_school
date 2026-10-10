from rest_framework import serializers
from .models import Book, BookSale, BookStockAddition, BookShortcut
from . import forecast as fc


class BookSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    stock_value = serializers.ReadOnlyField()
    predicted_students = serializers.SerializerMethodField()
    predicted_need = serializers.SerializerMethodField()
    forecast_auto = serializers.SerializerMethodField()
    forecast_levels_effective = serializers.SerializerMethodField()
    forecast_levels_default = serializers.SerializerMethodField()
    forecast_term_id = serializers.SerializerMethodField()
    forecast_term_title = serializers.SerializerMethodField()
    forecast_text = serializers.SerializerMethodField()
    predicted_is_manual = serializers.SerializerMethodField()
    order_needed = serializers.SerializerMethodField()
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
            'predicted_override', 'extra_copies', 'forecast_levels', 'forecast_levels_effective', 'forecast_levels_default',
            'forecast_auto', 'forecast_term_id', 'forecast_term_title', 'forecast_text',
            'predicted_is_manual', 'order_needed',
            'unit_price', 'purchase_price', 'stock_value',
            'total_sales_quantity', 'total_sales_revenue',
            'total_stock_added', 'total_units_acquired', 'total_cost', 'cost_of_goods_sold', 'total_profit',
            'created_at', 'updated_at', 'updated_at_jalali',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def _fc(self, obj):
        # یک‌بار برای کل درخواست ساخته می‌شود (context مشترک بین همه‌ی کتاب‌ها)
        ctx = self.context.get('forecast')
        if ctx is None:
            request = self.context.get('request')
            term_id = request.query_params.get('forecast_term') if request is not None else None
            ctx = fc.build_context(term_id)
            self.context['forecast'] = ctx
        cache = ctx.setdefault('_books', {})
        if obj.pk not in cache or cache[obj.pk][2] != (obj.forecast_levels, obj.title):
            auto, levels = fc.forecast_for_book(obj, ctx)
            cache[obj.pk] = (auto, levels, (obj.forecast_levels, obj.title))
        return ctx, cache[obj.pk][0], cache[obj.pk][1]

    def _effective(self, obj):
        _ctx, auto, _levels = self._fc(obj)
        if obj.predicted_override is not None:
            return obj.predicted_override
        return auto if auto is not None else 0

    def get_predicted_students(self, obj):
        return self._effective(obj)

    def get_order_needed(self, obj):
        return max(0, self._effective(obj) + int(obj.extra_copies or 0) - int(obj.current_stock or 0))

    def get_predicted_need(self, obj):
        return self.get_order_needed(obj)

    def get_forecast_auto(self, obj):
        return self._fc(obj)[1]

    def get_forecast_levels_effective(self, obj):
        return self._fc(obj)[2]

    def get_forecast_levels_default(self, obj):
        return fc.default_levels_for_title(obj.title)

    def get_forecast_term_id(self, obj):
        term = self._fc(obj)[0].get('term')
        return term.id if term else None

    def get_forecast_term_title(self, obj):
        term = self._fc(obj)[0].get('term')
        return term.title if term else ''

    def get_predicted_is_manual(self, obj):
        return obj.predicted_override is not None

    def get_forecast_text(self, obj):
        ctx, auto, levels = self._fc(obj)
        term = ctx.get('term')
        if auto is None or not term:
            return 'برای این کتاب سطحی برای پیش‌بینی خودکار تعریف نشده است؛ عدد را دستی وارد کنید.'
        if ctx.get('mode') == 'deposit':
            return f"طبق بیعانه‌های ثبت‌شده ({term.title}، سطح {'، '.join(levels)})، {auto} نفر زبان‌آموز ترم بعد داریم"
        return f"طبق محاسبات {term.title} (سطح {'، '.join(levels)})، {auto} نفر زبان‌آموز ترم بعد داریم"

    def validate_forecast_levels(self, value):
        return ','.join(fc.parse_levels(value))


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


class BookShortcutSerializer(serializers.ModelSerializer):
    book_title = serializers.CharField(source='book.title', read_only=True)
    book_category = serializers.CharField(source='book.category', read_only=True)

    class Meta:
        model = BookShortcut
        fields = ['id', 'book', 'book_title', 'book_category', 'label', 'default_quantity', 'hotkey', 'order']

    def validate_default_quantity(self, value):
        if value < 1:
            raise serializers.ValidationError('تعداد باید حداقل ۱ باشد')
        return value

    def validate_hotkey(self, value):
        import re
        value = (value or '').strip()
        if not value:
            return ''
        part = r'(Alt\+)?(Shift\+)?(Key[A-Z]|Digit[0-9]|Numpad[0-9]|F([1-4]|[6-9]|10))'
        if not re.fullmatch(part + '(,' + part + ')?', value):
            raise serializers.ValidationError('کلید میانبر نامعتبر است')
        clash = BookShortcut.objects.filter(hotkey=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError('این کلید برای میانبر دیگری استفاده شده است')
        return value
