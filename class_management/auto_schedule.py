"""
چیدمان هوشمند ساعت‌ها: برای کلاس‌های سه‌روزه (زوج/فرد)، صبح یا عصر بودن و ساعت دقیق را بر اساس
وضعیت اکثریت زبان‌آموزان همان کلاس تعیین می‌کند:
- اکثریت «چرخشی» → عصر، حتماً از ساعت ۱۷:۳۰ به بعد (چون مدرسه‌ی چرخشی ممکن است هر هفته
  زمان متفاوتی داشته باشد، تنها ساعت‌های خیلی دیر همیشه بدون تداخل‌اند).
- اکثریت «فقط صبح» → عصر، هر ساعتی مانعی ندارد (چون مدرسه‌شان ثابت صبح است، همیشه عصر آزادند).
- بقیه‌ی حالت‌ها (تمایل یک‌روزه/ترکیب مجازی/سایر/نامشخص) → صبح، چون تداخل مدرسه‌ی صبح محرز نیست.
توزیع بین چند گزینه‌ی ساعت هر دسته با چرخش (round-robin) در همان گروه (روز زوج/فرد) انجام می‌شود
تا کلاس‌های هم‌گروه روی یک ساعت واحد تلنبار نشوند. نتیجه همیشه بعداً دستی هم قابل ویرایش است.
"""
from .models import ClassSlot, MORNING_TIME_SLOTS, EVENING_TIME_SLOTS, EVENING_LATE_TIME_SLOTS


def auto_schedule_times():
    slots = list(ClassSlot.objects.filter(day_type__in=[ClassSlot.DayType.EVEN, ClassSlot.DayType.ODD]).order_by('day_type', 'number'))
    counters = {}

    for s in slots:
        if s.is_effectively_rotating:
            category = 'evening_late'
            options = EVENING_LATE_TIME_SLOTS
        elif s.student_status == ClassSlot.StudentStatus.ONLY_MORNING:
            category = 'evening_any'
            options = EVENING_TIME_SLOTS
        else:
            category = 'morning'
            options = MORNING_TIME_SLOTS

        key = (s.day_type, category)
        idx = counters.get(key, 0)
        s.time_slot = options[idx % len(options)]
        counters[key] = idx + 1
        s.save(update_fields=['time_slot', 'updated_at'])

    # کلاس‌های تک‌روزه (پنجشنبه/جمعه) ساعت ثابت دارند؛ همین که save() هر رکورد صدا زده شود کافیست
    fixed_slots = ClassSlot.objects.exclude(day_type__in=[ClassSlot.DayType.EVEN, ClassSlot.DayType.ODD])
    for s in fixed_slots:
        s.save(update_fields=['time_slot', 'updated_at'])

    return ClassSlot.objects.all().order_by('number')
