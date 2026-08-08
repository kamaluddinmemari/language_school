from django.db import models
from django.utils import timezone
from accounts.models import User
import jdatetime


def _jalali(dt):
    if not dt:
        return None
    local_dt = timezone.localtime(dt)
    return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')


class Book(models.Model):
    """
    یک عنوان کتاب در کتابخانه‌ی آموزشگاه، به‌همراه موجودی، قیمت، و پیش‌بینی نیاز آینده.
    موجودی اولیه (initial_stock) فقط برای سابقه/گزارش نگه داشته می‌شود؛ موجودی زنده که با هر
    فروش کم می‌شود current_stock است.
    """

    class Category(models.TextChoices):
        KIDS = 'kids', 'کودکان (Supermind)'
        TEEN = 'teen', 'نوجوانان (Project)'
        ADULT = 'adult', 'بزرگسال (Evolve)'
        OXFORD = 'oxford', 'آکسفورد'
        OTHER = 'other', 'سایر'

    title = models.CharField(max_length=150, unique=True)
    category = models.CharField(max_length=10, choices=Category.choices, default=Category.OTHER)
    initial_stock = models.PositiveIntegerField(default=0, help_text='موجودی اولیه‌ی ثبت‌شده (سابقه)')
    current_stock = models.IntegerField(default=0, help_text='موجودی فعلی — با فروش کم می‌شود')
    predicted_students = models.PositiveIntegerField(default=0, help_text='پیش‌بینی تعداد زبان‌آموزان نیازمند این کتاب در آینده')
    unit_price = models.PositiveIntegerField(default=0, help_text='قیمت فروش هر جلد (تومان)')
    purchase_price = models.PositiveIntegerField(default=0, help_text='قیمت خرید هر جلد (تومان) — برای محاسبه‌ی هزینه/درآمد/سود')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'title']

    @property
    def stock_value(self):
        """قیمت فروشِ کل موجودی فعلی"""
        return self.unit_price * self.current_stock

    @property
    def predicted_need(self):
        """
        تعداد باقی‌مانده از پیش‌بینیِ نیاز — با هر فروش (یعنی هر زبان‌آموزی که کتاب رو گرفته)
        این عدد کم می‌شه، نه با کم‌شدن موجودی زیاد بشه. یعنی: پیش‌بینی کل نیاز منهای تعداد
        فروخته‌شده تا الان؛ وقتی همه‌ی نیاز پوشش داده شد، صفر می‌مونه.
        """
        return max(0, self.predicted_students - self.total_sales_quantity)

    @property
    def total_sales_quantity(self):
        return sum(s.quantity for s in self.sales.all())

    @property
    def total_sales_revenue(self):
        return sum(s.total_price for s in self.sales.all())

    @property
    def total_stock_added(self):
        """جمع همه‌ی افزایش‌های موجودی که بعد از ثبت اولیه با دکمه‌ی «+ افزودن» زده شده"""
        return sum(a.quantity for a in self.stock_additions.all())

    @property
    def total_units_acquired(self):
        """کل جلدهایی که تا الان وارد موجودی این کتاب شدن (اولیه + همه‌ی افزایش‌ها)"""
        return self.initial_stock + self.total_stock_added

    @property
    def total_cost(self):
        """هزینه‌ی کل خرید — بر اساس همه‌ی جلدهایی که تا الان خریداری و وارد موجودی شدن"""
        return self.purchase_price * self.total_units_acquired

    @property
    def cost_of_goods_sold(self):
        """هزینه‌ی خریدِ متناظر با همون تعدادی که فروخته شده (مبنای محاسبه‌ی سود واقعی)"""
        return self.purchase_price * self.total_sales_quantity

    @property
    def total_profit(self):
        """سود خالص = درآمد فروش منهای هزینه‌ی خریدِ همون تعداد فروخته‌شده"""
        return self.total_sales_revenue - self.cost_of_goods_sold

    @property
    def updated_at_jalali(self):
        return _jalali(self.updated_at)

    def __str__(self):
        return f"{self.title} (موجودی: {self.current_stock})"


class BookStockAddition(models.Model):
    """هر بار که با دکمه‌ی «+ افزودن» به موجودی یک کتاب اضافه می‌شود، یک رکورد اینجا ثبت می‌شود"""
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='stock_additions')
    quantity = models.PositiveIntegerField()
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='book_stock_additions')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-added_at']

    @property
    def added_at_jalali(self):
        return _jalali(self.added_at)

    def __str__(self):
        return f"+{self.quantity} جلد {self.book.title}"


class BookSale(models.Model):
    """یک تراکنش فروش کتاب — با هر ثبت، موجودی کتاب مربوطه کم می‌شود"""

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='sales')
    quantity = models.PositiveIntegerField(default=1)
    unit_price_at_sale = models.PositiveIntegerField()
    sold_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='book_sales')
    sold_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sold_at']

    @property
    def total_price(self):
        return self.unit_price_at_sale * self.quantity

    @property
    def sold_at_jalali(self):
        return _jalali(self.sold_at)

    def __str__(self):
        return f"فروش {self.quantity} جلد {self.book.title}"
