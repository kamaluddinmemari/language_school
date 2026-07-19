from django.urls import path
from .views import (
    ClassSlotListView, ClassSlotDetailView, AllocateClassesView,
    ConfirmOverflowView, TransferSurplusView, SpinOffSurplusView, ClassStatsView,
)

urlpatterns = [
    path('class-management/slots/', ClassSlotListView.as_view(), name='class_slot_list'),
    path('class-management/slots/<int:pk>/', ClassSlotDetailView.as_view(), name='class_slot_detail'),
    path('class-management/slots/<int:pk>/transfer-surplus/', TransferSurplusView.as_view(), name='class_transfer_surplus'),
    path('class-management/slots/<int:pk>/spin-off-surplus/', SpinOffSurplusView.as_view(), name='class_spin_off_surplus'),
    path('class-management/allocate/', AllocateClassesView.as_view(), name='class_allocate'),
    path('class-management/allocate/confirm-overflow/', ConfirmOverflowView.as_view(), name='class_confirm_overflow'),
    path('class-management/stats/', ClassStatsView.as_view(), name='class_stats'),
]
