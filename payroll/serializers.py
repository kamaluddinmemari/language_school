from rest_framework import serializers
from .models import EmployeeProfile, SalaryProfile, MonthlyPayroll, LeaveBalance, LeaveRequest, AttendanceLog, OfficialHoliday, HolidayWorkAssignment


class EmployeeProfileSerializer(serializers.ModelSerializer):
    hire_date_jalali = serializers.ReadOnlyField()

    class Meta:
        model = EmployeeProfile
        fields = ['id', 'user', 'education_degree', 'education_field', 'hire_date', 'hire_date_jalali', 'minimum_monthly_hours',
                   'address', 'marital_status', 'children_count', 'sheba_number', 'bank_account_number',
                   'card_number', 'updated_at']
        read_only_fields = ['id', 'updated_at']


class SalaryProfileSerializer(serializers.ModelSerializer):
    gross_base_monthly_shared = serializers.ReadOnlyField()
    housing_allowance_monthly = serializers.ReadOnlyField()
    components_breakdown = serializers.ReadOnlyField()

    class Meta:
        model = SalaryProfile
        fields = ['id', 'work_year', 'base_salary', 'food_allowance',
                   'marriage_allowance', 'child_allowance',
                   'housing_allowance', 'housing_allowance_monthly',
                   'insurance_base_single', 'insurance_base_married',
                   'morning_leave_hours', 'evening_leave_hours', 'shortfall_hourly_threshold', 'shortfall_leave_day_threshold',
                   'gross_base_monthly_shared', 'components_breakdown', 'updated_at']
        read_only_fields = ['id', 'updated_at']


class MonthlyPayrollSerializer(serializers.ModelSerializer):
    hourly_wage = serializers.ReadOnlyField()
    daily_wage = serializers.ReadOnlyField()
    days_in_month = serializers.ReadOnlyField()
    standard_monthly_hours_this_month = serializers.ReadOnlyField()
    insurance_base_30days = serializers.ReadOnlyField()
    insurance_amount = serializers.ReadOnlyField()
    overtime_pay = serializers.ReadOnlyField()
    absence_deduction = serializers.ReadOnlyField()
    undertime_deduction = serializers.ReadOnlyField()
    total_deductions = serializers.ReadOnlyField()
    gross_pay = serializers.ReadOnlyField()
    net_pay = serializers.ReadOnlyField()
    net_pay_words = serializers.ReadOnlyField()
    approved_leave_days_this_month = serializers.ReadOnlyField()
    approved_leave_hours_this_month = serializers.ReadOnlyField()
    leave_credit_explanation = serializers.ReadOnlyField()
    jalali_label = serializers.ReadOnlyField()
    acknowledged_at_jalali = serializers.ReadOnlyField()
    auto_worked_hours = serializers.ReadOnlyField()
    minimum_monthly_hours = serializers.ReadOnlyField()
    automatic_shortfall_hours = serializers.ReadOnlyField()
    automatic_overtime_hours = serializers.ReadOnlyField()
    effective_undertime_hours = serializers.ReadOnlyField()
    effective_overtime_hours = serializers.ReadOnlyField()
    automatic_absence_days = serializers.ReadOnlyField()
    work_adjustment_explanation = serializers.ReadOnlyField()
    marital_status_display = serializers.ReadOnlyField()
    children_count = serializers.ReadOnlyField()
    seniority_base_monthly = serializers.ReadOnlyField()
    seniority_base_daily = serializers.ReadOnlyField()
    seniority_base_hourly = serializers.ReadOnlyField()
    is_seniority_eligible = serializers.ReadOnlyField()
    component_amounts_this_month = serializers.ReadOnlyField()
    holiday_work_hours = serializers.ReadOnlyField()
    holiday_work_explanation = serializers.ReadOnlyField()
    holiday_work_pay = serializers.ReadOnlyField()
    user_full_name = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyPayroll
        fields = [
            'id', 'user', 'user_full_name', 'jalali_year', 'jalali_month', 'jalali_label',
            'marital_status_display', 'children_count',
            'worked_hours', 'auto_worked_hours', 'minimum_monthly_hours', 'automatic_shortfall_hours', 'automatic_overtime_hours',
            'effective_undertime_hours', 'effective_overtime_hours', 'automatic_absence_days', 'work_adjustment_explanation',
            'insurance_days', 'absence_days', 'absence_hours', 'undertime_hours',
            'overtime_hours', 'bonus_amount', 'extra_payment', 'notes',
            'days_in_month', 'standard_monthly_hours_this_month',
            'hourly_wage', 'daily_wage', 'insurance_base_30days', 'insurance_amount', 'overtime_pay',
            'absence_deduction', 'undertime_deduction', 'total_deductions', 'gross_pay', 'net_pay',
            'net_pay_words', 'approved_leave_days_this_month', 'approved_leave_hours_this_month', 'leave_credit_explanation',
            'is_seniority_eligible', 'seniority_base_monthly', 'seniority_base_daily', 'seniority_base_hourly',
            'component_amounts_this_month', 'holiday_work_hours', 'holiday_work_explanation', 'holiday_work_pay',
            'acknowledged_at', 'acknowledged_at_jalali', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'acknowledged_at', 'created_at', 'updated_at']

    def get_user_full_name(self, obj):
        return obj.user.get_full_name()

    def validate_jalali_month(self, value):
        if value < 1 or value > 12:
            raise serializers.ValidationError('ماه باید بین ۱ تا ۱۲ باشد')
        return value


class AttendanceLogSerializer(serializers.ModelSerializer):
    date_jalali = serializers.ReadOnlyField()
    check_in_time_jalali = serializers.ReadOnlyField()
    check_out_time_jalali = serializers.ReadOnlyField()
    worked_hours = serializers.ReadOnlyField()
    user_full_name = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceLog
        fields = [
            'id', 'user', 'user_full_name', 'date', 'date_jalali', 'check_in', 'check_out',
            'check_in_time_jalali', 'check_out_time_jalali', 'worked_hours', 'edited_by_admin',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_user_full_name(self, obj):
        return obj.user.get_full_name()


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
    credited_hours = serializers.ReadOnlyField()
    credited_hours_label = serializers.ReadOnlyField()

    class Meta:
        model = LeaveRequest
        fields = ['id', 'user', 'user_full_name', 'leave_type', 'leave_category', 'leave_shift', 'start_date', 'start_date_jalali',
                   'end_date', 'end_date_jalali', 'hours', 'morning_days', 'evening_days', 'credited_hours', 'credited_hours_label', 'days_count', 'reason', 'status',
                   'requested_at', 'requested_at_jalali', 'decided_at', 'decided_at_jalali', 'decided_by_name']
        read_only_fields = ['id', 'status', 'requested_at', 'decided_at', 'decided_by_name']

    def get_user_full_name(self, obj):
        return obj.user.get_full_name()

    def get_decided_by_name(self, obj):
        return obj.decided_by.get_full_name() if obj.decided_by else None

    def validate(self, data):
        leave_type = data.get('leave_type', getattr(self.instance, 'leave_type', 'daily'))
        if leave_type == 'daily' and not data.get('leave_shift', getattr(self.instance, 'leave_shift', '')):
            raise serializers.ValidationError({'leave_shift': 'برای مرخصی روزانه، صبح، عصر یا ترکیبی را انتخاب کنید'})
        shift = data.get('leave_shift', getattr(self.instance, 'leave_shift', 'morning'))
        if leave_type == 'daily' and shift == 'mixed':
            start = data.get('start_date', getattr(self.instance, 'start_date', None))
            end = data.get('end_date', getattr(self.instance, 'end_date', None)) or start
            total_days = (end - start).days + 1 if start and end else 0
            morning_days = int(data.get('morning_days', getattr(self.instance, 'morning_days', 0)) or 0)
            evening_days = int(data.get('evening_days', getattr(self.instance, 'evening_days', 0)) or 0)
            if morning_days < 0 or evening_days < 0 or morning_days + evening_days != total_days:
                raise serializers.ValidationError({'morning_days': 'مجموع روزهای صبح و عصر باید برابر تعداد روزهای مرخصی باشد'})
        if leave_type == 'hourly' and not data.get('hours') and not getattr(self.instance, 'hours', None):
            raise serializers.ValidationError({'hours': 'برای مرخصی ساعتی، تعداد ساعت الزامی است'})

        leave_category = data.get('leave_category', getattr(self.instance, 'leave_category', 'entitled'))
        reason = data.get('reason', getattr(self.instance, 'reason', ''))
        if leave_category == 'other' and not (reason or '').strip():
            raise serializers.ValidationError({'reason': 'برای دسته‌ی «سایر»، توضیحات الزامی است'})
        return data


class OfficialHolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = OfficialHoliday
        fields = ['id', 'date', 'title', 'is_active', 'work_multiplier', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class HolidayWorkAssignmentSerializer(serializers.ModelSerializer):
    user_full_name = serializers.SerializerMethodField()
    configured_hours = serializers.ReadOnlyField()
    effective_multiplier = serializers.ReadOnlyField()

    class Meta:
        model = HolidayWorkAssignment
        fields = ['id', 'holiday', 'user', 'user_full_name', 'include_in_worked_hours', 'shift', 'morning_days', 'evening_days', 'multiplier', 'configured_hours', 'effective_multiplier', 'notes']
        read_only_fields = ['id']

    def get_user_full_name(self, obj):
        return obj.user.get_full_name()
