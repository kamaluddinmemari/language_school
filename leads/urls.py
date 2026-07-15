from django.urls import path
from .views import (
    NewLeadListView, NewLeadDetailView, NewLeadActionView,
    UnregisteredStudentListView, UnregisteredStudentDetailView,
    UnregisteredStudentFollowupView, UnregisteredStudentRegisterView, UnregisteredStudentStatsView,
    DebtorListView, DebtorDetailView, DebtorFollowupView, DebtorSettleView, DebtorStatsView,
    DiscountedPersonListView, DiscountedPersonDetailView,
)

urlpatterns = [
    path('leads/new-leads/', NewLeadListView.as_view(), name='new_lead_list'),
    path('leads/new-leads/<int:pk>/', NewLeadDetailView.as_view(), name='new_lead_detail'),
    path('leads/new-leads/<int:pk>/<str:action>/', NewLeadActionView.as_view(), name='new_lead_action'),

    path('leads/unregistered-students/', UnregisteredStudentListView.as_view(), name='unregistered_student_list'),
    path('leads/unregistered-students/<int:pk>/', UnregisteredStudentDetailView.as_view(), name='unregistered_student_detail'),
    path('leads/unregistered-students/<int:pk>/followup/', UnregisteredStudentFollowupView.as_view(), name='unregistered_student_followup'),
    path('leads/unregistered-students/<int:pk>/register/', UnregisteredStudentRegisterView.as_view(), name='unregistered_student_register'),
    path('leads/unregistered-students/stats/', UnregisteredStudentStatsView.as_view(), name='unregistered_student_stats'),

    path('leads/debtors/', DebtorListView.as_view(), name='debtor_list'),
    path('leads/debtors/<int:pk>/', DebtorDetailView.as_view(), name='debtor_detail'),
    path('leads/debtors/<int:pk>/followup/', DebtorFollowupView.as_view(), name='debtor_followup'),
    path('leads/debtors/<int:pk>/settle/', DebtorSettleView.as_view(), name='debtor_settle'),
    path('leads/debtors/stats/', DebtorStatsView.as_view(), name='debtor_stats'),

    path('leads/discounts/', DiscountedPersonListView.as_view(), name='discounted_person_list'),
    path('leads/discounts/<int:pk>/', DiscountedPersonDetailView.as_view(), name='discounted_person_detail'),
]
