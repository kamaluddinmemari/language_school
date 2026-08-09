"""
منبع واحد (single source of truth) برای لیست سطح‌های تعیین سطح.
از این به بعد این لیست دیتابیس‌محور است (از جدول StandardLevel خوانده می‌شود) — نه ثابت در کد؛
تعریف/حذف سطح از پنل («تعریف سطوح استاندارد») بلافاصله همه‌جا (تعیین‌سطح، تعریف کلاس، شهریه) اثر می‌کند.
هم مدل‌ها (به‌صورت callable choices) و هم API از همین توابع می‌خوانند.
"""

AGE_GROUP_LABELS = {'kids': 'کودک', 'teen': 'نوجوان', 'adult': 'بزرگسال'}


def get_all_level_choices():
    """برای استفاده به‌عنوان choices روی فیلدهای مدل (callable choices) — هر بار که لازم باشد دوباره از دیتابیس خوانده می‌شود"""
    from .models import StandardLevel
    from django.db import DatabaseError
    try:
        return [(lvl.code, lvl.code) for lvl in StandardLevel.objects.all().order_by('age_group', 'order', 'code')]
    except DatabaseError:
        # قبل از اجرای اولین migrate، جدول هنوز وجود ندارد — چون همین import در ابتدای اجرای
        # هر دستور manage.py (از جمله خودِ makemigrations/migrate) پیش می‌آید، نباید کرش کند
        return []


def get_levels_by_age_group():
    """برای پر کردن select های فرم پنل مدیر آموزش، گروه‌بندی‌شده بر اساس گروه سنی"""
    from .models import StandardLevel
    from django.db import DatabaseError
    result = {'kids': [], 'teen': [], 'adult': []}
    try:
        for lvl in StandardLevel.objects.all().order_by('age_group', 'order', 'code'):
            result.setdefault(lvl.age_group, []).append(lvl.code)
    except DatabaseError:
        pass
    return result


def __getattr__(name):
    """
    سازگاری با کدهای قدیمی که مستقیم `LEVELS_BY_AGE_GROUP` یا `ALL_LEVEL_CHOICES` را
    از این فایل ایمپورت می‌کنند (مثل `from .levels import LEVELS_BY_AGE_GROUP`) — به‌جای
    مقدار ثابت، هر بار که ایمپورت می‌شود مقدار تازه از دیتابیس برمی‌گرداند (PEP 562).
    """
    if name == 'LEVELS_BY_AGE_GROUP':
        return get_levels_by_age_group()
    if name == 'ALL_LEVEL_CHOICES':
        return get_all_level_choices()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
