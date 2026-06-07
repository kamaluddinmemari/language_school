from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import User


class RegisterSerializer(serializers.ModelSerializer):

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
            'national_code', 'role'
        ]

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError(
                {'password': 'رمزهای عبور یکسان نیستند'}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        user = User.objects.create_user(**validated_data)
        return user


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

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name',
            'phone', 'phone2', 'national_code', 'birth_date',
            'language_level', 'avatar', 'role'
        ]
        read_only_fields = ['username', 'role']