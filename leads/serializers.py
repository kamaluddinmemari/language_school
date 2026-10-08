from rest_framework import serializers
from .models import NewLead, NewLeadFollowup, UnregisteredStudent, UnregisteredStudentFollowup, Debtor, DebtorFollowup, DiscountedPerson, normalize_national_code, normalize_phone


class NewLeadFollowupSerializer(serializers.ModelSerializer):
    followed_up_at_jalali = serializers.ReadOnlyField()
    followed_up_by_name = serializers.SerializerMethodField()

    class Meta:
        model = NewLeadFollowup
        fields = ['id', 'followed_up_at', 'followed_up_at_jalali', 'followed_up_by_name']

    def get_followed_up_by_name(self, obj):
        return obj.followed_up_by.get_full_name() if obj.followed_up_by else None


class NewLeadSerializer(serializers.ModelSerializer):
    followups = NewLeadFollowupSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    followup1_at_jalali = serializers.ReadOnlyField()
    followup2_at_jalali = serializers.ReadOnlyField()
    registered_at_jalali = serializers.ReadOnlyField()
    cancelled_at_jalali = serializers.ReadOnlyField()
    followup1_by_name = serializers.SerializerMethodField()
    followup2_by_name = serializers.SerializerMethodField()
    birth_date_jalali = serializers.ReadOnlyField()
    needs_level_test_marked_at_jalali = serializers.ReadOnlyField()
    age = serializers.ReadOnlyField()
    level_test = serializers.SerializerMethodField()

    def get_followup1_by_name(self, obj):
        return obj.followup1_by.get_full_name() if obj.followup1_by else None

    def get_followup2_by_name(self, obj):
        return obj.followup2_by.get_full_name() if obj.followup2_by else None

    def get_level_test(self, obj):
        """
        اولویت با آزمونی است که مستقیماً از طریق تیک «نیاز به تعیین سطح دارد» برای همین
        سرنخ ساخته شده (obj.level_test). اگر چنین چیزی نبود (سرنخ‌های قدیمی‌تر یا کسی که
        خودش جدا از این‌جا در صف تعیین سطح ثبت شده)، بر اساس کد ملی و در نبود آن شماره
        موبایل (هر دو پس از نرمال‌سازی) به‌صورت حدسی تطبیق داده می‌شود.
        رنگ: pending → زرد، completed+paid → سبز، completed+unpaid → قرمز.
        """
        from level_tests.models import LevelTest
        match = obj.level_test
        if not match:
            national = normalize_national_code(obj.national_code)
            phone = normalize_phone(obj.phone)
            by_national = self.context.get('level_test_by_national')
            by_phone = self.context.get('level_test_by_phone')
            if by_national is not None or by_phone is not None:
                candidates = by_national.get(national, []) if national else []
                if not candidates and phone:
                    candidates = by_phone.get(phone, [])
            else:
                all_tests = list(LevelTest.objects.all())
                candidates = [t for t in all_tests if national and normalize_national_code(t.national_code) == national]
                if not candidates and phone:
                    candidates = [t for t in all_tests if normalize_phone(t.phone) == phone]
            if not candidates:
                return None
            match = sorted(candidates, key=lambda t: (t.status == LevelTest.Status.COMPLETED, t.id))[-1]
        if match.status == LevelTest.Status.COMPLETED:
            badge = 'paid' if match.payment_status == LevelTest.PaymentStatus.PAID else 'unpaid'
        else:
            badge = 'pending'
        return {
            'id': match.id, 'status': match.status, 'status_display': match.get_status_display(),
            'payment_status': match.payment_status, 'level': match.level, 'age_group': match.age_group,
            'age_group_display': match.get_age_group_display() if match.age_group else None,
            'test_date': match.test_date, 'test_date_jalali': match.test_date_jalali,
            'badge': badge,
        }

    class Meta:
        model = NewLead
        fields = [
            'id', 'first_name', 'last_name', 'father_name', 'national_code', 'birth_date', 'birth_date_jalali', 'age', 'phone',
            'status', 'status_display', 'term', 'term_title',
            'followup1_at', 'followup1_at_jalali', 'followup1_by_name',
            'followup2_at', 'followup2_at_jalali', 'followup2_by_name',
            'registered_at', 'registered_at_jalali', 'cancelled_at', 'cancelled_at_jalali',
            'deposit_amount', 'deposit_paid_at', 'deposit_paid_at_jalali',
            'description', 'followups',
            'needs_level_test', 'needs_level_test_marked_at', 'needs_level_test_marked_at_jalali',
            'created_at', 'created_at_jalali', 'updated_at', 'level_test',
        ]
        read_only_fields = [
            'status', 'term_title', 'followup1_at', 'followup2_at', 'registered_at', 'cancelled_at',
            'deposit_paid_at', 'created_at', 'updated_at',
            'needs_level_test', 'needs_level_test_marked_at',
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
    term_title = serializers.ReadOnlyField()
    dropout_from_term_title = serializers.SerializerMethodField()
    misplaced_class_number = serializers.SerializerMethodField()

    def get_misplaced_class_number(self, obj):
        return obj.misplaced_from_slot.number if obj.misplaced_from_slot_id else None

    def get_dropout_from_term_title(self, obj):
        return obj.dropout_from_term.title if obj.dropout_from_term_id else None

    class Meta:
        model = UnregisteredStudent
        fields = [
            'id', 'first_name', 'last_name', 'class_level', 'national_code', 'phone', 'tuition_price',
            'status', 'status_display', 'registered_at', 'registered_at_jalali',
            'followup_count', 'last_followup_at_jalali', 'latest_level', 'followups',
            'submitted_by_name', 'term', 'term_title', 'claims_registered', 'claim_reviewed',
            'is_dropout', 'dropout_from_term', 'dropout_from_term_title',
            'is_misplaced', 'misplaced_from_slot', 'misplaced_class_number',
            'created_at', 'created_at_jalali', 'updated_at',
        ]
        read_only_fields = ['status', 'registered_at', 'created_at', 'updated_at', 'is_dropout', 'dropout_from_term', 'is_misplaced', 'misplaced_from_slot']

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
    term_title = serializers.ReadOnlyField()
    carried_from_term_title = serializers.SerializerMethodField()
    source_slot_number = serializers.SerializerMethodField()

    def get_carried_from_term_title(self, obj):
        return obj.carried_from_term.title if obj.carried_from_term_id else None

    def get_source_slot_number(self, obj):
        return obj.source_slot.number if obj.source_slot_id else None

    class Meta:
        model = Debtor
        fields = [
            'id', 'first_name', 'last_name', 'phone', 'class_level', 'debt_amount', 'description',
            'status', 'status_display', 'settled_at', 'settled_at_jalali',
            'followup_count', 'last_followup_at_jalali', 'followups',
            'term', 'term_title', 'claims_settled', 'claim_reviewed', 'created_at', 'created_at_jalali', 'updated_at',
            'student', 'awaiting_registration', 'carried_from_term', 'carried_from_term_title',
            'source_slot', 'source_slot_number',
        ]
        read_only_fields = ['status', 'settled_at', 'created_at', 'updated_at', 'student', 'awaiting_registration', 'carried_from_term', 'source_slot']
        extra_kwargs = {'phone': {'required': False, 'allow_blank': True}, 'debt_amount': {'required': False}}


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
