from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.utils import timezone
from django.core.exceptions import MultipleObjectsReturned
from django.db import transaction, IntegrityError
from datetime import timedelta, datetime, date
import random
import re
import jdatetime

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    import xlrd
except ImportError:
    xlrd = None
from .models import User, OTPCode, PriceSetting, AppearanceSettings, MenuPermission
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
    AppearanceSettingsSerializer
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
        if self.request.user.role not in ('admin', 'office'):
            return User.objects.none()
        return User.objects.filter(role__in=User.TEACHER_LIKE_ROLES)

    def create(self, request, *args, **kwargs):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'فقط مدیر می‌تونه استاد اضافه کنه'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class TeacherDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TeacherSerializer

    def get_queryset(self):
        return User.objects.filter(role__in=User.TEACHER_LIKE_ROLES)

    def check_admin(self, request):
        if request.user.role not in ('admin', 'office'):
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
    لیست/ثبت کارمندان اداری — فقط مدیر.
    دسترسی‌ها و منوهای اختصاصی این نقش هنوز مشخص نشده؛ فعلاً فقط CRUD پایه (مثل استاد).
    """
    permission_classes = [IsAuthenticated]
    serializer_class = OfficeStaffSerializer

    def get_queryset(self):
        if self.request.user.role != 'admin':
            return User.objects.none()
        return User.objects.filter(role='office')

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
        return User.objects.filter(role='office')

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
        if self.request.user.role not in ('admin', 'office'):
            return User.objects.none()
        return User.objects.filter(role='student').order_by('-id')

    def create(self, request, *args, **kwargs):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'فقط مدیر می‌تونه دانش‌آموز اضافه کنه'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


def _excel_value(row, aliases):
    for alias in aliases:
        value = row.get(alias)
        if value not in (None, ''):
            return str(value).strip()
    return ''


def _normalize_excel_header(value):
    return (
        str(value or '').strip().lower()
        .replace('ي', 'ی').replace('ى', 'ی').replace('ك', 'ک')
        .replace(' ', '').replace('\u200c', '').replace('\u200d', '')
        .replace('_', '').replace('-', '').replace('/', '').replace('\\\\', '')
    )


def _parse_excel_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value or '').strip().translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))
    if not raw:
        return ''
    normalized = raw.replace('.', '/').replace('-', '/')
    parts = normalized.split('/')
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        year, month, day = (int(part) for part in parts)
        try:
            if 1300 <= year <= 1500:
                return jdatetime.date(year, month, day).togregorian().isoformat()
            return date(year, month, day).isoformat()
        except ValueError:
            return raw
    for fmt in ('%Y-%m-%d', '%Y/%m/%d'):
        try: return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError: pass
    return raw


def _read_student_excel(uploaded_file):
    """خواندن xlsx و xls با شناسایی ردیف header در چند ردیف اول فایل."""
    filename = str(getattr(uploaded_file, 'name', '') or '').lower()
    if filename.endswith('.xls') and not filename.endswith('.xlsx'):
        if xlrd is None:
            raise RuntimeError('کتابخانه خواندن فایل xls روی سرور نصب نیست؛ xlrd را نصب کنید')
        try:
            book = xlrd.open_workbook(file_contents=uploaded_file.read())
            sheet = book.sheet_by_index(0)
            rows = []
            for row_index in range(sheet.nrows):
                values = []
                for col_index in range(sheet.ncols):
                    cell = sheet.cell(row_index, col_index)
                    value = cell.value
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        value = xlrd.xldate_as_datetime(value, book.datemode)
                    values.append(value)
                rows.append(values)
        except Exception as exc:
            raise ValueError(f'فایل xls قابل خواندن نیست: {exc}') from exc
    else:
        if openpyxl is None:
            raise RuntimeError('کتابخانه خواندن فایل xlsx روی سرور نصب نیست؛ openpyxl را نصب کنید')
        try:
            uploaded_file.seek(0)
            workbook = openpyxl.load_workbook(uploaded_file, read_only=True, data_only=True)
            sheet = workbook.active
            rows = [list(values) for values in sheet.iter_rows(values_only=True)]
        except Exception as exc:
            raise ValueError(f'فایل xlsx قابل خواندن نیست؛ مطمئن شوید فایل واقعاً Excel است: {exc}') from exc
    if not rows:
        return []

    aliases = {
        'first_name': ['نام', 'firstname', 'نامکوچک'],
        'last_name': ['نامخانوادگی', 'نامفامیل', 'lastname'],
        'father_name': ['نامپدر', 'fathername'],
        'national_code': ['کدملی', 'nationalcode'],
        'phone': ['موبایل', 'شمارهتلفن', 'تلفن', 'phone', 'mobile'],
        'phone2': ['موبایلدوم', 'تلفندوم', 'phone2', 'mobile2'],
        'birth_date': ['تاریختولد', 'birthdate'],
        'gender': ['جنسیت', 'gender'],
        'language_level': ['سطح', 'سطحزبان', 'languagelevel', 'level'],
    }
    known_aliases = {alias for values in aliases.values() for alias in values}
    header_index = next(
        (index for index, values in enumerate(rows[:10])
         if sum(_normalize_excel_header(value) in known_aliases for value in values) >= 2),
        None,
    )
    if header_index is None:
        raise ValueError('ردیف عنوان ستون‌ها پیدا نشد؛ ستون‌هایی مانند نام، نام خانوادگی، کد ملی یا موبایل را در ردیف اول قرار دهید')
    headers = [_normalize_excel_header(value) for value in rows[header_index]]
    positions = {key: next((headers.index(alias) for alias in values if alias in headers), None) for key, values in aliases.items()}
    output = []
    for row_number, values in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(value not in (None, '') for value in values):
            continue
        raw = {key: (values[position] if position is not None and position < len(values) else '') for key, position in positions.items()}
        item = {key: (_parse_excel_date(value) if key == 'birth_date' else str(value or '').strip()) for key, value in raw.items()}
        item['_row_number'] = row_number
        output.append(item)
    return output


def _student_import_preview(items):
    digit_translation = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
    gender_map = {
        'خانم': 'female', 'خانوم': 'female', 'زن': 'female', 'دختر': 'female', 'female': 'female',
        'آقا': 'male', 'اقا': 'male', 'مرد': 'male', 'پسر': 'male', 'male': 'male',
    }
    persian_name = re.compile(r'^[\u0600-\u06FF\s\u200C]+$')
    result = []
    seen_nationals = set()
    seen_identity = set()
    for item in items:
        item = dict(item)
        errors = []
        national = re.sub(r'\D', '', str(item.get('national_code') or '').translate(digit_translation))
        phone = re.sub(r'\D', '', str(item.get('phone') or '').translate(digit_translation))
        if 1 <= len(national) < 10:
            national = national.zfill(10)
        if len(phone) == 10 and phone.startswith('9'):
            phone = '0' + phone
        first_name = ' '.join(str(item.get('first_name') or '').split())
        last_name = ' '.join(str(item.get('last_name') or '').split())
        father_name = ' '.join(str(item.get('father_name') or '').split())
        gender_raw = str(item.get('gender') or '').strip().lower()
        item.update({'first_name': first_name, 'last_name': last_name, 'father_name': father_name, 'national_code': national, 'phone': phone, 'gender': gender_map.get(gender_raw, gender_raw)})
        if not first_name or not last_name:
            errors.append('نام و نام خانوادگی الزامی است')
        for label, value in (('نام', first_name), ('نام خانوادگی', last_name), ('نام پدر', father_name)):
            if value and not persian_name.fullmatch(value):
                errors.append(f'{label} باید با حروف فارسی باشد')
        if not national and not phone:
            errors.append('کد ملی یا شماره موبایل الزامی است')
        if national and len(national) != 10:
            errors.append('کد ملی باید ۱۰ رقم باشد')
        if phone and (len(phone) != 11 or not phone.startswith('09')):
            errors.append('شماره موبایل باید با ۰۹ و ۱۱ رقم باشد')
        if item['gender'] and item['gender'] not in ('female', 'male'):
            errors.append('جنسیت باید خانم/آقا یا female/male باشد')
        duplicate = None
        duplicate_in_file = False
        if national:
            duplicate_in_file = national in seen_nationals
            seen_nationals.add(national)
            duplicate = User.objects.filter(national_code=national).first()
        elif phone:
            identity_key = (first_name, last_name, phone)
            duplicate_in_file = identity_key in seen_identity
            seen_identity.add(identity_key)
            duplicate = User.objects.filter(first_name=first_name, last_name=last_name, phone=phone).first()
        if duplicate_in_file:
            errors.append('این رکورد در همین فایل تکراری است')
        item['existing_student_id'] = duplicate.id if duplicate else None
        item['status'] = 'error' if errors else ('duplicate' if duplicate else 'new')
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
                if not uploaded: return Response({'error': 'فایل Excel را انتخاب کنید'}, status=400)
                items = _student_import_preview(_read_student_excel(uploaded))
                return Response({'rows': items, 'total': len(items), 'new_count': sum(x['status'] == 'new' for x in items), 'duplicate_count': sum(x['status'] == 'duplicate' for x in items), 'error_count': sum(x['status'] == 'error' for x in items)})
            if mode != 'commit': return Response({'error': 'حالت واردکردن معتبر نیست'}, status=400)
            rows = request.data.get('rows') or []
            if isinstance(rows, str):
                import json
                rows = json.loads(rows)
            if not isinstance(rows, list):
                return Response({'error': 'ساختار دادهٔ ثبت نهایی Excel معتبر نیست'}, status=400)
            committed = []; skipped = []; errors = []
            for raw_item in rows:
                item = dict(raw_item or {})
                # وضعیت و مقادیر از سمت مرورگر قابل اعتماد نیستند؛ هر ردیف دوباره روی سرور بررسی می‌شود.
                normalized = _student_import_preview([item])[0] if item else {'status': 'error', '_row_number': None, 'errors': ['ردیف خالی است']}
                row_number = normalized.get('_row_number')
                if normalized.get('status') != 'new':
                    skipped.append({'row_number': row_number, 'reason': ' / '.join(normalized.get('errors') or ['تکراری یا دارای خطا'])})
                    continue
                national = str(normalized.get('national_code') or '').strip() or None
                username_base = national or str(normalized.get('phone') or '').strip() or f"student_{row_number}"
                username = username_base; suffix = 1
                while User.objects.filter(username=username).exists():
                    username = f'{username_base}_{suffix}'; suffix += 1
                try:
                    # تراکنش مستقل برای هر ردیف اجازه می‌دهد یک ردیف خراب، ردیف‌های سالم را rollback نکند.
                    with transaction.atomic():
                        user = User(username=username, first_name=normalized.get('first_name', '').strip(), last_name=normalized.get('last_name', '').strip(), father_name=normalized.get('father_name', '').strip(), national_code=national, phone=normalized.get('phone', '').strip(), phone2=normalized.get('phone2', '').strip(), birth_date=normalized.get('birth_date') or None, gender=normalized.get('gender', ''), language_level=normalized.get('language_level', '').strip(), role=User.Role.STUDENT, needs_editing=False)
                        user.set_unusable_password()
                        user.full_clean()
                        user.save()
                    committed.append({'row_number': row_number, 'student_id': user.id, 'name': user.get_full_name()})
                except (Exception, IntegrityError) as exc:
                    errors.append({'row_number': row_number, 'reason': str(exc) or 'خطای پایگاه‌داده'})
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
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'فقط مدیر می‌تونه ویرایش کنه'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role not in ('admin', 'office'):
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
    """تنظیم دسترسی منوها برای نقش‌های کارمند، اداری و کارشناس آموزش؛ فقط مدیر."""
    permission_classes = [IsAuthenticated]

    def _admin_only(self, request):
        if request.user.role != User.Role.ADMIN:
            return Response({'error': 'فقط مدیر به تنظیمات دسترسی دسترسی دارد'}, status=status.HTTP_403_FORBIDDEN)
        return None

    def get(self, request):
        denied = self._admin_only(request)
        if denied:
            return denied
        from .menu_permissions import (
            MENU_ITEMS,
            CONFIGURABLE_ROLES,
            EDIT_ENFORCED_MENUS,
            VIEW_ENFORCED_ONLY_MENUS,
            get_all_effective_permissions,
        )
        role_labels = dict(User.Role.choices)
        menu_items = [
            {
                'key': key,
                'label': label,
                'path': path,
                'edit_enforced': key in EDIT_ENFORCED_MENUS,
                'view_enforced': key in VIEW_ENFORCED_ONLY_MENUS,
            }
            for key, label, path in MENU_ITEMS
        ]
        roles = [
            {'value': role, 'label': role_labels.get(role, role)}
            for role in CONFIGURABLE_ROLES
        ]
        return Response({
            'menu_items': menu_items,
            'roles': roles,
            'permissions': get_all_effective_permissions(),
        })

    def put(self, request):
        denied = self._admin_only(request)
        if denied:
            return denied
        from .menu_permissions import CONFIGURABLE_ROLES, MENU_KEYS, get_all_effective_permissions
        permissions = request.data.get('permissions')
        if not isinstance(permissions, dict):
            return Response({'error': 'ساختار تنظیمات دسترسی نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        for role in CONFIGURABLE_ROLES:
            role_permissions = permissions.get(role, {})
            if not isinstance(role_permissions, dict):
                continue
            for menu_key in MENU_KEYS:
                entry = role_permissions.get(menu_key, {})
                if isinstance(entry, bool):
                    view_enabled = entry
                    edit_enabled = entry
                elif isinstance(entry, dict):
                    view_enabled = bool(entry.get('view', False))
                    edit_enabled = bool(entry.get('edit', False)) and view_enabled
                else:
                    view_enabled = False
                    edit_enabled = False
                MenuPermission.objects.update_or_create(
                    role=role,
                    menu_key=menu_key,
                    defaults={'enabled': view_enabled, 'can_edit': edit_enabled},
                )
        return Response({'message': 'تنظیمات دسترسی ذخیره شد', 'permissions': get_all_effective_permissions()})


class MyMenuPermissionsView(APIView):
    """برگرداندن دسترسی منوهای کاربر جاری برای کنترل منوی frontend."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .menu_permissions import MENU_KEYS, get_effective_permissions
        if request.user.role == User.Role.ADMIN:
            return Response({key: {'view': True, 'edit': True} for key in MENU_KEYS})
        return Response(get_effective_permissions(request.user.role))


def _staff_credentials_payload(user):
    role_labels = dict(User.Role.choices)
    return {
        'id': user.id,
        'full_name': user.get_full_name() or user.username,
        'role': user.role,
        'role_label': role_labels.get(user.role, user.role),
        'username': user.username,
        'last_generated_password': user.last_generated_password or '',
        'last_login': user.last_login,
    }


class StaffCredentialsListView(APIView):
    """فهرست حساب‌های کارمندان و کارشناسان برای مدیر."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != User.Role.ADMIN:
            return Response({'error': 'فقط مدیر به اطلاعات ورود کارمندان دسترسی دارد'}, status=status.HTTP_403_FORBIDDEN)
        users = User.objects.filter(
            role__in=[User.Role.EMPLOYEE, User.Role.OFFICE, User.Role.EVALUATOR]
        ).order_by('first_name', 'last_name', 'id')
        return Response([_staff_credentials_payload(user) for user in users])


class StaffCredentialsDetailView(APIView):
    """تغییر نام کاربری یا تولید دوبارهٔ نام کاربری/رمز حساب‌های پرسنلی."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if request.user.role != User.Role.ADMIN:
            return Response({'error': 'فقط مدیر می‌تواند اطلاعات ورود کارمندان را تغییر دهد'}, status=status.HTTP_403_FORBIDDEN)
        try:
            user = User.objects.get(
                pk=pk,
                role__in=[User.Role.EMPLOYEE, User.Role.OFFICE, User.Role.EVALUATOR],
            )
        except User.DoesNotExist:
            return Response({'error': 'حساب کارمند یا کارشناس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        import secrets
        import string

        if request.data.get('generate_random'):
            alphabet = string.ascii_letters + string.digits
            while True:
                candidate = 'staff_' + ''.join(secrets.choice(alphabet) for _ in range(10))
                if not User.objects.filter(username=candidate).exclude(pk=user.pk).exists():
                    break
            password = 'St' + ''.join(secrets.choice(alphabet) for _ in range(10)) + '!'
            user.username = candidate
            user.set_password(password)
            user.last_generated_password = password
            user.save(update_fields=['username', 'password', 'last_generated_password'])
            return Response(_staff_credentials_payload(user))

        if 'username' not in request.data:
            return Response({'error': 'نام کاربری یا generate_random ارسال نشده است'}, status=status.HTTP_400_BAD_REQUEST)
        username = str(request.data.get('username') or '').strip()
        if not username:
            return Response({'error': 'نام کاربری نمی‌تواند خالی باشد'}, status=status.HTTP_400_BAD_REQUEST)
        if len(username) > 150 or not re.fullmatch(r'[A-Za-z0-9@.+_-]+', username):
            return Response({'error': 'نام کاربری فقط باید شامل حروف و اعداد انگلیسی و @ . + - _ باشد'}, status=status.HTTP_400_BAD_REQUEST)
        if User.objects.filter(username=username).exclude(pk=user.pk).exists():
            return Response({'error': 'این نام کاربری قبلاً استفاده شده است'}, status=status.HTTP_400_BAD_REQUEST)
        user.username = username
        user.save(update_fields=['username'])
        return Response(_staff_credentials_payload(user))
