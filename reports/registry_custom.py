"""
منابع دادهٔ گزارش‌ساز دلخواه — هر منبع یک queryset پایه و لیست فیلدهای مجاز (whitelist) دارد.
همه‌ی دسترسی به دیتابیس فقط از طریق این whitelist انجام می‌شود (بدون SQL خام)، برای امنیت.

field.db_field می‌تواند یک مسیر نقطه‌چین (با __ در سطح ORM) برای فیلد/فیلتر/گروه‌بندی در
سطح دیتابیس باشد، یا برای فیلدهای محاسباتی (property های پایتون، مثل net_pay) همان اسم
property. برای نمایش تخت (بدون group_by) هر دو نوع کار می‌کنند؛ برای group_by/aggregation
فقط فیلدهای واقعی دیتابیسی قابل استفاده‌اند (چون در سطح SQL اجرا می‌شوند).
"""
from dataclasses import dataclass, field as dc_field
from typing import List, Dict, Optional, Callable


@dataclass
class SourceField:
    key: str
    label: str
    db_field: str
    type: str = 'string'  # string | number | date | datetime | choice
    choices: Optional[Dict[str, str]] = None
    is_db_field: bool = True  # False یعنی property پایتونی است (فقط برای نمایش تخت قابل استفاده)


@dataclass
class DataSource:
    key: str
    label: str
    group: str
    base_qs: Callable
    fields: List[SourceField]
    date_field: Optional[str] = None  # مسیر ORM فیلد تاریخ برای فیلتر بازه

    @property
    def field_map(self):
        return {f.key: f for f in self.fields}


SOURCES: Dict[str, DataSource] = {}


def register_source(src: DataSource):
    SOURCES[src.key] = src
    return src


def _library_books_qs():
    from library.models import Book
    return Book.objects.all()


def _library_sales_qs():
    from library.models import BookSale
    return BookSale.objects.select_related('book', 'sold_by')


def _debtors_qs():
    from leads.models import Debtor
    return Debtor.objects.all()


def _students_qs():
    from accounts.models import User
    return User.objects.filter(role='student')


def _teachers_qs():
    from accounts.models import User
    return User.objects.filter(role__in=['teacher', 'evaluator'])


def _employees_qs():
    from accounts.models import User
    return User.objects.exclude(role='student')


def _tuition_enrollments_qs():
    from class_management.models import ClassSlotEnrollment
    return ClassSlotEnrollment.objects.filter(payment_verified=True).select_related(
        'student', 'class_slot', 'class_slot__term')


def _payroll_qs():
    from payroll.models import MonthlyPayroll
    return MonthlyPayroll.objects.select_related('user')


def _attendance_qs():
    from payroll.models import AttendanceLog
    return AttendanceLog.objects.select_related('user')


def _class_slots_qs():
    from class_management.models import ClassSlot
    return ClassSlot.objects.select_related('term')


def _private_classes_qs():
    from accounts.models import ClassRequest
    return ClassRequest.objects.filter(class_type='private').select_related('student', 'teacher')


def _group_sessions_qs():
    from group_classes.models import GroupSession
    return GroupSession.objects.all()



# ---------------------------------------------------------------------------
register_source(DataSource(
    key='library_books', label='کتاب‌های کتابخانه', group='کتابخانه',
    base_qs=_library_books_qs,
    date_field='created_at',
    fields=[
        SourceField('title', 'عنوان کتاب', 'title'),
        SourceField('category', 'دسته', 'category', 'choice', {
            'kids': 'کودکان', 'teen': 'نوجوانان', 'adult': 'بزرگسال', 'oxford': 'آکسفورد', 'other': 'سایر'}),
        SourceField('current_stock', 'موجودی فعلی', 'current_stock', 'number'),
        SourceField('initial_stock', 'موجودی اولیه', 'initial_stock', 'number'),
        SourceField('predicted_students', 'پیش‌بینی نیاز', 'predicted_students', 'number'),
        SourceField('unit_price', 'قیمت فروش', 'unit_price', 'number'),
        SourceField('purchase_price', 'قیمت خرید', 'purchase_price', 'number'),
        SourceField('created_at', 'تاریخ ثبت', 'created_at', 'datetime'),
    ],
))

register_source(DataSource(
    key='library_sales', label='فروش‌های کتابخانه', group='کتابخانه',
    base_qs=_library_sales_qs,
    date_field='sold_at',
    fields=[
        SourceField('book_title', 'عنوان کتاب', 'book__title'),
        SourceField('quantity', 'تعداد', 'quantity', 'number'),
        SourceField('unit_price_at_sale', 'قیمت واحد فروش', 'unit_price_at_sale', 'number'),
        SourceField('sold_by_first_name', 'نام فروشنده', 'sold_by__first_name'),
        SourceField('sold_at', 'تاریخ فروش', 'sold_at', 'datetime'),
    ],
))

register_source(DataSource(
    key='debtors', label='بدهکاران', group='مالی',
    base_qs=_debtors_qs,
    date_field='created_at',
    fields=[
        SourceField('first_name', 'نام', 'first_name'),
        SourceField('last_name', 'نام‌خانوادگی', 'last_name'),
        SourceField('phone', 'موبایل', 'phone'),
        SourceField('class_level', 'سطح کلاس', 'class_level'),
        SourceField('debt_amount', 'مبلغ بدهی', 'debt_amount', 'number'),
        SourceField('status', 'وضعیت', 'status', 'choice', {'pending': 'در حال پیگیری', 'settled': 'تسویه شد'}),
        SourceField('created_at', 'تاریخ ثبت', 'created_at', 'datetime'),
    ],
))

register_source(DataSource(
    key='students', label='دانش‌آموزان', group='دانش‌آموزان',
    base_qs=_students_qs,
    date_field='date_joined',
    fields=[
        SourceField('first_name', 'نام', 'first_name'),
        SourceField('last_name', 'نام‌خانوادگی', 'last_name'),
        SourceField('national_code', 'کد ملی', 'national_code'),
        SourceField('phone', 'موبایل', 'phone'),
        SourceField('gender', 'جنسیت', 'gender', 'choice', {'female': 'خانم', 'male': 'آقا'}),
        SourceField('language_level', 'سطح زبان', 'language_level'),
        SourceField('wallet_balance', 'موجودی کیف پول', 'wallet_balance', 'number'),
        SourceField('date_joined', 'تاریخ ثبت‌نام', 'date_joined', 'datetime'),
    ],
))

register_source(DataSource(
    key='teachers', label='اساتید', group='کارکنان',
    base_qs=_teachers_qs,
    date_field=None,
    fields=[
        SourceField('first_name', 'نام', 'first_name'),
        SourceField('last_name', 'نام‌خانوادگی', 'last_name'),
        SourceField('phone', 'موبایل', 'phone'),
        SourceField('teacher_level', 'سطح تدریس', 'teacher_level'),
        SourceField('role', 'نقش', 'role', 'choice', {'teacher': 'معلم', 'evaluator': 'مدیر آموزش'}),
        SourceField('average_rating', 'میانگین رضایت', 'average_rating', 'number', is_db_field=False),
    ],
))

register_source(DataSource(
    key='employees', label='کارمندان', group='کارکنان',
    base_qs=_employees_qs,
    date_field='date_joined',
    fields=[
        SourceField('first_name', 'نام', 'first_name'),
        SourceField('last_name', 'نام‌خانوادگی', 'last_name'),
        SourceField('phone', 'موبایل', 'phone'),
        SourceField('role', 'نقش', 'role', 'choice', {
            'admin': 'مدیر', 'teacher': 'معلم', 'evaluator': 'مدیر آموزش', 'office': 'اداری'}),
        SourceField('date_joined', 'تاریخ استخدام (ثبت سیستم)', 'date_joined', 'datetime'),
    ],
))

register_source(DataSource(
    key='tuition_enrollments', label='ثبت‌نام‌های شهریه‌ای (کلاس ترمیک)', group='مالی',
    base_qs=_tuition_enrollments_qs,
    date_field='created_at',
    fields=[
        SourceField('student_first_name', 'نام دانش‌آموز', 'student__first_name'),
        SourceField('student_last_name', 'نام‌خانوادگی دانش‌آموز', 'student__last_name'),
        SourceField('class_number', 'شماره کلاس', 'class_slot__number', 'number'),
        SourceField('term_year', 'سال ترم', 'class_slot__term__year', 'number'),
        SourceField('term_number', 'شماره ترم', 'class_slot__term__term_number', 'number'),
        SourceField('tuition_amount', 'مبلغ شهریه', 'tuition_amount', 'number'),
        SourceField('discount_percent', 'درصد تخفیف', 'discount_percent', 'number'),
        SourceField('payment_method', 'روش پرداخت', 'payment_method', 'choice', {
            'pos': 'پوز', 'cash': 'نقدی', 'gateway': 'درگاه', 'card_to_card': 'کارت‌به‌کارت', 'wallet': 'کیف پول'}),
        SourceField('created_at', 'تاریخ پرداخت', 'created_at', 'datetime'),
    ],
))

register_source(DataSource(
    key='payroll', label='حقوق و دستمزد ماهانه', group='حقوق و دستمزد',
    base_qs=_payroll_qs,
    date_field=None,
    fields=[
        SourceField('user_first_name', 'نام کارمند', 'user__first_name'),
        SourceField('user_last_name', 'نام‌خانوادگی کارمند', 'user__last_name'),
        SourceField('jalali_year', 'سال شمسی', 'jalali_year', 'number'),
        SourceField('jalali_month', 'ماه شمسی', 'jalali_month', 'number'),
        SourceField('worked_hours', 'ساعات کارکرد', 'worked_hours', 'number'),
        SourceField('bonus_amount', 'پاداش', 'bonus_amount', 'number'),
        SourceField('extra_payment', 'اضافه‌پرداخت', 'extra_payment', 'number'),
        SourceField('gross_pay', 'ناخالص', 'gross_pay', 'number', is_db_field=False),
        SourceField('net_pay', 'خالص پرداختی', 'net_pay', 'number', is_db_field=False),
    ],
))

register_source(DataSource(
    key='attendance', label='حضور/غیاب کارکنان', group='حقوق و دستمزد',
    base_qs=_attendance_qs,
    date_field='date',
    fields=[
        SourceField('user_first_name', 'نام کارمند', 'user__first_name'),
        SourceField('user_last_name', 'نام‌خانوادگی کارمند', 'user__last_name'),
        SourceField('date', 'تاریخ', 'date', 'date'),
        SourceField('worked_hours', 'ساعت کارکرد', 'worked_hours', 'number', is_db_field=False),
    ],
))

register_source(DataSource(
    key='class_slots', label='کلاس‌های حضوری/آنلاین', group='کلاس‌ها',
    base_qs=_class_slots_qs,
    date_field=None,
    fields=[
        SourceField('number', 'شماره کلاس', 'number', 'number'),
        SourceField('day_type', 'نوع روز', 'day_type', 'choice', {
            'even': 'زوج', 'odd': 'فرد', 'thursday_morning': 'پنجشنبه صبح',
            'thursday_evening': 'پنجشنبه عصر', 'friday': 'جمعه', 'online': 'آنلاین', 'hybrid': 'ترکیبی'}),
        SourceField('time_slot', 'ساعت', 'time_slot'),
        SourceField('is_online', 'آنلاین؟', 'is_online', 'choice', {'True': 'آنلاین', 'False': 'حضوری'}),
        SourceField('gender', 'جنسیت', 'gender', 'choice', {'girls': 'دخترانه', 'boys': 'پسرانه', 'mixed': 'مختلط'}),
        SourceField('capacity', 'ظرفیت', 'capacity', 'number'),
        SourceField('current_count', 'تعداد تخصیص', 'current_count', 'number'),
        SourceField('teacher_name', 'استاد', 'teacher_name'),
        SourceField('term_year', 'سال ترم', 'term__year', 'number'),
    ],
))

register_source(DataSource(
    key='private_classes', label='کلاس‌های خصوصی', group='کلاس‌ها',
    base_qs=_private_classes_qs,
    date_field='created_at',
    fields=[
        SourceField('student_first_name', 'نام دانش‌آموز', 'student__first_name'),
        SourceField('teacher_first_name', 'نام استاد', 'teacher__first_name'),
        SourceField('language_level', 'سطح', 'language_level'),
        SourceField('is_online', 'آنلاین؟', 'is_online', 'choice', {'True': 'آنلاین', 'False': 'حضوری'}),
        SourceField('session_count', 'تعداد جلسه', 'session_count', 'number'),
        SourceField('total_price', 'مبلغ کل', 'total_price', 'number'),
        SourceField('status', 'وضعیت', 'status', 'choice', {
            'pending': 'در انتظار', 'referred': 'ارجاع‌شده', 'confirmed': 'تایید نهایی',
            'completed': 'مختومه', 'rejected': 'رد شده', 'cancelled': 'کنسل شده'}),
        SourceField('created_at', 'تاریخ ثبت', 'created_at', 'datetime'),
    ],
))

register_source(DataSource(
    key='group_sessions', label='ورکشاپ‌ها و کلاس‌های خصوصی چندنفره', group='کلاس‌های گروهی',
    base_qs=_group_sessions_qs,
    date_field='created_at',
    fields=[
        SourceField('title', 'عنوان', 'title'),
        SourceField('session_type', 'نوع', 'session_type', 'choice', {
            'workshop': 'ورکشاپ', 'private_group': 'خصوصی گروهی'}),
        SourceField('language_level', 'سطح', 'language_level'),
        SourceField('is_online', 'آنلاین؟', 'is_online', 'choice', {'True': 'آنلاین', 'False': 'حضوری'}),
        SourceField('capacity', 'ظرفیت', 'capacity', 'number'),
        SourceField('price_per_person', 'قیمت هرنفر', 'price_per_person', 'number'),
        SourceField('status', 'وضعیت', 'status', 'choice', {
            'open': 'باز', 'assigning': 'ارجاع به استاد', 'confirmed': 'تایید نهایی',
            'completed': 'مختومه', 'rejected': 'رد شده', 'cancelled': 'کنسل شده'}),
        SourceField('created_at', 'تاریخ ثبت', 'created_at', 'datetime'),
    ],
))


def list_sources():
    return [
        {
            'key': s.key, 'label': s.label, 'group': s.group,
            'supports_date_filter': bool(s.date_field),
            'fields': [
                {'key': f.key, 'label': f.label, 'type': f.type, 'choices': f.choices, 'groupable': f.is_db_field}
                for f in s.fields
            ],
        }
        for s in SOURCES.values()
    ]
