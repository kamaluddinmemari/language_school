from django.urls import path
from .views import (
    ClassSlotListView, ClassSlotDetailView, AllocateClassesView,
    ConfirmOverflowView, TransferSurplusView, SpinOffSurplusView, ClassStatsView,
    BulkCreatePhysicalClassesView, ClassSlotEnrollView, ClassSlotUnenrollView, ClassSlotRosterView,
)

urlpatterns = [
    path('class-management/slots/', ClassSlotListView.as_view(), name='class_slot_list'),
    path('class-management/slots/<int:pk>/', ClassSlotDetailView.as_view(), name='class_slot_detail'),
    path('class-management/slots/<int:pk>/transfer-surplus/', TransferSurplusView.as_view(), name='class_transfer_surplus'),
    path('class-management/slots/<int:pk>/spin-off-surplus/', SpinOffSurplusView.as_view(), name='class_spin_off_surplus'),
    path('class-management/slots/<int:pk>/enroll/', ClassSlotEnrollView.as_view(), name='class_slot_enroll'),
    path('class-management/slots/<int:pk>/enroll/<int:student_id>/', ClassSlotUnenrollView.as_view(), name='class_slot_unenroll'),
    path('class-management/slots/<int:pk>/roster/', ClassSlotRosterView.as_view(), name='class_slot_roster'),
    path('class-management/bulk-create/', BulkCreatePhysicalClassesView.as_view(), name='class_bulk_create'),
    path('class-management/allocate/', AllocateClassesView.as_view(), name='class_allocate'),
    path('class-management/allocate/confirm-overflow/', ConfirmOverflowView.as_view(), name='class_confirm_overflow'),
    path('class-management/stats/', ClassStatsView.as_view(), name='class_stats'),
]
