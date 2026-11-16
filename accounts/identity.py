"""
«شناسنامه» برنامه — مسیر واقعی کدها روی سرور و دانلود فایل فشرده‌ی کدهای منبع.

- SystemCodeLocationView: مسیر مطلقِ پوشه‌های کد (بک‌اند، پنل ادمین، دیتابیس، مدیا)، تعداد فایل و حجم هر کدام،
  نسخه‌ی پایتون/جنگو — فقط برای مدیر.
- SourceCodeDownloadView: همه‌ی کدهای منبع را در یک zip می‌دهد (بدون دیتابیس، مدیا، فایل‌های موقت و پوشه‌های ساخت).
  مقدار SECRET_KEY داخل فایل‌های settings با متن جایگزین می‌شود تا کلید سرور بیرون نرود.
  پوشه‌های اضافه (مثلاً سورس اپ موبایل) با متغیر محیطی SOURCE_EXTRA_DIRS (جداشده با «;» یا «,») اضافه می‌شوند.
"""
import io
import os
import platform
import re
import sys
import zipfile
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

EXCLUDE_DIRS = {
    '__pycache__', 'node_modules', '.git', '.idea', '.vscode', 'venv', 'env', '.venv', 'media', 'staticfiles',
    'build', 'dist', '.mypy_cache', '.pytest_cache', 'coverage',
}
EXCLUDE_SUFFIXES = {'.pyc', '.pyo', '.sqlite3', '.db', '.log', '.sqlite3-journal', '.pem', '.key'}
EXCLUDE_NAMES = {'.env', '.DS_Store', 'Thumbs.db'}
MAX_FILE_BYTES = 5 * 1024 * 1024


def _roots():
    """[(برچسب، مسیر)] پوشه‌های کدی که در شناسنامه/دانلود می‌آیند."""
    backend = Path(settings.BASE_DIR).resolve()
    project_root = backend.parent
    roots = [('بک‌اند (Django)', backend)]
    panel = project_root / 'admin-panel'
    if panel.is_dir():
        roots.append(('پنل ادمین (React)', panel))
    app = project_root / 'language_school_app'
    if app.is_dir():
        roots.append(('اپ موبایل (Expo/React Native)', app))
    for raw in re.split(r'[;,]', os.environ.get('SOURCE_EXTRA_DIRS', '')):
        raw = raw.strip()
        if raw and Path(raw).is_dir():
            roots.append((f'اضافه: {Path(raw).name}', Path(raw).resolve()))
    return roots


def _iter_files(root):
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        for name in sorted(files):
            path = Path(current) / name
            if name in EXCLUDE_NAMES or path.suffix.lower() in EXCLUDE_SUFFIXES:
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield path


def _is_admin(request):
    return getattr(request.user, 'role', None) == 'admin'


class SystemCodeLocationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_admin(request):
            return Response({'error': 'فقط مدیر به شناسنامه و مسیر کدها دسترسی دارد'}, status=status.HTTP_403_FORBIDDEN)
        try:
            import django
            django_version = django.get_version()
        except Exception:
            django_version = ''
        roots = []
        for label, root in _roots():
            files = size = 0
            top = {}
            for path in _iter_files(root):
                files += 1
                try:
                    sz = path.stat().st_size
                except OSError:
                    sz = 0
                size += sz
                rel = path.relative_to(root).parts
                key = rel[0] if len(rel) > 1 else '(فایل‌های ریشه)'
                entry = top.setdefault(key, {'name': key, 'files': 0, 'bytes': 0})
                entry['files'] += 1
                entry['bytes'] += sz
            roots.append({
                'label': label, 'path': str(root), 'files': files, 'bytes': size,
                'folders': sorted(top.values(), key=lambda x: x['name']),
            })
        db_path = ''
        db_bytes = 0
        try:
            name = settings.DATABASES['default'].get('NAME')
            if name:
                db_path = str(name)
                db_bytes = Path(name).stat().st_size if Path(name).exists() else 0
        except Exception:
            pass
        media_root = str(getattr(settings, 'MEDIA_ROOT', '') or '')
        return Response({
            'generated_at': timezone.now().isoformat(),
            'server_os': platform.platform(),
            'python': sys.version.split()[0],
            'django': django_version,
            'roots': roots,
            'database': {'engine': settings.DATABASES['default'].get('ENGINE', ''), 'path': db_path, 'bytes': db_bytes},
            'media_root': media_root,
            'download_url': '/api/system/source-download/',
            'excluded': sorted(EXCLUDE_DIRS | EXCLUDE_NAMES | EXCLUDE_SUFFIXES),
        })


class SourceCodeDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_admin(request):
            return Response({'error': 'فقط مدیر می‌تواند کدها را دانلود کند'}, status=status.HTTP_403_FORBIDDEN)
        buffer = io.BytesIO()
        secret_re = re.compile(r"^(\s*SECRET_KEY\s*=\s*).*$", re.M)
        manifest = [f'Source export — {timezone.localtime().strftime("%Y-%m-%d %H:%M")}', '']
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for label, root in _roots():
                base = root.name
                manifest.append(f'[{label}] {root}')
                count = 0
                for path in _iter_files(root):
                    arc = f'{base}/{path.relative_to(root).as_posix()}'
                    if path.name in ('settings.py', 'core-settings.py'):
                        try:
                            text = path.read_text(encoding='utf-8')
                            archive.writestr(arc, secret_re.sub(r"\1'<REDACTED — set your own secret key>'", text))
                            count += 1
                            continue
                        except (OSError, UnicodeDecodeError):
                            pass
                    archive.write(path, arc)
                    count += 1
                manifest.append(f'   files: {count}')
            archive.writestr('MANIFEST.txt', '\n'.join(manifest))
        response = HttpResponse(buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="language-school-source-{timezone.localtime().strftime("%Y%m%d-%H%M")}.zip"'
        return response


# ───────────── آمار زنده (اسکن کدهای روی سرور) ─────────────
import ast
import json
import time

_LIVE_CACHE = {'at': 0, 'data': None}
_CACHE_SECONDS = 60
_SKIP_SCAN_DIRS = {'__pycache__', 'node_modules', 'media', '.git', 'staticfiles', 'build', 'venv', 'env', '.venv'}
_NOT_MODELS = ('Admin', 'Serializer', 'ViewSet')


def _first_line(doc):
    if not doc:
        return ''
    for line in doc.strip().splitlines():
        line = line.strip()
        if line:
            return line[:240]
    return ''


def _scan_python(path, rel, app_info):
    try:
        src = path.read_text(encoding='utf-8', errors='ignore')
        tree = ast.parse(src)
    except (SyntaxError, OSError, ValueError):
        return ''
    summary = _first_line(ast.get_docstring(tree))
    if not summary:
        m = re.match(r'\s*(?:#[^\n]*\n)*?\s*#\s*(.+)', src)
        if m and 'Generated by' not in m.group(1):
            summary = m.group(1).strip()[:200]
    in_mig = 'migrations' in rel.split('/')
    if app_info is not None and not in_mig:
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [ast.unparse(b) for b in node.bases]
            doc = _first_line(ast.get_docstring(node))
            if any('Model' in b for b in bases):
                if node.name.endswith(_NOT_MODELS):
                    continue
                fields = 0
                for n in node.body:
                    if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                        fn = ast.unparse(n.value.func)
                        if fn.startswith('models.') and fn not in ('models.Index', 'models.UniqueConstraint', 'models.CheckConstraint'):
                            fields += 1
                app_info['models'].append([node.name, fields, doc])
            elif any(x in ' '.join(bases) for x in ('APIView', 'ViewSet', 'View', 'Generic')):
                methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef) and n.name in ('get', 'post', 'put', 'patch', 'delete')]
                app_info['views'].append([node.name, methods, doc])
        if path.name == 'urls.py':
            for m in re.finditer(r"path\(\s*r?'([^']*)'\s*,\s*([\w\.]+)(?:\.as_view\(\))?", src):
                app_info['routes'].append(['/api/' + m.group(1), m.group(2).replace('views.', '')])
            for m in re.finditer(r"register\(\s*r?'([^']*)'\s*,\s*([\w\.]+)", src):
                app_info['routes'].append(['/api/' + m.group(1) + '/ (ViewSet)', m.group(2)])
    if in_mig and app_info is not None:
        app_info['migrations'] += 1
    return summary


def build_identity_data():
    backend = Path(settings.BASE_DIR).resolve()
    project = backend.parent
    files = []
    apps = {}

    def add_file(path, kind, summary):
        try:
            data = path.read_bytes()
        except OSError:
            return None
        rel = path.relative_to(project).as_posix()
        entry = [rel, kind, data.count(b'\n') + 1, len(data), summary]
        files.append(entry)
        return entry

    for app_dir in sorted(p for p in backend.iterdir() if p.is_dir() and p.name not in _SKIP_SCAN_DIRS and not p.name.startswith('.')):
        info = {'files': 0, 'lines': 0, 'migrations': 0, 'tests': 0, 'models': [], 'views': [], 'routes': []}
        for current, dirs, names in os.walk(app_dir):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_SCAN_DIRS)
            for name in sorted(names):
                path = Path(current) / name
                if path.suffix not in ('.py', '.docx', '.xlsx', '.html', '.json', '.txt', '.css', '.js'):
                    continue
                rel = path.relative_to(project).as_posix()
                summary = _scan_python(path, rel, info) if path.suffix == '.py' else ''
                if 'migrations' in rel.split('/') and path.suffix == '.py':
                    kind = 'backend-migration'
                elif 'test' in name and path.suffix == '.py':
                    kind = 'backend-test'
                    info['tests'] += 1
                else:
                    kind = 'backend'
                entry = add_file(path, kind, summary)
                if entry:
                    info['files'] += 1
                    info['lines'] += entry[2]
        if info['files']:
            info['modelCount'] = len(info['models'])
            info['viewCount'] = len(info['views'])
            info['routeCount'] = len(info['routes'])
            apps[app_dir.name] = info
    for path in sorted(backend.iterdir()):
        if path.is_file() and path.suffix not in EXCLUDE_SUFFIXES and path.name not in EXCLUDE_NAMES:
            add_file(path, 'backend', '')

    frontend = {'pages': [], 'components': [], 'utils': [], 'other': []}
    src_dir = project / 'admin-panel' / 'src'
    if src_dir.is_dir():
        for current, dirs, names in os.walk(src_dir):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_SCAN_DIRS)
            for name in sorted(names):
                path = Path(current) / name
                if path.suffix not in ('.js', '.css', '.svg', '.json'):
                    continue
                if name in ('identityData.js',):
                    continue
                summary = ''
                if path.suffix == '.js':
                    try:
                        head = path.read_text(encoding='utf-8', errors='ignore').splitlines()[:60]
                    except OSError:
                        head = []
                    cm = [l.strip()[2:].strip() for l in head if l.strip().startswith('//') and len(l.strip()) > 6]
                    summary = cm[0][:240] if cm else ''
                entry = add_file(path, 'frontend', summary)
                if not entry:
                    continue
                parts = path.relative_to(src_dir).parts
                group = 'pages' if 'pages' in parts else 'components' if 'components' in parts else 'utils' if 'utils' in parts else 'other'
                frontend[group].append([entry[0], entry[2], summary])
    # اپ موبایل (Expo/React Native): فقط src، با کوتاه‌ترین توضیحِ فارسیِ ابتدای فایل
    app_src = project / 'language_school_app' / 'src'
    if app_src.is_dir():
        for current, dirs, names in os.walk(app_src):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_SCAN_DIRS and d != 'node_modules')
            for name in sorted(names):
                path = Path(current) / name
                if path.suffix not in ('.ts', '.tsx', '.js', '.jsx', '.json'):
                    continue
                summary = ''
                if path.suffix in ('.ts', '.tsx'):
                    try:
                        head = path.read_text(encoding='utf-8', errors='ignore').splitlines()[:40]
                    except OSError:
                        head = []
                    cm = [l.strip()[2:].strip() for l in head if l.strip().startswith('//') and re.search(r'[\u0600-\u06FF]', l)]
                    summary = cm[0][:240] if cm else ''
                add_file(path, 'mobile', summary)
    now = timezone.localtime()
    try:
        import jdatetime
        jalali = jdatetime.datetime.fromgregorian(datetime=now).strftime('%Y/%m/%d %H:%M')
    except Exception:
        jalali = ''
    return {
        'generatedAt': f'{jalali} — {now.strftime("%Y-%m-%d %H:%M")}'.strip(' —'),
        'live': True, 'apps': apps, 'frontend': frontend, 'files': files,
    }


class IdentityDataView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_admin(request):
            return Response({'error': 'فقط مدیر به شناسنامه دسترسی دارد'}, status=status.HTTP_403_FORBIDDEN)
        force = request.query_params.get('refresh') == '1'
        if force or not _LIVE_CACHE['data'] or time.time() - _LIVE_CACHE['at'] > _CACHE_SECONDS:
            _LIVE_CACHE['data'] = build_identity_data()
            _LIVE_CACHE['at'] = time.time()
        return Response(_LIVE_CACHE['data'])


# ───────────── محتوای قابل ویرایش ─────────────
def _content_obj():
    from .models import IdentityContent
    obj = IdentityContent.objects.order_by('id').first()
    if not obj:
        obj = IdentityContent.objects.create()
    return obj


def _content_payload(obj):
    return {
        'meta': obj.meta or {}, 'sections': obj.sections, 'descriptions': obj.descriptions or {},
        'updated_at': obj.updated_at.isoformat() if obj.updated_at else None,
        'updated_by': (obj.updated_by.get_full_name() or obj.updated_by.username) if obj.updated_by_id else '',
    }


class IdentityContentView(APIView):
    """GET: متن‌های ذخیره‌شده — PUT: ذخیره (فقط کلیدهای ارسال‌شده) — DELETE: بازگشت به متن پیش‌فرض."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_admin(request):
            return Response({'error': 'فقط مدیر'}, status=status.HTTP_403_FORBIDDEN)
        return Response(_content_payload(_content_obj()))

    def put(self, request):
        if not _is_admin(request):
            return Response({'error': 'فقط مدیر می‌تواند شناسنامه را ویرایش کند'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data
        obj = _content_obj()
        if 'meta' in data:
            if not isinstance(data['meta'], dict):
                return Response({'error': 'meta باید شیء باشد'}, status=400)
            obj.meta = data['meta']
        if 'sections' in data:
            if data['sections'] is not None and not isinstance(data['sections'], list):
                return Response({'error': 'sections باید فهرست باشد'}, status=400)
            obj.sections = data['sections']
        if 'descriptions' in data:
            descs = data['descriptions']
            if not isinstance(descs, dict):
                return Response({'error': 'descriptions باید شیء باشد'}, status=400)
            obj.descriptions = {str(k)[:300]: str(v)[:2000] for k, v in descs.items() if str(v).strip()}
        if len(json.dumps([obj.meta, obj.sections, obj.descriptions], ensure_ascii=False)) > 2_000_000:
            return Response({'error': 'حجم متن بیش از حد است'}, status=400)
        obj.updated_by = request.user
        obj.save()
        return Response(_content_payload(obj))

    def delete(self, request):
        if not _is_admin(request):
            return Response({'error': 'فقط مدیر'}, status=status.HTTP_403_FORBIDDEN)
        obj = _content_obj()
        part = request.query_params.get('part', 'all')
        if part in ('all', 'meta'):
            obj.meta = {}
        if part in ('all', 'sections'):
            obj.sections = None
        if part in ('all', 'descriptions'):
            obj.descriptions = {}
        obj.updated_by = request.user
        obj.save()
        return Response(_content_payload(obj))
