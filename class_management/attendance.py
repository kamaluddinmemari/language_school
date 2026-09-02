"""ابزارهای مشترک لیست کلاسی و حضور و غیاب دانش‌آموزان."""
from datetime import timedelta

import jdatetime

from .models import ClassAttendance, ClassSlotEnrollment


DEFAULT_SESSION_COUNT = 15

# شماره‌گذاری date.weekday در پایتون: دوشنبه=۰ ... شنبه=۵، یکشنبه=۶.
WEEKDAY_NAMES = {
    'saturday': 5, 'شنبه': 5,
    'sunday': 6, 'یکشنبه': 6,
    'monday': 0, 'دوشنبه': 0,
    'tuesday': 1, 'سه‌شنبه': 1,
    'wednesday': 2, 'چهارشنبه': 2,
    'thursday': 3, 'پنجشنبه': 3,
    'friday': 4, 'جمعه': 4,
}

# این نگاشت با برنامهٔ فعلی کلاس‌ها یکسان است: زوج = شنبه/دوشنبه/چهارشنبه و
# فرد = یکشنبه/سه‌شنبه/پنجشنبه.
DAY_TYPE_WEEKDAYS = {
    'even': (5, 0, 2),
    'odd': (6, 1, 3),
    'thursday_morning': (3,),
    'thursday_evening': (3,),
    'friday': (4,),
    # کلاس‌های چرخشی/ترکیبی/آنلاین در صورت نداشتن روز اختصاصی، از تقویم سه‌روزهٔ
    # استاندارد استفاده می‌کنند؛ کلاس دو‌روزه فقط از schedule_days خودش استفاده می‌کند.
    'rotating': (5, 0, 2),
    'hybrid': (5, 0, 2),
    'online': (5, 0, 2),
}


def _slot_weekdays(slot):
    """روزهای واقعی برگزاری کلاس را از تنظیم کلاس برمی‌گرداند."""
    configured_days = slot.schedule_days or []
    normalized = [WEEKDAY_NAMES.get(str(day).strip().lower()) for day in configured_days]
    explicit_days = tuple(sorted({day for day in normalized if day is not None}))
    if explicit_days:
        return explicit_days
    return DAY_TYPE_WEEKDAYS.get(slot.day_type, ())


def session_dates_for_slot(slot, session_count=DEFAULT_SESSION_COUNT):
    """تا سقف تعداد جلسات، تاریخ‌های برگزاری را در بازهٔ ترم می‌سازد.

    تاریخ‌ها در پایگاه داده میلادی باقی می‌مانند. اگر کلاس ترم نداشته باشد یا برای
    نوع برنامهٔ آن روز برگزاری تعیین نشده باشد، لیست خالی است تا تاریخ ساختگی ثبت نشود.
    """
    if not slot.term_id or not slot.term.start_date or not slot.term.end_date:
        return []
    if slot.term.end_date < slot.term.start_date:
        return []

    weekdays = _slot_weekdays(slot)
    if not weekdays:
        return []

    dates = []
    cursor = slot.term.start_date
    while cursor <= slot.term.end_date and len(dates) < session_count:
        if cursor.weekday() in weekdays:
            dates.append(cursor)
        cursor += timedelta(days=1)
    return dates


def jalali_date(date_value):
    """نمایش تاریخ میلادیِ ذخیره‌شده به قالب شمسی ثابت برای پنل و چاپ."""
    return jdatetime.date.fromgregorian(date=date_value).strftime('%Y/%m/%d') if date_value else ''


def session_dates_payload(slot, session_count=DEFAULT_SESSION_COUNT):
    """دادهٔ استاندارد تاریخ جلسه برای API."""
    dates = session_dates_for_slot(slot, session_count=session_count)
    return [
        {
            'session_number': index,
            'date': date_value.isoformat(),
            'date_jalali': jalali_date(date_value),
        }
        for index, date_value in enumerate(dates, start=1)
    ]


def attendance_status(record):
    """وضعیت سازگار با داده‌های قدیمیِ فقط حاضر/غایب را برمی‌گرداند."""
    if getattr(record, 'status', ''):
        return record.status
    return 'present' if record.is_present else 'absent'


def roster_attendance_payload(slot, session_count=DEFAULT_SESSION_COUNT):
    """متادیتای کلاس، تاریخ جلسات و رستر ثبت‌نام‌های تأییدشده را برمی‌گرداند."""
    sessions = session_dates_payload(slot, session_count=session_count)
    session_number_by_date = {item['date']: item['session_number'] for item in sessions}
    enrolled = list(
        ClassSlotEnrollment.objects.filter(class_slot=slot, payment_verified=True)
        .select_related('student')
        .order_by('created_at')
    )
    attendance_by_student = {}
    if enrolled and sessions:
        attendance_rows = ClassAttendance.objects.filter(
            class_slot=slot,
            student_id__in=[enrollment.student_id for enrollment in enrolled],
            date__in=[item['date'] for item in sessions],
        )
        for row in attendance_rows:
            attendance_by_student.setdefault(row.student_id, {})[row.date.isoformat()] = row

    roster = []
    for enrollment in enrolled:
        student = enrollment.student
        rows = []
        for item in sessions:
            record = attendance_by_student.get(student.id, {}).get(item['date'])
            rows.append({
                'session_number': item['session_number'],
                'date': item['date'],
                'date_jalali': item['date_jalali'],
                'status': attendance_status(record) if record else 'unmarked',
                'note': record.note if record else '',
            })
        roster.append({
            'student_id': student.id,
            'student_name': student.get_full_name().strip(),
            'student_national_code': getattr(student, 'national_code', '') or '',
            'student_phone': getattr(student, 'phone', '') or '',
            'enrollment_id': enrollment.id,
            'sessions': rows,
        })

    warning = ''
    if not slot.term_id:
        warning = 'این کلاس به ترم وصل نشده است؛ لیست خام قابل چاپ است، اما تاریخ خودکار جلسه تولید نمی‌شود.'
    elif not sessions:
        warning = 'برای این کلاس روز برگزاری مشخص نیست؛ در ویرایش کلاس، روزهای برگزاری را تکمیل کنید تا تاریخ جلسه خودکار شود.'

    return {
        'class_slot': slot.id,
        'class_number': slot.number,
        'class_title': slot.title,
        'term': slot.term_id,
        'term_title': slot.term.title if slot.term_id else 'بدون ترم',
        'term_start_date': slot.term.start_date.isoformat() if slot.term_id else None,
        'term_end_date': slot.term.end_date.isoformat() if slot.term_id else None,
        'day_type': slot.day_type,
        'day_type_display': slot.get_day_type_display(),
        'time_slot': slot.time_slot,
        'level': slot.assigned_level,
        'teacher_name': slot.teacher_name,
        'gender': slot.gender,
        'gender_display': slot.get_gender_display(),
        'session_dates': sessions,
        'roster': roster,
        'raw_row_count': max(20, len(roster)),
        'schedule_warning': warning,
    }
