from django.urls import path
from .views import (
    EmployeeProfileListCreateView, EmployeeProfileDetailView,
    SalaryProfileListCreateView, SalaryProfileDetailView,
    MonthlyPayrollListCreateView, MonthlyPayrollDetailView,
    LeaveBalanceListCreateView, LeaveBalanceDetailView,
    LeaveRequestListCreateView, LeaveRequestDetailView, LeaveRequestDecideView,
)

urlpatterns = [
    path('employee-profiles/', EmployeeProfileListCreateView.as_view(), name='employee_profile_list'),
    path('employee-profiles/<int:pk>/', EmployeeProfileDetailView.as_view(), name='employee_profile_detail'),

    path('salary-profiles/', SalaryProfileListCreateView.as_view(), name='salary_profile_list'),
    path('salary-profiles/<int:pk>/', SalaryProfileDetailView.as_view(), name='salary_profile_detail'),

    path('monthly-payroll/', MonthlyPayrollListCreateView.as_view(), name='monthly_payroll_list'),
    path('monthly-payroll/<int:pk>/', MonthlyPayrollDetailView.as_view(), name='monthly_payroll_detail'),

    path('leave-balances/', LeaveBalanceListCreateView.as_view(), name='leave_balance_list'),
    path('leave-balances/<int:pk>/', LeaveBalanceDetailView.as_view(), name='leave_balance_detail'),

    path('leave-requests/', LeaveRequestListCreateView.as_view(), name='leave_request_list'),
    path('leave-requests/<int:pk>/', LeaveRequestDetailView.as_view(), name='leave_request_detail'),
    path('leave-requests/<int:pk>/decide/', LeaveRequestDecideView.as_view(), name='leave_request_decide'),
]
