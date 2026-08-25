"""
سرویس مشترک: وقتی یک نفر در جای دیگری از سیستم (پیگیری افراد ثبت‌نام‌نشده، بدهکاران،
ثبت‌نام مستقیم، ثبت کلاس خصوصی و...) ثبت می‌شود، اگر از قبل در بخش «دانش‌آموزان»
(User با role=student) وجود نداشته باشد، خودکار و بی‌صدا به آن بخش اضافه می‌شود —
با برچسب needs_editing=True (چون اطلاعاتش کامل نیست: بدون تاریخ تولد/جنسیت/آدرس).
اگر از قبل با همان کد ملی یا موبایل در سیستم بود، هیچ کاری انجام نمی‌شود (تکراری
ساخته نمی‌شود).

تطبیق بر اساس اولویت: کد ملی (اگر داده شده) -> موبایل (اگر داده شده). اگر هیچ‌کدام
داده نشده باشد، باز هم یک رکورد ناقص ساخته می‌شود (چون به‌هرحال این فرد باید یک‌جا
در سیستم قابل‌پیگیری باشد) با یک یوزرنیم موقت.
"""
import secrets


def _generate_unique_username(base):
    from .models import User
    base = (base or '').strip()
    if not base:
        base = f"pending-{secrets.token_hex(4)}"
    username = base
    suffix = 2
    while User.objects.filter(username=username).exists():
        username = f'{base}-{suffix}'
        suffix += 1
    return username


def sync_student_from_lead(first_name, last_name, phone='', national_code='', language_level='', gender=''):
    """
    اگر دانش‌آموزی با این کد ملی/موبایل از قبل وجود دارد، همان را برمی‌گرداند (بدون تغییر).
    وگرنه یک User جدید با role='student' و needs_editing=True می‌سازد.
    خروجی: (user, created: bool)
    """
    from .models import User

    national_code = (national_code or '').strip()
    phone = (phone or '').strip()
    first_name = (first_name or '').strip()
    last_name = (last_name or '').strip()

    if not first_name and not last_name:
        return None, False

    existing = None
    if national_code:
        existing = User.objects.filter(role='student', national_code=national_code).first()
    if not existing and phone:
        existing = User.objects.filter(role='student', phone=phone).first()

    if existing:
        return existing, False

    username_base = national_code or phone
    username = _generate_unique_username(username_base)

    user = User(
        username=username,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        national_code=national_code or None,
        gender=gender or '',
        language_level=language_level or '',
        role='student',
        needs_editing=True,
    )
    user.set_unusable_password()
    user.save()
    return user, True
