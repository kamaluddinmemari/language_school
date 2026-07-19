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
    user_full_name = serializers.SerializerMethodField()

    class Meta:
        model = SalaryProfile
        fields = ['id', 'user', 'user_full_name', 'work_year', 'base_salary', 'food_allowance',
                   'marriage_allowance', 'child_allowance', 'seniority_allowance', 'gross_base_monthly', 'updated_at']
        read_only_fields = ['id', 'updated_at']

    def get_user_full_name(self, obj):
        return obj.user.get_full_name()


class MonthlyPayrollSerializer(serializers.ModelSerializer):
    hourly_wage = serializers.ReadOnlyField()
    daily_wage = serializers.ReadOnlyField()
    gross_pay = serializers.ReadOnlyField()
    net_pay = serializers.ReadOnlyField()
    jalali_label = serializers.ReadOnlyField()
    user_full_name = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyPayroll
        fields = ['id', 'user', 'user_full_name', 'jalali_year', 'jalali_month', 'jalali_label',
                   'worked_hours', 'insurance_days', 'insurance_amount', 'notes',
                   'hourly_wage', 'daily_wage', 'gross_pay', 'net_pay', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_user_full_name(self, obj):
        return obj.user.get_full_name()

    def validate_jalali_month(self, value):
        if value < 1 or value > 12:
            raise serializers.ValidationError('ماه باید بین ۱ تا ۱۲ باشد')
        return value


class LeaveBalanceSerializer(serializers.ModelSerializer):
    used_days = serializers.ReadOnlyField()
    used_hours = serializers.ReadOnlyField()
    remaining_days = serializers.ReadOnlyField()
    remaining_hours = serializers.ReadOnlyField()
    user_full_name = serializers.SerializerMethodField()

    class Meta:
        model = LeaveBalance
        fields = ['id', 'user', 'user_full_name', 'jalali_year', 'annual_days', 'hourly_allowance',
                   'used_days', 'used_hours', 'remaining_days', 'remaining_hours']
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
        fields = ['id', 'user', 'user_full_name', 'leave_type', 'start_date', 'start_date_jalali',
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
        return data
