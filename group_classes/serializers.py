from rest_framework import serializers
from accounts.models import User
from accounts.validators import username_validator, password_validator
from .models import (
    GroupSession, GroupSessionParticipant, GroupSessionMeeting, GroupPriceSetting,
    GroupSessionAttendance, ensure_attendance_rows,
)


class StudentInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'phone', 'national_code', 'language_level']


class TeacherInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'phone', 'teacher_level']


class AttendanceSerializer(serializers.ModelSerializer):
    """حضور/غیاب + پرداخت هر شرکت‌کننده برای یک جلسه‌ی مجزا"""
    participant_id = serializers.IntegerField(source='participant.id', read_only=True)
    student_name = serializers.SerializerMethodField()

    class Meta:
        model = GroupSessionAttendance
        fields = ['id', 'participant_id', 'student_name', 'status', 'paid', 'updated_at']

    def get_student_name(self, obj):
        return f"{obj.participant.student.first_name} {obj.participant.student.last_name}"


class GroupSessionMeetingSerializer(serializers.ModelSerializer):
    """نسخه‌ی ساده — برای نمایش به دانش‌آموز (بدون افشای اطلاعات سایر شرکت‌کننده‌ها)"""
    completed_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = GroupSessionMeeting
        fields = ['id', 'meeting_number', 'completed_at', 'completed_at_jalali', 'notes']


class GroupSessionMeetingDetailSerializer(serializers.ModelSerializer):
    """نسخه‌ی کامل با حضور و غیاب هر شرکت‌کننده — برای مدیر و استاد"""
    completed_at_jalali = serializers.ReadOnlyField()
    attendances = serializers.SerializerMethodField()

    class Meta:
        model = GroupSessionMeeting
        fields = ['id', 'meeting_number', 'completed_at', 'completed_at_jalali', 'notes', 'attendances']

    def get_attendances(self, obj):
        rows = ensure_attendance_rows(obj)
        return AttendanceSerializer(rows, many=True).data


class GroupPriceSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupPriceSetting
        fields = ['id', 'price_for_two', 'price_for_three_plus', 'teacher_share_percent', 'school_share_percent', 'updated_at']
        read_only_fields = ['updated_at']


class ParticipantSerializer(serializers.ModelSerializer):
    """نمایش کامل هر شرکت‌کننده — برای مدیر و استاد"""
    student_info = StudentInfoSerializer(source='student', read_only=True)
    price_amount = serializers.ReadOnlyField()

    class Meta:
        model = GroupSessionParticipant
        fields = [
            'id', 'student', 'student_info', 'payment_status', 'receipt',
            'satisfaction', 'satisfaction_text', 'satisfaction_approved',
            'price_amount', 'joined_at',
        ]
        read_only_fields = ['student', 'joined_at']


class ParticipantSelfSerializer(serializers.ModelSerializer):
    """نمایش برای خودِ دانش‌آموز — فقط اطلاعات مربوط به خودش"""
    price_amount = serializers.ReadOnlyField()

    class Meta:
        model = GroupSessionParticipant
        fields = ['id', 'payment_status', 'satisfaction', 'satisfaction_text', 'satisfaction_approved', 'price_amount', 'joined_at']


class GroupSessionAdminSerializer(serializers.ModelSerializer):
    """نمایش/ویرایش کامل — برای مدیر و مسئول آموزش (که هم می‌تواند مثل مدیر همه را ببیند، هم اگر خودش استاد ارجاع‌شده‌ی یک کلاس باشد باید بخش استادی/حضورغیاب را هم ببیند)"""
    teacher_info = TeacherInfoSerializer(source='teacher', read_only=True)
    assigned_teachers_info = TeacherInfoSerializer(source='assigned_teachers', many=True, read_only=True)
    accepted_teachers_info = TeacherInfoSerializer(source='accepted_teachers', many=True, read_only=True)
    participants = ParticipantSerializer(many=True, read_only=True)
    participant_names = serializers.SerializerMethodField()
    meetings = GroupSessionMeetingDetailSerializer(many=True, read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    class_date_jalali = serializers.ReadOnlyField()
    completed_at_jalali = serializers.ReadOnlyField()
    participant_count = serializers.ReadOnlyField()
    seats_left = serializers.ReadOnlyField()
    price_per_person_computed = serializers.SerializerMethodField()
    price_per_session_computed = serializers.SerializerMethodField()
    total_price = serializers.ReadOnlyField()
    teacher_share_percent_effective = serializers.ReadOnlyField()
    teacher_share = serializers.ReadOnlyField()
    school_share = serializers.ReadOnlyField()
    # این دو فیلد فقط برای مدیر بی‌معنی‌اند ولی چون مسئول آموزش هم از همین سریالایزر پاسخ می‌گیرد
    # (چه به‌عنوان بیننده‌ی کلی، چه وقتی خودش استاد ارجاع‌شده‌ی یک کلاس است)، اینجا هم محاسبه می‌شوند
    # تا بخش پذیرفتن/رد‌کردن و حضورغیاب در اپ برایش هم مثل استاد فعال باشد.
    has_accepted = serializers.SerializerMethodField()
    is_assigned_to_me = serializers.SerializerMethodField()

    class Meta:
        model = GroupSession
        fields = [
            'id', 'session_type', 'title', 'language_level',
            'class_date', 'class_date_jalali', 'session_duration', 'session_count',
            'capacity', 'participant_count', 'seats_left',
            'price_per_person', 'price_per_session', 'price_per_person_computed', 'price_per_session_computed',
            'teacher_share_percent_override', 'teacher_share_percent_effective',
            'total_price', 'teacher_share', 'school_share',
            'teacher', 'teacher_info', 'assigned_teachers', 'assigned_teachers_info',
            'accepted_teachers', 'accepted_teachers_info', 'has_accepted', 'is_assigned_to_me',
            'status', 'notes', 'is_completed', 'completed_at', 'completed_at_jalali',
            'participants', 'participant_names', 'meetings',
            'created_at', 'created_at_jalali', 'updated_at',
        ]
        # نکته‌ی عمدی: completed_at از read_only خارج شده تا مدیر همیشه بتونه ویرایشش کنه (مثل فاز ۱)
        read_only_fields = ['status', 'created_at', 'updated_at', 'is_completed', 'accepted_teachers']

    def get_price_per_person_computed(self, obj):
        return obj.get_price_per_person()

    def get_price_per_session_computed(self, obj):
        return obj.get_price_per_session_amount()

    def get_participant_names(self, obj):
        return [f"{p.student.first_name} {p.student.last_name}" for p in obj.participants.all()]

    def get_has_accepted(self, obj):
        user = self.context['request'].user
        return obj.accepted_teachers.filter(pk=user.pk).exists()

    def get_is_assigned_to_me(self, obj):
        return obj.teacher_id == self.context['request'].user.pk


class GroupSessionCreateSerializer(serializers.ModelSerializer):
    """ساخت جلسه‌ی جدید — فقط توسط مدیر"""

    class Meta:
        model = GroupSession
        fields = [
            'id', 'session_type', 'title', 'language_level', 'class_date',
            'session_duration', 'session_count', 'capacity', 'price_per_person',
            'price_per_session', 'teacher_share_percent_override', 'notes',
        ]

    def validate(self, attrs):
        if attrs.get('session_type') == GroupSession.SessionType.WORKSHOP and attrs.get('price_per_person') is None:
            raise serializers.ValidationError({'price_per_person': 'برای ورکشاپ باید قیمت هرنفر (یا صفر برای رایگان) مشخص شود'})
        percent = attrs.get('teacher_share_percent_override')
        if percent is not None and not (0 <= percent <= 100):
            raise serializers.ValidationError({'teacher_share_percent_override': 'درصد باید بین ۰ تا ۱۰۰ باشد'})
        return attrs


class GroupSessionTeacherSerializer(serializers.ModelSerializer):
    """لیست برای استاد — شامل تعداد و اسم شرکت‌کننده‌ها، بدون اطلاعات تماس؛ شامل قیمت/سهم این کلاس"""
    participant_names = serializers.SerializerMethodField()
    participant_count = serializers.ReadOnlyField()
    meetings = GroupSessionMeetingDetailSerializer(many=True, read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    class_date_jalali = serializers.ReadOnlyField()
    has_accepted = serializers.SerializerMethodField()
    is_assigned_to_me = serializers.SerializerMethodField()
    price_per_person_computed = serializers.SerializerMethodField()
    price_per_session_computed = serializers.SerializerMethodField()
    total_price = serializers.ReadOnlyField()
    teacher_share_percent_effective = serializers.ReadOnlyField()
    teacher_share = serializers.ReadOnlyField()

    class Meta:
        model = GroupSession
        fields = [
            'id', 'session_type', 'title', 'language_level', 'class_date', 'class_date_jalali',
            'session_duration', 'session_count', 'meetings', 'capacity', 'participant_count', 'participant_names',
            'price_per_person_computed', 'price_per_session_computed', 'total_price',
            'teacher_share_percent_effective', 'teacher_share',
            'status', 'has_accepted', 'is_assigned_to_me', 'is_completed',
            'created_at', 'created_at_jalali',
        ]

    def get_participant_names(self, obj):
        return [f"{p.student.first_name} {p.student.last_name}" for p in obj.participants.all()]

    def get_price_per_person_computed(self, obj):
        return obj.get_price_per_person()

    def get_price_per_session_computed(self, obj):
        return obj.get_price_per_session_amount()

    def get_has_accepted(self, obj):
        user = self.context['request'].user
        return obj.accepted_teachers.filter(pk=user.pk).exists()

    def get_is_assigned_to_me(self, obj):
        return obj.teacher_id == self.context['request'].user.pk


class GroupSessionStudentSerializer(serializers.ModelSerializer):
    """لیست برای دانش‌آموز — جلسات باز برای ثبت‌نام + جلساتی که خودش عضوشونه"""
    my_participation = serializers.SerializerMethodField()
    price_per_person_computed = serializers.SerializerMethodField()
    teacher_name = serializers.SerializerMethodField()
    created_at_jalali = serializers.ReadOnlyField()
    class_date_jalali = serializers.ReadOnlyField()
    meetings = GroupSessionMeetingSerializer(many=True, read_only=True)

    class Meta:
        model = GroupSession
        fields = [
            'id', 'session_type', 'title', 'language_level', 'class_date', 'class_date_jalali',
            'session_duration', 'session_count', 'meetings', 'capacity', 'seats_left',
            'price_per_person_computed', 'teacher_name', 'status', 'my_participation',
            'created_at', 'created_at_jalali',
        ]

    def get_price_per_person_computed(self, obj):
        return obj.get_price_per_person()

    def get_teacher_name(self, obj):
        return f"{obj.teacher.first_name} {obj.teacher.last_name}" if obj.teacher else None

    def get_my_participation(self, obj):
        user = self.context['request'].user
        participation = obj.participants.filter(student=user).first()
        if not participation:
            return None
        return ParticipantSelfSerializer(participation).data
