from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.dateparse import parse_date
import json
import random
import re
import math
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from django.db import IntegrityError, models as django_models, transaction
from django.db.models import Count, Exists, Max, OuterRef, Q
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
import jdatetime
from .models import ClassSlot, ClassSlotEnrollment, TuitionSetting, DiscountedPerson, EnrollmentRefund, WalletTransaction, infer_age_group_from_level, _jalali, LevelRenewalApproval, Term, TermHoliday, TermRetentionFollowUp, OnlineCourse, OnlineCourseEnrollment, PaymentSettings, ClassAttendance, OnlineCourseActionRequest, GraduatedStudentInfo
from .models import THREE_DAY_TIME_SLOTS, THURSDAY_MORNING_SLOT, THURSDAY_EVENING_SLOT, FRIDAY_SLOT, FRIDAY_MORNING_SLOT, FRIDAY_EVENING_SLOT

# QR و جلسات استادان فعلاً غیرفعال هستند؛ نبودن مدل‌های این بخش‌ها نباید مانع اجرای ترم و کلاس شود.
try:
    from .models import RoomQrToken, TeacherSessionEvent, TeacherSessionAttendance, TeacherCompensationSetting
except ImportError:
    RoomQrToken = None
    TeacherSessionEvent = None
    TeacherSessionAttendance = None
    TeacherCompensationSetting = None
from .serializers import (
    ClassSlotSerializer, AllocateClassesSerializer, ConfirmOverflowSerializer,
    TransferSurplusSerializer, SpinOffSurplusSerializer,
    BulkCreatePhysicalClassesSerializer, EnrollStudentSerializer, ClassSlotEnrollmentSerializer,
    TuitionSettingSerializer, DiscountedPersonSerializer, RefundEnrollmentSerializer, TransferEnrollmentSerializer,
    SplitClassSerializer, LevelRenewalApprovalSerializer, TermSerializer, TermHolidaySerializer,
    OnlineCourseSerializer, OnlineCourseEnrollmentSerializer, OnlineCourseEnrollSerializer, PaymentSettingsSerializer,
    ClassAttendanceSerializer, OnlineCourseTransferSerializer, OnlineCourseActionRequestSerializer,
    OnlineCourseActionRequestCreateSerializer, OnlineCourseActionRequestReviewSerializer,
)
from level_tests.models import LevelTest
from accounts.menu_permissions import can_edit_menu, can_view_menu
from .allocation import allocate_classes
from .disciplinary import disciplinary_guard
from .carryover import sync_carryover_followup_list, create_awaiting_debtor, finalize_registration, register_student_in_slot, gray_enrollments
from .attendance import DEFAULT_SESSION_COUNT, jalali_date, roster_attendance_payload, session_date_and_sub, session_dates_for_slot, term_holiday_warnings_for_slot

# منسوخ — از تنظیمات دسترسی (accounts.menu_permissions.can_edit_menu) جایگزین شد.
# فقط برای مرجع/سازگاری با کد قدیمی نگه داشته شده؛ جایی از این فایل استفاده نمی‌شود.
MANAGE_ROLES = ('admin', 'evaluator', 'office', 'employee')


def _same_term_enrollments(slot, student_ids=None):
    queryset = ClassSlotEnrollment.objects.all()
    if slot.term_id:
        queryset = queryset.filter(class_slot__term_id=slot.term_id)
    else:
        queryset = queryset.filter(class_slot__term__isnull=True)
    if student_ids is not None:
        queryset = queryset.filter(student_id__in=student_ids)
    return queryset.select_related('class_slot').order_by('created_at')


def _enrollment_class_label(slot):
    return (
        f"کلاس {slot.number} — {slot.day_type_display} — ساعت {slot.time_slot or 'نامشخص'}"
        f" — سطح {slot.assigned_level or '—'}"
    )


def _next_level_for_carryover(level_code, terminal_levels=None):
    """Return the next level using the school-approved progression, plus a terminal warning.

    منبع اصلی، جدول StandardLevel («تعریف سطوح استاندارد») است: ترتیب از فیلد order و سطح
    پایانی هر رده از فیلد is_terminal خوانده می‌شود. terminal_levels (اگر فرستاده شود) فقط
    به‌عنوان بازگشت‌پذیری با نسخه‌های قدیمی‌تر فرانت‌اند در نظر گرفته می‌شود.
    """
    raw = str(level_code or '').strip()
    if not raw:
        return '', ''
    normalized = raw.lower().replace(' ', '')

    from level_tests.models import StandardLevel
    current = StandardLevel.objects.filter(code__iexact=raw).first()
    if current:
        if current.is_terminal:
            return raw, f'سطح «{raw}» سطح پایانی رده «{current.get_age_group_display()}» است؛ دانش‌آموزان برای ثبت‌نام ترم بعد نیازمند تعیین سطح می‌باشند.'
        siblings = list(StandardLevel.objects.filter(age_group=current.age_group).order_by('order', 'code'))
        idx = next((i for i, lvl in enumerate(siblings) if lvl.code.lower() == normalized), -1)
        if idx >= 0 and idx + 1 < len(siblings):
            return siblings[idx + 1].code, ''
        return raw, f'سطح «{raw}» آخرین سطح تعریف‌شده در رده «{current.get_age_group_display()}» است ولی به عنوان سطح پایانی علامت نخورده — از بخش «تعریف سطوح استاندارد» بررسی کنید.'

    # سطح در جدول StandardLevel پیدا نشد (داده‌ی قدیمی/دستی) — بازگشت به توالی پیش‌فرض قدیمی
    configured_terminal = {str(v).strip().lower().replace(' ', ''): str(k).strip() for k, v in (terminal_levels or {}).items() if v}
    terminal_group_labels = {'kids': 'کودک', 'teen': 'نوجوان', 'adult': 'بزرگسال'}
    if normalized in configured_terminal:
        group_key = configured_terminal.get(normalized, '')
        return raw, f'سطح نهایی گروه «{terminal_group_labels.get(group_key, group_key)}» است؛ دانش‌آموزان برای ثبت‌نام ترم بعد نیازمند تعیین سطح می‌باشند.'
    kids = [f'{prefix}{n}' for prefix in ('e', 's', 'g', 'u', 'm', 'h', 'i') for n in range(1, 6)]
    teens = ['teenstarter'] + [f'teen{n}' for n in range(1, 16)]
    adults = [str(n) for block in range(1, 7) for n in range(block * 100 + 1, block * 100 + 7)]
    for sequence, label in ((kids, 'کودک'), (teens, 'نوجوان'), (adults, 'بزرگسال')):
        idx = next((i for i, code in enumerate(sequence) if code.lower() == normalized), -1)
        if idx >= 0:
            if idx + 1 < len(sequence):
                return sequence[idx + 1], ''
            return raw, f'سطح «{raw}» آخرین سطح {label} است و برای ترم بعد سطح بالاتری ندارد.'
    return raw, f'برای سطح «{raw}» ترتیب ارتقا پیدا نشد؛ سطح ترم جدید را دستی بررسی کنید.'


def _auto_distribute_surplus(source, remainder):
    moves = []
    if remainder <= 0:
        return moves, 0

    category = source.time_category()
    others = ClassSlot.objects.exclude(pk=source.pk)
    if category:
        candidates = [s for s in others if category & s.time_category() and (not s.assigned_level or s.assigned_level == source.assigned_level)]
    else:
        candidates = [s for s in others if s.day_type == source.day_type and (not s.assigned_level or s.assigned_level == source.assigned_level)]
    candidates = [s for s in candidates if (s.capacity - s.current_count) > 0]
    candidates.sort(key=lambda s: -(s.capacity - s.current_count))

    for cand in candidates:
        if remainder <= 0:
            break
        room = cand.capacity - cand.current_count
        take = min(room, remainder)
        if take <= 0:
            continue
        cand.assigned_level = cand.assigned_level or source.assigned_level
        cand.current_count += take
        cand.save()
        source.current_count -= take
        moves.append({
            'target_slot_id': cand.id, 'target_number': cand.number,
            'target_time_slot': cand.time_slot, 'moved': take,
        })
        remainder -= take

    if moves:
        source.save()

    return moves, remainder


class ClassSlotListView(generics.ListCreateAPIView):
    """
    GET: لیست کلاس‌های فیزیکی/آنلاین — با فیلترهای اختیاری زیر (برای بخش «کلاس‌های ترم» و
    فهرست‌های مشابه که نیاز به لیست فشرده‌ی کلاس‌های یک ترم مشخص با ترکیبی از فیلترها دارند):
      term: شناسه‌ی ترم (یا legacy/unassigned/null برای کلاس‌های بدون ترم)
      day_type: نوع روز (even/odd/thursday_morning/thursday_evening/friday_morning/friday_evening/...)
      time_slot: ساعت دقیق (مثلاً 08:00-09:30)
      assigned_level: سطح تخصیص‌داده‌شده
      teacher_name: نام استاد (تطبیق دقیق—غیرحساس به بزرگی/کوچکی حروف)
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ClassSlotSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'class-management'):
            return ClassSlot.objects.none()
        qs = ClassSlot.objects.all()
        term_id = self.request.query_params.get('term')
        if term_id in ('legacy', 'unassigned', 'null'):
            qs = qs.filter(term__isnull=True)
        elif term_id and str(term_id).isdigit():
            qs = qs.filter(term_id=int(term_id))
        day_type = self.request.query_params.get('day_type')
        if day_type:
            qs = qs.filter(day_type=day_type)
        time_slot = self.request.query_params.get('time_slot')
        if time_slot:
            qs = qs.filter(time_slot=time_slot)
        assigned_level = self.request.query_params.get('assigned_level')
        if assigned_level:
            qs = qs.filter(assigned_level__iexact=assigned_level)
        teacher_name = self.request.query_params.get('teacher_name')
        if teacher_name:
            qs = qs.filter(teacher_name__iexact=teacher_name)
        return qs

    def create(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class TermListView(generics.ListCreateAPIView):
    """GET: لیست ترم‌های تعریف‌شده / POST: تعریف یک ترم جدید (سال + شماره‌ترم ۱ تا ۸ + بازه‌ی تاریخ)"""
    permission_classes = [IsAuthenticated]
    serializer_class = TermSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'class-management'):
            return Term.objects.none()
        return Term.objects.all()

    def create(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class TermSettingView(APIView):
    """GET/POST تیک سراسری «آخرین ترم موجود را ترم جاری حساب کن» + ترم جاریِ فعلی."""
    permission_classes = [IsAuthenticated]

    def _payload(self):
        from .models import TermSetting, get_current_term
        current = get_current_term()
        return {
            'force_latest_term': TermSetting.get().force_latest_term,
            'current_term_id': current.id if current else None,
            'current_term_title': current.title if current else '',
        }

    def get(self, request):
        return Response(self._payload())

    def post(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from .models import TermSetting
        setting = TermSetting.get()
        setting.force_latest_term = str(request.data.get('force_latest_term', '')).lower() in ('1', 'true', 'yes', 'on')
        setting.save()
        return Response(self._payload())


class CarryClassesToNextTermView(APIView):
    """انتقال انتخابی کلاس‌های یک ترم به ترم مقصد.

    برای هر کلاس، فیلد carry_students (پیش‌فرض: True) مشخص می‌کند دانش‌آموزان تاییدشدهٔ کلاس مبدا هم
    در کلاس جدید ثبت‌نام شوند یا نه. ثبت‌نام‌های ترم مبدا برای حفظ سوابق آموزشی/مالی دست‌نخورده می‌مانند.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی به انتقال کلاس‌ها ندارید'}, status=status.HTTP_403_FORBIDDEN)
        source_term_id = request.data.get('source_term_id')
        target_term_id = request.data.get('target_term_id')
        day_types = request.data.get('day_types') or []
        time_slots = request.data.get('time_slots') or []
        assignments = request.data.get('classes') or []
        terminal_levels = request.data.get('terminal_levels') or {}
        try:
            target_term = Term.objects.get(pk=target_term_id)
        except (Term.DoesNotExist, TypeError, ValueError):
            return Response({'error': 'ترم مقصد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        legacy_source = str(source_term_id).lower() in {'legacy', 'unassigned', 'null', 'none'}
        if legacy_source:
            qs = ClassSlot.objects.filter(term__isnull=True)
        else:
            try:
                source_term = Term.objects.get(pk=source_term_id)
            except (Term.DoesNotExist, TypeError, ValueError):
                return Response({'error': 'ترم مبدا پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
            if source_term.id == target_term.id:
                return Response({'error': 'ترم مقصد باید با ترم مبدا متفاوت باشد'}, status=status.HTTP_400_BAD_REQUEST)
            qs = ClassSlot.objects.filter(term=source_term)
        if day_types:
            qs = qs.filter(day_type__in=day_types)
        if time_slots:
            qs = qs.filter(time_slot__in=time_slots)
        assignment_by_id = {str(row.get('source_id')): row for row in assignments if row.get('source_id')}
        if assignment_by_id:
            qs = qs.filter(pk__in=[row.get('source_id') for row in assignments if row.get('source_id')])
        created, skipped, warnings = [], [], []
        created_targets = []
        students_carried_total = 0
        with transaction.atomic():
            for source in qs.select_for_update().order_by('number', 'day_type', 'time_slot'):
                row = assignment_by_id.get(str(source.id), {})
                number = int(row.get('number') or source.number)
                teacher_name = str(row.get('teacher_name') or '').strip()
                day_type = str(row.get('day_type') or source.day_type).strip()
                schedule_kind = str(row.get('schedule_kind') or source.schedule_kind).strip()
                time_slot = str(row.get('time_slot') or source.time_slot or '').strip()
                schedule_days = row.get('schedule_days') if isinstance(row.get('schedule_days'), list) else (source.schedule_days or [])
                delivery_pattern = row.get('delivery_pattern') if isinstance(row.get('delivery_pattern'), list) else (source.delivery_pattern or [])
                gender = str(row.get('gender') or source.gender).strip()
                is_online = row.get('is_online') if 'is_online' in row else source.is_online
                if day_type not in ClassSlot.DayType.values:
                    skipped.append({'source_id': source.id, 'reason': 'نوع روز کلاس مقصد معتبر نیست'})
                    continue
                if schedule_kind not in ClassSlot.ScheduleKind.values:
                    skipped.append({'source_id': source.id, 'reason': 'نوع برنامه کلاس مقصد معتبر نیست'})
                    continue
                if gender not in ClassSlot.Gender.values:
                    skipped.append({'source_id': source.id, 'reason': 'جنسیت کلاس مقصد معتبر نیست'})
                    continue
                fixed_time = {
                    ClassSlot.DayType.THURSDAY_MORNING: THURSDAY_MORNING_SLOT, ClassSlot.DayType.THURSDAY_EVENING: THURSDAY_EVENING_SLOT,
                    ClassSlot.DayType.FRIDAY: FRIDAY_SLOT, ClassSlot.DayType.FRIDAY_MORNING: FRIDAY_MORNING_SLOT, ClassSlot.DayType.FRIDAY_EVENING: FRIDAY_EVENING_SLOT,
                }.get(day_type)
                if fixed_time:
                    time_slot = fixed_time
                automatic_level, level_warning = _next_level_for_carryover(source.assigned_level, terminal_levels)
                assigned_level = str(row['assigned_level']).strip() if 'assigned_level' in row else automatic_level
                if assigned_level == automatic_level and level_warning:
                    warnings.append({'source_id': source.id, 'number': source.number, 'level': source.assigned_level or '', 'message': level_warning})
                if number < 1 or number > 11:
                    skipped.append({'source_id': source.id, 'reason': 'شماره محل باید بین ۱ تا ۱۱ باشد'})
                    continue
                if ClassSlot.objects.filter(term=target_term, number=number, day_type=day_type, time_slot=time_slot, is_online=is_online).exists():
                    skipped.append({'source_id': source.id, 'reason': f'محل {number} در ترم مقصد برای روز و ساعت انتخاب‌شده قبلاً وجود دارد'})
                    continue
                carry_flag = row.get('carry_students', True)
                if isinstance(carry_flag, str):
                    carry_flag = carry_flag.strip().lower() not in ('0', 'false', 'no', '')
                target = ClassSlot.objects.create(
                    term=target_term, number=number, title=source.title, day_type=day_type,
                    time_slot=time_slot, gender=gender, is_online=is_online,
                    meeting_link=str(row.get('meeting_link') or ''), notes=source.notes, capacity=source.capacity, teacher_name=teacher_name,
                    previous_teacher_name=source.teacher_name or '', assigned_level=assigned_level,
                    carried_from_slot=source, carry_students_from_source=bool(carry_flag),
                    schedule_kind=schedule_kind, schedule_days=schedule_days,
                    delivery_pattern=delivery_pattern, rotation_group='', current_count=0,
                )
                carried, student_skips = 0, []
                if carry_flag:
                    carried, student_skips = self._carry_students(source, target, request.user)
                    students_carried_total += carried
                    for item in student_skips:
                        warnings.append({'source_id': source.id, 'number': source.number, 'level': source.assigned_level or '', 'message': item})
                created_targets.append(target)
                created.append({
                    'source_id': source.id, 'target': ClassSlotSerializer(target).data,
                    'students_carried': carried, 'students_skipped': len(student_skips), 'carry_students': bool(carry_flag),
                })
            # فایل پیگیریِ خودکارِ انتقالی‌های منتظر ثبت‌نام (ارجاع/چک‌مارک/توضیحات در پنل «استخراج ریزشی»)
            followup_list = sync_carryover_followup_list(created_targets, None if legacy_source else source_term, target_term, request.user) if students_carried_total else None
        message = f'{len(created)} کلاس به ترم مقصد منتقل شد'
        if students_carried_total:
            message += f' و {students_carried_total} دانش‌آموز در کلاس‌های جدید ثبت‌نام شدند'
        if followup_list:
            message += f' — فایل پیگیری «{followup_list.name}» خودکار ذخیره شد'
        return Response({'message': message, 'created': created, 'skipped': skipped, 'warnings': warnings, 'students_carried': students_carried_total, 'followup_list_id': followup_list.id if followup_list else None})

    @staticmethod
    def _carry_students(source, target, user=None, only_registered=False, enrollment_ids=None, include_unverified=False):
        """ثبت‌نام دانش‌آموزان تاییدشدهٔ کلاس مبدا در کلاس مقصد (کپی؛ ثبت‌نام ترم مبدا حفظ می‌شود).

        قواعد: هر کد ملی در یک ترم فقط یک کلاس؛ جنسیت باید با کلاس مقصد همخوان باشد (کلاس مختلط آزاد است).
        شهریهٔ ترم جدید صفر ثبت می‌شود تا پرداخت ترم قبل دوباره در گزارش مالی حساب نشود.
        """
        carried, skips = 0, []
        enrollments = source.enrollments.select_related('student').order_by('created_at')
        if not include_unverified:
            enrollments = enrollments.filter(payment_verified=True)
        if only_registered:
            enrollments = enrollments.exclude(is_carryover=True, carryover_confirmed=False)
        if enrollment_ids is not None:
            enrollments = enrollments.filter(pk__in=enrollment_ids)
        for enrollment in enrollments:
            student = enrollment.student
            name = student.get_full_name() or student.username
            if target.gender != ClassSlot.Gender.MIXED and student.gender and (
                (target.gender == ClassSlot.Gender.GIRLS and student.gender != 'female') or
                (target.gender == ClassSlot.Gender.BOYS and student.gender != 'male')
            ):
                skips.append(f'«{name}» منتقل نشد: جنسیت با کلاس مقصد همخوانی ندارد')
                continue
            duplicate = _same_term_enrollments(target, [student.id]).first()
            if duplicate:
                skips.append(f'«{name}» منتقل نشد: قبلاً در ترم مقصد در {_enrollment_class_label(duplicate.class_slot)} ثبت‌نام شده است')
                continue
            ClassSlotEnrollment.objects.create(
                class_slot=target, student=student, payment_method=enrollment.payment_method,
                tuition_amount=0, discount_percent=enrollment.discount_percent,
                is_carryover=True, carryover_confirmed=False, carried_from_term=source.term,
            )
            # دانش‌آموز منتقل‌شده تا ثبت‌نام قطعی «ثبت‌نام‌نشده و بدهکار» است
            create_awaiting_debtor(student, target, source.term, user)
            carried += 1
        return carried, skips


class UpdateCarryoverStudentsView(APIView):
    """ابتدا فهرست افراد قابل انتقال را نشان می‌دهد و فقط موارد تأییدشده را منتقل می‌کند."""
    permission_classes = [IsAuthenticated]

    def _get_terms(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return None, None, Response({'error': 'دسترسی به به‌روزرسانی زبان‌آموزان ندارید'}, status=status.HTTP_403_FORBIDDEN)
        data = request.query_params if request.method == 'GET' else request.data
        source_term_id = data.get('source_term_id')
        target_term_id = data.get('target_term_id')
        try:
            source_term = Term.objects.get(pk=source_term_id)
            target_term = Term.objects.get(pk=target_term_id)
        except (Term.DoesNotExist, TypeError, ValueError):
            return None, None, Response({'error': 'ترم مبدأ یا مقصد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        if source_term.id == target_term.id:
            return None, None, Response({'error': 'ترم مقصد باید با ترم مبدأ متفاوت باشد'}, status=status.HTTP_400_BAD_REQUEST)
        return source_term, target_term, None

    @staticmethod
    def _slot_payload(slot):
        return {
            'id': slot.id, 'number': slot.number, 'day_type': slot.day_type,
            'day_type_display': slot.day_type_display, 'time_slot': slot.time_slot,
            'gender': slot.gender, 'gender_display': slot.get_gender_display(),
            'teacher_name': slot.teacher_name, 'assigned_level': slot.assigned_level,
            'is_online': slot.is_online,
            'level_match': None,
        }

    @staticmethod
    def _allowed_levels(source):
        """سطح مناسب برای ترم بعد: سطح بعدیِ سطح کلاس مبدأ (اگر سطح پایانی/ناشناخته باشد، همان سطح). خالی = سطح مبدأ نامشخص."""
        raw = str(source.assigned_level or '').strip()
        if not raw:
            return set()
        try:
            nxt = _next_level_for_carryover(raw, {})[0]
        except Exception:
            nxt = raw
        return {str(nxt or raw).strip().casefold()}

    @staticmethod
    def _rank_targets(source, candidates):
        """
        کلاس‌های مناسب ترم مقصد را برای یک کلاس مبدأ امتیاز می‌دهد (بالاتر = مناسب‌تر). فقط کلاس‌هایی پیشنهاد می‌شوند که
        سطحشان با سطح فرد در ترم بعد (سطح بعدی سطح کلاس مبدأ) یکی باشد؛ جنسیت/مختلط پیش‌تر در candidates اعمال شده است.
        سطوح تطبیق: ۱) منتقل‌شده از همین کلاس ۲) همان محل/روز/ساعت ۳) استاد ترم قبل ۴) همان استاد در همان روز و ساعت
        ۵) همان روز و ساعت ۶) همان نوع روز.
        """
        def norm(value):
            return str(value or '').strip().casefold()
        allowed = UpdateCarryoverStudentsView._allowed_levels(source)
        teacher = norm(source.teacher_name)
        ranked = []
        for slot in candidates:
            if slot.is_online != source.is_online:
                continue
            if allowed and norm(slot.assigned_level) not in allowed:
                continue
            same_time = slot.day_type == source.day_type and slot.time_slot == source.time_slot
            score, why = 1, 'سطح مناسب ترم بعد'
            if slot.carried_from_slot_id == source.id:
                score, why = 100, 'کلاس منتقل‌شده از همین کلاس'
            elif slot.number == source.number and same_time:
                score, why = 80, 'همان محل، روز و ساعت'
            elif teacher and same_time and norm(slot.previous_teacher_name) == teacher:
                score, why = 70, 'استاد ترم قبل مطابق است'
            elif teacher and same_time and norm(slot.teacher_name) == teacher:
                score, why = 60, 'همان استاد در همان روز و ساعت'
            elif same_time:
                score, why = 40, 'سطح مناسب در همان روز و ساعت'
            elif slot.day_type == source.day_type:
                score, why = 20, 'سطح مناسب با همان نوع روز'
            ranked.append((slot, score, why))
        ranked.sort(key=lambda item: (-item[1], item[0].number, item[0].time_slot or ''))
        return ranked

    def get(self, request):
        source_term, target_term, error = self._get_terms(request)
        if error:
            return error
        source_slots = list(ClassSlot.objects.filter(term=source_term).order_by('id'))
        target_slots = list(ClassSlot.objects.filter(term=target_term).select_related('carried_from_slot').order_by('number', 'day_type', 'time_slot'))
        enrollments = ClassSlotEnrollment.objects.filter(
            class_slot__in=source_slots,
        ).exclude(is_carryover=True, carryover_confirmed=False).select_related('student', 'class_slot').order_by(
            'class_slot__number', 'student__last_name', 'student__first_name', 'id',
        )
        rows = []
        for enrollment in enrollments:
            source = enrollment.class_slot
            student = enrollment.student
            if student.gender == 'female':
                gender_targets = [slot for slot in target_slots if slot.gender in (ClassSlot.Gender.GIRLS, ClassSlot.Gender.MIXED)]
            elif student.gender == 'male':
                gender_targets = [slot for slot in target_slots if slot.gender in (ClassSlot.Gender.BOYS, ClassSlot.Gender.MIXED)]
            else:
                gender_targets = list(target_slots)
            ranked = self._rank_targets(source, gender_targets)
            matched_ids = {slot.id for slot, _score, _why in ranked}
            gender_targets = [slot for slot, _score, _why in ranked] + [slot for slot in gender_targets if slot.id not in {r[0].id for r in ranked}]
            suggested = ranked[0][0].id if ranked else None
            suggestion_reason = ranked[0][2] if ranked else ''
            if len(ranked) > 1 and ranked[1][1] == ranked[0][1]:
                suggestion_reason += ' — چند کلاس مشابه وجود دارد؛ لطفاً بررسی کنید'
            # تکرار در هر کلاس ترم مقصد مانع انتقال است، نه فقط همان کلاس پیشنهادی.
            existing = ClassSlotEnrollment.objects.filter(
                student=student, class_slot__term=target_term,
            ).select_related('class_slot').first()
            rows.append({
                'enrollment_id': enrollment.id,
                'student_id': student.id,
                'student_name': student.get_full_name() or student.username,
                'student_gender': student.gender or '',
                'source_class': self._slot_payload(source),
                'payment_verified': enrollment.payment_verified,
                'payment_status': 'تأییدشده' if enrollment.payment_verified else 'در انتظار تأیید پرداخت',
                'target_options': [dict(self._slot_payload(slot), level_match=(slot.id in matched_ids)) for slot in gender_targets],
                'next_level': next(iter(self._allowed_levels(source)), ''),
                'suggested_target_id': suggested,
                'suggestion_reason': suggestion_reason,
                'already_in_target': bool(existing),
                'existing_target_class': self._slot_payload(existing.class_slot) if existing else None,
            })
        return Response({
            'source_term': {'id': source_term.id, 'title': source_term.title},
            'target_term': {'id': target_term.id, 'title': target_term.title},
            'students': rows,
            'total': len(rows),
        })

    @transaction.atomic
    def post(self, request):
        source_term, target_term, error = self._get_terms(request)
        if error:
            return error
        items = request.data.get('items') or []
        if not isinstance(items, list) or not items:
            return Response({'error': 'هیچ زبان‌آموزی برای انتقال انتخاب نشده است'}, status=status.HTTP_400_BAD_REQUEST)

        selected_slots = {}
        carried_total, warnings, followup_targets = 0, [], set()
        seen_enrollment_ids = set()
        for item in items:
            try:
                enrollment_id = int(item.get('enrollment_id'))
                target_id = int(item.get('target_slot_id'))
            except (TypeError, ValueError, AttributeError):
                warnings.append('شناسهٔ زبان‌آموز یا کلاس مقصد نامعتبر است')
                continue
            if enrollment_id in seen_enrollment_ids:
                continue
            seen_enrollment_ids.add(enrollment_id)
            enrollment = ClassSlotEnrollment.objects.select_for_update().select_related('student', 'class_slot').filter(
                pk=enrollment_id, class_slot__term=source_term,
            ).exclude(is_carryover=True, carryover_confirmed=False).first()
            target = ClassSlot.objects.select_for_update().filter(pk=target_id, term=target_term).first()
            if not enrollment or not target:
                warnings.append(f'ردیف ثبت‌نام {enrollment_id} یا کلاس مقصد معتبر نیست')
                continue
            student = enrollment.student
            if target.gender != ClassSlot.Gender.MIXED and student.gender and (
                (target.gender == ClassSlot.Gender.GIRLS and student.gender != 'female') or
                (target.gender == ClassSlot.Gender.BOYS and student.gender != 'male')
            ):
                warnings.append(f'«{student.get_full_name()}»: جنسیت با کلاس مقصد همخوانی ندارد')
                continue
            carried, skips = CarryClassesToNextTermView._carry_students(
                enrollment.class_slot, target, request.user, only_registered=True,
                enrollment_ids=[enrollment.id], include_unverified=True,
            )
            carried_total += carried
            warnings.extend(skips)
            if carried:
                selected_slots[target.id] = target
        followup_list = sync_carryover_followup_list(list(selected_slots.values()), source_term, target_term, request.user) if selected_slots else None
        return Response({
            'message': f'{carried_total} زبان‌آموز در ترم مقصد ثبت شد',
            'classes_updated': len(selected_slots),
            'students_carried': carried_total,
            'warnings': warnings,
            'followup_list_id': followup_list.id if followup_list else None,
        })


class TermDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE یک ترم — مثلاً برای اصلاح تاریخ شروع/پایان"""
    permission_classes = [IsAuthenticated]
    serializer_class = TermSerializer
    queryset = Term.objects.all()

    def update(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class TermHolidayListView(generics.ListCreateAPIView):
    """
    GET: لیست تعطیلات رسمیِ ثبت‌شده برای یک ترم / POST: ثبت یک تاریخ تعطیلی رسمیِ جدید برای آن ترم.
    هر تاریخی که اینجا ثبت شود و روی روز برگزاریِ یکی از کلاس‌های آن ترم بیفتد (زوج/فرد/یک‌روزه)،
    خودکار از محاسبه‌ی تاریخ جلسات آن کلاس حذف می‌شود — همه‌جا: پنل، اپ استاد، اپ دانش‌آموز،
    حضور و غیاب آنلاین (QR) و جلسات ساب استادان.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TermHolidaySerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'class-management'):
            return TermHoliday.objects.none()
        return TermHoliday.objects.filter(term_id=self.kwargs['term_id'])

    def perform_create(self, serializer):
        serializer.save(term_id=self.kwargs['term_id'])

    def create(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        if not Term.objects.filter(pk=self.kwargs['term_id']).exists():
            return Response({'error': 'ترم پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        from django.db import IntegrityError
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError:
            return Response({'error': 'این تاریخ قبلاً به‌عنوان تعطیلی رسمیِ همین ترم ثبت شده است'}, status=status.HTTP_400_BAD_REQUEST)


class TermHolidayDetailView(generics.DestroyAPIView):
    """DELETE: حذف یک تاریخ تعطیلی رسمی از ترم — با حذف آن، جلسه‌ی حذف‌شده دوباره به تقویم برمی‌گردد."""
    permission_classes = [IsAuthenticated]
    serializer_class = TermHolidaySerializer
    queryset = TermHoliday.objects.all()

    def destroy(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class ClassSlotDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ClassSlotSerializer
    queryset = ClassSlot.objects.all()

    def update(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        obj = self.get_object()

        # خواسته: ویرایش کلاس حتی وقتی دانش‌آموز ثبت‌نام‌شده دارد مجاز است؛ فقط «حذف» کلاس مسدود می‌شود.
        # استثنا: تغییر جنسیت کلاس فقط وقتی مجاز است که هیچ دانش‌آموزی در کلاس نباشد (حذف یا استرداد شده باشند).
        new_gender = request.data.get('gender')
        if new_gender not in (None, '') and new_gender != obj.gender:
            enrolled_count = obj.enrollments.count()
            if enrolled_count:
                return Response(
                    {'error': f'این کلاس {enrolled_count} دانش‌آموز ثبت‌نام‌شده دارد — برای تغییر جنسیت کلاس ابتدا باید همه‌ی دانش‌آموزان حذف یا مسترد شوند'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # خواسته: توی هر ردیفِ روز+ساعت (مثلاً همه‌ی کلاس‌های زوج ساعت ۳:۴۵ الی ۵:۱۵)، یک استاد
        # فقط می‌تواند همزمان روی یک کلاس باشد — نباید بین چند اتاق در همان روز/ساعت تداخل داشته باشد
        new_teacher = (request.data.get('teacher_name') or '').strip()
        if new_teacher:
            conflict = ClassSlot.objects.filter(
                day_type=obj.day_type, time_slot=obj.time_slot, term=obj.term,
                teacher_name__iexact=new_teacher,
            ).exclude(pk=obj.pk).first()
            if conflict:
                return Response(
                    {'error': f'استاد «{new_teacher}» همین الان در همین روز و ساعت روی کلاس شماره {conflict.number} تعریف شده — یک استاد نمی‌تواند همزمان روی دو کلاس باشد'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        obj = self.get_object()

        # خواسته: تا وقتی کلاس دانش‌آموز ثبت‌نام‌شده دارد، اجازه‌ی حذف داده نمی‌شود
        enrolled_count = obj.enrollments.count()
        if enrolled_count:
            return Response(
                {'error': f'این کلاس {enrolled_count} دانش‌آموز ثبت‌نام‌شده دارد — تا زمانی که دانش‌آموز(ها) از کلاس حذف یا مسترد نشوند، امکان حذف این کلاس وجود ندارد'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().destroy(request, *args, **kwargs)


THREE_DAY_TYPES = {ClassSlot.DayType.EVEN, ClassSlot.DayType.ODD}
ONE_DAY_TYPES = {
    ClassSlot.DayType.THURSDAY_MORNING, ClassSlot.DayType.THURSDAY_EVENING,
    ClassSlot.DayType.FRIDAY, ClassSlot.DayType.FRIDAY_MORNING, ClassSlot.DayType.FRIDAY_EVENING,
}


def _location_types_compatible(source, target):
    """قواعد انتقال: سه‌روزه ↔ یک‌روزه ممکن است؛ زوج/فرد و جنسیت معمولاً باید سازگار باشند."""
    if source.is_online != target.is_online:
        return False
    if source.gender != target.gender:
        return False
    if source.day_type in THREE_DAY_TYPES and target.day_type in THREE_DAY_TYPES:
        return source.day_type == target.day_type
    if source.day_type in ONE_DAY_TYPES and target.day_type in ONE_DAY_TYPES:
        return source.day_type == target.day_type
    if (source.day_type in THREE_DAY_TYPES and target.day_type in ONE_DAY_TYPES) or (source.day_type in ONE_DAY_TYPES and target.day_type in THREE_DAY_TYPES):
        return True
    return source.day_type == target.day_type


def _swap_locations_compatible(source, target):
    """جابجایی فیزیکی محل بین هر دو کلاس متفاوت از همان ترم مجاز است (در همه‌ی روزها و
    ساعت‌ها) — فقط شماره‌ی محل بین دو رکورد جابجا می‌شود و بقیه‌ی مشخصات هر کلاس (روز،
    ساعت، استاد، سطح، جنسیت، حالت آنلاین/حضوری) دست‌نخورده با همان رکورد می‌ماند؛ یعنی اگر
    کلاس مقصد سطح/استاد داشته باشد، با همه‌ی مشخصاتش همراه محل جدید (شماره‌ی کلاس مبدا)
    باقی می‌ماند."""
    return source.term_id == target.term_id and source.number != target.number


class SwapClassLocationView(APIView):
    """جابجایی محل دو کلاس سازگار؛ هر رکورد کلاس تمام اطلاعات خودش را حفظ می‌کند."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی به جابجایی محل کلاس‌ها ندارید'}, status=status.HTTP_403_FORBIDDEN)
        target_id = request.data.get('target_slot_id')
        if not target_id or str(target_id) == str(pk):
            return Response({'error': 'یک کلاس مقصد متفاوت انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                source = ClassSlot.objects.select_for_update().get(pk=pk)
                target = ClassSlot.objects.select_for_update().get(pk=target_id)
                if source.term_id != target.term_id:
                    return Response({'error': 'کلاس مقصد باید متعلق به همان ترم کلاس مبدا باشد'}, status=status.HTTP_400_BAD_REQUEST)
                if source.number < 1 or source.number > 11 or target.number < 1 or target.number > 11:
                    return Response({'error': 'شمارهٔ محل هر دو کلاس باید بین ۱ تا ۱۱ باشد'}, status=status.HTTP_400_BAD_REQUEST)
                if not _swap_locations_compatible(source, target):
                    return Response({'error': 'کلاس مقصد باید متعلق به همان ترم کلاس مبدا باشد و شماره‌ی متفاوتی داشته باشد'}, status=status.HTTP_400_BAD_REQUEST)
                source_number, target_number = source.number, target.number
                temporary_number = (ClassSlot.objects.order_by('-number').values_list('number', flat=True).first() or 0) + 1000000
                source.number = temporary_number
                source.save(update_fields=['number', 'updated_at'])
                target.number = source_number
                target.save(update_fields=['number', 'updated_at'])
                source.number = target_number
                source.save(update_fields=['number', 'updated_at'])
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس مبدا یا مقصد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'message': f'محل کلاس {source_number} و کلاس {target_number} با موفقیت جابجا شد', 'source': ClassSlotSerializer(source).data, 'target': ClassSlotSerializer(target).data})


class TransferClassLocationView(APIView):
    """انتقال یک کلاس به محل خالی مقصد؛ اطلاعات آموزشی کلاس مبدا همراه خود کلاس می‌ماند."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی به انتقال کلاس ندارید'}, status=status.HTTP_403_FORBIDDEN)
        target_id = request.data.get('target_slot_id')
        force_compatibility = request.data.get('force_compatibility') is True
        try:
            with transaction.atomic():
                source = ClassSlot.objects.select_for_update().get(pk=pk)
                target = ClassSlot.objects.select_for_update().get(pk=target_id)
                if source.term_id != target.term_id:
                    return Response({'error': 'کلاس مقصد باید متعلق به همان ترم کلاس مبدا باشد'}, status=status.HTTP_400_BAD_REQUEST)
                if not _location_types_compatible(source, target):
                    # مدیر می‌تواند بعد از دیدن هشدار، فقط استثنای روز/جنسیت/ساعت را تایید کند؛
                    # حالت آنلاین/حضوری و خالی بودن مقصد همچنان اجباری است.
                    if not force_compatibility or source.is_online != target.is_online:
                        return Response({'error': 'روز/نوع روز یا جنسیت مقصد با کلاس مبدا سازگار نیست؛ برای ادامه باید یکی از گزینه‌های جایگزین را با تایید مدیر انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
                if target.number < 1 or target.number > 11 or target.number == source.number:
                    return Response({'error': 'شمارهٔ محل مقصد باید از ۱ تا ۱۱ و متفاوت از مبدا باشد'}, status=status.HTTP_400_BAD_REQUEST)
                if target.real_enrolled_count or target.current_count or target.assigned_level or target.teacher_name:
                    return Response({'error': 'محل مقصد خالی نیست؛ برای جابه‌جایی دو کلاس از دکمهٔ «جابجایی محل کلاس» استفاده کنید'}, status=status.HTTP_409_CONFLICT)
                old_location = {'number': source.number, 'day_type': source.day_type, 'time_slot': source.time_slot}
                destination_location = {'number': target.number, 'day_type': target.day_type, 'time_slot': target.time_slot}

                # انتقال واقعی: اطلاعات آموزشی/اجرایی و ثبت‌نام‌ها به رکورد مقصد می‌روند؛
                # رکورد مبدا به یک محل خالی با برنامهٔ قبلی خودش تبدیل می‌شود.
                class_fields = ['title', 'meeting_link', 'notes', 'capacity', 'teacher_name', 'assigned_level', 'current_count', 'gender', 'is_online', 'schedule_kind', 'schedule_days', 'delivery_pattern', 'rotation_group']
                for field in class_fields:
                    setattr(target, field, getattr(source, field))
                target.save(update_fields=class_fields + ['updated_at'])
                source.enrollments.update(class_slot=target)
                source.title = ''
                source.meeting_link = ''
                source.notes = ''
                source.capacity = 10
                source.teacher_name = ''
                source.assigned_level = ''
                source.current_count = 0
                source.save(update_fields=['title', 'meeting_link', 'notes', 'capacity', 'teacher_name', 'assigned_level', 'current_count', 'updated_at'])
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس مبدا یا مقصد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        suffix = ' با تایید استثناهای مدیر' if force_compatibility else ''
        return Response({'message': f'کلاس از محل {old_location["number"]} به محل {destination_location["number"]} منتقل شد{suffix}', 'source': ClassSlotSerializer(source).data, 'target': ClassSlotSerializer(target).data})


class AllocateClassesView(APIView):
    """POST: دکمه‌ی «تخصیص کلاس» — هر سطح ترجیحاً در یک کلاس؛ سرریز نیازمند تایید مدیر برمی‌گردد"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        serializer = AllocateClassesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        warnings, summary, pending_overflow = allocate_classes(
            levels=data['levels'],
            tolerance=data['tolerance'],
            thursday_only_count=data['thursday_only_count'],
            friday_only_count=data['friday_only_count'],
        )

        slots = ClassSlot.objects.all().order_by('number')
        return Response({
            'warnings': warnings,
            'summary': summary,
            'pending_overflow': pending_overflow,
            'slots': ClassSlotSerializer(slots, many=True).data,
        })


def _distribute_unassigned(level_name, category, day_type, total, exclude_ids):
    """
    برخلاف _auto_distribute_surplus (که از یک کلاسِ موجودِ مازاد نفر برمی‌دارد)، این یکی برای
    نفراتی است که هنوز اصلاً روی هیچ کلاسی ننشسته‌اند (باقیمانده‌ی pending_overflow که مدیر
    تصمیم گرفت به کلاس دومِ انتخابی‌اش نبرد) — مستقیم بین کلاس‌های کاندیدِ دیگر (هم‌سطح/هم‌دسته)
    پخش می‌شود تا هیچ‌کس گم نشود.
    """
    moves = []
    if total <= 0:
        return moves, 0
    others = ClassSlot.objects.exclude(pk__in=exclude_ids)
    if category:
        candidates = [s for s in others if category & s.time_category() and (not s.assigned_level or s.assigned_level == level_name)]
    else:
        candidates = [s for s in others if s.day_type == day_type and (not s.assigned_level or s.assigned_level == level_name)]
    candidates = [s for s in candidates if (s.capacity - s.current_count) > 0]
    candidates.sort(key=lambda s: -(s.capacity - s.current_count))

    remaining = total
    for cand in candidates:
        if remaining <= 0:
            break
        room = cand.capacity - cand.current_count
        take = min(room, remaining)
        if take <= 0:
            continue
        cand.assigned_level = cand.assigned_level or level_name
        cand.current_count += take
        cand.save()
        moves.append({'target_slot_id': cand.id, 'target_number': cand.number, 'target_time_slot': cand.time_slot, 'moved': take})
        remaining -= take

    return moves, remaining


class ConfirmOverflowView(APIView):
    """
    POST: تایید مدیر برای نشاندن باقیمانده‌ی یک سطح (که در یک کلاس جا نشد) در کلاس دوم.
    قبلاً کل «remaining_count» را بدون چک ظرفیت در کلاس مقصدِ انتخابی می‌ریخت — که خودش
    می‌توانست کلاس مقصد را مازاد کند. حالا دقیقاً مثل «تصمیم برای مازاد»: عدد ارسالی
    (پیش‌فرض کل باقیمانده، ولی مدیر می‌تواند کمتر هم بفرستد) تا سقف جای خالی کلاس مقصد
    در آن نشانده می‌شود؛ اگر چیزی باقی ماند، به‌جای رهاشدن یا مازادکردن کلاس مقصد، بلافاصله
    با همان `_auto_distribute_surplus` بین کلاس‌های موجودِ هم‌سطح دیگر پخش می‌شود.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        serializer = ConfirmOverflowSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            target = ClassSlot.objects.get(pk=data['target_slot_id'])
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس مقصد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        if target.assigned_level and target.assigned_level != data['level']:
            return Response({'error': f"این کلاس قبلاً به سطح «{target.assigned_level}» اختصاص دارد"}, status=status.HTTP_400_BAD_REQUEST)

        requested = data['count']
        # کل باقیمانده‌ی واقعی این سطح — اگر مدیر نفرستد (سازگاری با فراخوانی‌های قدیمی)، همان count فرض می‌شود
        total_remaining = data.get('remaining_count', requested)
        if requested > total_remaining:
            return Response({'error': f'عدد وارد‌شده ({requested}) نمی‌تواند از کل باقیمانده ({total_remaining} نفر) بیشتر باشد'}, status=status.HTTP_400_BAD_REQUEST)

        room = max(0, target.capacity - target.current_count)
        placed_in_target = min(requested, room)
        target.assigned_level = data['level']
        target.current_count += placed_in_target
        target.save()

        # هرکس که یا (۱) در همین درخواست بود ولی جای کلاس مقصد کم آورد، یا (۲) مدیر از همان
        # اول تصمیم گرفت به کلاس مقصد نبردش (چون count کمتر از remaining_count فرستاده) —
        # هیچ‌کدام نباید گم شوند؛ هر دو با هم بین بقیه‌ی کاندیدها پخش می‌شوند.
        not_placed_in_target = (requested - placed_in_target) + (total_remaining - requested)
        category = target.time_category()
        moves, still_remaining = _distribute_unassigned(
            data['level'], category, target.day_type, not_placed_in_target, exclude_ids=[target.id]
        )

        return Response({
            'target': ClassSlotSerializer(target).data,
            'placed_in_target': placed_in_target,
            'auto_distributed_moves': moves,
            'remaining_unplaced': still_remaining,
        })


class TransferSurplusView(APIView):
    """POST: انتقال مازاد یک کلاس پرشده به کلاس دیگر (خالی یا هم‌سطح) — با تایید مدیر از فرانت"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            source = ClassSlot.objects.get(pk=pk)
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        surplus = source.surplus
        if surplus <= 0:
            return Response({'error': 'این کلاس مازادی ندارد'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = TransferSurplusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_id = serializer.validated_data.get('target_slot_id')
        # عدد دلخواه مدیر: می‌تواند کمتر یا بیشتر از خودِ مازاد باشد (تا سقف کل نفرات کلاس مبدا)
        move_amount = serializer.validated_data.get('count') or surplus
        if move_amount > source.current_count:
            return Response({'error': f'تعداد نمی‌تواند از تعداد فعلی کلاس مبدا ({source.current_count} نفر) بیشتر باشد'}, status=status.HTTP_400_BAD_REQUEST)

        if target_id:
            # حالت دستی: مدیر خودش یک کلاس مقصد مشخص انتخاب کرده — فقط همان یکی پر می‌شود
            try:
                target = ClassSlot.objects.get(pk=target_id)
            except ClassSlot.DoesNotExist:
                return Response({'error': 'کلاس مقصد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
            room = target.capacity - target.current_count
            if room <= 0:
                return Response({'error': 'کلاس مقصد ظرفیت خالی ندارد'}, status=status.HTTP_400_BAD_REQUEST)
            move_count = min(move_amount, room)
            source.current_count -= move_count
            target.assigned_level = target.assigned_level or source.assigned_level
            target.current_count += move_count
            source.save()
            target.save()
            return Response({
                'moved': move_count,
                'remaining_surplus': source.surplus,
                'source': ClassSlotSerializer(source).data,
                'moves': [{'target_slot_id': target.id, 'target_number': target.number, 'target_time_slot': target.time_slot, 'moved': move_count}],
            })

        # حالت خودکار: عدد درخواستی بین چند کلاس موجودِ هم‌سطح و هم‌ساعت (هرکدام تا سقف جای خالی‌اش) پخش می‌شود
        moves, still_remaining = _auto_distribute_surplus(source, move_amount)
        if not moves:
            return Response({'error': 'کلاس مناسبی برای تخصیص خودکار پیدا نشد — کلاس مقصد را دستی انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'moved': move_amount - still_remaining,
            'remaining_surplus': still_remaining,
            'source': ClassSlotSerializer(source).data,
            'moves': moves,
        })


class SpinOffSurplusView(APIView):
    """
    POST: به‌جای انتقال به یک کلاس موجود، برای مازاد یک کلاس پرشده، یک کلاس تازه می‌سازد —
    تعداد نفرات و نام استاد کلاس جدید از مدیر پرسیده می‌شود؛ روز/ساعت/ظرفیت هم قابل تعیین‌اند
    (اگر داده نشوند، بر اساس دسته‌ی ساعتی کلاس مبدا و تعداد درخواستی پیش‌فرض گذاشته می‌شوند).
    کلاس تازه بلافاصله به لیست کلاس‌ها اضافه می‌شود و در تخصیص‌های بعدی هم قابل استفاده است.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            source = ClassSlot.objects.get(pk=pk)
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        if source.surplus <= 0:
            return Response({'error': 'این کلاس مازادی ندارد'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = SpinOffSurplusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        count = data['count']
        if count > source.current_count:
            return Response({'error': f'تعداد نمی‌تواند از تعداد فعلی کلاس مبدا ({source.current_count} نفر) بیشتر باشد'}, status=status.HTTP_400_BAD_REQUEST)

        day_type = data.get('day_type') or source.day_type
        time_slot = data.get('time_slot') or source.time_slot
        capacity = data.get('capacity') or count
        number = data.get('number')
        if not number:
            last = ClassSlot.objects.order_by('-number').first()
            number = (last.number + 1) if last else 1
        if ClassSlot.objects.filter(number=number, day_type=day_type, time_slot=time_slot).exists():
            return Response({'error': f'کلاس شماره {number} دقیقاً در همین روز/ساعت از قبل وجود دارد — ساعت یا شماره‌ی دیگری بدهید'}, status=status.HTTP_400_BAD_REQUEST)

        new_slot = ClassSlot.objects.create(
            number=number, day_type=day_type, time_slot=time_slot, capacity=capacity,
            teacher_name=data.get('teacher_name', ''),
            assigned_level=source.assigned_level, current_count=count,
        )
        source.current_count -= count
        source.save()

        # اگر بعد از ساخت کلاس جدید هنوز روی کلاس مبدا مازاد باقی مانده (چون مدیر عدد کمتر
        # از کل مازاد را برای کلاس جدید انتخاب کرده)، باقیمانده به‌صورت خودکار بین کلاس‌های
        # موجودِ هم‌سطح و هم‌ساعت پخش می‌شود؛ هرچه پخش نشد همچنان روی کلاس مبدا باقی می‌ماند
        # و در پاسخ به‌عنوان remaining_surplus مشخص می‌شود.
        remainder = source.surplus
        moves, still_remaining = _auto_distribute_surplus(source, remainder)
        source.refresh_from_db()

        return Response({
            'moved': count,
            'source': ClassSlotSerializer(source).data,
            'new_class': ClassSlotSerializer(new_slot).data,
            'auto_distributed_moves': moves,
            'remaining_surplus': still_remaining,
        }, status=status.HTTP_201_CREATED)


_PERSIAN_LATIN = {
    'ا': 'a', 'آ': 'a', 'ب': 'b', 'پ': 'p', 'ت': 't', 'ث': 's', 'ج': 'j', 'چ': 'ch',
    'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'z', 'ر': 'r', 'ز': 'z', 'ژ': 'zh', 'س': 's',
    'ش': 'sh', 'ص': 's', 'ض': 'z', 'ط': 't', 'ظ': 'z', 'ع': '', 'غ': 'gh', 'ف': 'f',
    'ق': 'gh', 'ک': 'k', 'گ': 'g', 'ل': 'l', 'م': 'm', 'ن': 'n', 'و': 'v', 'ه': 'h',
    'ی': 'y', 'ي': 'y', 'ئ': 'y', 'ء': '', 'ة': 'h',
}

_COMMON_ENGLISH_NAMES = {
    'محمد': 'Mohammad', 'محمود': 'Mahmoud', 'علی': 'Ali', 'رضا': 'Reza', 'حسین': 'Hossein',
    'مهدی': 'Mehdi', 'امیر': 'Amir', 'امیرحسین': 'Amirhossein', 'امیر حسین': 'Amirhossein',
    'احمد': 'Ahmad', 'احسان': 'Ehsan', 'سعید': 'Saeed', 'سجاد': 'Sajjad', 'مجید': 'Majid',
    'مصطفی': 'Mostafa', 'ابوالفضل': 'Abolfazl', 'یوسف': 'Yousef', 'آرین': 'Arian',
    'پارسا': 'Parsa', 'نیما': 'Nima', 'کیان': 'Kian', 'آریا': 'Aria', 'سام': 'Sam', 'اشکان': 'Ashkan',
    'فاطمه': 'Fatemeh', 'زهرا': 'Zahra', 'مریم': 'Maryam', 'سارا': 'Sara', 'نازنین': 'Nazanin',
    'نرگس': 'Narges', 'سمیه': 'Somayeh', 'الهام': 'Elham', 'نگار': 'Negar', 'کیانا': 'Kiana',
    'یاسمن': 'Yasaman', 'مبینا': 'Mobina', 'مهسا': 'Mahsa', 'مهتاب': 'Mahtab', 'حدیث': 'Hadis',
    'ریحانه': 'Reyhaneh', 'ترانه': 'Taraneh', 'پرنیا': 'Parnia', 'آتنا': 'Atena', 'سحر': 'Sahar',
}

def _english_name(value):
    text = str(value or '').strip()
    normalized = ' '.join(text.replace('\u200c', ' ').split())
    if normalized in _COMMON_ENGLISH_NAMES:
        return _COMMON_ENGLISH_NAMES[normalized]
    words = []
    for word in normalized.split():
        if word in _COMMON_ENGLISH_NAMES:
            words.append(_COMMON_ENGLISH_NAMES[word])
            continue
        result = ''.join(_PERSIAN_LATIN.get(char, char if char.isascii() else '') for char in word)
        words.append(result)
    return ' '.join(words).strip().title()


_GRADUATE_INFO_TEXT_FIELDS = (
    'first_name', 'last_name', 'full_name_en', 'national_code', 'phone',
    'level', 'teacher', 'email', 'gender', 'age_group',
)
_GRADUATE_GRADE_FIELDS = (
    'previous_term_grade_1', 'previous_term_grade_2', 'previous_term_grade_3',
)


def _graduate_record_data(record):
    data = {field: getattr(record, field) or '' for field in _GRADUATE_INFO_TEXT_FIELDS}
    data.update({
        'graduation_date': record.graduation_date.isoformat() if record.graduation_date else '',
        'average_grade': str(record.average_grade) if record.average_grade is not None else '',
        'sent_to_center': record.sent_to_center,
        'next_term': record.next_term,
        'manual': record.manual,
        'student_id': record.student_id or '',
    })
    data.update({field: str(getattr(record, field)) if getattr(record, field) is not None else '' for field in _GRADUATE_GRADE_FIELDS})
    return data


def _save_graduate_record(term, row, preserve_existing=False):
    from django.contrib.auth import get_user_model

    manual = row.get('manual') is True
    raw_id = row.get('id')
    student = None
    if manual:
        record_key = str(raw_id or '').strip()
        if not record_key.startswith('manual-'):
            raise ValueError('شناسهٔ ردیف دستی معتبر نیست.')
        student_id = row.get('student_id')
        if student_id:
            student = get_user_model().objects.filter(pk=student_id, role='student').first()
    else:
        try:
            student_id = int(raw_id)
        except (TypeError, ValueError):
            raise ValueError('شناسهٔ زبان‌آموز معتبر نیست.')
        student = get_user_model().objects.filter(pk=student_id, role='student').first()
        if not student:
            raise ValueError('زبان‌آموز در سامانه پیدا نشد.')
        record_key = f'student:{student.pk}'

    record, created = GraduatedStudentInfo.objects.get_or_create(
        term=term, record_key=record_key,
        defaults={'student': student, 'manual': manual},
    )
    if preserve_existing and not created:
        return record
    record.student = student
    record.manual = manual
    record.excluded = False
    for field in _GRADUATE_INFO_TEXT_FIELDS:
        setattr(record, field, str(row.get(field) or '').strip())
    record.next_term = row.get('next_term') is True
    record.sent_to_center = row.get('sent_to_center') is True
    raw_date = str(row.get('graduation_date') or '').strip()
    record.graduation_date = parse_date(raw_date) if raw_date else None
    if raw_date and record.graduation_date is None:
        raise ValueError('تاریخ میلادی فارغ‌التحصیلی معتبر نیست.')
    for field in _GRADUATE_GRADE_FIELDS:
        raw_grade = str(row.get(field) or '').strip()
        try:
            value = Decimal(raw_grade) if raw_grade else None
        except InvalidOperation:
            raise ValueError('نمره باید عددی باشد.')
        if value is not None and (not value.is_finite() or value < 0 or value > Decimal('9999.99')):
            raise ValueError('مقدار نمره معتبر نیست.')
        setattr(record, field, value)
    record.save()
    return record


class GraduatedStudentsView(APIView):
    """دانش‌آموزان ثبت‌نام‌شده در سطح پایانی هر ردهٔ سنیِ یک ترم."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        term_id = request.query_params.get('term_id')
        if term_id:
            term = Term.objects.filter(pk=term_id).first()
        else:
            term = Term.objects.order_by('-year', '-term_number', '-id').first()
        if not term:
            return Response({'term_id': None, 'term_title': '', 'rows': []})
        level_groups = {
            'kids': {'current': ('i5', 'u5'), 'next': ('i4', 'u4')},
            'teen': {'current': ('teen15',), 'next': ('teen14',)},
            'adult': {'current': ('606', '406'), 'next': ('605', '405')},
        }
        all_levels = [level for group in level_groups.values() for levels in group.values() for level in levels]
        age_rank = {'kids': 0, 'teen': 1, 'adult': 2}
        gender_rank = {'female': 0, 'male': 1}
        rows_by_student = {}
        enrollments = ClassSlotEnrollment.objects.filter(
            class_slot__term=term,
            student__role='student',
            payment_verified=True,
            class_slot__assigned_level__in=all_levels,
        ).select_related('student', 'class_slot').order_by(
            'student__first_name', 'student__last_name', 'class_slot__number', 'class_slot__id'
        )
        for enrollment in enrollments:
            student, slot = enrollment.student, enrollment.class_slot
            level = (slot.assigned_level or '').strip()
            age_group = next((group for group, spec in level_groups.items() if any(level.casefold() == terminal.casefold() for levels in spec.values() for terminal in levels)), 'adult')
            next_term = any(level.casefold() == terminal.casefold() for terminal in level_groups[age_group]['next'])
            if student.id in rows_by_student:
                current = rows_by_student[student.id]
                if slot.teacher_name and slot.teacher_name not in current['teacher']:
                    current['teacher'] = f"{current['teacher']}، {slot.teacher_name}" if current['teacher'] else slot.teacher_name
                continue
            rows_by_student[student.id] = {
                'id': student.id,
                'first_name': student.first_name or '', 'last_name': student.last_name or '',
                'first_name_en': _english_name(student.first_name), 'last_name_en': _english_name(student.last_name),
                'father_name': student.father_name or '', 'national_code': student.national_code or '',
                'phone': student.phone or '', 'level': level, 'teacher': slot.teacher_name or '',
                'email': getattr(student, 'email', '') or '',
                'gender': student.gender or '', 'age_group': age_group, 'next_term': next_term,
            }
        # بررسی می‌کنیم فرد در سه ترم آخر تا سطح فعلی، مسیر سطح‌ها را به‌ترتیب طی کرده باشد.
        history_terms = list(Term.objects.filter(
            Q(year__lt=term.year) | Q(year=term.year, term_number__lte=term.term_number)
        ).order_by('-year', '-term_number', '-id')[:3])
        history_terms.reverse()
        candidate_ids = list(rows_by_student.keys())
        history = {}
        if candidate_ids and history_terms:
            history_qs = ClassSlotEnrollment.objects.filter(
                student_id__in=candidate_ids, class_slot__term_id__in=[item.id for item in history_terms], payment_verified=True,
            ).select_related('class_slot')
            for item in history_qs:
                history.setdefault(item.student_id, {}).setdefault(item.class_slot.term_id, set()).add((item.class_slot.assigned_level or '').strip().casefold())
        try:
            from level_tests.models import StandardLevel
            standard_levels = list(StandardLevel.objects.all().order_by('age_group', 'order', 'code'))
        except Exception:
            standard_levels = []
        fallback_sequences = {
            'kids': [f'{prefix}{number}' for prefix in ('i', 'u') for number in range(1, 6)],
            'teen': ['teenstarter'] + [f'teen{number}' for number in range(1, 16)],
            'adult': [str(number) for number in range(101, 607)],
        }
        for row in rows_by_student.values():
            siblings = [item.code for item in standard_levels if item.age_group == row['age_group']]
            sequence = siblings or fallback_sequences[row['age_group']]
            target_index = next((index for index, code in enumerate(sequence) if code.casefold() == row['level'].casefold()), -1)
            expected = sequence[target_index - 2:target_index + 1] if target_index >= 2 else []
            student_history = history.get(row['id'], {})
            has_valid_sequence = len(history_terms) == 3 and len(expected) == 3 and all(
                any(level == expected[position].casefold() for level in student_history.get(history_terms[position].id, set()))
                for position in range(3)
            )
            row['sequence_warning'] = not has_valid_sequence
            row['sequence_warning_text'] = 'هشدار مهم: توالی سه‌ترمی سطح‌ها کامل یا به‌ترتیب نیست.' if row['sequence_warning'] else ''
        saved_records = list(GraduatedStudentInfo.objects.filter(term=term).select_related('student'))
        saved_by_key = {item.record_key: item for item in saved_records if not item.excluded}
        excluded_keys = {item.record_key for item in saved_records if item.excluded}
        empty_extra = {
            'graduation_date': '', 'previous_term_grade_1': '', 'previous_term_grade_2': '',
            'previous_term_grade_3': '', 'average_grade': '', 'sent_to_center': False,
        }
        for row in rows_by_student.values():
            record = saved_by_key.get(f"student:{row['id']}")
            if record:
                row.update(_graduate_record_data(record))
            else:
                row.update(empty_extra)
                row['manual'] = False
        manual_rows = []
        for record in saved_records:
            if not record.manual or record.excluded:
                continue
            manual_row = _graduate_record_data(record)
            manual_row.update({
                'id': record.record_key, 'sequence_warning': False, 'sequence_warning_text': '',
                'first_name_en': _english_name(record.first_name), 'last_name_en': _english_name(record.last_name),
            })
            manual_rows.append(manual_row)
        # ترتیب: بزرگسال، نوجوان، کودک؛ داخل هر ردهٔ سنی افراد همسطح کنار هم می‌مانند.
        age_rank = {'adult': 0, 'teen': 1, 'kids': 2}
        level_rank = {code: index for index, code in enumerate(
            ('406', '606', '405', '605', 'teen15', 'teen14', 'i5', 'u5', 'i4', 'u4')
        )}
        visible_student_rows = [row for row in rows_by_student.values() if f"student:{row['id']}" not in excluded_keys]
        rows = sorted([*visible_student_rows, *manual_rows], key=lambda row: (
            age_rank.get(row['age_group'], 9), int(row.get('next_term', False)), level_rank.get(row['level'].casefold(), 99),
            gender_rank.get(row['gender'], 9), row['last_name'], row['first_name'], str(row['id']),
        ))
        from django.contrib.auth import get_user_model
        User = get_user_model()
        teachers = sorted({
            f"{teacher.first_name or ''} {teacher.last_name or ''}".strip()
            for teacher in User.objects.filter(role__in=User.TEACHER_LIKE_ROLES)
            if f"{teacher.first_name or ''} {teacher.last_name or ''}".strip()
        })
        return Response({'term_id': term.id, 'term_title': term.title, 'rows': rows, 'count': len(rows), 'teachers': teachers})

    def post(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        term_id = request.data.get('term_id')
        term = Term.objects.filter(pk=term_id).first() if term_id else None
        if not term:
            return Response({'error': 'ترم معتبر انتخاب نشده است.'}, status=status.HTTP_400_BAD_REQUEST)
        action = request.data.get('action', 'save')
        if action == 'delete':
            raw_id = str(request.data.get('row_id') or '').strip()
            is_manual = request.data.get('manual') is True
            if is_manual:
                if not raw_id.startswith('manual-'):
                    return Response({'error': 'شناسهٔ ردیف دستی معتبر نیست.'}, status=status.HTTP_400_BAD_REQUEST)
                deleted, _ = GraduatedStudentInfo.objects.filter(term=term, record_key=raw_id, manual=True).delete()
                if not deleted:
                    return Response({'error': 'ردیف دستی پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
                return Response({'deleted': True, 'manual': True})
            try:
                student_id = int(raw_id)
            except (TypeError, ValueError):
                return Response({'error': 'شناسهٔ زبان‌آموز معتبر نیست.'}, status=status.HTTP_400_BAD_REQUEST)
            if not get_user_model().objects.filter(pk=student_id, role='student').exists():
                return Response({'error': 'زبان‌آموز در سامانه پیدا نشد.'}, status=status.HTTP_404_NOT_FOUND)
            record, _ = GraduatedStudentInfo.objects.get_or_create(
                term=term, record_key=f'student:{student_id}',
                defaults={'student_id': student_id, 'manual': False},
            )
            record.excluded = True
            record.save(update_fields=['excluded', 'updated_at'])
            return Response({'deleted': True, 'manual': False})
        if action == 'legacy_import':
            rows = request.data.get('rows')
            if not isinstance(rows, list) or len(rows) > 5000:
                return Response({'error': 'اطلاعات انتقالی معتبر نیست.'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                with transaction.atomic():
                    saved = [_save_graduate_record(term, row, preserve_existing=True) for row in rows if isinstance(row, dict)]
            except ValueError as exc:
                return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            return Response({'migrated': len(saved)})
        if action != 'save' or not isinstance(request.data.get('row'), dict):
            return Response({'error': 'درخواست ذخیره‌سازی معتبر نیست.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            record = _save_graduate_record(term, request.data['row'])
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        response_row = _graduate_record_data(record)
        response_row.update({
            'id': record.record_key if record.manual else record.student_id,
            'sequence_warning': False,
            'sequence_warning_text': '',
            'first_name_en': _english_name(record.first_name),
            'last_name_en': _english_name(record.last_name),
        })
        return Response({'row': response_row}, status=status.HTTP_200_OK)


class GraduatedStudentLookupView(APIView):
    """پیشنهاد هوشمند برای ردیف دستی فارغ‌التحصیلان + ساخت شکل انگلیسی نام و نام‌خانوادگی.

    GET ?first_name=&last_name=&national_code=&phone= : حداکثر ۸ دانش‌آموز مطابق فیلدهای پرشده.
    پاسخ شامل first_name_en / last_name_en / full_name_en برای همان نام تایپ‌شده هم هست.
    """
    permission_classes = [IsAuthenticated]
    MAX_ROWS = 8

    def get(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        digits = StudentClassSearchView._digits_to_en
        variants = StudentClassSearchView._text_variants
        first = ' '.join(str(request.query_params.get('first_name', '')).split())
        last = ' '.join(str(request.query_params.get('last_name', '')).split())
        national_code = ''.join(ch for ch in digits(request.query_params.get('national_code', '')) if ch.isdigit())
        phone = ''.join(ch for ch in digits(request.query_params.get('phone', '')) if ch.isdigit())
        first_en, last_en = _english_name(first), _english_name(last)
        result = {
            'first_name_en': first_en, 'last_name_en': last_en,
            'full_name_en': f'{first_en} {last_en}'.strip(), 'matches': [],
        }
        if len(first) < 2 and len(last) < 2 and len(national_code) < 3 and len(phone) < 4:
            return Response(result)
        from django.contrib.auth import get_user_model
        students = get_user_model().objects.filter(role='student')
        for field, value in (('first_name', first), ('last_name', last)):
            if len(value) >= 2:
                cond = Q()
                for variant in variants(value):
                    cond |= Q(**{f'{field}__icontains': variant})
                students = students.filter(cond)
        if len(national_code) >= 3:
            students = students.filter(national_code__contains=national_code)
        if len(phone) >= 4:
            students = students.filter(phone__contains=phone)
        for student in students.order_by('last_name', 'first_name', 'id')[:self.MAX_ROWS]:
            fe, le = _english_name(student.first_name), _english_name(student.last_name)
            result['matches'].append({
                'id': student.id, 'first_name': student.first_name or '', 'last_name': student.last_name or '',
                'national_code': student.national_code or '', 'phone': student.phone or '',
                'email': getattr(student, 'email', '') or '', 'gender': student.gender or '',
                'first_name_en': fe, 'last_name_en': le, 'full_name_en': f'{fe} {le}'.strip(),
            })
        return Response(result)


class StudentClassSearchView(APIView):
    """GET ?q=&term=: جستجوی دانش‌آموز بر اساس کد ملی یا نام/نام‌خانوادگی در یک ترم.

    برای هر ثبت‌نامِ دانش‌آموز در آن ترم یک ردیف برمی‌گرداند: سطح (سطح کلاس)، شماره کلاس، روز، ساعت و استاد.
    اگر term فرستاده نشود، آخرین ترم (بزرگ‌ترین سال و شماره‌ی ترم) استفاده می‌شود.
    """
    permission_classes = [IsAuthenticated]
    MAX_ROWS = 200

    @staticmethod
    def _digits_to_en(value):
        table = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
        return str(value or '').translate(table)

    @staticmethod
    def _text_variants(token):
        """املای عربی/فارسی «ی» و «ک» را هم‌ارز می‌گیرد تا جستجو با هر دو شکل پیدا شود."""
        fa = token.replace('ي', 'ی').replace('ك', 'ک')
        ar = fa.replace('ی', 'ي').replace('ک', 'ك')
        return {token, fa, ar}

    def get(self, request):
        if not (can_view_menu(request.user, 'class-management') or can_edit_menu(request.user, 'class-management')):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        query = ' '.join(self._digits_to_en(request.query_params.get('q', '')).split())
        term_param = request.query_params.get('term')
        term = Term.objects.filter(pk=term_param).first() if term_param else None
        if not term:
            from leads.models import get_current_term
            term = get_current_term()
        if term_param and not term:
            return Response({'error': 'ترم پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        term_title = term.title if term else ''
        if not term or len(query) < 2:
            return Response({'term_id': term.id if term else None, 'term_title': term_title, 'count': 0, 'results': []})

        enrollments = ClassSlotEnrollment.objects.filter(class_slot__term=term).select_related('student', 'class_slot')
        if query.replace(' ', '').isdigit():
            enrollments = enrollments.filter(student__national_code__contains=query.replace(' ', ''))
        else:
            for token in query.split(' '):
                token_q = Q()
                for variant in self._text_variants(token):
                    token_q |= Q(student__first_name__icontains=variant) | Q(student__last_name__icontains=variant)
                enrollments = enrollments.filter(token_q)

        rows = []
        for enrollment in enrollments.order_by('student__last_name', 'student__first_name', 'class_slot__number')[:self.MAX_ROWS]:
            slot, student = enrollment.class_slot, enrollment.student
            rows.append({
                'student_id': student.id,
                'student_name': f'{student.first_name or ""} {student.last_name or ""}'.strip() or student.username,
                'first_name': student.first_name or '',
                'last_name': student.last_name or '',
                'national_code': student.national_code or '',
                'father_name': student.father_name or '',
                'gender': student.gender or '',
                'phone': student.phone or '',
                'level': slot.assigned_level or '',
                'class_number': slot.number,
                'day': slot.day_type_display,
                'time': slot.time_slot or '',
                'teacher': slot.teacher_name or '',
                'slot_id': slot.id,
                'payment_verified': enrollment.payment_verified,
            })
        return Response({'term_id': term.id, 'term_title': term_title, 'count': len(rows), 'results': rows})


class EnrollmentPulseView(APIView):
    """GET: «نبض» سبک ثبت‌نام‌ها برای اعلان صوتی سراسری — فقط دو عدد برای هر نوع ثبت‌نام تاییدشده
    (بزرگ‌ترین شناسه + تعداد). فرانت هر چند ثانیه می‌پرسد و اگر هر کدام زیاد شده باشد یعنی دانش‌آموز تازه‌ای
    (از هر سیستمی؛ دستی، اکسل، پرداخت تاییدشده، دوره‌ی آنلاین) ثبت‌نام شده است. حذف/استرداد صدا ندارد.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not (can_view_menu(request.user, 'class-management') or can_edit_menu(request.user, 'class-management')):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        slot_qs = ClassSlotEnrollment.objects.filter(payment_verified=True)
        course_qs = OnlineCourseEnrollment.objects.filter(payment_verified=True)
        slot_agg = slot_qs.aggregate(max_id=Max('id'), count=Count('id'))
        course_agg = course_qs.aggregate(max_id=Max('id'), count=Count('id'))
        return Response({
            'slot': {'max_id': slot_agg['max_id'] or 0, 'count': slot_agg['count'] or 0},
            'course': {'max_id': course_agg['max_id'] or 0, 'count': course_agg['count'] or 0},
        })


class ClassStatsView(APIView):
    """GET: آمار دقیق لحظه‌ای کلیه‌ی کلاس‌ها — تعداد افراد، مکان‌ها، استاد هر کلاس، تفکیک بر اساس روز"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        slots = list(ClassSlot.objects.all().order_by('number'))
        total_capacity = sum(s.capacity for s in slots)
        total_students = sum(s.current_count for s in slots)

        by_level = {}
        for s in slots:
            if s.assigned_level:
                entry = by_level.setdefault(s.assigned_level, {'count': 0, 'classes': []})
                entry['count'] += s.current_count
                entry['classes'].append(s.number)

        rooms = [{
            'number': s.number, 'title': s.title, 'day_type': s.day_type, 'day_type_display': s.day_type_display,
            'time_slot': s.time_slot, 'teacher_name': s.teacher_name, 'assigned_level': s.assigned_level,
            'current_count': s.current_count, 'capacity': s.capacity, 'capacity_status': s.capacity_status,
        } for s in slots]

        by_day_type = {}
        for choice_value, choice_label in ClassSlot.DayType.choices:
            group = [s for s in slots if s.day_type == choice_value]
            if not group:
                continue
            by_day_type[choice_value] = {
                'label': choice_label,
                'class_count': len(group),
                'total_capacity': sum(s.capacity for s in group),
                'total_students': sum(s.current_count for s in group),
                'empty_seats': max(0, sum(s.capacity for s in group) - sum(s.current_count for s in group)),
                'rooms': [{'number': s.number, 'time_slot': s.time_slot, 'teacher_name': s.teacher_name, 'assigned_level': s.assigned_level, 'current_count': s.current_count, 'capacity': s.capacity} for s in group],
            }

        now_local = timezone.localtime(timezone.now())
        return Response({
            'total_classes': len(slots),
            'total_capacity': total_capacity,
            'total_students': total_students,
            'total_empty_seats': max(0, total_capacity - total_students),
            'empty_classes': [s.number for s in slots if s.current_count == 0],
            'over_capacity_classes': [{'number': s.number, 'surplus': s.surplus} for s in slots if s.current_count > s.capacity],
            'by_level': by_level,
            'rooms': rooms,
            'by_day_type': by_day_type,
            'generated_at_jalali': jdatetime.datetime.fromgregorian(datetime=now_local).strftime('%Y/%m/%d - %H:%M:%S'),
        })


class BulkCreatePhysicalClassesView(APIView):
    """
    POST: دکمه‌ی «ساخت کلاس فیزیکی» — به‌جای وارد کردن یکی‌یکیِ هر کلاس، برای هر شماره‌کلاس
    فیزیکی (مثلاً ۱ تا ۱۱) فقط یک ظرفیت پرسیده می‌شود، و به‌صورت خودکار همه‌ی بازه‌های
    زمانیِ استاندارد براش ساخته می‌شوند: ۵ ساعت در روزهای زوج، همان ۵ ساعت در روزهای فرد،
    یک اسلات پنجشنبه‌صبح، یک اسلات پنجشنبه‌عصر، یک اسلات جمعه — یعنی هر شماره‌کلاس مجموعاً
    ۱۳ ردیف ClassSlot می‌سازد. اگر بعضی از این ترکیب‌ها از قبل موجود باشند (طبق قید یکتایی
    شماره+روز+ساعت)، نادیده گرفته می‌شوند (خطا نمی‌دهد)، تا این دکمه چند بار هم که زده شود
    مشکلی پیش نیاید.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        serializer = BulkCreatePhysicalClassesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rooms = serializer.validated_data['rooms']
        term_id = serializer.validated_data['term_id']
        try:
            term = Term.objects.get(pk=term_id)
        except Term.DoesNotExist:
            return Response({'error': 'ترم انتخاب‌شده پیدا نشد — اول یک ترم تعریف/انتخاب کنید'}, status=status.HTTP_404_NOT_FOUND)

        created, skipped = [], []
        include_slots = set(serializer.validated_data.get('include_time_slots') or []) or set(THREE_DAY_TIME_SLOTS)
        include_thu_morning = serializer.validated_data.get('include_thursday_morning', True)
        include_thu_evening = serializer.validated_data.get('include_thursday_evening', True)
        include_friday = serializer.validated_data.get('include_friday', True)
        include_friday_evening = serializer.validated_data.get('include_friday_evening', True)
        is_online = serializer.validated_data.get('is_online', False)
        schedule_kind = serializer.validated_data.get('schedule_kind', ClassSlot.ScheduleKind.STANDARD)
        two_day_days = serializer.validated_data.get('two_day_days') or []
        delivery_pattern = serializer.validated_data.get('delivery_pattern') or []
        rotating_morning_time = serializer.validated_data.get('rotating_morning_time') or '09:45-11:15'
        rotating_evening_time = serializer.validated_data.get('rotating_evening_time') or '17:30-19:00'

        for room in rooms:
            number = room['number']
            capacity = room['capacity']

            combos = []
            if schedule_kind == ClassSlot.ScheduleKind.TWO_DAY:
                if len(two_day_days) != 2 or len(set(two_day_days)) != 2:
                    return Response({'error': 'برای کلاس دو روز در هفته دقیقاً دو روز متفاوت انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
                combos.append((ClassSlot.DayType.TWO_DAY, '، '.join(two_day_days), room.get('thursday_morning_gender') or ClassSlot.Gender.MIXED, two_day_days, delivery_pattern, ''))
            elif schedule_kind == ClassSlot.ScheduleKind.ROTATING:
                rotation_key = f'rotating-{term.id}-{number}'
                combos.append((ClassSlot.DayType.ROTATING, f'{rotating_morning_time} / {rotating_evening_time}', ClassSlot.Gender.MIXED, ['صبح', 'عصر'], delivery_pattern, rotation_key))
            elif schedule_kind == ClassSlot.ScheduleKind.HYBRID:
                if not delivery_pattern:
                    return Response({'error': 'برای کلاس ترکیبی، ترکیب جلسه‌های حضوری و مجازی را مشخص کنید'}, status=status.HTTP_400_BAD_REQUEST)
                combos.append((ClassSlot.DayType.HYBRID, 'ترکیبی', room.get('thursday_morning_gender') or ClassSlot.Gender.MIXED, [], delivery_pattern, ''))
            else:
                for slot in THREE_DAY_TIME_SLOTS:
                    if slot in include_slots:
                        combos.append((ClassSlot.DayType.EVEN, slot, ClassSlot.Gender.GIRLS, [], [], ''))
                for slot in THREE_DAY_TIME_SLOTS:
                    if slot in include_slots:
                        combos.append((ClassSlot.DayType.ODD, slot, ClassSlot.Gender.BOYS, [], [], ''))
                if include_thu_morning:
                    combos.append((ClassSlot.DayType.THURSDAY_MORNING, THURSDAY_MORNING_SLOT, room['thursday_morning_gender'], [], [], ''))
                if include_thu_evening:
                    combos.append((ClassSlot.DayType.THURSDAY_EVENING, THURSDAY_EVENING_SLOT, room['thursday_evening_gender'], [], [], ''))
                if include_friday:
                    combos.append((ClassSlot.DayType.FRIDAY_MORNING, FRIDAY_MORNING_SLOT, room['friday_gender'], [], [], ''))
                if include_friday_evening:
                    combos.append((ClassSlot.DayType.FRIDAY_EVENING, FRIDAY_EVENING_SLOT, room.get('friday_evening_gender') or ClassSlot.Gender.MIXED, [], [], ''))

            for day_type, time_slot, gender, schedule_days, row_delivery_pattern, rotation_group in combos:
                # get_or_create با term و is_online در ورودی جستجو، یعنی هر ترم و هر حالت
                # (آنلاین/حضوری) مجموعه‌ی کاملاً مستقل خودش از کلاس‌ها را دارد
                obj, was_created = ClassSlot.objects.get_or_create(
                    number=number, day_type=day_type, time_slot=time_slot, term=term, is_online=is_online,
                    defaults={
                        'capacity': capacity, 'gender': gender, 'schedule_kind': schedule_kind,
                        'schedule_days': schedule_days, 'delivery_pattern': row_delivery_pattern,
                        'rotation_group': rotation_group,
                    },
                )
                if was_created:
                    created.append(obj.id)
                else:
                    skipped.append(obj.id)

        slots = ClassSlot.objects.filter(term=term).order_by('number')
        return Response({
            'created_count': len(created),
            'skipped_count': len(skipped),
            'term': TermSerializer(term).data,
            'slots': ClassSlotSerializer(slots, many=True).data,
        }, status=status.HTTP_201_CREATED)


class ClassSlotEnrollView(APIView):
    """
    POST: ثبت‌نام یک دانش‌آموز موجود (با کد ملی) در این کلاس فیزیکی خاص.
    دانش‌آموز باید از قبل توی سیستم ثبت‌نام شده باشه (نقش=دانش‌آموز) و سطح زبانش
    با سطح تخصیص‌داده‌شده‌ی این کلاس (assigned_level) یکی باشه.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            slot = ClassSlot.objects.get(pk=pk)
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        serializer = EnrollStudentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            if data.get('student_id'):
                student = User.objects.select_for_update().get(id=data['student_id'], role='student')
            else:
                student = User.objects.select_for_update().get(national_code=data['national_code'], role='student')
        except User.DoesNotExist:
            return Response({'error': 'دانش‌آموز پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        except User.MultipleObjectsReturned:
            return Response({'error': 'بیش از یک دانش‌آموز با این مشخصات ثبت شده — با مدیر سیستم هماهنگ کنید'}, status=status.HTTP_400_BAD_REQUEST)

        warning = disciplinary_guard(request, [student])
        if warning:
            return warning

        prior_enrollments = list(_same_term_enrollments(slot, [student.id]).filter(student=student))
        # اسم‌های خاکستری (منتظر ثبت‌نام) — چه در همین کلاس چه در کلاس‌های دیگرِ همین ترم — مانع ثبت‌نام نیستند
        all_gray = bool(prior_enrollments) and all(
            item.is_carryover and not item.carryover_confirmed and item.payment_verified for item in prior_enrollments
        )
        carryover_to_confirm = None
        if all_gray:
            carryover_to_confirm = next((item for item in prior_enrollments if item.class_slot_id == slot.id), prior_enrollments[0])
            for item in prior_enrollments:
                if item.pk != carryover_to_confirm.pk:
                    item.delete()
        if prior_enrollments and not carryover_to_confirm:
            class_labels = '؛ '.join(_enrollment_class_label(item.class_slot) for item in prior_enrollments)
            return Response({
                'error': f'خطای ثبت‌نام تکراری: این کد ملی قبلاً در همین ترم در {class_labels} ثبت‌نام شده است — برای جابه‌جایی از «انتقال کلاس» استفاده کنید'
            }, status=status.HTTP_400_BAD_REQUEST)

        # خواسته‌ی ۱: سطح این کلاس باید با سطح واقعیِ فعلیِ دانش‌آموز (محاسبه‌شده از آخرین
        # ثبت‌نام واقعی یا آخرین تعیین‌سطح — نه فیلد خام و اغلب خالیِ language_level) یکی
        # باشد؛ وگرنه ثبت‌نام مسدود می‌شود (مگر با تایید صریح force_level_mismatch)
        current_info = _compute_level_suggestion(student)
        current_level = current_info['level']
        # سطح بعدی و بالاتر (و ردهٔ سنی بالاتر) و خودِ سطح فعلی مجازند؛ فقط سطح پایین‌تر/نامرتبط نیاز به تایید دارد
        allowed_levels = set(_suggestion_plan(current_level)) if current_level else set()
        if slot.assigned_level and current_level and _normalize_level(slot.assigned_level) not in (allowed_levels | {_normalize_level(current_level)}) \
                and not data.get('force_level_mismatch'):
            return Response({
                'error': f"سطح فعلی این دانش‌آموز «{current_level}» است، ولی این کلاس سطح «{slot.assigned_level}» دارد — این ثبت‌نام با سطح دانش‌آموز همخوانی ندارد",
                'level_mismatch': True, 'student_level': current_level, 'class_level': slot.assigned_level,
            }, status=status.HTTP_400_BAD_REQUEST)

        if slot.gender != ClassSlot.Gender.MIXED and student.gender:
            expected_gender = 'دخترانه' if slot.gender == ClassSlot.Gender.GIRLS else 'پسرانه'
            if (slot.gender == ClassSlot.Gender.GIRLS and student.gender != 'female') or \
               (slot.gender == ClassSlot.Gender.BOYS and student.gender != 'male'):
                return Response({
                    'error': f"این کلاس {expected_gender} است و جنسیت این دانش‌آموز با آن همخوانی ندارد"
                }, status=status.HTTP_400_BAD_REQUEST)

        # خواسته‌ی ۵: ثبت‌نام هرگز به‌خاطر پر بودن ظرفیت مسدود نمی‌شود — چون current_count
        # ممکن است از روی «تخصیص خودکار» (پیش‌بینی تقاضا) از قبل با ظرفیت برابر شده باشد،
        # نه لزوماً تعداد واقعیِ ثبت‌نام‌شده‌ها. اگر مدیر واقعاً بخواهد سقف بگذارد، خودش دستی
        # ظرفیت (capacity) را از فرم ویرایش کلاس بالا/پایین می‌برد؛ وضعیت «مازاد» هم مثل
        # همیشه فقط به‌صورت برچسب اطلاع‌رسانی روی کارت کلاس نمایش داده می‌شود.

        tuition_amount = data['tuition_amount']
        discount_percent = data.get('discount_percent', 0)

        # پرداخت از کیف پول — قبل از ثبت، موجودی کافی چک می‌شود
        if data['payment_method'] == ClassSlotEnrollment.PaymentMethod.WALLET:
            if student.wallet_balance < tuition_amount:
                return Response({
                    'error': f'موجودی کیف پول این دانش‌آموز ({student.wallet_balance:,} تومان) برای این مبلغ کافی نیست'
                }, status=status.HTTP_400_BAD_REQUEST)

        if carryover_to_confirm:
            enrollment = carryover_to_confirm
            enrollment.class_slot = slot
            enrollment.payment_method = data['payment_method']
            enrollment.tuition_amount = tuition_amount
            enrollment.discount_percent = discount_percent
            enrollment.pos_reference_code = data.get('pos_reference_code', '')
            enrollment.payment_verified = True
            enrollment.self_enrolled = False
            enrollment.receipt_image = None
            enrollment.carryover_confirmed = True
            enrollment.save(update_fields=[
                'class_slot', 'payment_method', 'tuition_amount', 'discount_percent',
                'pos_reference_code', 'payment_verified', 'self_enrolled', 'receipt_image',
                'carryover_confirmed',
            ])
        else:
            enrollment = ClassSlotEnrollment.objects.create(
                class_slot=slot, student=student,
                payment_method=data['payment_method'],
                tuition_amount=tuition_amount,
                discount_percent=discount_percent,
                pos_reference_code=data.get('pos_reference_code', ''),
            )
        # توجه: current_count دیگر اینجا دست‌کاری نمی‌شود — آن فیلد فقط برای عدد
        # انتزاعیِ «تخصیص خودکار» است؛ شمارش واقعی از خودِ ردیف‌های ClassSlotEnrollment
        # محاسبه می‌شود (real_enrolled_count) تا با ثبت‌نام تک‌به‌تک دوبار شمارش نشود (خواسته‌ی جدید)
        if not slot.assigned_level and student.language_level:
            slot.assigned_level = student.language_level
            slot.save()

        # کسر خودکار از کیف پول، اگر روش پرداخت کیف پول بود
        if data['payment_method'] == ClassSlotEnrollment.PaymentMethod.WALLET:
            student.wallet_balance -= tuition_amount
            student.save(update_fields=['wallet_balance'])
            WalletTransaction.objects.create(
                student=student, kind=WalletTransaction.Kind.DEBIT, amount=tuition_amount,
                reason=f'پرداخت شهریه‌ی کلاس {slot.number}', class_slot=slot,
            )

        # ثبت/به‌روزرسانی خودکار در «افراد دارای تخفیف»، اگر درصد تخفیف صفر نبود
        discount_record = None
        if discount_percent > 0:
            discount_record, _ = DiscountedPerson.objects.update_or_create(
                student=student,
                defaults={'discount_percent': discount_percent, 'class_slot': slot, 'approved_tuition': tuition_amount},
            )

        # اگر فرد در این ترم خاکستری/بدهکارِ منتظر ثبت‌نام بود: مشکی شود، از کلاس‌های دیگر حذف و از بدهکاران تسویه شود
        finalize_registration(student, slot)

        return Response({
            'enrollment': ClassSlotEnrollmentSerializer(enrollment).data,
            'slot': ClassSlotSerializer(slot).data,
            'discount_record': DiscountedPersonSerializer(discount_record).data if discount_record else None,
            'wallet_balance': student.wallet_balance,
        }, status=status.HTTP_201_CREATED)


class ClassSlotExcelImportView(APIView):
    """Preview a selected Excel row/column range, then add those students to one class."""
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _national_code_key(value):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        text = unicodedata.normalize('NFKC', str(value or '')).strip()
        if re.fullmatch(r'\d+\.0+', text):
            text = text.split('.', 1)[0]
        digits = []
        for char in text:
            try:
                digits.append(str(unicodedata.digit(char)))
            except (TypeError, ValueError):
                continue
        return ''.join(digits)

    @staticmethod
    def _excel_column_index(column):
        result = 0
        for letter in column:
            result = result * 26 + ord(letter) - ord('A') + 1
        return result - 1

    @staticmethod
    def _class_tariff(slot):
        level = str(slot.assigned_level or '').strip()
        age_group = infer_age_group_from_level(level) if level else ''
        setting = TuitionSetting.objects.filter(level=level, age_group=age_group).first() if level and age_group else None
        if not setting:
            return None, level, age_group, 'برای سطح این کلاس شهریهٔ مصوب تعریف نشده است؛ ابتدا سطح و شهریهٔ کلاس را بررسی کنید.'
        return setting.amount, level, age_group, ''

    # وضعیت‌هایی که فقط با تایید صریح مدیر قابل ثبت‌اند. موارد زیر هرگز قابل ثبت نیستند، حتی با تایید مدیر:
    # ثبت‌نام تکراری (همین کلاس یا کلاس دیگری در همین ترم)، عدم تطابق جنسیت، و خطاهای ساختاری کد ملی/نام/تلفن.
    ADMIN_OVERRIDABLE_STATUSES = ('level_mismatch',)

    def _preview_students_by_code(self, slot, student_rows, lock_students=False):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        tuition, level, age_group, tariff_error = self._class_tariff(slot)
        students_by_code = {}
        students = list(User.objects.filter(role='student').only(
            'id', 'first_name', 'last_name', 'national_code', 'phone', 'gender', 'wallet_balance',
        ).order_by('id'))
        for student in students:
            code_key = self._national_code_key(student.national_code)
            if code_key:
                students_by_code.setdefault(code_key, []).append(student)
        if lock_students:
            incoming_codes = {self._national_code_key(row[3]) for row in student_rows}
            matched_student_ids = [
                student.id for code_key, matches in students_by_code.items() if code_key in incoming_codes
                for student in matches
            ]
            if matched_student_ids:
                list(User.objects.select_for_update().filter(pk__in=matched_student_ids).order_by('id').values_list('id', flat=True))
        other_users_by_code = {}
        other_users = User.objects.exclude(role='student').exclude(national_code__isnull=True).exclude(national_code='').only('national_code')
        for user in other_users:
            code_key = self._national_code_key(user.national_code)
            if code_key:
                other_users_by_code[code_key] = True

        student_ids = [student.id for matches in students_by_code.values() for student in matches]
        enrollments_by_student = {}
        gray_slot_ids_by_student = {}
        if student_ids:
            for enrollment in _same_term_enrollments(slot, student_ids):
                enrollments_by_student.setdefault(enrollment.student_id, []).append(enrollment.class_slot)
                if enrollment.is_carryover and not enrollment.carryover_confirmed and enrollment.payment_verified:
                    gray_slot_ids_by_student.setdefault(enrollment.student_id, set()).add(enrollment.class_slot_id)
        previous_term = None
        previous_enrollments_by_student = {}
        if slot.term_id:
            previous_term = Term.objects.filter(
                Q(year__lt=slot.term.year)
                | Q(year=slot.term.year, term_number__lt=slot.term.term_number)
            ).order_by('-year', '-term_number').first()
            if previous_term and student_ids:
                for enrollment in ClassSlotEnrollment.objects.filter(
                    class_slot__term=previous_term,
                    student_id__in=student_ids,
                    payment_verified=True,
                ).select_related('class_slot').order_by('created_at'):
                    previous_enrollments_by_student.setdefault(enrollment.student_id, enrollment)
        discount_by_student = {}
        if student_ids:
            for discount in DiscountedPerson.objects.filter(student_id__in=student_ids).order_by('-updated_at'):
                discount_by_student.setdefault(discount.student_id, discount.discount_percent)

        rows = []
        seen_codes = set()
        labels = {
            'new': 'دانش‌آموز جدید', 'existing': 'دانش‌آموز موجود',
            'already_enrolled': 'خطای ثبت‌نام تکراری',
            'other_term': 'خطای ثبت‌نام تکراری',
            'ambiguous_code': 'کد ملی در سامانه به بیش از یک پرونده اشاره می‌کند',
            'national_code_in_use': 'این کد ملی متعلق به حسابی غیر از دانش‌آموز است',
            'duplicate_in_file': 'کد ملی تکراری در فایل',
            'invalid_national_code': 'کد ملی باید دقیقاً ۱۰ رقم باشد',
            'invalid_name': 'نام یا نام خانوادگی دانش‌آموز جدید خالی یا بیش از ۱۵۰ نویسه است',
            'invalid_phone': 'شمارهٔ همراه باید ۱۰ یا ۱۱ رقم باشد',
            'level_mismatch': 'سطح فعلی با سطح کلاس همخوانی ندارد (نیازمند تایید مدیر)',
            'gender_mismatch': 'جنسیت با کلاس همخوانی ندارد',
        }
        for row_number, first_name, last_name, raw_national_code, raw_phone in student_rows:
            first_name = str(first_name or '').strip()
            last_name = str(last_name or '').strip()
            national_code = self._national_code_key(raw_national_code)
            phone = self._national_code_key(raw_phone)
            if len(phone) == 10 and phone.startswith('9'):
                phone = '0' + phone
            if not first_name and not last_name and not national_code and not phone:
                continue
            result = {
                'row_number': row_number, 'first_name': first_name, 'last_name': last_name, 'national_code': national_code, 'phone': phone,
                'status': '', 'status_label': '', 'note': '', 'student_id': None,
                'discount_percent': 0, 'tuition_amount': tuition,
                'is_carryover': False, 'carried_from_term_id': None,
                'carried_from_term_title': '', 'carryover_payment_method': '',
                'carryover_discount_percent': 0, 'awaiting_confirm': False,
            }
            if len(national_code) != 10:
                result['status'] = 'invalid_national_code'
            elif national_code in seen_codes:
                result['status'] = 'duplicate_in_file'
            else:
                seen_codes.add(national_code)
                matches = students_by_code.get(national_code, [])
                if len(matches) > 1:
                    result['status'] = 'ambiguous_code'
                elif not matches:
                    if national_code in other_users_by_code:
                        result['status'] = 'national_code_in_use'
                    elif not first_name or not last_name or len(first_name) > 150 or len(last_name) > 150:
                        result['status'] = 'invalid_name'
                    elif phone and len(phone) not in (10, 11):
                        result['status'] = 'invalid_phone'
                    else:
                        result['status'] = 'new'
                else:
                    student = matches[0]
                    result['student_id'] = student.id
                    result['first_name'] = student.first_name or first_name
                    result['last_name'] = student.last_name or last_name
                    result['phone'] = student.phone or phone or ''
                    result['discount_percent'] = discount_by_student.get(student.id, 0)
                    if tuition is not None:
                        result['tuition_amount'] = round(tuition * (100 - result['discount_percent']) / 100)
                    prior_slots = enrollments_by_student.get(student.id, [])
                    gray_ids = gray_slot_ids_by_student.get(student.id, set())
                    # فقط اسم خاکستری (منتظر ثبت‌نام) دارد؛ حضورش در لیست اکسل یعنی ثبت‌نام کرده است
                    confirm_gray = bool(prior_slots) and all(prior.pk in gray_ids for prior in prior_slots)
                    if prior_slots and not confirm_gray:
                        result['status'] = 'already_enrolled' if any(prior.pk == slot.pk for prior in prior_slots) else 'other_term'
                        class_labels = '؛ '.join(_enrollment_class_label(prior) for prior in prior_slots)
                        result['note'] = f'این کد ملی قبلاً در همین ترم ثبت‌نام شده است: {class_labels}'
                    else:
                        if confirm_gray:
                            result['awaiting_confirm'] = True
                            result['note'] = 'منتظر ثبت‌نام بود — با ثبت، اسم از خاکستری به مشکی تغییر می‌کند'
                        previous_enrollment = None if confirm_gray else previous_enrollments_by_student.get(student.id)
                        if previous_enrollment:
                            result.update({
                                'is_carryover': True,
                                'carried_from_term_id': previous_term.pk,
                                'carried_from_term_title': previous_term.title,
                                'carryover_payment_method': previous_enrollment.payment_method,
                                'carryover_discount_percent': previous_enrollment.discount_percent,
                                'discount_percent': previous_enrollment.discount_percent,
                                'tuition_amount': 0,
                            })
                        current_level = _compute_level_suggestion(student).get('level')
                        # تطابق جنسیت الزامی و غیرقابل‌عبور است (کلاس مختلط برای همه آزاد است)؛ پس قبل از
                        # بررسی سطح انجام می‌شود تا با تایید مدیر هم دور زده نشود.
                        if slot.gender != ClassSlot.Gender.MIXED and student.gender and (
                            (slot.gender == ClassSlot.Gender.GIRLS and student.gender != 'female') or
                            (slot.gender == ClassSlot.Gender.BOYS and student.gender != 'male')
                        ):
                            result['status'] = 'gender_mismatch'
                            result['note'] = 'کلاس دخترانه برای پسر و کلاس پسرانه برای دختر قابل ثبت‌نام نیست'
                        elif slot.assigned_level and current_level and _normalize_level(slot.assigned_level) != _normalize_level(current_level):
                            # قابل ثبت فقط با تایید صریح مدیر
                            result['status'] = 'level_mismatch'
                            result['note'] = f'سطح فعلی: {current_level} — با تایید مدیر قابل ثبت است'
                        else:
                            result['status'] = 'existing'
            result['status_label'] = labels.get(result['status'], result['status'])
            if result['is_carryover'] and result['status'] in ('existing', 'level_mismatch'):
                result['status_label'] = f'دانش‌آموز ترم قبل — انتقالی و نیازمند پیگیری ({result["carried_from_term_title"]})'
            result['needs_admin_approval'] = result['status'] in self.ADMIN_OVERRIDABLE_STATUSES
            rows.append(result)

        eligible_count = sum(1 for row in rows if row['status'] in ('new', 'existing'))
        approvable_count = sum(1 for row in rows if row['status'] in self.ADMIN_OVERRIDABLE_STATUSES)
        carryover_count = sum(1 for row in rows if row['is_carryover'] and row['status'] in ('existing', 'level_mismatch'))
        if tariff_error and not any(
            row['status'] in ('new', 'existing', *self.ADMIN_OVERRIDABLE_STATUSES) and not row['is_carryover']
            for row in rows
        ):
            tariff_error = ''
        return {
            'rows': rows, 'eligible_count': eligible_count, 'approvable_count': approvable_count,
            'carryover_count': carryover_count,
            'previous_term': {'id': previous_term.pk, 'title': previous_term.title} if previous_term else None,
            'level': level,
            'age_group': age_group, 'base_tuition': tuition,
            'tariff_error': tariff_error,
        }

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            slot = ClassSlot.objects.get(pk=pk)
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        mode = str(request.data.get('mode', 'preview')).strip().lower()
        if mode == 'preview':
            uploaded_file = request.FILES.get('file')
            if not uploaded_file:
                return Response({'error': 'فایل Excel را انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
            legacy_first_column = str(request.data.get('first_name_column', '')).strip().upper()
            legacy_national_code_column = str(request.data.get('national_code_column', request.data.get('national_code_start_column', request.data.get('last_name_column', '')))).strip().upper()
            first_start_column = str(request.data.get('first_name_start_column', legacy_first_column)).strip().upper()
            first_end_column = str(request.data.get('first_name_end_column', request.data.get('first_name_start_column', legacy_first_column))).strip().upper()
            legacy_last_name_column = str(request.data.get('last_name_column', 'B')).strip().upper()
            last_name_start_column = str(request.data.get('last_name_start_column', legacy_last_name_column)).strip().upper()
            last_name_end_column = str(request.data.get('last_name_end_column', request.data.get('last_name_start_column', legacy_last_name_column))).strip().upper()
            national_code_start_column = str(request.data.get('national_code_start_column', legacy_national_code_column)).strip().upper()
            national_code_end_column = str(request.data.get('national_code_end_column', request.data.get('national_code_start_column', legacy_national_code_column))).strip().upper()
            phone_start_column = str(request.data.get('phone_start_column', 'D')).strip().upper()
            phone_end_column = str(request.data.get('phone_end_column', request.data.get('phone_start_column', 'D'))).strip().upper()
            selected_columns = (
                first_start_column, first_end_column, last_name_start_column, last_name_end_column,
                national_code_start_column, national_code_end_column, phone_start_column, phone_end_column,
            )
            if any(not re.fullmatch(r'[A-Z]{1,2}', column) for column in selected_columns):
                return Response({'error': 'بازهٔ نام، نام خانوادگی، کد ملی و شمارهٔ همراه را از A تا ZZ انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
            if any(self._excel_column_index(column) > 701 for column in selected_columns):
                return Response({'error': 'حداکثر ستون قابل انتخاب ZZ است'}, status=status.HTTP_400_BAD_REQUEST)
            first_start_index = self._excel_column_index(first_start_column)
            first_end_index = self._excel_column_index(first_end_column)
            last_name_start_index = self._excel_column_index(last_name_start_column)
            last_name_end_index = self._excel_column_index(last_name_end_column)
            national_code_start_index = self._excel_column_index(national_code_start_column)
            national_code_end_index = self._excel_column_index(national_code_end_column)
            phone_start_index = self._excel_column_index(phone_start_column)
            phone_end_index = self._excel_column_index(phone_end_column)
            if any(start > end for start, end in (
                (first_start_index, first_end_index), (last_name_start_index, last_name_end_index),
                (national_code_start_index, national_code_end_index), (phone_start_index, phone_end_index),
            )):
                return Response({'error': 'ستون «از» باید قبل از ستون «تا» باشد'}, status=status.HTTP_400_BAD_REQUEST)
            column_ranges = [
                (first_start_index, first_end_index), (last_name_start_index, last_name_end_index),
                (national_code_start_index, national_code_end_index), (phone_start_index, phone_end_index),
            ]
            same_full_name_range = (first_start_index, first_end_index) == (last_name_start_index, last_name_end_index)
            if any(
                start <= other_end and other_start <= end and not (index == 0 and other_index == 1 and same_full_name_range)
                for index, (start, end) in enumerate(column_ranges)
                for other_index, (other_start, other_end) in enumerate(column_ranges[index + 1:], start=index + 1)
            ):
                return Response({'error': 'بازه‌های نام، نام خانوادگی، کد ملی و شمارهٔ همراه نباید با هم هم‌پوشانی داشته باشند'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                start_row = int(request.data.get('start_row', ''))
                end_row = int(request.data.get('end_row', ''))
            except (TypeError, ValueError):
                return Response({'error': 'شمارهٔ سطر شروع و پایان را وارد کنید'}, status=status.HTTP_400_BAD_REQUEST)
            if start_row < 1 or end_row < start_row:
                return Response({'error': 'بازهٔ سطرها معتبر نیست'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                from accounts.views import _load_excel_rows
                sheet_rows = _load_excel_rows(uploaded_file)
            except Exception as exc:
                return Response({'error': str(exc) or 'خواندن فایل Excel انجام نشد'}, status=status.HTTP_400_BAD_REQUEST)
            if start_row > len(sheet_rows):
                return Response({'error': f'فایل فقط {len(sheet_rows)} سطر قابل‌خواندن دارد'}, status=status.HTTP_400_BAD_REQUEST)
            actual_end_row = min(end_row, len(sheet_rows))

            def join_column_range(values, start_index, end_index):
                parts = []
                for column_index in range(start_index, end_index + 1):
                    value = values[column_index] if column_index < len(values) else ''
                    text = str(value).strip() if value is not None else ''
                    if text:
                        parts.append(text)
                return ' '.join(parts)

            student_rows = []
            for row_number in range(start_row, actual_end_row + 1):
                values = sheet_rows[row_number - 1] or ()
                if same_full_name_range:
                    full_name_parts = join_column_range(values, first_start_index, first_end_index).split()
                    first_name = full_name_parts[0] if full_name_parts else ''
                    last_name = ' '.join(full_name_parts[1:])
                else:
                    first_name = join_column_range(values, first_start_index, first_end_index)
                    last_name = join_column_range(values, last_name_start_index, last_name_end_index)
                national_code = join_column_range(values, national_code_start_index, national_code_end_index)
                phone = join_column_range(values, phone_start_index, phone_end_index)
                if first_name not in (None, '') or last_name not in (None, '') or national_code not in (None, '') or phone not in (None, ''):
                    student_rows.append((row_number, first_name, last_name, national_code, phone))
            preview = self._preview_students_by_code(slot, student_rows)
            preview.update({
                'selected_range': {'start': start_row, 'end': actual_end_row},
                'first_name_column': first_start_column, 'last_name_column': last_name_start_column,
                'national_code_column': national_code_start_column,
                'first_name_start_column': first_start_column, 'first_name_end_column': first_end_column,
                'last_name_start_column': last_name_start_column, 'last_name_end_column': last_name_end_column,
                'national_code_start_column': national_code_start_column, 'national_code_end_column': national_code_end_column,
                'phone_start_column': phone_start_column, 'phone_end_column': phone_end_column,
                'class_number': slot.number, 'capacity': slot.capacity,
                'real_enrolled_count': ClassSlotEnrollment.objects.filter(class_slot=slot).count(),
            })
            return Response(preview)

        if mode != 'commit':
            return Response({'error': 'درخواست نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            supplied_rows = json.loads(request.data.get('rows') or '[]')
        except (TypeError, ValueError):
            return Response({'error': 'فهرست سطرهای انتخاب‌شده معتبر نیست'}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(supplied_rows, list) or not supplied_rows:
            return Response({'error': 'حداقل یک سطر را برای ثبت انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
        if len(supplied_rows) > 2000:
            return Response({'error': 'در هر نوبت حداکثر ۲۰۰۰ سطر قابل ثبت است'}, status=status.HTTP_400_BAD_REQUEST)
        payment_method = str(request.data.get('payment_method', '')).strip()
        allowed_methods = {value for value, _label in ClassSlotEnrollment.PaymentMethod.choices}
        if payment_method and payment_method not in allowed_methods:
            return Response({'error': 'روش پرداخت نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        pos_reference_code = str(request.data.get('pos_reference_code', '')).strip()
        if len(pos_reference_code) > 50:
            return Response({'error': 'کد پیگیری پوز حداکثر ۵۰ نویسه است'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            approved_row_numbers = {int(n) for n in json.loads(request.data.get('approved_rows') or '[]')}
        except (TypeError, ValueError):
            return Response({'error': 'فهرست موارد تاییدشده توسط مدیر معتبر نیست'}, status=status.HTTP_400_BAD_REQUEST)

        student_rows = []
        try:
            for item in supplied_rows:
                row_number = int(item.get('row_number'))
                first_name = str(item.get('first_name') or '').strip()
                last_name = str(item.get('last_name') or '').strip()
                national_code = str(item.get('national_code') or '').strip()
                phone = str(item.get('phone') or '').strip()
                if row_number < 1 or (not first_name and not last_name and not national_code and not phone):
                    continue
                student_rows.append((row_number, first_name, last_name, national_code, phone))
        except (AttributeError, TypeError, ValueError):
            return Response({'error': 'اطلاعات یکی از سطرهای انتخاب‌شده معتبر نیست'}, status=status.HTTP_400_BAD_REQUEST)
        if not student_rows:
            return Response({'error': 'هیچ سطر معتبری برای ثبت انتخاب نشده است'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            slot = ClassSlot.objects.select_for_update().get(pk=pk)
            preview = self._preview_students_by_code(slot, student_rows, lock_students=True)
            if preview['tariff_error']:
                return Response({'error': preview['tariff_error']}, status=status.HTTP_400_BAD_REQUEST)
            def _is_candidate(row):
                if row['status'] in ('new', 'existing'):
                    return True
                return row['status'] in self.ADMIN_OVERRIDABLE_STATUSES and row['row_number'] in approved_row_numbers

            candidates = [row for row in preview['rows'] if _is_candidate(row)]
            rejected = [
                {'row_number': row['row_number'], 'name': f"{row['first_name']} {row['last_name']}", 'reason': row['status_label'] + (f" — {row['note']}" if row['note'] else '')}
                for row in preview['rows'] if not _is_candidate(row)
            ]
            paid_candidates = [row for row in candidates if not row.get('is_carryover')]
            if paid_candidates and payment_method not in allowed_methods:
                return Response({'error': 'برای ثبت‌نام‌های جدید روش پرداخت را انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
            if paid_candidates and payment_method == ClassSlotEnrollment.PaymentMethod.POS and not pos_reference_code:
                return Response({'error': 'کد پیگیری مشترک دستگاه پوز را وارد کنید'}, status=status.HTTP_400_BAD_REQUEST)
            if payment_method == ClassSlotEnrollment.PaymentMethod.WALLET:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                eligible_after_wallet = []
                for row in candidates:
                    if row.get('is_carryover'):
                        eligible_after_wallet.append(row)
                        continue
                    student = User.objects.filter(pk=row['student_id'], role='student').first() if row['student_id'] else None
                    balance = student.wallet_balance if student else 0
                    if balance < row['tuition_amount']:
                        rejected.append({'row_number': row['row_number'], 'name': f"{row['first_name']} {row['last_name']}", 'reason': 'موجودی کیف پول برای شهریه کافی نیست'})
                    else:
                        eligible_after_wallet.append(row)
                candidates = eligible_after_wallet
            if not candidates:
                return Response({'error': 'هیچ دانش‌آموز واجد شرایطی برای ثبت باقی نمانده است', 'rejected': rejected}, status=status.HTTP_400_BAD_REQUEST)
            from django.contrib.auth import get_user_model as _gum
            _flag_students = list(_gum().objects.filter(pk__in=[row['student_id'] for row in candidates if row.get('student_id')]))
            warning = disciplinary_guard(request, _flag_students)
            if warning:
                return warning
            current_enrolled_count = ClassSlotEnrollment.objects.filter(class_slot=slot).count()
            force_over_capacity = str(request.data.get('force_over_capacity', '')).lower() in ('1', 'true', 'yes')
            new_seat_count = len([row for row in candidates if not row.get('awaiting_confirm')])
            if current_enrolled_count + new_seat_count > slot.capacity and not force_over_capacity:
                return Response({
                    'capacity_warning': True, 'error': f'با ثبت این افراد، تعداد ثبت‌نام‌شده‌ها از ظرفیت {slot.capacity} نفر عبور می‌کند.',
                    'current_enrolled_count': current_enrolled_count, 'capacity': slot.capacity,
                    'eligible_count': new_seat_count,
                }, status=status.HTTP_409_CONFLICT)

            from django.contrib.auth import get_user_model
            User = get_user_model()
            created_students = 0
            enrolled_count = 0
            carried_count = 0
            for row in candidates:
                if row['student_id']:
                    student = User.objects.select_for_update().filter(pk=row['student_id'], role='student').first()
                    if not student:
                        rejected.append({'row_number': row['row_number'], 'name': f"{row['first_name']} {row['last_name']}", 'reason': 'دانش‌آموز دیگر پیدا نشد'})
                        continue
                else:
                    base_username = f'excel_{slot.id}_{row["row_number"]}'
                    username = base_username
                    suffix = 1
                    while User.objects.filter(username=username).exists():
                        username = f'{base_username}_{suffix}'
                        suffix += 1
                    student = User(
                        username=username, role='student', first_name=row['first_name'], last_name=row['last_name'],
                        phone=row['phone'], national_code=row['national_code'], gender='', needs_editing=True,
                    )
                    student.set_unusable_password()
                    student.save()
                    created_students += 1

                existing_here = ClassSlotEnrollment.objects.filter(class_slot=slot, student=student).first()
                if existing_here and not (existing_here.is_carryover and not existing_here.carryover_confirmed):
                    rejected.append({'row_number': row['row_number'], 'name': f"{row['first_name']} {row['last_name']}", 'reason': 'در همین کلاس ثبت‌نام بود'})
                    continue
                is_carryover = bool(row.get('is_carryover'))
                discount_percent = row['carryover_discount_percent'] if is_carryover else row['discount_percent']
                tuition_amount = 0 if is_carryover else row['tuition_amount']
                if existing_here:
                    # اسم خاکستریِ همین کلاس: همان ردیف قطعی (مشکی) می‌شود
                    enrollment = existing_here
                    enrollment.payment_method = payment_method
                    enrollment.tuition_amount = tuition_amount
                    enrollment.discount_percent = discount_percent
                    enrollment.pos_reference_code = pos_reference_code if payment_method == ClassSlotEnrollment.PaymentMethod.POS else ''
                    enrollment.payment_verified = True
                    enrollment.carryover_confirmed = True
                    enrollment.save()
                else:
                    enrollment = ClassSlotEnrollment.objects.create(
                        class_slot=slot, student=student,
                        payment_method=(row.get('carryover_payment_method') or ClassSlotEnrollment.PaymentMethod.CASH) if is_carryover else payment_method,
                        tuition_amount=tuition_amount, discount_percent=discount_percent,
                        pos_reference_code=pos_reference_code if not is_carryover and payment_method == ClassSlotEnrollment.PaymentMethod.POS else '',
                        payment_verified=True,
                        is_carryover=is_carryover,
                        carryover_confirmed=False,
                        carried_from_term_id=row.get('carried_from_term_id') if is_carryover else None,
                    )
                if not is_carryover:
                    # ثبت‌نام قطعی: خاکستریِ کلاس‌های دیگر حذف و بدهکارِ منتظر ثبت‌نام تسویه می‌شود
                    finalize_registration(student, slot)
                if is_carryover:
                    carried_count += 1
                if not is_carryover and payment_method == ClassSlotEnrollment.PaymentMethod.WALLET:
                    student.wallet_balance -= tuition_amount
                    student.save(update_fields=['wallet_balance'])
                    WalletTransaction.objects.create(
                        student=student, kind=WalletTransaction.Kind.DEBIT, amount=tuition_amount,
                        reason=f'پرداخت شهریهٔ کلاس {slot.number}', class_slot=slot,
                    )
                if not is_carryover and discount_percent > 0:
                    DiscountedPerson.objects.update_or_create(
                        student=student,
                        defaults={'discount_percent': discount_percent, 'class_slot': slot, 'approved_tuition': tuition_amount},
                    )
                enrolled_count += 1
            return Response({
                'created_students': created_students, 'enrolled_count': enrolled_count,
                'carried_count': carried_count,
                'skipped_count': len(rejected), 'rejected': rejected,
                'message': f'{enrolled_count} نفر به کلاس اضافه شدند',
            }, status=status.HTTP_201_CREATED)


class ClassSlotUnenrollView(APIView):
    """DELETE: حذف یک دانش‌آموز از لیست این کلاس فیزیکی"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            slot = ClassSlot.objects.get(pk=pk)
            enrollment = ClassSlotEnrollment.objects.get(class_slot=slot, student_id=student_id)
        except (ClassSlot.DoesNotExist, ClassSlotEnrollment.DoesNotExist):
            return Response({'error': 'ثبت‌نام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        enrollment.delete()
        return Response({'message': 'دانش‌آموز از این کلاس حذف شد', 'slot': ClassSlotSerializer(slot).data})


class ClassSlotRosterView(generics.ListAPIView):
    """
    GET: لیست دانش‌آموزان *تاییدشده*ی یک کلاس فیزیکی خاص — مبنای خروجی اکسل/چاپ حضور و غیاب.
    ثبت‌نام‌های خودِ دانش‌آموز از اپ که هنوز تایید نشده‌اند اینجا نمی‌آیند (خواسته‌ی ۱) —
    آن‌ها فقط توی پنجره‌ی «ثبت‌نام‌های در انتظار تایید» دیده می‌شوند.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ClassSlotEnrollmentSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'class-management'):
            return ClassSlotEnrollment.objects.none()
        enrollment_in_other_class = ClassSlotEnrollment.objects.filter(
            student_id=OuterRef('student_id'),
            class_slot__term_id=OuterRef('class_slot__term_id'),
            payment_verified=True,
        ).filter(
            Q(is_carryover=False) | Q(carryover_confirmed=True)
        ).exclude(class_slot_id=OuterRef('class_slot_id'))
        return ClassSlotEnrollment.objects.filter(
            class_slot_id=self.kwargs['pk'], payment_verified=True,
        ).select_related('student', 'class_slot').annotate(
            has_other_current_class=Exists(enrollment_in_other_class),
        )


class ConfirmCarryoverEnrollmentView(APIView):
    """تأیید دستیِ تمدید دانش‌آموز منتقل‌شده، بدون حذف او از فهرست حضور‌وغیاب."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ویرایش ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            enrollment = ClassSlotEnrollment.objects.select_related('class_slot').get(
                class_slot_id=pk, student_id=student_id,
            )
        except ClassSlotEnrollment.DoesNotExist:
            return Response({'error': 'ثبت‌نام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        if not enrollment.is_carryover:
            return Response({'error': 'این ردیف ثبت‌نام انتقالی نیست'}, status=status.HTTP_400_BAD_REQUEST)
        if not enrollment.payment_verified:
            return Response({'error': 'ابتدا پرداخت/ثبت‌نام را تأیید کنید'}, status=status.HTTP_400_BAD_REQUEST)
        if not enrollment.carryover_confirmed:
            enrollment.carryover_confirmed = True
            enrollment.save(update_fields=['carryover_confirmed'])
        finalize_registration(enrollment.student, enrollment.class_slot)
        return Response({
            'message': 'تمدید ثبت‌نام تأیید شد؛ دانش‌آموز در فهرست حضور‌وغیاب باقی می‌ماند',
            'student_id': enrollment.student_id,
            'class_slot_id': enrollment.class_slot_id,
            'carryover_confirmed': enrollment.carryover_confirmed,
            'needs_follow_up': False,
        })


class MarkCarryoverEnrollmentView(APIView):
    """نشانه‌گذاری دستی رکوردهای منتقل‌شدهٔ قدیمی که پیش از افزودن فیلد provenance ساخته شده‌اند."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ویرایش ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            enrollment = ClassSlotEnrollment.objects.select_related('class_slot__term').get(
                class_slot_id=pk, student_id=student_id,
            )
        except ClassSlotEnrollment.DoesNotExist:
            return Response({'error': 'ثبت‌نام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        source_term_id = request.data.get('source_term_id')
        try:
            source_term = Term.objects.get(pk=source_term_id)
        except (Term.DoesNotExist, TypeError, ValueError):
            return Response({'error': 'ترم مبدأ پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        target_term = enrollment.class_slot.term
        if not target_term:
            return Response({'error': 'کلاس مقصد به ترم متصل نیست'}, status=status.HTTP_400_BAD_REQUEST)
        if (source_term.year, source_term.term_number) >= (target_term.year, target_term.term_number):
            return Response({'error': 'ترم مبدأ باید قدیمی‌تر از ترم کلاس باشد'}, status=status.HTTP_400_BAD_REQUEST)
        enrollment.is_carryover = True
        enrollment.carryover_confirmed = False
        enrollment.carried_from_term = source_term
        enrollment.save(update_fields=['is_carryover', 'carryover_confirmed', 'carried_from_term'])
        return Response({
            'message': 'این رکورد به‌عنوان انتقالی علامت‌گذاری شد و اکنون نیازمند پیگیری است',
            'student_id': enrollment.student_id,
            'class_slot_id': enrollment.class_slot_id,
            'is_carryover': True,
            'needs_follow_up': True,
        })


class StudentEducationHistoryView(APIView):
    """
    GET: سوابق آموزشیِ کاملِ دانش‌آموز:
    ۱) سطح فعلی (همیشه به‌روز، از همون منطق پیشنهاد خودکار سطح)
    ۲) سوابق ثبت‌نام‌های ترمیک (سطح، روش ثبت‌نام، تاریخ شمسی)
    ۳) سوابق کلاس‌های خصوصی/جبرانی/سایر (از اپ classes، مدل ClassRequest در accounts)
    ۴) سوابق کلاس‌های گروهی/ورکشاپ (از اپ group_classes)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            student = User.objects.get(pk=student_id, role='student')
        except User.DoesNotExist:
            return Response({'error': 'دانش‌آموز پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        info = _compute_level_suggestion(student)
        history = ClassSlotEnrollment.objects.filter(student=student).select_related('class_slot').order_by('-created_at')

        # کلاس‌های خصوصی/جبرانی/سایر (فاز ۱ — مدل ClassRequest در accounts، جلسات در اپ classes)
        from accounts.models import ClassRequest
        private_classes = ClassRequest.objects.filter(student=student).select_related('teacher').order_by('-created_at')
        private_history = [{
            'id': c.id,
            'class_type': c.get_class_type_display() if c.class_type != 'other' else (c.custom_class_type or 'سایر'),
            'language_level': c.language_level,
            'teacher_name': f"{c.teacher.first_name} {c.teacher.last_name}" if c.teacher else '—',
            'status_display': c.get_status_display(),
            'session_count': c.session_count,
            'sessions_done': c.sessions.filter(completed_at__isnull=False).count() if hasattr(c, 'sessions') else 0,
            'class_date_jalali': c.class_date_jalali,
            'completed_at_jalali': c.completed_at_jalali,
            'created_at_jalali': c.created_at_jalali,
            'total_price': c.total_price,
        } for c in private_classes]

        # کلاس‌های گروهی/ورکشاپ (فاز ۲ — اپ group_classes)
        from group_classes.models import GroupSessionParticipant
        group_participations = GroupSessionParticipant.objects.filter(student=student).select_related('group_session', 'group_session__teacher').order_by('-joined_at')
        group_history = [{
            'id': p.id,
            'session_type': p.group_session.get_session_type_display(),
            'title': p.group_session.title or p.group_session.language_level,
            'language_level': p.group_session.language_level,
            'teacher_name': f"{p.group_session.teacher.first_name} {p.group_session.teacher.last_name}" if p.group_session.teacher else '—',
            'status_display': p.group_session.get_status_display(),
            'payment_status_display': p.get_payment_status_display(),
            'class_date_jalali': p.group_session.class_date_jalali,
            'completed_at_jalali': p.group_session.completed_at_jalali,
            'price_amount': p.price_amount,
        } for p in group_participations]

        return Response({
            'current_level': info['level'],
            'current_age_group': info['age_group'],
            'current_age_group_display': dict(LevelTest.AgeGroup.choices).get(info['age_group'], ''),
            'current_level_source': info['source'],
            'needs_retest': info['needs_retest'],
            'retest_reason': info['retest_reason'],
            'term_enrollments': [{
                'id': e.id,
                'term_id': e.class_slot.term_id,
                'term_title': e.class_slot.term.title if e.class_slot.term_id else '',
                'level': e.class_slot.assigned_level,
                'class_number': e.class_slot.number,
                'class_day': e.class_slot.schedule_days_display or e.class_slot.day_type_display or e.class_slot.day_type,
                'class_time': e.class_slot.time_slot,
                'teacher_name': e.class_slot.teacher_name,
                'method': 'خودِ دانش‌آموز از اپ' if e.self_enrolled else 'ثبت‌نام توسط مدیریت',
                'payment_method_display': e.get_payment_method_display(),
                'payment_verified': e.payment_verified,
                'created_at_jalali': e.created_at_jalali,
            } for e in history],
            'private_classes': private_history,
            'group_classes': group_history,
        })


class StudentFinancialHistoryView(APIView):
    """
    GET: کل گردش مالی یک دانش‌آموز — ثبت‌نام‌ها، استردادها، و تراکنش‌های کیف پول،
    همه با تاریخ/ساعت، به‌ترتیب نزولی زمان. برای دکمه‌ی «📊 سوابق مالی» در پروفایل دانش‌آموز.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            student = User.objects.get(pk=student_id, role='student')
        except User.DoesNotExist:
            return Response({'error': 'دانش‌آموز پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        events = []
        for e in ClassSlotEnrollment.objects.filter(student=student).select_related('class_slot'):
            events.append({
                'type': 'enrollment', 'type_display': 'ثبت‌نام کلاس',
                'datetime': e.created_at, 'datetime_jalali': e.created_at_jalali,
                'amount': e.tuition_amount, 'direction': 'debit',
                'details': f"کلاس {e.class_slot.number} — {e.get_payment_method_display()}" + (f" — {e.discount_percent}% تخفیف" if e.discount_percent else ''),
            })
        for r in EnrollmentRefund.objects.filter(student=student).select_related('class_slot'):
            events.append({
                'type': 'refund', 'type_display': 'استرداد',
                'datetime': r.created_at, 'datetime_jalali': r.created_at_jalali,
                'amount': r.amount, 'direction': 'credit_to_person',
                'details': f"کلاس {r.class_slot.number if r.class_slot else '—'} — کارت {r.card_number} — گیرنده: {r.receiver_name}",
            })
        for w in WalletTransaction.objects.filter(student=student).select_related('class_slot'):
            events.append({
                'type': 'wallet', 'type_display': w.get_kind_display(),
                'datetime': w.created_at, 'datetime_jalali': w.created_at_jalali,
                'amount': w.amount, 'direction': 'credit' if w.kind == WalletTransaction.Kind.CREDIT else 'debit',
                'details': w.reason or (f"کلاس {w.class_slot.number}" if w.class_slot else ''),
            })
        events.sort(key=lambda x: x['datetime'], reverse=True)
        for ev in events:
            ev.pop('datetime')

        return Response({
            'student': f"{student.first_name} {student.last_name}",
            'wallet_balance': student.wallet_balance,
            'events': events,
        })


class EnrollmentReportView(APIView):
    """
    GET: گزارش دقیق ثبت‌نام‌ها با فیلتر سطح/روز/جنسیت/بازه‌ی تاریخ — به همراه جمع شهریه و
    تخفیفات به‌تفکیک سطح، برای خروجی اکسل/چاپ دقیق (خواسته‌ی ۷)
    پارامترها: level, day_type, gender, date_from, date_to (میلادی ISO)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        qs = ClassSlotEnrollment.objects.select_related('class_slot', 'student').all()
        term_id = request.query_params.get('term_id')
        level = request.query_params.get('level')
        day_type = request.query_params.get('day_type')
        gender = request.query_params.get('gender')
        student_gender = request.query_params.get('student_gender')
        teacher_name = request.query_params.get('teacher_name')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        if not term_id and not (date_from and date_to):
            return Response({'error': 'برای گزارش، یک ترم یا هر دو تاریخ «از تاریخ» و «تا تاریخ» را انتخاب کنید.'}, status=status.HTTP_400_BAD_REQUEST)

        if term_id:
            qs = qs.filter(class_slot__term_id=term_id)
        if level:
            level_list = [x.strip() for x in level.split(',') if x.strip()]
            if level_list:
                qs = qs.filter(class_slot__assigned_level__in=level_list)
        if day_type:
            qs = qs.filter(class_slot__day_type=day_type)
        if gender:
            qs = qs.filter(class_slot__gender=gender)
        if student_gender in ('female', 'male'):
            qs = qs.filter(student__gender=student_gender)
        if teacher_name:
            qs = qs.filter(class_slot__teacher_name=teacher_name)
        # وقتی ترم انتخاب شده، بازه‌ی تاریخ فقط برای نمایش است (تاریخ ثبت‌نام‌ها ممکن است خارج
        # از بازه‌ی ترم باشد و گزارش را اشتباهاً خالی می‌کرد)؛ فیلتر تاریخ فقط در حالت بدون ترم اعمال می‌شود.
        if not term_id:
            try:
                if date_from:
                    qs = qs.filter(created_at__date__gte=date_from)
                if date_to:
                    qs = qs.filter(created_at__date__lte=date_to)
            except (ValueError, TypeError, ValidationError):
                return Response({'error': 'فرمت تاریخ نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)

        enrollments = []
        by_level = {}
        by_teacher_level = {}
        by_student_gender = {}
        for e in qs.order_by('-created_at'):
            lvl = e.class_slot.assigned_level or 'نامشخص'
            row = by_level.setdefault(lvl, {'level': lvl, 'count': 0, 'total_tuition': 0, 'discount_count': 0, 'total_discount_amount': 0})
            row['count'] += 1
            row['total_tuition'] += e.tuition_amount or 0
            teacher = (e.class_slot.teacher_name or 'بدون استاد').strip()
            teacher_level = by_teacher_level.setdefault((teacher, lvl), {'teacher': teacher, 'level': lvl, 'count': 0, 'female_count': 0, 'male_count': 0})
            teacher_level['count'] += 1
            if e.student.gender in ('female', 'male'):
                teacher_level[f"{e.student.gender}_count"] += 1
            gender_key = e.student.gender or 'unknown'
            by_student_gender.setdefault(gender_key, {'gender': gender_key, 'count': 0})['count'] += 1
            if (e.discount_percent or 0) > 0:
                row['discount_count'] += 1
                row['total_discount_amount'] += e.tuition_amount or 0
            enrollments.append({
                'id': e.id, 'student_name': f"{e.student.first_name} {e.student.last_name}",
                'student_national_code': e.student.national_code, 'student_gender': e.student.gender,
                'teacher_name': e.class_slot.teacher_name,
                'class_number': e.class_slot.number, 'level': lvl, 'day_type_display': e.class_slot.day_type_display,
                'time_slot': e.class_slot.time_slot, 'gender': e.class_slot.gender, 'gender_display': e.class_slot.get_gender_display(),
                'payment_method_display': e.get_payment_method_display(), 'tuition_amount': e.tuition_amount,
                'discount_percent': e.discount_percent, 'created_at_jalali': e.created_at_jalali,
            })

        return Response({
            'enrollments': enrollments,
            'summary_by_level': sorted(by_level.values(), key=lambda r: r['level']),
            'summary_by_teacher_level': sorted(by_teacher_level.values(), key=lambda r: (r['teacher'], r['level'])),
            'summary_by_gender': sorted(by_student_gender.values(), key=lambda r: r['gender']),
            'total_count': len(enrollments),
            'total_tuition': sum((r['tuition_amount'] or 0) for r in enrollments),
        })


class EnrollmentTermChartView(APIView):
    """
    GET: داده‌ی نمودار میله‌ای «تعداد زبان‌آموزان» در گزارش دقیق ثبت‌نام + فهرست سطوح/استادان موجود در ترم.
    پارامترها:
      term_id   — (اختیاری) ترم؛ اگر نباشد همه‌ی ترم‌ها
      group_by  — level (پیش‌فرض) | teacher
      value     — (اختیاری) چند سطح (جداشده با ویرگول) یا یک استاد؛ خالی = همه
      teacher_level — گروه‌بندی ترکیبی استاد و سطح
      gender    — (اختیاری) female | male: جنسیت زبان‌آموز
    خروجی: available_levels / available_teachers (برای قرمز و غیرفعال‌کردن موارد غایب در ترم)
    و bars: [{label, count}] (تعداد زبان‌آموز یکتا).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_view_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        term_id = (request.query_params.get('term_id') or '').strip()
        group_by = request.query_params.get('group_by') or 'level'
        value = (request.query_params.get('value') or '').strip()
        gender = (request.query_params.get('gender') or '').strip()
        if group_by not in ('level', 'teacher', 'teacher_level'):
            group_by = 'level'
        if term_id and not term_id.isdigit():
            return Response({'error': 'ترم نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)

        slot_qs = ClassSlot.objects.all()
        if term_id:
            slot_qs = slot_qs.filter(term_id=int(term_id))
        available_levels = sorted({(l or '').strip() for l in slot_qs.values_list('assigned_level', flat=True) if (l or '').strip()})
        available_teachers = sorted({(t or '').strip() for t in slot_qs.values_list('teacher_name', flat=True) if (t or '').strip()})
        available_teacher_levels = sorted({f"{(t or 'بدون استاد').strip()} — {(l or 'بدون سطح').strip()}" for t, l in slot_qs.values_list('teacher_name', 'assigned_level')})

        qs = ClassSlotEnrollment.objects.filter(class_slot__in=slot_qs, student__role='student').filter(
            Q(is_carryover=False) | Q(carryover_confirmed=True)
        ).select_related('class_slot', 'student')
        if gender in ('female', 'male'):
            qs = qs.filter(student__gender=gender)

        field = 'assigned_level' if group_by == 'level' else 'teacher_name'
        value_set = {x.strip() for x in value.split(',') if x.strip()} if group_by == 'level' else ({value} if value else set())
        buckets = {}
        for e in qs:
            if group_by == 'teacher_level':
                label = f"{(e.class_slot.teacher_name or 'بدون استاد').strip()} — {(e.class_slot.assigned_level or 'بدون سطح').strip()}"
            else:
                label = (getattr(e.class_slot, field) or '').strip() or ('بدون سطح' if group_by == 'level' else 'بدون استاد')
            if value_set and label not in value_set:
                continue
            buckets.setdefault(label, set()).add(e.student_id)

        pool = available_levels if group_by == 'level' else (available_teacher_levels if group_by == 'teacher_level' else available_teachers)
        if value_set:
            labels = [l for l in (pool if group_by in ('level', 'teacher_level') else sorted(value_set)) if l in value_set] + [l for l in sorted(value_set) if l not in pool]
        else:
            labels = list(pool) + [l for l in buckets if l not in pool]
        bars = [{'label': l, 'count': len(buckets.get(l, ()))} for l in labels]
        return Response({
            'available_levels': available_levels,
            'available_teachers': available_teachers,
            'available_teacher_levels': available_teacher_levels,
            'group_by': group_by,
            'bars': bars,
            'total': len({sid for ids in buckets.values() for sid in ids}),
        })


class TermEnrollmentComparisonView(APIView):
    """یک تصویر تجمیعی از تعداد زبان‌آموزان یکتا در همهٔ ترم‌ها برای مقایسهٔ پیوسته."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_view_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        ordered_terms = list(Term.objects.all().order_by('start_date', 'id'))
        term_ids = {term.id for term in ordered_terms}
        slots = {
            slot.id: slot
            for slot in ClassSlot.objects.filter(term_id__in=term_ids).only(
                'id', 'term_id', 'assigned_level', 'day_type'
            )
        }
        sets = {
            term.id: {'all': set(), 'levels': {}, 'genders': {}, 'days': {}}
            for term in ordered_terms
        }
        enrollments = ClassSlotEnrollment.objects.filter(
            class_slot_id__in=slots.keys(), student__role='student', payment_verified=True
        ).filter(Q(is_carryover=False) | Q(carryover_confirmed=True)).values_list(
            'class_slot_id', 'student_id', 'student__gender'
        )
        for slot_id, student_id, student_gender in enrollments.iterator(chunk_size=2000):
            slot = slots.get(slot_id)
            if not slot or slot.term_id not in sets:
                continue
            bucket = sets[slot.term_id]
            bucket['all'].add(student_id)
            level = (slot.assigned_level or '').strip() or 'بدون سطح'
            gender = student_gender if student_gender in ('female', 'male') else 'unknown'
            day = slot.get_day_type_display() or 'نامشخص'
            bucket['levels'].setdefault(level, set()).add(student_id)
            bucket['genders'].setdefault(gender, set()).add(student_id)
            bucket['days'].setdefault(day, set()).add(student_id)

        levels = sorted({key for item in sets.values() for key in item['levels']}, key=str.casefold)
        days = sorted({key for item in sets.values() for key in item['days']}, key=str.casefold)
        terms_payload = [{
            'id': term.id,
            'title': term.title,
            'start_date': term.start_date.isoformat() if term.start_date else None,
            'total': len(sets[term.id]['all']),
            'levels': {level: len(sets[term.id]['levels'].get(level, set())) for level in levels},
            'genders': {gender: len(sets[term.id]['genders'].get(gender, set())) for gender in ('female', 'male', 'unknown')},
            'days': {day: len(sets[term.id]['days'].get(day, set())) for day in days},
        } for term in ordered_terms]
        return Response({
            'terms': terms_payload,
            'levels': levels,
            'days': days,
            'latest_term_id': ordered_terms[-1].id if ordered_terms else None,
            'generated_at': timezone.now().isoformat(),
        })


class LevelProgressionSkipReportView(APIView):
    """گزارش زبان‌آموزانی که در ترم جاری از سطح ثبت‌نام‌شدهٔ قبلی، سطحی را جا انداخته‌اند."""
    permission_classes = [IsAuthenticated]

    HEADERS = [
        'نام و نام‌خانوادگی', 'کد ملی', 'شماره همراه',
        'آخرین ترم تحصیل‌شده', 'سطح قبلی', 'کلاس قبلی', 'روز کلاس قبلی', 'ساعت کلاس قبلی', 'استاد قبلی',
        'ترم جاری', 'سطح فعلی', 'کلاس فعلی', 'روز کلاس فعلی', 'ساعت کلاس فعلی', 'استاد فعلی',
        'سطح/سطوح جاافتاده', 'وضعیت عملیات',
    ]

    @staticmethod
    def _cell_values(row):
        return [
            row['student_name'], row['national_code'], row['phone'],
            row['previous_term_title'], row['previous_level'], row['previous_class_number'],
            row['previous_day'], row['previous_time_slot'], row['previous_teacher'],
            row['current_term_title'], row['current_levels'], row['current_class_numbers'],
            row['current_days'], row['current_time_slots'], row['current_teachers'],
            row['skipped_levels_text'], row.get('operation_status_text', ''),
        ]

    def get(self, request):
        if not can_view_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        from level_tests.models import StandardLevel
        from accounts.models import ClassRequest

        requested_term_id = request.query_params.get('current_term_id')
        if requested_term_id:
            try:
                current_term = Term.objects.filter(pk=int(requested_term_id)).first()
            except (TypeError, ValueError):
                current_term = None
            if not current_term:
                return Response({'error': 'ترم جاری پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        else:
            current_term = Term.objects.order_by('-year', '-term_number').first()
        if not current_term:
            return Response({'error': 'هیچ ترمی تعریف نشده است'}, status=status.HTTP_400_BAD_REQUEST)

        ordered_levels = list(StandardLevel.objects.all().order_by('age_group', 'order', 'code'))
        levels_by_group = {}
        levels_by_code = {}
        for level in ordered_levels:
            key = _normalize_level(level.code)
            levels_by_group.setdefault(level.age_group, []).append(level)
            levels_by_code[key] = level
        level_positions = {
            _normalize_level(level.code): (group, index)
            for group, levels in levels_by_group.items()
            for index, level in enumerate(levels)
        }

        current_enrollments = ClassSlotEnrollment.objects.filter(
            class_slot__term_id=current_term.pk,
            student__role='student',
            payment_verified=True,
        ).filter(Q(is_carryover=False) | Q(carryover_confirmed=True)).select_related(
            'student', 'class_slot', 'class_slot__term',
        ).order_by('student_id', 'created_at', 'id')
        current_by_student = {}
        for enrollment in current_enrollments:
            current_by_student.setdefault(enrollment.student_id, []).append(enrollment)

        if not current_by_student:
            results = []
        else:
            earlier_term_filter = (
                Q(class_slot__term__year__lt=current_term.year)
                | Q(class_slot__term__year=current_term.year, class_slot__term__term_number__lt=current_term.term_number)
            )
            previous_enrollments = ClassSlotEnrollment.objects.filter(
                student_id__in=current_by_student.keys(),
                student__role='student',
                class_slot__term__isnull=False,
                payment_verified=True,
            ).filter(earlier_term_filter).filter(
                Q(is_carryover=False) | Q(carryover_confirmed=True)
            ).select_related('student', 'class_slot', 'class_slot__term').order_by(
                'student_id', '-class_slot__term__year', '-class_slot__term__term_number', '-created_at', '-id',
            )
            latest_previous_by_student = {}
            for enrollment in previous_enrollments:
                latest_previous_by_student.setdefault(enrollment.student_id, enrollment)

            student_ids = list(current_by_student.keys())
            operation_by_student = {}
            sequence_requests = ClassRequest.objects.filter(
                Q(student_id__in=student_ids),
                Q(sequence_warning=True) | Q(source_level_test__sequence_warning=True),
                class_type__in=[ClassRequest.ClassType.PRIVATE, ClassRequest.ClassType.MAKEUP],
            ).exclude(status__in=[ClassRequest.Status.CANCELLED, ClassRequest.Status.REJECTED]).select_related(
                'student', 'source_level_test', 'teacher',
            ).order_by('-created_at', '-id')
            for class_request in sequence_requests:
                kind = 'private' if class_request.class_type == ClassRequest.ClassType.PRIVATE else 'makeup'
                operation_by_student.setdefault(class_request.student_id, []).append({
                    'kind': kind,
                    'label': class_request.get_class_type_display(),
                    'id': class_request.id,
                    'status': class_request.get_status_display(),
                    'payment_status': class_request.get_payment_status_display(),
                    'level': class_request.language_level or '—',
                    'sessions': class_request.session_count or 1,
                    'teacher': class_request.teacher.get_full_name().strip() if class_request.teacher else 'تعیین نشده',
                    'proposed_time': class_request.proposed_time or '—',
                    'class_date': class_request.class_date_jalali or '—',
                    'summary': f"وضعیت: {class_request.get_status_display()} — سطح: {class_request.language_level or '—'} — پرداخت: {class_request.get_payment_status_display()} — تعداد جلسات: {class_request.session_count or 1}",
                })
            sequence_tests = LevelTest.objects.filter(
                student_id__in=student_ids,
                sequence_warning=True,
            ).select_related('student').order_by('-created_at', '-id')
            for level_test in sequence_tests:
                operation_by_student.setdefault(level_test.student_id, []).append({
                    'kind': 'level-test',
                    'label': 'تعیین سطح',
                    'id': level_test.id,
                    'status': level_test.get_status_display(),
                    'test_date': level_test.test_date_jalali or '—',
                    'age_group': level_test.get_age_group_display() if level_test.age_group else '—',
                    'level': level_test.level or '—',
                    'summary': f"وضعیت: {level_test.get_status_display()} — زمان: {level_test.test_date_jalali or 'تعیین نشده'} — گروه سنی: {level_test.get_age_group_display() if level_test.age_group else '—'} — سطح: {level_test.level or '—'}",
                })
            for student_id in operation_by_student:
                operation_by_student[student_id].sort(key=lambda item: (item['kind'] != 'level-test', -int(item['id'])))

            results = []
            for student_id, current_rows in current_by_student.items():
                previous = latest_previous_by_student.get(student_id)
                if not previous:
                    continue
                previous_slot = previous.class_slot
                previous_level_key = _normalize_level(previous_slot.assigned_level)
                previous_level = levels_by_code.get(previous_level_key)
                previous_position = level_positions.get(previous_level_key)
                if not previous_level or not previous_position or previous_level.is_terminal:
                    continue

                missed_level_codes = set()
                skipped_current_classes = []
                all_current_classes = []
                previous_group, previous_index = previous_position
                group_levels = levels_by_group.get(previous_group, [])
                for enrollment in current_rows:
                    current_slot = enrollment.class_slot
                    if current_slot.pk not in {item['id'] for item in all_current_classes}:
                        all_current_classes.append({
                            'id': current_slot.pk,
                            'level': current_slot.assigned_level or '',
                            'class_number': str(current_slot.number),
                            'day': current_slot.day_type_display,
                            'time_slot': current_slot.time_slot or '—',
                            'teacher': current_slot.teacher_name or '—',
                        })
                    current_level_key = _normalize_level(current_slot.assigned_level)
                    current_position = level_positions.get(current_level_key)
                    if not current_position:
                        continue
                    current_group, current_index = current_position
                    # فقط پرش روبه‌جلو در همان ردهٔ سنی، نسبت به ترتیب رسمی سطوح، گزارش می‌شود.
                    if current_group != previous_group or current_index <= previous_index + 1:
                        continue
                    missed_level_codes.update(
                        level.code for level in group_levels[previous_index + 1:current_index]
                    )
                    skipped_current_classes.append(current_slot.pk)
                if not skipped_current_classes:
                    continue

                group_order = {level.code: index for index, level in enumerate(group_levels)}
                missed_codes = sorted(missed_level_codes, key=lambda code: group_order.get(code, 10**9))
                current_term_title = current_term.title
                operations = operation_by_student.get(student_id, [])
                results.append({
                    'student_id': student_id,
                    'student_name': previous.student.get_full_name().strip() or previous.student.username,
                    'national_code': previous.student.national_code or '',
                    'phone': previous.student.phone or '',
                    'previous_term_id': previous_slot.term_id,
                    'previous_term_title': previous_slot.term.title,
                    'previous_level': previous_slot.assigned_level or '—',
                    'previous_class_number': str(previous_slot.number),
                    'previous_day': previous_slot.day_type_display,
                    'previous_time_slot': previous_slot.time_slot or '—',
                    'previous_teacher': previous_slot.teacher_name or '—',
                    'current_term_id': current_term.pk,
                    'current_term_title': current_term_title,
                    'current_levels': '، '.join(dict.fromkeys(item['level'] or '—' for item in all_current_classes)),
                    'current_class_numbers': '، '.join(dict.fromkeys(item['class_number'] for item in all_current_classes)),
                    'current_class_ids': [item['id'] for item in all_current_classes],
                    'level_change_slot_id': next((item['id'] for item in all_current_classes if item['id'] in skipped_current_classes), all_current_classes[0]['id'] if all_current_classes else None),
                    'current_days': '؛ '.join(dict.fromkeys(item['day'] for item in all_current_classes)),
                    'current_time_slots': '؛ '.join(dict.fromkeys(item['time_slot'] for item in all_current_classes)),
                    'current_teachers': '؛ '.join(dict.fromkeys(item['teacher'] for item in all_current_classes)),
                    'skipped_levels': missed_codes,
                    'skipped_levels_text': '، '.join(missed_codes),
                    'operations': operations,
                    'operation_status_text': '، '.join(dict.fromkeys(item['label'] for item in operations)),
                    'sequence_warning_details': {
                        'previous_term': previous_slot.term.title,
                        'previous_level': previous_slot.assigned_level or '—',
                        'current_term': current_term_title,
                        'current_level': '، '.join(dict.fromkeys(item['level'] or '—' for item in all_current_classes)),
                        'skipped_levels': missed_codes,
                        'skipped_levels_text': '، '.join(missed_codes),
                        'previous_class': str(previous_slot.number),
                        'current_classes': '، '.join(dict.fromkeys(item['class_number'] for item in all_current_classes)),
                    },
                })

        results.sort(key=lambda row: (row['student_name'].casefold(), row['national_code']))
        if request.query_params.get('format') == 'xlsx':
            try:
                from openpyxl import Workbook
                from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
                from openpyxl.utils import get_column_letter
            except ImportError:
                return Response({'error': 'کتابخانهٔ openpyxl روی سرور نصب نیست؛ برای ساخت خروجی XLSX آن را نصب کنید.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

            import io
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = 'پرش سطح'
            sheet.sheet_view.rightToLeft = True
            sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(self.HEADERS))
            sheet.cell(row=1, column=1, value=f'گزارش رعایت‌نشدن توالی سطح — ترم جاری: {current_term.title}')
            sheet.cell(row=1, column=1).font = Font(bold=True, size=14, color='FFFFFF')
            sheet.cell(row=1, column=1).fill = PatternFill('solid', fgColor='17365D')
            sheet.cell(row=1, column=1).alignment = Alignment(horizontal='center', vertical='center')
            sheet.row_dimensions[1].height = 28
            sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(self.HEADERS))
            sheet.cell(row=2, column=1, value=f'تعداد افراد: {len(results)} — آخرین ترم ثبت‌نام تأییدشدهٔ قبلی هر فرد، حتی اگر ترم‌ها متوالی نباشند، مبنای مقایسه است.')
            sheet.cell(row=2, column=1).alignment = Alignment(horizontal='right', vertical='center', wrap_text=True)

            header_row = 4
            thin = Side(style='thin', color='D0D7DE')
            border = Border(left=thin, right=thin, top=thin, bottom=thin)
            for column_index, header in enumerate(self.HEADERS, start=1):
                cell = sheet.cell(row=header_row, column=column_index, value=header)
                cell.font = Font(bold=True, color='FFFFFF')
                cell.fill = PatternFill('solid', fgColor='1F6FEB')
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
                cell.border = border
            export_values = [self._cell_values(item) for item in results]
            for row_index, item in enumerate(results, start=header_row + 1):
                for column_index, value in enumerate(export_values[row_index - header_row - 1], start=1):
                    cell = sheet.cell(row=row_index, column=column_index, value=str(value or ''))
                    cell.data_type = 's'
                    cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
                    cell.border = border
            sheet.row_dimensions[header_row].height = 34
            for column_index, header in enumerate(self.HEADERS, start=1):
                values = [len(str(row[column_index - 1] or '')) for row in export_values]
                width = min(max([len(header), *values] or [len(header)]) + 2, 38)
                sheet.column_dimensions[get_column_letter(column_index)].width = max(width, 12)
            sheet.freeze_panes = f'A{header_row + 1}'
            sheet.auto_filter.ref = f'A{header_row}:{get_column_letter(len(self.HEADERS))}{max(header_row, header_row + len(results))}'
            sheet.page_setup.orientation = 'landscape'
            sheet.page_setup.fitToWidth = 1
            sheet.page_setup.fitToHeight = 0
            sheet.sheet_properties.pageSetUpPr.fitToPage = True
            buffer = io.BytesIO()
            workbook.save(buffer)
            response = HttpResponse(
                buffer.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            response['Content-Disposition'] = f'attachment; filename="level-progression-skips-{current_term.pk}.xlsx"'
            return response

        return Response({
            'current_term': {'id': current_term.pk, 'title': current_term.title},
            'count': len(results),
            'results': results,
        })


class TermRetentionFollowUpView(APIView):
    """مقایسهٔ دانش‌آموزان ثبت‌نام‌شدهٔ دو ترم و ذخیرهٔ نتیجهٔ پیگیری عدم ثبت‌نام."""
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _term_pair(params, require_explicit=False):
        terms = list(Term.objects.order_by('-year', '-term_number'))
        if len(terms) < 2:
            raise ValueError('برای مقایسه، دست‌کم دو ترم باید تعریف شده باشد')

        current_id = params.get('current_term_id')
        previous_id = params.get('previous_term_id')
        if require_explicit and (not current_id or not previous_id):
            raise ValueError('ترم قبل و ترم جاری الزامی است')

        current_term = next((term for term in terms if current_id and str(term.pk) == str(current_id)), None)
        if current_id and current_term is None:
            raise ValueError('ترم جاری پیدا نشد')
        current_term = current_term or terms[0]

        previous_term = next((term for term in terms if previous_id and str(term.pk) == str(previous_id)), None)
        if previous_id and previous_term is None:
            raise ValueError('ترم قبل پیدا نشد')
        if previous_term is None:
            current_index = terms.index(current_term)
            previous_term = terms[current_index + 1] if current_index + 1 < len(terms) else None
        if previous_term is None:
            raise ValueError('برای ترم انتخاب‌شده، ترم قدیمی‌تری وجود ندارد')
        if previous_term.pk == current_term.pk:
            raise ValueError('ترم قبل و ترم جاری نمی‌توانند یکسان باشند')
        if (previous_term.year, previous_term.term_number) >= (current_term.year, current_term.term_number):
            raise ValueError('ترم قبل باید از نظر سال و شماره، قدیمی‌تر از ترم جاری باشد')
        return previous_term, current_term

    @staticmethod
    def _class_payload(slot):
        return {
            'id': slot.pk,
            'number': slot.number,
            'title': slot.title,
            'day_type': slot.day_type,
            'day_type_display': slot.day_type_display,
            'time_slot': slot.time_slot,
            'level': slot.assigned_level,
            'teacher_name': slot.teacher_name or '',
            'gender': slot.gender,
            'gender_display': slot.get_gender_display(),
            'is_online': slot.is_online,
        }

    def get(self, request):
        if not can_view_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            previous_term, current_term = self._term_pair(request.query_params)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        previous_enrollments = ClassSlotEnrollment.objects.filter(
            class_slot__term_id=previous_term.pk,
            payment_verified=True,
            student__role='student',
        ).select_related('student', 'class_slot').order_by('student__last_name', 'student__first_name', 'class_slot__number')

        students = {}
        for enrollment in previous_enrollments:
            student = enrollment.student
            row = students.setdefault(student.pk, {
                'student': student,
                'previous_classes': [],
            })
            row['previous_classes'].append(self._class_payload(enrollment.class_slot))

        student_ids = list(students.keys())
        current_states = {}
        if student_ids:
            current_enrollments = ClassSlotEnrollment.objects.filter(
                class_slot__term_id=current_term.pk,
                student_id__in=student_ids,
            ).select_related('class_slot').order_by('student_id', 'class_slot__number')
            for enrollment in current_enrollments:
                state = current_states.setdefault(enrollment.student_id, {
                    'kind': 'not_registered',
                    'classes': [],
                })
                state['classes'].append({
                    **self._class_payload(enrollment.class_slot),
                    'payment_verified': enrollment.payment_verified,
                    'is_carryover': enrollment.is_carryover,
                    'carryover_confirmed': enrollment.carryover_confirmed,
                })
                if enrollment.payment_verified and (not enrollment.is_carryover or enrollment.carryover_confirmed):
                    state['kind'] = 'registered'
                elif not enrollment.payment_verified and state['kind'] != 'registered':
                    state['kind'] = 'pending_payment'
                elif enrollment.is_carryover and state['kind'] not in {'registered', 'pending_payment'}:
                    state['kind'] = 'carried_forward'

            for state in current_states.values():
                verified_class_ids = {
                    item['id'] for item in state['classes']
                    if item['payment_verified'] and (not item['is_carryover'] or item['carryover_confirmed'])
                }
                if len(verified_class_ids) > 1:
                    state['kind'] = 'registered'

        followups = {
            item.student_id: item
            for item in TermRetentionFollowUp.objects.filter(
                previous_term=previous_term,
                current_term=current_term,
                student_id__in=student_ids,
            ).select_related('updated_by')
        }

        results = []
        for student_id, item in students.items():
            student = item['student']
            followup = followups.get(student_id)
            current = current_states.get(student_id, {'kind': 'not_registered', 'classes': []})
            follow_up_status = followup.status if followup else TermRetentionFollowUp.Status.NEEDS_FOLLOW_UP
            needs_follow_up = (
                current['kind'] in {'carried_forward', 'not_registered'}
                and follow_up_status not in {
                    TermRetentionFollowUp.Status.DROPOUT_CONFIRMED,
                    TermRetentionFollowUp.Status.GRADUATED,
                    TermRetentionFollowUp.Status.TRANSFERRED,
                }
            )
            results.append({
                'student_id': student.pk,
                'student_name': student.get_full_name().strip() or student.username,
                'national_code': student.national_code or '',
                'phone': student.phone or '',
                'previous_classes': item['previous_classes'],
                'current_classes': current['classes'],
                'current_state': current['kind'],
                'current_state_display': {
                    'registered': 'ثبت‌نام تأییدشده در ترم جاری',
                    'pending_payment': 'ثبت‌نام در انتظار تأیید پرداخت',
                    'carried_forward': 'منتقل‌شده از ترم قبل؛ نیازمند تأیید تمدید',
                    'not_registered': 'در ترم جاری ثبت‌نام ندارد',
                }[current['kind']],
                'needs_follow_up': needs_follow_up,
                'follow_up_status': follow_up_status,
                'follow_up_status_display': followup.get_status_display() if followup else TermRetentionFollowUp.Status.NEEDS_FOLLOW_UP.label,
                'reason': followup.reason if followup else '',
                'reason_display': followup.get_reason_display() if followup and followup.reason else '',
                'notes': followup.notes if followup else '',
                'next_follow_up_date': followup.next_follow_up_date.isoformat() if followup and followup.next_follow_up_date else '',
                'last_contacted_at': followup.last_contacted_at.isoformat() if followup and followup.last_contacted_at else '',
                'updated_by': followup.updated_by.get_full_name() if followup and followup.updated_by else '',
            })

        day_filter = request.query_params.get('day_type') or ''
        level_filter = request.query_params.get('level') or ''
        gender_filter = request.query_params.get('gender') or ''
        teacher_filter = str(request.query_params.get('teacher_name') or '').strip()
        teacher_options = sorted({
            slot['teacher_name']
            for row in results
            for slot in (row['current_classes'] or row['previous_classes'])
            if slot['teacher_name']
        }, key=str.casefold)
        if day_filter or level_filter or gender_filter or teacher_filter:
            filtered_results = []
            for row in results:
                # فردِ منتقل‌شده با کلاس مقصدش فیلتر می‌شود؛ اگر اصلاً در ترم جاری کلاسی ندارد،
                # کلاس‌های ترم مبدأ مبنا هستند تا از فهرست قابل پیگیری حذف نشود.
                filter_classes = row['current_classes'] or row['previous_classes']
                if any(
                    (not day_filter or slot['day_type'] == day_filter)
                    and (not level_filter or slot['level'] == level_filter)
                    and (not gender_filter or slot['gender'] == gender_filter)
                    and (not teacher_filter or slot['teacher_name'].casefold() == teacher_filter.casefold())
                    for slot in filter_classes
                ):
                    filtered_results.append(row)
            results = filtered_results

        summary = {
            'previous_total': len(results),
            'registered_count': sum(1 for row in results if row['current_state'] == 'registered'),
            'pending_payment_count': sum(1 for row in results if row['current_state'] == 'pending_payment'),
            'carried_forward_count': sum(1 for row in results if row['current_state'] == 'carried_forward'),
            'not_registered_count': sum(1 for row in results if row['current_state'] == 'not_registered'),
            'needs_follow_up_count': sum(1 for row in results if row['needs_follow_up']),
            'confirmed_dropout_count': sum(
                1 for row in results
                if row['current_state'] in {'carried_forward', 'not_registered'}
                and row['follow_up_status'] == TermRetentionFollowUp.Status.DROPOUT_CONFIRMED
            ),
            'confirmed_in_other_or_same_class_count': sum(
                1 for row in results if row['current_state'] == 'registered'
            ),
        }
        return Response({
            'previous_term': {'id': previous_term.pk, 'title': previous_term.title},
            'current_term': {'id': current_term.pk, 'title': current_term.title},
            'active_filters': {'day_type': day_filter, 'level': level_filter, 'gender': gender_filter, 'teacher_name': teacher_filter},
            'teacher_options': teacher_options,
            'summary': summary,
            'status_options': [{'value': value, 'label': label} for value, label in TermRetentionFollowUp.Status.choices],
            'reason_options': [{'value': value, 'label': label} for value, label in TermRetentionFollowUp.Reason.choices],
            'results': results,
        })

    def post(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ویرایش ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            previous_term, current_term = self._term_pair(request.data, require_explicit=True)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        student_id = request.data.get('student_id')
        if not student_id:
            return Response({'error': 'شناسهٔ دانش‌آموز الزامی است'}, status=status.HTTP_400_BAD_REQUEST)
        if not ClassSlotEnrollment.objects.filter(
            class_slot__term_id=previous_term.pk,
            student_id=student_id,
            student__role='student',
            payment_verified=True,
        ).exists():
            return Response({'error': 'این دانش‌آموز در ترم قبل ثبت‌نام تأییدشده ندارد'}, status=status.HTTP_404_NOT_FOUND)
        current_student_enrollments = ClassSlotEnrollment.objects.filter(
            class_slot__term_id=current_term.pk,
            student_id=student_id,
        )
        verified_current_rows = list(current_student_enrollments.filter(payment_verified=True).values(
            'class_slot_id', 'is_carryover', 'carryover_confirmed',
        ))
        has_confirmed_registration = any(
            not row['is_carryover'] or row['carryover_confirmed'] for row in verified_current_rows
        ) or len({row['class_slot_id'] for row in verified_current_rows}) > 1
        has_pending_payment = current_student_enrollments.filter(payment_verified=False).exists()
        if has_confirmed_registration or has_pending_payment:
            return Response({'error': 'این دانش‌آموز در ترم جاری ثبت‌نام قطعی یا پرداخت در انتظار تأیید دارد؛ وضعیت ریزش برای او ثبت نمی‌شود'}, status=status.HTTP_400_BAD_REQUEST)

        follow_up_status = request.data.get('follow_up_status') or TermRetentionFollowUp.Status.NEEDS_FOLLOW_UP
        allowed_statuses = {value for value, _ in TermRetentionFollowUp.Status.choices}
        if follow_up_status not in allowed_statuses:
            return Response({'error': 'وضعیت پیگیری نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        reason = request.data.get('reason') or ''
        allowed_reasons = {value for value, _ in TermRetentionFollowUp.Reason.choices}
        if reason and reason not in allowed_reasons:
            return Response({'error': 'علت پیگیری نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)

        follow_up_date_text = request.data.get('next_follow_up_date') or ''
        if follow_up_date_text:
            try:
                next_follow_up_date = datetime.strptime(str(follow_up_date_text), '%Y-%m-%d').date()
            except ValueError:
                return Response({'error': 'تاریخ پیگیری باید به صورت YYYY-MM-DD باشد'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            next_follow_up_date = None

        record_defaults = {
            'status': follow_up_status,
            'reason': reason,
            'notes': str(request.data.get('notes') or '').strip(),
            'next_follow_up_date': next_follow_up_date,
            'updated_by': request.user,
        }
        if follow_up_status != TermRetentionFollowUp.Status.NEEDS_FOLLOW_UP:
            record_defaults['last_contacted_at'] = timezone.now()
        record, _ = TermRetentionFollowUp.objects.update_or_create(
            student_id=student_id,
            previous_term=previous_term,
            current_term=current_term,
            defaults=record_defaults,
        )
        return Response({
            'message': 'نتیجهٔ پیگیری ذخیره شد',
            'student_id': record.student_id,
            'follow_up_status': record.status,
            'follow_up_status_display': record.get_status_display(),
            'reason': record.reason,
            'reason_display': record.get_reason_display() if record.reason else '',
            'next_follow_up_date': record.next_follow_up_date.isoformat() if record.next_follow_up_date else '',
            'last_contacted_at': record.last_contacted_at.isoformat() if record.last_contacted_at else '',
        })


class MyEnrollmentsView(APIView):
    """
    GET: لیست همه‌ی دوره‌های ترمیکی که خودِ دانش‌آموز (چه با ثبت‌نام مستقیم مدیر، چه با
    ثبت‌نام خودش از اپ) توشون ثبت‌نام شده — سطح، شماره‌ی کلاس، استاد، روز/ساعت، شهریه،
    وضعیت تخفیف و وضعیت تایید پرداخت. برای بخش «دوره‌های ترمیک من» توی صفحه‌ی اصلی اپ.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = request.user
        if student.role != 'student':
            return Response({'error': 'این بخش فقط برای دانش‌آموزان است'}, status=status.HTTP_403_FORBIDDEN)

        from grading.models import StudentGrade
        enrollments = ClassSlotEnrollment.objects.filter(student=student).select_related('class_slot', 'class_slot__term').order_by('-created_at')
        grade_map = {
            g.class_slot_id: g for g in StudentGrade.objects.filter(
                student=student, class_slot_id__in=[e.class_slot_id for e in enrollments], is_finalized=True,
            )
        }
        return Response([{
            'id': e.id,
            'class_slot_id': e.class_slot_id,
            'class_number': e.class_slot.number,
            'level': e.class_slot.assigned_level,
            'teacher_name': e.class_slot.teacher_name,
            'day_type_display': e.class_slot.day_type_display,
            'time_slot': e.class_slot.time_slot,
            'gender_display': e.class_slot.get_gender_display(),
            'is_online': e.class_slot.is_online,
            'meeting_link': e.class_slot.meeting_link if (e.class_slot.is_online and e.payment_verified) else '',
            'term_title': e.class_slot.term.title if e.class_slot.term_id else '',
            'term_start_jalali': e.class_slot.term.start_date_jalali if e.class_slot.term_id else '',
            'term_end_jalali': e.class_slot.term.end_date_jalali if e.class_slot.term_id else '',
            'capacity': e.class_slot.capacity,
            'current_count': e.class_slot.current_count,
            'tuition_amount': e.tuition_amount,
            'discount_percent': e.discount_percent,
            'payment_method_display': e.get_payment_method_display(),
            'self_enrolled': e.self_enrolled,
            'payment_verified': e.payment_verified,
            'created_at_jalali': e.created_at_jalali,
            'grade_finalized': e.class_slot_id in grade_map,
            'grade_is_fail': grade_map[e.class_slot_id].is_fail if e.class_slot_id in grade_map else False,
            'grade_total_score': grade_map[e.class_slot_id].total_score if e.class_slot_id in grade_map else None,
        } for e in enrollments])


MAX_LEVELS_NEEDING_RETEST = {'i5', 'teen15', 'teen 15'}  # آخرین سطح کودکان/نوجوانان — عبور از این‌ها همیشه به تعیین‌سطح تازه نیاز دارد


def class_tariff_amount(slot):
    """شهریه‌ی مصوب سطح کلاس (۰ اگر تعریف نشده)."""
    level = str(slot.assigned_level or '').strip()
    age_group = infer_age_group_from_level(level) if level else ''
    setting = TuitionSetting.objects.filter(level=level, age_group=age_group).first() if level and age_group else None
    return setting.amount if setting else 0


def tuition_difference(enrollment, target):
    """
    اختلاف شهریه‌ی کلاس مبدأ و مقصد برای انتقال. مبلغ پرداخت‌شده‌ی فرد (با همان تخفیفش) با شهریه‌ی کلاس مقصد مقایسه می‌شود.
    difference > 0 یعنی فرد باید مابه‌التفاوت بپردازد؛ < 0 یعنی مبلغی به او برمی‌گردد.
    """
    paid = int(enrollment.tuition_amount or 0)
    target_base = class_tariff_amount(target)
    target_due = round(target_base * (100 - int(enrollment.discount_percent or 0)) / 100)
    diff = target_due - paid if target_base else 0
    if not target_base:
        message = 'شهریه‌ی سطح کلاس مقصد تعریف نشده است؛ اختلاف شهریه قابل محاسبه نیست'
    elif diff > 0:
        message = f'⚠ شهریه‌ی کلاس مقصد {diff:,} تومان بیشتر از مبلغ پرداختی است ({paid:,} ← {target_due:,}) — مابه‌التفاوت باید از فرد دریافت شود'
    elif diff < 0:
        message = f'⚠ شهریه‌ی کلاس مقصد {abs(diff):,} تومان کمتر از مبلغ پرداختی است ({paid:,} ← {target_due:,}) — این مبلغ باید به فرد برگردانده شود (مثلاً کیف پول)'
    else:
        message = ''
    return {'paid': paid, 'target_due': target_due, 'difference': diff, 'message': message}


def _normalize_level(level):
    return str(level or '').strip().lower()


def _classes_matching_level(level, gender=None):
    """
    کلاس‌هایی که سطحشون با level یکیه — با مقایسه‌ی نرمال‌شده (فاصله/بزرگ‌کوچیکی حروف نادیده
    گرفته می‌شه)، نه تطبیق دقیق رشته. رفع باگ: کلاس هم‌سطح ساخته‌شده پیدا نمی‌شد چون
    assigned_level با فاصله یا حروف بزرگ/کوچیک متفاوت تایپ شده بود.

    رفع باگ دوم: جنسیت دانش‌آموز (male/female — روی مدل User) با جنسیت کلاس (boys/girls —
    روی ClassSlot) قبلاً مستقیم مقایسه می‌شد که هیچ‌وقت برابر نبودن، پس هیچ کلاس تک‌جنسیتی‌ای
    match نمی‌شد. اینجا اول به مقدار معادل ClassSlot.Gender تبدیل می‌شود.
    """
    target = _normalize_level(level)
    if not target:
        return ClassSlot.objects.none()
    matches = [c.id for c in ClassSlot.objects.all() if _normalize_level(c.assigned_level) == target]
    qs = ClassSlot.objects.filter(id__in=matches)
    if gender:
        class_gender = {'male': ClassSlot.Gender.BOYS, 'female': ClassSlot.Gender.GIRLS}.get(gender, gender)
        qs = qs.filter(Q(gender=class_gender) | Q(gender=ClassSlot.Gender.MIXED))
    return qs


_AGE_RANK = {'kids': 0, 'teen': 1, 'adult': 2}


def _suggestion_plan(level, as_target=False):
    """
    برنامهٔ پیشنهاد کلاس برای ثبت‌نام ترم بعد، بر اساس ترتیب «سطوح استاندارد» (StandardLevel.order):
    - سطح فعلی فرد (as_target=False): پیشنهاد اصلی = سطح بعدیِ همان رده سنی؛ سپس خودِ سطح فعلی،
      سطوح بالاترِ همان رده و تمام سطوح ردهٔ سنی بالاتر به‌عنوان گزینه‌های عادی.
    - فردِ بدون سطح فعلی که مدیر سطح را انتخاب کرده (as_target=True): پیشنهاد اصلی = همان سطح انتخابی؛
      سطوح بالاتر گزینهٔ عادی.
    خروجی: {سطح نرمال‌شده: (relation, sort_key)} — relation یکی از primary / same / higher / higher_age.
    """
    from level_tests.models import StandardLevel
    rows = list(StandardLevel.objects.all().order_by('age_group', 'order', 'code'))
    target = _normalize_level(level)
    current = next((row for row in rows if _normalize_level(row.code) == target), None)
    if not current:
        return {target: ('primary' if as_target else 'same', (0, 0))} if target else {}
    cur_age = _AGE_RANK.get(current.age_group, 9)

    def key(row):
        return (_AGE_RANK.get(row.age_group, 9), row.order)

    plan = {}
    higher_in_age = [r for r in rows if r.age_group == current.age_group and r.order > current.order]
    higher_age = [r for r in rows if _AGE_RANK.get(r.age_group, 9) > cur_age]
    if as_target:
        plan[target] = ('primary', key(current))
        primaries = set()
    else:
        next_order = min((r.order for r in higher_in_age), default=None)
        primaries = {r.code for r in higher_in_age if r.order == next_order} if next_order is not None else set()
        plan[target] = ('same', key(current))
    for row in higher_in_age:
        plan[_normalize_level(row.code)] = ('primary' if row.code in primaries else 'higher', key(row))
    for row in higher_age:
        plan[_normalize_level(row.code)] = ('higher_age', key(row))
    return plan


def _suggested_classes(level, gender=None, term_id=None, as_target=False):
    """کلاس‌های قابل پیشنهاد (هم‌جنس یا مختلط) با برچسب relation؛ پیشنهاد اصلی اول لیست می‌آید."""
    plan = _suggestion_plan(level, as_target=as_target)
    if not plan:
        return []
    qs = ClassSlot.objects.select_related('term')
    if term_id:
        qs = qs.filter(term_id=term_id)
    if gender:
        class_gender = {'male': ClassSlot.Gender.BOYS, 'female': ClassSlot.Gender.GIRLS}.get(gender, gender)
        qs = qs.filter(Q(gender=class_gender) | Q(gender=ClassSlot.Gender.MIXED))
    result = []
    for slot in qs:
        entry = plan.get(_normalize_level(slot.assigned_level))
        if entry:
            result.append((slot, entry[0], entry[1]))
    rank = {'primary': 0, 'same': 1, 'higher': 2, 'higher_age': 3}
    result.sort(key=lambda item: (rank[item[1]], item[2], item[0].number or 0, item[0].id))
    return result


def _compute_level_suggestion(student):
    """
    منطق مشترکِ حدس سطح دانش‌آموز برای «ثبت‌نام مستقیم» (هم پنل ادمین هم اپ):
    - سطح از نزدیک‌ترین منبع (آخرین ثبت‌نام واقعی یا آخرین تعیین‌سطحِ تکمیل‌شده) گرفته می‌شود
    - اگر بیش از ۶۰ روز از آن منبع گذشته باشد: هشدار اعتبار (قابل دور زدن با تایید مدیر آموزش)
    - اگر آخرین سطح، آخرین سطح گروه سنی‌اش باشد (i5 یا teen15): هشدار سطح پایانی (تعیین‌سطح الزامی، بدون امکان تایید مدیر آموزش)
    """
    last_enrollment = ClassSlotEnrollment.objects.filter(student=student).select_related('class_slot').order_by('-created_at').first()
    last_test = LevelTest.objects.filter(student=student, status=LevelTest.Status.COMPLETED).order_by('-updated_at').first()

    level, source, source_date = '', '', None
    if last_enrollment and last_test:
        if last_enrollment.created_at >= last_test.updated_at:
            level, source, source_date = last_enrollment.class_slot.assigned_level, 'pastEnrollment', last_enrollment.created_at
        else:
            level, source, source_date = last_test.level, 'levelTest', last_test.updated_at
    elif last_enrollment:
        level, source, source_date = last_enrollment.class_slot.assigned_level, 'pastEnrollment', last_enrollment.created_at
    elif last_test:
        level, source, source_date = last_test.level, 'levelTest', last_test.updated_at

    days_since_source = (timezone.now() - source_date).days if source_date else None
    expired = days_since_source is not None and days_since_source > 60
    max_level_reached = str(level).strip().lower() in MAX_LEVELS_NEEDING_RETEST

    renewal = None
    if expired and level:
        renewal = LevelRenewalApproval.objects.filter(student=student, level=level).order_by('-created_at').first()
    renewal_status = renewal.status if renewal else None
    # اگر مدیر آموزش قبلاً همین سطح را تایید کرده، دیگر هشدار انقضا نشان داده نمی‌شود
    if renewal_status == LevelRenewalApproval.Status.APPROVED:
        expired = False

    needs_retest = expired or max_level_reached
    if max_level_reached:
        retest_reason = 'max_level_reached'
    elif expired:
        retest_reason = 'expired'
    else:
        retest_reason = ''

    eligible = []
    if level:
        eligible = _classes_matching_level(level, student.gender)

    age_group = infer_age_group_from_level(level)
    base_tuition = None
    if level and age_group:
        setting = TuitionSetting.objects.filter(level=level, age_group=age_group).first()
        if setting:
            base_tuition = setting.amount

    existing_discount = DiscountedPerson.objects.filter(student=student).order_by('-updated_at').first()
    discount_percent = existing_discount.discount_percent if existing_discount else 0

    return {
        'level': level, 'source': source, 'source_date': source_date,
        'days_since_source': days_since_source, 'needs_retest': needs_retest, 'retest_reason': retest_reason,
        'renewal_status': renewal_status, 'eligible': eligible, 'age_group': age_group,
        'base_tuition': base_tuition, 'discount_percent': discount_percent,
        # خواسته‌ی جدید: اگه نه تعیین‌سطحی داره نه هیچ کلاس قبلی، یعنی کاملاً «ورودی جدید» است —
        # اولین سطحی که براش (معمولاً با تعیین‌سطح) ثبت بشه، خودکار مبنای این تابع می‌شود چون
        # last_test/last_enrollment در دفعه‌ی بعد پیدا می‌شوند؛ فعلاً فقط پرچم هشدار لازم است.
        'is_new_entrant': not last_enrollment and not last_test,
    }


class DirectEnrollSuggestionsView(APIView):
    """
    GET: برای بخش تازه‌ی «ثبت‌نام مستقیم دانش‌آموز» — بدون اینکه از قبل کلاس مشخصی باز باشد،
    فقط با گرفتن یک دانش‌آموز، سطح مناسبش را از نزدیک‌ترین منبع حدس می‌زند: یا آخرین کلاسی که
    واقعاً توش ثبت‌نام بوده (ترم قبل)، یا آخرین آزمون تعیین‌سطح تکمیل‌شده — هرکدام تاریخش
    جدیدتر بود. بعد کلاس‌های مجاز (هم‌سطح، هم‌جنسیت یا مختلط، با جای خالی واقعی) را به همراه
    شهریه‌ی پیشنهادی/تخفیف قبلی/موجودی کیف‌پول برمی‌گرداند. اگر سطح پیشنهادی منقضی یا
    پایانیِ گروه سنی‌اش باشد، هشدار مربوطه هم برمی‌گردد.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        student_id = request.query_params.get('student_id')
        manual_level = request.query_params.get('level', '').strip()
        if not student_id:
            return Response({'error': 'student_id الزامی است'}, status=status.HTTP_400_BAD_REQUEST)

        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            student = User.objects.get(pk=student_id, role='student')
        except User.DoesNotExist:
            return Response({'error': 'دانش‌آموز پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        info = _compute_level_suggestion(student)

        # خواسته‌ی ۲: اگه سطح پیشنهادی درست نبود، مدیر می‌تونه دستی سطح رو بزنه — کلاس‌های
        # همون سطح (در همه‌ی ساعت‌ها، هم‌جنسیت) دوباره لیست می‌شن، بدون چک انقضا/سطح‌پایانی
        has_current_level = bool(info['level'])
        current_level = info['level']
        term_id = request.query_params.get('term_id') or None
        # سطح فعلی فرد → پیشنهاد اصلی «سطح بعدی»؛ بدون سطح فعلی → پیشنهاد اصلی همان سطحی که مدیر انتخاب کرده
        plan_level = manual_level or current_level
        as_target = bool(manual_level) and not has_current_level
        suggested = _suggested_classes(plan_level, student.gender, term_id, as_target=as_target) if plan_level else []
        info['eligible'] = [slot for slot, _rel, _key in suggested]
        if manual_level:
            info['level'] = manual_level
            info['age_group'] = infer_age_group_from_level(manual_level)
            setting = TuitionSetting.objects.filter(level=manual_level, age_group=info['age_group']).first()
            info['base_tuition'] = setting.amount if setting else None
            info['needs_retest'] = False
            info['retest_reason'] = ''
            info['source'] = 'manual'

        relations = {slot.id: rel for slot, rel, _key in suggested}
        eligible_payload = ClassSlotSerializer(info['eligible'], many=True).data
        eligible_payload = [{**item, 'suggestion': relations.get(item['id'], 'higher')} for item in eligible_payload]

        return Response({
            'student_id': student.id,
            'student_name': f"{student.first_name} {student.last_name}",
            'student_gender': student.gender,
            'suggested_level': info['level'],
            'age_group': info['age_group'],
            'age_group_display': dict(LevelTest.AgeGroup.choices).get(info['age_group'], ''),
            'source': info['source'],
            'source_date_jalali': _jalali(info['source_date']) if info.get('source_date') else None,
            'days_since_source': info['days_since_source'],
            'needs_retest': info['needs_retest'],
            'retest_reason': info['retest_reason'],
            'renewal_status': info['renewal_status'],
            'eligible_classes': eligible_payload,
            'level_role': 'target' if as_target else 'current',
            'current_level': current_level,
            'primary_levels': sorted({item['assigned_level'] for item in eligible_payload if item['suggestion'] == 'primary'}),
            'base_tuition': info['base_tuition'],
            'wallet_balance': student.wallet_balance,
            'previous_discount_percent': info['discount_percent'],
            'is_new_entrant': info['is_new_entrant'],
            'needs_editing': student.needs_editing,
        })


class MyDirectEnrollSuggestionsView(APIView):
    """
    GET: نسخه‌ی خودِ دانش‌آموز از DirectEnrollSuggestionsView — برای بخش «ثبت‌نام دوره
    ترمیک» توی اپ. هیچ student_id نمی‌گیرد؛ همیشه خودِ کاربر لاگین‌کرده است. بدون امکان
    وارد کردن دستی سطح (فقط ادمین این اجازه را دارد).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = request.user
        if student.role != 'student':
            return Response({'error': 'این بخش فقط برای دانش‌آموزان است'}, status=status.HTTP_403_FORBIDDEN)

        info = _compute_level_suggestion(student)
        base_tuition = info['base_tuition']
        discount_percent = info['discount_percent']
        final_tuition = round(base_tuition * (100 - discount_percent) / 100) if base_tuition is not None else None

        return Response({
            'suggested_level': info['level'],
            'age_group': info['age_group'],
            'age_group_display': dict(LevelTest.AgeGroup.choices).get(info['age_group'], ''),
            'source': info['source'],
            'source_date_jalali': _jalali(info['source_date']) if info.get('source_date') else None,
            'days_since_source': info['days_since_source'],
            'needs_retest': info['needs_retest'],
            'retest_reason': info['retest_reason'],
            'renewal_status': info['renewal_status'],
            'eligible_classes': ClassSlotSerializer(info['eligible'], many=True).data,
            'base_tuition': base_tuition,
            'discount_percent': discount_percent,
            'final_tuition': final_tuition,
            'wallet_balance': student.wallet_balance,
            'is_new_entrant': info['is_new_entrant'],
        })


class SelfEnrollView(APIView):
    """
    POST: خودِ دانش‌آموز از طریق اپ (بخش «ثبت‌نام دوره ترمیک») در یکی از کلاس‌های مجازِ
    پیشنهادی ثبت‌نام می‌کند. فقط دو روش پرداخت مجاز است: کارت‌به‌کارت (با آپلود اجباری
    تصویر رسید) یا درگاه پرداخت آنلاین (فعلاً غیرفعال تا اتصال واقعی درگاه انجام شود).
    مبلغ شهریه و درصد تخفیف را خودِ سرور محاسبه می‌کند — دانش‌آموز نمی‌تواند این‌ها را
    دستکاری کند. ثبت‌نامِ کارت‌به‌کارت تا بررسی رسید توسط مدیر «تاییدنشده» می‌ماند.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @transaction.atomic
    def post(self, request, pk):
        from django.contrib.auth import get_user_model
        student = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        if student.role != 'student':
            return Response({'error': 'این بخش فقط برای دانش‌آموزان است'}, status=status.HTTP_403_FORBIDDEN)
        try:
            slot = ClassSlot.objects.get(pk=pk)
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        payment_method = request.data.get('payment_method')
        if payment_method not in (ClassSlotEnrollment.PaymentMethod.CARD_TO_CARD, ClassSlotEnrollment.PaymentMethod.GATEWAY):
            return Response({'error': 'روش پرداخت نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        if payment_method == ClassSlotEnrollment.PaymentMethod.GATEWAY:
            return Response({'error': 'پرداخت از طریق درگاه فعلاً راه‌اندازی نشده — لطفاً کارت‌به‌کارت را انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)

        receipt = request.FILES.get('receipt')
        if not receipt:
            return Response({'error': 'تصویر رسید کارت‌به‌کارت الزامی است'}, status=status.HTTP_400_BAD_REQUEST)

        prior_enrollments = list(_same_term_enrollments(slot, [student.id]).filter(student=student))
        carryover_to_confirm = (
            prior_enrollments[0]
            if len(prior_enrollments) == 1
            and prior_enrollments[0].is_carryover
            and not prior_enrollments[0].carryover_confirmed
            and prior_enrollments[0].payment_verified
            else None
        )
        if prior_enrollments and not carryover_to_confirm:
            class_labels = '؛ '.join(_enrollment_class_label(item.class_slot) for item in prior_enrollments)
            return Response({
                'error': f'خطای ثبت‌نام تکراری: شما قبلاً در همین ترم در {class_labels} ثبت‌نام کرده‌اید — برای جابه‌جایی با مدرسه تماس بگیرید'
            }, status=status.HTTP_400_BAD_REQUEST)

        # اگه سطح دانش‌آموز نیاز به تعیین‌سطح مجدد داره (منقضی یا آخرین سطح گروه سنی‌اش)،
        # اجازه‌ی ثبت‌نام خودکار نمی‌دیم — باید یا تعیین‌سطح بده یا مدیر آموزش تاییدش کنه
        info = _compute_level_suggestion(student)
        if info['needs_retest'] and info['level'] == slot.assigned_level:
            if info['retest_reason'] == 'max_level_reached':
                return Response({'error': 'برای ادامه به این سطح، باید ابتدا تعیین‌سطح جدید انجام دهید'}, status=status.HTTP_400_BAD_REQUEST)
            return Response({'error': 'اعتبار سطح شما (بیش از ۶۰ روز) منقضی شده — باید تعیین‌سطح مجدد بدهید یا منتظر تایید مدیر آموزش بمانید'}, status=status.HTTP_400_BAD_REQUEST)

        age_group = infer_age_group_from_level(slot.assigned_level)
        setting = TuitionSetting.objects.filter(level=slot.assigned_level, age_group=age_group).first() if slot.assigned_level else None
        base_tuition = setting.amount if setting else 0
        existing_discount = DiscountedPerson.objects.filter(student=student).order_by('-updated_at').first()
        discount_percent = existing_discount.discount_percent if existing_discount else 0
        tuition_amount = round(base_tuition * (100 - discount_percent) / 100)

        if carryover_to_confirm:
            enrollment = carryover_to_confirm
            enrollment.class_slot = slot
            enrollment.payment_method = payment_method
            enrollment.tuition_amount = tuition_amount
            enrollment.discount_percent = discount_percent
            enrollment.receipt_image = receipt
            enrollment.self_enrolled = True
            enrollment.payment_verified = False
            enrollment.carryover_confirmed = False
            enrollment.save(update_fields=[
                'class_slot', 'payment_method', 'tuition_amount', 'discount_percent',
                'receipt_image', 'self_enrolled', 'payment_verified', 'carryover_confirmed',
            ])
        else:
            enrollment = ClassSlotEnrollment.objects.create(
                class_slot=slot, student=student,
                payment_method=payment_method, tuition_amount=tuition_amount, discount_percent=discount_percent,
                receipt_image=receipt, self_enrolled=True, payment_verified=False,
            )

        return Response({
            'message': 'ثبت‌نام شما ثبت شد — بعد از بررسی رسید توسط مدیریت نهایی می‌شود',
            'enrollment': ClassSlotEnrollmentSerializer(enrollment).data,
        }, status=status.HTTP_200_OK if carryover_to_confirm else status.HTTP_201_CREATED)


class PendingSelfEnrollmentsView(generics.ListAPIView):
    """
    GET: لیست *همه‌ی* ثبت‌نام‌هایی که خودِ دانش‌آموز از اپ انجام داده و هنوز رسیدش تایید نشده —
    از همه‌ی کلاس‌ها، یک‌جا. مبنای پنجره‌ی هشدار وسط صفحه‌ی مدیریت کلاس‌ها (خواسته‌ی ۱).
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ClassSlotEnrollmentSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'class-management'):
            return ClassSlotEnrollment.objects.none()
        return ClassSlotEnrollment.objects.filter(self_enrolled=True, payment_verified=False).select_related('student', 'class_slot').order_by('created_at')


class RejectPendingEnrollmentView(APIView):
    """POST: مدیر رسید کارت‌به‌کارتِ یک ثبت‌نامِ در-انتظار را نامعتبر تشخیص می‌دهد و ثبت‌نام حذف می‌شود"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            enrollment = ClassSlotEnrollment.objects.get(class_slot_id=pk, student_id=student_id, self_enrolled=True, payment_verified=False)
        except ClassSlotEnrollment.DoesNotExist:
            return Response({'error': 'ثبت‌نام در انتظاری پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        enrollment.delete()
        return Response({'message': 'ثبت‌نام رد شد و حذف گردید'})


class VerifyEnrollmentPaymentView(APIView):
    """POST: مدیر بعد از بررسی تصویر رسید کارت‌به‌کارتِ ثبت‌نامِ خودِ دانش‌آموز، پرداخت را تایید می‌کند"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        target_slot_id = request.data.get('target_class_slot_id')
        try:
            with transaction.atomic():
                enrollment = ClassSlotEnrollment.objects.select_for_update().select_related('class_slot', 'student').get(
                    class_slot_id=pk, student_id=student_id,
                )
                original_slot_id = enrollment.class_slot_id
                target_slot = enrollment.class_slot
                if target_slot_id:
                    try:
                        target_slot = ClassSlot.objects.get(pk=target_slot_id)
                    except ClassSlot.DoesNotExist:
                        return Response({'error': 'کلاس مقصد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
                    if target_slot.term_id != enrollment.class_slot.term_id:
                        return Response({'error': 'کلاس مقصد باید در همان ترم ثبت‌نام باشد'}, status=status.HTTP_400_BAD_REQUEST)
                    if _normalize_level(target_slot.assigned_level) != _normalize_level(enrollment.class_slot.assigned_level):
                        return Response({'error': 'کلاس مقصد باید هم‌سطح کلاس ثبت‌نام اولیه باشد'}, status=status.HTTP_400_BAD_REQUEST)
                    student_gender = enrollment.student.gender
                    if target_slot.gender != ClassSlot.Gender.MIXED and student_gender and (
                        (target_slot.gender == ClassSlot.Gender.GIRLS and student_gender != 'female') or
                        (target_slot.gender == ClassSlot.Gender.BOYS and student_gender != 'male')
                    ):
                        return Response({'error': 'جنسیت دانش‌آموز با کلاس مقصد همخوانی ندارد'}, status=status.HTTP_400_BAD_REQUEST)
                    duplicate = ClassSlotEnrollment.objects.filter(
                        class_slot__term_id=target_slot.term_id, student_id=student_id,
                    ).exclude(pk=enrollment.pk).select_related('class_slot').first()
                    if duplicate:
                        return Response({
                            'error': f'این دانش‌آموز در همین ترم در کلاس {duplicate.class_slot.number} نیز ثبت‌نام دارد؛ از مسیر انتقال کلاس استفاده کنید'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    enrollment.class_slot = target_slot
                enrollment.payment_verified = True
                update_fields = ['payment_verified']
                if enrollment.class_slot_id != original_slot_id:
                    update_fields.append('class_slot')
                if enrollment.is_carryover:
                    enrollment.carryover_confirmed = True
                    update_fields.append('carryover_confirmed')
                enrollment.save(update_fields=update_fields)
        except ClassSlotEnrollment.DoesNotExist:
            return Response({'error': 'ثبت‌نام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'message': 'پرداخت تایید شد', 'enrollment': ClassSlotEnrollmentSerializer(enrollment).data})


class LevelRenewalApprovalListView(generics.ListCreateAPIView):
    """
    GET: لیست درخواست‌های تایید تمدید سطح (پیش‌فرض همه؛ با ?status=pending فقط در انتظار)
    POST: مدیر/آفیس یک درخواست تازه برای یک دانش‌آموز+سطح ثبت می‌کند (وقتی هشدار انقضای
    ۶۰روزه دیده و می‌خواهد از مدیر آموزش تاییدیه بگیرد، به‌جای تعیین‌سطح مجدد)
    """
    permission_classes = [IsAuthenticated]
    serializer_class = LevelRenewalApprovalSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'class-management'):
            return LevelRenewalApproval.objects.none()
        qs = LevelRenewalApproval.objects.select_related('student', 'requested_by', 'reviewed_by').all()
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def create(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        student_id = request.data.get('student')
        level = request.data.get('level')
        if not student_id or not level:
            return Response({'error': 'دانش‌آموز و سطح الزامی است'}, status=status.HTTP_400_BAD_REQUEST)
        existing = LevelRenewalApproval.objects.filter(student_id=student_id, level=level, status=LevelRenewalApproval.Status.PENDING).first()
        if existing:
            return Response(LevelRenewalApprovalSerializer(existing).data, status=status.HTTP_200_OK)
        approval = LevelRenewalApproval.objects.create(
            student_id=student_id, level=level, requested_by=request.user, note=request.data.get('note', ''),
        )
        return Response(LevelRenewalApprovalSerializer(approval).data, status=status.HTTP_201_CREATED)


class LevelRenewalApprovalDecideView(APIView):
    """POST: مدیر آموزش درخواست تمدید سطح را تایید یا رد می‌کند. بدنه: {decision: 'approve' | 'reject'}"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            approval = LevelRenewalApproval.objects.get(pk=pk)
        except LevelRenewalApproval.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        decision = request.data.get('decision')
        if decision not in ('approve', 'reject'):
            return Response({'error': 'decision باید approve یا reject باشد'}, status=status.HTTP_400_BAD_REQUEST)
        approval.status = LevelRenewalApproval.Status.APPROVED if decision == 'approve' else LevelRenewalApproval.Status.REJECTED
        approval.reviewed_by = request.user
        approval.reviewed_at = timezone.now()
        approval.save()
        return Response(LevelRenewalApprovalSerializer(approval).data)


class TuitionSuggestionView(APIView):
    """
    GET: بعد از انتخاب دانش‌آموز در فرم ثبت‌نام — شهریه‌ی پیشنهادی (بر اساس سطح این کلاس و گروه
    سنیِ آخرین تعیین‌سطحِ تکمیل‌شده‌ی دانش‌آموز)، موجودی فعلی کیف پولش، و درصد تخفیف قبلی‌اش
    (اگر قبلاً در «افراد دارای تخفیف» ثبت شده) را برمی‌گرداند.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        student_id = request.query_params.get('student_id')
        if not student_id:
            return Response({'error': 'student_id الزامی است'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            slot = ClassSlot.objects.get(pk=pk)
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            student = User.objects.get(pk=student_id, role='student')
        except User.DoesNotExist:
            return Response({'error': 'دانش‌آموز پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        latest_test = LevelTest.objects.filter(
            student=student, status=LevelTest.Status.COMPLETED
        ).order_by('-updated_at').first()
        level = slot.assigned_level or (latest_test.level if latest_test else '')
        # گروه سنی دیگر از روی آزمون تعیین‌سطح حدس زده نمی‌شود — چون هر سطح خودش
        # قطعاً متعلق به یک گروه سنی مشخص است (رفع باگ «شهریه‌ای تعریف نشده»)
        age_group = infer_age_group_from_level(level)

        base_tuition = None
        if level and age_group:
            setting = TuitionSetting.objects.filter(level=level, age_group=age_group).first()
            if setting:
                base_tuition = setting.amount

        existing_discount = DiscountedPerson.objects.filter(student=student).order_by('-updated_at').first()

        return Response({
            'base_tuition': base_tuition,
            'level': level,
            'age_group': age_group,
            'age_group_display': dict(LevelTest.AgeGroup.choices).get(age_group, ''),
            'wallet_balance': student.wallet_balance,
            'previous_discount_percent': existing_discount.discount_percent if existing_discount else 0,
        })


class TuitionSettingListView(generics.ListCreateAPIView):
    """لیست/تعریف شهریه‌ی مصوب هر سطح × گروه سنی — بخش جداگانه‌ی «تعریف شهریه»"""
    permission_classes = [IsAuthenticated]
    serializer_class = TuitionSettingSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'class-management'):
            return TuitionSetting.objects.none()
        return TuitionSetting.objects.all()

    def create(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        level = request.data.get('level')
        # گروه سنی معمولاً از روی خودِ سطح محاسبه می‌شود؛ ولی برای سطوح سفارشی/غیراستاندارد
        # (خواسته‌ی ۹) که این تشخیص خودکار جواب نمی‌ده، گروه سنیِ دستیِ ارسالی از کلاینت رو قبول می‌کنیم
        age_group = infer_age_group_from_level(level) or request.data.get('age_group', '')
        if not age_group:
            return Response({'error': f'گروه سنی سطح «{level}» قابل تشخیص نیست — برای سطح سفارشی، گروه سنی را دستی انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
        payload = {**request.data, 'age_group': age_group}
        existing = TuitionSetting.objects.filter(level=level, age_group=age_group).first()
        if existing:
            serializer = self.get_serializer(existing, data=payload, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TuitionSettingDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TuitionSettingSerializer
    queryset = TuitionSetting.objects.all()

    def update(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class DiscountedPersonListView(generics.ListAPIView):
    """GET: لیست «افراد دارای تخفیف» — خودکار از روی ثبت‌نام‌های دارای تخفیف (کلاس ترمیک یا دوره‌ی آنلاین) ساخته می‌شود"""
    permission_classes = [IsAuthenticated]
    serializer_class = DiscountedPersonSerializer

    def get_queryset(self):
        if not can_view_menu(self.request.user, 'discounts'):
            return DiscountedPerson.objects.none()
        return DiscountedPerson.objects.select_related('student', 'class_slot', 'online_course').all()


class DiscountedPersonDetailView(generics.RetrieveUpdateDestroyAPIView):
    """PATCH/DELETE — برای ویرایش درصد تخفیفِ رکوردهای خودکارساخته‌شده از صفحه‌ی «افراد دارای تخفیف»"""
    permission_classes = [IsAuthenticated]
    serializer_class = DiscountedPersonSerializer
    queryset = DiscountedPerson.objects.all()

    def update(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'discounts'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'discounts'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class RefundEnrollmentView(APIView):
    """
    POST: دکمه‌ی «استرداد» — شهریه‌ی پرداختی به شخص برگردانده می‌شود؛ تاریخ/ساعت خودکار ثبت
    می‌شود، شماره کارت و نام گیرنده از فرم گرفته می‌شود، و دانش‌آموز از لیست کلاس حذف می‌شود.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            slot = ClassSlot.objects.get(pk=pk)
            enrollment = ClassSlotEnrollment.objects.get(class_slot=slot, student_id=student_id)
        except (ClassSlot.DoesNotExist, ClassSlotEnrollment.DoesNotExist):
            return Response({'error': 'ثبت‌نام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        serializer = RefundEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        refund = EnrollmentRefund.objects.create(
            student_id=student_id, class_slot=slot, amount=enrollment.tuition_amount,
            card_number=data['card_number'], receiver_name=data['receiver_name'],
            refunded_by=request.user,
        )
        enrollment.delete()

        return Response({
            'message': 'شهریه مسترد شد و دانش‌آموز از کلاس حذف شد',
            'refund': {
                'id': refund.id, 'amount': refund.amount, 'card_number': refund.card_number,
                'receiver_name': refund.receiver_name, 'created_at_jalali': refund.created_at_jalali,
            },
            'slot': ClassSlotSerializer(slot).data,
        })


class TransferEnrollmentOptionsView(APIView):
    """GET: تمام کلاس‌های هم‌سطح و سازگار با جنسیت دانش‌آموز، حتی در صورت تکمیل ظرفیت."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            slot = ClassSlot.objects.get(pk=pk)
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        enrollment = ClassSlotEnrollment.objects.select_related('student').filter(class_slot=slot, student_id=student_id).first()
        if not enrollment:
            return Response({'error': 'این دانش‌آموز در کلاس مبدأ ثبت‌نام نیست'}, status=status.HTTP_404_NOT_FOUND)
        student_gender = enrollment.student.gender or _student_gender_from_class(slot)
        target_gender = {'female': ClassSlot.Gender.GIRLS, 'male': ClassSlot.Gender.BOYS}.get(student_gender)
        candidates = ClassSlot.objects.exclude(pk=slot.pk).filter(term=slot.term, assigned_level=slot.assigned_level)
        if target_gender:
            candidates = candidates.filter(gender__in=[target_gender, ClassSlot.Gender.MIXED])
        else:
            # وقتی جنسیت فرد قابل تعیین نیست، فقط کلاس مختلط گزینهٔ امن محسوب می‌شود.
            candidates = candidates.filter(gender=ClassSlot.Gender.MIXED)
        candidates = candidates.order_by('day_type', 'time_slot', 'number')

        return Response([{
            'id': c.id, 'number': c.number, 'day_type_display': c.day_type_display,
            'time_slot': c.time_slot, 'teacher_name': c.teacher_name, 'seats_left': c.real_seats_left,
            'real_seats_left': c.real_seats_left, 'capacity': c.capacity,
            'real_enrolled_count': c.real_enrolled_count, 'gender': c.gender,
            'gender_display': c.get_gender_display(), 'assigned_level': c.assigned_level,
            'tuition_amount': class_tariff_amount(c),
        } for c in candidates])


class TransferEnrollmentView(APIView):
    """POST: دکمه‌ی «انتقال کلاس» — دانش‌آموز از کلاس فعلی حذف و به کلاس مقصدِ انتخاب‌شده منتقل می‌شود"""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            source = ClassSlot.objects.select_for_update().get(pk=pk)
            enrollment = ClassSlotEnrollment.objects.select_for_update().get(class_slot=source, student_id=student_id)
        except (ClassSlot.DoesNotExist, ClassSlotEnrollment.DoesNotExist):
            return Response({'error': 'ثبت‌نام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            student = User.objects.select_for_update().get(pk=student_id, role='student')
        except User.DoesNotExist:
            return Response({'error': 'دانش‌آموز پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        serializer = TransferEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            target = ClassSlot.objects.select_for_update().get(pk=serializer.validated_data['target_slot_id'])
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس مقصد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        if target.pk == source.pk:
            return Response({'error': 'کلاس مقصد نمی‌تواند همان کلاس فعلی باشد'}, status=status.HTTP_400_BAD_REQUEST)
        if target.term_id != source.term_id:
            return Response({'error': 'کلاس مقصد باید در همان ترم باشد'}, status=status.HTTP_400_BAD_REQUEST)
        change_level = str(request.data.get('change_level', '')).lower() in ('1', 'true', 'yes')
        if not change_level and target.assigned_level != source.assigned_level:
            return Response({'error': 'برای انتقال معمولی، کلاس مقصد باید هم‌سطح باشد'}, status=status.HTTP_400_BAD_REQUEST)
        student_gender = student.gender or _student_gender_from_class(source)
        if target.gender != ClassSlot.Gender.MIXED:
            expected_gender = 'female' if target.gender == ClassSlot.Gender.GIRLS else 'male'
            if student_gender != expected_gender:
                return Response({'error': 'جنسیت دانش‌آموز با کلاس مقصد سازگار نیست؛ فقط کلاس هم‌جنس یا مختلط قابل انتخاب است'}, status=status.HTTP_400_BAD_REQUEST)
        if target.real_seats_left <= 0:
            return Response({'error': 'کلاس مقصد ظرفیت خالی ندارد'}, status=status.HTTP_400_BAD_REQUEST)
        existing_in_target_term = list(_same_term_enrollments(target, [student_id]).exclude(pk=enrollment.pk))
        if existing_in_target_term:
            class_labels = '؛ '.join(_enrollment_class_label(item.class_slot) for item in existing_in_target_term)
            return Response({
                'error': f'خطای ثبت‌نام تکراری: این کد ملی قبلاً در ترم مقصد در {class_labels} ثبت‌نام شده است'
            }, status=status.HTTP_400_BAD_REQUEST)

        ClassSlotEnrollment.objects.create(
            class_slot=target, student_id=student_id,
            payment_method=enrollment.payment_method, tuition_amount=enrollment.tuition_amount,
            discount_percent=enrollment.discount_percent, pos_reference_code=enrollment.pos_reference_code,
            is_carryover=enrollment.is_carryover,
            carryover_confirmed=(
                enrollment.carryover_confirmed
                or (enrollment.is_carryover and source.term_id == target.term_id)
            ),
            carried_from_term=enrollment.carried_from_term,
        )
        tuition_note = tuition_difference(enrollment, target)
        enrollment.delete()
        if change_level and target.assigned_level:
            _student = User.objects.filter(pk=student_id).first()
            if _student:
                _student.language_level = target.assigned_level
                _student.save(update_fields=['language_level'])
                # سطح اصلاح‌شده باید در فهرست پیگیری/بدهکاران هم مبنا باشد؛ در غیر این صورت
                # رکورد بدهکاریِ قبلی هنوز سطح اشتباه کلاس را نمایش می‌داد.
                from leads.models import Debtor
                debtor_identity = Q(student_id=student_id)
                if _student.phone:
                    debtor_identity |= Q(phone=_student.phone, first_name=_student.first_name, last_name=_student.last_name)
                if _student.national_code:
                    debtor_identity |= Q(first_name=_student.first_name, last_name=_student.last_name, student__national_code=_student.national_code)
                Debtor.objects.filter(debtor_identity).exclude(
                    status=Debtor.Status.SETTLED,
                ).update(class_level=target.assigned_level)
        if not target.assigned_level:
            target.assigned_level = source.assigned_level
            target.save()

        return Response({
            'message': f'دانش‌آموز به کلاس {target.number} منتقل شد' + (f'\n{tuition_note["message"]}' if tuition_note['message'] else ''),
            'tuition_difference': tuition_note,
            'source': ClassSlotSerializer(source).data,
            'target': ClassSlotSerializer(target).data,
        })


class CreditToWalletView(APIView):
    """
    POST: دکمه‌ی «انتقال به کیف پول» — دانش‌آموز از کلاس حذف می‌شود و مبلغ شهریه‌ی پرداختی‌اش
    به کیف پولش واریز می‌شود تا بعداً برای ثبت‌نام دیگری استفاده کند.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            slot = ClassSlot.objects.get(pk=pk)
            enrollment = ClassSlotEnrollment.objects.get(class_slot=slot, student_id=student_id)
        except (ClassSlot.DoesNotExist, ClassSlotEnrollment.DoesNotExist):
            return Response({'error': 'ثبت‌نام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        amount = enrollment.tuition_amount
        student = enrollment.student
        enrollment.delete()

        student.wallet_balance += amount
        student.save(update_fields=['wallet_balance'])
        WalletTransaction.objects.create(
            student=student, kind=WalletTransaction.Kind.CREDIT, amount=amount,
            reason=f'انتقال از کلاس {slot.number} به کیف پول', class_slot=slot,
        )

        return Response({
            'message': f'{amount:,} تومان به کیف پول دانش‌آموز واریز شد',
            'wallet_balance': student.wallet_balance,
            'slot': ClassSlotSerializer(slot).data,
        })


class SplitClassView(APIView):
    """
    POST: «تفکیک کلاس» — گروهی از دانش‌آموزهای واقعاً ثبت‌نام‌شده‌ی این کلاس (چه مشخص‌شده با
    نام، چه تصادفی) به یک کلاس هم‌سطح/هم‌جنسیت تازه منتقل می‌شوند. اول دنبال یک کلاس هم‌شرایط
    که هنوز هیچ ثبت‌نام واقعی ندارد می‌گردد؛ اگر پیدا نشد، خودش یک کلاس جدید (با اولین شماره‌ی
    آزاد) می‌سازد. بدنه: {student_ids: [..]} یا {random_count: N}
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            source = ClassSlot.objects.select_for_update().get(pk=pk)
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        serializer = SplitClassSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        enrollments = list(ClassSlotEnrollment.objects.select_for_update().filter(class_slot=source).select_related('student'))
        if payload.get('student_ids'):
            wanted = set(payload['student_ids'])
            to_move = [e for e in enrollments if e.student_id in wanted]
            if len(to_move) != len(wanted):
                return Response({'error': 'بعضی از دانش‌آموزهای انتخاب‌شده توی این کلاس ثبت‌نام نیستند'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            count = payload['random_count']
            if count > len(enrollments):
                return Response({'error': f'تعداد وارد شده ({count}) از تعداد واقعیِ افراد این کلاس ({len(enrollments)}) بیشتر است'}, status=status.HTTP_400_BAD_REQUEST)
            to_move = random.sample(enrollments, count)

        if not to_move:
            return Response({'error': 'هیچ دانش‌آموزی برای تفکیک انتخاب نشد'}, status=status.HTTP_400_BAD_REQUEST)

        student_ids = sorted({enrollment.student_id for enrollment in to_move})
        from django.contrib.auth import get_user_model
        list(get_user_model().objects.select_for_update().filter(pk__in=student_ids).order_by('id').values_list('id', flat=True))
        existing_elsewhere = list(_same_term_enrollments(source, student_ids).exclude(class_slot=source))
        if existing_elsewhere:
            enrollments_by_student = {}
            for enrollment in existing_elsewhere:
                enrollments_by_student.setdefault(enrollment.student_id, []).append(enrollment.class_slot)
            duplicate_details = []
            for enrollment in to_move:
                prior_slots = enrollments_by_student.get(enrollment.student_id, [])
                if prior_slots:
                    classes = '؛ '.join(_enrollment_class_label(slot) for slot in prior_slots)
                    duplicate_details.append(f'{enrollment.student.get_full_name()}: {classes}')
            return Response({
                'error': 'خطای ثبت‌نام تکراری: تفکیک انجام نشد؛ این افراد در کلاس دیگری از همین ترم ثبت‌نام دارند: ' + ' | '.join(duplicate_details)
            }, status=status.HTTP_400_BAD_REQUEST)

        # اول دنبال یک کلاس هم‌سطح/هم‌جنسیت/هم‌روز که هنوز هیچ ثبت‌نام واقعی ندارد بگرد
        target = (
            ClassSlot.objects.exclude(pk=source.pk)
            .filter(assigned_level=source.assigned_level, gender=source.gender, day_type=source.day_type, term_id=source.term_id)
            .annotate(real_count=Count('enrollments'))
            .filter(real_count=0)
            .order_by('number')
            .first()
        )
        if not target:
            next_number = (ClassSlot.objects.aggregate(m=Max('number'))['m'] or 0) + 1
            target = ClassSlot.objects.create(
                number=next_number, term=source.term, day_type=source.day_type, time_slot=source.time_slot,
                gender=source.gender, assigned_level=source.assigned_level,
                capacity=source.capacity, teacher_name='',
                title=f'تفکیک‌شده از کلاس {source.number}',
            )

        moved_names = []
        for e in to_move:
            e.class_slot = target
            e.save(update_fields=['class_slot'])
            moved_names.append(f"{e.student.first_name} {e.student.last_name}")

        return Response({
            'message': f'{len(to_move)} نفر به کلاس {target.number} منتقل شدند',
            'moved_count': len(to_move),
            'moved_names': moved_names,
            'source': ClassSlotSerializer(source).data,
            'target': ClassSlotSerializer(target).data,
        })


class TeacherEducationHistoryView(APIView):
    """
    GET /api/class-management/teachers/<teacher_id>/education-history/?term=<term_id>
    سوابق آموزشیِ کاملِ یک استاد — برای بخش «سوابق آموزشی» در «مدیریت اساتید»:
    ۱) سوابق کلاس‌های ترمیک (بر اساس ترم انتخابی؛ اگر term داده نشود، جدیدترین ترم پیش‌فرض است)
       — چون ClassSlot رابطه‌ی مستقیم (FK) به استاد ندارد، تطبیق روی نام کامل (teacher_name) انجام می‌شود
    ۲) سوابق کلاس‌های خصوصی/جبرانی/سایر (فاز ۱ — مدل ClassRequest در accounts)
    ۳) سوابق کلاس‌های ورکشاپ/خصوصی‌گروهی (فاز ۲ — اپ group_classes)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, teacher_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            teacher = User.objects.get(pk=teacher_id, role__in=User.TEACHER_LIKE_ROLES)
        except User.DoesNotExist:
            return Response({'error': 'استاد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        teacher_full_name = f"{teacher.first_name} {teacher.last_name}".strip()

        # ۱) ترم‌ها برای انتخابگر + کلاس‌های ترمیک استاد در ترم انتخابی (یا جدیدترین ترم)
        terms = Term.objects.all().order_by('-year', '-term_number')
        term_id = request.query_params.get('term')
        selected_term = terms.filter(pk=term_id).first() if term_id else None
        if not selected_term:
            selected_term = terms.first()

        term_classes = []
        if selected_term:
            term_slots = ClassSlot.objects.filter(
                term=selected_term, teacher_name__iexact=teacher_full_name
            ).order_by('day_type', 'time_slot', 'number')
            for s in term_slots:
                term_classes.append({
                    'id': s.id, 'number': s.number, 'day_type_display': s.day_type_display,
                    'time_slot': s.time_slot, 'assigned_level': s.assigned_level,
                    'gender_display': s.get_gender_display(),
                    'is_online': s.is_online, 'meeting_link': s.meeting_link,
                    'real_enrolled_count': s.real_enrolled_count, 'capacity': s.capacity,
                })

        # ۲) کلاس‌های خصوصی/جبرانی/سایر (فاز ۱)
        private_history = []
        try:
            from accounts.models import ClassRequest
            private_classes = ClassRequest.objects.filter(
                teacher=teacher, status=ClassRequest.Status.COMPLETED
            ).select_related('student').order_by('-completed_at')
            for c in private_classes:
                private_history.append({
                    'id': c.id,
                    'class_type': c.get_class_type_display() if c.class_type != 'other' else (c.custom_class_type or 'سایر'),
                    'language_level': c.language_level,
                    'student_name': f"{c.student.first_name} {c.student.last_name}" if c.student else '—',
                    'session_count': c.session_count,
                    'completed_at_jalali': getattr(c, 'completed_at_jalali', None),
                    'total_price': c.total_price,
                    'teacher_share': c.teacher_share,
                })
        except Exception:
            pass  # اگه اپ classes در دسترس نبود، این بخش خالی برمی‌گرده نه اینکه کل صفحه خطا بده

        # ۳) کلاس‌های ورکشاپ/خصوصی‌گروهی (فاز ۲)
        group_history = []
        try:
            from group_classes.models import GroupSession, GroupSessionParticipant
            group_sessions = GroupSession.objects.filter(teacher=teacher).order_by('-id')
            for g in group_sessions:
                group_history.append({
                    'id': g.id,
                    'session_type': g.get_session_type_display(),
                    'title': g.title or g.language_level,
                    'language_level': g.language_level,
                    'status_display': g.get_status_display(),
                    'class_date_jalali': getattr(g, 'class_date_jalali', None),
                    'completed_at_jalali': getattr(g, 'completed_at_jalali', None),
                    'participant_count': GroupSessionParticipant.objects.filter(group_session=g).count(),
                })
        except Exception:
            pass

        # ۴) سایر دوره‌ها / کلاس‌های علمی (OnlineCourse مستقل)
        online_course_history = []
        courses = OnlineCourse.objects.filter(teacher_name__iexact=teacher_full_name).order_by('-created_at')
        for c in courses:
            online_course_history.append({
                'id': c.id, 'title': c.title, 'schedule_note': c.schedule_note,
                'session_date_jalali': c.session_date_jalali, 'session_time': c.session_time,
                'session_count': c.session_count, 'price': c.price, 'is_active': c.is_active,
                'created_at_jalali': c.created_at_jalali,
                'enrolled_count': c.enrolled_count,
            })

        return Response({
            'teacher_id': teacher.id, 'teacher_name': teacher_full_name,
            'terms': TermSerializer(terms, many=True).data,
            'selected_term': TermSerializer(selected_term).data if selected_term else None,
            'term_classes': term_classes,
            'private_classes': private_history,
            'group_classes': group_history,
            'online_courses': online_course_history,
        })


class TeacherTermClassesView(APIView):
    """
    GET /api/class-management/my-term-classes/
    برای اپ موبایل استاد — کلاس‌های ترمیکِ خودِ استاد در «ترم جاری» (بر اساس تاریخ امروز؛ اگر
    ترم جاری‌ای پیدا نشد، آخرین ترمِ تعریف‌شده به‌عنوان جایگزین استفاده می‌شود)، همراه با اسم
    دانش‌آموزهای هرکلاس، روز، ساعت، سطح و ظرفیت.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if request.user.role not in User.TEACHER_LIKE_ROLES:
            return Response({'error': 'این بخش فقط برای اساتید است'}, status=status.HTTP_403_FORBIDDEN)

        from leads.models import get_current_term
        term = get_current_term()
        if not term:
            return Response({'term': None, 'classes': []})

        teacher_full_name = request.user.get_full_name().strip()
        slots = ClassSlot.objects.filter(
            term=term, teacher_name__iexact=teacher_full_name
        ).order_by('day_type', 'time_slot', 'number')

        result = []
        today_str = today.isoformat()
        for s in slots:
            students = ClassSlotEnrollment.objects.filter(class_slot=s, payment_verified=True).select_related('student')
            today_attendance = {a.student_id: a for a in ClassAttendance.objects.filter(class_slot=s, date=today)}
            result.append({
                'id': s.id, 'number': s.number, 'day_type_display': s.day_type_display,
                'time_slot': s.time_slot, 'gender_display': s.get_gender_display(),
                'assigned_level': s.assigned_level, 'capacity': s.capacity,
                'is_online': s.is_online, 'meeting_link': s.meeting_link if s.is_online else '',
                'student_count': students.count(),
                'students': [f"{e.student.first_name} {e.student.last_name}".strip() for e in students],
                'roster': [{
                    'student_id': e.student.id,
                    'student_name': f"{e.student.first_name} {e.student.last_name}".strip(),
                    'today_attendance': (
                        {'is_present': today_attendance[e.student.id].is_present, 'date_jalali': today_attendance[e.student.id].date_jalali}
                        if e.student.id in today_attendance else None
                    ),
                } for e in students],
                'today_date': today_str,
            })

        return Response({'term': TermSerializer(term).data, 'classes': result})


# ==================== سایر دوره‌ها / کلاس‌های علمی (OnlineCourse) ====================
# دوره‌های آنلاین مستقل از سیستم ترم/کلاس فیزیکی — دانش‌آموز بدون محدودیت تعداد می‌خرد،
# استاد یکتا/بدون‌تداخل نیست (فقط هشدار)، و کد ملی محدودیت یک‌کلاس ندارد.

class OnlineCourseListView(generics.ListCreateAPIView):
    """GET/POST برای پنل ادمین — هم دکمه‌ی «کلاس‌های علمی» (تعریف سطوح) هم بخش «سایر دوره‌ها» از همینجا کار می‌کنند"""
    permission_classes = [IsAuthenticated]
    serializer_class = OnlineCourseSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'class-management'):
            return OnlineCourse.objects.none()
        return OnlineCourse.objects.all()

    def create(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        # هشدار (نه مسدودسازی) تداخل زمانی استاد با دوره‌های دیگرش
        warning = self._teacher_overlap_warning(request.data.get('teacher_name', ''), request.data.get('schedule_note', ''))
        response = super().create(request, *args, **kwargs)
        if warning:
            response.data['teacher_overlap_warning'] = warning
        return response

    def _teacher_overlap_warning(self, teacher_name, schedule_note, exclude_id=None):
        teacher_name = (teacher_name or '').strip()
        schedule_note = (schedule_note or '').strip()
        if not teacher_name or not schedule_note:
            return None
        qs = OnlineCourse.objects.filter(teacher_name__iexact=teacher_name, schedule_note__iexact=schedule_note, is_active=True)
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)
        conflict = qs.first()
        if conflict:
            return f'⚠ توجه: استاد «{teacher_name}» از قبل روی دوره‌ی «{conflict.title}» با همین زمان‌بندی («{schedule_note}») تعریف شده — این فقط هشدار است و مانع ثبت نمی‌شود'
        return None


class OnlineCourseDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE یک دوره — برای ویرایش، تخصیص استاد، تعریف تعداد جلسات/قیمت/لینک"""
    permission_classes = [IsAuthenticated]
    serializer_class = OnlineCourseSerializer
    queryset = OnlineCourse.objects.all()

    def update(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        obj = self.get_object()
        warning = OnlineCourseListView()._teacher_overlap_warning(
            request.data.get('teacher_name', obj.teacher_name),
            request.data.get('schedule_note', obj.schedule_note),
            exclude_id=obj.pk,
        )
        response = super().update(request, *args, **kwargs)
        if warning:
            response.data['teacher_overlap_warning'] = warning
        return response

    def destroy(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        obj = self.get_object()
        enrolled_count = obj.enrollments.count()
        if enrolled_count:
            return Response(
                {'error': f'این دوره {enrolled_count} دانش‌آموز ثبت‌نام‌شده دارد — تا زمانی که دانش‌آموز(ها) از دوره حذف یا مسترد نشوند، امکان حذف آن وجود ندارد'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


class OnlineCourseCatalogView(generics.ListAPIView):
    """
    GET — برای اپ دانش‌آموز، بخش «کلاس‌های آنلاین». همه‌ی دوره‌های فعال، بدون نیاز به سرچ یا
    شرط سطح/جنسیت، به‌صورت پیش‌فرض نمایش داده می‌شوند — دانش‌آموز بدون محدودیت تعداد می‌تواند
    از هرکدام خرید کند.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = OnlineCourseSerializer

    def get_queryset(self):
        if self.request.user.role != 'student':
            return OnlineCourse.objects.none()
        return OnlineCourse.objects.filter(is_active=True)


class OnlineCourseEnrollView(APIView):
    """POST: ثبت‌نام دستیِ مدیر برای یک دانش‌آموز در یک دوره — بدون محدودیت کد ملی/ترم"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            course = OnlineCourse.objects.get(pk=pk)
        except OnlineCourse.DoesNotExist:
            return Response({'error': 'دوره پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        serializer = OnlineCourseEnrollSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            if data.get('student_id'):
                student = User.objects.get(pk=data['student_id'], role='student')
            else:
                student = User.objects.get(national_code=data['national_code'], role='student')
        except User.DoesNotExist:
            return Response({'error': 'دانش‌آموز پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        # خواسته: خرید دوباره‌ی «همون» دوره برای یک نفر خطا بدهد؛ خرید دوره‌های دیگر آزاد است
        if OnlineCourseEnrollment.objects.filter(course=course, student=student).exists():
            return Response({'error': f'این دانش‌آموز از قبل در دوره‌ی «{course.title}» ثبت‌نام دارد'}, status=status.HTTP_400_BAD_REQUEST)

        price_paid = data['price_paid']
        discount_percent = data.get('discount_percent', 0)

        if data['payment_method'] == OnlineCourseEnrollment.PaymentMethod.WALLET:
            if student.wallet_balance < price_paid:
                return Response({'error': f'موجودی کیف پول این دانش‌آموز ({student.wallet_balance:,} تومان) کافی نیست'}, status=status.HTTP_400_BAD_REQUEST)

        enrollment = OnlineCourseEnrollment.objects.create(
            course=course, student=student, payment_method=data['payment_method'],
            price_paid=price_paid, discount_percent=discount_percent,
        )

        if data['payment_method'] == OnlineCourseEnrollment.PaymentMethod.WALLET:
            student.wallet_balance -= price_paid
            student.save(update_fields=['wallet_balance'])
            WalletTransaction.objects.create(
                student=student, kind=WalletTransaction.Kind.DEBIT, amount=price_paid,
                reason=f'پرداخت دوره «{course.title}»', online_course=course,
            )

        discount_record = None
        if discount_percent > 0:
            discount_record, _ = DiscountedPerson.objects.update_or_create(
                student=student,
                defaults={'discount_percent': discount_percent, 'online_course': course, 'approved_tuition': price_paid},
            )

        return Response({
            'enrollment': OnlineCourseEnrollmentSerializer(enrollment).data,
            'course': OnlineCourseSerializer(course).data,
            'discount_record': DiscountedPersonSerializer(discount_record).data if discount_record else None,
            'wallet_balance': student.wallet_balance,
        }, status=status.HTTP_201_CREATED)


class OnlineCourseSelfEnrollView(APIView):
    """POST: خودِ دانش‌آموز از اپ، بدون هیچ محدودیتی، هر تعداد دوره که بخواهد می‌خرد — کارت‌به‌کارت یا درگاه"""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        student = request.user
        if student.role != 'student':
            return Response({'error': 'این بخش فقط برای دانش‌آموزان است'}, status=status.HTTP_403_FORBIDDEN)
        try:
            course = OnlineCourse.objects.get(pk=pk, is_active=True)
        except OnlineCourse.DoesNotExist:
            return Response({'error': 'دوره پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        # خواسته: خرید دوباره‌ی «همون» دوره خطا بدهد؛ خرید دوره‌های دیگر هم‌زمان آزاد است
        if OnlineCourseEnrollment.objects.filter(course=course, student=student).exists():
            return Response({'error': f'شما از قبل در دوره‌ی «{course.title}» ثبت‌نام کرده‌اید'}, status=status.HTTP_400_BAD_REQUEST)

        payment_method = request.data.get('payment_method')
        if payment_method not in (OnlineCourseEnrollment.PaymentMethod.CARD_TO_CARD, OnlineCourseEnrollment.PaymentMethod.GATEWAY):
            return Response({'error': 'روش پرداخت نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        if payment_method == OnlineCourseEnrollment.PaymentMethod.GATEWAY:
            return Response({'error': 'پرداخت از طریق درگاه فعلاً راه‌اندازی نشده — لطفاً کارت‌به‌کارت را انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)

        receipt = request.FILES.get('receipt')
        if not receipt:
            return Response({'error': 'تصویر رسید کارت‌به‌کارت الزامی است'}, status=status.HTTP_400_BAD_REQUEST)

        existing_discount = DiscountedPerson.objects.filter(student=student).order_by('-updated_at').first()
        discount_percent = existing_discount.discount_percent if existing_discount else 0
        price_paid = round(course.price * (100 - discount_percent) / 100)

        enrollment = OnlineCourseEnrollment.objects.create(
            course=course, student=student, payment_method=payment_method,
            price_paid=price_paid, discount_percent=discount_percent,
            receipt_image=receipt, self_enrolled=True, payment_verified=False,
        )

        return Response({
            'message': 'ثبت‌نام شما ثبت شد — بعد از بررسی رسید توسط مدیریت نهایی می‌شود',
            'enrollment': OnlineCourseEnrollmentSerializer(enrollment).data,
        }, status=status.HTTP_201_CREATED)


class PendingOnlineCourseEnrollmentsView(generics.ListAPIView):
    """GET: لیست ثبت‌نام‌های در-انتظارِ دوره‌ها — طبق همون پروتکل قبلی، پیش‌فرض توی پنجره‌ی هشدار مدیریت کلاس‌ها می‌آید"""
    permission_classes = [IsAuthenticated]
    serializer_class = OnlineCourseEnrollmentSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'class-management'):
            return OnlineCourseEnrollment.objects.none()
        return OnlineCourseEnrollment.objects.filter(self_enrolled=True, payment_verified=False).select_related('student', 'course').order_by('created_at')


class VerifyOnlineCourseEnrollmentPaymentView(APIView):
    """POST: تایید رسید یک ثبت‌نام دوره"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            enrollment = OnlineCourseEnrollment.objects.get(course_id=pk, student_id=student_id)
        except OnlineCourseEnrollment.DoesNotExist:
            return Response({'error': 'ثبت‌نام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        enrollment.payment_verified = True
        enrollment.save(update_fields=['payment_verified'])
        return Response({'message': 'پرداخت تایید شد', 'enrollment': OnlineCourseEnrollmentSerializer(enrollment).data})


class RejectPendingOnlineCourseEnrollmentView(APIView):
    """POST: رد یک ثبت‌نامِ در-انتظارِ دوره (رسید نامعتبر)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            enrollment = OnlineCourseEnrollment.objects.get(course_id=pk, student_id=student_id, self_enrolled=True, payment_verified=False)
        except OnlineCourseEnrollment.DoesNotExist:
            return Response({'error': 'ثبت‌نام در انتظاری پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        enrollment.delete()
        return Response({'message': 'ثبت‌نام رد شد و حذف گردید'})


class RefundOnlineCourseEnrollmentView(APIView):
    """POST: استرداد وجه یک ثبت‌نام دوره"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            course = OnlineCourse.objects.get(pk=pk)
            enrollment = OnlineCourseEnrollment.objects.get(course=course, student_id=student_id)
        except (OnlineCourse.DoesNotExist, OnlineCourseEnrollment.DoesNotExist):
            return Response({'error': 'ثبت‌نام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        serializer = RefundEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        refund = EnrollmentRefund.objects.create(
            student_id=student_id, online_course=course, amount=enrollment.price_paid,
            card_number=data['card_number'], receiver_name=data['receiver_name'],
            refunded_by=request.user,
        )
        enrollment.delete()

        return Response({
            'message': 'وجه مسترد شد و دانش‌آموز از دوره حذف شد',
            'refund': {'id': refund.id, 'amount': refund.amount, 'card_number': refund.card_number, 'receiver_name': refund.receiver_name},
        })


class CreditOnlineCourseToWalletView(APIView):
    """POST: انتقال وجه ثبت‌نامِ یک دوره به کیف پول دانش‌آموز"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            course = OnlineCourse.objects.get(pk=pk)
            enrollment = OnlineCourseEnrollment.objects.get(course=course, student_id=student_id)
        except (OnlineCourse.DoesNotExist, OnlineCourseEnrollment.DoesNotExist):
            return Response({'error': 'ثبت‌نام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        amount = enrollment.price_paid
        student = enrollment.student
        enrollment.delete()

        student.wallet_balance += amount
        student.save(update_fields=['wallet_balance'])
        WalletTransaction.objects.create(
            student=student, kind=WalletTransaction.Kind.CREDIT, amount=amount,
            reason=f'انتقال از دوره «{course.title}» به کیف پول', online_course=course,
        )

        return Response({
            'message': f'{amount:,} تومان به کیف پول دانش‌آموز واریز شد',
            'wallet_balance': student.wallet_balance,
            'course': OnlineCourseSerializer(course).data,
        })


class OnlineCourseRosterView(generics.ListAPIView):
    """GET: لیست دانش‌آموزانِ *تاییدشده*ی یک دوره‌ی علمی/آنلاین خاص — پایه‌ی دکمه‌های استرداد/کیف‌پول/حذف/انتقال"""
    permission_classes = [IsAuthenticated]
    serializer_class = OnlineCourseEnrollmentSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'class-management'):
            return OnlineCourseEnrollment.objects.none()
        return OnlineCourseEnrollment.objects.filter(course_id=self.kwargs['pk'], payment_verified=True).select_related('student')


class OnlineCourseUnenrollView(APIView):
    """DELETE: دکمه‌ی «حذف» — دانش‌آموز بدون استرداد یا انتقالِ وجه از دوره حذف می‌شود (مثلاً ثبت‌نام اشتباه)"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            course = OnlineCourse.objects.get(pk=pk)
            enrollment = OnlineCourseEnrollment.objects.get(course=course, student_id=student_id)
        except (OnlineCourse.DoesNotExist, OnlineCourseEnrollment.DoesNotExist):
            return Response({'error': 'ثبت‌نام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        enrollment.delete()
        return Response({'message': 'دانش‌آموز از این دوره حذف شد', 'course': OnlineCourseSerializer(course).data})


class OnlineCourseTransferOptionsView(APIView):
    """GET: لیست دوره‌های علمی/آنلاینِ فعالِ دیگر (به‌جز خودِ همین دوره) که جای خالی دارند — برای دکمه‌ی «انتقال کلاس»"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            course = OnlineCourse.objects.get(pk=pk)
        except OnlineCourse.DoesNotExist:
            return Response({'error': 'دوره پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        candidates = OnlineCourse.objects.exclude(pk=course.pk).filter(is_active=True)
        candidates = [c for c in candidates if c.seats_left > 0]

        return Response([{
            'id': c.id, 'title': c.title, 'teacher_name': c.teacher_name,
            'schedule_note': c.schedule_note, 'seats_left': c.seats_left, 'price': c.price,
        } for c in candidates])


class OnlineCourseTransferView(APIView):
    """POST: دکمه‌ی «انتقال کلاس» — دانش‌آموز از این دوره حذف و به دوره‌ی مقصدِ انتخاب‌شده منتقل می‌شود"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            source = OnlineCourse.objects.get(pk=pk)
            enrollment = OnlineCourseEnrollment.objects.get(course=source, student_id=student_id)
        except (OnlineCourse.DoesNotExist, OnlineCourseEnrollment.DoesNotExist):
            return Response({'error': 'ثبت‌نام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        serializer = OnlineCourseTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            target = OnlineCourse.objects.get(pk=serializer.validated_data['target_course_id'])
        except OnlineCourse.DoesNotExist:
            return Response({'error': 'دوره‌ی مقصد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        if target.pk == source.pk:
            return Response({'error': 'دوره‌ی مقصد نمی‌تواند همان دوره‌ی فعلی باشد'}, status=status.HTTP_400_BAD_REQUEST)
        if target.seats_left <= 0:
            return Response({'error': 'دوره‌ی مقصد ظرفیت خالی ندارد'}, status=status.HTTP_400_BAD_REQUEST)
        if OnlineCourseEnrollment.objects.filter(course=target, student_id=student_id).exists():
            return Response({'error': 'این دانش‌آموز از قبل توی دوره‌ی مقصد ثبت‌نام شده'}, status=status.HTTP_400_BAD_REQUEST)

        OnlineCourseEnrollment.objects.create(
            course=target, student_id=student_id, payment_method=enrollment.payment_method,
            price_paid=enrollment.price_paid, discount_percent=enrollment.discount_percent,
        )
        enrollment.delete()

        return Response({
            'message': f'دانش‌آموز به دوره‌ی «{target.title}» منتقل شد',
            'source': OnlineCourseSerializer(source).data,
            'target': OnlineCourseSerializer(target).data,
        })


class StudentCreateOnlineCourseActionRequestView(APIView):
    """
    POST: دانش‌آموز از اپ برای یک دوره‌ی علمی که در آن ثبت‌نامِ تاییدشده دارد، درخواست
    استرداد یا انتقال کلاس ثبت می‌کند. این فقط یک درخواست است؛ تا وقتی مدیر تاییدش نکند
    هیچ تغییری در ثبت‌نام واقعی ایجاد نمی‌شود.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'student':
            return Response({'error': 'فقط دانش‌آموز می‌تواند این درخواست را ثبت کند'}, status=status.HTTP_403_FORBIDDEN)

        serializer = OnlineCourseActionRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            course = OnlineCourse.objects.get(pk=data['online_course_id'])
        except OnlineCourse.DoesNotExist:
            return Response({'error': 'دوره پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        if not OnlineCourseEnrollment.objects.filter(course=course, student=request.user, payment_verified=True).exists():
            return Response({'error': 'شما در این دوره ثبت‌نامِ تاییدشده‌ای ندارید'}, status=status.HTTP_400_BAD_REQUEST)

        if OnlineCourseActionRequest.objects.filter(
            student=request.user, online_course=course, status=OnlineCourseActionRequest.Status.PENDING,
        ).exists():
            return Response({'error': 'یک درخواست در-انتظار برای همین دوره از قبل ثبت شده است'}, status=status.HTTP_400_BAD_REQUEST)

        target_course = None
        if data.get('requested_target_course_id'):
            target_course = OnlineCourse.objects.filter(pk=data['requested_target_course_id']).first()

        req = OnlineCourseActionRequest.objects.create(
            student=request.user, online_course=course, action_type=data['action_type'],
            card_number=data.get('card_number', ''), receiver_name=data.get('receiver_name', ''),
            requested_target_course=target_course, reason=data.get('reason', ''),
        )
        return Response(OnlineCourseActionRequestSerializer(req).data, status=status.HTTP_201_CREATED)


class MyOnlineCourseActionRequestsView(generics.ListAPIView):
    """GET: لیست درخواست‌های استرداد/انتقالِ خودِ دانش‌آموز — به همراه وضعیت هرکدام"""
    permission_classes = [IsAuthenticated]
    serializer_class = OnlineCourseActionRequestSerializer

    def get_queryset(self):
        return OnlineCourseActionRequest.objects.filter(student=self.request.user).select_related('online_course', 'requested_target_course')


class AdminOnlineCourseActionRequestListView(generics.ListAPIView):
    """GET: لیست همه‌ی درخواست‌های استرداد/انتقالِ کلاس علمی برای بررسی مدیر — پیش‌فرض فقط در-انتظارها؛ با ?status=all همه"""
    permission_classes = [IsAuthenticated]
    serializer_class = OnlineCourseActionRequestSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'class-management'):
            return OnlineCourseActionRequest.objects.none()
        qs = OnlineCourseActionRequest.objects.select_related('student', 'online_course', 'requested_target_course')
        status_param = self.request.query_params.get('status', 'pending')
        if status_param != 'all':
            qs = qs.filter(status=status_param)
        return qs


class ApproveOnlineCourseActionRequestView(APIView):
    """
    POST: تایید درخواست دانش‌آموز — همان عملیات واقعیِ استرداد یا انتقال را اجرا می‌کند
    (دقیقاً همان منطق دکمه‌های دستیِ مدیر) و درخواست را به‌عنوان تاییدشده علامت می‌زند.
    برای انتقال، اگر مدیر target_course_id متفاوتی بفرستد همان اولویت دارد؛ وگرنه دوره‌ی
    پیشنهادیِ خودِ دانش‌آموز استفاده می‌شود.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            req = OnlineCourseActionRequest.objects.select_related('online_course', 'student', 'requested_target_course').get(pk=pk)
        except OnlineCourseActionRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        if req.status != OnlineCourseActionRequest.Status.PENDING:
            return Response({'error': 'این درخواست قبلاً بررسی شده است'}, status=status.HTTP_400_BAD_REQUEST)

        review = OnlineCourseActionRequestReviewSerializer(data=request.data)
        review.is_valid(raise_exception=True)
        review_data = review.validated_data

        try:
            enrollment = OnlineCourseEnrollment.objects.get(course=req.online_course, student=req.student)
        except OnlineCourseEnrollment.DoesNotExist:
            return Response({'error': 'ثبت‌نام مربوطه دیگر وجود ندارد'}, status=status.HTTP_404_NOT_FOUND)

        if req.action_type == OnlineCourseActionRequest.ActionType.REFUND:
            refund = EnrollmentRefund.objects.create(
                student=req.student, online_course=req.online_course, amount=enrollment.price_paid,
                card_number=req.card_number, receiver_name=req.receiver_name, refunded_by=request.user,
            )
            enrollment.delete()
            result_message = f'استرداد {refund.amount:,} تومانی تایید و اجرا شد'
        else:
            target_id = review_data.get('target_course_id') or (req.requested_target_course_id)
            if not target_id:
                return Response({'error': 'برای تایید انتقال، دوره‌ی مقصد باید مشخص شود'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                target = OnlineCourse.objects.get(pk=target_id)
            except OnlineCourse.DoesNotExist:
                return Response({'error': 'دوره‌ی مقصد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
            if target.pk == req.online_course_id:
                return Response({'error': 'دوره‌ی مقصد نمی‌تواند همان دوره‌ی فعلی باشد'}, status=status.HTTP_400_BAD_REQUEST)
            if target.seats_left <= 0:
                return Response({'error': 'دوره‌ی مقصد ظرفیت خالی ندارد'}, status=status.HTTP_400_BAD_REQUEST)
            if OnlineCourseEnrollment.objects.filter(course=target, student=req.student).exists():
                return Response({'error': 'دانش‌آموز از قبل در دوره‌ی مقصد ثبت‌نام شده'}, status=status.HTTP_400_BAD_REQUEST)
            OnlineCourseEnrollment.objects.create(
                course=target, student=req.student, payment_method=enrollment.payment_method,
                price_paid=enrollment.price_paid, discount_percent=enrollment.discount_percent,
            )
            enrollment.delete()
            result_message = f'انتقال به دوره‌ی «{target.title}» تایید و اجرا شد'

        req.status = OnlineCourseActionRequest.Status.APPROVED
        req.admin_note = review_data.get('admin_note', '')
        req.reviewed_by = request.user
        req.reviewed_at = timezone.now()
        req.save()

        return Response({'message': result_message, 'request': OnlineCourseActionRequestSerializer(req).data})


class RejectOnlineCourseActionRequestView(APIView):
    """POST: رد درخواست دانش‌آموز — هیچ تغییری در ثبت‌نام ایجاد نمی‌شود، فقط وضعیت و دلیل رد ثبت می‌شود"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            req = OnlineCourseActionRequest.objects.get(pk=pk)
        except OnlineCourseActionRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        if req.status != OnlineCourseActionRequest.Status.PENDING:
            return Response({'error': 'این درخواست قبلاً بررسی شده است'}, status=status.HTTP_400_BAD_REQUEST)

        review = OnlineCourseActionRequestReviewSerializer(data=request.data)
        review.is_valid(raise_exception=True)

        req.status = OnlineCourseActionRequest.Status.REJECTED
        req.admin_note = review.validated_data.get('admin_note', '')
        req.reviewed_by = request.user
        req.reviewed_at = timezone.now()
        req.save()

        return Response({'message': 'درخواست رد شد', 'request': OnlineCourseActionRequestSerializer(req).data})


class MyOnlineCourseEnrollmentsView(APIView):
    """GET: دوره‌های آنلاینی که خودِ دانش‌آموز خریده — برای اپ دانش‌آموز"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = request.user
        if student.role != 'student':
            return Response({'error': 'این بخش فقط برای دانش‌آموزان است'}, status=status.HTTP_403_FORBIDDEN)
        enrollments = OnlineCourseEnrollment.objects.filter(student=student).select_related('course').order_by('-created_at')
        return Response([{
            'id': e.id,
            'course_id': e.course.id,
            'course_title': e.course.title,
            'teacher_name': e.course.teacher_name,
            'schedule_note': e.course.schedule_note,
            'session_date_jalali': e.course.session_date_jalali,
            'session_time': e.course.session_time,
            'session_count': e.course.session_count,
            'meeting_link': e.course.meeting_link if e.payment_verified else '',
            'price_paid': e.price_paid,
            'discount_percent': e.discount_percent,
            'payment_verified': e.payment_verified,
            'created_at_jalali': e.created_at_jalali,
        } for e in enrollments])


class TeacherOnlineCoursesView(APIView):
    """GET: دوره‌های آنلاین مستقلی که به خودِ استاد تخصیص داده شده — برای اپ استاد، همراه با تاریخچه‌ی همه‌ی دوره‌های قبلی‌اش"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if request.user.role not in User.TEACHER_LIKE_ROLES:
            return Response({'error': 'این بخش فقط برای اساتید است'}, status=status.HTTP_403_FORBIDDEN)

        teacher_full_name = request.user.get_full_name().strip()
        courses = OnlineCourse.objects.filter(teacher_name__iexact=teacher_full_name).order_by('-created_at')

        result = []
        today_str = timezone.now().date().isoformat()
        today = timezone.now().date()
        for c in courses:
            students = OnlineCourseEnrollment.objects.filter(course=c, payment_verified=True).select_related('student')
            today_attendance = {a.student_id: a for a in ClassAttendance.objects.filter(online_course=c, date=today)}
            result.append({
                'id': c.id, 'title': c.title, 'schedule_note': c.schedule_note,
                'session_date_jalali': c.session_date_jalali, 'session_time': c.session_time,
                'session_count': c.session_count, 'meeting_link': c.meeting_link,
                'is_active': c.is_active, 'created_at_jalali': c.created_at_jalali,
                'student_count': students.count(),
                'students': [f"{e.student.first_name} {e.student.last_name}".strip() for e in students],
                'roster': [{
                    'student_id': e.student.id,
                    'student_name': f"{e.student.first_name} {e.student.last_name}".strip(),
                    'today_attendance': (
                        {'is_present': today_attendance[e.student.id].is_present, 'date_jalali': today_attendance[e.student.id].date_jalali}
                        if e.student.id in today_attendance else None
                    ),
                } for e in students],
                'today_date': today_str,
            })

        return Response({'courses': result})


class GatewayPaymentInitiateView(APIView):
    """
    POST: شروع پرداخت از درگاه — ساختار آماده برای اتصال بعدی به یک درگاه واقعی (زرین‌پال/آیدی‌پی/...).
    فعلاً فقط پیام «به‌زودی» برمی‌گرداند؛ وقتی مشخصات درگاه واقعی مشخص شد، این ویو باید:
    ۱) یک تراکنش/سفارش pending بسازد (شبیه به self-enroll ولی payment_method='gateway')
    ۲) درخواست به API درگاه بزند و لینک پرداخت (authority/redirect_url) را برگرداند
    ۳) در callback درگاه، وضعیت را verify و payment_verified=True کند
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return Response(
            {'error': 'پرداخت از درگاه هنوز راه‌اندازی نشده — لطفاً از کارت‌به‌کارت استفاده کنید'},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )


class PaymentSettingsView(APIView):
    """
    GET: شماره‌کارت/نام صاحب‌کارت برای واریز کارت‌به‌کارت — همه‌ی کاربران احراز‌هویت‌شده می‌بینند
    (تا موقع پرداخت در اپ نشان داده شود). PATCH: فقط مدیر می‌تواند تنظیم/ویرایش کند.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(PaymentSettingsSerializer(PaymentSettings.get_solo()).data)

    def patch(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        obj = PaymentSettings.get_solo()
        serializer = PaymentSettingsSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ==================== حضور و غیاب دانش‌آموزان ====================

ATTENDANCE_STATUSES = set(ClassAttendance.Status.values)


def _save_roster_attendance(slot, student_id, session_number, attendance_status, note, marked_by):
    """یک وضعیت حضور را فقط برای زبان‌آموز ثبت‌نام‌شده و یک جلسهٔ واقعی ذخیره می‌کند."""
    try:
        session_number = int(session_number)
    except (TypeError, ValueError):
        raise ValueError('شماره جلسه نامعتبر است')
    if session_number < 1 or session_number > DEFAULT_SESSION_COUNT:
        raise ValueError(f'شماره جلسه باید بین ۱ تا {DEFAULT_SESSION_COUNT} باشد')
    if attendance_status not in ATTENDANCE_STATUSES | {'unmarked'}:
        raise ValueError('وضعیت حضور و غیاب نامعتبر است')
    if not ClassSlotEnrollment.objects.filter(
        class_slot=slot, student_id=student_id, payment_verified=True,
    ).exists():
        raise ValueError('دانش‌آموز در فهرست ثبت‌نام‌های تاییدشدهٔ این کلاس نیست')

    class_date, sub = session_date_and_sub(slot, session_number)
    if class_date is None:
        raise ValueError('تاریخ خودکار این جلسه برای کلاس قابل محاسبه نیست؛ تاریخ ترم و روز برگزاری را بررسی کنید')
    lookup = {'class_slot': slot, 'student_id': student_id, 'date': class_date, 'session_in_day': sub}

    if attendance_status == 'unmarked':
        ClassAttendance.objects.filter(**lookup).delete()
        return None
    attendance, _ = ClassAttendance.objects.update_or_create(
        **lookup,
        defaults={
            'status': attendance_status,
            'is_present': attendance_status != ClassAttendance.Status.ABSENT,
            'note': str(note or '')[:200],
            'marked_by': marked_by,
        },
    )
    return attendance


def _user_can_manage_roster(user, slot):
    """ادمین با دسترسی مدیریت کلاس، یا استادِ همان کلاس، اجازهٔ ثبت حضور و غیاب رستر را دارد."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    if can_edit_menu(user, 'class-management'):
        return True
    if user.role in User.TEACHER_LIKE_ROLES:
        return slot.teacher_name.strip().casefold() == user.get_full_name().strip().casefold()
    return False


class RosterNotInClassView(APIView):
    """
    دکمه‌ی «فرد در این کلاس نیست» در حضور و غیاب: مشخصات فرد خودکار به «ثبت‌نام‌نشده‌های» پنل وب می‌رود
    با برچسب قرمز «در کلاس درست ثبت‌نام نشده — جابجا شود». ثبت‌نامِ فعلی فرد در کلاس دست‌نخورده می‌ماند
    تا مدیر جابجایی را انجام دهد.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from leads.models import UnregisteredStudent
        slot_id = request.data.get('class_slot')
        student_id = request.data.get('student_id')
        if not slot_id or not student_id:
            return Response({'error': 'class_slot و student_id الزامی هستند'}, status=status.HTTP_400_BAD_REQUEST)
        slot = get_object_or_404(ClassSlot.objects.select_related('term'), pk=slot_id)
        if not _user_can_manage_roster(request.user, slot):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        enrollment = ClassSlotEnrollment.objects.filter(class_slot=slot, student_id=student_id).select_related('student').first()
        if not enrollment:
            return Response({'error': 'این دانش‌آموز در لیست این کلاس نیست'}, status=status.HTTP_404_NOT_FOUND)
        student = enrollment.student
        existing = UnregisteredStudent.objects.filter(
            term=slot.term, is_misplaced=True, misplaced_from_slot=slot, status=UnregisteredStudent.Status.TRACKING,
            first_name=student.first_name, last_name=student.last_name,
        ).first()
        if existing:
            return Response({'message': 'قبلاً به ثبت‌نام‌نشده‌ها منتقل شده است', 'id': existing.id, 'already': True})
        try:
            with transaction.atomic():
                item = UnregisteredStudent.objects.create(
                    first_name=student.first_name, last_name=student.last_name,
                    class_level=slot.assigned_level or 'نامشخص', national_code=student.national_code or '',
                    phone=student.phone or '', term=slot.term, is_misplaced=True, misplaced_from_slot=slot,
                    gender=student.gender or {'girls': 'female', 'boys': 'male'}.get(slot.gender, ''),
                    submitted_by=request.user,
                )
        except IntegrityError:
            return Response({'error': 'این فرد قبلاً با همین مشخصات در ثبت‌نام‌نشده‌های این ترم ثبت شده است'}, status=status.HTTP_409_CONFLICT)
        return Response({'message': 'به ثبت‌نام‌نشده‌ها منتقل شد', 'id': item.id, 'already': False}, status=status.HTTP_201_CREATED)


class RosterAttendanceView(APIView):
    """لیست ۲۰ سطری یک کلاس و ثبت حضور با تاریخ‌های از پیش محاسبه‌شدهٔ همان ترم."""
    permission_classes = [IsAuthenticated]

    def _get_slot(self, slot_id):
        return get_object_or_404(ClassSlot.objects.select_related('term'), pk=slot_id)

    def get(self, request):
        slot_id = request.query_params.get('class_slot')
        if not slot_id:
            return Response({'error': 'شناسه کلاس الزامی است'}, status=status.HTTP_400_BAD_REQUEST)
        slot = self._get_slot(slot_id)
        if not _user_can_manage_roster(request.user, slot):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return Response(roster_attendance_payload(slot))

    def post(self, request):
        slot_id = request.data.get('class_slot')
        records = request.data.get('records')
        if not slot_id or not isinstance(records, list):
            return Response({'error': 'class_slot و فهرست records الزامی هستند'}, status=status.HTTP_400_BAD_REQUEST)
        slot = self._get_slot(slot_id)
        if not _user_can_manage_roster(request.user, slot):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            with transaction.atomic():
                for row in records:
                    _save_roster_attendance(
                        slot=slot,
                        student_id=row.get('student_id'),
                        session_number=row.get('session_number'),
                        attendance_status=row.get('status', 'unmarked'),
                        note=row.get('note', ''),
                        marked_by=request.user,
                    )
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        payload = roster_attendance_payload(slot)
        payload['message'] = f'{len(records)} وضعیت حضور و غیاب ذخیره شد'
        return Response(payload)


class BulkRosterAttendanceView(APIView):
    """انتخاب و ثبت یکجای حضور و غیاب کلاس‌های یک ترم با فیلتر استاد، سطح و روز."""
    permission_classes = [IsAuthenticated]

    def _filtered_slots(self, params):
        term_id = params.get('term')
        if not term_id:
            raise ValueError('انتخاب ترم الزامی است')
        try:
            qs = ClassSlot.objects.select_related('term').filter(term_id=int(term_id))
        except (TypeError, ValueError):
            raise ValueError('ترم انتخاب‌شده نامعتبر است')
        teacher_name = str(params.get('teacher_name') or '').strip()
        level = str(params.get('level') or '').strip()
        day_type = str(params.get('day_type') or '').strip()
        if teacher_name:
            qs = qs.filter(teacher_name__iexact=teacher_name)
        if level:
            qs = qs.filter(assigned_level__iexact=level)
        if day_type:
            qs = qs.filter(day_type=day_type)
        return qs.order_by('teacher_name', 'assigned_level', 'day_type', 'time_slot', 'number')

    def get(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            slots = self._filtered_slots(request.query_params)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'classes': [roster_attendance_payload(slot) for slot in slots]})

    def post(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        records = request.data.get('records')
        if not isinstance(records, list):
            return Response({'error': 'فهرست records الزامی است'}, status=status.HTTP_400_BAD_REQUEST)
        slot_ids = {row.get('class_slot') for row in records if row.get('class_slot')}
        slots = {
            slot.id: slot for slot in ClassSlot.objects.select_related('term').filter(id__in=slot_ids)
        }
        if len(slots) != len(slot_ids):
            return Response({'error': 'یک یا چند کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        try:
            with transaction.atomic():
                for row in records:
                    slot = slots.get(row.get('class_slot'))
                    if slot is None:
                        raise ValueError('شناسه کلاس در یک رکورد نامعتبر است')
                    _save_roster_attendance(
                        slot=slot,
                        student_id=row.get('student_id'),
                        session_number=row.get('session_number'),
                        attendance_status=row.get('status', 'unmarked'),
                        note=row.get('note', ''),
                        marked_by=request.user,
                    )
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'message': f'{len(records)} وضعیت حضور و غیاب در {len(slot_ids)} کلاس ذخیره شد'})


class MarkAttendanceView(APIView):
    """API سازگار با اپ استاد/نسخه‌های قبلی؛ با پشتیبانی از حاضر، غایب و تأخیر."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if not can_edit_menu(request.user, 'class-management') and request.user.role not in User.TEACHER_LIKE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        class_slot_id = request.data.get('class_slot')
        online_course_id = request.data.get('online_course')
        student_id = request.data.get('student')
        date_str = request.data.get('date')
        note = request.data.get('note', '')
        supplied_status = request.data.get('status')
        attendance_status = supplied_status or ('present' if request.data.get('is_present', True) else 'absent')
        if attendance_status not in ATTENDANCE_STATUSES:
            return Response({'error': 'وضعیت حضور و غیاب نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)

        if not student_id or not date_str or (not class_slot_id and not online_course_id):
            return Response({'error': 'student، date، و یکی از class_slot/online_course الزامی است'}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.role in User.TEACHER_LIKE_ROLES and not can_edit_menu(request.user, 'class-management'):
            teacher_full_name = request.user.get_full_name().strip()
            owns = ClassSlot.objects.filter(pk=class_slot_id, teacher_name__iexact=teacher_full_name).exists() if class_slot_id else OnlineCourse.objects.filter(pk=online_course_id, teacher_name__iexact=teacher_full_name).exists()
            if not owns:
                return Response({'error': 'این کلاس/دوره متعلق به شما نیست'}, status=status.HTTP_403_FORBIDDEN)

        lookup = {'student_id': student_id, 'date': date_str}
        if class_slot_id:
            lookup['class_slot_id'] = class_slot_id
        else:
            lookup['online_course_id'] = online_course_id
        attendance, _created = ClassAttendance.objects.update_or_create(
            **lookup,
            defaults={
                'status': attendance_status,
                'is_present': attendance_status != ClassAttendance.Status.ABSENT,
                'note': note,
                'marked_by': request.user,
            },
        )
        return Response(ClassAttendanceSerializer(attendance).data)


class ClassAttendanceListView(generics.ListAPIView):
    """GET: لیست حضور و غیاب یک کلاس ترمیک یا دوره‌ی علمی."""
    permission_classes = [IsAuthenticated]
    serializer_class = ClassAttendanceSerializer

    def get_queryset(self):
        qs = ClassAttendance.objects.select_related('student', 'marked_by')
        class_slot_id = self.request.query_params.get('class_slot')
        online_course_id = self.request.query_params.get('online_course')
        date_str = self.request.query_params.get('date')
        if class_slot_id:
            qs = qs.filter(class_slot_id=class_slot_id)
        if online_course_id:
            qs = qs.filter(online_course_id=online_course_id)
        if date_str:
            qs = qs.filter(date=date_str)
        return qs


def _teacher_event_payload(event):
    slot = event.class_slot
    return {
        'id': event.id, 'term': event.term_id, 'term_title': event.term.title,
        'class_slot': slot.id, 'class_number': slot.number, 'class_title': slot.title,
        'day_type': slot.day_type, 'day_type_display': slot.get_day_type_display(),
        'time_slot': slot.time_slot, 'gender': slot.gender, 'gender_display': slot.get_gender_display(),
        'level': slot.assigned_level, 'event_type': event.event_type,
        'event_type_display': event.get_event_type_display(), 'class_date': event.class_date,
        'class_date_jalali': event.class_date_jalali, 'session_number': event.session_number,
        'requested_teacher_name': event.requested_teacher_name,
        'replacement_teacher_name': event.replacement_teacher_name,
        'status': event.status, 'status_display': event.get_status_display(),
        'requested_by': event.requested_by.get_full_name() if event.requested_by else '',
        'approved_by': event.approved_by.get_full_name() if event.approved_by else '',
        'requested_at_jalali': event.requested_at_jalali, 'approved_at_jalali': event.approved_at_jalali,
        'makeup_required': event.makeup_required, 'makeup_session_count': event.makeup_session_count,
        'notes': event.notes,
    }


def _teacher_report_session_dates(slot):
    """تقویم گزارش استادان: هر نوبت یک‌روزدرهفته، سه جلسهٔ متوالی در همان تاریخ دارد."""
    dates = session_dates_for_slot(slot)
    one_day_types = {'thursday_morning', 'thursday_evening', 'friday', 'friday_morning', 'friday_evening'}
    if slot.day_type not in one_day_types:
        return dates
    expanded = []
    for date_value in dates:
        expanded.extend([date_value, date_value, date_value])
        if len(expanded) >= DEFAULT_SESSION_COUNT:
            break
    return expanded[:DEFAULT_SESSION_COUNT]


def _teacher_report_payload(slot, events):
    approved = [e for e in events if TeacherSessionEvent is not None and e.status == TeacherSessionEvent.ApprovalStatus.APPROVED]
    source = slot.teacher_name or ''
    # منبع واحد تاریخ جلسه: همان تقویمی که لیست کلاسی و حضور و غیاب استفاده می‌کند.
    scheduled_dates = _teacher_report_session_dates(slot)
    total_sessions = len(scheduled_dates) or DEFAULT_SESSION_COUNT
    date_by_session = {index: value for index, value in enumerate(scheduled_dates, start=1)}
    today = timezone.localdate()
    elapsed_session_numbers = {number for number, value in date_by_session.items() if value <= today}
    elapsed_sessions = len(elapsed_session_numbers)
    past_absence_count = sum(1 for e in approved if e.event_type == TeacherSessionEvent.EventType.ABSENCE and e.session_number in elapsed_session_numbers)
    past_substitution_count = sum(1 for e in approved if e.event_type == TeacherSessionEvent.EventType.SUBSTITUTION and e.session_number in elapsed_session_numbers)
    absence_count = sum(1 for e in approved if e.event_type == TeacherSessionEvent.EventType.ABSENCE)
    substitution_count = sum(1 for e in approved if e.event_type == TeacherSessionEvent.EventType.SUBSTITUTION)
    makeup_count = sum(1 for e in approved if e.event_type == TeacherSessionEvent.EventType.MAKEUP)
    replacement_counts = {}
    status_rows = []

    for event in approved:
        automatic_date = date_by_session.get(event.session_number)
        display_date = jalali_date(automatic_date) if automatic_date else event.class_date_jalali
        if event.event_type == TeacherSessionEvent.EventType.SUBSTITUTION:
            replacement_counts[event.replacement_teacher_name] = replacement_counts.get(event.replacement_teacher_name, 0) + 1
            status_rows.append({'id': event.id, 'session_number': event.session_number, 'date': display_date, 'status': 'substitution', 'label': 'ساب', 'teacher': event.replacement_teacher_name})
        elif event.event_type == TeacherSessionEvent.EventType.ABSENCE:
            status_rows.append({'id': event.id, 'session_number': event.session_number, 'date': display_date, 'status': 'absence', 'label': 'غیبت/کنسلی', 'teacher': source})
        elif event.event_type == TeacherSessionEvent.EventType.MAKEUP:
            status_rows.append({'id': event.id, 'session_number': event.session_number, 'date': display_date, 'status': 'makeup', 'label': 'جبرانی', 'teacher': source})

    source_count = max(0, elapsed_sessions - past_substitution_count - past_absence_count)
    participants = [{'teacher_name': source, 'role': 'استاد اصلی', 'scheduled_sessions': total_sessions, 'effective_sessions': source_count}]
    for name, count in sorted(replacement_counts.items()):
        if name:
            participants.append({'teacher_name': name, 'role': 'استاد پذیرنده ساب', 'scheduled_sessions': 0, 'effective_sessions': count})
    return {
        'class_slot': slot.id, 'term_id': slot.term_id,
        'class_number': slot.number, 'class_title': slot.title,
        'teacher_name': source, 'day_type': slot.day_type, 'day_type_display': slot.get_day_type_display(),
        'time_slot': slot.time_slot, 'gender': slot.gender, 'gender_display': slot.get_gender_display(),
        'level': slot.assigned_level, 'capacity': slot.capacity,
        'term_start_date': slot.term.start_date.isoformat() if slot.term_id else None,
        'term_end_date': slot.term.end_date.isoformat() if slot.term_id else None,
        'session_dates': [value.isoformat() for value in scheduled_dates],
        'total_sessions': total_sessions,
        'elapsed_sessions': elapsed_sessions,
        'held_sessions': max(0, elapsed_sessions - past_absence_count),
        'progress_sessions': max(0, elapsed_sessions - past_absence_count),
        'substitution_count': substitution_count, 'absence_count': absence_count,
        'makeup_count': makeup_count, 'repaired_absence_count': makeup_count,
        'participants': participants, 'session_statuses': status_rows,
        'holiday_warnings': term_holiday_warnings_for_slot(slot),
    }


def _teacher_attendance_data(record, pay_factors=None):
    setting = getattr(record.teacher, 'teacher_compensation_setting', None)
    # ضریب امتیاز اولویت (teacher_priority) — فقط وقتی تیک «اثر روی قیمت» روشن است غیر از ۱ می‌شود
    priority_factor = float((pay_factors or {}).get(record.teacher_id, 1.0))
    multiplier = 1.0
    if setting:
        if record.class_slot.day_type in (ClassSlot.DayType.FRIDAY, ClassSlot.DayType.FRIDAY_MORNING, ClassSlot.DayType.FRIDAY_EVENING): multiplier = float(setting.friday_multiplier)
        elif record.class_slot.day_type in (ClassSlot.DayType.THURSDAY_MORNING, ClassSlot.DayType.THURSDAY_EVENING): multiplier = float(setting.thursday_multiplier)
    session_price = (setting.session_price * priority_factor) if setting else 0
    base = (session_price if setting and record.check_out_at else 0) * multiplier
    allowed = max(1, int(setting.allowed_minutes_per_session)) if setting else 90
    rate = ((int(setting.adjustment_per_minute) * priority_factor) if setting and setting.adjustment_per_minute else ((session_price / allowed) if setting else 0)) * multiplier
    shortage = max(0, allowed - record.minutes_worked) if setting and record.check_out_at else 0
    overtime = max(0, record.minutes_worked - allowed) if setting and record.check_out_at else 0
    gross = round(base + (overtime * rate) - (shortage * rate))
    # کسری بیمه یک مبلغ ترمی است (نه به ازای هر جلسه)؛ در این تابع سطح-جلسه صفر گزارش می‌شود
    # و در گزارش جمع‌بندیِ فیش دستمزد (TeacherCompensationReportView) یک‌بار برای هر ترم کسر می‌شود.
    return {
        'id': record.id, 'class_slot': record.class_slot_id, 'class_number': record.class_slot.number,
        'term_id': record.class_slot.term_id,
        'teacher': record.teacher_id, 'teacher_name': record.teacher.get_full_name(),
        'day_type': record.class_slot.day_type, 'day_type_display': record.class_slot.get_day_type_display(),
        'time_slot': record.class_slot.time_slot, 'gender': record.class_slot.get_gender_display(),
        'level': record.class_slot.assigned_level, 'class_date': record.class_date,
        'session_number': record.session_number, 'check_in_at': record.check_in_at,
        'check_out_at': record.check_out_at, 'minutes_worked': record.minutes_worked,
        'status': record.status, 'notes': record.notes,
        'session_price': setting.session_price if setting else 0, 'multiplier': multiplier,
        'priority_factor': priority_factor, 'effective_session_price': round(session_price),
        'allowed_minutes': allowed, 'shortage_minutes': shortage, 'overtime_minutes': overtime,
        'gross_amount': gross, 'insurance_deduction': 0, 'net_amount': gross,
    }


def _distance_meters(lat1, lon1, lat2, lon2):
    try:
        r = 6371000
        p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
        dp = math.radians(float(lat2) - float(lat1)); dl = math.radians(float(lon2) - float(lon1))
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))
    except (TypeError, ValueError):
        return None


def _canonical_qr_slot(slot):
    """یک QR مشترک برای شمارهٔ کلاس در همان ترم؛ مستقل از سطح و استاد."""
    existing = RoomQrToken.objects.filter(
        class_slot__term_id=slot.term_id,
        class_slot__number=slot.number,
    ).select_related('class_slot').order_by('id').first()
    if existing:
        RoomQrToken.objects.filter(
            class_slot__term_id=slot.term_id,
            class_slot__number=slot.number,
        ).exclude(pk=existing.pk).filter(is_active=True).update(is_active=False)
        return existing.class_slot, existing
    qr = RoomQrToken.objects.create(class_slot=slot)
    return slot, qr


def _qr_payload(slot, qr):
    return {
        'class_slot': slot.id,
        'class_number': slot.number,
        'token': str(qr.token),
        'payload': f'LSCHOOL-ROOM:{slot.id}:{qr.token}',
        'is_active': qr.is_active,
        'latitude': qr.latitude,
        'longitude': qr.longitude,
        'allowed_radius_m': qr.allowed_radius_m,
    }


class RoomQrManageView(APIView):
    """مدیریت یک QR مشترک برای هر شماره کلاس در هر ترم؛ مستقل از سطح و استاد."""
    permission_classes = [IsAuthenticated]
    def _allowed(self, request): return can_edit_menu(request.user, 'class-management')
    def get(self, request, pk):
        if not self._allowed(request): return Response({'error': 'دسترسی ندارید'}, status=403)
        requested_slot = get_object_or_404(ClassSlot, pk=pk)
        slot, qr = _canonical_qr_slot(requested_slot)
        return Response(_qr_payload(slot, qr))
    def post(self, request, pk):
        if not self._allowed(request): return Response({'error': 'دسترسی ندارید'}, status=403)
        requested_slot = get_object_or_404(ClassSlot, pk=pk)
        slot, qr = _canonical_qr_slot(requested_slot)
        if request.data.get('action') == 'rotate': qr.rotate()
        if 'is_active' in request.data: qr.is_active = bool(request.data.get('is_active'))
        if 'latitude' in request.data: qr.latitude = request.data.get('latitude') or None
        if 'longitude' in request.data: qr.longitude = request.data.get('longitude') or None
        if 'allowed_radius_m' in request.data: qr.allowed_radius_m = max(20, min(1000, int(request.data.get('allowed_radius_m'))))
        qr.save()
        return Response(_qr_payload(slot, qr))


class TeacherQrAttendanceView(APIView):
    """ثبت ورود/خروج استاد با توکن QR و موقعیت مکانی؛ گالری هیچ نقشی ندارد چون payload فقط از دوربین اپ دریافت می‌شود."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.contrib.auth import get_user_model
        from accounts.models import AttendanceAccessSettings
        User = get_user_model()
        toggle = AttendanceAccessSettings.get_current()
        if not toggle.teacher_attendance_enabled:
            return Response({'error': 'ثبت حضور با QR فعلاً توسط مدیر غیرفعال شده است'}, status=403)
        if request.user.role not in User.TEACHER_LIKE_ROLES and not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'این بخش فقط برای استاد یا مدیر است'}, status=403)
        raw = str(request.data.get('qr_token') or '').strip()
        parts = raw.split(':')
        token = parts[-1] if len(parts) >= 3 and parts[0] == 'LSCHOOL-ROOM' else raw
        qr = RoomQrToken.objects.select_related('class_slot').filter(token=token, is_active=True).first()
        if not qr: return Response({'error': 'QR نامعتبر، غیرفعال یا متعلق به محل دیگری است'}, status=400)
        canonical_slot = qr.class_slot
        slot = canonical_slot
        today = timezone.localtime().date()
        class_date = request.data.get('class_date') or today.isoformat()
        if not can_edit_menu(request.user, 'class-management') and str(class_date) != today.isoformat():
            return Response({'error': 'ثبت حضور فقط برای جلسه امروز مجاز است'}, status=400)
        try: session_number = int(request.data.get('session_number', 1))
        except (TypeError, ValueError): session_number = 0
        if not 1 <= session_number <= 15: return Response({'error': 'شماره جلسه باید بین ۱ تا ۱۵ باشد'}, status=400)
        teacher_name = request.user.get_full_name().strip()
        if request.user.role in User.TEACHER_LIKE_ROLES:
            candidate_slots = ClassSlot.objects.filter(term_id=canonical_slot.term_id, number=canonical_slot.number).order_by('id')
            owned_slot = next((candidate for candidate in candidate_slots if candidate.teacher_name.strip().casefold() == teacher_name.casefold() and class_date in {value.isoformat() for value in session_dates_for_slot(candidate)}), None)
            if owned_slot is None:
                owned_slot = next((candidate for candidate in candidate_slots if candidate.teacher_name.strip().casefold() == teacher_name.casefold()), None)
            if owned_slot is not None:
                slot = owned_slot
            replacement = TeacherSessionEvent.objects.filter(term_id=canonical_slot.term_id, class_slot__in=candidate_slots, class_date=class_date, session_number=session_number, event_type=TeacherSessionEvent.EventType.SUBSTITUTION, status=TeacherSessionEvent.ApprovalStatus.APPROVED, replacement_teacher_name__iexact=teacher_name).exists()
            if replacement: return Response({'error': 'برای این جلسه ساب تایید شده ثبت شده است؛ QR استاد اصلی نباید ثبت شود'}, status=400)
            if slot.teacher_name.strip().casefold() != teacher_name.casefold(): return Response({'error': 'این QR برای کلاس‌های شما نیست'}, status=403)
        if TeacherSessionEvent.objects.filter(term_id=slot.term_id, class_slot=slot, class_date=class_date, session_number=session_number, event_type=TeacherSessionEvent.EventType.ABSENCE, status=TeacherSessionEvent.ApprovalStatus.APPROVED).exists():
            return Response({'error': 'این جلسه به‌عنوان غیبت/کنسلی ثبت شده و نباید QR بخورد'}, status=400)
        lat, lon = request.data.get('latitude'), request.data.get('longitude')
        if qr.latitude is not None and qr.longitude is not None:
            distance = _distance_meters(qr.latitude, qr.longitude, lat, lon)
            if distance is None or distance > qr.allowed_radius_m:
                return Response({'error': f'شما خارج از محدوده کلاس هستید (فاصله: {round(distance) if distance else "نامشخص"} متر)'}, status=400)
        action = request.data.get('action', 'check_in')
        record, _ = TeacherSessionAttendance.objects.get_or_create(class_slot=slot, teacher=request.user, class_date=class_date, session_number=session_number)
        now = timezone.now()
        if action == 'check_in':
            if record.check_in_at: return Response({'error': 'ورود این جلسه قبلاً ثبت شده است', 'record': _teacher_attendance_data(record)}, status=400)
            record.check_in_at = now; record.check_in_latitude = lat or None; record.check_in_longitude = lon or None; record.check_in_accuracy_m = request.data.get('accuracy') or None; record.status = 'present'
        elif action == 'check_out':
            if not record.check_in_at: return Response({'error': 'ابتدا ورود را ثبت کنید'}, status=400)
            if record.check_out_at: return Response({'error': 'خروج این جلسه قبلاً ثبت شده است', 'record': _teacher_attendance_data(record)}, status=400)
            record.check_out_at = now; record.minutes_worked = max(0, int((now - record.check_in_at).total_seconds() // 60))
        else: return Response({'error': 'عملیات ورود یا خروج معتبر نیست'}, status=400)
        record.save()
        return Response({'message': 'ورود با موفقیت ثبت شد' if action == 'check_in' else 'خروج با موفقیت ثبت شد', 'record': _teacher_attendance_data(record)})


class TeacherSessionAttendanceListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, 'teacher-sessions'): return Response({'error': 'فقط مدیر می‌تواند گزارش حضور استادان را ببیند'}, status=403)
        if TeacherSessionAttendance is None:
            return Response({'records': []})
        qs = TeacherSessionAttendance.objects.select_related('class_slot', 'teacher').all()
        if request.query_params.get('term'): qs = qs.filter(class_slot__term_id=request.query_params['term'])
        if request.query_params.get('teacher'): qs = qs.filter(teacher_id=request.query_params['teacher'])
        if request.query_params.get('class_slot'): qs = qs.filter(class_slot_id=request.query_params['class_slot'])
        from teacher_priority.services import pay_factor_map
        pay_factors = pay_factor_map()
        records = [_teacher_attendance_data(x, pay_factors) for x in qs]
        totals = {}
        for row in records:
            key = str(row['teacher'])
            bucket = totals.setdefault(key, {'teacher': row['teacher'], 'teacher_name': row['teacher_name'], 'sessions': 0, 'minutes': 0, 'gross_amount': 0, 'insurance_deduction': 0, 'net_amount': 0})
            bucket['sessions'] += 1; bucket['minutes'] += row['minutes_worked']; bucket['gross_amount'] += row['gross_amount']; bucket['insurance_deduction'] += row['insurance_deduction']; bucket['net_amount'] += row['net_amount']
        return Response({'records': records, 'totals': list(totals.values())})


class TeacherCompensationSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def _allowed(self, request): return can_edit_menu(request.user, 'teacher-sessions')

    SETTING_FIELDS = ('session_price', 'ordinary_multiplier', 'thursday_multiplier', 'friday_multiplier',
                       'insurance_base_monthly', 'insurance_rate_percent', 'insurance_days_per_term',
                       'allowed_minutes_per_session', 'adjustment_per_minute')

    def _payload(self, x):
        data = {'id': x.id, 'teacher_id': x.teacher_id, 'teacher_name': x.teacher.get_full_name()}
        for field in self.SETTING_FIELDS:
            data[field] = getattr(x, field)
        data['term_insurance_deduction'] = x.term_insurance_deduction
        return data

    def get(self, request):
        if not self._allowed(request): return Response({'error': 'فقط مدیر می‌تواند تنظیمات دستمزد استادان را ببیند'}, status=403)
        qs = TeacherCompensationSetting.objects.select_related('teacher').all()
        if request.query_params.get('teacher_id'): qs = qs.filter(teacher_id=request.query_params['teacher_id'])
        return Response({'settings': [self._payload(x) for x in qs]})

    def post(self, request):
        if not self._allowed(request): return Response({'error': 'فقط مدیر می‌تواند تنظیمات دستمزد را تغییر دهد'}, status=403)
        teacher_id = request.data.get('teacher_id')
        if not teacher_id: return Response({'error': 'استاد الزامی است'}, status=400)
        from django.contrib.auth import get_user_model
        teacher = get_user_model().objects.filter(pk=teacher_id, role__in=get_user_model().TEACHER_LIKE_ROLES).first()
        if not teacher: return Response({'error': 'استاد معتبر پیدا نشد'}, status=400)
        obj, _ = TeacherCompensationSetting.objects.get_or_create(teacher=teacher)
        for field in self.SETTING_FIELDS:
            if field in request.data: setattr(obj, field, request.data[field])
        obj.save()
        return Response(self._payload(obj))


class TeacherCompensationReportView(APIView):
    """فیش دستمزد استادان بر مبنای حضور واقعی QR — جمع دقیقه/مبلغ به تفکیک استاد، و به تفکیک استاد و درس (سطح)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, 'teacher-sessions'):
            return Response({'error': 'فقط مدیر می‌تواند فیش دستمزد استادان را ببیند'}, status=403)
        if TeacherSessionAttendance is None:
            return Response({'term': None, 'totals': [], 'subject_totals': [], 'records': []})

        term_id = request.query_params.get('term') or request.query_params.get('term_id')
        term_key = str(term_id).lower() if term_id else 'all'
        qs = TeacherSessionAttendance.objects.select_related('class_slot', 'teacher').all()
        if term_key in ('', 'all'):
            pass
        elif term_key in {'legacy', 'unassigned', 'null'}:
            qs = qs.filter(class_slot__term__isnull=True)
        elif term_key.isdigit():
            qs = qs.filter(class_slot__term_id=int(term_key))
        else:
            return Response({'error': 'ترم انتخاب‌شده معتبر نیست'}, status=400)

        teacher_id = request.query_params.get('teacher_id') or request.query_params.get('teacher')
        if teacher_id: qs = qs.filter(teacher_id=teacher_id)

        from teacher_priority.services import pay_factor_map
        pay_factors = pay_factor_map()
        records = [_teacher_attendance_data(x, pay_factors) for x in qs]

        totals, subject_totals, teacher_terms, settings_cache = {}, {}, {}, {}
        for row in records:
            tkey = str(row['teacher'])
            bucket = totals.setdefault(tkey, {
                'teacher': row['teacher'], 'teacher_name': row['teacher_name'],
                'class_count_set': set(), 'record_count': 0, 'minutes_worked': 0,
                'shortage_minutes': 0, 'overtime_minutes': 0, 'gross_amount': 0,
            })
            bucket['class_count_set'].add(row['class_slot'])
            bucket['record_count'] += 1
            bucket['minutes_worked'] += row['minutes_worked']
            bucket['shortage_minutes'] += row['shortage_minutes']
            bucket['overtime_minutes'] += row['overtime_minutes']
            bucket['gross_amount'] += row['gross_amount']
            teacher_terms.setdefault(tkey, set()).add(row['term_id'])

            skey = (tkey, row['level'] or 'بدون سطح')
            sbucket = subject_totals.setdefault(skey, {
                'teacher': row['teacher'], 'teacher_name': row['teacher_name'], 'level': row['level'] or 'بدون سطح',
                'class_count_set': set(), 'record_count': 0, 'minutes_worked': 0, 'gross_amount': 0,
            })
            sbucket['class_count_set'].add(row['class_slot'])
            sbucket['record_count'] += 1
            sbucket['minutes_worked'] += row['minutes_worked']
            sbucket['gross_amount'] += row['gross_amount']

        def teacher_insurance(tkey):
            if tkey not in settings_cache:
                from django.contrib.auth import get_user_model
                teacher = get_user_model().objects.filter(pk=tkey).first()
                settings_cache[tkey] = getattr(teacher, 'teacher_compensation_setting', None) if teacher else None
            setting = settings_cache[tkey]
            if not setting:
                return 0
            terms_worked = teacher_terms.get(tkey, set())
            term_count = max(1, len({t for t in terms_worked if t is not None})) if term_key == 'all' else 1
            return setting.term_insurance_deduction * term_count

        totals_list = []
        for tkey, bucket in totals.items():
            insurance = teacher_insurance(tkey)
            gross = bucket['gross_amount']
            totals_list.append({
                'teacher': bucket['teacher'], 'teacher_name': bucket['teacher_name'],
                'class_count': len(bucket['class_count_set']), 'record_count': bucket['record_count'],
                'minutes_worked': bucket['minutes_worked'], 'shortage_minutes': bucket['shortage_minutes'],
                'overtime_minutes': bucket['overtime_minutes'], 'gross_amount': gross,
                'insurance_deduction': insurance, 'net_amount': max(0, gross - insurance),
            })
        totals_list.sort(key=lambda x: x['teacher_name'])

        subject_totals_list = [{
            'teacher': b['teacher'], 'teacher_name': b['teacher_name'], 'level': b['level'],
            'class_count': len(b['class_count_set']), 'record_count': b['record_count'],
            'minutes_worked': b['minutes_worked'], 'gross_amount': b['gross_amount'],
            'net_amount': b['gross_amount'],
        } for b in subject_totals.values()]
        subject_totals_list.sort(key=lambda x: (x['teacher_name'], x['level']))

        return Response({'term': term_id, 'totals': totals_list, 'subject_totals': subject_totals_list, 'records': records})


class TeacherTermReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, 'teacher-sessions'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        term_id = request.query_params.get('term') or request.query_params.get('term_id')
        if not term_id or (not str(term_id).isdigit() and str(term_id).lower() not in {'legacy', 'unassigned', 'null', 'all'}):
            return Response({'error': 'انتخاب ترم برای گزارش استادان الزامی است'}, status=status.HTTP_400_BAD_REQUEST)
        term_key = str(term_id).lower()
        if term_key == 'all':
            qs = ClassSlot.objects.all()
        elif term_key in {'legacy', 'unassigned', 'null'}:
            qs = ClassSlot.objects.filter(term__isnull=True)
        else:
            qs = ClassSlot.objects.filter(term_id=int(term_id))
        teacher_values = [x.strip() for x in request.query_params.getlist('teacher') if x.strip()]
        if not teacher_values and request.query_params.get('teacher'):
            teacher_values = [x.strip() for x in request.query_params.get('teacher').split(',') if x.strip()]
        search = (request.query_params.get('search') or '').strip().lower()
        event_type = request.query_params.get('event_type') or ''
        if teacher_values:
            teacher_query = Q()
            for teacher_value in teacher_values:
                teacher_query |= Q(teacher_name__icontains=teacher_value)
            qs = qs.filter(teacher_query)
        slots = list(qs.order_by('teacher_name', 'number', 'time_slot'))
        if TeacherSessionEvent is None:
            events = []
        else:
            events = TeacherSessionEvent.objects.filter(status=TeacherSessionEvent.ApprovalStatus.APPROVED).select_related('class_slot', 'term', 'requested_by', 'approved_by')
            if event_type in dict(TeacherSessionEvent.EventType.choices):
                events = events.filter(event_type=event_type)
            if term_key != 'all':
                events = events.filter(term_id=int(term_id)) if term_key.isdigit() else events.none()
        grouped = {}
        for event in events:
            grouped.setdefault(event.class_slot_id, []).append(event)
        if TeacherSessionEvent is not None and event_type in dict(TeacherSessionEvent.EventType.choices):
            slots = [slot for slot in slots if slot.id in grouped]
        rows = [_teacher_report_payload(slot, grouped.get(slot.id, [])) for slot in slots]
        if search:
            rows = [r for r in rows if search in f"{r['teacher_name']} {r['class_number']} {r['level']} {r['day_type_display']}".lower()]
        teacher_names = sorted({r['teacher_name'] for r in rows if r['teacher_name']})
        return Response({'term': term_id, 'teachers': teacher_names, 'rows': rows, 'total_held_sessions': sum(r['held_sessions'] for r in rows)})


class TeacherSessionEventListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, 'teacher-sessions'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        term_id = request.query_params.get('term') or request.query_params.get('term_id')
        if not term_id or (not str(term_id).isdigit() and str(term_id).lower() not in {'legacy', 'unassigned', 'null', 'all'}):
            return Response({'error': 'انتخاب ترم برای مشاهده ساب و غیبت الزامی است'}, status=status.HTTP_400_BAD_REQUEST)
        term_key = str(term_id).lower()
        if TeacherSessionEvent is None:
            return Response([])
        qs = TeacherSessionEvent.objects.all().select_related('class_slot', 'term', 'requested_by', 'approved_by')
        if term_key == 'all':
            pass
        elif term_key.isdigit():
            qs = qs.filter(term_id=int(term_id))
        else:
            qs = qs.none()
        event_type = request.query_params.get('event_type')
        teacher_values = [x.strip() for x in request.query_params.getlist('teacher') if x.strip()]
        if not teacher_values and request.query_params.get('teacher'):
            teacher_values = [x.strip() for x in request.query_params.get('teacher').split(',') if x.strip()]
        search = (request.query_params.get('search') or '').strip().lower()
        if event_type in dict(TeacherSessionEvent.EventType.choices): qs = qs.filter(event_type=event_type)
        if teacher_values:
            teacher_query = Q()
            for teacher_value in teacher_values:
                teacher_query |= Q(requested_teacher_name__icontains=teacher_value) | Q(replacement_teacher_name__icontains=teacher_value)
            qs = qs.filter(teacher_query)
        data = [_teacher_event_payload(e) for e in qs]
        if search:
            data = [e for e in data if search in f"{e['class_number']} {e['level']} {e['requested_teacher_name']} {e['replacement_teacher_name']} {e['day_type_display']}".lower()]
        return Response(data)

    def post(self, request):
        if not can_edit_menu(request.user, 'teacher-sessions'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        term_id = request.data.get('term_id') or request.data.get('term')
        slot_id = request.data.get('class_slot_id') or request.data.get('class_slot')
        event_type = request.data.get('event_type')
        if TeacherSessionEvent is None:
            return Response({'error': 'مدل ثبت جلسات استادان در نسخه backend نصب نشده است؛ ابتدا فایل مدل جلسات استادان و migration مربوط به آن را نصب کنید.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not str(term_id).isdigit() or not str(slot_id).isdigit() or event_type not in dict(TeacherSessionEvent.EventType.choices):
            return Response({'error': 'ترم، کلاس و نوع رویداد را کامل انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            term = Term.objects.get(pk=int(term_id)); slot = ClassSlot.objects.get(pk=int(slot_id), term=term)
        except (Term.DoesNotExist, ClassSlot.DoesNotExist):
            return Response({'error': 'کلاس با ترم انتخاب‌شده مطابقت ندارد'}, status=status.HTTP_400_BAD_REQUEST)
        raw_date = str(request.data.get('class_date') or request.data.get('class_date_jalali') or '').strip()
        raw_date = raw_date.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))
        try:
            if '/' in raw_date:
                y, m, d = [int(x) for x in raw_date.replace('-', '/').split('/')]
                class_date = jdatetime.date(y, m, d).togregorian()
            else:
                class_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            return Response({'error': 'تاریخ جلسه را به‌صورت شمسی معتبر مانند ۱۴۰۵/۰۶/۰۷ وارد کنید'}, status=status.HTTP_400_BAD_REQUEST)
        class_time = str(request.data.get('class_time') or '').strip()
        if class_time and class_time != str(slot.time_slot or '').strip():
            return Response({'error': 'ساعت انتخاب‌شده با ساعت استاندارد کلاس مطابقت ندارد'}, status=status.HTTP_400_BAD_REQUEST)
        session_number = int(request.data.get('session_number') or 0)
        if not 1 <= session_number <= 15:
            return Response({'error': 'شماره جلسه باید بین ۱ تا ۱۵ باشد'}, status=status.HTTP_400_BAD_REQUEST)
        requested_name = str(request.data.get('requested_teacher_name') or slot.teacher_name or '').strip()
        replacement_name = str(request.data.get('replacement_teacher_name') or '').strip()
        if event_type == 'substitution' and not replacement_name:
            return Response({'error': 'استاد جایگزین را انتخاب یا وارد کنید'}, status=status.HTTP_400_BAD_REQUEST)
        event = TeacherSessionEvent.objects.create(term=term, class_slot=slot, event_type=event_type, class_date=class_date, session_number=session_number, requested_teacher_name=requested_name, replacement_teacher_name=replacement_name if event_type == 'substitution' else '', requested_by=request.user, makeup_required=event_type == 'absence', makeup_session_count=1 if event_type == 'absence' else 0, notes=str(request.data.get('notes') or '').strip(), status=TeacherSessionEvent.ApprovalStatus.PENDING)
        return Response(_teacher_event_payload(event), status=status.HTTP_201_CREATED)


class TeacherSessionEventDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if not can_edit_menu(request.user, 'teacher-sessions'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try: event = TeacherSessionEvent.objects.select_related('class_slot', 'term').get(pk=pk)
        except TeacherSessionEvent.DoesNotExist: return Response({'error': 'رویداد پیدا نشد'}, status=404)
        for field in ('requested_teacher_name', 'replacement_teacher_name', 'notes'):
            if field in request.data: setattr(event, field, str(request.data.get(field) or '').strip())
        if 'event_type' in request.data and request.data['event_type'] in dict(TeacherSessionEvent.EventType.choices):
            event.event_type = request.data['event_type']
        if 'session_number' in request.data:
            n = int(request.data['session_number'])
            if not 1 <= n <= 15: return Response({'error': 'شماره جلسه باید بین ۱ تا ۱۵ باشد'}, status=400)
            event.session_number = n
        if 'class_date' in request.data:
            try: event.class_date = datetime.strptime(str(request.data['class_date']), '%Y-%m-%d').date()
            except ValueError: return Response({'error': 'تاریخ جلسه معتبر نیست'}, status=400)
        event.save(); return Response(_teacher_event_payload(event))

    def delete(self, request, pk):
        if not can_edit_menu(request.user, 'teacher-sessions'): return Response({'error': 'دسترسی ندارید'}, status=403)
        deleted, _ = TeacherSessionEvent.objects.filter(pk=pk).delete()
        return Response(status=204 if deleted else 404)

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'teacher-sessions'): return Response({'error': 'دسترسی ندارید'}, status=403)
        try: event = TeacherSessionEvent.objects.get(pk=pk)
        except TeacherSessionEvent.DoesNotExist: return Response({'error': 'رویداد پیدا نشد'}, status=404)
        decision = request.data.get('decision')
        if decision not in ('approve', 'reject'): return Response({'error': 'تصمیم تایید یا رد را مشخص کنید'}, status=400)
        event.status = TeacherSessionEvent.ApprovalStatus.APPROVED if decision == 'approve' else TeacherSessionEvent.ApprovalStatus.REJECTED
        event.approved_by = request.user; event.approved_at = timezone.now(); event.save()
        return Response(_teacher_event_payload(event))


class BulkClassSlotActionView(APIView):
    """
    POST: عملیات دسته‌جمعی روی کلاس‌های ترمیک — بر اساس فیلتر روز (زوج/فرد/پنجشنبه‌صبح/
    پنجشنبه‌عصر/جمعه — هرکدوم یا هر ترکیبی)، اختیاری ساعت‌های استاندارد، اختیاری ترم، و اختیاری
    آنلاین/فیزیکی، همه‌ی کلاس‌های منطبق را یکجا حذف یا ویرایش می‌کند — بدون نیاز به باز کردن
    هرکلاس جداگانه (که همچنان هم موجود و قابل‌استفاده است).

    بدنه‌ی درخواست:
      action: 'delete' | 'edit'
      day_types: ['even', 'odd', 'thursday_morning', 'thursday_evening', 'friday']  (الزامی، حداقل یکی)
      time_slots: [...]  (اختیاری — فقط برای زوج/فرد؛ اگه خالی باشه یعنی همه‌ی ساعت‌ها)
      term_id: عدد (اختیاری)
      is_online: true/false (اختیاری — اگه نیاد یعنی فرقی نکنه)
      slot_ids: [عدد, ...]  (اختیاری — اگه بیاد، فقط همین کلاس‌های مشخص‌شده از بین منطبق‌ها را
                 هدف می‌گیرد؛ برای وقتی که پنل ادمین لیست منطبق‌ها را نشان می‌دهد و کاربر مشخصاً
                 بعضی‌ها را تیک می‌زند، نه لزوماً همه‌ی منطبق‌ها)
      fields: {teacher_name, assigned_level, capacity, gender, notes, meeting_link, is_online}  (فقط برای action=edit؛ فقط فیلدهایی که واقعاً می‌خوای عوض کنی رو بفرست)
    """
    permission_classes = [IsAuthenticated]
    ALLOWED_EDIT_FIELDS = ['teacher_name', 'assigned_level', 'capacity', 'gender', 'notes', 'meeting_link', 'is_online']

    def post(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        action = request.data.get('action')
        day_types = request.data.get('day_types') or []
        time_slots = request.data.get('time_slots') or []
        term_id = request.data.get('term_id')
        is_online_filter = request.data.get('is_online')
        slot_ids = request.data.get('slot_ids') or []

        if action not in ('delete', 'edit'):
            return Response({'error': "action باید 'delete' یا 'edit' باشد"}, status=status.HTTP_400_BAD_REQUEST)
        if not day_types:
            return Response({'error': 'حداقل یک روز (زوج/فرد/پنجشنبه‌صبح/پنجشنبه‌عصر/جمعه) را انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)

        qs = ClassSlot.objects.filter(day_type__in=day_types)
        if time_slots:
            qs = qs.filter(time_slot__in=time_slots)
        if term_id:
            qs = qs.filter(term_id=term_id)
        if is_online_filter is not None:
            qs = qs.filter(is_online=is_online_filter)
        if slot_ids:
            qs = qs.filter(pk__in=slot_ids)

        match_count = qs.count()
        if match_count == 0:
            return Response({'error': 'هیچ کلاسی با این فیلتر پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        if action == 'delete':
            # خواسته: کلاسی که دانش‌آموز ثبت‌نام‌شده دارد حذف نمی‌شود، تا وقتی همه‌ی افراد مسترد یا حذف شوند
            blocked = [s for s in qs.annotate(enr_total=Count('enrollments')).filter(enr_total__gt=0)]
            if blocked:
                names = '، '.join(f'کلاس {b.number} ({b.enr_total} نفر)' for b in blocked[:10])
                more = f' و {len(blocked) - 10} کلاس دیگر' if len(blocked) > 10 else ''
                return Response(
                    {'error': f'هیچ کلاسی حذف نشد. این کلاس‌ها دانش‌آموز ثبت‌نام‌شده دارند: {names}{more} — ابتدا دانش‌آموزان را استرداد یا حذف کنید.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            qs.delete()
            return Response({'message': f'{match_count} کلاس حذف شد', 'deleted_count': match_count})

        # action == 'edit'
        raw_fields = request.data.get('fields') or {}
        updates = {k: v for k, v in raw_fields.items() if k in self.ALLOWED_EDIT_FIELDS}
        if not updates:
            return Response({'error': 'هیچ فیلدی برای ویرایش دسته‌جمعی مشخص نشده'}, status=status.HTTP_400_BAD_REQUEST)

        updated, skipped = 0, 0
        from django.db import IntegrityError
        for slot in qs:
            try:
                for k, v in updates.items():
                    setattr(slot, k, v)
                slot.full_clean()
                slot.save()
                updated += 1
            except (IntegrityError, Exception):
                skipped += 1

        msg = f'{updated} کلاس ویرایش شد'
        if skipped:
            msg += f' — {skipped} مورد به‌خاطر تداخل (مثلاً یکتاییِ شماره کلاس در همون روز/ساعت) رد شد'
        return Response({'message': msg, 'updated_count': updated, 'skipped_count': skipped})


def _student_gender_from_class(slot):
    """روز فرد=آقا و روز زوج=خانم؛ اگر جنسیت صریح کلاس با قاعده روز ناسازگار باشد، جنسیت کلاس مقدم است."""
    if not slot:
        return ''
    day_gender = {'even': 'female', 'odd': 'male'}.get(slot.day_type, '')
    class_gender = {'girls': 'female', 'boys': 'male'}.get(slot.gender, '')
    if class_gender and day_gender and class_gender != day_gender:
        return class_gender
    return day_gender or class_gender or ''


class TermOverviewView(APIView):
    """
    GET ?term_id=&gender=female|male&level=  — «کلاس‌های ترم در یک نگاه».
    همه‌ی سطوح استاندارد را با وضعیت موجود/ناموجود (برای ترم و جنسیتِ انتخابی؛ کلاس مختلط همیشه حساب می‌شود) برمی‌گرداند
    و اگر level داده شود، همه‌ی کلاس‌های آن سطح را با مشخصات کامل.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_view_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from level_tests.models import StandardLevel
        from accounts.models import ClassRequest
        from level_tests.models import LevelTest
        term_id = request.query_params.get('term_id')
        term = Term.objects.filter(pk=term_id).first() if str(term_id or '').isdigit() else None
        if not term:
            term = sorted(Term.objects.all(), key=lambda t: (t.year, t.term_number))[-1] if Term.objects.exists() else None
        if not term:
            return Response({'term': None, 'all_levels': [], 'classes': []})
        gender = request.query_params.get('gender', '')
        student_param = request.query_params.get('student_id')
        if not gender and str(student_param or '').isdigit():
            from django.contrib.auth import get_user_model
            student = get_user_model().objects.filter(pk=student_param, role='student').only('gender').first()
            gender = getattr(student, 'gender', '') or ''
            if not gender:
                enrolled = ClassSlotEnrollment.objects.filter(
                    student_id=student_param, class_slot__term=term,
                ).select_related('class_slot').order_by('-created_at', '-id').first()
                # اگر جنسیت پرونده خالی باشد، از کلاس همین ترم برای fallback استفاده می‌شود.
                gender = _student_gender_from_class(enrolled.class_slot) if enrolled else ''

        def gender_ok(slot):
            if not gender or slot.gender == ClassSlot.Gender.MIXED:
                return True
            return (slot.gender == ClassSlot.Gender.GIRLS and gender == 'female') or (slot.gender == ClassSlot.Gender.BOYS and gender == 'male')

        pool = [c for c in ClassSlot.objects.filter(term=term).order_by('number', 'day_type', 'time_slot') if gender_ok(c)]
        have = {}
        for c in pool:
            if c.assigned_level:
                key = _normalize_level(c.assigned_level)
                have.setdefault(key, [c.assigned_level, 0])[1] += 1
        group_labels = dict(StandardLevel.AgeGroup.choices)
        all_levels, seen = [], set()
        for lv in StandardLevel.objects.all().order_by('age_group', 'order', 'code'):
            key = _normalize_level(lv.code)
            if key in seen:
                continue
            seen.add(key)
            all_levels.append({
                'value': have[key][0] if key in have else lv.code, 'label': lv.code, 'group': lv.age_group,
                'group_label': group_labels.get(lv.age_group, lv.age_group),
                'available': key in have, 'class_count': have[key][1] if key in have else 0,
            })
        for key, (label, count) in have.items():
            if key not in seen:
                all_levels.append({'value': label, 'label': label, 'group': 'other', 'group_label': 'سایر', 'available': True, 'class_count': count})
        classes = []
        level = (request.query_params.get('level') or '').strip()
        if level:
            target = _normalize_level(level)
            classes = [ClassSlotSerializer(c).data for c in pool if _normalize_level(c.assigned_level) == target]
        return Response({'term': term.id, 'term_title': term.title, 'gender': gender, 'level': level, 'all_levels': all_levels, 'classes': classes})


class AttendanceStatusView(APIView):
    """
    GET ?term_id=&date=YYYY-MM-DD (پیش‌فرض: امروز، آخرین ترم) — وضعیت ثبت حضور و غیاب کلاس‌های ترم در آن تاریخ.
    held=True یعنی آن کلاس طبق تقویمش در آن روز جلسه دارد؛ recorded=True یعنی حداقل یک حضور/غیاب برایش ثبت شده.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import datetime as _dt
        from .attendance import attendance_session_dates_for_slot
        from django.db.models import Count
        term_id = request.query_params.get('term_id')
        term = Term.objects.filter(pk=term_id).first() if str(term_id or '').isdigit() else None
        if not term:
            term = sorted(Term.objects.all(), key=lambda t: (t.year, t.term_number))[-1] if Term.objects.exists() else None
        if not term:
            return Response({'date': None, 'classes': []})
        try:
            day = _dt.date.fromisoformat(request.query_params.get('date') or '')
        except ValueError:
            day = timezone.localdate()
        slots = list(ClassSlot.objects.filter(term=term).select_related('term').prefetch_related('term__holidays').order_by('number', 'day_type', 'time_slot'))
        marked = {
            row['class_slot_id']: row['n']
            for row in ClassAttendance.objects.filter(class_slot__in=slots, date=day).values('class_slot_id').annotate(n=Count('id'))
        }
        enrolled = {
            row['class_slot_id']: row['n']
            for row in ClassSlotEnrollment.objects.filter(class_slot__in=slots, payment_verified=True).values('class_slot_id').annotate(n=Count('id'))
        }
        out = []
        for slot in slots:
            held = day in set(attendance_session_dates_for_slot(slot))
            out.append({
                'slot_id': slot.id, 'number': slot.number, 'assigned_level': slot.assigned_level,
                'day_type_display': slot.day_type_display, 'time_slot': slot.time_slot,
                'gender_display': slot.get_gender_display(), 'teacher_name': slot.teacher_name,
                'enrolled': enrolled.get(slot.id, 0), 'held': held,
                'recorded': marked.get(slot.id, 0) > 0, 'marked_count': marked.get(slot.id, 0),
            })
        return Response({'date': day.isoformat(), 'term': term.id, 'term_title': term.title, 'classes': out})


def _registered_person_key(national_code='', phone='', first_name='', last_name=''):
    """کلید یکتای فرد برای ادغام ردیف‌های یک نفر از منابع مختلف: کد ملی ← موبایل+نام ← نام."""
    national = re.sub(r'\D', '', str(national_code or ''))
    if national:
        return f'nc:{national}'
    name = ' '.join(f'{first_name or ""} {last_name or ""}'.split()).casefold()
    phone_digits = re.sub(r'\D', '', str(phone or ''))
    if phone_digits and name:
        return f'ph:{phone_digits}|{name}'
    return f'nm:{name}' if name else ''


class TermRegisteredPeopleView(APIView):
    """
    GET ?term=<id>: فهرست یکپارچهٔ «همهٔ افرادی که در این ترم، از هر مسیری، ثبت‌نام کرده‌اند».
    منابع (هر فرد فقط یک ردیف دارد و برچسب منابعش جمع می‌شود):
      ۱) ثبت‌نام در کلاس (دستی/اکسل/اپ دانش‌آموز/انتقالی/پیگیری ثبت‌نام‌نشده‌ها/ورودی‌های جدید/ریزشی‌ها)
      ۲) پیگیری افراد ثبت‌نام‌نشده با وضعیت «ثبت‌نام شد» در همین ترم
      ۳) لیست انتظار ورودی‌های جدید با وضعیت «ثبت‌نام شد» در همین ترم
      ۴) تعیین سطحِ تکمیل‌شده‌ای که فرد را در کلاسی از همین ترم جایابی کرده است
    ردیف‌هایی که کلاس مشخص ندارند با class_number خالی و has_class=False برگردانده می‌شوند.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not (can_view_menu(request.user, 'class-management') or can_edit_menu(request.user, 'class-management')):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        term_id = request.query_params.get('term')
        term = Term.objects.filter(pk=term_id).first() if term_id else None
        if not term:
            return Response({'error': 'ترم پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        from leads.models import UnregisteredStudent, NewLead

        rows = {}
        order = []

        def slot_fields(slot):
            if not slot:
                return {
                    'slot_id': None, 'level': '', 'class_number': None, 'day': '', 'day_type': '', 'time': '', 'teacher': '', 'has_class': False,
                }
            return {
                'slot_id': slot.id, 'level': slot.assigned_level or '', 'class_number': slot.number,
                'day': slot.day_type_display or slot.day_type or '', 'day_type': slot.day_type or '', 'time': slot.time_slot or '',
                'teacher': slot.teacher_name or 'بدون استاد', 'has_class': True,
            }

        def add(key, source, base, slot=None, fallback_level=''):
            if not key:
                key = f'row:{len(order)}'
            row = rows.get(key)
            if row is None:
                row = {
                    'student_id': None, 'student_name': '', 'national_code': '', 'phone': '',
                    'payment_verified': True, 'is_carryover': False, 'carryover_confirmed': False,
                    'sources': [], 'has_enrollment': False, 'is_confirmed': False, 'registered_at': '', 'level': '', 'slot_id': None, 'class_number': None,
                    'day': '', 'day_type': '', 'time': '', 'teacher': '', 'has_class': False,
                }
                rows[key] = row
                order.append(key)
            for field, value in base.items():
                if value not in (None, '') and (row.get(field) in (None, '') or field in ('payment_verified', 'is_carryover', 'carryover_confirmed')):
                    row[field] = value
            if source not in row['sources']:
                row['sources'].append(source)
            # اطلاعات کلاس فقط وقتی پر می‌شود که ردیف هنوز کلاسی نداشته باشد (ثبت‌نام واقعی اولویت دارد)
            if slot and not row['has_class']:
                row.update(slot_fields(slot))
            if not row['level'] and fallback_level:
                row['level'] = fallback_level
            return row

        # ۱) ثبت‌نام‌های واقعی در کلاس‌های این ترم (تاییدشده و در انتظار تایید پرداخت)
        enrollments = ClassSlotEnrollment.objects.filter(class_slot__term_id=term.id).select_related('student', 'class_slot').order_by('created_at', 'id')
        for en in enrollments:
            st = en.student
            if en.is_carryover and not en.carryover_confirmed:
                source = 'منتقل‌شده از ترم قبل (منتظر ثبت‌نام)'
            elif not en.payment_verified:
                source = 'ثبت‌نام اپ (در انتظار تأیید پرداخت)'
            elif en.self_enrolled:
                source = 'ثبت‌نام از اپ دانش‌آموز'
            else:
                source = 'ثبت‌نام در کلاس'
            key = _registered_person_key(st.national_code, st.phone, st.first_name, st.last_name)
            row = add(key, source, {
                'student_id': st.id, 'student_name': f'{st.first_name or ""} {st.last_name or ""}'.strip(),
                'national_code': st.national_code or '', 'phone': st.phone or '',
                'registered_at': en.created_at_jalali or '',
            }, slot=en.class_slot)
            row['has_enrollment'] = True
            # اگر فرد چند ثبت‌نام دارد، ثبت‌نام قطعی/تأییدشده بر ثبت‌نام در انتظار یا منتقل‌نشده اولویت دارد
            is_final = en.payment_verified and (not en.is_carryover or en.carryover_confirmed)
            if is_final:
                row.update(slot_fields(en.class_slot))
                row.update(payment_verified=True, is_carryover=en.is_carryover, carryover_confirmed=en.carryover_confirmed, _confirmed=True, is_confirmed=True)
            elif not row.get('_confirmed'):
                row.update(slot_fields(en.class_slot))
                row.update(payment_verified=en.payment_verified, is_carryover=en.is_carryover, carryover_confirmed=en.carryover_confirmed)

        # ۲) پیگیری ثبت‌نام‌نشده‌ها که «ثبت‌نام شد» خورده‌اند
        for u in UnregisteredStudent.objects.filter(term_id=term.id, status=UnregisteredStudent.Status.REGISTERED).select_related('reported_slot'):
            key = _registered_person_key(u.national_code, u.phone, u.first_name, u.last_name)
            add(key, 'پیگیری ثبت‌نام‌نشده‌ها', {
                'student_name': f'{u.first_name} {u.last_name}'.strip(), 'national_code': u.national_code or '', 'phone': u.phone or '',
                'registered_at': u.registered_at_jalali or '',
            }, slot=u.reported_slot, fallback_level=u.class_level or '')

        # ۳) ورودی‌های جدید (لیست انتظار) که ثبت‌نام شده‌اند
        for lead in NewLead.objects.filter(term_id=term.id, status=NewLead.Status.REGISTERED):
            key = _registered_person_key(lead.national_code, lead.phone, lead.first_name, lead.last_name)
            add(key, 'ورودی‌های جدید', {
                'student_name': f'{lead.first_name} {lead.last_name}'.strip(), 'national_code': lead.national_code or '', 'phone': lead.phone or '',
                'registered_at': lead.registered_at_jalali or '',
            }, fallback_level=lead.requested_level or '')

        # ۴) تعیین سطح‌های تکمیل‌شده‌ای که فرد را در کلاس همین ترم جایابی کرده‌اند
        tests = LevelTest.objects.filter(
            status=LevelTest.Status.COMPLETED, assigned_class_slot__term_id=term.id,
        ).select_related('assigned_class_slot', 'student').order_by('updated_at', 'id')
        for t in tests:
            key = _registered_person_key(t.national_code, t.phone, t.first_name, t.last_name)
            add(key, 'تعیین سطح', {
                'student_id': t.student_id, 'student_name': f'{t.first_name} {t.last_name}'.strip(),
                'national_code': t.national_code or '', 'phone': t.phone or '',
                'registered_at': jdatetime.datetime.fromgregorian(datetime=timezone.localtime(t.updated_at)).strftime('%Y/%m/%d') if t.updated_at else '',
            }, slot=t.assigned_class_slot, fallback_level=t.level or '')

        result = []
        for key in order:
            row = rows[key]
            row.pop('_confirmed', None)
            row['key'] = key
            row['level'] = row['level'] or '—'
            row['sources_text'] = '، '.join(row['sources'])
            result.append(row)
        result.sort(key=lambda r: (r['class_number'] is None, r['class_number'] or 0, r['student_name']))
        return Response({'term': term.id, 'count': len(result), 'rows': result})
