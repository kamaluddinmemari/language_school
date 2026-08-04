from django.utils import timezone
import random
from django.db import models as django_models
from django.db.models import Count, Max, Q
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
import jdatetime
from .models import ClassSlot, ClassSlotEnrollment, TuitionSetting, DiscountedPerson, EnrollmentRefund, WalletTransaction, infer_age_group_from_level, _jalali, LevelRenewalApproval
from .models import THREE_DAY_TIME_SLOTS, THURSDAY_MORNING_SLOT, THURSDAY_EVENING_SLOT, FRIDAY_SLOT
from .serializers import (
    ClassSlotSerializer, AllocateClassesSerializer, ConfirmOverflowSerializer,
    TransferSurplusSerializer, SpinOffSurplusSerializer,
    BulkCreatePhysicalClassesSerializer, EnrollStudentSerializer, ClassSlotEnrollmentSerializer,
    TuitionSettingSerializer, DiscountedPersonSerializer, RefundEnrollmentSerializer, TransferEnrollmentSerializer,
    SplitClassSerializer, LevelRenewalApprovalSerializer,
)
from level_tests.models import LevelTest
from .allocation import allocate_classes

MANAGE_ROLES = ('admin', 'evaluator', 'office')


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
        return ClassSlot.objects.all()

    def create(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class ClassSlotDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ClassSlotSerializer
    queryset = ClassSlot.objects.all()

    def update(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


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

        created, skipped = [], []
        for room in rooms:
            number = room['number']
            capacity = room['capacity']

            combos = []
            for slot in THREE_DAY_TIME_SLOTS:
                combos.append((ClassSlot.DayType.EVEN, slot, ClassSlot.Gender.GIRLS))
            for slot in THREE_DAY_TIME_SLOTS:
                combos.append((ClassSlot.DayType.ODD, slot, ClassSlot.Gender.BOYS))
            combos.append((ClassSlot.DayType.THURSDAY_MORNING, THURSDAY_MORNING_SLOT, room['thursday_morning_gender']))
            combos.append((ClassSlot.DayType.THURSDAY_EVENING, THURSDAY_EVENING_SLOT, room['thursday_evening_gender']))
            combos.append((ClassSlot.DayType.FRIDAY, FRIDAY_SLOT, room['friday_gender']))

            for day_type, time_slot, gender in combos:
                obj, was_created = ClassSlot.objects.get_or_create(
                    number=number, day_type=day_type, time_slot=time_slot,
                    defaults={'capacity': capacity, 'gender': gender},
                )
                if was_created:
                    created.append(obj.id)
                else:
                    skipped.append(obj.id)

        slots = ClassSlot.objects.all().order_by('number')
        return Response({
            'created_count': len(created),
            'skipped_count': len(skipped),
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

        if slot.assigned_level and student.language_level and slot.assigned_level != student.language_level:
            return Response({
                'error': f"سطح این دانش‌آموز ({student.language_level}) با سطح این کلاس ({slot.assigned_level}) یکی نیست"
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

        # خواسته‌ی ۲: کد ملی یکتاست — اگه همین الان توی یه کلاس دیگه ثبت‌نام فعال داره، اجازه‌ی
        # ثبت‌نام دوم نمی‌دیم (اول باید با «انتقال کلاس» یا حذف/استرداد از کلاس قبلی خارجش کنن)
        other_enrollment = ClassSlotEnrollment.objects.filter(student=student).exclude(class_slot=slot).select_related('class_slot').first()
        if other_enrollment:
            return Response({
                'error': f"این دانش‌آموز از قبل توی کلاس {other_enrollment.class_slot.number} (سطح {other_enrollment.class_slot.assigned_level or '—'}) ثبت‌نام فعال دارد — برای جابه‌جایی از «انتقال کلاس» استفاده کنید"
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
    GET: سوابق آموزشیِ دانش‌آموز — سطح فعلی (همیشه به‌روز، از همون منطق تخصیص خودکار سطح)
    + تاریخچه‌ی کامل ثبت‌نام‌های ترمیک (سطح، روش ثبت‌نام، تاریخ شمسی).
    ⚠️ سوابق کلاس‌های خصوصی/گروهی/ورکشاپ اینجا نیست — آن‌ها توی اپ‌های دیگری (classes,
    group_classes) هستند که این بخش بهشون دسترسی نداره.
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

        enrollments = ClassSlotEnrollment.objects.filter(student=student).select_related('class_slot').order_by('-created_at')
        return Response([{
            'id': e.id,
            'class_number': e.class_slot.number,
            'level': e.class_slot.assigned_level,
            'teacher_name': e.class_slot.teacher_name,
            'day_type_display': e.class_slot.day_type_display,
            'time_slot': e.class_slot.time_slot,
            'gender_display': e.class_slot.get_gender_display(),
            'tuition_amount': e.tuition_amount,
            'discount_percent': e.discount_percent,
            'payment_method_display': e.get_payment_method_display(),
            'self_enrolled': e.self_enrolled,
            'payment_verified': e.payment_verified,
            'created_at_jalali': e.created_at_jalali,
        } for e in enrollments])


MAX_LEVELS_NEEDING_RETEST = {'i5', 'teen15', 'teen 15'}  # آخرین سطح کودکان/نوجوانان — عبور از این‌ها همیشه به تعیین‌سطح تازه نیاز دارد


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
        candidates = ClassSlot.objects.filter(assigned_level=level)
        if student.gender:
            candidates = candidates.filter(Q(gender=student.gender) | Q(gender=ClassSlot.Gender.MIXED))
        eligible = [c for c in candidates if c.real_seats_left > 0]

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
            candidates = ClassSlot.objects.filter(assigned_level=manual_level)
            if student.gender:
                candidates = candidates.filter(Q(gender=student.gender) | Q(gender=ClassSlot.Gender.MIXED))
            info['eligible'] = [c for c in candidates if c.real_seats_left > 0]
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

        other_enrollment = ClassSlotEnrollment.objects.filter(student=student).exclude(class_slot=slot).first()
        if other_enrollment:
            return Response({'error': 'شما از قبل یک ثبت‌نام فعال دیگر دارید — برای تغییر کلاس با مدرسه تماس بگیرید'}, status=status.HTTP_400_BAD_REQUEST)

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
    """GET: لیست «افراد دارای تخفیف» — خودکار از روی ثبت‌نام‌های دارای تخفیف ساخته می‌شود"""
    permission_classes = [IsAuthenticated]
    serializer_class = DiscountedPersonSerializer

    def get_queryset(self):
        if self.request.user.role not in MANAGE_ROLES:
            return DiscountedPerson.objects.none()
        return DiscountedPerson.objects.select_related('student', 'class_slot').all()


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
