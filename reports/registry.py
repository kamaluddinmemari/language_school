"""
رجیستری مرکزی گزارش‌های سیستمی — هر گزارش یک «کلید» یکتا، اسم فارسی، گروه، لیست ستون‌ها،
و یک تابع fetch(start, end, **kwargs) دارد که ردیف‌ها را به‌صورت لیستی از دیکشنری برمی‌گرداند.
start/end تاریخ میلادی (datetime.date) هستند یا None (یعنی بدون محدودیت آن سمت بازه).

افزودن گزارش جدید = اضافه‌کردن یک تابع fetch_xxx + یک ورودی در REGISTRY. هیچ migration ای
لازم نیست چون این اپ هیچ مدلی ندارد و فقط از روی داده‌ی اپ‌های دیگر می‌خواند.
"""
from dataclasses import dataclass, field
from typing import Callable, List, Dict, Optional, Tuple
from django.db.models import Q
import jdatetime


@dataclass
class Column:
    key: str
    header: str


@dataclass
class ReportSpec:
    key: str
    name: str
    group: str
    columns: List[Column]
    fetch: Callable
    date_label: str = 'بازه‌ی تاریخ (شمسی)'
    supports_term: bool = False
    totals_row_label: str = 'جمع کل'


REGISTRY: Dict[str, ReportSpec] = {}


def register(spec: ReportSpec):
    REGISTRY[spec.key] = spec
    return spec


# ---------------------------------------------------------------------------
# ۱. گزارش کتابخانه (موجودی + فروش/هزینه/درآمد در بازه)
# ---------------------------------------------------------------------------
def fetch_library(start, end, **kwargs):
    from library.models import Book
    rows, totals = [], {'sold_qty_period': 0, 'revenue_period': 0, 'cost_period': 0, 'profit_period': 0}
    for b in Book.objects.all().order_by('category', 'title'):
        sales_qs = b.sales.all()
        if start:
            sales_qs = sales_qs.filter(sold_at__date__gte=start)
        if end:
            sales_qs = sales_qs.filter(sold_at__date__lte=end)
        qty = sum(s.quantity for s in sales_qs)
        revenue = sum(s.total_price for s in sales_qs)
        cost = b.purchase_price * qty
        profit = revenue - cost
        rows.append({
            'title': b.title, 'category': b.get_category_display(),
            'current_stock': b.current_stock, 'unit_price': b.unit_price,
            'sold_qty_period': qty, 'revenue_period': revenue,
            'cost_period': cost, 'profit_period': profit,
        })
        totals['sold_qty_period'] += qty
        totals['revenue_period'] += revenue
        totals['cost_period'] += cost
        totals['profit_period'] += profit
    return rows, totals


register(ReportSpec(
    key='library', name='گزارش کتابخانه (موجودی/هزینه/درآمد)', group='کتابخانه',
    columns=[
        Column('title', 'عنوان کتاب'), Column('category', 'دسته'),
        Column('current_stock', 'موجودی فعلی'), Column('unit_price', 'قیمت فروش (تومان)'),
        Column('sold_qty_period', 'فروش در بازه (جلد)'), Column('revenue_period', 'درآمد بازه (تومان)'),
        Column('cost_period', 'هزینه‌ی خرید بازه (تومان)'), Column('profit_period', 'سود بازه (تومان)'),
    ],
    fetch=fetch_library, date_label='بازه‌ی تاریخ فروش (شمسی)',
))


# ---------------------------------------------------------------------------
# ۲. گزارش پیگیری/بدهکاران
# ---------------------------------------------------------------------------
def fetch_debtors(start, end, **kwargs):
    from leads.models import Debtor
    qs = Debtor.objects.all().order_by('-created_at')
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    rows, total_debt = [], 0
    for d in qs:
        rows.append({
            'full_name': f"{d.first_name} {d.last_name}", 'phone': d.phone,
            'class_level': d.class_level or '-', 'debt_amount': d.debt_amount,
            'status': d.get_status_display(), 'followup_count': d.followup_count,
            'created_at_jalali': d.created_at_jalali,
        })
        total_debt += d.debt_amount
    return rows, {'debt_amount': total_debt}


register(ReportSpec(
    key='debtors', name='گزارش پیگیری/بدهکاران', group='مالی',
    columns=[
        Column('full_name', 'نام و نام‌خانوادگی'), Column('phone', 'موبایل'),
        Column('class_level', 'سطح کلاس'), Column('debt_amount', 'مبلغ بدهی (تومان)'),
        Column('status', 'وضعیت'), Column('followup_count', 'تعداد پیگیری'),
        Column('created_at_jalali', 'تاریخ ثبت'),
    ],
    fetch=fetch_debtors,
))


# ---------------------------------------------------------------------------
# ۳. گزارش دانش‌آموزان
# ---------------------------------------------------------------------------
def fetch_students(start, end, **kwargs):
    from accounts.models import User
    qs = User.objects.filter(role='student').order_by('-date_joined')
    if start:
        qs = qs.filter(date_joined__date__gte=start)
    if end:
        qs = qs.filter(date_joined__date__lte=end)
    rows = []
    for u in qs:
        rows.append({
            'full_name': u.get_full_name(), 'national_code': u.national_code or '-',
            'phone': u.phone, 'gender': u.get_gender_display() if u.gender else '-',
            'language_level': u.language_level or '-', 'wallet_balance': u.wallet_balance,
        })
    return rows, None


register(ReportSpec(
    key='students', name='گزارش دانش‌آموزان', group='دانش‌آموزان',
    columns=[
        Column('full_name', 'نام و نام‌خانوادگی'), Column('national_code', 'کد ملی'),
        Column('phone', 'موبایل'), Column('gender', 'جنسیت'),
        Column('language_level', 'سطح زبان'), Column('wallet_balance', 'موجودی کیف پول (تومان)'),
    ],
    fetch=fetch_students, date_label='بازه‌ی تاریخ ثبت‌نام (شمسی)',
))


# ---------------------------------------------------------------------------
# ۴. گزارش درآمد شهریه‌ای (کلاس‌های ترمیک) — با امکان تفکیک ترمی
# ---------------------------------------------------------------------------
def fetch_tuition_income(start, end, term_id=None, **kwargs):
    from class_management.models import ClassSlotEnrollment
    qs = ClassSlotEnrollment.objects.filter(payment_verified=True).select_related(
        'class_slot', 'class_slot__term', 'student'
    ).order_by('-created_at')
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    if term_id:
        qs = qs.filter(class_slot__term_id=term_id)
    rows, total = [], 0
    for e in qs:
        rows.append({
            'student_name': e.student.get_full_name(),
            'class_number': e.class_slot.number,
            'term': e.class_slot.term.title if e.class_slot.term else '-',
            'is_online': 'آنلاین' if e.class_slot.is_online else 'حضوری',
            'tuition_amount': e.tuition_amount, 'discount_percent': e.discount_percent,
            'payment_method': e.get_payment_method_display(),
            'created_at_jalali': e.created_at_jalali,
        })
        total += e.tuition_amount
    return rows, {'tuition_amount': total}


register(ReportSpec(
    key='tuition_income', name='گزارش درآمد شهریه‌ای (کلاس‌های ترمیک)', group='مالی',
    columns=[
        Column('student_name', 'دانش‌آموز'), Column('class_number', 'شماره کلاس'),
        Column('term', 'ترم'), Column('is_online', 'نوع'),
        Column('tuition_amount', 'مبلغ شهریه (تومان)'), Column('discount_percent', 'تخفیف (%)'),
        Column('payment_method', 'روش پرداخت'), Column('created_at_jalali', 'تاریخ پرداخت'),
    ],
    fetch=fetch_tuition_income, supports_term=True, date_label='بازه‌ی تاریخ پرداخت (شمسی)',
))


# ---------------------------------------------------------------------------
# ۵. گزارش حقوق و دستمزد
# ---------------------------------------------------------------------------
def fetch_payroll(start, end, **kwargs):
    from payroll.models import MonthlyPayroll
    qs = MonthlyPayroll.objects.select_related('user').order_by('-jalali_year', '-jalali_month')
    if start:
        sj = jdatetime.date.fromgregorian(date=start)
        qs = qs.filter(Q(jalali_year__gt=sj.year) | Q(jalali_year=sj.year, jalali_month__gte=sj.month))
    if end:
        ej = jdatetime.date.fromgregorian(date=end)
        qs = qs.filter(Q(jalali_year__lt=ej.year) | Q(jalali_year=ej.year, jalali_month__lte=ej.month))
    rows, total_net = [], 0
    for p in qs:
        rows.append({
            'employee_name': p.user.get_full_name(), 'period': p.jalali_label,
            'worked_hours': str(p.worked_hours), 'gross_pay': p.gross_pay,
            'total_deductions': p.total_deductions, 'net_pay': p.net_pay,
        })
        total_net += p.net_pay
    return rows, {'net_pay': total_net}


register(ReportSpec(
    key='payroll', name='گزارش حقوق و دستمزد', group='حقوق و دستمزد',
    columns=[
        Column('employee_name', 'کارمند'), Column('period', 'دوره'),
        Column('worked_hours', 'ساعات کارکرد'), Column('gross_pay', 'ناخالص (تومان)'),
        Column('total_deductions', 'کسورات (تومان)'), Column('net_pay', 'خالص پرداختی (تومان)'),
    ],
    fetch=fetch_payroll, date_label='بازه‌ی ماه/سال شمسی',
))


# ---------------------------------------------------------------------------
# ۶. گزارش حضور/غیاب کارکنان
# ---------------------------------------------------------------------------
def fetch_attendance(start, end, **kwargs):
    from payroll.models import AttendanceLog
    qs = AttendanceLog.objects.select_related('user').order_by('-date')
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    rows = []
    for a in qs:
        rows.append({
            'employee_name': a.user.get_full_name(), 'date_jalali': a.date_jalali,
            'check_in': a.check_in_time_jalali or '-', 'check_out': a.check_out_time_jalali or '-',
            'worked_hours': a.worked_hours,
        })
    return rows, None


register(ReportSpec(
    key='attendance', name='گزارش حضور/غیاب کارکنان', group='حقوق و دستمزد',
    columns=[
        Column('employee_name', 'کارمند'), Column('date_jalali', 'تاریخ'),
        Column('check_in', 'ورود'), Column('check_out', 'خروج'), Column('worked_hours', 'ساعت کارکرد'),
    ],
    fetch=fetch_attendance,
))


# ---------------------------------------------------------------------------
# ۷. گزارش کلاس‌های حضوری/آنلاین (به‌تفکیک روز زوج/فرد/یک‌روزه و ساعت)
# ---------------------------------------------------------------------------
def fetch_physical_online_classes(start, end, term_id=None, **kwargs):
    from class_management.models import ClassSlot
    qs = ClassSlot.objects.select_related('term').order_by('day_type', 'time_slot', 'number')
    if term_id:
        qs = qs.filter(term_id=term_id)
    rows = []
    for c in qs:
        enrollments = c.enrollments.filter(payment_verified=True)
        if start:
            enrollments = enrollments.filter(created_at__date__gte=start)
        if end:
            enrollments = enrollments.filter(created_at__date__lte=end)
        rows.append({
            'class_number': c.number, 'day_type': c.day_type_display, 'time_slot': c.time_slot or '-',
            'mode': 'آنلاین' if c.is_online else 'حضوری', 'gender': c.get_gender_display(),
            'term': c.term.title if c.term else '-', 'teacher_name': c.teacher_name or '-',
            'capacity': c.capacity, 'enrolled_in_period': enrollments.count(),
            'real_enrolled_total': c.real_enrolled_count,
        })
    return rows, None


register(ReportSpec(
    key='physical_online_classes', name='گزارش کلاس‌های حضوری/آنلاین (روز و ساعت)', group='کلاس‌ها',
    columns=[
        Column('class_number', 'شماره کلاس'), Column('day_type', 'نوع روز'),
        Column('time_slot', 'ساعت'), Column('mode', 'حضوری/آنلاین'), Column('gender', 'جنسیت'),
        Column('term', 'ترم'), Column('teacher_name', 'استاد'), Column('capacity', 'ظرفیت'),
        Column('enrolled_in_period', 'ثبت‌نام در بازه'), Column('real_enrolled_total', 'ثبت‌نام کل فعلی'),
    ],
    fetch=fetch_physical_online_classes, supports_term=True,
    date_label='بازه‌ی تاریخ ثبت‌نام (شمسی)',
))


# ---------------------------------------------------------------------------
# ۸. گزارش کلاس‌های خصوصی (تک‌نفره)
# ---------------------------------------------------------------------------
def fetch_private_classes(start, end, **kwargs):
    from accounts.models import ClassRequest
    qs = ClassRequest.objects.filter(class_type='private').select_related('student', 'teacher').order_by('-created_at')
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    rows, total_amount = [], 0
    for r in qs:
        rows.append({
            'student_name': r.student.get_full_name(),
            'teacher_name': r.teacher.get_full_name() if r.teacher else '-',
            'language_level': r.language_level, 'mode': 'آنلاین' if r.is_online else 'حضوری',
            'session_count': r.session_count, 'total_price': r.total_price,
            'status': r.get_status_display(), 'created_at_jalali': r.created_at_jalali,
        })
        total_amount += r.total_price
    return rows, {'total_price': total_amount}


register(ReportSpec(
    key='private_classes', name='گزارش کلاس‌های خصوصی', group='کلاس‌ها',
    columns=[
        Column('student_name', 'دانش‌آموز'), Column('teacher_name', 'استاد'),
        Column('language_level', 'سطح'), Column('mode', 'نوع'), Column('session_count', 'تعداد جلسه'),
        Column('total_price', 'مبلغ کل (تومان)'), Column('status', 'وضعیت'),
        Column('created_at_jalali', 'تاریخ ثبت'),
    ],
    fetch=fetch_private_classes,
))


# ---------------------------------------------------------------------------
# ۹ و ۱۰. گزارش ورکشاپ‌ها و کلاس‌های خصوصی چندنفره (هر دو از group_classes)
# ---------------------------------------------------------------------------
def _fetch_group_sessions(session_type, start, end, **kwargs):
    from group_classes.models import GroupSession
    qs = GroupSession.objects.filter(session_type=session_type).order_by('-created_at')
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    rows, total_revenue = [], 0
    for g in qs:
        price_person = g.get_price_per_person() if hasattr(g, 'get_price_per_person') else (g.price_per_person or 0)
        revenue = (price_person or 0) * g.participant_count
        rows.append({
            'title': g.title or f"جلسه {g.id}", 'language_level': g.language_level,
            'mode': 'آنلاین' if g.is_online else 'حضوری', 'participant_count': g.participant_count,
            'capacity': g.capacity, 'price_per_person': price_person or 0,
            'status': g.get_status_display(), 'created_at_jalali': g.created_at_jalali,
        })
        total_revenue += revenue
    return rows, {'estimated_revenue': total_revenue}


def fetch_workshops(start, end, **kwargs):
    return _fetch_group_sessions('workshop', start, end, **kwargs)


def fetch_private_group_classes(start, end, **kwargs):
    return _fetch_group_sessions('private_group', start, end, **kwargs)


register(ReportSpec(
    key='workshops', name='گزارش ورکشاپ‌ها', group='کلاس‌های گروهی',
    columns=[
        Column('title', 'عنوان'), Column('language_level', 'سطح'), Column('mode', 'نوع'),
        Column('participant_count', 'تعداد شرکت‌کننده'), Column('capacity', 'ظرفیت'),
        Column('price_per_person', 'قیمت هرنفر (تومان)'), Column('status', 'وضعیت'),
        Column('created_at_jalali', 'تاریخ ثبت'),
    ],
    fetch=fetch_workshops,
))

register(ReportSpec(
    key='private_group_classes', name='گزارش کلاس‌های خصوصی چندنفره', group='کلاس‌های گروهی',
    columns=[
        Column('title', 'عنوان'), Column('language_level', 'سطح'), Column('mode', 'نوع'),
        Column('participant_count', 'تعداد شرکت‌کننده'), Column('capacity', 'ظرفیت'),
        Column('price_per_person', 'قیمت هرنفر (تومان)'), Column('status', 'وضعیت'),
        Column('created_at_jalali', 'تاریخ ثبت'),
    ],
    fetch=fetch_private_group_classes,
))


# ---------------------------------------------------------------------------
# ۱۱. گزارش اساتید
# ---------------------------------------------------------------------------
def fetch_teachers(start, end, **kwargs):
    from accounts.models import User
    qs = User.objects.filter(role__in=User.TEACHER_LIKE_ROLES).order_by('first_name')
    rows = []
    for t in qs:
        rows.append({
            'full_name': t.get_full_name(), 'phone': t.phone,
            'teacher_level': t.teacher_level or '-', 'role': t.get_role_display(),
            'average_rating': t.average_rating,
        })
    return rows, None


register(ReportSpec(
    key='teachers', name='گزارش اساتید', group='کارکنان',
    columns=[
        Column('full_name', 'نام و نام‌خانوادگی'), Column('phone', 'موبایل'),
        Column('teacher_level', 'سطح تدریس'), Column('role', 'نقش'), Column('average_rating', 'میانگین رضایت'),
    ],
    fetch=fetch_teachers, date_label=None,
))


# ---------------------------------------------------------------------------
# ۱۲. گزارش کارمندان
# ---------------------------------------------------------------------------
def fetch_employees(start, end, **kwargs):
    from accounts.models import User
    qs = User.objects.exclude(role='student').order_by('first_name')
    rows = []
    for e in qs:
        profile = getattr(e, 'employee_profile', None)
        rows.append({
            'full_name': e.get_full_name(), 'role': e.get_role_display(), 'phone': e.phone,
            'hire_date_jalali': profile.hire_date_jalali if profile else '-',
            'education_field': profile.education_field if profile else '-',
        })
    return rows, None


register(ReportSpec(
    key='employees', name='گزارش کارمندان', group='کارکنان',
    columns=[
        Column('full_name', 'نام و نام‌خانوادگی'), Column('role', 'نقش'), Column('phone', 'موبایل'),
        Column('hire_date_jalali', 'تاریخ استخدام'), Column('education_field', 'رشته تحصیلی'),
    ],
    fetch=fetch_employees, date_label=None,
))


def list_registry():
    return [
        {
            'key': s.key, 'name': s.name, 'group': s.group,
            'date_label': s.date_label, 'supports_term': s.supports_term,
            'columns': [{'key': c.key, 'header': c.header} for c in s.columns],
        }
        for s in REGISTRY.values()
    ]
