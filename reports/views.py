from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework import viewsets, status

from .registry import REGISTRY, list_registry
from .registry_custom import SOURCES, list_sources
from .query_engine import run_query, ReportQueryError
from .models import ReportDefinition
from .serializers import ReportDefinitionSerializer
from .utils import get_date_range
from . import exporters


class IsAdminOrOffice(IsAuthenticated):
    """فقط مدیر/اداری اجازه‌ی دیدن گزارش‌های کل‌سیستمی را دارند"""
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return getattr(request.user, 'role', None) in ('admin', 'office')


def _get_spec_or_404(key):
    spec = REGISTRY.get(key)
    if not spec:
        raise NotFound('گزارش مورد نظر پیدا نشد')
    return spec


def _fetch_rows(request, spec):
    start, end = get_date_range(request)
    term_id = request.query_params.get('term_id') if spec.supports_term else None
    rows, totals = spec.fetch(start, end, term_id=term_id)
    return rows, totals


class ReportListView(APIView):
    """GET /api/reports/  -> فهرست همه‌ی گزارش‌های سیستمی موجود، به‌همراه ستون‌ها و متادیتا"""
    permission_classes = [IsAdminOrOffice]

    def get(self, request):
        return Response(list_registry())


class ReportDataView(APIView):
    """GET /api/reports/<key>/data/?start=&end=&term_id=  -> ردیف‌ها به‌صورت JSON (پیش‌نمایش)"""
    permission_classes = [IsAdminOrOffice]

    def get(self, request, key):
        spec = _get_spec_or_404(key)
        rows, totals = _fetch_rows(request, spec)
        return Response({
            'key': spec.key, 'name': spec.name,
            'columns': [{'key': c.key, 'header': c.header} for c in spec.columns],
            'rows': rows, 'totals': totals,
        })


class ReportExportView(APIView):
    """GET /api/reports/<key>/export/?format=xlsx|docx&start=&end=&term_id=  -> دانلود فایل"""
    permission_classes = [IsAdminOrOffice]

    def get(self, request, key):
        spec = _get_spec_or_404(key)
        rows, totals = _fetch_rows(request, spec)
        fmt = request.query_params.get('format', 'xlsx')

        if fmt == 'xlsx':
            buf = exporters.build_excel(spec, rows, totals)
            response = HttpResponse(
                buf.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="{spec.key}.xlsx"'
            return response

        if fmt == 'docx':
            buf = exporters.build_docx(spec, rows, totals)
            response = HttpResponse(
                buf.read(),
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
            response['Content-Disposition'] = f'attachment; filename="{spec.key}.docx"'
            return response

        raise NotFound('فرمت خروجی نامعتبر است')


class ReportPrintView(APIView):
    """GET /api/reports/<key>/print/?start=&end=&term_id=  -> HTML آماده‌ی چاپ (JSON: {html})"""
    permission_classes = [IsAdminOrOffice]

    def get(self, request, key):
        spec = _get_spec_or_404(key)
        rows, totals = _fetch_rows(request, spec)
        html = exporters.build_print_html(spec, rows, totals)
        return Response({'html': html})


# ===========================================================================
# فاز ۳: گزارش‌ساز دلخواه
# ===========================================================================
class CustomSourceListView(APIView):
    """GET /api/reports/custom/sources/  -> فهرست منابع داده‌ی قابل‌استفاده در گزارش‌ساز، با فیلدهای هرکدام"""
    permission_classes = [IsAdminOrOffice]

    def get(self, request):
        return Response(list_sources())


class CustomPreviewView(APIView):
    """
    POST /api/reports/custom/preview/
    body: {source, fields, filters, group_by, aggregations, start, end}
    -> پیش‌نمایش نتیجه بدون ذخیره‌شدن گزارش
    """
    permission_classes = [IsAdminOrOffice]

    def post(self, request):
        body = request.data
        start, end = get_date_range_from_body(body)
        try:
            rows, columns = run_query(
                source_key=body.get('source'),
                fields=body.get('fields', []),
                filters=body.get('filters', []),
                group_by=body.get('group_by', []),
                aggregations=body.get('aggregations', []),
                start=start, end=end,
            )
        except ReportQueryError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'columns': columns, 'rows': rows})


def get_date_range_from_body(body):
    from .utils import parse_jalali_date
    return parse_jalali_date(body.get('start')), parse_jalali_date(body.get('end'))


class ReportDefinitionViewSet(viewsets.ModelViewSet):
    """CRUD گزارش‌های دلخواهِ ذخیره‌شده"""
    queryset = ReportDefinition.objects.all()
    serializer_class = ReportDefinitionSerializer
    permission_classes = [IsAdminOrOffice]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def get_queryset(self):
        return ReportDefinition.objects.all().select_related('created_by')


class ReportDefinitionDataView(APIView):
    """GET /api/reports/custom/definitions/<id>/data/?start=&end=  -> اجرای گزارش دلخواهِ ذخیره‌شده"""
    permission_classes = [IsAdminOrOffice]

    def get(self, request, pk):
        try:
            definition = ReportDefinition.objects.get(pk=pk)
        except ReportDefinition.DoesNotExist:
            raise NotFound('گزارش دلخواه پیدا نشد')

        start, end = (None, None) if definition.date_override else get_date_range(request)
        try:
            rows, columns = run_query(
                source_key=definition.source_key,
                fields=definition.fields,
                filters=definition.filters,
                group_by=definition.group_by,
                aggregations=definition.aggregations,
                start=start, end=end,
            )
        except ReportQueryError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'key': f'custom-{definition.id}', 'name': definition.name, 'columns': columns, 'rows': rows, 'totals': None})
