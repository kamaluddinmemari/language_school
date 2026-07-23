from rest_framework import serializers
from .models import EmployeeProfile, SalaryProfile, MonthlyPayroll, LeaveBalance, LeaveRequest


class EmployeeProfileSerializer(serializers.ModelSerializer):
    hire_date_jalali = serializers.ReadOnlyField()

    class Meta:
        model = EmployeeProfile
        fields = ['id', 'user', 'education_degree', 'education_field', 'hire_date', 'hire_date_jalali',
                   'address', 'marital_status', 'children_count', 'updated_at']
        read_only_fields = ['id', 'updated_at']


class SalaryProfileSerializer(serializers.ModelSerializer):
    gross_base_monthly = serializers.ReadOnlyField()
    components_breakdown = serializers.ReadOnlyField()
    user_full_name = serializers.SerializerMethodField()

    class Meta:
        model = SalaryProfile
        fields = ['id', 'user', 'user_full_name', 'work_year', 'base_salary', 'food_allowance',
                   'marriage_allowance', 'child_allowance', 'seniority_allowance', 'insurance_rate_30_days',
                   'gross_base_monthly', 'components_breakdown', 'updated_at']
        read_only_fields = ['id', 'updated_at']

    def get_user_full_name(self, obj):
        return obj.user.get_full_name()


class MonthlyPayrollSerializer(serializers.ModelSerializer):
    hourly_wage = serializers.ReadOnlyField()
    daily_wage = serializers.ReadOnlyField()
    insurance_amount = serializers.ReadOnlyField()
    overtime_pay = serializers.ReadOnlyField()
    absence_deduction = serializers.ReadOnlyField()
    undertime_deduction = serializers.ReadOnlyField()
    total_deductions = serializers.ReadOnlyField()
    gross_pay = serializers.ReadOnlyField()
    net_pay = serializers.ReadOnlyField()
    jalali_label = serializers.ReadOnlyField()
    acknowledged_at_jalali = serializers.ReadOnlyField()
    user_full_name = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyPayroll
        fields = [
            'id', 'user', 'user_full_name', 'jalali_year', 'jalali_month', 'jalali_label',
            'worked_hours', 'insurance_days', 'absence_days', 'absence_hours', 'undertime_hours',
            'overtime_hours', 'bonus_amount', 'notes',
            'hourly_wage', 'daily_wage', 'insurance_amount', 'overtime_pay', 'absence_deduction',
            'undertime_deduction', 'total_deductions', 'gross_pay', 'net_pay',
            'acknowledged_at', 'acknowledged_at_jalali', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'acknowledged_at', 'created_at', 'updated_at']

    def get_user_full_name(self, obj):
        return obj.user.get_full_name()

    def validate_jalali_month(self, value):
        if value < 1 or value > 12:
            raise serializers.ValidationError('ماه باید بین ۱ تا ۱۲ باشد')
        return value


class LeaveBalanceSerializer(serializers.ModelSerializer):
    used_days = serializers.ReadOnlyField()
    remaining_days = serializers.ReadOnlyField()
    monthly_hourly_breakdown = serializers.ReadOnlyField()
    user_full_name = serializers.SerializerMethodField()

    class Meta:
        model = LeaveBalance
        fields = ['id', 'user', 'user_full_name', 'jalali_year', 'annual_days', 'monthly_hourly_allowance',
                   'used_days', 'remaining_days', 'monthly_hourly_breakdown']
        read_only_fields = ['id']

    def get_user_full_name(self, obj):
        return obj.user.get_full_name()


class LeaveRequestSerializer(serializers.ModelSerializer):
    days_count = serializers.ReadOnlyField()
    start_date_jalali = serializers.ReadOnlyField()
    end_date_jalali = serializers.ReadOnlyField()
    requested_at_jalali = serializers.ReadOnlyField()
    decided_at_jalali = serializers.ReadOnlyField()
    user_full_name = serializers.SerializerMethodField()
    decided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = LeaveRequest
        fields = ['id', 'user', 'user_full_name', 'leave_type', 'leave_category', 'start_date', 'start_date_jalali',
                   'end_date', 'end_date_jalali', 'hours', 'days_count', 'reason', 'status',
                   'requested_at', 'requested_at_jalali', 'decided_at', 'decided_at_jalali', 'decided_by_name']
        read_only_fields = ['id', 'status', 'requested_at', 'decided_at', 'decided_by_name']

    def get_user_full_name(self, obj):
        return obj.user.get_full_name()

    def get_decided_by_name(self, obj):
        return obj.decided_by.get_full_name() if obj.decided_by else None

    def validate(self, data):
        leave_type = data.get('leave_type', getattr(self.instance, 'leave_type', 'daily'))
        if leave_type == 'hourly' and not data.get('hours') and not getattr(self.instance, 'hours', None):
            raise serializers.ValidationError({'hours': 'برای مرخصی ساعتی، تعداد ساعت الزامی است'})

        leave_category = data.get('leave_category', getattr(self.instance, 'leave_category', 'entitled'))
        reason = data.get('reason', getattr(self.instance, 'reason', ''))
        if leave_category == 'other' and not (reason or '').strip():
            raise serializers.ValidationError({'reason': 'برای دسته‌ی «سایر»، توضیحات الزامی است'})
        return data
