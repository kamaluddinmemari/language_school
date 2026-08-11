from django.urls import path
from .views import (
    EmployeeProfileListCreateView, EmployeeProfileDetailView,
    SalaryProfileListCreateView, SalaryProfileDetailView,
    MonthlyPayrollListCreateView, MonthlyPayrollDetailView, MonthlyPayrollAcknowledgeView,
    LeaveBalanceListCreateView, LeaveBalanceDetailView,
    LeaveRequestListCreateView, LeaveRequestDetailView, LeaveRequestDecideView,
    MyAttendanceTodayView, CheckInView, CheckOutView,
    AttendanceLogListCreateView, AttendanceLogDetailView, AttendanceSummaryView,
)

urlpatterns = [
    path('employee-profiles/', EmployeeProfileListCreateView.as_view(), name='employee_profile_list'),
    path('employee-profiles/<int:pk>/', EmployeeProfileDetailView.as_view(), name='employee_profile_detail'),

    path('salary-profiles/', SalaryProfileListCreateView.as_view(), name='salary_profile_list'),
    path('salary-profiles/<int:pk>/', SalaryProfileDetailView.as_view(), name='salary_profile_detail'),

    path('monthly-payroll/', MonthlyPayrollListCreateView.as_view(), name='monthly_payroll_list'),
    path('monthly-payroll/<int:pk>/', MonthlyPayrollDetailView.as_view(), name='monthly_payroll_detail'),
    path('monthly-payroll/<int:pk>/acknowledge/', MonthlyPayrollAcknowledgeView.as_view(), name='monthly_payroll_acknowledge'),

    path('leave-balances/', LeaveBalanceListCreateView.as_view(), name='leave_balance_list'),
    path('leave-balances/<int:pk>/', LeaveBalanceDetailView.as_view(), name='leave_balance_detail'),

    path('leave-requests/', LeaveRequestListCreateView.as_view(), name='leave_request_list'),
    path('leave-requests/<int:pk>/', LeaveRequestDetailView.as_view(), name='leave_request_detail'),
    path('leave-requests/<int:pk>/decide/', LeaveRequestDecideView.as_view(), name='leave_request_decide'),

    # --- ثبت ساعت ورود و خروج ---
    path('attendance/my-today/', MyAttendanceTodayView.as_view(), name='attendance_my_today'),
    path('attendance/check-in/', CheckInView.as_view(), name='attendance_check_in'),
    path('attendance/check-out/', CheckOutView.as_view(), name='attendance_check_out'),
    path('attendance/', AttendanceLogListCreateView.as_view(), name='attendance_list'),
    path('attendance/<int:pk>/', AttendanceLogDetailView.as_view(), name='attendance_detail'),
    path('attendance/summary/', AttendanceSummaryView.as_view(), name='attendance_summary'),
]
