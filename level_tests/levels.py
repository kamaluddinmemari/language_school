"""
منبع واحد (single source of truth) برای لیست سطح‌های تعیین سطح.
هم مدل (validation) و هم API (برای پر کردن select های پنل ارزیاب) از همین‌جا می‌خوانند —
اگر روزی لیست سطوح عوض شد، فقط همین فایل کافیست ویرایش شود.
"""

KIDS_LETTERS = ['E', 'S', 'G', 'U', 'M', 'H', 'I']
KIDS_LEVELS = [f'{letter}{n}' for letter in KIDS_LETTERS for n in range(1, 6)]

TEEN_LEVELS = [f'Teen{n}' for n in range(1, 16)]

ADULT_LEVELS = [f'{main}{sub:02d}' for main in range(1, 7) for sub in range(1, 7)]

LEVELS_BY_AGE_GROUP = {
    'kids': KIDS_LEVELS,
    'teen': TEEN_LEVELS,
    'adult': ADULT_LEVELS,
}

ALL_LEVEL_CHOICES = [(lvl, lvl) for lvl in KIDS_LEVELS + TEEN_LEVELS + ADULT_LEVELS]

AGE_GROUP_LABELS = {'kids': 'کودک', 'teen': 'نوجوان', 'adult': 'بزرگسال'}
