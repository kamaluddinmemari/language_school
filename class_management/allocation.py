"""
موتور «تخصیص کلاس» — بعد از این‌که همه‌ی کلاس‌ها با «چیدمان هوشمند ساعت‌ها» زمان‌بندی شدند،
این بخش تصمیم می‌گیرد کدام سطح با چه تعدادی در کدام کلاس بنشیند. یک الگوریتم حریصانه (greedy)
شفاف است، نه یک حل‌کننده‌ی کامل بهینه‌سازی — نتیجه همیشه توسط مدیر قابل ویرایش دستی است.
"""
from .models import ClassSlot


def allocate_classes(levels, tolerance=0, thursday_only_count=0, friday_only_count=0):
    """
    levels: [{'level': 'B1', 'count': 12}, ...] — تقاضای هر سطح.
    برمی‌گرداند: (warnings, summary) و مستقیماً assigned_level/current_count همه‌ی کلاس‌ها را بازنویسی می‌کند
    (روز/ساعت/ظرفیت/استاد/وضعیت چرخشی هر کلاس دست‌نخورده می‌ماند، چون این‌ها زیرساخت ثابت‌اند).
    """
    slots = list(ClassSlot.objects.all().order_by('number'))
    for s in slots:
        s.assigned_level = ''
        s.current_count = 0

    thursday_slots = [s for s in slots if s.day_type in (ClassSlot.DayType.THURSDAY_MORNING, ClassSlot.DayType.THURSDAY_EVENING)]
    friday_slots = [s for s in slots if s.day_type == ClassSlot.DayType.FRIDAY]
    three_day_slots = [s for s in slots if s.is_three_day]

    demand = sorted([dict(l) for l in levels if l.get('count', 0) > 0], key=lambda x: -x['count'])
    warnings = []

    def fill(slot_list, level_name, needed):
        remaining = needed
        for slot in slot_list:
            if remaining <= 0:
                break
            if slot.assigned_level and slot.assigned_level != level_name:
                continue
            room = (slot.capacity + tolerance) - slot.current_count
            if room <= 0:
                continue
            take = min(room, remaining)
            slot.assigned_level = level_name
            slot.current_count += take
            remaining -= take
        return remaining

    def carve_out(pool_name, count, slot_list):
        if count <= 0 or not slot_list:
            return
        remaining = count
        for d in demand:
            if remaining <= 0:
                break
            take = min(d['count'], remaining)
            if take <= 0:
                continue
            left = fill(slot_list, d['level'], take)
            placed = take - left
            d['count'] -= placed
            remaining -= placed
        if remaining > 0:
            warnings.append(f"{remaining} نفر از علاقه‌مندان «{pool_name}» به‌خاطر کمبود ظرفیت کلاس‌های تک‌روزه جا نشدند.")

    carve_out('فقط پنجشنبه', thursday_only_count, thursday_slots)
    carve_out('فقط جمعه', friday_only_count, friday_slots)

    for d in demand:
        if d['count'] <= 0:
            continue
        left = fill(three_day_slots, d['level'], d['count'])
        if left > 0:
            left = fill(thursday_slots + friday_slots, d['level'], left)
        if left > 0:
            warnings.append(f"سطح «{d['level']}»: {left} نفر به‌خاطر کمبود ظرفیت کلاس‌ها تخصیص داده نشدند.")

    for s in slots:
        s.save(update_fields=['assigned_level', 'current_count', 'updated_at'])

    summary = {
        'total_slots': len(slots),
        'filled_slots': len([s for s in slots if s.current_count > 0]),
        'empty_slots': len([s for s in slots if s.current_count == 0]),
        'over_capacity_slots': len([s for s in slots if s.current_count > s.capacity]),
    }
    return warnings, summary
