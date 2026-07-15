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
    unit_price = models.PositiveIntegerField(default=0, help_text='قیمت هر جلد (تومان)')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'title']

    @property
    def stock_value(self):
        """قیمت کل موجودی فعلی"""
        return self.unit_price * self.current_stock

    @property
    def predicted_need(self):
        """پیش‌بینی تعداد کتاب مورد نیاز اضافه — اگر موجودی از پیش‌بینی تعداد زبان‌آموزان کمتر باشد"""
        return max(0, self.predicted_students - self.current_stock)

    @property
    def total_sales_quantity(self):
        return sum(s.quantity for s in self.sales.all())

    @property
    def total_sales_revenue(self):
        return sum(s.total_price for s in self.sales.all())

    @property
    def updated_at_jalali(self):
        return _jalali(self.updated_at)

    def __str__(self):
        return f"{self.title} (موجودی: {self.current_stock})"


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
