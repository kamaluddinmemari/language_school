"""
موتور «تخصیص کلاس» — نسخه‌ی یکپارچه: هم تصمیم می‌گیرد هر سطح به کدام کلاس (بر اساس ساعت
فعلی‌اش، که تغییر نمی‌کند) برود، هم تلاش می‌کند هر سطح را در یک کلاس واحد جا بدهد. اگر یک
کلاس برای کل تقاضای یک سطح کافی نبود، به‌جای پخش خودکار و بی‌صدا بین چند کلاس، باقیمانده به‌عنوان
«نیازمند تایید مدیر برای کلاس دوم» برگردانده می‌شود (pending_overflow) — مدیر با تایید،
کلاس دوم را (از میان کاندیدهای پیشنهادی) فعال می‌کند.

هر سطح می‌تواند اختیاری «روز/ساعت/استاد ترجیحی» هم داشته باشد (preferred_day_type/
preferred_time_slot/preferred_teacher_name) — اگر داده شود، اول سعی می‌شود دقیقاً همان
روز+ساعت بین اتاق‌های موجود پیدا شود (نه فقط دسته‌ی ساعتیِ کلی)، و اگر آن اتاق هنوز استادی
ندارد، نام استاد ترجیحی رویش گذاشته می‌شود. اگر چنین اتاقی پیدا نشد، به همان منطق قبلیِ
دسته‌بندی ساعتی کلی برمی‌گردد و هشدار می‌دهد.
"""
from .models import ClassSlot


def _level_category(entry):
    """دسته‌ی ساعتی موردنیاز این سطح، بر اساس وضعیت مدرسه‌ی اکثریت زبان‌آموزانش"""
    if entry.get('is_rotating_majority') or entry.get('student_status') == 'rotating':
        return 'evening_late'
    if entry.get('student_status') == 'only_morning':
        return 'evening_any'
    return 'morning'


def allocate_classes(levels, tolerance=0, thursday_only_count=0, friday_only_count=0):
    """
    levels: [{'level': 'B1', 'count': 12, 'is_rotating_majority': False, 'student_status': 'rotating',
               'preferred_day_type': 'even', 'preferred_time_slot': '17:30-19:00',
               'preferred_teacher_name': 'استاد رضایی'}, ...]
    برمی‌گرداند: (warnings, summary, pending_overflow)
    """
    slots = list(ClassSlot.objects.all().order_by('number'))
    for s in slots:
        s.assigned_level = ''
        s.current_count = 0

    thursday_slots = [s for s in slots if s.day_type in (ClassSlot.DayType.THURSDAY_MORNING, ClassSlot.DayType.THURSDAY_EVENING)]
    friday_slots = [s for s in slots if s.day_type == ClassSlot.DayType.FRIDAY]
    category_slots = [s for s in slots if s.day_type in (
        ClassSlot.DayType.EVEN, ClassSlot.DayType.ODD, ClassSlot.DayType.ONLINE, ClassSlot.DayType.HYBRID)]

    demand = sorted([dict(l) for l in levels if l.get('count', 0) > 0], key=lambda x: -x['count'])
    warnings = []
    pending_overflow = []

    def fill_pool(slot_list, level_name, needed):
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
            left = fill_pool(slot_list, d['level'], take)
            placed = take - left
            d['count'] -= placed
            remaining -= placed
        if remaining > 0:
            warnings.append(f"{remaining} نفر از علاقه‌مندان «{pool_name}» به‌خاطر کمبود ظرفیت کلاس‌های تک‌روزه جا نشدند.")

    carve_out('فقط پنجشنبه', thursday_only_count, thursday_slots)
    carve_out('فقط جمعه', friday_only_count, friday_slots)

    def assign_teacher_if_needed(slot, preferred_teacher):
        """اگر استاد ترجیحی داده شده و اتاق هنوز استادی ندارد، همین‌جا رویش می‌گذاریم"""
        if preferred_teacher and not slot.teacher_name:
            slot.teacher_name = preferred_teacher

    for entry in demand:
        if entry['count'] <= 0:
            continue
        level_name = entry['level']
        needed = entry['count']
        pref_day = (entry.get('preferred_day_type') or '').strip()
        pref_time = (entry.get('preferred_time_slot') or '').strip()
        pref_teacher = (entry.get('preferred_teacher_name') or '').strip()

        candidates = []
        used_exact_pref = False
        if pref_day and pref_time:
            exact_candidates = [
                s for s in category_slots
                if s.day_type == pref_day and s.time_slot == pref_time
                and (not s.assigned_level or s.assigned_level == level_name)
                and (not s.teacher_name or not pref_teacher or s.teacher_name == pref_teacher)
            ]
            if exact_candidates:
                candidates = exact_candidates
                used_exact_pref = True
            else:
                warnings.append(
                    f"سطح «{level_name}»: اتاقی با روز/ساعت درخواستی («{pref_day}»، «{pref_time}»"
                    + (f"، استاد «{pref_teacher}»" if pref_teacher else "") +
                    ") پیدا نشد یا استاد دیگری آنجا دارد — طبق دسته‌ی ساعتی معمول این سطح تخصیص داده شد."
                )

        if not candidates:
            category = _level_category(entry)
            candidates = [s for s in category_slots if category in s.time_category() and (not s.assigned_level or s.assigned_level == level_name)]

        # ترجیح اول: یک کلاس که کل تقاضا در آن جا شود (کوچک‌ترین ظرفیت کافی، برای جلوگیری از اسراف ظرفیت)
        exact_fits = [s for s in candidates if (s.capacity + tolerance - s.current_count) >= needed]
        if exact_fits:
            best = min(exact_fits, key=lambda s: s.capacity)
            best.assigned_level = level_name
            best.current_count += needed
            assign_teacher_if_needed(best, pref_teacher)
            continue

        # جا نشد در یک کلاس؛ بیشترین ظرفیت خالی ممکن را در بهترین کلاس موجود پر کن
        remaining = needed
        if candidates:
            best = max(candidates, key=lambda s: (s.capacity + tolerance - s.current_count))
            room = (best.capacity + tolerance) - best.current_count
            if room > 0:
                best.assigned_level = level_name
                best.current_count += room
                assign_teacher_if_needed(best, pref_teacher)
                remaining = needed - room
            placed_slot_id = best.id
        else:
            placed_slot_id = None

        if remaining > 0:
            if used_exact_pref:
                # اگر با روز/ساعت دقیق دنبال کلاس دوم هم بگردیم، آدرس‌مان محدودتر می‌شود
                second_candidates = [
                    s for s in category_slots
                    if s.day_type == pref_day and s.time_slot == pref_time and s.id != placed_slot_id
                    and (not s.assigned_level or s.assigned_level == level_name)
                    and (s.capacity + tolerance - s.current_count) > 0
                ]
                if not second_candidates:
                    category = _level_category(entry)
                    second_candidates = [
                        s for s in category_slots
                        if category in s.time_category() and s.id != placed_slot_id
                        and (not s.assigned_level or s.assigned_level == level_name)
                        and (s.capacity + tolerance - s.current_count) > 0
                    ]
            else:
                category = _level_category(entry)
                second_candidates = [
                    s for s in category_slots
                    if category in s.time_category() and s.id != placed_slot_id
                    and (not s.assigned_level or s.assigned_level == level_name)
                    and (s.capacity + tolerance - s.current_count) > 0
                ]
            pending_overflow.append({
                'level': level_name,
                'remaining_count': remaining,
                'candidate_slots': [{'id': s.id, 'number': s.number, 'time_slot': s.time_slot, 'seats_left': s.capacity + tolerance - s.current_count} for s in second_candidates],
            })
            warnings.append(f"سطح «{level_name}»: {remaining} نفر در یک کلاس جا نشدند — برای کلاس دوم نیاز به تایید مدیر دارد (پایین صفحه).")

    for s in slots:
        s.save(update_fields=['assigned_level', 'current_count', 'teacher_name', 'updated_at'])

    summary = {
        'total_slots': len(slots),
        'filled_slots': len([s for s in slots if s.current_count > 0]),
        'empty_slots': len([s for s in slots if s.current_count == 0]),
        'over_capacity_slots': len([s for s in slots if s.current_count > s.capacity]),
    }
    return warnings, summary, pending_overflow
