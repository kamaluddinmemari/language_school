from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import User, PriceSetting


class RegisterSerializer(serializers.ModelSerializer):
    """ثبت‌نام عمومی — همیشه با نقش دانش‌آموز (نقش از سمت کاربر قابل تغییر نیست)"""

    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password]
    )
    password2 = serializers.CharField(
        write_only=True,
        required=True
    )

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

    password = serializers.CharField(write_only=True, required=False, validators=[validate_password])
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
        validators=[validate_password]
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