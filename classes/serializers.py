from rest_framework import serializers
from accounts.models import ClassRequest, User


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

    class Meta:
        model = ClassRequest
        fields = [
            'id', 'student', 'student_info', 'teacher', 'teacher_info',
            'assigned_teachers', 'assigned_teachers_info',
            'accepted_teachers', 'accepted_teachers_info',
            'class_type', 'custom_class_type', 'language_level',
            'proposed_time', 'class_date', 'class_date_approved',
            'session_duration', 'session_count',
            'total_price', 'teacher_share', 'school_share',
            'teacher_payment_status', 'teacher_payment_date', 'teacher_payment_amount',
            'receipt', 'amount', 'payment_status', 'status', 'notes',
            'is_completed', 'completed_at',
            'satisfaction', 'satisfaction_text', 'satisfaction_approved',
            'created_at', 'created_at_jalali', 'updated_at',
        ]
        read_only_fields = [
            'status', 'created_at', 'updated_at', 'total_price',
            'teacher_share', 'school_share', 'is_completed', 'completed_at',
            'accepted_teachers',
        ]


class ClassRequestAdminCreateSerializer(serializers.Serializer):
    """
    ثبت درخواست کلاس از طریق کانتر توسط مدیر/کارمند.
    اگر دانش‌آموزی با این شماره موبایل قبلاً ثبت نشده باشد، خودکار ساخته می‌شود.
    """
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    national_code = serializers.CharField(max_length=10)
    phone = serializers.CharField(max_length=11)
    class_type = serializers.ChoiceField(choices=ClassRequest.ClassType.choices, default=ClassRequest.ClassType.PRIVATE)
    custom_class_type = serializers.CharField(max_length=100, required=False, allow_blank=True)
    language_level = serializers.CharField(max_length=50)
    proposed_time = serializers.CharField(max_length=100, required=False, allow_blank=True)
    session_count = serializers.IntegerField(min_value=1)
    session_duration = serializers.ChoiceField(
        choices=ClassRequest.SessionDuration.choices,
        default=ClassRequest.SessionDuration.ONE_HOUR
    )
    payment_status = serializers.ChoiceField(
        choices=ClassRequest.PaymentStatus.choices,
        default=ClassRequest.PaymentStatus.UNPAID
    )
    notes = serializers.CharField(required=False, allow_blank=True)

    def create(self, validated_data):
        phone = validated_data.pop('phone')
        first_name = validated_data.pop('first_name')
        last_name = validated_data.pop('last_name')
        national_code = validated_data.pop('national_code', '')

        student, created = User.objects.get_or_create(
            phone=phone,
            defaults={
                'username': phone,
                'first_name': first_name,
                'last_name': last_name,
                'national_code': national_code,
                'role': User.Role.STUDENT,
            }
        )
        if created:
            student.set_unusable_password()
            student.save()

        return ClassRequest.objects.create(student=student, **validated_data)

    def to_representation(self, instance):
        return ClassRequestAdminSerializer(instance, context=self.context).data


class ClassRequestCreateSerializer(serializers.ModelSerializer):
    """ثبت درخواست کلاس خصوصی/جبرانی توسط خود دانش‌آموز از طریق اپ"""

    class Meta:
        model = ClassRequest
        fields = [
            'class_type', 'language_level',
            'session_count', 'session_duration', 'receipt', 'notes',
        ]
        extra_kwargs = {
            'receipt': {'required': True},  # تصویر فیش واریزی الزامی است
        }

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
    satisfaction = serializers.SerializerMethodField()
    satisfaction_text = serializers.SerializerMethodField()
    created_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = ClassRequest
        fields = [
            'id', 'student_name', 'class_type', 'custom_class_type',
            'language_level', 'proposed_time', 'class_date',
            'session_duration', 'session_count', 'total_price', 'teacher_share',
            'status', 'has_accepted', 'is_completed',
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

    def get_satisfaction(self, obj):
        return obj.satisfaction if obj.satisfaction_approved else None

    def get_satisfaction_text(self, obj):
        return obj.satisfaction_text if obj.satisfaction_approved else None


class ClassRequestStudentSerializer(serializers.ModelSerializer):
    """
    نمایش برای دانش‌آموز.
    نام استاد فقط بعد از تایید نهایی مدیر (وضعیت confirmed به بعد) نشان داده می‌شود.
    """
    teacher_name = serializers.SerializerMethodField()
    created_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = ClassRequest
        fields = [
            'id', 'teacher_name', 'class_type', 'custom_class_type',
            'language_level', 'proposed_time', 'class_date',
            'session_duration', 'session_count', 'amount', 'total_price',
            'payment_status', 'status', 'notes', 'receipt',
            'satisfaction', 'satisfaction_text',
            'created_at', 'created_at_jalali',
        ]
        read_only_fields = ['status', 'created_at', 'total_price']

    def get_teacher_name(self, obj):
        if obj.status in [ClassRequest.Status.CONFIRMED, ClassRequest.Status.COMPLETED] and obj.teacher:
            return obj.teacher.get_full_name()
        return None
