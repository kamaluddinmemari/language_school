from django.utils import timezone
import random
import re
import math
from datetime import datetime, timedelta
from django.db import models as django_models, transaction
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
import jdatetime
from .models import ClassSlot, ClassSlotEnrollment, TuitionSetting, DiscountedPerson, EnrollmentRefund, WalletTransaction, infer_age_group_from_level, _jalali, LevelRenewalApproval, Term, OnlineCourse, OnlineCourseEnrollment, PaymentSettings, ClassAttendance, OnlineCourseActionRequest
from .models import THREE_DAY_TIME_SLOTS, THURSDAY_MORNING_SLOT, THURSDAY_EVENING_SLOT, FRIDAY_SLOT

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
    SplitClassSerializer, LevelRenewalApprovalSerializer, TermSerializer,
    OnlineCourseSerializer, OnlineCourseEnrollmentSerializer, OnlineCourseEnrollSerializer, PaymentSettingsSerializer,
    ClassAttendanceSerializer, OnlineCourseTransferSerializer, OnlineCourseActionRequestSerializer,
    OnlineCourseActionRequestCreateSerializer, OnlineCourseActionRequestReviewSerializer,
)
from level_tests.models import LevelTest
from .allocation import allocate_classes

MANAGE_ROLES = ('admin', 'evaluator', 'office')


def _next_level_for_carryover(level_code, terminal_levels=None):
    """Return the next level using the school-approved progression, plus a terminal warning."""
    raw = str(level_code or '').strip()
    if not raw:
        return '', ''
    normalized = raw.lower().replace(' ', '')
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
            if normalized == 'i5' and label == 'کودک':
                return raw, 'سطح کودکان به پایان رسید؛ دانش‌آموزان برای ثبت‌نام ترم بعد نیازمند تعیین سطح می‌باشند.'
            if normalized == 'teen15' and label == 'نوجوان':
                return raw, 'سطح نوجوانان به پایان رسید؛ دانش‌آموزان برای ثبت‌نام ترم بعد نیازمند تعیین سطح می‌باشند.'
            if normalized == '606' and label == 'بزرگسال':
                return raw, 'دوره بزرگسالان به پایان رسید؛ دانش‌آموزان برای ثبت‌نام ترم بعد با توضیح اتمام دوره مواجه می‌شوند و نیازمند تعیین سطح می‌باشند.'
            return raw, f'سطح «{raw}» آخرین سطح {label} است و برای ترم بعد سطح بالاتری ندارد.'
    try:
        from level_tests.models import StandardLevel
        current = StandardLevel.objects.filter(code__iexact=raw).first()
        if current:
            siblings = list(StandardLevel.objects.filter(age_group=current.age_group).order_by('order', 'code').values_list('code', flat=True))
            idx = next((i for i, code in enumerate(siblings) if str(code).lower() == normalized), -1)
            if idx >= 0 and idx + 1 < len(siblings):
                return siblings[idx + 1], ''
            return raw, f'سطح «{raw}» آخرین سطح گروه «{current.get_age_group_display()}» است و برای ترم بعد سطح بالاتری ندارد.'
    except Exception:
        pass
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
    permission_classes = [IsAuthenticated]
    serializer_class = ClassSlotSerializer

    def get_queryset(self):
        if self.request.user.role not in MANAGE_ROLES:
            return ClassSlot.objects.none()
        qs = ClassSlot.objects.all()
        term_id = self.request.query_params.get('term')
        if term_id in ('legacy', 'unassigned', 'null'):
            qs = qs.filter(term__isnull=True)
        elif term_id and str(term_id).isdigit():
            qs = qs.filter(term_id=int(term_id))
        return qs

    def create(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class TermListView(generics.ListCreateAPIView):
    """GET: لیست ترم‌های تعریف‌شده / POST: تعریف یک ترم جدید (سال + شماره‌ترم ۱ تا ۸ + بازه‌ی تاریخ)"""
    permission_classes = [IsAuthenticated]
    serializer_class = TermSerializer

    def get_queryset(self):
        if self.request.user.role not in MANAGE_ROLES:
            return Term.objects.none()
        return Term.objects.all()

    def create(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class CarryClassesToNextTermView(APIView):
    """انتقال انتخابی کلاس‌های یک ترم به ترم مقصد بدون انتقال ثبت‌نام دانش‌آموزان."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in MANAGE_ROLES:
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
        created, skipped, warnings = [], [], []
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
                fixed_time = {ClassSlot.DayType.THURSDAY_MORNING: THURSDAY_MORNING_SLOT, ClassSlot.DayType.THURSDAY_EVENING: THURSDAY_EVENING_SLOT, ClassSlot.DayType.FRIDAY: FRIDAY_SLOT}.get(day_type)
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
                target = ClassSlot.objects.create(
                    term=target_term, number=number, title=source.title, day_type=day_type,
                    time_slot=time_slot, gender=gender, is_online=is_online,
                    meeting_link=str(row.get('meeting_link') or ''), notes=source.notes, capacity=source.capacity, teacher_name=teacher_name,
                    previous_teacher_name=source.teacher_name or '', assigned_level=assigned_level,
                    schedule_kind=schedule_kind, schedule_days=schedule_days,
                    delivery_pattern=delivery_pattern, rotation_group='', current_count=0,
                )
                created.append({'source_id': source.id, 'target': ClassSlotSerializer(target).data})
        return Response({'message': f'{len(created)} کلاس به ترم مقصد منتقل شد', 'created': created, 'skipped': skipped, 'warnings': warnings})


class TermDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE یک ترم — مثلاً برای اصلاح تاریخ شروع/پایان"""
    permission_classes = [IsAuthenticated]
    serializer_class = TermSerializer
    queryset = Term.objects.all()

    def update(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class ClassSlotDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ClassSlotSerializer
    queryset = ClassSlot.objects.all()

    def update(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        # خواسته: توی هر ردیفِ روز+ساعت (مثلاً همه‌ی کلاس‌های زوج ساعت ۳:۴۵ الی ۵:۱۵)، یک استاد
        # فقط می‌تواند همزمان روی یک کلاس باشد — نباید بین چند اتاق در همان روز/ساعت تداخل داشته باشد
        new_teacher = (request.data.get('teacher_name') or '').strip()
        if new_teacher:
            obj = self.get_object()
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
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


THREE_DAY_TYPES = {ClassSlot.DayType.EVEN, ClassSlot.DayType.ODD}
ONE_DAY_TYPES = {ClassSlot.DayType.THURSDAY_MORNING, ClassSlot.DayType.THURSDAY_EVENING, ClassSlot.DayType.FRIDAY}


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
    """جابجایی فیزیکی فقط بین دو کلاس دقیقاً هم‌روز و هم‌ساعت انجام می‌شود."""
    return (
        source.term_id == target.term_id
        and source.number != target.number
        and source.day_type == target.day_type
        and source.time_slot == target.time_slot
        and source.gender == target.gender
        and source.is_online == target.is_online
    )


class SwapClassLocationView(APIView):
    """جابجایی محل دو کلاس سازگار؛ هر رکورد کلاس تمام اطلاعات خودش را حفظ می‌کند."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in MANAGE_ROLES:
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
                    return Response({'error': 'برای جابجایی، کلاس مقصد باید دقیقاً در همان روز، همان ساعت، همان ترم، با جنسیت و حالت برگزاری یکسان باشد'}, status=status.HTTP_400_BAD_REQUEST)
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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


class ClassStatsView(APIView):
    """GET: آمار دقیق لحظه‌ای کلیه‌ی کلاس‌ها — تعداد افراد، مکان‌ها، استاد هر کلاس، تفکیک بر اساس روز"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
                    combos.append((ClassSlot.DayType.FRIDAY, FRIDAY_SLOT, room['friday_gender'], [], [], ''))

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

    def post(self, request, pk):
        if request.user.role not in MANAGE_ROLES:
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
                student = User.objects.get(id=data['student_id'], role='student')
            else:
                student = User.objects.get(national_code=data['national_code'], role='student')
        except User.DoesNotExist:
            return Response({'error': 'دانش‌آموز پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        except User.MultipleObjectsReturned:
            return Response({'error': 'بیش از یک دانش‌آموز با این مشخصات ثبت شده — با مدیر سیستم هماهنگ کنید'}, status=status.HTTP_400_BAD_REQUEST)

        # خواسته‌ی ۱: سطح این کلاس باید با سطح واقعیِ فعلیِ دانش‌آموز (محاسبه‌شده از آخرین
        # ثبت‌نام واقعی یا آخرین تعیین‌سطح — نه فیلد خام و اغلب خالیِ language_level) یکی
        # باشد؛ وگرنه ثبت‌نام مسدود می‌شود (مگر با تایید صریح force_level_mismatch)
        current_info = _compute_level_suggestion(student)
        current_level = current_info['level']
        if slot.assigned_level and current_level and _normalize_level(slot.assigned_level) != _normalize_level(current_level) \
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

        if ClassSlotEnrollment.objects.filter(class_slot=slot, student=student).exists():
            return Response({'error': 'این دانش‌آموز قبلاً توی همین کلاس ثبت‌نام شده'}, status=status.HTTP_400_BAD_REQUEST)

        # خواسته: کد ملی در هر ترم فقط یک ثبت‌نام فعال دارد — اگه همین الان توی یه کلاس دیگه‌ی
        # همین ترم ثبت‌نام فعال داره، اجازه‌ی ثبت‌نام دوم نمی‌دیم (اول باید با «انتقال کلاس» یا
        # حذف/استرداد از کلاس قبلی خارجش کنن). بین ترم‌های مختلف مانعی نیست.
        other_enrollment = ClassSlotEnrollment.objects.filter(
            student=student, class_slot__term=slot.term
        ).exclude(class_slot=slot).select_related('class_slot').first()
        if other_enrollment:
            return Response({
                'error': f"این دانش‌آموز از قبل توی کلاس {other_enrollment.class_slot.number} (سطح {other_enrollment.class_slot.assigned_level or '—'}) در همین ترم ثبت‌نام فعال دارد — برای جابه‌جایی از «انتقال کلاس» استفاده کنید"
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

        return Response({
            'enrollment': ClassSlotEnrollmentSerializer(enrollment).data,
            'slot': ClassSlotSerializer(slot).data,
            'discount_record': DiscountedPersonSerializer(discount_record).data if discount_record else None,
            'wallet_balance': student.wallet_balance,
        }, status=status.HTTP_201_CREATED)


class ClassSlotUnenrollView(APIView):
    """DELETE: حذف یک دانش‌آموز از لیست این کلاس فیزیکی"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk, student_id):
        if request.user.role not in MANAGE_ROLES:
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
        if self.request.user.role not in MANAGE_ROLES:
            return ClassSlotEnrollment.objects.none()
        return ClassSlotEnrollment.objects.filter(class_slot_id=self.kwargs['pk'], payment_verified=True).select_related('student')


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
        if request.user.role not in MANAGE_ROLES:
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
                'level': e.class_slot.assigned_level,
                'class_number': e.class_slot.number,
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        qs = ClassSlotEnrollment.objects.select_related('class_slot', 'student').all()
        level = request.query_params.get('level')
        day_type = request.query_params.get('day_type')
        gender = request.query_params.get('gender')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        if level:
            qs = qs.filter(class_slot__assigned_level=level)
        if day_type:
            qs = qs.filter(class_slot__day_type=day_type)
        if gender:
            qs = qs.filter(class_slot__gender=gender)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        enrollments = []
        by_level = {}
        for e in qs.order_by('-created_at'):
            lvl = e.class_slot.assigned_level or 'نامشخص'
            row = by_level.setdefault(lvl, {'level': lvl, 'count': 0, 'total_tuition': 0, 'discount_count': 0, 'total_discount_amount': 0})
            row['count'] += 1
            row['total_tuition'] += e.tuition_amount
            if e.discount_percent > 0:
                row['discount_count'] += 1
                row['total_discount_amount'] += e.tuition_amount
            enrollments.append({
                'id': e.id, 'student_name': f"{e.student.first_name} {e.student.last_name}",
                'student_national_code': e.student.national_code, 'student_gender': e.student.gender,
                'class_number': e.class_slot.number, 'level': lvl, 'day_type_display': e.class_slot.day_type_display,
                'time_slot': e.class_slot.time_slot, 'gender': e.class_slot.gender, 'gender_display': e.class_slot.gender_display,
                'payment_method_display': e.get_payment_method_display(), 'tuition_amount': e.tuition_amount,
                'discount_percent': e.discount_percent, 'created_at_jalali': e.created_at_jalali,
            })

        return Response({
            'enrollments': enrollments,
            'summary_by_level': sorted(by_level.values(), key=lambda r: r['level']),
            'total_count': len(enrollments),
            'total_tuition': sum(r['tuition_amount'] for r in enrollments),
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

        enrollments = ClassSlotEnrollment.objects.filter(student=student).select_related('class_slot', 'class_slot__term').order_by('-created_at')
        return Response([{
            'id': e.id,
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
        } for e in enrollments])


MAX_LEVELS_NEEDING_RETEST = {'i5', 'teen15', 'teen 15'}  # آخرین سطح کودکان/نوجوانان — عبور از این‌ها همیشه به تعیین‌سطح تازه نیاز دارد


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
        eligible = [c for c in _classes_matching_level(level, student.gender) if c.real_seats_left > 0]

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
        if request.user.role not in MANAGE_ROLES:
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
        if manual_level:
            info['eligible'] = [c for c in _classes_matching_level(manual_level, student.gender) if c.real_seats_left > 0]
            info['level'] = manual_level
            info['age_group'] = infer_age_group_from_level(manual_level)
            setting = TuitionSetting.objects.filter(level=manual_level, age_group=info['age_group']).first()
            info['base_tuition'] = setting.amount if setting else None
            info['needs_retest'] = False
            info['retest_reason'] = ''
            info['source'] = 'manual'

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
            'eligible_classes': ClassSlotSerializer(info['eligible'], many=True).data,
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

    def post(self, request, pk):
        student = request.user
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

        if ClassSlotEnrollment.objects.filter(class_slot=slot, student=student).exists():
            return Response({'error': 'شما قبلاً توی همین کلاس ثبت‌نام کرده‌اید'}, status=status.HTTP_400_BAD_REQUEST)

        other_enrollment = ClassSlotEnrollment.objects.filter(student=student, class_slot__term=slot.term).exclude(class_slot=slot).first()
        if other_enrollment:
            return Response({'error': 'شما از قبل یک ثبت‌نام فعال دیگر در همین ترم دارید — برای تغییر کلاس با مدرسه تماس بگیرید'}, status=status.HTTP_400_BAD_REQUEST)

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

        enrollment = ClassSlotEnrollment.objects.create(
            class_slot=slot, student=student,
            payment_method=payment_method, tuition_amount=tuition_amount, discount_percent=discount_percent,
            receipt_image=receipt, self_enrolled=True, payment_verified=False,
        )

        return Response({
            'message': 'ثبت‌نام شما ثبت شد — بعد از بررسی رسید توسط مدیریت نهایی می‌شود',
            'enrollment': ClassSlotEnrollmentSerializer(enrollment).data,
        }, status=status.HTTP_201_CREATED)


class PendingSelfEnrollmentsView(generics.ListAPIView):
    """
    GET: لیست *همه‌ی* ثبت‌نام‌هایی که خودِ دانش‌آموز از اپ انجام داده و هنوز رسیدش تایید نشده —
    از همه‌ی کلاس‌ها، یک‌جا. مبنای پنجره‌ی هشدار وسط صفحه‌ی مدیریت کلاس‌ها (خواسته‌ی ۱).
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ClassSlotEnrollmentSerializer

    def get_queryset(self):
        if self.request.user.role not in MANAGE_ROLES:
            return ClassSlotEnrollment.objects.none()
        return ClassSlotEnrollment.objects.filter(self_enrolled=True, payment_verified=False).select_related('student', 'class_slot').order_by('created_at')


class RejectPendingEnrollmentView(APIView):
    """POST: مدیر رسید کارت‌به‌کارتِ یک ثبت‌نامِ در-انتظار را نامعتبر تشخیص می‌دهد و ثبت‌نام حذف می‌شود"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            enrollment = ClassSlotEnrollment.objects.get(class_slot_id=pk, student_id=student_id)
        except ClassSlotEnrollment.DoesNotExist:
            return Response({'error': 'ثبت‌نام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        enrollment.payment_verified = True
        enrollment.save(update_fields=['payment_verified'])
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
        if self.request.user.role not in MANAGE_ROLES:
            return LevelRenewalApproval.objects.none()
        qs = LevelRenewalApproval.objects.select_related('student', 'requested_by', 'reviewed_by').all()
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def create(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if self.request.user.role not in MANAGE_ROLES:
            return TuitionSetting.objects.none()
        return TuitionSetting.objects.all()

    def create(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class DiscountedPersonListView(generics.ListAPIView):
    """GET: لیست «افراد دارای تخفیف» — خودکار از روی ثبت‌نام‌های دارای تخفیف (کلاس ترمیک یا دوره‌ی آنلاین) ساخته می‌شود"""
    permission_classes = [IsAuthenticated]
    serializer_class = DiscountedPersonSerializer

    def get_queryset(self):
        if self.request.user.role not in MANAGE_ROLES:
            return DiscountedPerson.objects.none()
        return DiscountedPerson.objects.select_related('student', 'class_slot', 'online_course').all()


class DiscountedPersonDetailView(generics.RetrieveUpdateDestroyAPIView):
    """PATCH/DELETE — برای ویرایش درصد تخفیفِ رکوردهای خودکارساخته‌شده از صفحه‌ی «افراد دارای تخفیف»"""
    permission_classes = [IsAuthenticated]
    serializer_class = DiscountedPersonSerializer
    queryset = DiscountedPerson.objects.all()

    def update(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class RefundEnrollmentView(APIView):
    """
    POST: دکمه‌ی «استرداد» — شهریه‌ی پرداختی به شخص برگردانده می‌شود؛ تاریخ/ساعت خودکار ثبت
    می‌شود، شماره کارت و نام گیرنده از فرم گرفته می‌شود، و دانش‌آموز از لیست کلاس حذف می‌شود.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if request.user.role not in MANAGE_ROLES:
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
    """GET: لیست کلاس‌های هم‌سطح و هم‌جنسیت (به‌جز خودِ همین کلاس) برای دکمه‌ی «انتقال کلاس»"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, student_id):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            slot = ClassSlot.objects.get(pk=pk)
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        candidates = ClassSlot.objects.exclude(pk=slot.pk).filter(assigned_level=slot.assigned_level)
        if slot.gender != ClassSlot.Gender.MIXED:
            candidates = candidates.filter(gender__in=[slot.gender, ClassSlot.Gender.MIXED])
        candidates = [c for c in candidates if c.real_seats_left > 0]

        return Response([{
            'id': c.id, 'number': c.number, 'day_type_display': c.day_type_display,
            'time_slot': c.time_slot, 'teacher_name': c.teacher_name, 'seats_left': c.real_seats_left,
        } for c in candidates])


class TransferEnrollmentView(APIView):
    """POST: دکمه‌ی «انتقال کلاس» — دانش‌آموز از کلاس فعلی حذف و به کلاس مقصدِ انتخاب‌شده منتقل می‌شود"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            source = ClassSlot.objects.get(pk=pk)
            enrollment = ClassSlotEnrollment.objects.get(class_slot=source, student_id=student_id)
        except (ClassSlot.DoesNotExist, ClassSlotEnrollment.DoesNotExist):
            return Response({'error': 'ثبت‌نام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        serializer = TransferEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            target = ClassSlot.objects.get(pk=serializer.validated_data['target_slot_id'])
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس مقصد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        if target.pk == source.pk:
            return Response({'error': 'کلاس مقصد نمی‌تواند همان کلاس فعلی باشد'}, status=status.HTTP_400_BAD_REQUEST)
        if target.real_seats_left <= 0:
            return Response({'error': 'کلاس مقصد ظرفیت خالی ندارد'}, status=status.HTTP_400_BAD_REQUEST)
        if ClassSlotEnrollment.objects.filter(class_slot=target, student_id=student_id).exists():
            return Response({'error': 'این دانش‌آموز از قبل توی کلاس مقصد ثبت‌نام شده'}, status=status.HTTP_400_BAD_REQUEST)

        ClassSlotEnrollment.objects.create(
            class_slot=target, student_id=student_id,
            payment_method=enrollment.payment_method, tuition_amount=enrollment.tuition_amount,
            discount_percent=enrollment.discount_percent, pos_reference_code=enrollment.pos_reference_code,
        )
        enrollment.delete()
        if not target.assigned_level:
            target.assigned_level = source.assigned_level
            target.save()

        return Response({
            'message': f'دانش‌آموز به کلاس {target.number} منتقل شد',
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
        if request.user.role not in MANAGE_ROLES:
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

    def post(self, request, pk):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            source = ClassSlot.objects.get(pk=pk)
        except ClassSlot.DoesNotExist:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        serializer = SplitClassSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        enrollments = list(ClassSlotEnrollment.objects.filter(class_slot=source).select_related('student'))
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

        # اول دنبال یک کلاس هم‌سطح/هم‌جنسیت/هم‌روز که هنوز هیچ ثبت‌نام واقعی ندارد بگرد
        target = (
            ClassSlot.objects.exclude(pk=source.pk)
            .filter(assigned_level=source.assigned_level, gender=source.gender, day_type=source.day_type)
            .annotate(real_count=Count('enrollments'))
            .filter(real_count=0)
            .order_by('number')
            .first()
        )
        if not target:
            next_number = (ClassSlot.objects.aggregate(m=Max('number'))['m'] or 0) + 1
            target = ClassSlot.objects.create(
                number=next_number, day_type=source.day_type, time_slot=source.time_slot,
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
        if request.user.role not in MANAGE_ROLES:
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

        today = timezone.now().date()
        term = Term.objects.filter(start_date__lte=today, end_date__gte=today).order_by('-start_date').first()
        if not term:
            term = Term.objects.order_by('-year', '-term_number').first()
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
        if self.request.user.role not in MANAGE_ROLES:
            return OnlineCourse.objects.none()
        return OnlineCourse.objects.all()

    def create(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
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
        if request.user.role not in MANAGE_ROLES:
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
        if self.request.user.role not in MANAGE_ROLES:
            return OnlineCourseEnrollment.objects.none()
        return OnlineCourseEnrollment.objects.filter(self_enrolled=True, payment_verified=False).select_related('student', 'course').order_by('created_at')


class VerifyOnlineCourseEnrollmentPaymentView(APIView):
    """POST: تایید رسید یک ثبت‌نام دوره"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, student_id):
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if self.request.user.role not in MANAGE_ROLES:
            return OnlineCourseEnrollment.objects.none()
        return OnlineCourseEnrollment.objects.filter(course_id=self.kwargs['pk'], payment_verified=True).select_related('student')


class OnlineCourseUnenrollView(APIView):
    """DELETE: دکمه‌ی «حذف» — دانش‌آموز بدون استرداد یا انتقالِ وجه از دوره حذف می‌شود (مثلاً ثبت‌نام اشتباه)"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk, student_id):
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if self.request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        obj = PaymentSettings.get_solo()
        serializer = PaymentSettingsSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ==================== حضور و غیاب آنلاین توسط استاد ====================

class MarkAttendanceView(APIView):
    """
    POST: استاد (یا مدیر) حضور/غیاب یک دانش‌آموز را برای یک تاریخ مشخص، در یک کلاس ترمیک یا
    دوره‌ی علمی ثبت/ویرایش می‌کند. اگر برای همون دانش‌آموز/تاریخ قبلاً رکوردی بود، آپدیت می‌شود
    (یعنی کاملاً قابل ویرایش است، نه فقط یک‌بار ثبت).
    بدنه‌ی درخواست: class_slot یا online_course (یکی از این دو الزامی)، student, date (YYYY-MM-DD میلادی)، is_present, note
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if request.user.role not in MANAGE_ROLES and request.user.role not in User.TEACHER_LIKE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        class_slot_id = request.data.get('class_slot')
        online_course_id = request.data.get('online_course')
        student_id = request.data.get('student')
        date_str = request.data.get('date')
        is_present = request.data.get('is_present', True)
        note = request.data.get('note', '')

        if not student_id or not date_str or (not class_slot_id and not online_course_id):
            return Response({'error': 'student، date، و یکی از class_slot/online_course الزامی است'}, status=status.HTTP_400_BAD_REQUEST)

        # اگه استاد (نه مدیر) درخواست داده، فقط اجازه داره برای کلاس‌های خودش ثبت کنه
        if request.user.role in User.TEACHER_LIKE_ROLES and request.user.role not in MANAGE_ROLES:
            teacher_full_name = request.user.get_full_name().strip()
            if class_slot_id:
                owns = ClassSlot.objects.filter(pk=class_slot_id, teacher_name__iexact=teacher_full_name).exists()
            else:
                owns = OnlineCourse.objects.filter(pk=online_course_id, teacher_name__iexact=teacher_full_name).exists()
            if not owns:
                return Response({'error': 'این کلاس/دوره متعلق به شما نیست'}, status=status.HTTP_403_FORBIDDEN)

        lookup = {'student_id': student_id, 'date': date_str}
        if class_slot_id:
            lookup['class_slot_id'] = class_slot_id
        else:
            lookup['online_course_id'] = online_course_id

        attendance, _created = ClassAttendance.objects.update_or_create(
            **lookup, defaults={'is_present': is_present, 'note': note, 'marked_by': request.user},
        )
        return Response(ClassAttendanceSerializer(attendance).data)


class ClassAttendanceListView(generics.ListAPIView):
    """GET: لیست حضور و غیاب یک کلاس ترمیک یا دوره‌ی علمی — با ?class_slot=<id> یا ?online_course=<id>، اختیاری ?date=<YYYY-MM-DD>"""
    permission_classes = [IsAuthenticated]
    serializer_class = ClassAttendanceSerializer

    def get_queryset(self):
        qs = ClassAttendance.objects.select_related('student')
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


def _scheduled_session_dates(slot):
    """محاسبه تاریخ‌های واقعی ۱۵ جلسه از بازه ترم؛ تاریخ‌ها به‌صورت ISO برای frontend ارسال می‌شوند."""
    if not slot.term_id or not slot.term or not slot.term.start_date or not slot.term.end_date:
        return []
    day_type = str(slot.day_type or '').lower()
    if day_type == ClassSlot.DayType.EVEN:
        weekdays = {5, 0, 2}  # شنبه، دوشنبه، چهارشنبه در datetime.weekday()
    elif day_type == ClassSlot.DayType.ODD:
        weekdays = {6, 1, 3}  # یکشنبه، سه‌شنبه، پنجشنبه
    elif day_type in (ClassSlot.DayType.THURSDAY_MORNING, ClassSlot.DayType.THURSDAY_EVENING):
        weekdays = {3}
    elif day_type == ClassSlot.DayType.FRIDAY:
        weekdays = {4}
    elif day_type == ClassSlot.DayType.TWO_DAY:
        day_map = {'شنبه': 5, 'یکشنبه': 6, 'دوشنبه': 0, 'سه‌شنبه': 1, 'چهارشنبه': 2, 'پنجشنبه': 3, 'جمعه': 4}
        weekdays = {day_map.get(str(value).strip()) for value in (slot.schedule_days or [])}
        weekdays.discard(None)
    else:
        return []
    result = []
    cursor = slot.term.start_date
    while cursor <= slot.term.end_date and len(result) < 15:
        if cursor.weekday() in weekdays:
            repeats = 3 if day_type in (ClassSlot.DayType.THURSDAY_MORNING, ClassSlot.DayType.THURSDAY_EVENING) else 1
            for _ in range(repeats):
                if len(result) >= 15:
                    break
                result.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return result


def _past_scheduled_session_count(slot):
    count = 0
    today = timezone.localtime().date()
    for value in _scheduled_session_dates(slot):
        try:
            session_date = datetime.fromisoformat(str(value)).date()
        except (TypeError, ValueError):
            continue
        if session_date <= today:
            count += 1
    return count


def _teacher_report_payload(slot, events):
    approved = [e for e in events if TeacherSessionEvent is not None and e.status == TeacherSessionEvent.ApprovalStatus.APPROVED]
    source = slot.teacher_name or ''
    substitution_count = sum(1 for e in approved if e.event_type == TeacherSessionEvent.EventType.SUBSTITUTION)
    absence_count = sum(1 for e in approved if e.event_type == TeacherSessionEvent.EventType.ABSENCE)
    makeup_count = sum(1 for e in approved if e.event_type == TeacherSessionEvent.EventType.MAKEUP)
    repaired_absence_count = min(absence_count, makeup_count)
    remaining_absence_count = max(0, absence_count - repaired_absence_count)
    source_count = max(0, 15 - substitution_count - remaining_absence_count)
    replacement_counts = {}
    status_rows = []
    for e in approved:
        if e.event_type == TeacherSessionEvent.EventType.SUBSTITUTION:
            replacement_counts[e.replacement_teacher_name] = replacement_counts.get(e.replacement_teacher_name, 0) + 1
            status_rows.append({'id': e.id, 'session_number': e.session_number, 'date': e.class_date_jalali, 'status': 'substitution', 'label': 'ساب', 'teacher': e.replacement_teacher_name})
        elif e.event_type == TeacherSessionEvent.EventType.ABSENCE:
            status_rows.append({'id': e.id, 'session_number': e.session_number, 'date': e.class_date_jalali, 'status': 'absence', 'label': 'غیبت/کنسلی', 'teacher': source})
        elif e.event_type == TeacherSessionEvent.EventType.MAKEUP:
            status_rows.append({'id': e.id, 'session_number': e.session_number, 'date': e.class_date_jalali, 'status': 'makeup', 'label': 'جبرانی', 'teacher': source})
    participants = [{'teacher_name': source, 'role': 'استاد اصلی', 'scheduled_sessions': 15, 'effective_sessions': source_count}]
    for name, count in sorted(replacement_counts.items()):
        if name:
            participants.append({'teacher_name': name, 'role': 'استاد پذیرنده ساب', 'scheduled_sessions': 0, 'effective_sessions': count})
    return {
        'class_slot': slot.id, 'class_number': slot.number, 'class_title': slot.title,
        'teacher_name': source, 'day_type': slot.day_type, 'day_type_display': slot.get_day_type_display(),
        'time_slot': slot.time_slot, 'gender': slot.gender, 'gender_display': slot.get_gender_display(),
        'level': slot.assigned_level, 'capacity': slot.capacity, 'total_sessions': 15,
        'term_start_date': slot.term.start_date.isoformat() if slot.term_id and slot.term and slot.term.start_date else '',
        'term_end_date': slot.term.end_date.isoformat() if slot.term_id and slot.term and slot.term.end_date else '',
        'session_dates': _scheduled_session_dates(slot),
        'held_sessions': max(0, _past_scheduled_session_count(slot) - remaining_absence_count),
        'substitution_count': substitution_count, 'absence_count': absence_count, 'makeup_count': makeup_count,
        'repaired_absence_count': repaired_absence_count, 'remaining_absence_count': remaining_absence_count,
        'participants': participants, 'session_statuses': status_rows,
    }


def _teacher_compensation_setting(teacher):
    try:
        return teacher.teacher_compensation_setting
    except (AttributeError, TeacherCompensationSetting.DoesNotExist):
        return None


def _teacher_attendance_data(record):
    setting = _teacher_compensation_setting(record.teacher)
    multiplier = 1.0
    if setting:
        if record.class_slot.day_type == ClassSlot.DayType.FRIDAY: multiplier = float(setting.friday_multiplier)
        elif record.class_slot.day_type in (ClassSlot.DayType.THURSDAY_MORNING, ClassSlot.DayType.THURSDAY_EVENING): multiplier = float(setting.thursday_multiplier)
    base = (setting.session_price if setting and record.check_out_at else 0) * multiplier
    allowed = max(1, int(setting.allowed_minutes_per_session)) if setting else 90
    rate = (int(setting.adjustment_per_minute) if setting and setting.adjustment_per_minute else ((setting.session_price / allowed) if setting else 0)) * multiplier
    shortage = max(0, allowed - record.minutes_worked) if setting and record.check_out_at else 0
    overtime = max(0, record.minutes_worked - allowed) if setting and record.check_out_at else 0
    gross = round(base + (overtime * rate) - (shortage * rate))
    insurance = setting.insurance_deduction if setting and record.check_out_at else 0
    return {
        'id': record.id, 'class_slot': record.class_slot_id, 'class_number': record.class_slot.number,
        'teacher': record.teacher_id, 'teacher_name': record.teacher.get_full_name(),
        'day_type': record.class_slot.day_type, 'day_type_display': record.class_slot.get_day_type_display(),
        'time_slot': record.class_slot.time_slot, 'gender': record.class_slot.get_gender_display(),
        'level': record.class_slot.assigned_level, 'class_date': record.class_date,
        'session_number': record.session_number, 'check_in_at': record.check_in_at,
        'check_out_at': record.check_out_at, 'minutes_worked': record.minutes_worked,
        'status': record.status, 'notes': record.notes,
        'session_price': setting.session_price if setting else 0, 'multiplier': multiplier,
        'allowed_minutes': allowed, 'shortage_minutes': shortage, 'overtime_minutes': overtime,
        'gross_amount': gross, 'insurance_deduction': insurance, 'net_amount': max(0, gross - insurance),
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


class RoomQrManageView(APIView):
    """مدیریت QR محل کلاس؛ فقط مدیر/اداری/مدیرآموزش."""
    permission_classes = [IsAuthenticated]

    def _allowed(self, request): return request.user.role in MANAGE_ROLES

    def get(self, request, pk):
        if not self._allowed(request): return Response({'error': 'دسترسی ندارید'}, status=403)
        slot = get_object_or_404(ClassSlot, pk=pk)
        qr, _ = RoomQrToken.objects.get_or_create(class_slot=slot)
        return Response({'class_slot': slot.id, 'token': qr.token, 'payload': f'LSCHOOL-ROOM:{slot.id}:{qr.token}', 'is_active': qr.is_active, 'latitude': qr.latitude, 'longitude': qr.longitude, 'allowed_radius_m': qr.allowed_radius_m})

    def post(self, request, pk):
        if not self._allowed(request): return Response({'error': 'دسترسی ندارید'}, status=403)
        slot = get_object_or_404(ClassSlot, pk=pk)
        qr, _ = RoomQrToken.objects.get_or_create(class_slot=slot)
        if request.data.get('action') == 'rotate': qr.rotate()
        if 'is_active' in request.data: qr.is_active = bool(request.data.get('is_active'))
        if 'latitude' in request.data: qr.latitude = request.data.get('latitude') or None
        if 'longitude' in request.data: qr.longitude = request.data.get('longitude') or None
        if 'allowed_radius_m' in request.data: qr.allowed_radius_m = max(20, min(1000, int(request.data.get('allowed_radius_m'))))
        qr.save()
        return Response({'class_slot': slot.id, 'token': qr.token, 'payload': f'LSCHOOL-ROOM:{slot.id}:{qr.token}', 'is_active': qr.is_active, 'latitude': qr.latitude, 'longitude': qr.longitude, 'allowed_radius_m': qr.allowed_radius_m})


class TeacherQrAttendanceView(APIView):
    """ثبت ورود/خروج استاد با توکن QR و موقعیت مکانی؛ گالری هیچ نقشی ندارد چون payload فقط از دوربین اپ دریافت می‌شود."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if request.user.role not in User.TEACHER_LIKE_ROLES and request.user.role not in MANAGE_ROLES:
            return Response({'error': 'این بخش فقط برای استاد یا مدیر است'}, status=403)
        raw = str(request.data.get('qr_token') or '').strip()
        parts = raw.split(':')
        token = parts[-1] if len(parts) >= 3 and parts[0] == 'LSCHOOL-ROOM' else raw
        qr = RoomQrToken.objects.select_related('class_slot').filter(token=token, is_active=True).first()
        if not qr: return Response({'error': 'QR نامعتبر، غیرفعال یا متعلق به محل دیگری است'}, status=400)
        slot = qr.class_slot
        today = timezone.localtime().date()
        class_date = request.data.get('class_date') or today.isoformat()
        if request.user.role not in MANAGE_ROLES and str(class_date) != today.isoformat():
            return Response({'error': 'ثبت حضور فقط برای جلسه امروز مجاز است'}, status=400)
        try: session_number = int(request.data.get('session_number', 1))
        except (TypeError, ValueError): session_number = 0
        if not 1 <= session_number <= 15: return Response({'error': 'شماره جلسه باید بین ۱ تا ۱۵ باشد'}, status=400)
        teacher_name = request.user.get_full_name().strip()
        if request.user.role in User.TEACHER_LIKE_ROLES:
            owns = slot.teacher_name.strip().casefold() == teacher_name.casefold()
            replacement = TeacherSessionEvent.objects.filter(term=slot.term, class_slot=slot, class_date=class_date, session_number=session_number, event_type=TeacherSessionEvent.EventType.SUBSTITUTION, status=TeacherSessionEvent.ApprovalStatus.APPROVED, replacement_teacher_name__iexact=teacher_name).exists()
            if replacement: return Response({'error': 'برای این جلسه ساب تایید شده ثبت شده است؛ QR استاد اصلی نباید ثبت شود'}, status=400)
            if not owns: return Response({'error': 'این QR برای کلاس‌های شما نیست'}, status=403)
        if TeacherSessionEvent.objects.filter(term=slot.term, class_slot=slot, class_date=class_date, session_number=session_number, event_type=TeacherSessionEvent.EventType.ABSENCE, status=TeacherSessionEvent.ApprovalStatus.APPROVED).exists():
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
        if request.user.role not in MANAGE_ROLES: return Response({'error': 'فقط مدیر می‌تواند گزارش حضور استادان را ببیند'}, status=403)
        if TeacherSessionAttendance is None:
            return Response({'records': []})
        qs = TeacherSessionAttendance.objects.select_related('class_slot', 'teacher').all()
        if request.query_params.get('term'): qs = qs.filter(class_slot__term_id=request.query_params['term'])
        if request.query_params.get('teacher'): qs = qs.filter(teacher_id=request.query_params['teacher'])
        if request.query_params.get('class_slot'): qs = qs.filter(class_slot_id=request.query_params['class_slot'])
        records = [_teacher_attendance_data(x) for x in qs]
        totals = {}
        for row in records:
            key = str(row['teacher'])
            bucket = totals.setdefault(key, {'teacher': row['teacher'], 'teacher_name': row['teacher_name'], 'sessions': 0, 'minutes': 0, 'gross_amount': 0, 'insurance_deduction': 0, 'net_amount': 0})
            bucket['sessions'] += 1; bucket['minutes'] += row['minutes_worked']; bucket['gross_amount'] += row['gross_amount']; bucket['insurance_deduction'] += row['insurance_deduction']; bucket['net_amount'] += row['net_amount']
        return Response({'records': records, 'totals': list(totals.values())})


class TeacherCompensationSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def _allowed(self, request): return request.user.role in MANAGE_ROLES

    def get(self, request):
        if not self._allowed(request): return Response({'error': 'فقط مدیر می‌تواند تنظیمات دستمزد استادان را ببیند'}, status=403)
        qs = TeacherCompensationSetting.objects.select_related('teacher').all()
        if request.query_params.get('teacher_id'): qs = qs.filter(teacher_id=request.query_params['teacher_id'])
        return Response({'settings': [{'id': x.id, 'teacher_id': x.teacher_id, 'teacher_name': x.teacher.get_full_name(), 'session_price': x.session_price, 'thursday_multiplier': x.thursday_multiplier, 'friday_multiplier': x.friday_multiplier, 'insurance_deduction': x.insurance_deduction, 'allowed_minutes_per_session': x.allowed_minutes_per_session, 'adjustment_per_minute': x.adjustment_per_minute} for x in qs]})

    def post(self, request):
        if not self._allowed(request): return Response({'error': 'فقط مدیر می‌تواند تنظیمات دستمزد را تغییر دهد'}, status=403)
        teacher_id = request.data.get('teacher_id')
        if not teacher_id: return Response({'error': 'استاد الزامی است'}, status=400)
        from django.contrib.auth import get_user_model
        teacher = get_user_model().objects.filter(pk=teacher_id, role__in=get_user_model().TEACHER_LIKE_ROLES).first()
        if not teacher: return Response({'error': 'استاد معتبر پیدا نشد'}, status=400)
        obj, _ = TeacherCompensationSetting.objects.get_or_create(teacher=teacher)
        for field in ('session_price', 'thursday_multiplier', 'friday_multiplier', 'insurance_deduction', 'allowed_minutes_per_session', 'adjustment_per_minute'):
            if field in request.data: setattr(obj, field, request.data[field])
        obj.save()
        return Response({'id': obj.id, 'teacher_id': teacher.id, 'teacher_name': teacher.get_full_name(), 'session_price': obj.session_price, 'thursday_multiplier': obj.thursday_multiplier, 'friday_multiplier': obj.friday_multiplier, 'insurance_deduction': obj.insurance_deduction, 'allowed_minutes_per_session': obj.allowed_minutes_per_session, 'adjustment_per_minute': obj.adjustment_per_minute})


def _teacher_event_pay_row(event, teacher):
    slot = event.class_slot
    setting = _teacher_compensation_setting(teacher)
    price = int(setting.session_price) if setting else 0
    multiplier = 1.0
    if setting and slot.day_type == ClassSlot.DayType.FRIDAY:
        multiplier = float(setting.friday_multiplier)
    elif setting and slot.day_type in (ClassSlot.DayType.THURSDAY_MORNING, ClassSlot.DayType.THURSDAY_EVENING):
        multiplier = float(setting.thursday_multiplier)
    is_absence = event.event_type == TeacherSessionEvent.EventType.ABSENCE
    amount = 0 if is_absence else round(price * multiplier)
    return {'id': f'event-{event.id}', 'class_slot': slot.id, 'class_number': slot.number, 'teacher': teacher.id, 'teacher_name': teacher.get_full_name(), 'day_type': slot.day_type, 'day_type_display': slot.get_day_type_display(), 'time_slot': slot.time_slot, 'gender': slot.get_gender_display(), 'level': slot.assigned_level, 'class_date': event.class_date, 'session_number': event.session_number, 'check_in_at': None, 'check_out_at': None, 'minutes_worked': 0, 'status': 'absence' if is_absence else ('substitution' if event.event_type == TeacherSessionEvent.EventType.SUBSTITUTION else 'makeup'), 'status_display': event.get_event_type_display() + ' تاییدشده', 'session_price': price, 'multiplier': multiplier, 'allowed_minutes': setting.allowed_minutes_per_session if setting else 90, 'shortage_minutes': 0, 'overtime_minutes': 0, 'gross_amount': amount, 'insurance_deduction': 0, 'net_amount': amount, 'source': 'event', 'amount_note': 'بدون پرداخت' if is_absence else 'بر اساس رویداد تاییدشده'}


class TeacherCompensationReportView(APIView):
    """فیش محاسباتی استادان؛ فقط گزارش تولید می‌کند و داده خام را تغییر نمی‌دهد."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'فقط مدیر، مدیر آموزش یا اداری می‌تواند فیش استادان را ببیند'}, status=403)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        teacher_id = request.query_params.get('teacher_id') or request.query_params.get('teacher')
        teachers_qs = User.objects.filter(role__in=User.TEACHER_LIKE_ROLES).order_by('first_name', 'last_name')
        if teacher_id and str(teacher_id).isdigit():
            teachers_qs = teachers_qs.filter(pk=int(teacher_id))
        term = str(request.query_params.get('term') or 'all').lower()
        slots = ClassSlot.objects.filter(term_id=int(term)) if term.isdigit() else ClassSlot.objects.all()
        events = TeacherSessionEvent.objects.filter(term_id=int(term), status=TeacherSessionEvent.ApprovalStatus.APPROVED) if TeacherSessionEvent is not None and term.isdigit() else (TeacherSessionEvent.objects.filter(status=TeacherSessionEvent.ApprovalStatus.APPROVED) if TeacherSessionEvent is not None else [])
        attendance = TeacherSessionAttendance.objects.filter(class_slot__term_id=int(term)) if TeacherSessionAttendance is not None and term.isdigit() else (TeacherSessionAttendance.objects.all() if TeacherSessionAttendance is not None else [])
        slots = list(slots); events = list(events); attendance = list(attendance)
        totals, records = [], []
        for teacher in teachers_qs:
            name = teacher.get_full_name().strip()
            own_class_count = sum(1 for slot in slots if (slot.teacher_name or '').strip().casefold() == name.casefold())
            rows = []
            for record in attendance:
                if record.teacher_id == teacher.id:
                    row = _teacher_attendance_data(record)
                    row.update({'source': 'qr', 'status_display': 'حضور با QR', 'amount_note': 'محاسبه بر اساس ورود و خروج'})
                    rows.append(row)
            for event in events:
                requested = (event.requested_teacher_name or '').strip().casefold()
                replacement = (event.replacement_teacher_name or '').strip().casefold()
                if (event.event_type == TeacherSessionEvent.EventType.SUBSTITUTION and replacement == name.casefold()) or (event.event_type in (TeacherSessionEvent.EventType.ABSENCE, TeacherSessionEvent.EventType.MAKEUP) and requested == name.casefold()):
                    rows.append(_teacher_event_pay_row(event, teacher))
            rows.sort(key=lambda row: (str(row.get('class_date') or ''), int(row.get('session_number') or 0)))
            gross = sum(int(row.get('gross_amount') or 0) for row in rows)
            insurance = sum(int(row.get('insurance_deduction') or 0) for row in rows)
            totals.append({'teacher': teacher.id, 'teacher_name': name, 'class_count': own_class_count, 'record_count': len(rows), 'minutes_worked': sum(int(row.get('minutes_worked') or 0) for row in rows), 'shortage_minutes': sum(int(row.get('shortage_minutes') or 0) for row in rows), 'overtime_minutes': sum(int(row.get('overtime_minutes') or 0) for row in rows), 'gross_amount': gross, 'insurance_deduction': insurance, 'net_amount': max(0, gross - insurance)})
            records.extend(rows)
        return Response({'term': term, 'teachers': [{'id': teacher.id, 'name': teacher.get_full_name()} for teacher in teachers_qs], 'records': records, 'totals': totals})


class TeacherTermReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES: return Response({'error': 'دسترسی ندارید'}, status=403)
        deleted, _ = TeacherSessionEvent.objects.filter(pk=pk).delete()
        return Response(status=204 if deleted else 404)

    def post(self, request, pk):
        if request.user.role not in MANAGE_ROLES: return Response({'error': 'دسترسی ندارید'}, status=403)
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
        if request.user.role not in MANAGE_ROLES:
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
