from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.utils import timezone
from django.core.exceptions import MultipleObjectsReturned
from django.db import transaction
from datetime import timedelta, datetime, date
import random
import re

try:
    import openpyxl
except ImportError:
    openpyxl = None
try:
    import xlrd  # فقط برای خواندن فرمت قدیمی .xls (پیش از Excel 2007) — openpyxl فقط .xlsx می‌خواند
except ImportError:
    xlrd = None
from .models import User, OTPCode, PriceSetting, AppearanceSettings, MenuPermission, AttendanceAccessSettings, AppAccessSettings, MobileMenuVisibility
from .menu_permissions import MENU_ITEMS, MENU_KEYS, CONFIGURABLE_ROLES, EDIT_ENFORCED_MENUS, VIEW_ENFORCED_ONLY_MENUS, get_effective_permissions, get_all_effective_permissions, can_edit_menu, can_view_menu
import string
from .serializers import (
    RegisterSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    UserProfileSerializer,
    TeacherSerializer,
    OfficeStaffSerializer,
    PriceSettingSerializer,
    StudentSerializer,
    UserRoleSerializer,
    AppearanceSettingsSerializer,
    AttendanceAccessSettingsSerializer,
    AppAccessSettingsSerializer,
    MobileMenuVisibilitySerializer
)


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if serializer.is_valid():
            phone = serializer.validated_data['phone']
            try:
                user = User.objects.get(phone=phone)
            except User.DoesNotExist:
                return Response(
                    {'error': 'کاربری با این شماره پیدا نشد'},
                    status=status.HTTP_404_NOT_FOUND
                )
            except MultipleObjectsReturned:
                return Response(
                    {'error': 'چند حساب کاربری با این شماره موبایل ثبت شده (مثلاً چند خواهر/برادر با شماره‌ی مشترک) — برای بازیابی رمز عبور، لطفاً با نام کاربری وارد شوید یا با آموزشگاه تماس بگیرید'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            code = str(random.randint(100000, 999999))
            expires_at = timezone.now() + timedelta(minutes=5)
            OTPCode.objects.create(
                user=user,
                code=code,
                expires_at=expires_at
            )
            print(f'کد OTP برای {phone}: {code}')
            return Response(
                {'message': 'کد تایید ارسال شد'},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if serializer.is_valid():
            phone = serializer.validated_data['phone']
            code = serializer.validated_data['code']
            new_password = serializer.validated_data['new_password']
            try:
                user = User.objects.get(phone=phone)
                otp = OTPCode.objects.filter(
                    user=user,
                    code=code,
                    is_used=False,
                    expires_at__gt=timezone.now()
                ).latest('created_at')
            except (User.DoesNotExist, OTPCode.DoesNotExist):
                return Response(
                    {'error': 'کد نامعتبر یا منقضی شده'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            except MultipleObjectsReturned:
                return Response(
                    {'error': 'چند حساب کاربری با این شماره موبایل ثبت شده — برای بازیابی رمز عبور، لطفاً با نام کاربری وارد شوید یا با آموزشگاه تماس بگیرید'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            user.set_password(new_password)
            user.last_generated_password = ''  # از این پس رمز واقعی را فقط خودِ کاربر می‌داند
            user.save()
            otp.is_used = True
            otp.save()
            return Response(
                {'message': 'رمز عبور با موفقیت تغییر کرد'},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserProfileSerializer

    def get_object(self):
        return self.request.user


class TeacherListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TeacherSerializer

    def get_queryset(self):
        if not can_view_menu(self.request.user, 'teachers'):
            return User.objects.none()
        return User.objects.filter(role__in=User.TEACHER_LIKE_ROLES)

    def create(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'teachers'):
            return Response({'error': 'فقط مدیر می‌تونه استاد اضافه کنه'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class TeacherDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TeacherSerializer

    def get_queryset(self):
        return User.objects.filter(role__in=User.TEACHER_LIKE_ROLES)

    def check_admin(self, request):
        if not can_edit_menu(request.user, 'teachers'):
            return Response({'error': 'فقط مدیر دسترسی دارد'}, status=status.HTTP_403_FORBIDDEN)
        return None

    def update(self, request, *args, **kwargs):
        denied = self.check_admin(request)
        if denied:
            return denied
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        denied = self.check_admin(request)
        if denied:
            return denied
        return super().destroy(request, *args, **kwargs)


class OfficeStaffListCreateView(generics.ListCreateAPIView):
    """
    لیست/ثبت کارمندان اداری و کارمندان — فقط مدیر. (تغییر نقش بین «کارشناس اداری» و «کارمند»
    از دراپ‌داون «تغییر نقش» انجام می‌شود؛ هر دو نقش همچنان در همین لیست می‌مانند.)
    دسترسی‌ها و منوهای اختصاصی این نقش هنوز مشخص نشده؛ فعلاً فقط CRUD پایه (مثل استاد).
    """
    permission_classes = [IsAuthenticated]
    serializer_class = OfficeStaffSerializer

    def get_queryset(self):
        if self.request.user.role != 'admin':
            return User.objects.none()
        return User.objects.filter(role__in=['office', 'employee'])

    def create(self, request, *args, **kwargs):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تواند کارمند اداری اضافه کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class OfficeStaffDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OfficeStaffSerializer

    def get_queryset(self):
        if self.request.user.role != 'admin':
            return User.objects.none()
        return User.objects.filter(role__in=['office', 'employee'])

    def check_admin(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر دسترسی دارد'}, status=status.HTTP_403_FORBIDDEN)
        return None

    def update(self, request, *args, **kwargs):
        denied = self.check_admin(request)
        if denied:
            return denied
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        denied = self.check_admin(request)
        if denied:
            return denied
        return super().destroy(request, *args, **kwargs)


class AppearanceSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(AppearanceSettingsSerializer(AppearanceSettings.get_current()).data)

    def patch(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تواند تنظیمات ظاهر را تغییر دهد'}, status=status.HTTP_403_FORBIDDEN)
        obj = AppearanceSettings.get_current()
        serializer = AppearanceSettingsSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save(updated_by=request.user)
        return Response(AppearanceSettingsSerializer(obj).data)


class AttendanceAccessSettingsView(APIView):
    """
    GET: هر کاربر لاگین‌شده (اپ موبایل کارمند/کارشناس اداری/استاد) می‌خواند تا تصمیم بگیرد
    دکمه‌ی ثبت حضور و غیاب با QR را نشان بدهد یا نه.
    PATCH: فقط مدیر، از صفحه‌ی «تنظیمات دسترسی».
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(AttendanceAccessSettingsSerializer(AttendanceAccessSettings.get_current()).data)

    def patch(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تواند این تنظیمات را تغییر دهد'}, status=status.HTTP_403_FORBIDDEN)
        obj = AttendanceAccessSettings.get_current()
        serializer = AttendanceAccessSettingsSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save(updated_by=request.user)
        return Response(AttendanceAccessSettingsSerializer(obj).data)


class AppAccessSettingsView(APIView):
    """
    GET: هر کاربر لاگین‌شده می‌خواند — اپ موبایل هنگام باز شدن صفحه‌ی خانه چک می‌کند که آیا
    نقش خودش هنوز فعال است یا نه (برای بیرون‌انداختن کاربرانی که از قبل لاگین بودند).
    PATCH: فقط مدیر، از صفحه‌ی «تنظیمات دسترسی» — کلید خاموش/روشن کل اپ استاد/دانش‌آموز/اداری.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(AppAccessSettingsSerializer(AppAccessSettings.get_current()).data)

    def patch(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تواند این تنظیمات را تغییر دهد'}, status=status.HTTP_403_FORBIDDEN)
        obj = AppAccessSettings.get_current()
        serializer = AppAccessSettingsSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save(updated_by=request.user)
        return Response(AppAccessSettingsSerializer(obj).data)


class MobileMenuVisibilityView(APIView):
    """
    GET: هر کاربر لاگین‌شده — اپ موبایل هنگام باز شدن صفحه‌ی خانه می‌خواند تا بداند کدام
    دکمه‌ها را برای نقش خودش مخفی کند (فقط ظاهری، endpoint را نمی‌بندد).
    PATCH: فقط مدیر، از صفحه‌ی «تنظیمات دسترسی» — کل لیست hidden_keys جایگزین می‌شود.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .mobile_menus import MOBILE_MENU_GROUPS
        data = MobileMenuVisibilitySerializer(MobileMenuVisibility.get_current()).data
        data['catalog'] = MOBILE_MENU_GROUPS
        return Response(data)

    def patch(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تواند این تنظیمات را تغییر دهد'}, status=status.HTTP_403_FORBIDDEN)
        obj = MobileMenuVisibility.get_current()
        serializer = MobileMenuVisibilitySerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save(updated_by=request.user)
        return Response(MobileMenuVisibilitySerializer(obj).data)


class PriceSettingView(APIView):
    """
    تنظیمات قیمت فعلی. هر کاربر لاگین‌شده (مثلاً اپ دانش‌آموز برای پیش‌نمایش قیمت)
    می‌تواند بخواند؛ فقط مدیر می‌تواند تغییر دهد.
    """
    permission_classes = [IsAuthenticated]

    def get_current(self):
        price_setting = PriceSetting.objects.order_by('-updated_at').first()
        if not price_setting:
            price_setting = PriceSetting.objects.create()
        return price_setting

    def get(self, request):
        from class_management.models import PaymentSettings
        from class_management.serializers import PaymentSettingsSerializer
        serializer = PriceSettingSerializer(self.get_current())
        data = dict(serializer.data)
        data['payment_settings'] = PaymentSettingsSerializer(PaymentSettings.get_solo()).data
        return Response(data)

    def patch(self, request):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'فقط مدیر می‌تونه قیمت رو تغییر بده'}, status=status.HTTP_403_FORBIDDEN)
        price_setting = self.get_current()
        serializer = PriceSettingSerializer(price_setting, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(updated_by=request.user)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class StudentListView(generics.ListCreateAPIView):
    """لیست + افزودن دانش‌آموز جدید (هم آن‌هایی که از کانتر ثبت شدند هم از طریق اپ) — فقط برای مدیر"""
    permission_classes = [IsAuthenticated]
    serializer_class = StudentSerializer

    def get_queryset(self):
        if not can_view_menu(self.request.user, 'students'):
            return User.objects.none()
        return User.objects.filter(role='student').order_by('-id')

    def create(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'students'):
            return Response({'error': 'فقط مدیر می‌تونه دانش‌آموز اضافه کنه'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


def _excel_value(row, aliases):
    for alias in aliases:
        value = row.get(alias)
        if value not in (None, ''):
            return str(value).strip()
    return ''


def _normalize_excel_header(value):
    text = str(value or '').strip().lower().replace('ي', 'ی').replace('ك', 'ک').replace('_', '').replace('-', '')
    return re.sub(r'\s+', '', text)


def _parse_excel_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)) and 1 < value < 90000:
        # فایل‌های .xls قدیمی (xlrd) تاریخ را به‌صورت عدد سریال اکسل برمی‌گردانند، نه datetime
        try:
            base = datetime(1899, 12, 30)  # مبدأ تاریخ سریال اکسل (سیستم رایج‌تر 1900)
            return (base + timedelta(days=float(value))).date().isoformat()
        except (OverflowError, ValueError):
            pass
    raw = str(value or '').strip()
    if not raw:
        return ''
    for fmt in ('%Y-%m-%d', '%Y/%m/%d'):
        try: return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError: pass
    return raw


# لیست کامل مترادف‌های هر ستون — برای تطبیق خودکار با هر مدل جدول/چیدمانی از اکسل که کارمند
# آپلود کند (اسم دقیق ستون‌ها مهم نیست، فقط باید یکی از این عبارات را در خودش داشته باشد).
STUDENT_FIELD_ALIASES = {
    'first_name': ['نام', 'نامکوچک', 'اسم', 'firstname', 'first_name', 'fname', 'name'],
    'last_name': ['نامخانوادگی', 'نامفامیل', 'فامیل', 'فامیلی', 'lastname', 'last_name', 'surname', 'familyname'],
    'father_name': ['نامپدر', 'نامولی', 'fathername', 'father_name', 'parentname'],
    'national_code': ['کدملی', 'شمارهملی', 'کدملی۱۰رقمی', 'nationalcode', 'national_code', 'nationalid', 'idnumber'],
    'phone': ['موبایل', 'شمارهموبایل', 'شمارهتماس', 'شمارهتلفن', 'تلفنهمراه', 'تلفن', 'همراه', 'phone', 'mobile', 'cell', 'cellphone', 'phonenumber', 'mobilenumber', 'contact'],
    'phone2': ['موبایلدوم', 'تلفندوم', 'تماسدوم', 'شمارهدوم', 'phone2', 'mobile2', 'secondphone', 'altphone', 'alternatephone'],
    'birth_date': ['تاریختولد', 'تولد', 'birthdate', 'birth_date', 'dob', 'dateofbirth'],
    'gender': ['جنسیت', 'gender', 'sex'],
    'language_level': ['سطح', 'سطحزبان', 'سطحفعلی', 'languagelevel', 'language_level', 'level', 'currentlevel'],
}


STUDENT_FIELD_LABELS = {
    'first_name': 'نام',
    'last_name': 'نام خانوادگی',
    'father_name': 'نام پدر',
    'national_code': 'کد ملی',
    'phone': 'موبایل',
    'phone2': 'موبایل دوم',
    'birth_date': 'تاریخ تولد',
    'gender': 'جنسیت',
    'language_level': 'سطح زبان',
}


def _auto_map_headers(headers):
    """
    برای هر ستون خام اکسل (هر ترتیب/اسمی)، بهترین فیلد متناظر را پیدا می‌کند —
    اول تطابق دقیق روی مترادف‌ها، بعد (اگر پیدا نشد) تطابق زیررشته‌ای (شامل‌بودن).
    خروجی: dict از {field_key: column_index یا None}
    """
    positions = {}
    used_columns = set()
    for key, aliases in STUDENT_FIELD_ALIASES.items():
        found = None
        for idx, header in enumerate(headers):
            if idx in used_columns:
                continue
            if header in aliases:
                found = idx
                break
        if found is None:
            for idx, header in enumerate(headers):
                if idx in used_columns or not header:
                    continue
                if any(alias in header or header in alias for alias in aliases):
                    found = idx
                    break
        if found is not None:
            used_columns.add(found)
        positions[key] = found
    return positions


def _find_header_row(rows, max_scan=5):
    """
    ردیف عنوان‌ها همیشه ردیف اول نیست (گاهی یک ردیف عنوان کلی یا خالی قبلش هست) — بین
    ۵ ردیف اول، ردیفی که بیشترین تطابق با مترادف‌های شناخته‌شده دارد را به‌عنوان هدر انتخاب می‌کند.
    """
    best_row_index, best_score = 0, -1
    for i, raw_row in enumerate(rows[:max_scan]):
        headers = [_normalize_excel_header(x) for x in raw_row]
        mapping = _auto_map_headers(headers)
        score = sum(1 for v in mapping.values() if v is not None)
        if score > best_score:
            best_score, best_row_index = score, i
    return best_row_index


def _load_excel_rows(uploaded_file):
    """
    فایل آپلودشده را چه .xlsx (فرمت جدید، zip-based) چه .xls (فرمت قدیمی ۹۷-۲۰۰۳) باشد،
    به یک لیست ساده از سطرها (هر سطر = tuple مقادیر) تبدیل می‌کند. تشخیص فرمت از روی
    محتوای واقعیِ فایل انجام می‌شود (نه فقط پسوند اسم فایل) چون کاربر ممکن است پسوند را
    اشتباه گذاشته باشد.
    """
    name = (getattr(uploaded_file, 'name', '') or '').lower()
    uploaded_file.seek(0)
    header_bytes = uploaded_file.read(8)
    uploaded_file.seek(0)
    is_legacy_xls = header_bytes[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'  # امضای فایل OLE (فرمت قدیمی xls)
    is_zip_xlsx = header_bytes[:2] == b'PK'  # امضای zip (فرمت جدید xlsx)

    if is_legacy_xls or (name.endswith('.xls') and not is_zip_xlsx):
        if xlrd is None:
            raise RuntimeError('این فایل با فرمت قدیمی Excel (.xls) است و کتابخانه‌ی xlrd روی سرور نصب نیست؛ pip install xlrd را اجرا کنید یا فایل را با فرمت xlsx ذخیره کنید')
        book = xlrd.open_workbook(file_contents=uploaded_file.read())
        sheet = book.sheet_by_index(0)
        return [tuple(sheet.row_values(r)) for r in range(sheet.nrows)]

    if openpyxl is None:
        raise RuntimeError('کتابخانه خواندن Excel روی سرور نصب نیست؛ openpyxl را نصب کنید')
    try:
        workbook = openpyxl.load_workbook(uploaded_file, read_only=True, data_only=True)
    except Exception:
        raise RuntimeError('این فایل به‌عنوان Excel معتبر (xlsx یا xls) خوانده نشد. لطفاً مطمئن شوید فایل خراب نیست و با فرمت Excel واقعی (نه مثلاً CSV با پسوند تغییریافته) ذخیره شده است.')
    sheet = workbook.active
    return list(sheet.iter_rows(values_only=True))


def _read_student_excel(uploaded_file, manual_mapping=None):
    """
    manual_mapping (اختیاری): dict از {field_key: column_index} که کارمند از پنل «تطبیق ستون‌ها»
    ارسال کرده — اگر داده شود، جای تشخیص خودکار همان استفاده می‌شود (برای فیلدهایی که خودکار
    درست تشخیص داده نشدند).
    """
    rows = _load_excel_rows(uploaded_file)
    if not rows:
        return {'rows': [], 'headers': [], 'positions': {}, 'header_row_index': 0}
    header_row_index = _find_header_row(rows)
    raw_headers = list(rows[header_row_index])
    headers = [_normalize_excel_header(x) for x in raw_headers]
    positions = _auto_map_headers(headers)
    if manual_mapping:
        for key, idx in manual_mapping.items():
            if key in positions:
                positions[key] = idx if idx is not None and idx >= 0 else None
    output = []
    for row_number, values in enumerate(rows[header_row_index + 1:], start=header_row_index + 2):
        if values is None or all(v in (None, '') for v in values):
            continue  # ردیف کاملاً خالی را نادیده می‌گیرد (مثلاً انتهای فایل)
        raw = {key: (values[pos] if pos is not None and pos < len(values) else '') for key, pos in positions.items()}
        item = {key: (_parse_excel_date(value) if key == 'birth_date' else str(value or '').strip()) for key, value in raw.items()}
        item['_row_number'] = row_number
        output.append(item)
    return {
        'rows': output,
        'headers': [str(h or '').strip() for h in raw_headers],
        'positions': positions,
        'header_row_index': header_row_index,
    }


def _student_import_preview(items):
    digit_translation = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
    gender_map = {'خانم': 'female', 'زن': 'female', 'دختر': 'female', 'female': 'female', 'آقا': 'male', 'مرد': 'male', 'پسر': 'male', 'male': 'male'}
    result = []
    for item in items:
        item = dict(item)
        errors = []
        national = re.sub(r'\D', '', str(item.get('national_code') or '').translate(digit_translation))
        phone = re.sub(r'\D', '', str(item.get('phone') or '').translate(digit_translation))
        item['national_code'] = national
        item['phone'] = phone
        item['gender'] = gender_map.get(str(item.get('gender') or '').strip().lower(), str(item.get('gender') or '').strip())
        if not item.get('first_name') or not item.get('last_name'): errors.append('نام و نام خانوادگی الزامی است')
        if not national and not phone: errors.append('کد ملی یا شماره موبایل الزامی است')
        if national and len(national) != 10: errors.append('کد ملی باید ۱۰ رقم باشد')
        if phone and len(phone) not in (10, 11): errors.append('شماره موبایل معتبر نیست')
        if item['gender'] and item['gender'] not in ('female', 'male'): errors.append('جنسیت باید خانم/آقا یا female/male باشد')
        if national:
            duplicate = User.objects.filter(role='student', national_code=national).first()
        else:
            duplicate = User.objects.filter(role='student', first_name=item.get('first_name'), last_name=item.get('last_name'), phone=phone).first()
        item['existing_student_id'] = duplicate.id if duplicate else None
        item['status'] = 'duplicate' if duplicate else ('error' if errors else 'new')
        item['errors'] = errors
        result.append(item)
    return result


class StudentExcelImportView(APIView):
    permission_classes = [IsAuthenticated]

    def _allowed(self, request):
        return request.user.role in ('admin', 'office')

    def post(self, request):
        if not self._allowed(request):
            return Response({'error': 'فقط مدیر یا کارمند اداری می‌تواند ورود Excel را انجام دهد'}, status=status.HTTP_403_FORBIDDEN)
        mode = request.data.get('mode', 'preview')
        try:
            if mode == 'preview':
                uploaded = request.FILES.get('file')
                if not uploaded:
                    return Response({'error': 'فایل Excel را انتخاب کنید'}, status=400)
                manual_mapping = None
                raw_mapping = request.data.get('mapping')
                if raw_mapping:
                    import json
                    parsed_mapping = json.loads(raw_mapping) if isinstance(raw_mapping, str) else raw_mapping
                    manual_mapping = {k: (int(v) if v not in (None, '', 'null') else None) for k, v in parsed_mapping.items()}
                parsed_file = _read_student_excel(uploaded, manual_mapping)
                items = _student_import_preview(parsed_file['rows'])
                return Response({
                    'rows': items,
                    'total': len(items),
                    'new_count': sum(x['status'] == 'new' for x in items),
                    'duplicate_count': sum(x['status'] == 'duplicate' for x in items),
                    'error_count': sum(x['status'] == 'error' for x in items),
                    'headers': parsed_file['headers'],
                    'positions': parsed_file['positions'],
                    'header_row_index': parsed_file['header_row_index'],
                    'field_labels': STUDENT_FIELD_LABELS,
                })
            if mode != 'commit': return Response({'error': 'حالت واردکردن معتبر نیست'}, status=400)
            rows = request.data.get('rows') or []
            if isinstance(rows, str):
                import json
                rows = json.loads(rows)
            committed = []; skipped = []; errors = []
            with transaction.atomic():
                for item in rows:
                    item = dict(item); status_value = item.get('status')
                    if status_value != 'new': skipped.append({'row_number': item.get('_row_number'), 'reason': 'تکراری یا دارای خطا'}); continue
                    national = str(item.get('national_code') or '').strip() or None
                    if national and User.objects.filter(national_code=national).exists(): skipped.append({'row_number': item.get('_row_number'), 'reason': 'کد ملی قبلاً ثبت شده'}); continue
                    username_base = national or str(item.get('phone') or '').strip() or f"student_{item.get('_row_number')}"
                    username = username_base; suffix = 1
                    while User.objects.filter(username=username).exists(): username = f'{username_base}_{suffix}'; suffix += 1
                    try:
                        user = User(username=username, first_name=item.get('first_name', '').strip(), last_name=item.get('last_name', '').strip(), father_name=item.get('father_name', '').strip(), national_code=national, phone=item.get('phone', '').strip(), phone2=item.get('phone2', '').strip(), birth_date=item.get('birth_date') or None, gender=item.get('gender', ''), language_level=item.get('language_level', '').strip(), role=User.Role.STUDENT, needs_editing=False)
                        user.set_unusable_password(); user.save()
                        committed.append({'row_number': item.get('_row_number'), 'student_id': user.id, 'name': user.get_full_name()})
                    except Exception as exc:
                        errors.append({'row_number': item.get('_row_number'), 'reason': str(exc)})
            return Response({'message': f'{len(committed)} دانش‌آموز با موفقیت اضافه شد', 'committed': committed, 'skipped': skipped, 'errors': errors})
        except Exception as exc:
            return Response({'error': str(exc)}, status=400)


class StudentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """ویرایش/حذف مشخصات یک دانش‌آموز (نام، نام‌خانوادگی، موبایل، کد ملی، سطح) — فقط برای مدیر"""
    permission_classes = [IsAuthenticated]
    serializer_class = StudentSerializer

    def get_queryset(self):
        return User.objects.filter(role='student')

    def update(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'students'):
            return Response({'error': 'فقط مدیر می‌تونه ویرایش کنه'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'students'):
            return Response({'error': 'فقط مدیر می‌تونه حذف کنه'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class UserRoleView(APIView):
    """تغییر نقش هر کاربری (مثلاً ارتقای کاربری که از اپ ثبت‌نام کرده) — فقط برای مدیر"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تواند نقش را تغییر دهد'}, status=status.HTTP_403_FORBIDDEN)
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({'error': 'کاربر پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        new_role = request.data.get('role')
        if new_role not in [User.Role.ADMIN, User.Role.TEACHER, User.Role.STUDENT, User.Role.EVALUATOR, User.Role.OFFICE, User.Role.EMPLOYEE]:
            return Response({'error': 'نقش نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)

        user.role = new_role
        user.save()
        return Response(UserRoleSerializer(user).data)


class PeopleSearchView(APIView):
    """
    جستجوی سراسری افراد بر اساس کد ملی، نام، یا نام‌خانوادگی، برای پرکردن خودکار فرم‌ها با اطلاعات
    قبلاً ثبت‌شده (دانش‌آموزان، لیست انتظار ورودی جدید، زبان‌آموزان ثبت‌نام‌نشده، بدهکاران) —
    تا کاربر مجبور به تایپ دوباره‌ی اطلاعات یک نفر که قبلاً جایی ثبت شده نباشد.
    فقط برای مدیر/مسئول آموزش (کسانی که این فرم‌ها را پر می‌کنند).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in ('admin', 'evaluator'):
            return Response([])
        q = request.query_params.get('q', '').strip()
        if len(q) < 2:
            return Response([])

        from django.db.models import Q
        results = []
        seen = set()

        def add(first_name, last_name, father_name, national_code, phone, phone2, source):
            key = (national_code or '', phone or '', first_name, last_name)
            if key in seen:
                return
            seen.add(key)
            results.append({
                'first_name': first_name, 'last_name': last_name, 'father_name': father_name or '',
                'national_code': national_code or '', 'phone': phone or '', 'phone2': phone2 or '',
                'source': source,
            })

        students = User.objects.filter(role='student').filter(
            Q(national_code__icontains=q) | Q(last_name__icontains=q) | Q(first_name__icontains=q)
        )[:8]
        for s in students:
            add(s.first_name, s.last_name, s.father_name, s.national_code, s.phone, s.phone2, 'دانش‌آموز')

        try:
            from leads.models import NewLead, UnregisteredStudent, Debtor, DiscountedPerson
            for lead in NewLead.objects.filter(Q(national_code__icontains=q) | Q(last_name__icontains=q) | Q(first_name__icontains=q))[:8]:
                add(lead.first_name, lead.last_name, lead.father_name, lead.national_code, lead.phone, '', 'لیست انتظار')
            for us in UnregisteredStudent.objects.filter(Q(national_code__icontains=q) | Q(last_name__icontains=q) | Q(first_name__icontains=q))[:8]:
                add(us.first_name, us.last_name, '', us.national_code, us.phone, '', 'ثبت‌نام‌نشده')
            for d in Debtor.objects.filter(Q(last_name__icontains=q) | Q(first_name__icontains=q))[:8]:
                add(d.first_name, d.last_name, '', '', d.phone, '', 'بدهکار')
            for dp in DiscountedPerson.objects.filter(Q(national_code__icontains=q) | Q(last_name__icontains=q) | Q(first_name__icontains=q))[:8]:
                add(dp.first_name, dp.last_name, '', dp.national_code, '', '', 'دارای تخفیف')
        except ImportError:
            pass

        return Response(results[:10])


class StudentQuickSearchView(APIView):
    """
    جستجوی مخصوص «ثبت دانش‌آموز در کلاس فیزیکی» — فقط بین دانش‌آموزهای واقعاً
    ثبت‌نام‌شده (نه لیست انتظار/بدهکار و...)، و برخلاف PeopleSearchView، اینجا
    آیدی واقعی کاربر (student.id) هم برمی‌گرده چون لازمه مستقیم برای enroll استفاده بشه.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in ('admin', 'evaluator', 'office'):
            return Response([])
        q = request.query_params.get('q', '').strip()
        if len(q) < 2:
            return Response([])

        from django.db.models import Q
        students = User.objects.filter(role='student').filter(
            Q(national_code__icontains=q) | Q(last_name__icontains=q) | Q(first_name__icontains=q)
        )[:10]
        return Response([{
            'id': s.id,
            'first_name': s.first_name,
            'last_name': s.last_name,
            'father_name': s.father_name or '',
            'national_code': s.national_code or '',
            'phone': s.phone or '',
            'gender': s.gender or '',
            'language_level': s.language_level or '',
        } for s in students])


class MenuPermissionSettingsView(APIView):
    """
    تنظیمات دسترسی — فقط مدیر می‌تواند ببیند/ویرایش کند که هرکدام از نقش‌های کارمند/
    کارشناس اداری/کارشناس آموزش به کدام منوهای پنل ادمین دسترسی دارند.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر به تنظیمات دسترسی دسترسی دارد'}, status=status.HTTP_403_FORBIDDEN)
        return Response({
            'menu_items': [
                {'key': key, 'label': label, 'edit_enforced': key in EDIT_ENFORCED_MENUS, 'view_enforced': key in EDIT_ENFORCED_MENUS or key in VIEW_ENFORCED_ONLY_MENUS}
                for key, label, _ in MENU_ITEMS
            ],
            'roles': [{'value': value, 'label': label} for value, label in User.Role.choices if value in CONFIGURABLE_ROLES],
            'permissions': get_all_effective_permissions(),
        })

    def put(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تواند تنظیمات دسترسی را تغییر دهد'}, status=status.HTTP_403_FORBIDDEN)
        permissions = request.data.get('permissions') or {}
        if not isinstance(permissions, dict):
            return Response({'error': 'قالب داده نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        for role, menu_map in permissions.items():
            if role not in CONFIGURABLE_ROLES or not isinstance(menu_map, dict):
                continue
            for menu_key, entry in menu_map.items():
                if menu_key not in MENU_KEYS or not isinstance(entry, dict):
                    continue
                view_val = bool(entry.get('view'))
                edit_val = bool(entry.get('edit')) and view_val  # ویرایش بدون نمایش بی‌معنیه
                MenuPermission.objects.update_or_create(
                    role=role, menu_key=menu_key, defaults={'enabled': view_val, 'can_edit': edit_val},
                )
        return Response({'permissions': get_all_effective_permissions()})


class MyMenuPermissionsView(APIView):
    """دسترسی خودِ کاربر لاگین‌شده به منوهای پنل ادمین — برای ساخت داینامیک منو در فرانت‌اند."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        role = request.user.role
        if role not in CONFIGURABLE_ROLES:
            # مدیر (و نقش‌های غیرمرتبط با پنل ادمین) همیشه به همه‌ی منوها دسترسی کامل دارند
            return Response({key: {'view': True, 'edit': True} for key, _, _ in MENU_ITEMS})
        return Response(get_effective_permissions(role))


def _generate_username():
    return 'user' + ''.join(random.choices(string.digits, k=5))


def _generate_password():
    upper = 'ABCDEFGHJKLMNPQRSTUVWXYZ'  # بدون حروف شبیه‌به‌هم مثل I/O
    lower = 'abcdefghijkmnpqrstuvwxyz'
    digits = '23456789'
    chars = [random.choice(upper), random.choice(lower), random.choice(digits)]
    chars += random.choices(upper + lower + digits, k=7)
    random.shuffle(chars)
    return ''.join(chars)


def _staff_credentials_payload(user):
    return {
        'id': user.id,
        'full_name': f'{user.first_name} {user.last_name}'.strip() or user.username,
        'role': user.role,
        'role_label': user.get_role_display(),
        'username': user.username,
        'last_login': user.last_login.isoformat() if user.last_login else None,
        'last_generated_password': user.last_generated_password or None,
    }


class StaffCredentialsListView(APIView):
    """
    یوزر/پسورد ورود کارمند/کارشناس اداری/کارشناس آموزش — همه‌جا در «تنظیمات دسترسی».
    فقط مدیر می‌بیند و تغییر می‌دهد.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر دسترسی دارد'}, status=status.HTTP_403_FORBIDDEN)
        users = User.objects.filter(role__in=CONFIGURABLE_ROLES).order_by('first_name', 'last_name')
        return Response([_staff_credentials_payload(u) for u in users])


class StaffCredentialsDetailView(APIView):
    """PATCH: تنظیم دستیِ نام‌کاربری، یا تولید تصادفیِ یوزر/پسورد جدید — فقط مدیر."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر دسترسی دارد'}, status=status.HTTP_403_FORBIDDEN)
        try:
            user = User.objects.get(pk=pk, role__in=CONFIGURABLE_ROLES)
        except User.DoesNotExist:
            return Response({'error': 'کاربر یافت نشد'}, status=status.HTTP_404_NOT_FOUND)

        if request.data.get('generate_random'):
            new_username = _generate_username()
            while User.objects.filter(username=new_username).exclude(pk=user.pk).exists():
                new_username = _generate_username()
            new_password = _generate_password()
            user.username = new_username
            user.set_password(new_password)
            user.last_generated_password = new_password
            user.save()
            return Response(_staff_credentials_payload(user))

        new_username = (request.data.get('username') or '').strip()
        if new_username:
            if User.objects.filter(username=new_username).exclude(pk=user.pk).exists():
                return Response({'error': 'این نام‌کاربری قبلاً استفاده شده است'}, status=status.HTTP_400_BAD_REQUEST)
            user.username = new_username
            user.save()
        return Response(_staff_credentials_payload(user))