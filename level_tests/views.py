from rest_framework import status, generics
from rest_framework import serializers as drf_serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils import timezone
from django.db.models import Q
from .models import LevelTest, LevelTestPriceSetting, StandardLevel
from .serializers import LevelTestIntakeSerializer, LevelTestSerializer, LevelTestPriceSettingSerializer
from .levels import get_levels_by_age_group, AGE_GROUP_LABELS
from accounts.models import User
from accounts.serializers import StudentSerializer
from notifications.utils import send_notification

MANAGE_LEVEL_ROLES = ('admin', 'evaluator')

DEFAULT_STANDARD_LEVELS = (
    ('kids', ['e1', 'e2', 'e3', 'e4', 'e5', 's1', 's2', 's3', 's4', 's5', 'g1', 'g2', 'g3', 'g4', 'g5', 'u1', 'u2', 'u3', 'u4', 'u5', 'm1', 'm2', 'm3', 'm4', 'm5', 'h1', 'h2', 'h3', 'h4', 'h5', 'i1', 'i2', 'i3', 'i4', 'i5']),
    ('teen', ['teen starter'] + [f'teen{i}' for i in range(1, 16)]),
    ('adult', [f'{prefix}{i}' for prefix in ('1', '2', '3', '4', '5', '6') for i in range(1, 7)]),
)


def ensure_default_standard_levels():
    """Seed only missing defaults; never edits or deletes levels created by the manager."""
    existing = set(StandardLevel.objects.values_list('code', flat=True))
    missing = []
    for age_group, codes in DEFAULT_STANDARD_LEVELS:
        last_code = codes[-1]
        for order, code in enumerate(codes, start=1):
            if code not in existing:
                missing.append(StandardLevel(code=code, age_group=age_group, order=order, is_terminal=(code == last_code)))
    if missing:
        StandardLevel.objects.bulk_create(missing, ignore_conflicts=True)


def _clear_other_terminals(age_group, keep_id=None):
    """فقط یک سطح پایانی در هر رده معتبر است — با علامت‌گذاری سطح جدید، بقیه‌ی همان رده خودکار پاک می‌شوند."""
    qs = StandardLevel.objects.filter(age_group=age_group, is_terminal=True)
    if keep_id is not None:
        qs = qs.exclude(pk=keep_id)
    qs.update(is_terminal=False)


class StandardLevelSerializer(drf_serializers.ModelSerializer):
    age_group_display = drf_serializers.CharField(source='get_age_group_display', read_only=True)

    class Meta:
        model = StandardLevel
        fields = ['id', 'code', 'age_group', 'age_group_display', 'order', 'is_terminal', 'created_at']
        read_only_fields = ['id', 'created_at']


class StandardLevelListView(generics.ListCreateAPIView):
    """GET: لیست سطوح استاندارد تعریف‌شده (همه‌ی رده‌ها) / POST: افزودن سطح استاندارد جدید — منبع واحد سطوح در کل پروژه"""
    permission_classes = [IsAuthenticated]
    serializer_class = StandardLevelSerializer

    def get_queryset(self):
        if self.request.user.role not in MANAGE_LEVEL_ROLES:
            return StandardLevel.objects.none()
        if not StandardLevel.objects.exists():
            # فقط وقتی جدول کاملاً خالیه (نصب اولیه) سطوح پیش‌فرض ساخته می‌شن؛
            # وگرنه حذفِ یک سطح پیش‌فرض توسط مدیر، با رفرش بعدی دوباره ساخته می‌شد.
            ensure_default_standard_levels()
        qs = StandardLevel.objects.all()
        age_group = self.request.query_params.get('age_group')
        if age_group:
            qs = qs.filter(age_group=age_group)
        return qs

    def create(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_LEVEL_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        code = (request.data.get('code') or '').strip()
        age_group = (request.data.get('age_group') or '').strip()
        if not code:
            return Response({'error': 'کد سطح را وارد کنید'}, status=status.HTTP_400_BAD_REQUEST)
        if not age_group:
            return Response({'error': 'گروه سنی را انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
        if StandardLevel.objects.filter(code__iexact=code).exists():
            return Response({'error': f'سطح «{code}» از قبل وجود دارد'}, status=status.HTTP_400_BAD_REQUEST)
        response = super().create(request, *args, **kwargs)
        if response.status_code == status.HTTP_201_CREATED and request.data.get('is_terminal'):
            _clear_other_terminals(age_group, keep_id=response.data.get('id'))
        return response


class StandardLevelDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE یک سطح استاندارد"""
    permission_classes = [IsAuthenticated]
    serializer_class = StandardLevelSerializer
    queryset = StandardLevel.objects.all()

    def update(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_LEVEL_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        instance = self.get_object()
        response = super().update(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK and request.data.get('is_terminal'):
            _clear_other_terminals(instance.age_group, keep_id=instance.pk)
        return response

    def destroy(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_LEVEL_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class LevelChoicesView(APIView):
    """لیست کامل سطوح، گروه‌بندی‌شده بر اساس گروه سنی — برای پر کردن select های فرم پنل مدیر آموزش"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            'age_groups': [{'value': k, 'label': v} for k, v in AGE_GROUP_LABELS.items()],
            'levels_by_age_group': get_levels_by_age_group(),
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
        if user.role not in ('admin', 'evaluator', 'office'):
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


class StudentRequestLevelTestView(APIView):
    """
    POST: خواسته‌ی «دکمه‌ی درخواست وقت تعیین سطح» در اپ دانش‌آموز — خودِ دانش‌آموز
    (چه ورودی جدید بدون هیچ سابقه‌ای، چه هر زمان دیگری که نیاز به تعیین سطح داشته باشد)
    درخواست می‌دهد: نوع (آنلاین/حضوری) + پرداخت الزامی (کارت‌به‌کارت با رسید، یا درگاه).
    بعد از ثبت، اسم فرد در لیست «در انتظار تعیین سطح» پنل ادمین ظاهر می‌شود و به مدیر/کانتر
    نوتیف می‌رود.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        student = request.user
        if student.role != 'student':
            return Response({'error': 'این بخش فقط برای دانش‌آموزان است'}, status=status.HTTP_403_FORBIDDEN)

        if LevelTest.objects.filter(student=student, status=LevelTest.Status.PENDING).exists():
            return Response({'error': 'شما از قبل یک درخواست تعیین سطحِ در-انتظار دارید'}, status=status.HTTP_400_BAD_REQUEST)

        mode = request.data.get('mode')
        if mode not in (LevelTest.Mode.ONLINE, LevelTest.Mode.ONSITE):
            return Response({'error': 'نوع تعیین سطح (آنلاین/حضوری) را مشخص کنید'}, status=status.HTTP_400_BAD_REQUEST)

        payment_method = request.data.get('payment_method')
        if payment_method not in (LevelTest.PaymentMethod.CARD_TO_CARD, LevelTest.PaymentMethod.GATEWAY):
            return Response({'error': 'روش پرداخت نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        if payment_method == LevelTest.PaymentMethod.GATEWAY:
            return Response(
                {'error': 'پرداخت از طریق درگاه فعلاً راه‌اندازی نشده — لطفاً کارت‌به‌کارت را انتخاب کنید'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        receipt = request.FILES.get('receipt')
        if not receipt:
            return Response({'error': 'تصویر رسید کارت‌به‌کارت الزامی است'}, status=status.HTTP_400_BAD_REQUEST)

        if not student.gender:
            return Response({'error': 'ابتدا جنسیت خود را در پروفایل تکمیل کنید'}, status=status.HTTP_400_BAD_REQUEST)

        setting = LevelTestPriceSetting.objects.order_by('-updated_at').first()
        price = setting.price if setting else 0

        obj = LevelTest.objects.create(
            first_name=student.first_name, last_name=student.last_name, father_name=student.father_name,
            birth_date=student.birth_date, national_code=student.national_code, phone=student.phone,
            gender=student.gender, student=student, price=price, payment_status=LevelTest.PaymentStatus.UNPAID,
            mode=mode, payment_method=payment_method, receipt_image=receipt, self_requested=True,
            status=LevelTest.Status.PENDING, created_by=student,
        )

        mode_label = 'حضوری' if mode == LevelTest.Mode.ONSITE else 'آنلاین'
        admins = list(User.objects.filter(role__in=['admin', 'office']))
        send_notification(
            sender=None, recipients=admins,
            title='درخواست وقت تعیین سطح جدید',
            body=f'{student.first_name} {student.last_name} درخواست تعیین سطح {mode_label} داد و منتظر تعیین وقت است',
        )

        return Response(LevelTestSerializer(obj).data, status=status.HTTP_201_CREATED)


class MyLevelTestsView(generics.ListAPIView):
    """GET: سوابق تعیین‌سطح خودِ دانش‌آموز — برای نمایش وضعیت/زمان/لینک/نتیجه در صفحه‌ی اصلی و صفحه‌ی ترمیک/تعیین‌سطح اپ"""
    permission_classes = [IsAuthenticated]
    serializer_class = LevelTestSerializer

    def get_queryset(self):
        return LevelTest.objects.filter(student=self.request.user).order_by('-created_at')


class LevelTestPaymentInfoView(APIView):
    """GET: شماره‌کارت/نام صاحب‌کارت برای پرداخت کارت‌به‌کارتِ تعیین سطح — همان تنظیمات مشترکِ پرداخت پروژه"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from class_management.models import PaymentSettings
        from class_management.serializers import PaymentSettingsSerializer
        setting = LevelTestPriceSetting.objects.order_by('-updated_at').first()
        return Response({
            'price': setting.price if setting else 0,
            'payment_settings': PaymentSettingsSerializer(PaymentSettings.get_solo()).data,
        })


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
        if request.user.role not in ('admin', 'evaluator', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            obj = self._get_visible(request, pk)
        except LevelTest.DoesNotExist:
            return Response({'error': 'پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        return Response(LevelTestSerializer(obj).data)

    def patch(self, request, pk):
        user = request.user
        if user.role not in ('admin', 'evaluator', 'office'):
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

        # برای تشخیصِ «تازه اضافه شده» (تا فقط همون لحظه نوتیف بفرستیم، نه هر بار ویرایش)
        had_test_date_before = bool(obj.test_date)
        had_meeting_link_before = bool(obj.meeting_link)
        was_completed_before = obj.status == LevelTest.Status.COMPLETED

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

        # خواسته‌ی «سطح تخصیص‌داده‌شده به‌عنوان سطح اصلی فرد در نظر گرفته شود» — همین که نتیجه
        # تکمیل شد و به یک حساب دانش‌آموزی وصل بود، سطح را روی پروفایل کاربر هم می‌نویسیم تا
        # هرجای دیگر سیستم که «سطح دانش‌آموز» لازم است (ثبت‌نام کلاس، گزارش‌ها، ...) همین مقدار
        # به‌عنوان مرجع استفاده شود.
        if updated.status == LevelTest.Status.COMPLETED and updated.level and updated.student:
            if updated.student.language_level != updated.level:
                updated.student.language_level = updated.level
                updated.student.save(update_fields=['language_level'])

        # نوتیف به دانش‌آموز — فقط در همون لحظه‌ای که هرکدوم از این‌ها *تازه* مقداردهی می‌شن،
        # نه هر بار که مدیر رکورد رو ویرایش می‌کنه
        if updated.student:
            if updated.test_date and not had_test_date_before:
                send_notification(
                    sender=user, recipients=[updated.student],
                    title='وقت تعیین سطح شما مشخص شد',
                    body=f'وقت تعیین سطح شما: {updated.test_date_jalali} ({updated.get_mode_display() or "حضوری"})',
                )
            if updated.meeting_link and not had_meeting_link_before:
                send_notification(
                    sender=user, recipients=[updated.student],
                    title='لینک تعیین سطح آنلاین شما آماده شد',
                    body='لینک تعیین سطح آنلاینِ شما در اپ در دسترس است — سر وقتِ تعیین‌شده وارد شوید',
                )
            if updated.status == LevelTest.Status.COMPLETED and not was_completed_before and updated.level:
                send_notification(
                    sender=user, recipients=[updated.student],
                    title='نتیجه‌ی تعیین سطح شما آماده شد',
                    body=f'سطح نهایی شما: {updated.level}',
                )

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
