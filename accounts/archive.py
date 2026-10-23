"""
حفظ سوابق هنگام حذف دانش‌آموز.

حذف یک دانش‌آموز (از هر مسیری: پنل، حذف گروهی، ادمین جنگو…) نباید سوابق «کلاس‌های خصوصی/جبرانی» و «ریزشی‌ها» را پاک کند.
این تابع به‌عنوان `on_delete` روی آن کلیدهای خارجی گذاشته می‌شود: به‌جای CASCADE، سوابق به یک «پروندهٔ بایگانی‌شده»
(نقش `archived`، غیرفعال، بدون رمز، پنهان از همهٔ لیست‌هایی که role='student' را فیلتر می‌کنند) منتقل می‌شوند که نام،
موبایل و کد ملیِ دانش‌آموز را برای نمایش در همان لیست‌ها نگه می‌دارد. (بدهکاران و ثبت‌نام‌نشده‌ها خودشان به حساب کاربری وابسته نیستند.)
"""
from collections import defaultdict

from django.db import models


def _archived_user(User, original, using):
    username = f'archived_{original.pk}'
    placeholder = User.objects.using(using).filter(username=username).first()
    if placeholder:
        return placeholder
    placeholder = User(
        username=username, role=User.Role.ARCHIVED, is_active=False,
        first_name=original.first_name, last_name=original.last_name, father_name=original.father_name,
        phone=original.phone, phone2=original.phone2, gender=original.gender, language_level=original.language_level,
        birth_date=original.birth_date, national_code=None,  # کد ملی یکتاست؛ نسخهٔ نمایشی در archived_national_code می‌ماند
        archived_national_code=original.national_code or '',
    )
    placeholder.set_unusable_password()
    placeholder.save(using=using)
    return placeholder


def keep_as_archived_student(collector, field, sub_objs, using):
    User = field.remote_field.model
    groups = defaultdict(list)
    for obj in sub_objs:
        groups[getattr(obj, field.attname)].append(obj)
    for student_id, objs in groups.items():
        original = User.objects.using(using).filter(pk=student_id).first()
        if original is None or original.role == User.Role.ARCHIVED:
            models.CASCADE(collector, field, objs, using)  # خودِ پروندهٔ بایگانی حذف می‌شود: رفتار عادی
            continue
        collector.add_field_update(field, _archived_user(User, original, using), objs)


def _obj_term_is_current(obj):
    """ترم جاری = ترمی که هنوز تمام نشده (در جریان یا آینده/پیش‌ثبت‌نام)؛ از ترم کلاس (یا فیلد term خودِ رکورد) تشخیص داده می‌شود."""
    from django.utils import timezone
    term = getattr(obj, 'term', None) if hasattr(obj, 'term') else None
    if term is None:
        slot = getattr(obj, 'class_slot', None)
        term = getattr(slot, 'term', None) if slot is not None else None
    end_date = getattr(term, 'end_date', None) if term is not None else None
    return bool(end_date and end_date >= timezone.localdate())


def keep_current_term_records(collector, field, sub_objs, using):
    """
    ثبت‌نام/حضور‌وغیاب/نمرهٔ «ترم جاری» (و ترم‌های آینده) با حذف دانش‌آموز پاک نمی‌شود و به پروندهٔ بایگانی‌شده منتقل می‌شود
    تا لیست کلاسی و حضور‌وغیاب آن ترم سالم بماند؛ رکوردهای ترم‌های تمام‌شده طبق رفتار قبلی (CASCADE) حذف می‌شوند.
    """
    keep, drop = [], []
    for obj in sub_objs:
        (keep if _obj_term_is_current(obj) else drop).append(obj)
    if drop:
        models.CASCADE(collector, field, drop, using)
    if keep:
        keep_as_archived_student(collector, field, keep, using)
