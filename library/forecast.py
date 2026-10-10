"""پیش‌بینی خودکار تعداد زبان‌آموز ترم بعد برای هر کتاب، از روی ثبت‌نام‌های ترم ملاک.

- ترم ملاک: پیش‌فرض آخرین ترم؛ با پارامتر ?forecast_term=<id> قابل تغییر است.
- فقط زبان‌آموزان ثبت‌نام‌شده‌ی قطعی (پرداخت‌تأییدشده و نه «منتظر ثبت‌نام» خاکستری) در کلاس‌های
  زوج، فرد و یک‌روز در هفته شمرده می‌شوند. هر زبان‌آموز برای هر کتاب فقط یک‌بار.
- سطح‌های هر کتاب: اگر در فیلد forecast_levels کتاب چیزی نوشته شده همان؛ وگرنه جدول پیش‌فرض
  زیر که از روی عنوان کتاب تشخیص داده می‌شود.
"""
import re

ONE_AND_TWO_DAY_TYPES = (
    'even', 'odd',
    'thursday_morning', 'thursday_evening',
    'friday', 'friday_morning', 'friday_evening',
)

SUPERMIND_LEVELS = {1: 'e5', 2: 's5', 3: 'g5', 4: 'u5', 5: 'm5', 6: 'h5'}
EVOLVE_LEVELS = {1: '101', 2: '106', 3: '206', 4: '306', 5: '406', 6: '506'}
PROJECT_LEVELS = {1: 'teen1', 2: 'teen3', 3: 'teen6', 4: 'teen9', 5: 'teen12'}

# داستان‌ها: (الگوی عنوان، سطح). ترتیب مهم است — الگوهای اختصاصی‌تر اول.
STORY_RULES = [
    (r'little\s*tr\w*\s*(in)?\s*cali', 'teen1'),
    (r'little\s*tr\w*\s*(in)?\s*(dub|dob)', 'teen5'),
    (r'little\s*tr\w*\s*(in)?\s*(ams|qme|mst)', 'teen9'),
    (r'little\s*tr\w*\s*(in)?\s*(york|yor)', 'teen14'),
    (r'cali', 'teen1'),
    (r'^gone', 'teen1'),
    (r'quick\s*change', 'teen2'),
    (r'summer\s*sound', 'teen3'),
    (r'(vinn|vienn|vini)', 'teen4'),
    (r'(dublin|doblin)', 'teen5'),
    (r'(others?\s*see\s*us|other\s*see\s*us)', 'teen6'),
    (r'ask\s*alice', 'teen7'),
    (r'(kil+er|kilker)\s*bees', 'teen8'),
    (r'(amsterdam|qmester|msterdam)', 'teen9'),
    (r'part\w*\s*(and|abd|&)\s*pran', 'teen10'),
    (r'london', 'teen11'),
    (r'running\s*wild', 'teen12'),
    (r'(tales?|talse)\s*of\s*terror', 'teen13'),
    (r'(york|yorkshire)', 'teen14'),
]


def normalize_level(value):
    return re.sub(r'[\s\-_]+', '', str(value or '').strip().lower())


def default_levels_for_title(title):
    t = str(title or '').strip().lower()
    if not t:
        return []
    compact = re.sub(r'\s+', ' ', t)
    num = re.search(r'(\d)', compact)
    n = int(num.group(1)) if num else None
    if re.search(r'ev[oa][lk]ve', compact):
        if 'جلدی' in compact:
            return []
        return [EVOLVE_LEVELS[n]] if n in EVOLVE_LEVELS else []
    if 'oxford' in compact:
        if re.search(r'elem', compact):
            return ['101']
        if re.search(r'inter', compact):
            return ['306']
        if re.search(r'adv', compact):
            return ['406']
        return []
    if re.search(r'little\s*tr', compact) or any(re.search(p, compact) for p, _ in STORY_RULES[4:]):
        for pattern, level in STORY_RULES:
            if re.search(pattern, compact):
                return [level]
    if re.search(r'bogs|bugs|mr\.?\s*b', compact):
        return ['e1']
    if re.search(r'super\s*-?\s*mind', compact):
        if 'starter' in compact:
            return ['e1']
        return [SUPERMIND_LEVELS[n]] if n in SUPERMIND_LEVELS else []
    if re.search(r'project', compact):
        return [PROJECT_LEVELS[n]] if n in PROJECT_LEVELS else []
    return []


def parse_levels(text):
    return [normalize_level(x) for x in re.split(r'[,،;\n]+', str(text or '')) if normalize_level(x)]


def levels_for_book(book):
    stored = parse_levels(getattr(book, 'forecast_levels', ''))
    return stored if stored else [normalize_level(x) for x in default_levels_for_title(book.title)]


def ordered_terms():
    from class_management.models import Term
    return sorted(Term.objects.all(), key=lambda t: (t.year, t.term_number))


def resolve_term(term_id=None):
    terms = ordered_terms()
    if not terms:
        return None, terms
    if term_id not in (None, ''):
        try:
            wanted = int(term_id)
            for t in terms:
                if t.id == wanted:
                    return t, terms
        except (TypeError, ValueError):
            pass
    return terms[-1], terms


def current_mode():
    from .models import LibrarySetting
    return LibrarySetting.get().forecast_mode


def build_context(term_id=None, mode=None):
    """شمارش یکتای زبان‌آموزان هر سطح در ترم ملاک: {سطح_نرمال: {student_id,...}}
    mode='registered': همه‌ی ثبت‌نام‌شده‌ها (روش قبلی)؛ mode='deposit': فقط افراد بیعانه‌داده."""
    from class_management.models import ClassSlotEnrollment
    from .models import BookDeposit
    term, terms = resolve_term(term_id)
    mode = mode or current_mode()
    index = {}
    paid_ids = None
    if term and mode == 'deposit':
        paid_ids = set(BookDeposit.objects.filter(term_id=term.id, paid=True).values_list('student_id', flat=True))
    if term:
        rows = ClassSlotEnrollment.objects.filter(
            class_slot__term_id=term.id,
            class_slot__day_type__in=ONE_AND_TWO_DAY_TYPES,
            payment_verified=True,
        ).exclude(is_carryover=True, carryover_confirmed=False).values_list('student_id', 'class_slot__assigned_level')
        for student_id, level in rows:
            if paid_ids is not None and student_id not in paid_ids:
                continue
            key = normalize_level(level)
            if key:
                index.setdefault(key, set()).add(student_id)
    return {'term': term, 'terms': terms, 'index': index, 'mode': mode}


def forecast_for_book(book, ctx):
    """(تعداد خودکار یا None، فهرست سطح‌های مؤثر)"""
    levels = levels_for_book(book)
    if not levels or not ctx.get('term'):
        return None, levels
    students = set()
    for level in levels:
        students |= ctx['index'].get(level, set())
    return len(students), levels
