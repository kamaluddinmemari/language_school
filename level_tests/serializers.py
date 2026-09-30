from rest_framework import serializers
from django.utils import timezone
from datetime import timedelta
from .models import LevelTest, LevelTestPriceSetting
from .levels import LEVELS_BY_AGE_GROUP


def _ensure_slot_free(attrs, instance, force=False):
    """
    یک تایم در یک تاریخ فقط برای یک نفر: اگر همان تایم برای فرد دیگری رزرو یا مسدود باشد، خطا می‌دهد.
    force=True (دکمه‌ی «همین الان تعیین سطح می‌دهد» بعد از تأیید هشدار) این بررسی را نادیده می‌گیرد؛
    محدودیتِ رزرو در گذشته حتی با force هم برداشته نمی‌شود.
    """
    from .scheduling import find_reserved_conflict
    new_date = attrs.get('test_date')
    if not new_date:
        return
    if instance is not None and instance.test_date == new_date:
        return  # تغییری در تایم نداده
    if new_date < timezone.now() - timedelta(minutes=5):  # ۵ دقیقه تلورانس برای دکمه‌ی «همین الان»
        raise serializers.ValidationError({'test_date': 'امکان رزرو در تاریخ و ساعتِ گذشته وجود ندارد'})
    if force:
        return
    conflict = find_reserved_conflict(new_date, instance.pk if instance is not None else None)
    if conflict:
        if conflict.get('blocked'):
            message = conflict['message']
        elif conflict.get('busy'):
            message = f"این تایم به‌دلیل برنامه‌ی «{conflict['name']}» برای استاد اشغال است؛ در صورت تأیید، ثبت اجباری را تأیید کنید"
        else:
            message = f"این تایم قبلاً برای «{conflict['name']}» رزرو شده است؛ تایم دیگری انتخاب کنید یا ابتدا رزرو قبلی را لغو کنید"
        raise serializers.ValidationError({'test_date': message})


class LevelTestPriceSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = LevelTestPriceSetting
        fields = ['id', 'price', 'updated_at']
        read_only_fields = ['updated_at']


class LevelTestIntakeSerializer(serializers.ModelSerializer):
    """برای مرحله‌ی اول — فقط مدیر/کانتر، فقط مشخصات اولیه‌ی داوطلب (بدون نتیجه).
    test_date اختیاری است — همان‌جا هم می‌توان وقت تعیین سطح را رزرو کرد."""

    # فقط برای عبور از بررسی تداخلِ تایم — با تأیید صریح کاربر در هشدارِ «این تایم آزاد نیست»؛ در دیتابیس ذخیره نمی‌شود
    force_time_override = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = LevelTest
        fields = ['id', 'first_name', 'last_name', 'father_name', 'birth_date', 'national_code', 'phone', 'gender', 'student', 'price', 'payment_status', 'test_date', 'force_time_override']

    def validate(self, attrs):
        for field in ['first_name', 'last_name', 'father_name', 'birth_date', 'national_code', 'phone', 'gender']:
            if not attrs.get(field) and not (self.instance and getattr(self.instance, field, None)):
                raise serializers.ValidationError({field: 'این فیلد لازم است'})
        _ensure_slot_free(attrs, self.instance, force=attrs.pop('force_time_override', False))
        return attrs


class LevelTestSerializer(serializers.ModelSerializer):
    """نمایش کامل + ویرایش نتیجه (برای پنل مسئول آموزش و مدیر)"""
    test_date_jalali = serializers.ReadOnlyField()
    created_at_jalali = serializers.ReadOnlyField()
    birth_date_jalali = serializers.ReadOnlyField()
    age = serializers.ReadOnlyField()
    display_evaluator_name = serializers.ReadOnlyField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    mode_display = serializers.CharField(source='get_mode_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    payment_status_display = serializers.CharField(source='get_payment_status_display', read_only=True)
    reminder_24h_at = serializers.SerializerMethodField()
    reminder_2h_at = serializers.SerializerMethodField()
    reminder_24h_due = serializers.SerializerMethodField()
    reminder_2h_due = serializers.SerializerMethodField()
    reminder_24h_followed_at_jalali = serializers.SerializerMethodField()
    reminder_2h_followed_at_jalali = serializers.SerializerMethodField()
    assigned_class_display = serializers.ReadOnlyField()

    def _reminder_at(self, obj, hours):
        return obj.test_date - timedelta(hours=hours) if obj.test_date else None

    def get_reminder_24h_at(self, obj): return self._reminder_at(obj, 24)
    def get_reminder_2h_at(self, obj): return self._reminder_at(obj, 2)
    def get_reminder_24h_due(self, obj): return bool(obj.status == LevelTest.Status.PENDING and self._reminder_at(obj, 24) and self._reminder_at(obj, 24) <= timezone.now())
    def get_reminder_2h_due(self, obj): return bool(obj.status == LevelTest.Status.PENDING and self._reminder_at(obj, 2) and self._reminder_at(obj, 2) <= timezone.now())
    def get_reminder_24h_followed_at_jalali(self, obj): return obj.reminder_24h_followed_at_jalali
    def get_reminder_2h_followed_at_jalali(self, obj): return obj.reminder_2h_followed_at_jalali

    class Meta:
        model = LevelTest
        fields = [
            'id', 'first_name', 'last_name', 'father_name', 'birth_date', 'birth_date_jalali', 'age',
            'national_code', 'phone', 'gender', 'student', 'status', 'status_display', 'price', 'payment_status',
            'payment_status_display', 'mode', 'mode_display', 'meeting_link', 'self_requested',
            'payment_method', 'payment_method_display', 'receipt_image',
            'age_group', 'level', 'test_date', 'test_date_jalali',
            'assigned_class_slot', 'assigned_class_day', 'assigned_class_time',
            'assigned_class_teacher_name', 'assigned_class_display',
            'needs_private_class', 'private_sessions_needed',
            'needs_makeup_class', 'makeup_sessions_needed',
            'evaluator', 'evaluator_name', 'display_evaluator_name', 'notes', 'created_by',
            'created_at', 'created_at_jalali', 'updated_at', 'natoos_registered',
            'reminder_24h_at', 'reminder_2h_at', 'reminder_24h_due', 'reminder_2h_due',
            'reminder_24h_followed_at_jalali', 'reminder_2h_followed_at_jalali', 'followup_lead',
            'force_time_override',
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at', 'status', 'self_requested']

    # فقط برای عبور از بررسی تداخلِ تایم — با تأیید صریح کاربر در هشدارِ «این تایم آزاد نیست»؛ در دیتابیس ذخیره نمی‌شود
    force_time_override = serializers.BooleanField(write_only=True, required=False, default=False)

    def validate(self, attrs):
        age_group = attrs.get('age_group', getattr(self.instance, 'age_group', None))
        level = attrs.get('level', getattr(self.instance, 'level', None))
        if age_group and level:
            valid_levels = LEVELS_BY_AGE_GROUP.get(age_group, [])
            if level not in valid_levels:
                raise serializers.ValidationError({'level': f'این سطح متعلق به گروه سنی «{age_group}» نیست'})
        # ثبت نتیجه (تکمیل تعیین‌سطح) رزرو جدید نیست؛ فقط ویرایش/رزرو وقت یک داوطلبِ در انتظار بررسی می‌شود
        if not (level or (self.instance and self.instance.level)):
            _ensure_slot_free(attrs, self.instance, force=attrs.pop('force_time_override', False))
        else:
            attrs.pop('force_time_override', None)
        return attrs
