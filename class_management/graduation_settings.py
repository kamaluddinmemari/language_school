import base64
import binascii
from pathlib import Path

from django.http import HttpResponse
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.menu_permissions import can_edit_menu
from .models import AccessFormConfig, GraduationLevelSetting

AGE_GROUPS = ('kids', 'teen', 'adult')
DEFAULT_CURRENT = {'kids': ['i5'], 'teen': ['teen15'], 'adult': ['606', '406']}
FALLBACK_SEQUENCES = {
    'kids': [f'{p}{n}' for p in ('i', 'u') for n in range(1, 6)],
    'teen': ['teenstarter'] + [f'teen{n}' for n in range(1, 16)],
    'adult': [str(n) for n in range(101, 607)],
}
MAX_TEMPLATE_BYTES = 5 * 1024 * 1024
DEFAULT_ACCESS_TEMPLATES = {'teacher': 'teacher.xlsx', 'employee': 'employee.xlsx'}
def _default_template(kind):
    name = DEFAULT_ACCESS_TEMPLATES.get(kind)
    path = Path(__file__).resolve().parent / 'access_form_templates' / name if name else None
    return (path.read_bytes(), name) if path and path.is_file() else (b'', '')


def level_sequences():
    """ترتیب استاندارد سطوح هر ردهٔ سنی از StandardLevel (با fallback وقتی خالی است)."""
    result = {}
    try:
        from level_tests.models import StandardLevel
        rows = list(StandardLevel.objects.all().order_by('age_group', 'order', 'code'))
    except Exception:
        rows = []
    for group in AGE_GROUPS:
        codes = [r.code for r in rows if r.age_group == group]
        result[group] = codes or FALLBACK_SEQUENCES[group]
    return result


def previous_level(sequence, code):
    for index, item in enumerate(sequence):
        if item.casefold() == str(code).casefold():
            return sequence[index - 1] if index > 0 else ''
    return ''


def saved_current_levels():
    saved = GraduationLevelSetting.get_current().levels or {}
    result = {}
    for group in AGE_GROUPS:
        value = saved.get(group)
        # اگر کاربر ذخیره کرده باشد (حتی خالی) همان معتبر است؛ فقط وقتی هیچ‌چیز ذخیره نشده پیش‌فرض می‌آید.
        result[group] = [str(x).strip() for x in value if str(x).strip()] if isinstance(value, list) else list(DEFAULT_CURRENT[group])
    return result


def get_level_groups():
    """{'kids': {'current': (...), 'next': (...)}, ...} — next = سطح قبلیِ هر سطح مدرک (افراد ترم بعد)."""
    sequences = level_sequences()
    current = saved_current_levels()
    groups = {}
    for group in AGE_GROUPS:
        nxt = []
        for code in current[group]:
            prev = previous_level(sequences[group], code)
            if prev and prev.casefold() not in [x.casefold() for x in nxt + current[group]]:
                nxt.append(prev)
        groups[group] = {'current': tuple(current[group]), 'next': tuple(nxt)}
    return groups


def _deny(request):
    return None if can_edit_menu(request.user, 'class-management') else Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)


class GraduationLevelSettingView(APIView):
    permission_classes = [IsAuthenticated]

    def _payload(self):
        sequences = level_sequences()
        current = saved_current_levels()
        groups = get_level_groups()
        return {
            'levels': current,
            'available': sequences,
            'previous': {g: {c: previous_level(sequences[g], c) for c in current[g]} for g in AGE_GROUPS},
            'next': {g: list(groups[g]['next']) for g in AGE_GROUPS},
            'defaults': DEFAULT_CURRENT,
        }

    def get(self, request):
        denied = _deny(request)
        return denied or Response(self._payload())

    def put(self, request):
        denied = _deny(request)
        if denied:
            return denied
        data = request.data.get('levels') if hasattr(request.data, 'get') else None
        if not isinstance(data, dict):
            return Response({'error': 'ساختار سطوح معتبر نیست.'}, status=status.HTTP_400_BAD_REQUEST)
        sequences = level_sequences()
        clean = {}
        for group in AGE_GROUPS:
            items = data.get(group) or []
            if not isinstance(items, list):
                return Response({'error': 'ساختار سطوح معتبر نیست.'}, status=status.HTTP_400_BAD_REQUEST)
            allowed = {c.casefold(): c for c in sequences[group]}
            picked = []
            for item in items:
                code = allowed.get(str(item).strip().casefold())
                if code and code not in picked:
                    picked.append(code)
            clean[group] = picked
        if not any(clean.values()):
            return Response({'error': 'حداقل یک سطح فارغ‌التحصیلی (در یکی از ردیف‌های سنی) انتخاب کنید.'}, status=status.HTTP_400_BAD_REQUEST)
        obj = GraduationLevelSetting.get_current()
        obj.levels = clean
        obj.save()
        return Response(self._payload())


def _config(kind):
    obj, _ = AccessFormConfig.objects.get_or_create(kind=kind)
    # The teacher template has its column headers on row 2; data starts on row 3.
    if kind == 'teacher' and obj.start_row < 3:
        obj.start_row = 3
        obj.save(update_fields=['start_row', 'updated_at'])
    return obj


def _config_payload(obj):
    return {
        'kind': obj.kind, 'has_template': bool(obj.template_b64) or bool(_default_template(obj.kind)[0]), 'template_name': obj.template_name or _default_template(obj.kind)[1],
        'start_row': obj.start_row, 'fields': obj.fields or [], 'fixed_cells': obj.fixed_cells or [],
        'letter_template': obj.letter_template or '',
    }


class AccessFormConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, kind):
        denied = _deny(request)
        if denied:
            return denied
        if kind not in ('teacher', 'employee'):
            return Response({'error': 'نوع فرم معتبر نیست.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(_config_payload(_config(kind)))

    def put(self, request, kind):
        denied = _deny(request)
        if denied:
            return denied
        if kind not in ('teacher', 'employee'):
            return Response({'error': 'نوع فرم معتبر نیست.'}, status=status.HTTP_404_NOT_FOUND)
        obj = _config(kind)
        d = request.data
        try:
            start_row = max(3 if kind == 'teacher' else 2, min(1000, int(d.get('start_row', obj.start_row))))
        except (TypeError, ValueError):
            return Response({'error': 'ردیف شروع معتبر نیست.'}, status=status.HTTP_400_BAD_REQUEST)
        fields, fixed = [], []
        for f in d.get('fields') or []:
            label = str(f.get('label', '')).strip()[:100]
            col = str(f.get('column', '')).strip().upper()[:3]
            if label and col.isalpha():
                fields.append({'key': str(f.get('key') or label)[:60], 'label': label, 'column': col})
        for c in d.get('fixed_cells') or []:
            label = str(c.get('label', '')).strip()[:100]
            cell = str(c.get('cell', '')).strip().upper()[:10]
            if cell:
                fixed.append({'label': label, 'cell': cell, 'value': str(c.get('value', ''))[:500]})
        obj.start_row, obj.fields, obj.fixed_cells = start_row, fields, fixed
        obj.letter_template = str(d.get('letter_template', obj.letter_template or ''))[:5000]
        obj.save()
        return Response(_config_payload(obj))


class AccessFormTemplateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, kind):
        denied = _deny(request)
        if denied:
            return denied
        obj = AccessFormConfig.objects.filter(kind=kind).first()
        if obj and obj.template_b64:
            try:
                raw = base64.b64decode(obj.template_b64)
            except (binascii.Error, ValueError):
                return Response({'error': 'قالب ذخیره‌شده خراب است.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            raw, _name = _default_template(kind)
            if not raw:
                return Response({'error': 'قالب استاندارد موجود نیست.'}, status=status.HTTP_404_NOT_FOUND)
        resp = HttpResponse(raw, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Cache-Control'] = 'no-store'
        return resp

    def post(self, request, kind):
        denied = _deny(request)
        if denied:
            return denied
        if kind not in ('teacher', 'employee'):
            return Response({'error': 'نوع فرم معتبر نیست.'}, status=status.HTTP_404_NOT_FOUND)
        f = request.FILES.get('file')
        if not f:
            return Response({'error': 'فایل ارسال نشده است.'}, status=status.HTTP_400_BAD_REQUEST)
        if not f.name.lower().endswith('.xlsx'):
            return Response({'error': 'فقط فایل اکسل با پسوند xlsx پذیرفته می‌شود.'}, status=status.HTTP_400_BAD_REQUEST)
        if f.size > MAX_TEMPLATE_BYTES:
            return Response({'error': 'حجم فایل بیشتر از ۵ مگابایت است.'}, status=status.HTTP_400_BAD_REQUEST)
        raw = f.read()
        if not raw.startswith(b'PK'):
            return Response({'error': 'فایل اکسل معتبر نیست.'}, status=status.HTTP_400_BAD_REQUEST)
        obj = _config(kind)
        obj.template_name = f.name[:255]
        obj.template_b64 = base64.b64encode(raw).decode('ascii')
        obj.save()
        return Response(_config_payload(obj))

    def delete(self, request, kind):
        denied = _deny(request)
        if denied:
            return denied
        obj = AccessFormConfig.objects.filter(kind=kind).first()
        if obj:
            obj.template_b64, obj.template_name = '', ''
            obj.save()
        return Response({'ok': True})
