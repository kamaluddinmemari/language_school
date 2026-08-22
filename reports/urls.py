from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    ReportListView, ReportDataView, ReportExportView, ReportPrintView,
    CustomSourceListView, CustomPreviewView, ReportDefinitionViewSet, ReportDefinitionDataView,
)

router = DefaultRouter()
router.register('reports/custom/definitions', ReportDefinitionViewSet, basename='report-definition')

urlpatterns = [
    path('reports/', ReportListView.as_view(), name='report-list'),
    path('reports/<str:key>/data/', ReportDataView.as_view(), name='report-data'),
    path('reports/<str:key>/export/', ReportExportView.as_view(), name='report-export'),
    path('reports/<str:key>/print/', ReportPrintView.as_view(), name='report-print'),

    path('reports/custom/sources/', CustomSourceListView.as_view(), name='report-custom-sources'),
    path('reports/custom/preview/', CustomPreviewView.as_view(), name='report-custom-preview'),
    path('reports/custom/definitions/<int:pk>/data/', ReportDefinitionDataView.as_view(), name='report-definition-data'),
] + router.urls
