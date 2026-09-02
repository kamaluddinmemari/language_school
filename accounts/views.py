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
from .models import User, OTPCode, PriceSetting, AppearanceSettings, MenuPermission
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
    return str(value or '').strip().lower().replace('ي', 'ی').replace('ك', 'ک').replace(' ', '').replace('_', '')


def _parse_excel_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value or '').strip()
    if not raw:
        return ''
    for fmt in ('%Y-%m-%d', '%Y/%m/%d'):
        try: return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError: pass
    return raw


def _read_student_excel(uploaded_file):
    if openpyxl is None:
        raise RuntimeError('کتابخانه خواندن Excel روی سرور نصب نیست؛ openpyxl را نصب کنید')
    workbook = openpyxl.load_workbook(uploaded_file, read_only=True, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [_normalize_excel_header(x) for x in rows[0]]
    aliases = {
        'first_name': ['نام', 'firstname', 'first_name', 'نامکوچک'],
        'last_name': ['نامخانوادگی', 'نامفامیل', 'lastname', 'last_name'],
        'father_name': ['نامپدر', 'fathername', 'father_name'],
        'national_code': ['کدملی', 'کدملی', 'nationalcode', 'national_code'],
        'phone': ['موبایل', 'شمارهتلفن', 'تلفن', 'phone', 'mobile'],
        'phone2': ['موبایلدوم', 'تلفندوم', 'phone2', 'mobile2'],
        'birth_date': ['تاریختولد', 'birthdate', 'birth_date'],
        'gender': ['جنسیت', 'gender'],
        'language_level': ['سطح', 'سطحزبان', 'languagelevel', 'language_level', 'level'],
    }
    positions = {key: next((headers.index(a) for a in values if a in headers), None) for key, values in aliases.items()}
    output = []
    for row_number, values in enumerate(rows[1:], start=2):
        raw = {key: (values[pos] if pos is not None and pos < len(values) else '') for key, pos in positions.items()}
        item = {key: (_parse_excel_date(value) if key == 'birth_date' else str(value or '').strip()) for key, value in raw.items()}
        item['_row_number'] = row_number
        output.append(item)
    return output


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
                if not uploaded: return Response({'error': 'فایل Excel را انتخاب کنید'}, status=400)
                items = _student_import_preview(_read_student_excel(uploaded))
                return Response({'rows': items, 'total': len(items), 'new_count': sum(x['status'] == 'new' for x in items), 'duplicate_count': sum(x['status'] == 'duplicate' for x in items), 'error_count': sum(x['status'] == 'error' for x in items)})
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