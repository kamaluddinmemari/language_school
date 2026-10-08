from django.utils import timezone

from .models import Debtor, UnregisteredStudent, normalize_phone


CARRYOVER_DEBT_LABEL = 'دانش‌آموز انتقالی از ترم قبل در دست بررسی و منتظر ثبت‌نام'


def _same_person(record, student):
    record_phone = normalize_phone(getattr(record, 'phone', ''))
    student_phone = normalize_phone(getattr(student, 'phone', ''))
    names_match = (
        (record.first_name or '').strip().casefold() == (student.first_name or '').strip().casefold()
        and (record.last_name or '').strip().casefold() == (student.last_name or '').strip().casefold()
    )
    if record_phone and student_phone:
        return record_phone == student_phone and names_match
    return names_match


def create_carryover_debtor(student, source_term, target_slot):
    """Create/update the target-term debt tracker for a roster-only carryover."""
    from class_management.models import DiscountedPerson, TuitionSetting, infer_age_group_from_level

    level = str(target_slot.assigned_level or '').strip()
    age_group = infer_age_group_from_level(level) if level else ''
    tuition = TuitionSetting.objects.filter(level=level, age_group=age_group).first() if level and age_group else None
    discount = DiscountedPerson.objects.filter(student=student).order_by('-updated_at').first()
    discount_percent = discount.discount_percent if discount else 0
    amount = round(tuition.amount * (100 - discount_percent) / 100) if tuition else 0
    phone = (student.phone or '').strip() or f'ID{student.pk}'

    debtor = None
    for candidate in Debtor.objects.filter(term=target_slot.term).order_by('-created_at'):
        if _same_person(candidate, student):
            debtor = candidate
            break
    description = (debtor.description if debtor else '').strip()
    if CARRYOVER_DEBT_LABEL not in description:
        description = f'{CARRYOVER_DEBT_LABEL} — {description}'.strip(' —')
    if debtor is None:
        debtor = Debtor(
            first_name=student.first_name or 'دانش‌آموز', last_name=student.last_name or '',
            phone=phone, class_level=level, debt_amount=amount, description=description,
            status=Debtor.Status.PENDING, term=target_slot.term,
        )
    else:
        debtor.first_name = student.first_name or debtor.first_name
        debtor.last_name = student.last_name or debtor.last_name
        debtor.phone = phone
        debtor.class_level = level
        debtor.debt_amount = amount if amount else debtor.debt_amount
        debtor.description = description
        debtor.status = Debtor.Status.PENDING
        debtor.settled_at = None
    debtor.save()
    return debtor


def mark_student_registered(student, term):
    """Move matching debt/unregistered trackers to registered after a class enrollment."""
    if not term:
        return
    now = timezone.now()
    for debtor in Debtor.objects.filter(term=term).exclude(status=Debtor.Status.REGISTERED):
        if _same_person(debtor, student):
            debtor.status = Debtor.Status.REGISTERED
            debtor.settled_at = now
            debtor.save(update_fields=['status', 'settled_at', 'updated_at'])
    for record in UnregisteredStudent.objects.filter(term=term).exclude(status=UnregisteredStudent.Status.REGISTERED):
        if _same_person(record, student):
            record.status = UnregisteredStudent.Status.REGISTERED
            record.registered_at = now
            record.save(update_fields=['status', 'registered_at', 'updated_at'])
