# کاتالوگ دکمه‌های منوی صفحه‌ی خانه‌ی اپ موبایل — برای صفحه‌ی «تنظیمات دسترسی» در پنل ادمین
# (لیست تیک‌های قابل‌مشاهده/غیرقابل‌مشاهده) و برای اعتبارسنجی کلیدها.
# هر آیتم شامل تعریف تکراری متناظر در admin-panell (AccessSettings.js) و app (home.tsx) است؛
# در صورت افزودن/حذف دکمه در home.tsx، این سه‌جا باید هم‌زمان به‌روز شوند.

MOBILE_MENU_GROUPS = {
    'office': {
        'label': 'اپ اداری (کارمندان و کارشناسان)',
        'items': [
            ('group-classes', 'کلاس‌های گروهی/ورکشاپ'),
            ('office-payroll', 'فیش حقوقی شخصی'),
            ('OfficeQrAttendance', 'ثبت ورود و خروج با QR'),
            ('office-attendance', 'کارکرد ماهانه'),
            ('office-classes', 'مدیریت کلاس‌ها'),
            ('office-unregistered', 'ثبت فرد خارج از لیست کلاس'),
            ('office-debtors', 'بدهکاران'),
            ('office-special-classes', 'ثبت کلاس خصوصی و ورکشاپ'),
            ('contact-us', 'تماس با ما'),
        ],
    },
    'teacher': {
        'label': 'اپ استاد',
        'items': [
            ('group-classes', 'کلاس‌های گروهی/ورکشاپ'),
            ('level-tests', 'تعیین سطح'),
            ('teacher-notices', 'پیام‌های مدیریت'),
            ('teacher-term-classes', 'کلاس‌های ترمیک'),
            ('TeacherRosterAttendance', 'حضور و غیاب کلاس'),
            ('TeacherQrAttendance', 'حضور با QR'),
            ('TeacherGrading', 'ثبت نمرات کلاس'),
            ('entry-exit-requests', 'کسب مجوز ورود/خروج'),
            ('unregistered-student-form', 'زبان‌آموزان ثبت‌نام‌نکرده'),
            ('contact-us', 'تماس با ما'),
        ],
    },
    'student': {
        'label': 'اپ دانش‌آموز',
        'items': [
            ('group-classes', 'کلاس‌های گروهی/ورکشاپ'),
            ('level-test-request', 'تعیین سطح'),
            ('direct-enrollment', 'ثبت‌نام کلاس ترمیک'),
            ('my-term-classes', 'دوره‌های ترمیک من'),
            ('online-courses', 'کلاس‌های آنلاین (علمی)'),
            ('contact-us', 'تماس با ما'),
        ],
    },
}


def all_mobile_menu_keys():
    """کلید کامل هر دکمه به فرم group:item — برای اعتبارسنجی هنگام ذخیره."""
    keys = []
    for group, data in MOBILE_MENU_GROUPS.items():
        for item_key, _label in data['items']:
            keys.append(f'{group}:{item_key}')
    return keys
