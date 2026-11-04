from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


@receiver(post_save, sender='class_management.ClassSlotEnrollment')
def remove_registered_person_from_waiting_list(sender, instance, **kwargs):
    """Mark a matching waiting-list lead registered after confirmed enrollment in the latest eligible term."""
    if instance.is_carryover and not instance.carryover_confirmed:
        return

    from class_management.models import get_current_term, get_latest_term_for_pre_registration
    latest_term = get_latest_term_for_pre_registration() or get_current_term()
    if not latest_term or instance.class_slot.term_id != latest_term.id:
        return

    from leads.models import NewLead, normalize_national_code, normalize_phone

    student = instance.student
    national_code = normalize_national_code(getattr(student, 'national_code', '') or '')
    phone = normalize_phone(getattr(student, 'phone', '') or '')
    matches = []

    pending = NewLead.objects.filter(status=NewLead.Status.PENDING)
    if national_code:
        for lead in pending.exclude(national_code='').only('id', 'national_code', 'phone', 'first_name', 'last_name'):
            if normalize_national_code(lead.national_code) == national_code:
                matches.append(lead.id)
    if not matches and phone:
        first = (getattr(student, 'first_name', '') or '').strip().casefold()
        last = (getattr(student, 'last_name', '') or '').strip().casefold()
        if first or last:
            for lead in pending.only('id', 'national_code', 'phone', 'first_name', 'last_name'):
                if (lead.first_name or '').strip().casefold() != first or (lead.last_name or '').strip().casefold() != last:
                    continue
                if normalize_phone(lead.phone) == phone:
                    matches.append(lead.id)

    if matches:
        NewLead.objects.filter(id__in=matches, status=NewLead.Status.PENDING).update(
            status=NewLead.Status.REGISTERED, registered_at=timezone.now(), no_response=False,
        )
