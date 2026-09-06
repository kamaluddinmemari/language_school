from django.urls import path
from .views import (
    GradeFieldSettingListView, GradePassingSettingListView, GradingTermListView,
    GradingClassListView, GradingClassRosterView, GradingClassSaveView, GradingClassFinalizeView,
    TeacherMyGradingClassesView, StudentMyGradesView, StudentAcademicHistoryView,
)

urlpatterns = [
    path('grading/field-settings/', GradeFieldSettingListView.as_view(), name='grading_field_settings'),
    path('grading/passing-settings/', GradePassingSettingListView.as_view(), name='grading_passing_settings'),
    path('grading/terms/', GradingTermListView.as_view(), name='grading_terms'),
    path('grading/classes/', GradingClassListView.as_view(), name='grading_class_list'),
    path('grading/classes/<int:pk>/roster/', GradingClassRosterView.as_view(), name='grading_class_roster'),
    path('grading/classes/<int:pk>/save/', GradingClassSaveView.as_view(), name='grading_class_save'),
    path('grading/classes/<int:pk>/finalize/', GradingClassFinalizeView.as_view(), name='grading_class_finalize'),
    path('grading/my-classes/', TeacherMyGradingClassesView.as_view(), name='grading_my_classes'),
    path('grading/my-grades/', StudentMyGradesView.as_view(), name='grading_my_grades'),
    path('grading/students/<int:student_id>/history/', StudentAcademicHistoryView.as_view(), name='grading_student_history'),
]
