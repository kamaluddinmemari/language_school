"""
منطق خالص (بدون وابستگی به جنگو/دیتابیس) امتیازدهی ترمی به استادها.

ورودی: «واقعیت‌های» یک استاد در یک ترم (TermFacts) + تنظیمات (ScoringConfig)
خروجی: امتیاز ۰ تا ۱۰۰ همان ترم، با جزئیات هر معیار (برای نمایش در پنل).

ساختار امتیاز (مجموع وزن‌های مثبت = ۱۰۰، غیبت از آن کم می‌شود):
  ۱) تنوع برنامه ترمیک (زوج + فرد)        پیش‌فرض ۲۵
  ۲) تعداد دانش‌آموزان ترم                 پیش‌فرض ۲۵
  ۳) کلاس‌های یک‌روز در هفته (پنجشنبه/جمعه) پیش‌فرض ۲۵
  ۴) تعداد کلاس‌های ترم                    پیش‌فرض ۲۵
  ـ) غیبت‌ها: منفی (به‌ازای هر غیبتِ تاییدشده، با سقف)

امتیاز اولویتِ نهایی = امتیاز آخرین ترم − کسرِ کلاس‌های خصوصی/جبرانیِ گرفته‌شده (priority_score).
"""
from dataclasses import dataclass, field
from typing import Dict, List

EVEN, ODD = 'even', 'odd'
ONE_DAY_FRIDAY_MORNING = 'friday_morning'
ONE_DAY_FRIDAY_EVENING = 'friday_evening'
ONE_DAY_THURSDAY_MORNING = 'thursday_morning'
ONE_DAY_THURSDAY_EVENING = 'thursday_evening'
FRIDAY_LEGACY = 'friday'  # کلاس‌های قدیمی

# سهم هر نوع کلاسِ یک‌روزه از وزن این معیار (جمعِ بهترینِ جمعه + بهترینِ پنجشنبه + پاداشِ «هر دو» = ۱٫۰)
# جمعه > پنجشنبه، و عصر > صبح (طبق خواسته)
ONE_DAY_RATIOS = {
    ONE_DAY_FRIDAY_EVENING: 0.44,
    ONE_DAY_FRIDAY_MORNING: 0.36,
    FRIDAY_LEGACY: 0.36,
    ONE_DAY_THURSDAY_EVENING: 0.28,
    ONE_DAY_THURSDAY_MORNING: 0.20,
}
ONE_DAY_BOTH_BONUS_RATIO = 0.28
FRIDAY_TYPES = (ONE_DAY_FRIDAY_EVENING, ONE_DAY_FRIDAY_MORNING, FRIDAY_LEGACY)
THURSDAY_TYPES = (ONE_DAY_THURSDAY_EVENING, ONE_DAY_THURSDAY_MORNING)


@dataclass
class ScoringConfig:
    w_parity: float = 25
    w_students: float = 25
    w_one_day: float = 25
    w_class_count: float = 25
    # نسبت امتیازِ «فقط زوج» و «فقط فرد» به کلِ وزن تنوع (فقط‌فرد < فقط‌زوج < هر دو)
    parity_even_only_ratio: float = 0.55
    parity_odd_only_ratio: float = 0.35
    student_target: int = 60       # با این تعداد دانش‌آموز، امتیاز کامل معیار ۲
    class_count_target: int = 6    # با این تعداد کلاس، امتیاز کامل معیار ۴
    absence_penalty_per_event: float = 4
    absence_penalty_cap: float = 20


@dataclass
class TermFacts:
    day_types: List[str] = field(default_factory=list)   # day_type هر کلاسِ استاد در ترم
    student_count: int = 0
    absence_count: int = 0                                # غیبت‌های تاییدشده


def _r(x: float) -> float:
    return round(float(x), 2)


def parity_points(day_types, cfg: ScoringConfig):
    has_even = EVEN in day_types
    has_odd = ODD in day_types
    w = cfg.w_parity
    if has_even and has_odd:
        return w, 'هم زوج هم فرد دارد (امتیاز کامل)'
    if has_even:
        return w * cfg.parity_even_only_ratio, 'فقط روزهای زوج'
    if has_odd:
        return w * cfg.parity_odd_only_ratio, 'فقط روزهای فرد (کمتر از فقط‌زوج)'
    return 0.0, 'کلاس زوج/فرد ندارد'


def one_day_points(day_types, cfg: ScoringConfig):
    w = cfg.w_one_day
    friday = max((ONE_DAY_RATIOS[d] for d in day_types if d in FRIDAY_TYPES), default=0.0)
    thursday = max((ONE_DAY_RATIOS[d] for d in day_types if d in THURSDAY_TYPES), default=0.0)
    both = friday > 0 and thursday > 0
    pts = (friday + thursday + (ONE_DAY_BOTH_BONUS_RATIO if both else 0.0)) * w
    parts = []
    if friday:
        evening = any(d == ONE_DAY_FRIDAY_EVENING for d in day_types)
        parts.append('جمعه ' + ('عصر' if evening else 'صبح'))
    if thursday:
        evening = any(d == ONE_DAY_THURSDAY_EVENING for d in day_types)
        parts.append('پنجشنبه ' + ('عصر' if evening else 'صبح'))
    if both:
        parts.append('هر دو روز (پاداش)')
    return min(pts, w), ('، '.join(parts) if parts else 'کلاس یک‌روزه ندارد')


def compute_term_score(facts: TermFacts, cfg: ScoringConfig) -> Dict:
    """امتیاز یک ترمِ یک استاد + جزئیات هر معیار."""
    day_types = list(facts.day_types)
    class_count = len(day_types)

    p_pts, p_note = parity_points(day_types, cfg)
    s_ratio = min(1.0, facts.student_count / cfg.student_target) if cfg.student_target > 0 else 0.0
    s_pts = cfg.w_students * s_ratio
    o_pts, o_note = one_day_points(day_types, cfg)
    c_ratio = min(1.0, class_count / cfg.class_count_target) if cfg.class_count_target > 0 else 0.0
    c_pts = cfg.w_class_count * c_ratio
    a_pts = -min(cfg.absence_penalty_cap, facts.absence_count * cfg.absence_penalty_per_event)

    positive = p_pts + s_pts + o_pts + c_pts
    total = max(0.0, min(100.0, positive + a_pts))
    return {
        'score': _r(total),
        'criteria': [
            {'key': 'parity', 'label': 'تنوع برنامه (زوج/فرد)', 'points': _r(p_pts), 'max': cfg.w_parity,
             'detail': p_note},
            {'key': 'students', 'label': 'تعداد دانش‌آموزان ترم', 'points': _r(s_pts), 'max': cfg.w_students,
             'detail': f'{facts.student_count} نفر از هدف {cfg.student_target} نفر'},
            {'key': 'one_day', 'label': 'کلاس‌های یک‌روز در هفته', 'points': _r(o_pts), 'max': cfg.w_one_day,
             'detail': o_note},
            {'key': 'class_count', 'label': 'تعداد کلاس‌های ترم', 'points': _r(c_pts), 'max': cfg.w_class_count,
             'detail': f'{class_count} کلاس از هدف {cfg.class_count_target} کلاس'},
            {'key': 'absence', 'label': 'غیبت‌ها (منفی)', 'points': _r(a_pts), 'max': -cfg.absence_penalty_cap,
             'detail': f'{facts.absence_count} غیبت تاییدشده'},
        ],
        'facts': {'class_count': class_count, 'student_count': facts.student_count,
                  'absence_count': facts.absence_count},
    }


def usage_penalty(private_sessions: int, makeup_sessions: int,
                  private_rate: float, makeup_rate: float) -> Dict:
    """کسر امتیازِ اولویت بابت جلسه‌های خصوصی/جبرانی که استاد قبلاً گرفته (جبرانی کمتر)."""
    p = private_sessions * private_rate
    m = makeup_sessions * makeup_rate
    return {'private_sessions': private_sessions, 'makeup_sessions': makeup_sessions,
            'private_points': _r(p), 'makeup_points': _r(m), 'points': _r(p + m)}


def price_factor(priority_score: float, coefficient: float, enabled: bool) -> float:
    """ضریبِ اثر روی قیمت هر ساعت/جلسه: ۱ + ضریب × (امتیاز/۱۰۰). اگر تیک خاموش باشد همیشه ۱."""
    if not enabled:
        return 1.0
    return round(1.0 + coefficient * (max(0.0, priority_score) / 100.0), 4)
