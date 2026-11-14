"""ابزارهای مشترک لیست کلاسی و حضور و غیاب دانش‌آموزان."""
from datetime import timedelta

import jdatetime
from django.db.models import Q
from django.utils import timezone

from .models import ClassAttendance, ClassSlot, ClassSlotEnrollment, TeacherSessionEvent, Term, infer_age_group_from_level


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
    'friday_morning': (4,),
    'friday_evening': (4,),
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


def session_dates_for_slot_detailed(slot, session_count=DEFAULT_SESSION_COUNT):
    """مثل session_dates_for_slot اما جفتِ (تاریخ‌های جلسات، تعطیلات رسمیِ همین ترم که دقیقاً
    روی یکی از روزهای برگزاری این کلاس افتاده‌اند و به همین دلیل از تقویم حذف شده‌اند) را
    برمی‌گرداند — برای نمایش هشدار «فلان تاریخ تعطیلی رسمی می‌باشد» در پنل و اپ‌ها.
    """
    if not slot.term_id or not slot.term.start_date or not slot.term.end_date:
        return [], []
    if slot.term.end_date < slot.term.start_date:
        return [], []

    weekdays = _slot_weekdays(slot)
    if not weekdays:
        return [], []

    holidays_by_date = {h.date: h for h in slot.term.holidays.all()}

    dates = []
    skipped_holidays = []
    cursor = slot.term.start_date
    while cursor <= slot.term.end_date and len(dates) < session_count:
        if cursor.weekday() in weekdays:
            holiday = holidays_by_date.get(cursor)
            if holiday:
                skipped_holidays.append(holiday)
            else:
                dates.append(cursor)
        cursor += timedelta(days=1)
    return dates, skipped_holidays


def session_dates_for_slot(slot, session_count=DEFAULT_SESSION_COUNT):
    """تا سقف تعداد جلسات، تاریخ‌های برگزاری را در بازهٔ ترم می‌سازد.

    تاریخ‌ها در پایگاه داده میلادی باقی می‌مانند. اگر کلاس ترم نداشته باشد یا برای
    نوع برنامهٔ آن روز برگزاری تعیین نشده باشد، لیست خالی است تا تاریخ ساختگی ثبت نشود.
    هر تاریخی که در تعطیلات رسمیِ ثبت‌شده‌ی همان ترم باشد و روی روز برگزاری این کلاس بیفتد،
    نادیده گرفته می‌شود و جلسه‌ی بعدیِ همان الگوی روز جایگزینش می‌شود.
    """
    dates, _skipped_holidays = session_dates_for_slot_detailed(slot, session_count=session_count)
    return dates


def term_holiday_warnings_for_slot(slot, session_count=DEFAULT_SESSION_COUNT):
    """لیست هشدارهای تعطیلی رسمی برای همین کلاس (فقط تعطیلاتی که واقعاً روی یکی از
    جلسات محاسبه‌شده‌ی این کلاس افتاده و حذف شده‌اند)."""
    _dates, skipped_holidays = session_dates_for_slot_detailed(slot, session_count=session_count)
    return [
        {
            'date': h.date.isoformat(),
            'date_jalali': h.date_jalali,
            'description': h.description,
            'message': f"تاریخ {h.date_jalali} تعطیلی رسمی می‌باشد" + (f" ({h.description})" if h.description else "") + " و جلسه‌ی آن حذف و جابه‌جا شد",
        }
        for h in skipped_holidays
    ]


def attendance_session_dates_for_slot(slot, session_count=DEFAULT_SESSION_COUNT):
    """تقویم مورد استفاده در لیست کلاسی ادمین و حضور و غیاب.

    کلاس‌های یک‌روزدرهفته در پنل ادمین سه جلسه متوالی در همان تاریخ دارند؛
    بنابراین endpoint اپ نیز باید دقیقاً همان شماره جلسه و همان تاریخ را بدهد.
    """
    dates = session_dates_for_slot(slot, session_count=session_count)
    one_day_types = {'thursday_morning', 'thursday_evening', 'friday', 'friday_morning', 'friday_evening'}
    if slot.day_type not in one_day_types:
        return dates
    expanded = []
    for date_value in dates:
        expanded.extend([date_value, date_value, date_value])
        if len(expanded) >= session_count:
            break
    return expanded[:session_count]


def session_date_and_sub(slot, session_number, session_count=DEFAULT_SESSION_COUNT):
    """(تاریخ جلسه، شمارهٔ جلسه در همان روز) برای شمارهٔ جلسهٔ ۱ تا ۱۵. کلاس‌های یک‌روزه سه جلسه در هر تاریخ دارند."""
    dates = attendance_session_dates_for_slot(slot, session_count=session_count)
    if session_number < 1 or session_number > len(dates):
        return None, None
    date_value = dates[session_number - 1]
    return date_value, dates[:session_number - 1].count(date_value) + 1


def jalali_date(date_value):
    """نمایش تاریخ میلادیِ ذخیره‌شده به قالب شمسی ثابت برای پنل و چاپ."""
    return jdatetime.date.fromgregorian(date=date_value).strftime('%Y/%m/%d') if date_value else ''


def session_dates_payload(slot, session_count=DEFAULT_SESSION_COUNT):
    """دادهٔ استاندارد تاریخ جلسه برای API."""
    dates = attendance_session_dates_for_slot(slot, session_count=session_count)
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
    event_status_by_session = {}
    for event in TeacherSessionEvent.objects.filter(
        class_slot=slot,
        status=TeacherSessionEvent.ApprovalStatus.APPROVED,
        class_date__in=[item['date'] for item in sessions],
    ):
        event_status_by_session[(event.session_number, event.class_date.isoformat())] = (
            'substitution' if event.event_type == TeacherSessionEvent.EventType.SUBSTITUTION else
            'absence' if event.event_type == TeacherSessionEvent.EventType.ABSENCE else
            'makeup'
        )
    seen_per_date = {}
    for item in sessions:
        seen_per_date[item['date']] = seen_per_date.get(item['date'], 0) + 1
        item['session_in_day'] = seen_per_date[item['date']]
        item['event_status'] = event_status_by_session.get((item['session_number'], item['date']), '')
        item['is_past'] = item['date'] < timezone.localdate().isoformat()
    enrolled = list(
        ClassSlotEnrollment.objects.filter(class_slot=slot, payment_verified=True)
        .select_related('student')
        .order_by('created_at')
    )
    confirmed_current_ids = set()
    if slot.term_id:
        confirmed_current_ids = set(ClassSlotEnrollment.objects.filter(
            class_slot__term_id=slot.term_id,
            payment_verified=True,
        ).filter(
            Q(is_carryover=False) | Q(carryover_confirmed=True)
        ).values_list('student_id', flat=True))
    # انتقال به «پیگیری ثبت‌نام‌نشده‌ها» باید فرد را از فهرست زرد همین صفحه خارج کند؛
    # رکورد پیگیری در leads باقی می‌ماند و فقط نمایش رستر حذف می‌شود.
    from leads.models import UnregisteredStudent
    transferred_people = set(UnregisteredStudent.objects.filter(
        term_id=slot.term_id, misplaced_from_slot=slot,
        is_misplaced=True, status=UnregisteredStudent.Status.TRACKING,
    ).values_list('first_name', 'last_name', 'national_code', 'phone'))

    # فردی که «در کلاس حضور دارد ولی ثبت‌نام نکرده» به پیگیری رفته: در رستر می‌ماند (هنوز سر کلاس می‌آید)
    # ولی با نشان «به لیست پیگیری منتقل شد» دیده می‌شود.
    attending_transferred = set(UnregisteredStudent.objects.filter(
        term_id=slot.term_id, reported_slot=slot,
        attendance_transfer='attending', status=UnregisteredStudent.Status.TRACKING,
    ).values_list('first_name', 'last_name', 'national_code', 'phone'))

    def _identity(student):
        return (
            student.first_name, student.last_name,
            getattr(student, 'national_code', '') or '', getattr(student, 'phone', '') or '',
        )

    def was_transferred(student):
        return _identity(student) in transferred_people

    def attending_in_followup(student):
        return _identity(student) in attending_transferred
    attendance_by_student = {}
    if enrolled and sessions:
        attendance_rows = ClassAttendance.objects.filter(
            class_slot=slot,
            student_id__in=[enrollment.student_id for enrollment in enrolled],
            date__in=[item['date'] for item in sessions],
        )
        for row in attendance_rows:
            attendance_by_student.setdefault(row.student_id, {})[(row.date.isoformat(), row.session_in_day)] = row

    roster = []
    roster_student_ids = set()
    for enrollment in enrolled:
        student = enrollment.student
        needs_follow_up = student.id not in confirmed_current_ids
        if needs_follow_up and was_transferred(student):
            continue
        rows = []
        for item in sessions:
            record = attendance_by_student.get(student.id, {}).get((item['date'], item['session_in_day']))
            rows.append({
                'session_number': item['session_number'],
                'date': item['date'],
                'date_jalali': item['date_jalali'],
                'status': attendance_status(record) if record else 'unmarked',
                'event_status': event_status_by_session.get((item['session_number'], item['date']), ''),
                'note': record.note if record else '',
            })
        roster.append({
            'student_id': student.id,
            'student_name': student.get_full_name().strip(),
            'student_national_code': getattr(student, 'national_code', '') or '',
            'student_phone': getattr(student, 'phone', '') or '',
            'enrollment_id': enrollment.id,
            'is_carryover': enrollment.is_carryover,
            'carryover_confirmed': enrollment.carryover_confirmed,
            'needs_follow_up': needs_follow_up,
            'needs_follow_up_label': 'منتظر ثبت‌نام' if needs_follow_up else '',
            'registration_status': 'needs_follow_up' if needs_follow_up else 'registered',
            'student_name_color': '#6c757d' if needs_follow_up else '#212529',
            'student_row_color': '#e9ecef' if needs_follow_up else '#ffffff',
            'is_previous_only': False,
            'followup_transfer_available': needs_follow_up,
            'registration_note': 'این فرد هنوز ثبت‌نام نکرده' if needs_follow_up else '',
            'followup_transferred': bool(needs_follow_up and attending_in_followup(student)),
            'sessions': rows,
        })
        roster_student_ids.add(student.id)

    # دانش‌آموزان کلاس متناظر ترم قبل نیز در رستر جاری دیده می‌شوند؛ این کار مخصوصاً
    # برای افرادی لازم است که هنوز هیچ رکوردی در ترم جاری ندارند و انتقال خودکار برایشان
    # انجام نشده است. ابتدا ارتباط صریحِ کلاسِ کپی‌شده را ترجیح می‌دهیم و سپس تطبیق شماره/روز/ساعت را.
    previous_slot = slot.carried_from_slot
    if previous_slot is None and slot.term_id:
        previous_term = Term.objects.filter(
            Q(year__lt=slot.term.year)
            | Q(year=slot.term.year, term_number__lt=slot.term.term_number)
        ).order_by('-year', '-term_number').first()
        if previous_term:
            previous_slot = ClassSlot.objects.filter(
                term=previous_term, number=slot.number, day_type=slot.day_type,
                time_slot=slot.time_slot, is_online=slot.is_online,
            ).order_by('id').first()
    if previous_slot:
        previous_students = ClassSlotEnrollment.objects.filter(
            class_slot=previous_slot, payment_verified=True,
        ).select_related('student').order_by('created_at')
        for enrollment in previous_students:
            student = enrollment.student
            if student.id in roster_student_ids:
                continue
            rows = [{
                'session_number': item['session_number'],
                'date': item['date'],
                'date_jalali': item['date_jalali'],
                'status': 'unmarked',
                'event_status': event_status_by_session.get((item['session_number'], item['date']), ''),
                'note': '',
            } for item in sessions]
            needs_follow_up = student.id not in confirmed_current_ids
            if needs_follow_up and was_transferred(student):
                continue
            roster.append({
                'student_id': student.id,
                'student_name': student.get_full_name().strip(),
                'student_national_code': getattr(student, 'national_code', '') or '',
                'student_phone': getattr(student, 'phone', '') or '',
                'enrollment_id': None,
                'is_carryover': False,
                'carryover_confirmed': False,
                'needs_follow_up': needs_follow_up,
                'needs_follow_up_label': 'شهریه بدهکار — ثبت‌نام قطعی نشده' if needs_follow_up else '',
                'registration_status': 'needs_follow_up' if needs_follow_up else 'registered',
                'student_name_color': '#adb5bd' if needs_follow_up else '#212529',
                'student_row_color': '#fff3cd' if needs_follow_up else '#ffffff',
                'is_previous_only': True,
                'followup_transfer_available': needs_follow_up,
                'registration_note': 'این فرد هنوز ثبت‌نام نکرده' if needs_follow_up else '',
                'followup_transferred': bool(needs_follow_up and attending_in_followup(student)),
                'sessions': rows,
            })
            roster_student_ids.add(student.id)

    warning = ''
    if not slot.term_id:
        warning = 'این کلاس به ترم وصل نشده است؛ لیست خام قابل چاپ است، اما تاریخ خودکار جلسه تولید نمی‌شود.'
    elif not sessions:
        warning = 'برای این کلاس روز برگزاری مشخص نیست؛ در ویرایش کلاس، روزهای برگزاری را تکمیل کنید تا تاریخ جلسه خودکار شود.'

    holiday_warnings = term_holiday_warnings_for_slot(slot, session_count=session_count)

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
        'age_group': infer_age_group_from_level(slot.assigned_level),
        'teacher_name': slot.teacher_name,
        'gender': slot.gender,
        'gender_display': slot.get_gender_display(),
        'session_dates': sessions,
        'roster': roster,
        'raw_row_count': max(20, len(roster)),
        'schedule_warning': warning,
        'holiday_warnings': holiday_warnings,
    }
