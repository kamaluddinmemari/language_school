"""
زمان‌بندی خودکار تعیین سطح.

هر روز، تایم‌های ۵ دقیقه‌ای پیشنهاد می‌شود (صبح ۰۹:۰۰–۱۲:۰۰ و عصر ۱۵:۳۰–۱۹:۳۰ + بازه‌های
اولویت‌دار عصر) و بر اساس برنامه‌ی واقعی استاد ارزیاب (کلاس‌های ترمی، جبرانی‌ها، خصوصی‌ها،
جلسات گروهی) و تعیین‌سطح‌های از‌قبل رزروشده، به سه وضعیت تقسیم می‌شود:
  free     → خالی، قابل انتخاب (عدد مشکی پررنگ)
  reserved → رزرو‌شده توسط تعیین‌سطح دیگر (قرمز، غیرقابل انتخاب مگر رزرو حذف شود)
  busy     → استاد در این ساعت کلاس/جبرانی/خصوصی دارد (قرمز، غیرقابل انتخاب)
"""
import re
from datetime import datetime, timedelta

import jdatetime
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LevelTest

# نام استادِ ارزیاب تعیین‌سطح — برای تغییر، فقط همین‌جا را عوض کنید (مقایسه بدون توجه به فاصله/نیم‌فاصله/ی-ك عربی).
EVALUATOR_TEACHER_NAME = 'حسام الدین معماری'

SLOT_MINUTES = 5
MORNING_RANGE = (9 * 60, 12 * 60)
EVENING_RANGE = (15 * 60 + 30, 19 * 60 + 30)
# بازه‌های اولویت‌دار عصر (شروع، پایان) — معمولاً فاصله‌ی بین کلاس‌های استاد
PRIORITY_RANGES = [(15 * 60, 15 * 60 + 45), (17 * 60 + 10, 17 * 60 + 35), (19 * 60, 19 * 60 + 20)]

# در این بازه‌ها (۱۷:۰۰–۱۷:۲۰ و ۱۹:۰۰–۱۹:۲۰) مشغول‌بودن استاد (کلاس/جبرانی/خصوصی) نادیده گرفته می‌شود؛ فقط رزرو تعیین‌سطح دیگر مانع است.
BUSY_EXEMPT_RANGES = [(17 * 60, 17 * 60 + 20), (19 * 60, 19 * 60 + 20)]


def normalize_name(value):
    s = str(value or '')
    s = s.replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', '').replace('\u200f', '')
    return re.sub(r'\s+', '', s).strip()


def is_evaluator_name(value):
    # نام اساتید استاندارد است: تطبیق دقیق با «حسام الدین معماری» (بدون توجه به فاصله/نیم‌فاصله و ی/ي)
    return normalize_name(value) == normalize_name(EVALUATOR_TEACHER_NAME)


def _user_full_name(user):
    return f'{user.first_name} {user.last_name}' if user else ''


def _hm(minutes):
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def _parse_range(text):
    m = re.match(r'^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$', str(text or ''))
    if not m:
        return None
    a = int(m.group(1)) * 60 + int(m.group(2))
    b = int(m.group(3)) * 60 + int(m.group(4))
    return (a, b) if b > a else None


def _minute_of_day(dt):
    local = timezone.localtime(dt)
    return local.hour * 60 + local.minute


def _local_date(dt):
    return timezone.localtime(dt).date()


def _candidate_starts():
    starts = set()
    for lo, hi in (MORNING_RANGE, EVENING_RANGE):
        t = lo
        while t + SLOT_MINUTES <= hi:
            starts.add(t)
            t += SLOT_MINUTES
    for lo, hi in PRIORITY_RANGES:
        t = lo
        while t + SLOT_MINUTES <= hi:
            starts.add(t)
            t += SLOT_MINUTES
    return sorted(starts)


def _is_priority(start):
    return any(lo <= start and start + SLOT_MINUTES <= hi for lo, hi in PRIORITY_RANGES)


def teacher_busy_intervals(day):
    """[(شروع_دقیقه, پایان_دقیقه, دلیل)] — برنامه‌ی واقعی استاد ارزیاب در تاریخ میلادیِ day"""
    from class_management.attendance import _slot_weekdays
    from class_management.models import ClassSlot, Term, TeacherSessionEvent
    from accounts.models import ClassRequest
    from group_classes.models import GroupSession

    busy = []

    # ۱) کلاس‌های ترمی — همیشه «آخرین ترمِ موجود» (بزرگ‌ترین سال، بعد بزرگ‌ترین شماره‌ی ترم)،
    # حتی اگر تاریخ انتخاب‌شده بیرون از بازه‌ی همان ترم باشد (الگوی هفتگی کلاس‌ها ملاک است)
    latest_term = Term.objects.order_by('-year', '-term_number').first()
    slots = ClassSlot.objects.select_related('term').filter(term=latest_term).exclude(teacher_name='') if latest_term else []
    for slot in slots:
        if not is_evaluator_name(slot.teacher_name):
            continue
        if day.weekday() not in _slot_weekdays(slot):
            continue
        # تعطیلی رسمی/غیبتِ ثبت‌شده فقط وقتی اعمال می‌شود که تاریخ داخل بازه‌ی خود ترم باشد
        if slot.term.holidays.filter(date=day).exists():
            continue
        rng = _parse_range(slot.time_slot)
        if not rng:
            continue
        freed = TeacherSessionEvent.objects.filter(
            class_slot=slot, class_date=day, event_type__in=['absence', 'substitution'],
        ).exclude(status='rejected').exists()
        if freed:
            continue
        busy.append((rng[0], rng[1], f'کلاس {slot.number} ({slot.time_slot})'))

    # ۲) رویدادهای جلسه (جبرانی، و ساب‌هایی که استاد جایگزین است)
    for ev in TeacherSessionEvent.objects.select_related('class_slot').filter(class_date=day).exclude(status='rejected'):
        if ev.event_type == 'makeup':
            mine = is_evaluator_name(ev.replacement_teacher_name) or is_evaluator_name(ev.requested_teacher_name) \
                or (not ev.replacement_teacher_name and not ev.requested_teacher_name and is_evaluator_name(ev.class_slot.teacher_name))
            label = 'جبرانی'
        elif ev.event_type == 'substitution':
            mine = is_evaluator_name(ev.replacement_teacher_name)
            label = 'ساب'
        else:
            continue
        if not mine:
            continue
        rng = _parse_range(ev.class_time) or _parse_range(ev.class_slot.time_slot)
        if rng:
            busy.append((rng[0], rng[1], f'{label} کلاس {ev.class_slot.number} ({_hm(rng[0])}-{_hm(rng[1])})'))

    # ۳) کلاس‌های خصوصی/جبرانی/سایر ثبت‌شده در «درخواست‌های کلاس»
    for req in ClassRequest.objects.select_related('teacher').filter(class_date__isnull=False).exclude(status__in=['rejected', 'cancelled']):
        if _local_date(req.class_date) != day:
            continue
        names = [_user_full_name(req.teacher), req.suggested_teacher_name]
        if not any(is_evaluator_name(n) for n in names):
            continue
        start = _minute_of_day(req.class_date)
        dur = 60 if str(req.session_duration) == '1' else 90
        kind = req.get_class_type_display()
        busy.append((start, start + dur, f'کلاس {kind} ({_hm(start)}-{_hm(start + dur)})'))

    # ۴) جلسات گروهی/ورکشاپ
    for gs in GroupSession.objects.select_related('teacher').filter(class_date__isnull=False).exclude(status__in=['rejected', 'cancelled']):
        if _local_date(gs.class_date) != day:
            continue
        if not is_evaluator_name(_user_full_name(gs.teacher)):
            continue
        start = _minute_of_day(gs.class_date)
        dur = 60 if str(gs.session_duration) == '1' else 90
        busy.append((start, start + dur, f'جلسه گروهی ({_hm(start)}-{_hm(start + dur)})'))

    return busy


def reservations_for_day(day, exclude_id=None):
    """تعیین‌سطح‌های در انتظارِ رزروشده در این روز → [(دقیقه‌ی شروع, نام)]"""
    qs = LevelTest.objects.filter(status=LevelTest.Status.PENDING, test_date__isnull=False)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    out = []
    for t in qs:
        if _local_date(t.test_date) == day:
            out.append((_minute_of_day(t.test_date), f'{t.first_name} {t.last_name}'.strip()))
    return out


def find_reserved_conflict(test_date, exclude_pk=None):
    """اگر همین تایم (بازه‌ی SLOT_MINUTES) قبلاً برای تعیین‌سطحِ در انتظارِ دیگری رزرو شده باشد، نام او را برمی‌گرداند."""
    if not test_date:
        return None
    day = _local_date(test_date)
    start = _minute_of_day(test_date)
    for s, name in reservations_for_day(day, exclude_pk):
        if abs(s - start) < SLOT_MINUTES:
            return name or 'فرد دیگر'
    return None


def _overlaps(a1, a2, b1, b2):
    return a1 < b2 and b1 < a2


class LevelTestAvailableTimesView(APIView):
    """GET ?date=YYYY-MM-DD (میلادی) [&exclude_id=N] → تایم‌های پیشنهادی آن روز با وضعیت هرکدام"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if getattr(request.user, 'role', '') == 'student':
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            day = datetime.strptime(request.query_params.get('date', ''), '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'تاریخ نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        exclude_id = request.query_params.get('exclude_id') or None

        busy = teacher_busy_intervals(day)
        reserved = reservations_for_day(day, exclude_id)
        now_local = timezone.localtime(timezone.now())
        now_min = now_local.hour * 60 + now_local.minute

        slots = []
        for start in _candidate_starts():
            end = start + SLOT_MINUTES
            state, reason = 'free', ''
            is_past = day < now_local.date() or (day == now_local.date() and start < now_min)
            hit = next(((s, n) for s, n in reserved if _overlaps(start, end, s, s + SLOT_MINUTES)), None)
            if is_past:
                state, reason = 'past', 'این تایم گذشته است'
            elif hit:
                state, reason = 'reserved', f'رزرو شده برای {hit[1]}'
            elif not any(lo <= start and end <= hi for lo, hi in BUSY_EXEMPT_RANGES):
                b = next((x for x in busy if _overlaps(start, end, x[0], x[1])), None)
                if b:
                    state, reason = 'busy', f'استاد در این ساعت: {b[2]}'
            slots.append({
                'time': _hm(start), 'period': 'morning' if start < 13 * 60 else 'evening',
                'priority': _is_priority(start) and start >= 13 * 60, 'state': state, 'reason': reason,
            })
        return Response({
            'date': day.isoformat(),
            'teacher_name': EVALUATOR_TEACHER_NAME,
            'slots': slots,
            'busy': [{'start': _hm(a), 'end': _hm(b), 'reason': r} for a, b, r in busy],
            'reservations': [{'time': _hm(s), 'name': n} for s, n in reserved],
        })


class LevelTestTeacherConflictsView(APIView):
    """
    GET ?start=ISO&minutes=90&teacher=نام[&teacher=نام2...] → تعیین‌سطح‌های رزروشده که با بازه‌ی
    [start, start+minutes) تداخل دارند — فقط اگر یکی از نام‌های استاد، استاد ارزیاب باشد.
    برای هشدارِ «استاد در این ساعت تایم تعیین سطح دارد» هنگام ثبت کلاس خصوصی/جبرانی.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if getattr(request.user, 'role', '') == 'student':
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        teachers = request.query_params.getlist('teacher')
        if not any(is_evaluator_name(t) for t in teachers):
            return Response({'conflicts': [], 'teacher_name': EVALUATOR_TEACHER_NAME})
        raw = (request.query_params.get('start') or '').replace('Z', '+00:00')
        try:
            start_dt = datetime.fromisoformat(raw)
            minutes = int(request.query_params.get('minutes') or 90)
        except ValueError:
            return Response({'error': 'ورودی نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        if timezone.is_naive(start_dt):
            start_dt = timezone.make_aware(start_dt)
        end_dt = start_dt + timedelta(minutes=minutes)
        conflicts = []
        qs = LevelTest.objects.filter(
            status=LevelTest.Status.PENDING, test_date__gt=start_dt - timedelta(minutes=SLOT_MINUTES),
            test_date__lt=end_dt,
        ).order_by('test_date')
        for t in qs:
            conflicts.append({
                'id': t.id, 'name': f'{t.first_name} {t.last_name}'.strip(), 'test_date_jalali': t.test_date_jalali,
            })
        return Response({'conflicts': conflicts, 'teacher_name': EVALUATOR_TEACHER_NAME})
