from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import ClassSlot
from .serializers import ClassSlotSerializer, AllocateClassesSerializer
from .allocation import allocate_classes
from .auto_schedule import auto_schedule_times

MANAGE_ROLES = ('admin', 'evaluator')


class ClassSlotListView(generics.ListCreateAPIView):
    """مدیر کلاس‌ها را یکی‌یکی وارد می‌کند — لیست کامل + افزودن"""
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
    """ویرایش یا حذف هر کلاس، همیشه آزاد"""
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


class AutoScheduleTimesView(APIView):
    """POST: دکمه‌ی «چیدمان هوشمند ساعت‌ها» — صبح/عصر و ساعت دقیق کلاس‌های زوج/فرد را بر اساس وضعیت چرخشی تعیین می‌کند"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        slots = auto_schedule_times()
        return Response(ClassSlotSerializer(slots, many=True).data)


class AllocateClassesView(APIView):
    """POST: دکمه‌ی «تخصیص کلاس» — سطوح و تعداد را بین کلاس‌های از‌قبل زمان‌بندی‌شده تقسیم می‌کند"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        serializer = AllocateClassesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        warnings, summary = allocate_classes(
            levels=data['levels'],
            tolerance=data['tolerance'],
            thursday_only_count=data['thursday_only_count'],
            friday_only_count=data['friday_only_count'],
        )

        slots = ClassSlot.objects.all().order_by('number')
        return Response({
            'warnings': warnings,
            'summary': summary,
            'slots': ClassSlotSerializer(slots, many=True).data,
        })
