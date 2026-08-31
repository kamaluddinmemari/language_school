"""
منبع واحد فهرست منوهای پنل ادمین برای «تنظیمات دسترسی».
هر بار منوی جدیدی به پنل اضافه شد، فقط کافیه اینجا (و لینک متناظرش در Dashboard.js) اضافه بشه.

هر منو برای هر نقش دو بُعد دسترسی داره:
  view (نمایش) — دیدن لینک منو و بازکردن صفحه‌ش
  edit (ویرایش) — انجام کارهای واقعی توش (ثبت/ویرایش/حذف)؛ فقط وقتی view فعاله معنی داره.
«view=دیدن، edit=خاموش» یعنی فقط می‌تونه ببینه، کاری نمی‌تونه انجام بده (فقط‌خواندنی).

نکته‌ی مهم برای توسعه‌ی بعدی: بُعد edit فعلاً فقط برای دو منوی «مدیریت کلاس‌ها» و «تعیین
سطح» واقعاً توسط بک‌اند چک می‌شه (چون این دو اپ از قبل هرکدوم یک ثابت متمرکز برای این کار
داشتن: MANAGE_ROLES و MANAGE_LEVEL_ROLES — که الان به‌جای مقدار ثابت، از همینجا خونده
می‌شن). برای بقیه‌ی ۱۶ منو، بُعد edit توی این صفحه قابل تنظیمه ولی هنوز هیچ endpoint ای
واقعاً بهش نگاه نمی‌کنه (یعنی فعلاً فقط view همون‌طور که قبلاً بود کنترل‌کننده‌ست) — چون
تبدیل بقیه‌ی اپ‌ها به این مدل، کار جدا و بزرگیه که باید تدریجی انجام بشه.
"""

MENU_ITEMS = [
    ('students', 'اطلاعات دانش‌آموزان', '/students'),
    ('teachers', 'مدیریت استادها', '/teachers'),
    ('group-classes', 'کلاس‌های گروهی/ورکشاپ', '/group-classes'),
    ('level-tests', 'تعیین سطح', '/level-tests'),
    ('stats', 'گزارش آمار', '/stats'),
    ('staff-messages', 'یادآور غیاب/مجوز', '/staff-messages'),
    ('library', 'کتابخانه', '/library'),
    ('new-leads', 'ورودی‌های جدید', '/new-leads'),
    ('followups', 'پیگیری/بدهکاران', '/followups'),
    ('dropout-students', 'دانشجویان ریزشی', '/dropout-students'),
    ('discounts', 'افراد دارای تخفیف', '/discounts'),
    ('class-management', 'مدیریت کلاس‌ها', '/class-management'),
    ('standard-levels', 'تعریف سطوح استاندارد (زیرمجموعه‌ی مدیریت کلاس‌ها)', '/class-management'),
    ('teacher-sessions', 'جلسات و ساب استادان', '/teacher-sessions'),
    ('payroll', 'حقوق و دستمزد', '/payroll'),
    ('leaves', 'مرخصی', '/leaves'),
    ('working-hours', 'ساعت کاری', '/working-hours'),
    ('feedback', 'نظرات و پیشنهادات', '/feedback'),
    ('reports', 'گزارش‌گیری و آمار', '/reports'),
]
MENU_KEYS = {key for key, _, _ in MENU_ITEMS}

# منوهایی که بک‌اندشون واقعاً به بُعد edit نگاه می‌کنه (فهرست باید هر بار که اپ جدیدی
# سیم‌کشی شد به‌روزرسانی بشه — فقط برای نمایش یک برچسب «فعال» در صفحه‌ی تنظیمات).
EDIT_ENFORCED_MENUS = {
    'class-management', 'standard-levels', 'discounts', 'teacher-sessions',
    'group-classes', 'level-tests', 'teachers', 'students',
    'library', 'feedback', 'staff-messages',
    'new-leads', 'followups', 'dropout-students',
}
# منوهایی که فقط بُعد view واقعاً چک می‌شه (نه edit) — برای نشونه‌ی ⚡ جدا از بالا لازمه
VIEW_ENFORCED_ONLY_MENUS = {'stats'}

CONFIGURABLE_ROLES = ['employee', 'office', 'evaluator']

_EVALUATOR_BLOCKED = {'teachers', 'stats', 'students', 'new-leads', 'followups', 'dropout-students'}
# «تعریف سطوح استاندارد» یه استثنای قدیمیه: حتی با اینکه کارشناس اداری همه‌جا دسترسی کامل
# داشت، این یکی رو هیچ‌وقت نمی‌تونست حتی ببینه (فقط مدیر/کارشناس آموزش) — این رفتار حفظ شد.
_OFFICE_VIEW_EXCEPTIONS = {'standard-levels'}

# پیش‌فرض‌های view — طوری انتخاب شدن که رفتار فعلیِ سیستم (قبل از وجود این صفحه) حفظ بشه.
_DEFAULT_VIEW = {
    'office': {key: (key not in _OFFICE_VIEW_EXCEPTIONS) for key, _, _ in MENU_ITEMS},
    'evaluator': {key: (key not in _EVALUATOR_BLOCKED) for key, _, _ in MENU_ITEMS},
    'employee': {key: False for key, _, _ in MENU_ITEMS},
}

# پیش‌فرض‌های edit — برای منوهای سیم‌کشی‌شده، دقیقاً همون چیزیه که ثابت‌های قدیمیِ کد
# (MANAGE_ROLES و MANAGE_LEVEL_ROLES) بودن، تا با فعال‌شدن این سیستم هیچ رفتاری برای
# هیچ‌کس عوض نشه. برای بقیه‌ی منوها، فعلاً همون مقدار view رو mirror می‌کنه (چون هنوز
# هیچ‌جا چک نمی‌شه، این مقدار صرفاً پیش‌فرض معقول برای روزی‌ست که آن منو هم سیم‌کشی بشه).
_DEFAULT_EDIT_OVERRIDES = {
    'class-management': {'office': True, 'evaluator': True, 'employee': False},   # = MANAGE_ROLES سابق
    'standard-levels': {'office': False, 'evaluator': True, 'employee': False},   # = MANAGE_LEVEL_ROLES سابق
    'discounts': {'office': True, 'evaluator': True, 'employee': False},          # = MANAGE_ROLES سابق (همون فایل)
    'teacher-sessions': {'office': True, 'evaluator': True, 'employee': False},   # = MANAGE_ROLES سابق (همون فایل)
    # قبلاً ساخت جلسه فقط برای (admin,office) بود و ویرایش/حذف فقط برای (admin,evaluator)؛
    # این دو تا یکی شدن (اجتماع هردو مجموعه) تا کسی نسبت به قبل چیزی از دست نده — یعنی حالا
    # اگه edit این منو برای یک نقش فعال باشه، هم ساخت هم ویرایش/حذف براش باز می‌شه.
    'group-classes': {'office': True, 'evaluator': True, 'employee': False},
    # قبلاً: ثبت داوطلب جدید فقط (admin,office)، ویرایش (admin,evaluator,office)، حذف و
    # تنظیم قیمت فقط (admin,evaluator) — اجتماع همه‌شون گرفته شد.
    'level-tests': {'office': True, 'evaluator': True, 'employee': False},
    # این دو رو کارشناس آموزش قبلاً اصلاً حتی نمی‌دید (رفتار حفظ شد، چون در _EVALUATOR_BLOCKED هست)
    'teachers': {'office': True, 'evaluator': False, 'employee': False},
    'students': {'office': True, 'evaluator': False, 'employee': False},
    'library': {'office': True, 'evaluator': True, 'employee': False},
    'feedback': {'office': True, 'evaluator': True, 'employee': False},
    'staff-messages': {'office': True, 'evaluator': False, 'employee': False},
    # این سه تا (اپ leads) قبلاً فقط (admin,office) بودن، کارشناس آموزش اصلاً توشون نبود
    'new-leads': {'office': True, 'evaluator': False, 'employee': False},
    'followups': {'office': True, 'evaluator': False, 'employee': False},
    'dropout-students': {'office': True, 'evaluator': False, 'employee': False},
}


def _default_edit(role, key):
    if key in _DEFAULT_EDIT_OVERRIDES:
        return _DEFAULT_EDIT_OVERRIDES[key][role]
    return _DEFAULT_VIEW[role][key]


DEFAULT_PERMISSIONS = {
    role: {
        key: {'view': _DEFAULT_VIEW[role][key], 'edit': _default_edit(role, key)}
        for key, _, _ in MENU_ITEMS
    }
    for role in CONFIGURABLE_ROLES
}


def get_effective_permissions(role):
    """دیکشنری menu_key -> {'view': bool, 'edit': bool} برای یک نقش؛ رکورد صریح دیتابیس در اولویته."""
    from .models import MenuPermission
    defaults = {key: dict(val) for key, val in DEFAULT_PERMISSIONS.get(role, {}).items()}
    overrides = MenuPermission.objects.filter(role=role).values_list('menu_key', 'enabled', 'can_edit')
    for menu_key, enabled, can_edit in overrides:
        if menu_key in MENU_KEYS:
            defaults[menu_key] = {'view': enabled, 'edit': can_edit}
    return defaults


def get_all_effective_permissions():
    """دیکشنری role -> {menu_key: {'view','edit'}} برای هر سه نقش قابل‌تنظیم."""
    return {role: get_effective_permissions(role) for role in CONFIGURABLE_ROLES}


def can_edit_menu(user, menu_key):
    """
    آیا این کاربر اجازه‌ی ثبت/ویرایش/حذف در این منو رو داره؟ مدیر همیشه بله.
    برای نقش‌های خارج از CONFIGURABLE_ROLES (مثلاً teacher/student) همیشه False —
    این تابع فقط برای صفحاتی هست که کارمند/کارشناس اداری/کارشناس آموزش ممکنه بهشون
    دسترسی نوشتن داشته باشن.
    """
    role = getattr(user, 'role', None)
    if role == 'admin':
        return True
    if role not in CONFIGURABLE_ROLES:
        return False
    perms = get_effective_permissions(role)
    entry = perms.get(menu_key)
    return bool(entry and entry.get('view') and entry.get('edit'))


def can_view_menu(user, menu_key):
    """آیا این کاربر اصلاً اجازه‌ی دیدن این منو رو داره؟ (برای استفاده‌ی احتمالی سمت بک‌اند)"""
    role = getattr(user, 'role', None)
    if role == 'admin':
        return True
    if role not in CONFIGURABLE_ROLES:
        return False
    perms = get_effective_permissions(role)
    entry = perms.get(menu_key)
    return bool(entry and entry.get('view'))
