from rest_framework import serializers
from accounts.models import ClassRequest, User


class ClassRequestSerializer(serializers.ModelSerializer):

    class Meta:
        model = ClassRequest
        fields = [
            'id', 'student', 'teacher', 'language_level',
            'proposed_time', 'amount', 'payment_status',
            'status', 'notes', 'receipt', 'created_at'
        ]
        read_only_fields = ['status', 'created_at']


class ClassRequestCreateSerializer(serializers.ModelSerializer):

    class Meta:
        model = ClassRequest
        fields = [
            'language_level', 'proposed_time',
            'amount', 'notes', 'receipt'
        ]

    def validate(self, attrs):
        request = self.context.get('request')
        if request.user.role == 'student':
            if not attrs.get('receipt'):
                raise serializers.ValidationError(
                    {'receipt': 'بارگذاری فیش واریزی اجباری است'}
                )
        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['student'] = request.user
        return ClassRequest.objects.create(**validated_data)


class ClassRequestAdminSerializer(serializers.ModelSerializer):

    class Meta:
        model = ClassRequest
        fields = [
            'id', 'student', 'teacher', 'language_level',
            'proposed_time', 'amount', 'payment_status',
            'status', 'notes', 'receipt', 'created_at'
        ]