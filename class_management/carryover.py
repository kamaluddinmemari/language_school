"""
منطق مشترکِ «دانش‌آموز انتقالی از ترم قبل — منتظر ثبت‌نام».

جریان کار:
  ۱) با «انتقال کلاس به ترم بعد» برای هر دانش‌آموزِ منتقل‌شده: یک ثبت‌نامِ خاکستری (is_carryover=True،
     carryover_confirmed=False) در کلاس جدید ساخته می‌شود و یک ردیف «بدهکار» در ترم جدید باز می‌شود
     (awaiting_registration=True).
  ۲) هر مسیرِ ثبت‌نام قطعی (اکسل کلاس / ثبت‌نام دستی / تسویه‌ی بدهکار) باید `finalize_registration`
     را صدا بزند تا: اسم خاکستری مشکی شود (یا اگر در کلاس دیگری ثبت شد، از کلاس اصلی حذف شود) و
     بدهکارِ منتظر ثبت‌نام «تسویه‌شده» شود.
"""
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import ClassSlot, ClassSlotEnrollment, TuitionSetting, WalletTransaction, infer_age_group_from_level

AWAITING_LABEL = 'منتظر ثبت‌نام'
DEBTOR_CARRY_DESCRIPTION = 'دانش‌آموز انتقالی از ترم قبل — در دست بررسی و منتظر ثبت‌نام'


def _norm(value):
    return str(value or '').strip().lower()


def gray_enrollments(student, term_id):
    """ثبت‌نام‌های خاکستری (منتظر ثبت‌نام) یک دانش‌آموز در یک ترم."""
    return ClassSlotEnrollment.objects.filter(
        student=student, class_slot__term_id=term_id,
        is_carryover=True, carryover_confirmed=False, payment_verified=True,
    ).select_related('class_slot')


def _tuition_for_level(level):
    level = str(level or '').strip()
    if not level:
        return 0
    age_group = infer_age_group_from_level(level)
    setting = TuitionSetting.objects.filter(level=level, age_group=age_group).first() if age_group else None
    return int(setting.amount) if setting else 0


def _find_awaiting_debtors(student, term_id):
    from leads.models import Debtor, build_identity_key
    identity = build_identity_key('', student.phone, student.first_name, student.last_name)
    return Debtor.objects.filter(term_id=term_id, awaiting_registration=True, status=Debtor.Status.PENDING).filter(
        Q(student=student) | Q(identity_key=identity)
    )


def create_awaiting_debtor(student, target_slot, source_term, user=None):
    """ثبت دانش‌آموزِ منتقل‌شده در بدهکارانِ ترم جدید؛ در صورت وجود قبلی، فقط علامت‌گذاری می‌شود."""
    from leads.models import Debtor, build_identity_key
    term_id = target_slot.term_id
    if not term_id:
        return None
    identity = build_identity_key('', student.phone, student.first_name, student.last_name)
    existing = Debtor.objects.filter(term_id=term_id).filter(Q(student=student) | Q(identity_key=identity)).first()
    if existing:
        if existing.status == Debtor.Status.PENDING:
            existing.student = student
            existing.awaiting_registration = True
            existing.carried_from_term = source_term
            existing.source_slot = target_slot
            existing.save()
        return existing
    try:
        with transaction.atomic():
            return Debtor.objects.create(
                first_name=student.first_name, last_name=student.last_name, phone=student.phone or '',
                class_level=target_slot.assigned_level or '', debt_amount=_tuition_for_level(target_slot.assigned_level),
                description=DEBTOR_CARRY_DESCRIPTION, term_id=term_id, student=student,
                awaiting_registration=True, carried_from_term=source_term, source_slot=target_slot, created_by=user,
            )
    except IntegrityError:
        # هم‌نام و بدون موبایل با یک بدهکار دیگر — کلاس خاکستری حفظ می‌شود و ثبت بدهکار رد می‌شود
        return None


def settle_awaiting_debtors(student, term_id):
    now = timezone.now()
    count = 0
    for debtor in _find_awaiting_debtors(student, term_id):
        debtor.status = debtor.Status.SETTLED
        debtor.settled_at = now
        debtor.awaiting_registration = False
        debtor.student = debtor.student or student
        debtor.save()
        count += 1
    return count


def finalize_registration(student, slot):
    """
    بعد از ثبت‌نام قطعیِ `student` در `slot` صدا زده می‌شود (ردیف ثبت‌نام باید از قبل ساخته/تأیید شده باشد).
    - خاکستریِ همین کلاس ← مشکی (تأییدشده)
    - خاکستریِ کلاس‌های دیگرِ همان ترم ← حذف
    - بدهکارِ منتظر ثبت‌نامِ همان ترم ← تسویه‌شده
    """
    if not slot.term_id:
        return {'confirmed': 0, 'removed': 0, 'settled': 0}
    confirmed = removed = 0
    for row in gray_enrollments(student, slot.term_id):
        if row.class_slot_id == slot.id:
            row.carryover_confirmed = True
            row.save(update_fields=['carryover_confirmed'])
            confirmed += 1
        else:
            row.delete()
            removed += 1
    settled = settle_awaiting_debtors(student, slot.term_id)
    return {'confirmed': confirmed, 'removed': removed, 'settled': settled}


def register_student_in_slot(student, slot, payment_method='cash', tuition_amount=0, discount_percent=0, pos_reference_code=''):
    """
    ثبت‌نام قطعیِ دانش‌آموز در کلاسِ انتخاب‌شده توسط مدیر (بدون چک سطح — مدیر کلاس را صریح انتخاب کرده).
    خروجی: (enrollment, error_message)
    """
    if slot.gender != ClassSlot.Gender.MIXED and student.gender and (
        (slot.gender == ClassSlot.Gender.GIRLS and student.gender != 'female')
        or (slot.gender == ClassSlot.Gender.BOYS and student.gender != 'male')
    ):
        return None, 'جنسیت دانش‌آموز با این کلاس همخوانی ندارد'
    same_term = ClassSlotEnrollment.objects.filter(student=student, class_slot__term_id=slot.term_id) if slot.term_id \
        else ClassSlotEnrollment.objects.filter(student=student, class_slot__term__isnull=True)
    real = same_term.exclude(is_carryover=True, carryover_confirmed=False)
    if real.exclude(class_slot_id=slot.id).exists():
        other = real.exclude(class_slot_id=slot.id).select_related('class_slot').first()
        return None, f'این دانش‌آموز قبلاً در همین ترم در کلاس {other.class_slot.number} ثبت‌نام قطعی دارد'
    if payment_method == ClassSlotEnrollment.PaymentMethod.WALLET and student.wallet_balance < tuition_amount:
        return None, f'موجودی کیف پول ({student.wallet_balance:,} تومان) کافی نیست'

    enrollment = same_term.filter(class_slot=slot).first()
    if enrollment:
        enrollment.payment_method = payment_method
        enrollment.tuition_amount = tuition_amount
        enrollment.discount_percent = discount_percent
        enrollment.pos_reference_code = pos_reference_code
        enrollment.payment_verified = True
        enrollment.carryover_confirmed = True if enrollment.is_carryover else enrollment.carryover_confirmed
        enrollment.save()
    else:
        enrollment = ClassSlotEnrollment.objects.create(
            class_slot=slot, student=student, payment_method=payment_method,
            tuition_amount=tuition_amount, discount_percent=discount_percent, pos_reference_code=pos_reference_code,
        )
    if payment_method == ClassSlotEnrollment.PaymentMethod.WALLET and tuition_amount:
        student.wallet_balance -= tuition_amount
        student.save(update_fields=['wallet_balance'])
        WalletTransaction.objects.create(
            student=student, kind=WalletTransaction.Kind.DEBIT, amount=tuition_amount,
            reason=f'پرداخت شهریه‌ی کلاس {slot.number}', class_slot=slot,
        )
    if not slot.assigned_level and student.language_level:
        slot.assigned_level = student.language_level
        slot.save()
    finalize_registration(student, slot)
    return enrollment, ''
