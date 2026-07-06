from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Q
from .models import LevelTest, LevelTestPriceSetting
from .serializers import LevelTestIntakeSerializer, LevelTestSerializer, LevelTestPriceSettingSerializer
from .levels import LEVELS_BY_AGE_GROUP, AGE_GROUP_LABELS


class LevelChoicesView(APIView):
    """لیست کامل سطوح، گروه‌بندی‌شده بر اساس گروه سنی — برای پر کردن select های فرم پنل مدیر آموزش"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            'age_groups': [{'value': k, 'label': v} for k, v in AGE_GROUP_LABELS.items()],
            'levels_by_age_group': LEVELS_BY_AGE_GROUP,
        })


class LevelTestListCreateView(APIView):
    """
    GET: مدیر و مدیر آموزش هر دو همه‌ی رکوردها (در انتظار + تعیین‌سطح‌شده) را با جستجو می‌بینند
         (مدیر آموزش دیگر محدود به صف خودش نیست — گزارش‌گیری کامل دارد).
    POST: فقط مدیر/کانتر — ثبت مشخصات اولیه‌ی داوطلب (مرحله‌ی ارجاع، بدون نتیجه).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.role not in ('admin', 'evaluator'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        qs = LevelTest.objects.all()

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(first_name__icontains=search) | Q(last_name__icontains=search) |
                Q(phone__icontains=search) | Q(national_code__icontains=search) | Q(level__icontains=search)
            )
        return Response(LevelTestSerializer(qs, many=True).data)

    def post(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر/کانتر می‌تواند داوطلب جدید ثبت کند'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data.copy()
        if data.get('price') in (None, ''):
            setting = LevelTestPriceSetting.objects.order_by('-updated_at').first()
            data['price'] = setting.price if setting else 0
        serializer = LevelTestIntakeSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save(created_by=request.user, status=LevelTest.Status.PENDING)
        return Response(LevelTestSerializer(obj).data, status=status.HTTP_201_CREATED)


class LevelTestPriceSettingView(APIView):
    """تنظیمات قیمت پیش‌فرض آزمون تعیین سطح — مدیر و مدیر آموزش هر دو می‌توانند ویرایش کنند"""
    permission_classes = [IsAuthenticated]

    def get_current(self):
        setting = LevelTestPriceSetting.objects.order_by('-updated_at').first()
        if not setting:
            setting = LevelTestPriceSetting.objects.create()
        return setting

    def get(self, request):
        return Response(LevelTestPriceSettingSerializer(self.get_current()).data)

    def patch(self, request):
        if request.user.role not in ('admin', 'evaluator'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        setting = self.get_current()
        serializer = LevelTestPriceSettingSerializer(setting, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class LevelTestDetailView(APIView):
    """
    GET/PATCH/DELETE: مدیر و مدیر آموزش دسترسی کامل و یکسان دارند (هم مشخصات اولیه هم نتیجه،
    همیشه قابل ویرایش/حذف — طبق الگوی «همیشه قابل ویرایش» بقیه‌ی پروژه).
    وقتی age_group و level هر دو مقدار داشته باشند، status خودکار completed می‌شود.
    """
    permission_classes = [IsAuthenticated]

    def _get_visible(self, request, pk):
        return LevelTest.objects.get(pk=pk)

    def get(self, request, pk):
        if request.user.role not in ('admin', 'evaluator'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            obj = self._get_visible(request, pk)
        except LevelTest.DoesNotExist:
            return Response({'error': 'پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        return Response(LevelTestSerializer(obj).data)

    def patch(self, request, pk):
        user = request.user
        if user.role not in ('admin', 'evaluator'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            obj = self._get_visible(request, pk)
        except LevelTest.DoesNotExist:
            return Response({'error': 'پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data.copy()
        if data.get('level') and not data.get('evaluator') and not obj.evaluator:
            data['evaluator'] = user.id
        if data.get('level') and not data.get('test_date') and not obj.test_date:
            data['test_date'] = timezone.now().isoformat()

        serializer = LevelTestSerializer(obj, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        if updated.age_group and updated.level and updated.status != LevelTest.Status.COMPLETED:
            updated.status = LevelTest.Status.COMPLETED
            updated.save()

        return Response(LevelTestSerializer(updated).data)

    def delete(self, request, pk):
        if request.user.role not in ('admin', 'evaluator'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            obj = LevelTest.objects.get(pk=pk)
        except LevelTest.DoesNotExist:
            return Response({'error': 'پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        obj.delete()
        return Response({'message': 'حذف شد'})
