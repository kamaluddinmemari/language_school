from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import User, PriceSetting
from .validators import username_validator, password_validator


class RegisterSerializer(serializers.ModelSerializer):
    """ثبت‌نام عمومی — همیشه با نقش دانش‌آموز (نقش از سمت کاربر قابل تغییر نیست)"""

    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password, password_validator]
    )
    password2 = serializers.CharField(
        write_only=True,
        required=True
    )
    national_code = serializers.CharField(required=True, max_length=10)

    class Meta:
        model = User
        fields = [
            'username', 'password', 'password2',
            'first_name', 'last_name', 'phone',
            'national_code'
        ]

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError(
                {'password': 'رمزهای عبور یکسان نیستند'}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        validated_data['role'] = User.Role.STUDENT
        user = User.objects.create_user(**validated_data)
        return user


class TeacherSerializer(serializers.ModelSerializer):
    """ثبت/ویرایش اطلاعات استاد — فقط برای مدیر"""

    password = serializers.CharField(write_only=True, required=False, validators=[validate_password, password_validator])
    average_rating = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'password', 'first_name', 'last_name',
            'phone', 'phone2', 'teacher_level', 'avatar', 'average_rating'
        ]

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        validated_data['role'] = User.Role.TEACHER
        validated_data.setdefault('username', validated_data.get('phone'))
        validated_data.setdefault('national_code', None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class ForgotPasswordSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=11)


class ResetPasswordSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=11)
    code = serializers.CharField(max_length=6)
    new_password = serializers.CharField(
        write_only=True,
        validators=[validate_password, password_validator]
    )
    new_password2 = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password2']:
            raise serializers.ValidationError(
                {'new_password': 'رمزهای عبور یکسان نیستند'}
            )
        return attrs


class UserProfileSerializer(serializers.ModelSerializer):

    average_rating = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name',
            'phone', 'phone2', 'national_code', 'birth_date',
            'language_level', 'teacher_level', 'avatar', 'role',
            'average_rating'
        ]
        read_only_fields = ['username', 'role']


class PriceSettingSerializer(serializers.ModelSerializer):
    """تنظیمات قیمت فعلی — برای محاسبه‌ی پیش‌نمایش قیمت در اپ دانش‌آموز"""

    class Meta:
        model = PriceSetting
        fields = [
            'id', 'one_hour_price', 'one_half_hour_price',
            'teacher_share_percent', 'school_share_percent', 'updated_at'
        ]
        read_only_fields = ['updated_at']


class StudentSerializer(serializers.ModelSerializer):
    """
    نمایش/ساخت/ویرایش اطلاعات دانش‌آموزان برای مدیر (هم آن‌هایی که از کانتر ثبت شدند هم از طریق اپ).
    username/password اختیاری‌اند: اگر موقع ساخت پر نشوند، حساب بدون رمز قابل‌استفاده ساخته می‌شود
    (بعداً هم از همین‌جا با ویرایش قابل تنظیم است).
    """
    username = serializers.CharField(required=False, allow_blank=True, validators=[username_validator])
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, validators=[password_validator])
    has_app_account = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'first_name', 'last_name', 'father_name', 'phone', 'phone2',
            'national_code', 'birth_date', 'language_level',
            'username', 'password', 'has_app_account',
        ]

    def get_has_app_account(self, obj):
        return obj.has_usable_password()

    def validate_username(self, value):
        if not value:
            return value
        qs = User.objects.filter(username=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('این نام کاربری قبلاً استفاده شده است')
        return value

    def create(self, validated_data):
        password = validated_data.pop('password', '')
        username = validated_data.pop('username', '') or validated_data.get('phone')
        validated_data['role'] = User.Role.STUDENT
        user = User(username=username, **validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        username = validated_data.pop('username', None)
        if username:
            instance.username = username
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class UserRoleSerializer(serializers.ModelSerializer):
    """برای تغییر نقش یک کاربر (مثلاً کاربری که از اپ ثبت‌نام کرده) توسط مدیر"""

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'phone', 'role']
        read_only_fields = ['id', 'username', 'first_name', 'last_name', 'phone']