"""هشدار «فرد کلاً نیامده» و «فرد در کلاس دیگری پیدا شد» (اپ مدیریت کلاس‌ها ↔ پنل وب)."""
NEVER_CAME_NOTE = 'فرد از ابتدا سر کلاس نبوده؛ ممکن است سر کلاس اشتباهی باشد یا کلاً نیامده باشد'


def slot_detail_text(slot):
    """مشخصات کلاس: شماره، سطح، روز، ساعت، استاد."""
    if slot is None:
        return 'نامشخص'
    day = getattr(slot, 'day_type_display', None) or slot.get_day_type_display() or '—'
    return ' | '.join([
        f'کلاس {slot.number}', f'سطح: {slot.assigned_level or "نامشخص"}', f'روز: {day}',
        f'ساعت: {slot.time_slot or "نامشخص"}', f'استاد: {slot.teacher_name or "نامشخص"}',
    ])


def push_alert(kind, name, text, unregistered=None, by=None):
    from .models import FollowupAlertEvent
    return FollowupAlertEvent.objects.create(kind=kind, name=name, text=text, unregistered=unregistered, created_by=by)


def apply_found_elsewhere(existing, new_slot, actor=None):
    """
    فردی که قبلاً «کلاً نیامده» گزارش شده بود، حالا در کلاس دیگری دیده/ثبت شد:
    توضیح زرد «از کلاس قدیمی ← به کلاس درست» روی همان ردیف پیگیری می‌نشیند، فرد «جابجا شود» می‌شود
    و هشدار صوتی/زیرنویس در اپ و پنل پخش می‌شود. اگر همان کلاسِ قبلی باشد، کاری نمی‌کند (False).
    """
    old_slot = existing.misplaced_from_slot
    if new_slot is None or (old_slot and old_slot.pk == new_slot.pk):
        return False
    name = f'{existing.first_name} {existing.last_name}'.strip()
    note = f'⚠ فرد در کلاس اشتباهی ثبت شده — جابجایی لازم: از «{slot_detail_text(old_slot)}» ← به «{slot_detail_text(new_slot)}» (کلاس قدیمی ← کلاس درست)'
    existing.relocation_note = note
    existing.reported_slot = new_slot
    existing.is_misplaced = bool(old_slot)
    if not existing.class_level or existing.class_level == 'نامشخص':
        existing.class_level = new_slot.assigned_level or existing.class_level
    existing.save()
    push_alert('found_elsewhere', name, f'«{name}» در کلاس دیگری پیدا شد — از کلاس {old_slot.number if old_slot else "؟"} به کلاس {new_slot.number} جابجا شود', existing, actor)
    return True
