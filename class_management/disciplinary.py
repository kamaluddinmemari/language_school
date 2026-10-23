"""
هشدار ثبت‌نام: اگر یک فرد دو (یا بیشتر) فرم تعهد انضباطی در بایگانی «تعهدنامه» داشته باشد، یا بدهکار قبلی باشد، یا در لیست «ثبت‌نام‌نشده‌ها» باشد،
در هر مسیرِ ثبت‌نام در کلاس (مدیریت کلاس‌ها، اکسل، پیگیری ثبت‌نام‌نشده‌ها/بدهکاران، استخراج ریزشی) قبل از
ثبت یک هشدار (HTTP 409 با code=disciplinary_warning) برمی‌گردد. پنل با تأیید کاربر همان درخواست را با
پارامتر `?confirm_disciplinary=1` دوباره می‌فرستد (api-client.js) و ثبت‌نام انجام می‌شود.
"""
import re

from rest_framework import status
from rest_framework.response import Response

DISCIPLINARY_WARNING_THRESHOLD = 2
_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def _digits(value):
    return re.sub(r'\D', '', str(value or '').translate(_DIGITS))


def _phone(value):
    phone = _digits(value)
    if phone.startswith('0098'):
        return '0' + phone[4:]
    if phone.startswith('98') and len(phone) == 12:
        return '0' + phone[2:]
    return phone


def _full_name(first, last):
    name = f"{first or ''} {last or ''}".replace('ي', 'ی').replace('ك', 'ک').casefold()
    return re.sub(r'\s+', ' ', name).strip()


def _same_person(student, data):
    """همان منطق تطبیق بایگانی فرم‌ها: کد ملی، در غیر این صورت موبایل، در غیر این صورت نام کامل."""
    data = data if isinstance(data, dict) else {}
    code, row_code = _digits(student.national_code), _digits(data.get('national_code'))
    if code and row_code:
        return code == row_code
    phone, row_phone = _phone(student.phone), _phone(data.get('phone'))
    if phone and row_phone:
        return phone == row_phone
    name = _full_name(student.first_name, student.last_name)
    return bool(name and name == _full_name(data.get('first_name'), data.get('last_name')))


def disciplinary_commitment_count(student):
    from accounts.models import FormArchive
    return sum(
        1 for row in FormArchive.objects.filter(document_type='disciplinary').only('data').iterator()
        if _same_person(student, row.data)
    )


def _confirmed(request):
    header = str(request.META.get('HTTP_X_CONFIRM_DISCIPLINARY', '')).lower()
    value = str(request.data.get('confirm_disciplinary', '') if hasattr(request.data, 'get') else '').lower()
    query = str(request.query_params.get('confirm_disciplinary', '')).lower()
    return any(item in ('1', 'true', 'yes') for item in (header, value, query))


def _norm_name(first, last):
    return _full_name(first, last)


def _pending_debts(student):
    """بدهی‌های در حال پیگیریِ این فرد (بدهکاران قبلی). ردیف‌های «منتظر ثبت‌نام»ِ انتقالی بدهی واقعی نیستند و حساب نمی‌شوند."""
    from leads.models import Debtor
    name = _norm_name(student.first_name, student.last_name)
    phone = _phone(student.phone)
    rows = []
    for debtor in Debtor.objects.filter(status=Debtor.Status.PENDING, awaiting_registration=False).iterator():
        if debtor.student_id:
            matched = debtor.student_id == student.id
        else:
            debtor_phone = _phone(debtor.phone)
            matched = bool(name) and _norm_name(debtor.first_name, debtor.last_name) == name and (
                debtor_phone == phone if (debtor_phone and phone) else True
            )
        if matched:
            rows.append(debtor)
    return rows


def _tracking_unregistered(student):
    """ردیف‌های «ثبت‌نام‌نشده‌ها» (در حال پیگیری) که مربوط به این فرد است."""
    from leads.models import UnregisteredStudent
    name = _norm_name(student.first_name, student.last_name)
    code = _digits(student.national_code)
    phone = _phone(student.phone)
    rows = []
    for item in UnregisteredStudent.objects.filter(status=UnregisteredStudent.Status.TRACKING).select_related('term').iterator():
        item_code, item_phone = _digits(item.national_code), _phone(item.phone)
        if code and item_code:
            matched = code == item_code
        else:
            matched = bool(name) and _norm_name(item.first_name, item.last_name) == name and (
                item_phone == phone if (item_phone and phone) else True
            )
        if matched:
            rows.append(item)
    return rows


def person_reasons(student, skip_debtor=False, skip_unregistered=False, skip_disciplinary=False):
    """دلایل هشدار برای یک فرد (آبجکت دارای first_name/last_name/national_code/phone و id)."""
    reasons = []
    count = 0
    if not skip_disciplinary:
        count = disciplinary_commitment_count(student)
        if count >= DISCIPLINARY_WARNING_THRESHOLD:
            reasons.append({'type': 'disciplinary', 'text': f'{count} تعهدنامه انضباطی دارد'})
    if not skip_debtor:
        debts = _pending_debts(student)
        if debts:
            total = sum(int(d.debt_amount or 0) for d in debts)
            reasons.append({'type': 'debtor', 'text': 'بدهکار از قبل است' + (f' (مبلغ بدهی: {total:,} تومان)' if total else '')})
    if not skip_unregistered:
        tracked = _tracking_unregistered(student)
        if tracked:
            terms = '، '.join(sorted({item.term.title for item in tracked if item.term_id}))
            reasons.append({'type': 'unregistered', 'text': 'جزو لیست ثبت‌نام‌نشده‌ها است' + (f' ({terms})' if terms else '')})
    return reasons, count


def pseudo_person(first_name='', last_name='', national_code='', phone='', person_id=None):
    """فردِ بدون حساب دانش‌آموزی (مثلاً داوطلب تعیین سطح) را شبیه یک دانش‌آموز می‌کند تا همان بررسی‌ها روی آن اجرا شود."""
    from types import SimpleNamespace
    return SimpleNamespace(id=person_id, first_name=first_name or '', last_name=last_name or '',
                           national_code=national_code or '', phone=phone or '', username='')


def disciplinary_guard(request, students, skip_debtor=False, skip_unregistered=False, skip_disciplinary=False, title='هشدار هنگام ثبت‌نام'):
    """
    هشدار فوری قبل از ثبت‌نام در کلاس / ثبت درخواست تعیین سطح (HTTP 409 با code=disciplinary_warning؛ نام قدیمی برای سازگاری با پنل حفظ شده):
      ۱) فرد دو تعهدنامه انضباطی یا بیشتر دارد؛
      ۲) فرد بدهکارِ قبلی است (بدهی در حال پیگیری)؛
      ۳) فرد در لیست «ثبت‌نام‌نشده‌ها» (در حال پیگیری) است.
    مسیرهایی که خودشان از همان لیست ثبت می‌کنند (ثبت از لیست بدهکاران / ثبت‌نام‌نشده‌ها / استخراج ریزشی) بررسی
    همان لیست را رد می‌کنند (skip_*). با تأیید کاربر درخواست با confirm_disciplinary=1 تکرار می‌شود.
    """
    if _confirmed(request):
        return None
    flagged, lines = [], []
    for student in students:
        if not student:
            continue
        reasons, count = person_reasons(student, skip_debtor, skip_unregistered, skip_disciplinary)
        if reasons:
            name = f"{student.first_name or ''} {student.last_name or ''}".strip() or getattr(student, 'username', '')
            flagged.append({'student_id': getattr(student, 'id', None), 'name': name, 'count': count, 'reasons': reasons})
            lines.append(f"«{name}»: " + '؛ '.join(r['text'] for r in reasons))
    if not flagged:
        return None
    return Response({
        'code': 'disciplinary_warning',
        'disciplinary_warning': True,
        'error': f'{title}:\n' + '\n'.join(lines),
        'confirm_prompt': 'با وجود این هشدار، ادامه داده شود؟',
        'students': flagged,
    }, status=status.HTTP_409_CONFLICT)


def student_delete_blockers(student):
    """
    دلایلی که حذف این دانش‌آموز را «خطرناک» می‌کند (حذف دانش‌آموز همه‌ی این سوابق را هم پاک می‌کند):
    ثبت‌نام فعال (ترم در جریان/آینده یا دوره‌ی آنلاین فعال)، کلاس خصوصی/جبرانی، بدهکاران، ثبت‌نام‌نشده‌ها، تعیین سطح.
    """
    from django.utils import timezone
    from class_management.models import ClassSlotEnrollment, OnlineCourseEnrollment
    from accounts.models import ClassRequest
    from level_tests.models import LevelTest
    today = timezone.localdate()
    reasons = []

    enrollments = ClassSlotEnrollment.objects.filter(student=student).exclude(
        is_carryover=True, carryover_confirmed=False,
    ).select_related('class_slot', 'class_slot__term')
    active = [e for e in enrollments if not e.class_slot.term_id or not e.class_slot.term.end_date or e.class_slot.term.end_date >= today]
    if active:
        labels = '، '.join(sorted({f"کلاس {e.class_slot.number}" + (f" ({e.class_slot.term.title})" if e.class_slot.term_id else '') for e in active}))
        reasons.append(f'ثبت‌نام فعال دارد: {labels} — ثبت‌نام ترم جاری حفظ می‌شود')
    courses = OnlineCourseEnrollment.objects.filter(student=student, payment_verified=True, course__is_active=True).count()
    if courses:
        reasons.append(f'در {courses} دوره‌ی آنلاین فعال ثبت‌نام دارد')

    private_qs = ClassRequest.objects.filter(student=student, class_type__in=['private', 'makeup'])
    private_total = private_qs.count()
    if private_total:
        open_count = private_qs.filter(status__in=['pending', 'referred', 'confirmed']).count()
        reasons.append(f'در لیست کلاس‌های خصوصی/جبرانی است ({private_total} درخواست' + (f'، {open_count} مورد باز' if open_count else '') + ') — سوابق آن حفظ می‌شود')

    debts = _pending_debts(student)
    if debts:
        total = sum(int(d.debt_amount or 0) for d in debts)
        reasons.append('در لیست بدهکاران است' + (f' (مبلغ بدهی: {total:,} تومان)' if total else '') + ' — در همان لیست باقی می‌ماند')
    tracked = _tracking_unregistered(student)
    if tracked:
        reasons.append('در لیست ثبت‌نام‌نشده‌ها است — در همان لیست باقی می‌ماند')

    tests = LevelTest.objects.filter(student=student)
    test_total = tests.count()
    if test_total:
        pending = tests.filter(status=LevelTest.Status.PENDING).count()
        reasons.append(f'در لیست تعیین سطح است ({test_total} مورد' + (f'، {pending} مورد در انتظار تعیین سطح' if pending else '') + ')')
    return reasons
