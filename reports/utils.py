import jdatetime
from datetime import date


def parse_jalali_date(value):
    """
    ورودی را به datetime.date میلادی تبدیل می‌کند. دو فرمت پذیرفته می‌شود:
    ۱) ISO میلادی استاندارد 'YYYY-MM-DD' (همان چیزی که JalaliDateInput واقعاً می‌فرستد)
    ۲) رشته‌ی شمسی 'YYYY-MM-DD' با سال زیر ۱۷۰۰ (برای فراخوانی مستقیم API بدون فرم)
    ورودی خالی/نامعتبر -> None
    """
    if not value:
        return None
    value = str(value).strip().replace('/', '-')
    try:
        y, m, d = [int(x) for x in value.split('-')]
    except (ValueError, TypeError):
        return None
    if y > 1700:
        try:
            return date(y, m, d)
        except ValueError:
            return None
    try:
        return jdatetime.date(y, m, d).togregorian()
    except ValueError:
        return None


def get_date_range(request):
    """بازه‌ی تاریخ شمسیِ ارسالی در query params (start, end) را به تاریخ میلادی تبدیل می‌کند"""
    start = parse_jalali_date(request.query_params.get('start'))
    end = parse_jalali_date(request.query_params.get('end'))
    return start, end


def to_jalali_str(dt):
    if not dt:
        return None
    if hasattr(dt, 'hour'):
        return jdatetime.datetime.fromgregorian(datetime=dt).strftime('%Y/%m/%d - %H:%M')
    return jdatetime.date.fromgregorian(date=dt).strftime('%Y/%m/%d')


def format_number(n):
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return n
