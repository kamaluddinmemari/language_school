from rest_framework import serializers
from .models import ClassSlot, ClassSlotEnrollment, TuitionSetting, DiscountedPerson, LevelRenewalApproval, Term, OnlineCourse, OnlineCourseEnrollment, PaymentSettings, ClassAttendance, OnlineCourseActionRequest


class TermSerializer(serializers.ModelSerializer):
    start_date_jalali = serializers.ReadOnlyField()
    end_date_jalali = serializers.ReadOnlyField()
    title = serializers.ReadOnlyField()
    class_count = serializers.SerializerMethodField()

    class Meta:
        model = Term
        fields = [
            'id', 'year', 'term_number', 'start_date', 'end_date',
            'start_date_jalali', 'end_date_jalali', 'title', 'class_count', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_class_count(self, obj):
        return obj.class_slots.count()


class ClassSlotSerializer(serializers.ModelSerializer):
    day_type_display = serializers.ReadOnlyField()
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)
    is_three_day = serializers.ReadOnlyField()
    capacity_status = serializers.ReadOnlyField()
    seats_left = serializers.ReadOnlyField()
    surplus = serializers.ReadOnlyField()
    real_enrolled_count = serializers.ReadOnlyField()
    real_capacity_status = serializers.ReadOnlyField()
    real_seats_left = serializers.ReadOnlyField()
    real_surplus = serializers.ReadOnlyField()
    updated_at_jalali = serializers.ReadOnlyField()
    term_title = serializers.SerializerMethodField()
    schedule_days_display = serializers.ReadOnlyField()
    delivery_pattern_display = serializers.ReadOnlyField()

    class Meta:
        model = ClassSlot
        fields = [
            'id', 'number', 'term', 'term_title', 'title', 'day_type', 'day_type_display', 'gender', 'gender_display',
            'capacity', 'teacher_name', 'previous_teacher_name', 'time_slot', 'schedule_kind', 'schedule_days', 'schedule_days_display', 'delivery_pattern', 'delivery_pattern_display', 'rotation_group', 'notes', 'is_three_day', 'is_online', 'meeting_link',
            'assigned_level', 'current_count', 'capacity_status', 'seats_left', 'surplus',
            'real_enrolled_count', 'real_capacity_status', 'real_seats_left', 'real_surplus',
            'updated_at', 'updated_at_jalali',
        ]
        read_only_fields = ['updated_at']

    def get_term_title(self, obj):
        return obj.term.title if obj.term_id else ''


class LevelDemandSerializer(serializers.Serializer):
    level = serializers.CharField()
    count = serializers.IntegerField(min_value=0)
    is_rotating_majority = serializers.BooleanField(default=False)
    student_status = serializers.ChoiceField(
        choices=['', 'rotating', 'only_morning', 'one_day_preference', 'hybrid_online', 'other'],
        required=False, default='', allow_blank=True
    )
    student_status_other = serializers.CharField(required=False, default='', allow_blank=True)
    # روز/ساعت/استاد ترجیحی برای همین سطح — اختیاری؛ اگر داده شود، اول بین اتاق‌های
    # موجود دقیقاً با همین روز+ساعت (و ترجیحاً همین استاد) دنبال جا می‌گردد
    preferred_day_type = serializers.CharField(required=False, default='', allow_blank=True)
    preferred_time_slot = serializers.CharField(required=False, default='', allow_blank=True)
    preferred_teacher_name = serializers.CharField(required=False, default='', allow_blank=True)


class AllocateClassesSerializer(serializers.Serializer):
    levels = LevelDemandSerializer(many=True)
    tolerance = serializers.IntegerField(min_value=0, default=0)
    thursday_only_count = serializers.IntegerField(min_value=0, default=0)
    friday_only_count = serializers.IntegerField(min_value=0, default=0)


class ConfirmOverflowSerializer(serializers.Serializer):
    level = serializers.CharField()
    count = serializers.IntegerField(min_value=1)
    target_slot_id = serializers.IntegerField()
    # کل باقیمانده‌ی واقعیِ همین سطح که pending_overflow گزارش کرده بود (نه فقط عددی که به
    # کلاس دوم می‌رود) — تا اگر مدیر کمتر از کل باقیمانده را وارد کند، بقیه گم نشوند.
    remaining_count = serializers.IntegerField(min_value=1, required=False)


class TransferSurplusSerializer(serializers.Serializer):
    target_slot_id = serializers.IntegerField(required=False)
    count = serializers.IntegerField(required=False, min_value=1)


class SpinOffSurplusSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=1)
    teacher_name = serializers.CharField(required=False, allow_blank=True, default='')
    number = serializers.IntegerField(required=False)
    day_type = serializers.CharField(required=False, allow_blank=True, default='')
    time_slot = serializers.CharField(required=False, allow_blank=True, default='')
    capacity = serializers.IntegerField(required=False, min_value=1)


class RoomCapacitySerializer(serializers.Serializer):
    """ظرفیت یک «کلاس فیزیکی» (شماره اتاق) — همین یک عدد برای همه‌ی ساعت‌های همون اتاق استفاده می‌شود.
    زوج به‌صورت پیش‌فرض دخترانه، فرد به‌صورت پیش‌فرض پسرانه در نظر گرفته می‌شود؛ ولی برای
    سه گروهِ «یک‌روز‌در‌هفته» (پنجشنبه‌صبح/پنجشنبه‌عصر/جمعه)، جنسیت هرکدام جدا و دلخواه انتخاب می‌شود
    (چون ممکنه هرکدوم از این ۱۱ کلاس فیزیکی دخترانه، پسرانه، یا مختلط باشه)."""
    number = serializers.IntegerField(min_value=1)
    capacity = serializers.IntegerField(min_value=1)
    thursday_morning_gender = serializers.ChoiceField(choices=ClassSlot.Gender.choices)
    thursday_evening_gender = serializers.ChoiceField(choices=ClassSlot.Gender.choices)
    friday_gender = serializers.ChoiceField(choices=ClassSlot.Gender.choices)


class BulkCreatePhysicalClassesSerializer(serializers.Serializer):
    """
    ورودی دکمه‌ی «ساخت کلاس فیزیکی/آنلاین» — ترمی که این کلاس‌ها به آن تعلق دارند + لیست شماره‌کلاس‌ها و
    ظرفیت هرکدام + فیلتر اختیاری اینکه کدوم ساعت‌ها اصلاً ساخته بشن + is_online (پیش‌فرض حضوری).
    """
    term_id = serializers.IntegerField()
    rooms = RoomCapacitySerializer(many=True)
    include_time_slots = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    include_thursday_morning = serializers.BooleanField(required=False, default=True)
    include_thursday_evening = serializers.BooleanField(required=False, default=True)
    include_friday = serializers.BooleanField(required=False, default=True)
    is_online = serializers.BooleanField(required=False, default=False)
    schedule_kind = serializers.ChoiceField(choices=ClassSlot.ScheduleKind.choices, required=False, default=ClassSlot.ScheduleKind.STANDARD)
    two_day_days = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    delivery_pattern = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    rotating_morning_time = serializers.CharField(required=False, allow_blank=True, default='')
    rotating_evening_time = serializers.CharField(required=False, allow_blank=True, default='')


class EnrollStudentSerializer(serializers.Serializer):
    student_id = serializers.IntegerField(required=False)
    national_code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    payment_method = serializers.ChoiceField(choices=ClassSlotEnrollment.PaymentMethod.choices)
    tuition_amount = serializers.IntegerField(min_value=0)
    discount_percent = serializers.IntegerField(min_value=0, max_value=100, required=False, default=0)
    pos_reference_code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    force_level_mismatch = serializers.BooleanField(required=False, default=False)

    def validate(self, data):
        if not data.get('student_id') and not data.get('national_code'):
            raise serializers.ValidationError('باید دانش‌آموز را از لیست پیشنهادی انتخاب کنید یا کد ملی را وارد کنید')
        if data['payment_method'] == ClassSlotEnrollment.PaymentMethod.POS and not data.get('pos_reference_code'):
            raise serializers.ValidationError({'pos_reference_code': 'کد پیگیری/ساعت دستگاه پوز الزامی است'})
        return data


class ClassSlotEnrollmentSerializer(serializers.ModelSerializer):
    student_first_name = serializers.CharField(source='student.first_name', read_only=True)
    student_last_name = serializers.CharField(source='student.last_name', read_only=True)
    student_father_name = serializers.CharField(source='student.father_name', read_only=True)
    student_national_code = serializers.CharField(source='student.national_code', read_only=True)
    student_phone = serializers.CharField(source='student.phone', read_only=True)
    student_birth_date = serializers.DateField(source='student.birth_date', read_only=True)
    student_gender = serializers.CharField(source='student.gender', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    created_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = ClassSlotEnrollment
        fields = [
            'id', 'class_slot', 'student', 'student_first_name', 'student_last_name',
            'student_father_name', 'student_national_code', 'student_phone',
            'student_birth_date', 'student_gender', 'payment_method', 'payment_method_display',
            'tuition_amount', 'discount_percent', 'pos_reference_code', 'receipt_image',
            'self_enrolled', 'payment_verified', 'created_at', 'created_at_jalali',
        ]
        read_only_fields = ['id', 'created_at']


class TuitionSettingSerializer(serializers.ModelSerializer):
    level_display = serializers.ReadOnlyField()
    age_group_display = serializers.ReadOnlyField()
    updated_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = TuitionSetting
        fields = ['id', 'level', 'level_display', 'age_group', 'age_group_display', 'amount', 'updated_at', 'updated_at_jalali']
        read_only_fields = ['updated_at']


class DiscountedPersonSerializer(serializers.ModelSerializer):
    student_first_name = serializers.CharField(source='student.first_name', read_only=True)
    student_last_name = serializers.CharField(source='student.last_name', read_only=True)
    student_national_code = serializers.CharField(source='student.national_code', read_only=True)
    student_phone = serializers.CharField(source='student.phone', read_only=True)
    class_slot_number = serializers.IntegerField(source='class_slot.number', read_only=True)
    online_course_title = serializers.CharField(source='online_course.title', read_only=True)
    updated_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = DiscountedPerson
        fields = [
            'id', 'student', 'student_first_name', 'student_last_name', 'student_national_code',
            'student_phone', 'discount_percent', 'class_slot', 'class_slot_number',
            'online_course', 'online_course_title', 'approved_tuition',
            'created_at', 'updated_at', 'updated_at_jalali',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PaymentSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentSettings
        fields = ['card_number', 'card_holder_name', 'bank_name', 'updated_at']
        read_only_fields = ['updated_at']


class ClassAttendanceSerializer(serializers.ModelSerializer):
    date_jalali = serializers.ReadOnlyField()
    student_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    marked_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ClassAttendance
        fields = [
            'id', 'class_slot', 'online_course', 'student', 'student_name', 'date', 'date_jalali',
            'status', 'status_display', 'is_present', 'note', 'marked_by_name', 'updated_at',
        ]
        read_only_fields = ['id', 'updated_at', 'marked_by_name']

    def get_student_name(self, obj):
        return obj.student.get_full_name()

    def get_marked_by_name(self, obj):
        return obj.marked_by.get_full_name() if obj.marked_by else ''


class RefundEnrollmentSerializer(serializers.Serializer):
    card_number = serializers.CharField(max_length=30)
    receiver_name = serializers.CharField(max_length=150)


class OnlineCourseSerializer(serializers.ModelSerializer):
    seats_left = serializers.ReadOnlyField()
    enrolled_count = serializers.ReadOnlyField()
    created_at_jalali = serializers.ReadOnlyField()
    session_date_jalali = serializers.ReadOnlyField()

    class Meta:
        model = OnlineCourse
        fields = [
            'id', 'title', 'price', 'session_count', 'capacity', 'teacher_name', 'schedule_note',
            'session_date', 'session_date_jalali', 'session_time',
            'meeting_link', 'is_active', 'seats_left', 'enrolled_count', 'created_at', 'created_at_jalali',
        ]
        read_only_fields = ['id', 'created_at']


class OnlineCourseEnrollSerializer(serializers.Serializer):
    student_id = serializers.IntegerField(required=False)
    national_code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    payment_method = serializers.ChoiceField(choices=OnlineCourseEnrollment.PaymentMethod.choices)
    price_paid = serializers.IntegerField(min_value=0)
    discount_percent = serializers.IntegerField(min_value=0, max_value=100, required=False, default=0)

    def validate(self, data):
        if not data.get('student_id') and not data.get('national_code'):
            raise serializers.ValidationError('یا شناسه‌ی دانش‌آموز یا کد ملی لازم است')
        return data


class OnlineCourseEnrollmentSerializer(serializers.ModelSerializer):
    student_first_name = serializers.CharField(source='student.first_name', read_only=True)
    student_last_name = serializers.CharField(source='student.last_name', read_only=True)
    student_national_code = serializers.CharField(source='student.national_code', read_only=True)
    student_phone = serializers.CharField(source='student.phone', read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    created_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = OnlineCourseEnrollment
        fields = [
            'id', 'course', 'course_title', 'student', 'student_first_name', 'student_last_name',
            'student_national_code', 'student_phone', 'payment_method', 'payment_method_display',
            'price_paid', 'discount_percent', 'receipt_image', 'self_enrolled', 'payment_verified',
            'created_at', 'created_at_jalali',
        ]
        read_only_fields = ['id', 'created_at']


class LevelRenewalApprovalSerializer(serializers.ModelSerializer):
    student_first_name = serializers.CharField(source='student.first_name', read_only=True)
    student_last_name = serializers.CharField(source='student.last_name', read_only=True)
    student_national_code = serializers.CharField(source='student.national_code', read_only=True)
    requested_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    reviewed_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = LevelRenewalApproval
        fields = [
            'id', 'student', 'student_first_name', 'student_last_name', 'student_national_code',
            'level', 'status', 'status_display', 'note', 'requested_by_name', 'reviewed_by_name',
            'created_at', 'created_at_jalali', 'reviewed_at', 'reviewed_at_jalali',
        ]
        read_only_fields = ['id', 'status', 'created_at', 'reviewed_at']

    def get_requested_by_name(self, obj):
        return f"{obj.requested_by.first_name} {obj.requested_by.last_name}" if obj.requested_by else '—'

    def get_reviewed_by_name(self, obj):
        return f"{obj.reviewed_by.first_name} {obj.reviewed_by.last_name}" if obj.reviewed_by else '—'


class TransferEnrollmentSerializer(serializers.Serializer):
    target_slot_id = serializers.IntegerField()


class OnlineCourseTransferSerializer(serializers.Serializer):
    target_course_id = serializers.IntegerField()


class OnlineCourseActionRequestSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    online_course_title = serializers.CharField(source='online_course.title', read_only=True)
    requested_target_course_title = serializers.CharField(source='requested_target_course.title', read_only=True, default=None)
    action_type_display = serializers.CharField(source='get_action_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    reviewed_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = OnlineCourseActionRequest
        fields = [
            'id', 'student', 'student_name', 'online_course', 'online_course_title', 'action_type', 'action_type_display',
            'card_number', 'receiver_name', 'requested_target_course', 'requested_target_course_title', 'reason',
            'status', 'status_display', 'admin_note', 'created_at', 'created_at_jalali', 'reviewed_at', 'reviewed_at_jalali',
        ]
        read_only_fields = ['id', 'status', 'admin_note', 'created_at', 'reviewed_at']

    def get_student_name(self, obj):
        return obj.student.get_full_name()


class OnlineCourseActionRequestCreateSerializer(serializers.Serializer):
    online_course_id = serializers.IntegerField()
    action_type = serializers.ChoiceField(choices=OnlineCourseActionRequest.ActionType.choices)
    card_number = serializers.CharField(max_length=30, required=False, allow_blank=True)
    receiver_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    requested_target_course_id = serializers.IntegerField(required=False)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)

    def validate(self, data):
        if data['action_type'] == OnlineCourseActionRequest.ActionType.REFUND:
            if not data.get('card_number') or not data.get('receiver_name'):
                raise serializers.ValidationError('برای درخواست استرداد، شماره کارت و نام گیرنده الزامی است')
        return data


class OnlineCourseActionRequestReviewSerializer(serializers.Serializer):
    target_course_id = serializers.IntegerField(required=False)
    admin_note = serializers.CharField(max_length=300, required=False, allow_blank=True)


class SplitClassSerializer(serializers.Serializer):
    student_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    random_count = serializers.IntegerField(required=False, min_value=1)

    def validate(self, data):
        if not data.get('student_ids') and not data.get('random_count'):
            raise serializers.ValidationError('باید یا لیست دانش‌آموزان مشخص یا تعداد تصادفی وارد شود')
        return data
