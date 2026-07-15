from django.urls import path
from .views import ClassSlotListView, ClassSlotDetailView, AllocateClassesView, AutoScheduleTimesView

urlpatterns = [
    path('class-management/slots/', ClassSlotListView.as_view(), name='class_slot_list'),
    path('class-management/slots/<int:pk>/', ClassSlotDetailView.as_view(), name='class_slot_detail'),
    path('class-management/auto-schedule/', AutoScheduleTimesView.as_view(), name='class_auto_schedule'),
    path('class-management/allocate/', AllocateClassesView.as_view(), name='class_allocate'),
]
