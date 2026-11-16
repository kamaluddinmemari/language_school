from rest_framework import status, generics
from rest_framework import serializers as drf_serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils import timezone
from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from .models import LevelTest, LevelTestPriceSetting, StandardLevel
from .serializers import LevelTestIntakeSerializer, LevelTestSerializer, LevelTestPriceSettingSerializer
from accounts.menu_permissions import can_edit_menu, can_view_menu
from .levels import get_levels_by_age_group, AGE_GROUP_LABELS
from accounts.models import User, ClassRequest
from accounts.serializers import StudentSerializer
from notifications.utils import send_notification

# منسوخ — از تنظیمات دسترسی (accounts.menu_permissions) جایگزین شد؛ فقط برای مرجع نگه داشته شده.
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
        if not can_view_menu(self.request.user, 'standard-levels'):
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
        if not can_edit_menu(request.user, 'standard-levels'):
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
        if not can_edit_menu(request.user, 'standard-levels'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        instance = self.get_object()
        response = super().update(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK and request.data.get('is_terminal'):
            _clear_other_terminals(instance.age_group, keep_id=instance.pk)
        return response

    def destroy(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'standard-levels'):
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


class AvailableClassSlotsForLevelView(APIView):
    """
    خواسته: برای فرم «ثبت نتیجه‌ی تعیین سطح» — کلاس‌های ترمِ جاری (آخرین ترم تعریف‌شده)
    را برمی‌گرداند؛ آرشیو می‌تواند با term_id ترمِ موردنظرش را صریحاً انتخاب کند. کلاس‌ها
    با جنسیتِ داوطلب سازگارند (همان جنسیت + کلاس‌های مختلط). از این یک
    پاسخ هم برای رنگ‌آمیزیِ سطوحِ موجود/ناموجود (بر اساس اینکه سطح در نتیجه حضور دارد یا نه)
    و هم برای پیشنهاد کلاسِ متناسب با سطحِ انتخابی، در فرانت استفاده می‌شود.

    نکته‌ی مهم: جنسیت روی LevelTest با مقادیر User.Gender ثبت می‌شود ('female'/'male')،
    اما جنسیت روی ClassSlot با مقادیر جداگانه‌ای است ('girls'/'boys'/'mixed')؛ اینجا بین
    این دو نگاشت انجام می‌شود (باگ قبلی همین عدم تطابق بود که باعث می‌شد فیلتر جنسیت اصلاً
    اعمال نشود و همه‌ی کلاس‌ها، صرف‌نظر از جنسیت، برگردانده شوند).
    """
    permission_classes = [IsAuthenticated]
    GENDER_MAP = {'female': 'girls', 'male': 'boys'}

    def get(self, request):
        from class_management.models import ClassSlot
        from class_management.models import Term, get_latest_term_for_pre_registration
        gender = (request.query_params.get('gender') or '').strip()
        term_param = request.query_params.get('term_id')
        selected_term = Term.objects.filter(pk=term_param).first() if str(term_param or '').isdigit() else None
        latest_term = selected_term or get_latest_term_for_pre_registration()
        if not latest_term:
            return Response([])
        qs = ClassSlot.objects.filter(term=latest_term).exclude(assigned_level='').annotate(
            _confirmed_enrollment_count=Count('enrollments', filter=Q(enrollments__payment_verified=True), distinct=True),
        )
        mapped_gender = self.GENDER_MAP.get(gender)
        if mapped_gender:
            qs = qs.filter(gender__in=[mapped_gender, ClassSlot.Gender.MIXED])
        results = [{
            'id': c.id,
            'number': c.number,
            'term_number': latest_term.term_number,
            'term_year': latest_term.year,
            'term_title': latest_term.title,
            'term_id': latest_term.id,
            'level': c.assigned_level,
            'day_display': c.get_day_type_display(),
            'time_slot': c.time_slot,
            'teacher_name': c.teacher_name or 'تعیین نشده',
            'gender_display': c.get_gender_display(),
            'seats_left': c.seats_left,
            'capacity': c.capacity,
            'real_enrolled_count': c._confirmed_enrollment_count,
            'real_seats_left': c.capacity - c._confirmed_enrollment_count,
        } for c in qs.order_by('assigned_level', 'day_type', 'time_slot')]
        return Response(results)


class LevelTestListCreateView(APIView):
    """
    GET: مدیر و مدیر آموزش هر دو همه‌ی رکوردها (در انتظار + تعیین‌سطح‌شده) را با جستجو می‌بینند
         (مدیر آموزش دیگر محدود به صف خودش نیست — گزارش‌گیری کامل دارد).
    POST: فقط مدیر/کانتر — ثبت مشخصات اولیه‌ی داوطلب (مرحله‌ی ارجاع، بدون نتیجه).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not can_view_menu(user, 'level-tests'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        # خواسته: صف همیشه بر اساس وقتِ تعیین‌شده از نزدیک‌ترین به دورترین چیده شود؛ برای کسانی
        # که هنوز وقتی برایشان تعیین نشده، زمان ثبتشان در صف (created_at) ملاک مرتب‌سازی است.
        qs = LevelTest.objects.select_related('evaluator').annotate(_effective_sort_time=Coalesce('test_date', 'created_at')).order_by('_effective_sort_time')

        # فقط «در انتظار»ها (برای شمارنده و هشدارهای صفحهٔ اصلی؛ بدون خواندن کل بایگانی)
        status_filter = request.query_params.get('status', '').strip()
        if status_filter in {value for value, _label in LevelTest.Status.choices}:
            qs = qs.filter(status=status_filter)

        # نبض سبک برای اعلان‌های صوتیِ سراسری: همهٔ در انتظارها + نتیجه‌های دو روز اخیر (نه کل بایگانی)
        if request.query_params.get('pulse'):
            from datetime import timedelta as _td
            qs = qs.filter(Q(status=LevelTest.Status.PENDING) | Q(status=LevelTest.Status.COMPLETED, updated_at__gte=timezone.now() - _td(days=2)))

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(first_name__icontains=search) | Q(last_name__icontains=search) |
                Q(phone__icontains=search) | Q(national_code__icontains=search) | Q(level__icontains=search)
            )
        return Response(LevelTestSerializer(qs, many=True).data)

    def post(self, request):
        if not can_edit_menu(request.user, 'level-tests'):
            return Response({'error': 'فقط مدیر/کانتر می‌تواند داوطلب جدید ثبت کند'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data.copy()
        if data.get('price') in (None, ''):
            setting = LevelTestPriceSetting.objects.order_by('-updated_at').first()
            data['price'] = setting.price if setting else 0
        serializer = LevelTestIntakeSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        from .scheduling import normalize_name
        first_name = normalize_name(serializer.validated_data.get('first_name'))
        last_name = normalize_name(serializer.validated_data.get('last_name'))
        national_code = str(serializer.validated_data.get('national_code') or '').strip()
        student_id = serializer.validated_data.get('student').id if serializer.validated_data.get('student') else None
        pending_tests = LevelTest.objects.filter(status=LevelTest.Status.PENDING).only(
            'id', 'first_name', 'last_name', 'national_code', 'student_id', 'test_date'
        )
        duplicate = None
        for existing in pending_tests:
            # وقت گذشته و انجام‌نشده فقط سابقه‌ی هشدار است؛ نباید مانع رزرو وقت جدید شود.
            if existing.test_date and existing.test_date < timezone.now():
                continue
            same_student = bool(student_id and existing.student_id == student_id)
            same_code = bool(national_code and existing.national_code and existing.national_code.strip() == national_code)
            same_name = (
                normalize_name(existing.first_name) == first_name
                and normalize_name(existing.last_name) == last_name
            )
            if same_student or same_code or same_name:
                duplicate = existing
                break
        if duplicate:
            return Response({
                'error': f"⚠️ این فرد از قبل در فهرست تعیین‌سطح‌های در انتظار ثبت شده است: {duplicate.first_name} {duplicate.last_name} (شمارهٔ پیگیری: {duplicate.id}). برای جلوگیری از ثبت تکراری، ابتدا همان مورد را بررسی کنید.",
                'duplicate_id': duplicate.id,
            }, status=status.HTTP_409_CONFLICT)
        # هشدار فوری: داوطلبِ بدهکار از قبل یا جزو «ثبت‌نام‌نشده‌ها» (بدون دور زدن تأیید کاربر)
        from class_management.disciplinary import disciplinary_guard, pseudo_person
        student_obj = serializer.validated_data.get('student')
        person = student_obj or pseudo_person(
            serializer.validated_data.get('first_name'), serializer.validated_data.get('last_name'),
            national_code, serializer.validated_data.get('phone'),
        )
        warning = disciplinary_guard(request, [person], skip_disciplinary=True, title='هشدار هنگام ثبت درخواست تعیین سطح')
        if warning:
            return warning
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
        # درخواست از اپ قابل «تأیید در لحظه» نیست؛ هشدار بدهکار/ثبت‌نام‌نشده بودن در همان اعلان مدیران می‌آید
        from class_management.disciplinary import person_reasons
        warning_reasons, _count = person_reasons(student, skip_disciplinary=True)
        warning_note = (' ⚠ هشدار: ' + '؛ '.join(r['text'] for r in warning_reasons)) if warning_reasons else ''
        send_notification(
            sender=None, recipients=admins,
            title='⚠ درخواست وقت تعیین سطح جدید' if warning_note else 'درخواست وقت تعیین سطح جدید',
            body=f'{student.first_name} {student.last_name} درخواست تعیین سطح {mode_label} داد و منتظر تعیین وقت است.{warning_note}',
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
        if not can_edit_menu(request.user, 'level-tests'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        setting = self.get_current()
        serializer = LevelTestPriceSettingSerializer(setting, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


DEFAULT_LATE_GRACE_MINUTES = 45


def _queue_setting_row():
    from accounts.models import AppearanceSettings
    obj, _ = AppearanceSettings.objects.get_or_create(key='level_tests')
    return obj


def get_late_grace_minutes():
    try:
        value = int((_queue_setting_row().settings or {}).get('late_grace_minutes', DEFAULT_LATE_GRACE_MINUTES))
    except Exception:
        return DEFAULT_LATE_GRACE_MINUTES
    return min(max(value, 1), 1440)


class LevelTestQueueSettingView(APIView):
    """مهلت ماندن فرد در صف انتظار بعد از زمان رزرو (دقیقه) — بعد از آن به «مراجعه نکرده‌ها» می‌رود. بدون ستون جدید در دیتابیس."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({'late_grace_minutes': get_late_grace_minutes()})

    def patch(self, request):
        if not can_edit_menu(request.user, 'level-tests'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            minutes = int(request.data.get('late_grace_minutes'))
        except (TypeError, ValueError):
            return Response({'error': 'مهلت را به‌صورت عدد (دقیقه) وارد کنید'}, status=status.HTTP_400_BAD_REQUEST)
        if not 1 <= minutes <= 1440:
            return Response({'error': 'مهلت باید بین ۱ تا ۱۴۴۰ دقیقه باشد'}, status=status.HTTP_400_BAD_REQUEST)
        row = _queue_setting_row()
        row.settings = {**(row.settings or {}), 'late_grace_minutes': minutes}
        row.updated_by = request.user
        row.save()
        return Response({'late_grace_minutes': minutes})


class LevelTestActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        if not can_edit_menu(request.user, 'level-tests'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try: obj = LevelTest.objects.get(pk=pk)
        except LevelTest.DoesNotExist: return Response({'error': 'پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        now = timezone.now()
        if action == 'prioritize':
            if obj.status != LevelTest.Status.PENDING:
                return Response({'error': 'فقط افراد در صف انتظار قابل انتقال به ابتدای صف هستند'}, status=status.HTTP_400_BAD_REQUEST)
            obj.queue_priority_at = now
            obj.save(update_fields=['queue_priority_at', 'updated_at'])
            return Response(LevelTestSerializer(obj).data)
        elif action == 'requeue':
            # وقت ازدست‌رفته را نگه می‌داریم، اما برای فرد وقت جدیدِ همین لحظه می‌سازیم.
            if obj.status != LevelTest.Status.PENDING:
                return Response({'error': 'فقط افراد در انتظار تعیین سطح قابل بازگشت به صف هستند'}, status=status.HTTP_400_BAD_REQUEST)
            if obj.test_date:
                obj.previous_missed_test_date = obj.test_date
            obj.test_date = now
            obj.queue_priority_at = now
            obj.reminder_24h_followed_at = None
            obj.reminder_2h_followed_at = None
            obj.save(update_fields=['test_date', 'previous_missed_test_date', 'queue_priority_at', 'reminder_24h_followed_at', 'reminder_2h_followed_at', 'updated_at'])
            return Response(LevelTestSerializer(obj).data)
        elif action == 'natoos':
            obj.natoos_registered = True
        elif action == 'reminder-24h':
            obj.reminder_24h_followed_at = now
        elif action == 'reminder-2h':
            obj.reminder_2h_followed_at = now
        elif action == 'followup':
            from leads.models import NewLead
            lead = obj.followup_lead
            if not lead:
                lead = NewLead.objects.create(first_name=obj.first_name, last_name=obj.last_name, father_name=obj.father_name, national_code=obj.national_code, birth_date=obj.birth_date, phone=obj.phone, created_by=request.user)
                obj.followup_lead = lead
            obj.save(update_fields=['followup_lead', 'updated_at'])
            return Response({'lead_id': lead.id, 'message': 'برای پیگیری به ورودی‌های جدید اضافه شد'})
        else:
            return Response({'error': 'اکشن نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        obj.save()
        return Response(LevelTestSerializer(obj).data)


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
        if not can_view_menu(request.user, 'level-tests'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            obj = self._get_visible(request, pk)
        except LevelTest.DoesNotExist:
            return Response({'error': 'پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        return Response(LevelTestSerializer(obj).data)

    def patch(self, request, pk):
        user = request.user
        if not can_edit_menu(user, 'level-tests'):
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
            elif updated.phone:
                existing = User.objects.filter(
                    role='student', phone=updated.phone,
                    first_name=updated.first_name, last_name=updated.last_name,
                ).first()
            if existing:
                updated.student = existing
                updated.save(update_fields=['student'])
            elif updated.first_name and updated.last_name and updated.phone and updated.gender:
                student_serializer = StudentSerializer(data={
                    'first_name': updated.first_name, 'last_name': updated.last_name,
                    'father_name': updated.father_name, 'phone': updated.phone,
                    'national_code': updated.national_code or None,
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

        # خواسته: اگر تعیین‌سطح تکمیل شد و فرد نیاز به کلاس خصوصی و/یا جبرانی دارد، بدون نیاز
        # به ورود دوباره‌ی اطلاعات، خودکار یک درخواست کلاس (به ازای هرکدام) در «درخواست‌های
        # کلاس» ساخته می‌شود — با وضعیت pending (منتظر ارجاع به استاد) و پرداخت‌نشده (منتظر
        # پرداخت هزینه)؛ پروتکل رنگی همان‌جاست: خصوصی‌ی پرداخت‌نشده قرمز، پرداخت‌شده سبز،
        # جبرانی زرد. با بررسی auto_created_class_requests از ساختن دوباره جلوگیری می‌شود.
        if updated.status == LevelTest.Status.COMPLETED and updated.student and not updated.auto_created_class_requests.exists():
            source_note = 'ورود اطلاعات از بخش تعیین سطح — منتظر ارجاع به استاد و پرداخت هزینه'
            if updated.needs_private_class:
                ClassRequest.objects.create(
                    student=updated.student, class_type=ClassRequest.ClassType.PRIVATE,
                    language_level=updated.level or updated.student.language_level,
                    session_count=updated.private_sessions_needed or 1,
                    payment_status=ClassRequest.PaymentStatus.UNPAID, status=ClassRequest.Status.PENDING,
                    notes=source_note, source_level_test=updated,
                )
            if updated.needs_makeup_class:
                ClassRequest.objects.create(
                    student=updated.student, class_type=ClassRequest.ClassType.MAKEUP,
                    language_level=updated.level or updated.student.language_level,
                    session_count=updated.makeup_sessions_needed or 1,
                    payment_status=ClassRequest.PaymentStatus.UNPAID, status=ClassRequest.Status.PENDING,
                    notes=source_note, source_level_test=updated,
                )

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
        if not can_edit_menu(request.user, 'level-tests'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            obj = LevelTest.objects.get(pk=pk)
        except LevelTest.DoesNotExist:
            return Response({'error': 'پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        # اگر این آزمون از طریق تیک «نیاز به تعیین سطح دارد» برای یک سرنخ ساخته شده بود،
        # با حذفش تیک همان سرنخ هم خاموش شود تا در «ورودی‌های جدید» یتیم/گمراه‌کننده نماند.
        obj.new_leads.update(needs_level_test=False, needs_level_test_marked_at=None, level_test=None)
        obj.delete()
        return Response({'message': 'حذف شد'})


class LevelTestRegistrationStatsView(APIView):
    """
    GET: آمار تعیین‌سطح‌شده‌هایی که بعد از تعیین سطح ثبت‌نام قطعی کرده‌اند + آمار کلاس مقصدشان.
    «ثبت‌نام‌کرده» = ثبت‌نام قطعیِ او (غیر از انتقالیِ تأییدنشده) در کلاسی از ترمی که بعد از تاریخ تعیین سطح تمام نشده؛
    اولین چنین ثبت‌نامی کلاس مقصد حساب می‌شود. تطبیق فرد: پروندهٔ دانش‌آموز ثبت‌شده، کد ملی، یا شماره همراه (۱۰ رقم آخر) + نام.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            return self._compute(request)
        except Exception as exc:  # علت واقعی به‌جای خطای مبهم به پنل برگردد
            import logging
            logging.getLogger(__name__).exception('%s failed', self.__class__.__name__)
            return Response({'error': f'خطای سرور: {type(exc).__name__}: {exc}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _compute(self, request):
        if not can_view_menu(request.user, 'level-tests'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from class_management.models import ClassSlotEnrollment
        from leads.views import _lead_digits, _lead_name
        tests = list(LevelTest.objects.filter(status=LevelTest.Status.COMPLETED).order_by('-id'))
        students = list(User.objects.filter(role='student').only('id', 'first_name', 'last_name', 'national_code', 'phone', 'phone2'))
        by_code, by_phone = {}, {}
        for st in students:
            code = _lead_digits(st.national_code)
            if code:
                by_code.setdefault(code.zfill(10), []).append(st)
            for ph in (st.phone, st.phone2):
                ph = _lead_digits(ph)[-10:]
                if len(ph) == 10:
                    by_phone.setdefault(ph, []).append(st)
        enrolls = {}
        qs = ClassSlotEnrollment.objects.exclude(is_carryover=True, carryover_confirmed=False).select_related('class_slot__term').order_by('id')
        for e in qs:
            enrolls.setdefault(e.student_id, []).append(e)

        def student_of(t):
            if t.student_id:
                return t.student_id
            name = _lead_name(t.first_name, t.last_name)
            code = _lead_digits(t.national_code)
            if code:
                found = by_code.get(code.zfill(10))
                if found:
                    return found[0].id
            ph = _lead_digits(t.phone)[-10:]
            cands = by_phone.get(ph, []) if len(ph) == 10 else []
            same = [c for c in cands if _lead_name(c.first_name, c.last_name) == name]
            return (same or cands or [None])[0].id if (same or cands) else None

        age_labels = dict(LevelTest.AgeGroup.choices)
        people, by_age, by_class, by_term = [], {}, {}, {}
        for t in tests:
            test_day = timezone.localtime(t.test_date).date() if t.test_date else timezone.localtime(t.created_at).date()
            sid = student_of(t)
            chosen = None
            for e in enrolls.get(sid, []) if sid else []:
                term = e.class_slot.term
                if term is None or (term.end_date and term.end_date < test_day):
                    continue
                chosen = e
                break
            slot = chosen.class_slot if chosen else None
            age = age_labels.get(t.age_group, 'نامشخص')
            agg = by_age.setdefault(age, {'age_group': age, 'completed': 0, 'registered': 0})
            agg['completed'] += 1
            term_key = slot.term_id if slot and slot.term else None
            term_label = slot.term.title if slot and slot.term else 'بدون ترم / ثبت‌نام‌نشده'
            term_agg = by_term.setdefault(term_key or 'none', {'term_id': term_key, 'term_title': term_label, 'completed': 0, 'registered': 0})
            term_agg['completed'] += 1
            row = {
                'id': t.id, 'name': f'{t.first_name} {t.last_name}'.strip(), 'national_code': t.national_code, 'phone': t.phone,
                'age_group': age, 'level': t.level or '', 'test_date': t.test_date_jalali or '',
                'registered': bool(chosen),
                'class_number': slot.number if slot else None, 'class_level': (slot.assigned_level or '') if slot else '',
                'day': slot.day_type_display if slot else '', 'time_slot': (slot.time_slot or '') if slot else '',
                'teacher': (slot.teacher_name or '') if slot else '', 'term_title': slot.term.title if slot and slot.term else '',
            }
            people.append(row)
            if chosen:
                agg['registered'] += 1
                term_agg['registered'] += 1
                key = slot.id
                c = by_class.setdefault(key, {
                    'class_slot': slot.id, 'number': slot.number, 'level': slot.assigned_level or '', 'day': row['day'],
                    'time_slot': row['time_slot'], 'teacher': row['teacher'], 'term_title': row['term_title'], 'count': 0, 'names': [],
                })
                c['count'] += 1
                c['names'].append(row['name'])
        total, reg = len(people), sum(1 for p in people if p['registered'])
        for a in by_age.values():
            a['percent'] = round(a['registered'] * 100 / a['completed'], 1) if a['completed'] else 0
        for item in by_term.values():
            item['not_registered'] = item['completed'] - item['registered']
            item['percent'] = round(item['registered'] * 100 / item['completed'], 1) if item['completed'] else 0
        return Response({
            'totals': {'completed': total, 'registered': reg, 'not_registered': total - reg, 'percent': round(reg * 100 / total, 1) if total else 0},
            'by_age_group': list(by_age.values()),
            'by_term': list(by_term.values()),
            'by_class': sorted(by_class.values(), key=lambda c: (-c['count'], c['number'] or 0)),
            'people': people,
        })
