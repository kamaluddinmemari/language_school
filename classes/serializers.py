from rest_framework import serializers
from accounts.models import ClassRequest, User, persian_only_validator
from accounts.validators import username_validator, password_validator
from classes.models import ClassSession


ACTIVE_IDENTITY_STATUSES = [ClassRequest.Status.PENDING, ClassRequest.Status.REFERRED, ClassRequest.Status.CONFIRMED]


def normalize_identity(value):
    """برای مقایسه‌ی هویت، فاصله‌ها و ارقام فارسی/عربی را یکسان می‌کند."""
    value = str(value or '').strip()
    return value.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')).replace(' ', '').replace('\u200c', '')


def _urgent_allowed(class_type, payment_status):
    """«فوری / عجله دارد» فقط برای خصوصیِ پرداخت‌شده و جبرانی (با هر وضعیت پرداخت)."""
    if class_type == ClassRequest.ClassType.MAKEUP:
        return True
    return class_type == ClassRequest.ClassType.PRIVATE and payment_status == ClassRequest.PaymentStatus.PAID


def validate_active_identity(attrs, *, student=None):
    """برای یک هویت و نوع کلاس، تا وقتی کلاس مختومه/رد/کنسل نشده است، ثبت تکراری ممنوع است."""
    first_name = normalize_identity(attrs.get('first_name') or getattr(student, 'first_name', ''))
    last_name = normalize_identity(attrs.get('last_name') or getattr(student, 'last_name', ''))
    national_code = normalize_identity(attrs.get('national_code') or getattr(student, 'national_code', ''))
    class_type = attrs.get('class_type')
    full_name = normalize_identity(f'{first_name}{last_name}')
    if not full_name or not national_code or not class_type:
        return
    qs = ClassRequest.objects.filter(status__in=ACTIVE_IDENTITY_STATUSES, class_type=class_type).select_related('student')
    for existing in qs:
        existing_name = normalize_identity(existing.student.first_name + existing.student.last_name)
        existing_national = normalize_identity(existing.student.national_code)
        if full_name == existing_name and national_code == existing_national:
            raise serializers.ValidationError({'error': 'برای این دانش‌آموز با این نوع کلاس، یک کلاس فعال وجود دارد و هنوز مختومه نشده است.'})


class ClassSessionSerializer(serializers.ModelSerializer):
    completed_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = ClassSession
        fields = [
            'id', 'session_number', 'completed_at', 'completed_at_jalali', 'student_confirmed', 'student_rejected', 'held',
            'notes', 'is_cancelled', 'cancelled_at', 'cancel_reason',
        ]


class StudentInfoSerializer(serializers.ModelSerializer):
    """اطلاعات کامل دانش‌آموز — فقط برای مدیر قابل مشاهده است"""
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'phone', 'phone2', 'national_code']


class TeacherInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'phone', 'teacher_level']


class ClassRequestAdminSerializer(serializers.ModelSerializer):
    """نمایش و ویرایش کامل — فقط برای مدیر"""
    student_info = StudentInfoSerializer(source='student', read_only=True)
    teacher_info = TeacherInfoSerializer(source='teacher', read_only=True)
    assigned_teachers_info = TeacherInfoSerializer(source='assigned_teachers', many=True, read_only=True)
    accepted_teachers_info = TeacherInfoSerializer(source='accepted_teachers', many=True, read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    completed_at_jalali = serializers.ReadOnlyField()
    class_date_jalali = serializers.ReadOnlyField()
    payment_confirmed_at_jalali = serializers.ReadOnlyField()
    refund_date_jalali = serializers.ReadOnlyField()
    refund_recorded_by_name = serializers.SerializerMethodField()
    is_refunded = serializers.BooleanField(read_only=True)
    refund_amount = serializers.IntegerField(read_only=True)
    refund_date = serializers.DateTimeField(read_only=True)
    refund_reference = serializers.CharField(read_only=True)
    refund_note = serializers.CharField(read_only=True)
    refund_recorded_by = serializers.PrimaryKeyRelatedField(read_only=True)
    sessions = ClassSessionSerializer(many=True, read_only=True)
    # خواسته: با کنسل‌شدنِ جلسات (۲ به بعد)، سهم واقعیِ استاد/مدرسه طبق جلساتِ باقی‌مانده
    # و اختلافش با مبلغِ کلاسِ «از ابتدا با همین تعداد جلسه ست‌شده» (بدون کنسلی) نمایش داده شود.
    cancelled_session_count = serializers.ReadOnlyField()
    active_session_count = serializers.ReadOnlyField()
    effective_total_price = serializers.ReadOnlyField()
    effective_teacher_share = serializers.ReadOnlyField()
    effective_school_share = serializers.ReadOnlyField()
    teacher_share_difference_from_original = serializers.ReadOnlyField()
    total_price_difference_from_original = serializers.ReadOnlyField()

    def to_internal_value(self, data):
        # ورودی فرم هنگام انتقال paid → unpaid تاریخ پرداخت را به شکل رشته‌ی خالی می‌فرستاد؛
        # DateTimeField رشته‌ی خالی را نمی‌پذیرد، پس آن را به null تبدیل می‌کنیم.
        if data.get('payment_confirmed_at') == '':
            data = data.copy()
            data['payment_confirmed_at'] = None
        return super().to_internal_value(data)

    def get_refund_recorded_by_name(self, obj):
        return obj.refund_recorded_by.get_full_name() if obj.refund_recorded_by else ''

    def validate(self, attrs):
        payment_status = attrs.get('payment_status', getattr(self.instance, 'payment_status', None))
        payment_method = attrs.get('payment_method', getattr(self.instance, 'payment_method', ''))
        payment_confirmed_at = attrs.get('payment_confirmed_at', getattr(self.instance, 'payment_confirmed_at', None))
        payment_reference = attrs.get('payment_reference', getattr(self.instance, 'payment_reference', ''))
        if payment_status == ClassRequest.PaymentStatus.PAID:
            if not payment_method or not payment_confirmed_at:
                raise serializers.ValidationError({'payment_status': 'برای پرداخت‌شده، نوع پرداخت و تاریخ و ساعت پرداخت الزامی است.'})
            # فقط پرداخت کارت‌به‌کارت شناسه‌ی پرداخت می‌خواهد؛ نقدی و پوز نیازی به شناسه ندارند
            if payment_method == ClassRequest.PaymentMethod.CARD_TO_CARD and not str(payment_reference or '').strip():
                raise serializers.ValidationError({'payment_reference': 'برای پرداخت کارت‌به‌کارت، شناسه پرداخت الزامی است.'})
        return attrs

    class Meta:
        model = ClassRequest
        fields = [
            'id', 'student', 'student_info', 'teacher', 'teacher_info',
            'assigned_teachers', 'assigned_teachers_info',
            'accepted_teachers', 'accepted_teachers_info',
            'class_type', 'custom_class_type', 'is_online', 'meeting_link', 'language_level',
            'proposed_time', 'class_date', 'class_date_jalali', 'class_date_approved',
            'teacher_coordinated', 'student_coordinated',
            'workflow_stage', 'teacher_assigned_at', 'teacher_proposed_at', 'teacher_proposed_at_jalali',
            'student_time_confirmed', 'student_time_rejected',
            'stage1_notes', 'stage2_notes', 'stage3_notes', 'stage4_notes',
            'manual_priority', 'force_last', 'contact_no_answer',
            'is_urgent',
            'suggested_teacher_name', 'group_key', 'group_size',
            'session_duration', 'session_count', 'sessions',
            'cancelled_session_count', 'active_session_count',
            'total_price', 'teacher_share', 'school_share',
            'effective_total_price', 'effective_teacher_share', 'effective_school_share',
            'teacher_share_difference_from_original', 'total_price_difference_from_original',
            'teacher_payment_status', 'teacher_payment_date', 'teacher_payment_amount',
            'receipt', 'amount', 'payment_status',
            'payment_method', 'payment_reference', 'payment_confirmed_at', 'payment_confirmed_at_jalali',
            'is_refunded', 'refund_amount', 'refund_date', 'refund_date_jalali', 'refund_reference', 'refund_note',
            'refund_recorded_by', 'refund_recorded_by_name',
            'sequence_warning', 'sequence_warning_details',
            'status', 'notes',
            'is_completed', 'completed_at', 'completed_at_jalali',
            'satisfaction', 'satisfaction_text', 'satisfaction_approved',
            'source_level_test',
            'created_at', 'created_at_jalali', 'updated_at',
        ]

    def update(self, instance, validated_data):
        # تغییر وضعیت پرداخت باید بلافاصله در صف/رنگ/فیلتر منعکس شود. هنگام برگشت
        # از پرداخت‌شده به پرداخت‌نشده، اطلاعات پرداخت و اولویت دستی قبلی پاک می‌شوند
        # تا کلاس طبق قواعد عادیِ کلاس‌های پرداخت‌نشده دوباره جای‌گذاری شود.
        next_status = validated_data.get('payment_status', instance.payment_status)
        if validated_data.get('is_urgent') and not _urgent_allowed(instance.class_type, next_status):
            raise serializers.ValidationError({'is_urgent': 'وضعیت «فوری» فقط برای کلاس خصوصیِ پرداخت‌شده یا کلاس جبرانی قابل ثبت است.'})
        if 'payment_status' in validated_data:
            next_payment_status = validated_data['payment_status']
            if not _urgent_allowed(instance.class_type, next_payment_status):
                validated_data['is_urgent'] = False
            if next_payment_status == ClassRequest.PaymentStatus.PAID:
                validated_data['force_last'] = False
                validated_data['manual_priority'] = None
            else:
                validated_data['payment_method'] = ''
                validated_data['payment_reference'] = ''
                validated_data['payment_confirmed_at'] = None
                if instance.payment_status == ClassRequest.PaymentStatus.PAID:
                    validated_data['force_last'] = False
                    validated_data['manual_priority'] = None
        return super().update(instance, validated_data)

    read_only_fields = [
            'status', 'created_at', 'updated_at', 'total_price', 'teacher_proposed_at_jalali',
            'teacher_share', 'school_share', 'is_completed',
            'accepted_teachers', 'source_level_test',
            'cancelled_session_count', 'active_session_count',
            'effective_total_price', 'effective_teacher_share', 'effective_school_share',
            'teacher_share_difference_from_original', 'total_price_difference_from_original',
        ]
        # نکته: completed_at عمداً از read_only خارج شده تا مدیر همیشه بتونه
        # تاریخ و ساعت اتمام کلاس رو از پنل ویرایش کنه (حتی بعد از مختومه شدن)


class ClassRequestAdminCreateSerializer(serializers.Serializer):
    """
    ثبت درخواست کلاس از طریق کانتر توسط مدیر/کارمند.
    اگر دانش‌آموزی با این شماره موبایل قبلاً ثبت نشده باشد، خودکار ساخته می‌شود.
    """
    first_name = serializers.CharField(max_length=150, validators=[persian_only_validator])
    last_name = serializers.CharField(max_length=150, validators=[persian_only_validator])
    national_code = serializers.CharField(max_length=10)
    phone = serializers.CharField(max_length=11)
    class_type = serializers.ChoiceField(choices=ClassRequest.ClassType.choices, default=ClassRequest.ClassType.PRIVATE)
    custom_class_type = serializers.CharField(max_length=100, required=False, allow_blank=True)
    is_online = serializers.BooleanField(required=False, default=False)
    meeting_link = serializers.CharField(max_length=500, required=False, allow_blank=True)
    language_level = serializers.CharField(max_length=50)
    proposed_time = serializers.CharField(max_length=100, required=False, allow_blank=True)
    class_date = serializers.DateTimeField(required=False, allow_null=True)
    group_key = serializers.CharField(max_length=40, required=False, allow_blank=True)
    group_size = serializers.IntegerField(required=False, min_value=1, default=1)
    session_count = serializers.IntegerField(min_value=1)
    session_duration = serializers.ChoiceField(
        choices=ClassRequest.SessionDuration.choices,
        default=ClassRequest.SessionDuration.ONE_HALF
    )
    payment_status = serializers.ChoiceField(
        choices=ClassRequest.PaymentStatus.choices,
        default=ClassRequest.PaymentStatus.UNPAID
    )
    sequence_warning = serializers.BooleanField(required=False, default=False)
    sequence_warning_details = serializers.JSONField(required=False, default=dict)
    is_urgent = serializers.BooleanField(required=False, default=False)
    payment_method = serializers.ChoiceField(choices=ClassRequest.PaymentMethod.choices, required=False, allow_blank=True)
    payment_reference = serializers.CharField(max_length=100, required=False, allow_blank=True)
    payment_confirmed_at = serializers.DateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    suggested_teacher_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    username = serializers.CharField(max_length=150, required=False, allow_blank=True, validators=[username_validator])
    password = serializers.CharField(max_length=128, required=False, allow_blank=True, validators=[password_validator])

    def validate(self, attrs):
        validate_active_identity(attrs)
        if attrs.get('payment_status') == ClassRequest.PaymentStatus.PAID:
            if not attrs.get('payment_method') or not attrs.get('payment_confirmed_at'):
                raise serializers.ValidationError({'payment_status': 'برای پرداخت‌شده، نوع پرداخت و تاریخ و ساعت پرداخت الزامی است.'})
            if attrs.get('payment_method') == ClassRequest.PaymentMethod.CARD_TO_CARD and not str(attrs.get('payment_reference') or '').strip():
                raise serializers.ValidationError({'payment_reference': 'برای پرداخت کارت‌به‌کارت، شناسه پرداخت الزامی است.'})
        return attrs


    @staticmethod
    def _resolve_student(phone, first_name, last_name, national_code, username, password):
        """
        پیدا کردن یا ساختن دانش‌آموز بدون خطای ۵۰۰:
        - شماره موبایل یکتا نیست (خواهر/برادر با شماره‌ی والدین)، پس get_or_create(phone=...)
          با دو رکورد MultipleObjectsReturned می‌داد و پاسخ HTML برمی‌گشت.
        - کد ملی یکتاست؛ اگر قبلاً برای کسی ثبت شده باشد همان فرد استفاده می‌شود.
        - نام کاربری پیش‌فرض (همان موبایل) ممکن است قبلاً گرفته شده باشد؛ پسوند عددی می‌گیرد.
        """
        from django.db import IntegrityError, transaction

        if national_code:
            existing = User.objects.filter(national_code=national_code).first()
            if existing:
                if existing.role != User.Role.STUDENT:
                    raise serializers.ValidationError({'error': 'این کد ملی برای یک کاربر غیر دانش‌آموز ثبت شده است.'})
                return existing

        wanted_name = normalize_identity(f'{first_name}{last_name}')
        for candidate in User.objects.filter(phone=phone, role=User.Role.STUDENT):
            if normalize_identity(f'{candidate.first_name}{candidate.last_name}') == wanted_name:
                if national_code and not candidate.national_code:
                    candidate.national_code = national_code
                    candidate.save(update_fields=['national_code'])
                return candidate

        base_username = username
        candidate_username = base_username
        suffix = 1
        while User.objects.filter(username=candidate_username).exists():
            suffix += 1
            candidate_username = f'{base_username}_{suffix}'[:150]

        try:
            with transaction.atomic():
                student = User(
                    username=candidate_username, first_name=first_name, last_name=last_name,
                    phone=phone, national_code=national_code, role=User.Role.STUDENT, needs_editing=True,
                )
                if password:
                    student.set_password(password)
                else:
                    student.set_unusable_password()
                student.save()
        except IntegrityError:
            raise serializers.ValidationError({'error': 'ثبت دانش‌آموز جدید ممکن است با اطلاعات تکراری (کد ملی یا نام کاربری) در تعارض باشد؛ اطلاعات را بررسی کنید.'})
        return student

    def create(self, validated_data):
        phone = validated_data.pop('phone')
        first_name = validated_data.pop('first_name')
        last_name = validated_data.pop('last_name')
        national_code = validated_data.pop('national_code', None) or None
        username = validated_data.pop('username', '') or phone
        password = validated_data.pop('password', '')

        # «فوری» برای کلاس خصوصیِ پرداخت‌شده و هر کلاس جبرانی معنا دارد.
        if not _urgent_allowed(validated_data.get('class_type'), validated_data.get('payment_status')):
            validated_data['is_urgent'] = False

        student = self._resolve_student(phone, first_name, last_name, national_code, username, password)
        return ClassRequest.objects.create(student=student, **validated_data)

    def to_representation(self, instance):
        return ClassRequestAdminSerializer(instance, context=self.context).data


class ClassRequestCreateSerializer(serializers.ModelSerializer):
    """ثبت درخواست کلاس خصوصی/جبرانی توسط خود دانش‌آموز از طریق اپ"""

    class Meta:
        model = ClassRequest
        fields = [
            'class_type', 'language_level', 'proposed_time', 'is_online',
            'session_count', 'session_duration', 'receipt', 'notes',
        ]
        extra_kwargs = {
            'receipt': {'required': True},  # تصویر فیش واریزی الزامی است
        }

    def validate(self, attrs):
        validate_active_identity(attrs, student=self.context['request'].user)
        return attrs

    def to_representation(self, instance):
        return ClassRequestStudentSerializer(instance, context=self.context).data


class ClassRequestTeacherSerializer(serializers.ModelSerializer):
    """
    نمایش محدود برای استادی که کلاس به او ارجاع شده.
    عمداً اطلاعات تماس دانش‌آموز (موبایل، کد ملی) نمایش داده نمی‌شود.
    نظر متنی دانش‌آموز فقط بعد از تایید مدیر قابل مشاهده است.
    """
    student_name = serializers.SerializerMethodField()
    has_accepted = serializers.SerializerMethodField()
    is_assigned_to_me = serializers.SerializerMethodField()
    satisfaction = serializers.SerializerMethodField()
    satisfaction_text = serializers.SerializerMethodField()
    created_at_jalali = serializers.ReadOnlyField()
    class_date_jalali = serializers.ReadOnlyField()
    sessions = ClassSessionSerializer(many=True, read_only=True)

    class Meta:
        model = ClassRequest
        fields = [
            'id', 'student_name', 'class_type', 'custom_class_type', 'is_online', 'meeting_link',
            'language_level', 'proposed_time', 'class_date', 'class_date_jalali',
            'session_duration', 'session_count', 'sessions', 'total_price', 'teacher_share',
            'status', 'has_accepted', 'is_assigned_to_me', 'is_completed',
            'satisfaction', 'satisfaction_text',
            'created_at', 'created_at_jalali',
        ]

    def get_student_name(self, obj):
        return obj.student.get_full_name()

    def get_has_accepted(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.accepted_teachers.filter(pk=request.user.pk).exists()

    def get_is_assigned_to_me(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.teacher_id == request.user.id

    def get_satisfaction(self, obj):
        if not obj.satisfaction_approved:
            return None
        if not self.get_is_assigned_to_me(obj):
            return None
        return obj.satisfaction

    def get_satisfaction_text(self, obj):
        if not obj.satisfaction_approved:
            return None
        if not self.get_is_assigned_to_me(obj):
            return None
        return obj.satisfaction_text


class ClassRequestStudentSerializer(serializers.ModelSerializer):
    """
    نمایش برای دانش‌آموز.
    نام استاد فقط بعد از تایید نهایی مدیر (وضعیت confirmed به بعد) نشان داده می‌شود.
    """
    teacher_name = serializers.SerializerMethodField()
    meeting_link = serializers.SerializerMethodField()
    created_at_jalali = serializers.ReadOnlyField()
    class_date_jalali = serializers.ReadOnlyField()
    sessions = ClassSessionSerializer(many=True, read_only=True)

    class Meta:
        model = ClassRequest
        fields = [
            'id', 'teacher_name', 'class_type', 'custom_class_type', 'is_online', 'meeting_link',
            'language_level', 'proposed_time', 'class_date', 'class_date_jalali',
            'session_duration', 'session_count', 'sessions', 'amount', 'total_price',
            'payment_status', 'status', 'notes', 'receipt',
            'satisfaction', 'satisfaction_text',
            'created_at', 'created_at_jalali',
        ]
        read_only_fields = ['status', 'created_at', 'total_price']

    def get_teacher_name(self, obj):
        if obj.status in [ClassRequest.Status.CONFIRMED, ClassRequest.Status.COMPLETED] and obj.teacher:
            return obj.teacher.get_full_name()
        return None

    def get_meeting_link(self, obj):
        if obj.is_online and obj.status in [ClassRequest.Status.CONFIRMED, ClassRequest.Status.COMPLETED]:
            return obj.meeting_link
        return ''
