from rest_framework import serializers
from accounts.models import ClassRequest, User


class StudentInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'phone', 'phone2', 'national_code']


class ClassRequestSerializer(serializers.ModelSerializer):
    student_info = StudentInfoSerializer(source='student', read_only=True)

    class Meta:
        model = ClassRequest
        fields = [
            'id', 'student', 'student_info', 'teacher',
            'language_level', 'proposed_time', 'amount',
            'payment_status', 'status', 'notes', 'receipt', 'created_at'
        ]
        read_only_fields = ['status', 'created_at']


class ClassRequestCreateSerializer(serializers.ModelSerializer):

    class Meta:
        model = ClassRequest
        fields = [
            'language_level', 'proposed_time',
            'amount', 'notes', 'receipt'
        ]
        extra_kwargs = {
            'receipt': {'required': False}
        }


class ClassRequestAdminSerializer(serializers.ModelSerializer):
    student_info = StudentInfoSerializer(source='student', read_only=True)

    class Meta:
        model = ClassRequest
        fields = [
            'id', 'student', 'student_info', 'teacher',
            'language_level', 'proposed_time', 'amount',
            'payment_status', 'status', 'notes', 'receipt', 'created_at'
        ]