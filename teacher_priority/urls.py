from django.urls import path
from .views import TeacherPriorityRankingView, TeacherPriorityQueueView, TeacherPriorityConfigView

urlpatterns = [
    path('teacher-priority/ranking/', TeacherPriorityRankingView.as_view(), name='teacher_priority_ranking'),
    path('teacher-priority/queue/', TeacherPriorityQueueView.as_view(), name='teacher_priority_queue'),
    path('teacher-priority/config/', TeacherPriorityConfigView.as_view(), name='teacher_priority_config'),
]
