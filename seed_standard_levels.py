# این اسکریپت رو یک‌بار، بعد از migrate، اجرا کن تا جدول StandardLevel با همون سطوحی که
# قبلاً به‌صورت هاردکد در levels.py بودن پر بشه (تا داده‌های قدیمی LevelTest/TuitionSetting که
# به این کدها اشاره می‌کنن خراب نشن).
#
# نحوه‌ی اجرا (از پوشه‌ی ریشه‌ی بک‌اند، یعنی کنار manage.py):
#   python manage.py shell < seed_standard_levels.py
#
# اجرای دوباره‌اش مشکلی نداره (idempotent) — سطح‌های تکراری دوباره ساخته نمی‌شن.

from level_tests.models import StandardLevel

KIDS_LETTERS = ['E', 'S', 'G', 'U', 'M', 'H', 'I']
KIDS_LEVELS = [f'{letter}{n}' for letter in KIDS_LETTERS for n in range(1, 6)]
TEEN_LEVELS = [f'Teen{n}' for n in range(1, 16)]
ADULT_LEVELS = [f'{main}{sub:02d}' for main in range(1, 7) for sub in range(1, 7)]

created_count = 0
for order, code in enumerate(KIDS_LEVELS):
    obj, created = StandardLevel.objects.get_or_create(code=code, defaults={'age_group': 'kids', 'order': order})
    if created:
        created_count += 1

for order, code in enumerate(TEEN_LEVELS):
    obj, created = StandardLevel.objects.get_or_create(code=code, defaults={'age_group': 'teen', 'order': order})
    if created:
        created_count += 1

for order, code in enumerate(ADULT_LEVELS):
    obj, created = StandardLevel.objects.get_or_create(code=code, defaults={'age_group': 'adult', 'order': order})
    if created:
        created_count += 1

print(f"✔ {created_count} سطح استاندارد جدید ساخته شد. جمع کل سطوح الان: {StandardLevel.objects.count()}")
