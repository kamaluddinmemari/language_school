from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Q
from .models import LevelTest, LevelTestPriceSetting
from .serializers import LevelTestIntakeSerializer, LevelTestSerializer, LevelTestPriceSettingSerializer
from .levels import LEVELS_BY_AGE_GROUP, AGE_GROUP_LABELS
from accounts.models import User
from accounts.serializers import StudentSerializer


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
        if request.user.role not in ('admin', 'office'):
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
        # وقتی خودِ مدیر (نه یک حساب با نقش evaluator) نتیجه را ثبت می‌کند، فیلد FK اسم «evaluator»
        # طبق طراحی فقط به حساب‌های نقش evaluator اجازه می‌دهد (limit_choices_to روی مدل) — پس
        # نباید مدیر را در آن FK بگذاریم (باعث خطای «Invalid pk» می‌شود)، به‌جایش در فیلد متنی
        # evaluator_name (که دقیقاً برای همین حالت طراحی شده) اسمش را ثبت می‌کنیم.
        if data.get('level') and not data.get('evaluator') and not data.get('evaluator_name') \
                and not obj.evaluator and not obj.evaluator_name:
            if user.role == 'evaluator':
                data['evaluator'] = user.id
            else:
                data['evaluator_name'] = f"{user.first_name} {user.last_name}"
        if data.get('level') and not data.get('test_date') and not obj.test_date:
            data['test_date'] = timezone.now().isoformat()

        serializer = LevelTestSerializer(obj, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        if updated.age_group and updated.level and updated.status != LevelTest.Status.COMPLETED:
            updated.status = LevelTest.Status.COMPLETED
            updated.save()

        # وقتی تعیین‌سطح تکمیل می‌شود و هنوز به حساب دانش‌آموزی وصل نیست، خودکار وصلش می‌کنیم:
        # اول دنبال حسابی با همین کد ملی می‌گردیم؛ اگه نبود، با همون مشخصات اولیه یکی می‌سازیم
        # (خواسته‌ی «افرادی که برای تعیین‌سطح ثبت می‌شن خودکار وارد لیست دانش‌آموزان بشن»)
        if updated.status == LevelTest.Status.COMPLETED and not updated.student:
            existing = None
            if updated.national_code:
                existing = User.objects.filter(role='student', national_code=updated.national_code).first()
            if existing:
                updated.student = existing
                updated.save(update_fields=['student'])
            elif updated.first_name and updated.last_name and updated.national_code and updated.gender:
                student_serializer = StudentSerializer(data={
                    'first_name': updated.first_name, 'last_name': updated.last_name,
                    'father_name': updated.father_name, 'phone': updated.phone,
                    'national_code': updated.national_code,
                    'birth_date': updated.birth_date.isoformat() if updated.birth_date else None,
                    'gender': updated.gender,
                })
                if student_serializer.is_valid():
                    new_student = student_serializer.save()
                    updated.student = new_student
                    updated.save(update_fields=['student'])
                # اگه به هر دلیلی نامعتبر بود (مثلاً کد ملی تکراری با نقش غیردانش‌آموز)، بی‌صدا رد می‌شویم —
                # مدیر می‌تواند بعداً دستی از پنل مدیریت دانش‌آموزان وصلش کند، بدون اینکه ثبت نتیجه‌ی
                # تعیین‌سطح به‌خاطر این خطا مسدود شود

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
