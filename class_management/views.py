from django.utils import timezone
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
import jdatetime
from .models import ClassSlot
from .serializers import (
    ClassSlotSerializer, AllocateClassesSerializer, ConfirmOverflowSerializer,
    TransferSurplusSerializer, SpinOffSurplusSerializer,
)
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
