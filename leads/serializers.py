from rest_framework import serializers
from .models import NewLead, UnregisteredStudent, UnregisteredStudentFollowup, Debtor, DebtorFollowup, DiscountedPerson


class NewLeadSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    followup1_at_jalali = serializers.ReadOnlyField()
    followup2_at_jalali = serializers.ReadOnlyField()
    registered_at_jalali = serializers.ReadOnlyField()
    cancelled_at_jalali = serializers.ReadOnlyField()
    followup1_by_name = serializers.SerializerMethodField()
    followup2_by_name = serializers.SerializerMethodField()
    birth_date_jalali = serializers.ReadOnlyField()

    def get_followup1_by_name(self, obj):
        return obj.followup1_by.get_full_name() if obj.followup1_by else None

    def get_followup2_by_name(self, obj):
        return obj.followup2_by.get_full_name() if obj.followup2_by else None

    class Meta:
        model = NewLead
        fields = [
            'id', 'first_name', 'last_name', 'father_name', 'national_code', 'birth_date', 'birth_date_jalali', 'phone',
            'status', 'status_display',
            'followup1_at', 'followup1_at_jalali', 'followup1_by_name',
            'followup2_at', 'followup2_at_jalali', 'followup2_by_name',
            'registered_at', 'registered_at_jalali', 'cancelled_at', 'cancelled_at_jalali',
            'deposit_amount', 'deposit_paid_at', 'deposit_paid_at_jalali',
            'created_at', 'created_at_jalali', 'updated_at',
        ]
        read_only_fields = [
            'status', 'followup1_at', 'followup2_at', 'registered_at', 'cancelled_at',
            'deposit_paid_at', 'created_at', 'updated_at',
        ]


class UnregisteredFollowupSerializer(serializers.ModelSerializer):
    followed_up_at_jalali = serializers.ReadOnlyField()
    followed_up_by_name = serializers.SerializerMethodField()

    class Meta:
        model = UnregisteredStudentFollowup
        fields = ['id', 'followed_up_at', 'followed_up_at_jalali', 'followed_up_by_name', 'note']

    def get_followed_up_by_name(self, obj):
        if not obj.followed_up_by:
            return None
        return f"{obj.followed_up_by.first_name} {obj.followed_up_by.last_name}"


class UnregisteredStudentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    registered_at_jalali = serializers.ReadOnlyField()
    followup_count = serializers.ReadOnlyField()
    last_followup_at_jalali = serializers.ReadOnlyField()
    submitted_by_name = serializers.SerializerMethodField()
    followups = UnregisteredFollowupSerializer(many=True, read_only=True)

    class Meta:
        model = UnregisteredStudent
        fields = [
            'id', 'first_name', 'last_name', 'class_level', 'national_code', 'phone', 'tuition_price',
            'status', 'status_display', 'registered_at', 'registered_at_jalali',
            'followup_count', 'last_followup_at_jalali', 'followups',
            'submitted_by_name', 'created_at', 'created_at_jalali', 'updated_at',
        ]
        read_only_fields = ['status', 'registered_at', 'created_at', 'updated_at']

    def get_submitted_by_name(self, obj):
        if not obj.submitted_by:
            return None
        return f"{obj.submitted_by.first_name} {obj.submitted_by.last_name}"


class DebtorFollowupSerializer(serializers.ModelSerializer):
    followed_up_at_jalali = serializers.ReadOnlyField()
    followed_up_by_name = serializers.SerializerMethodField()

    class Meta:
        model = DebtorFollowup
        fields = ['id', 'followed_up_at', 'followed_up_at_jalali', 'followed_up_by_name', 'note']

    def get_followed_up_by_name(self, obj):
        if not obj.followed_up_by:
            return None
        return f"{obj.followed_up_by.first_name} {obj.followed_up_by.last_name}"


class DebtorSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    settled_at_jalali = serializers.ReadOnlyField()
    followup_count = serializers.ReadOnlyField()
    last_followup_at_jalali = serializers.ReadOnlyField()
    followups = DebtorFollowupSerializer(many=True, read_only=True)

    class Meta:
        model = Debtor
        fields = [
            'id', 'first_name', 'last_name', 'phone', 'class_level', 'debt_amount', 'description',
            'status', 'status_display', 'settled_at', 'settled_at_jalali',
            'followup_count', 'last_followup_at_jalali', 'followups',
            'created_at', 'created_at_jalali', 'updated_at',
        ]
        read_only_fields = ['status', 'settled_at', 'created_at', 'updated_at']


class DiscountedPersonSerializer(serializers.ModelSerializer):
    created_at_jalali = serializers.ReadOnlyField()
    valid_until_jalali = serializers.ReadOnlyField()
    is_expired = serializers.ReadOnlyField()

    class Meta:
        model = DiscountedPerson
        fields = [
            'id', 'first_name', 'last_name', 'national_code',
            'discount_percent', 'reason', 'valid_until', 'valid_until_jalali', 'is_expired',
            'created_at', 'created_at_jalali', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_discount_percent(self, value):
        if not (0 <= value <= 100):
            raise serializers.ValidationError('درصد تخفیف باید بین ۰ تا ۱۰۰ باشد')
        return value
