"""
تبدیل نوع کلاس بین «خصوصی/جبرانی» (ClassRequest) و «ورکشاپ» (GroupSession).

- خصوصی/جبرانی → ورکشاپ: اگر خصوصی پرداخت شده بود، مبلغ پرداخت‌شده با قیمت ورکشاپ مقایسه و
  استرداد/باقی‌مانده محاسبه می‌شود. با confirm=false فقط پیش‌نمایش محاسبه برمی‌گردد.
- ورکشاپ → خصوصی/جبرانی: وضعیت پرداخت هر نفر باید صریحاً مشخص شود (برای خصوصی).
هیچ ستون جدیدی لازم نیست.
"""
import uuid
import re
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from accounts.models import ClassRequest, PriceSetting, User
from .models import GroupSession, GroupSessionParticipant

ALLOWED_SOURCE_STATUSES = (ClassRequest.Status.PENDING, ClassRequest.Status.REFERRED, ClassRequest.Status.CONFIRMED)


def _can_convert(user):
    return getattr(user, 'role', None) in ('admin', 'office')


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _member_name(req):
    s = req.student
    return f'{s.first_name} {s.last_name}'.strip() or s.username


def _private_destination_price(group_size, duration, session_count):
    try:
        setting = PriceSetting.objects.latest('updated_at')
    except Exception:
        try:
            setting = PriceSetting.objects.values(
                'one_hour_price', 'one_half_hour_price', 'teacher_share_percent', 'school_share_percent'
            ).latest('updated_at')
        except Exception:
            setting = None

    def setting_value(field, default):
        if isinstance(setting, dict):
            return setting.get(field, default)
        return getattr(setting, field, default) if setting else default

    size = max(_int(group_size, 1), 1)
    if size >= 3:
        field = 'three_plus_person_one_hour_price' if str(duration) == '1' else 'three_plus_person_one_half_hour_price'
        default = 400000 if str(duration) == '1' else 550000
    elif size == 2:
        field = 'two_person_one_hour_price' if str(duration) == '1' else 'two_person_one_half_hour_price'
        default = 400000 if str(duration) == '1' else 550000
    else:
        field = 'one_hour_price' if str(duration) == '1' else 'one_half_hour_price'
        default = 400000 if str(duration) == '1' else 550000
    return max(int(setting_value(field, default) or 0), 0) * max(_int(session_count, 1), 1)


class ConvertRequestTypeView(APIView):
    """تبدیل خصوصی↔جبرانی برای کل گروه؛ مقصد خصوصی نیازمند وضعیت پرداخت هر عضو است."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _can_convert(request.user):
            return Response({'error': 'فقط مدیر یا کارشناس اداری می‌تواند نوع کلاس را تغییر دهد'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data
        target = data.get('target_type')
        if target not in ('private', 'makeup'):
            return Response({'error': 'نوع مقصد باید خصوصی یا جبرانی باشد'}, status=status.HTTP_400_BAD_REQUEST)
        payments = data.get('payments') or {}
        try:
            with transaction.atomic():
                anchor = ClassRequest.objects.select_for_update().get(pk=data.get('request_id'))
                qs = ClassRequest.objects.select_for_update()
                qs = qs.filter(group_key=anchor.group_key) if anchor.group_key else qs.filter(pk=anchor.pk)
                members = list(qs.select_related('student').prefetch_related('sessions', 'assigned_teachers', 'accepted_teachers'))
                if not members or any(m.class_type not in ('private', 'makeup') for m in members):
                    return Response({'error': 'فقط کلاس خصوصی یا جبرانی قابل تبدیل است'}, status=status.HTTP_400_BAD_REQUEST)
                if any(m.class_type == target for m in members):
                    return Response({'error': 'نوع کلاس هم‌اکنون همین است'}, status=status.HTTP_400_BAD_REQUEST)
                if any(m.status not in ALLOWED_SOURCE_STATUSES for m in members):
                    return Response({'error': 'فقط کلاس‌های فعال قابل تبدیل هستند'}, status=status.HTTP_400_BAD_REQUEST)
                if any(m.sessions.filter(held=True, is_cancelled=False).exists() for m in members):
                    return Response({'error': 'کلاسی که جلسه‌ای از آن برگزار شده قابل تبدیل نیست'}, status=status.HTTP_400_BAD_REQUEST)
                if target == 'private':
                    for m in members:
                        pay = payments.get(str(m.id)) or {}
                        if pay.get('payment_status') not in ('paid', 'unpaid'):
                            return Response({'error': f'وضعیت پرداخت {_member_name(m)} را مشخص کنید'}, status=status.HTTP_400_BAD_REQUEST)
                        if pay.get('payment_status') == 'paid' and pay.get('payment_method') not in ('cash', 'card_to_card', 'pos'):
                            return Response({'error': f'روش پرداخت {_member_name(m)} را مشخص کنید'}, status=status.HTTP_400_BAD_REQUEST)
                rows = []
                for m in members:
                    source_price = max(int(m.total_price or m.amount or 0), 0)
                    source_paid = source_price if m.payment_status == ClassRequest.PaymentStatus.PAID and not m.is_refunded else 0
                    destination_price = _private_destination_price(m.group_size or len(members), m.session_duration, m.session_count) if target == 'private' else 0
                    pay = payments.get(str(m.id)) or {}
                    additional_payment = max(destination_price - source_paid, 0) if target == 'private' and pay.get('payment_status') == 'paid' else 0
                    available = source_paid + additional_payment
                    refund = max(source_paid - destination_price, 0)
                    due = max(destination_price - available, 0)
                    final_payment_status = 'paid' if due == 0 else 'unpaid'
                    settlement_status = 'creditor' if refund else 'debtor' if due else 'settled'
                    rows.append({
                        'request_id': m.id, 'name': _member_name(m), 'source_price': source_price,
                        'source_paid': source_paid, 'destination_price': destination_price,
                        'additional_payment': additional_payment, 'refund': refund, 'due': due,
                        'payment_status': final_payment_status, 'settlement_status': settlement_status,
                    })
                summary = {
                    'members': rows,
                    'source_price_total': sum(row['source_price'] for row in rows),
                    'source_paid_total': sum(row['source_paid'] for row in rows),
                    'destination_price_total': sum(row['destination_price'] for row in rows),
                    'refund_total': sum(row['refund'] for row in rows),
                    'due_total': sum(row['due'] for row in rows),
                    'debtor_count': sum(1 for row in rows if row['due'] > 0),
                    'creditor_count': sum(1 for row in rows if row['refund'] > 0),
                    'settled_count': sum(1 for row in rows if row['settlement_status'] == 'settled'),
                }
                if data.get('preview') in (True, 'true', '1', 1):
                    return Response({'preview': True, **summary})
                changed = []
                for m, row in zip(members, rows):
                    old_type = m.class_type
                    m.class_type = target
                    if target == 'private':
                        pay = payments[str(m.id)]
                        m.payment_status = row['payment_status']
                        if m.payment_status == 'paid':
                            if row['additional_payment'] > 0:
                                m.payment_method = pay['payment_method']
                                m.payment_reference = str(pay.get('payment_reference') or '')[:100]
                                m.payment_confirmed_at = timezone.now()
                        else:
                            m.payment_method = ''
                            m.payment_reference = ''
                            m.payment_confirmed_at = None
                    m.notes = re.sub(r'ثبت موازی از ورکشاپ #\d+(?:\s*\[workshop-blue\])?(?:\s*\[workshop-free\])?', 'تغییر نوع از ورکشاپ', m.notes or '')
                    m.notes = ((m.notes + '\n') if m.notes else '') + f'تبدیل از {"خصوصی" if old_type == "private" else "جبرانی"} به {"خصوصی" if target == "private" else "جبرانی"}'
                    if row['refund']:
                        m.is_refunded = True
                        m.refund_amount = row['refund']
                        m.refund_date = timezone.now()
                        m.refund_note = 'استرداد بابت تبدیل کلاس خصوصی به جبرانی؛ وجه باید عملاً مسترد شده باشد'
                        m.refund_recorded_by = request.user
                    m.save()  # قیمت خصوصی طبق تعداد جلسات و تعداد اعضای گروه از مدل محاسبه می‌شود.
                    changed.append(m.id)
                return Response({'message': f'کلاس به {"خصوصی" if target == "private" else "جبرانی"} تبدیل شد', 'class_request_ids': changed, **summary})
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)


class ConvertRequestToWorkshopView(APIView):
    """POST: {request_id, price_per_person, capacity?, title?, settle_mode: 'net'|'full_refund', confirm, refund_reference?, refund_note?}"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _can_convert(request.user):
            return Response({'error': 'فقط مدیر یا کارشناس اداری می‌تواند نوع کلاس را تغییر دهد'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data
        price = _int(data.get('price_per_person'), -1)
        if price < 0:
            return Response({'error': 'قیمت هرنفر ورکشاپ را وارد کنید (۰ = رایگان)'}, status=status.HTTP_400_BAD_REQUEST)
        settle_mode = data.get('settle_mode') or 'net'
        if settle_mode not in ('net', 'full_refund'):
            return Response({'error': 'نحوه‌ی تسویه نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        confirm = data.get('confirm') in (True, 'true', '1', 1)
        try:
            with transaction.atomic():
                anchor = ClassRequest.objects.select_for_update().get(pk=data.get('request_id'))
                members_qs = ClassRequest.objects.select_for_update()
                members_qs = members_qs.filter(group_key=anchor.group_key) if anchor.group_key else members_qs.filter(pk=anchor.pk)
                members = list(members_qs.select_related('student', 'teacher').prefetch_related('assigned_teachers', 'accepted_teachers'))
                if any(m.class_type not in (ClassRequest.ClassType.PRIVATE, ClassRequest.ClassType.MAKEUP) for m in members):
                    return Response({'error': 'فقط کلاس خصوصی یا جبرانی قابل تبدیل به ورکشاپ است'}, status=status.HTTP_400_BAD_REQUEST)
                if any(m.status not in ALLOWED_SOURCE_STATUSES for m in members):
                    return Response({'error': 'فقط کلاس‌های در انتظار، ارجاع‌شده یا تایید نهایی قابل تبدیل هستند'}, status=status.HTTP_400_BAD_REQUEST)
                if any(m.sessions.filter(held=True, is_cancelled=False).exists() for m in members):
                    return Response({'error': 'کلاسی که جلسه‌ای از آن برگزار شده قابل تبدیل نیست'}, status=status.HTTP_400_BAD_REQUEST)

                # --- محاسبه برای هر نفر
                rows = []
                for m in members:
                    source_price = max(int(m.total_price or m.amount or 0), 0)
                    paid_amount = source_price if m.payment_status == ClassRequest.PaymentStatus.PAID and not m.is_refunded else 0
                    if paid_amount and settle_mode == 'full_refund':
                        refund, due = paid_amount, price
                    else:
                        refund, due = max(paid_amount - price, 0), max(price - paid_amount, 0)
                    settlement_status = 'creditor_and_debtor' if refund > 0 and due > 0 else 'creditor' if refund > 0 else 'debtor' if due > 0 else 'settled'
                    rows.append({
                        'request_id': m.id, 'name': _member_name(m), 'class_type': m.class_type,
                        'source_price': source_price, 'paid_amount': paid_amount, 'workshop_price': price,
                        'refund': refund, 'due': due, 'settlement_status': settlement_status,
                        'will_be_paid': due == 0 and (paid_amount > 0 or price == 0),
                    })
                summary = {
                    'members': rows, 'refund_total': sum(r['refund'] for r in rows), 'due_total': sum(r['due'] for r in rows),
                    'paid_total': sum(r['paid_amount'] for r in rows),
                    'source_price_total': sum(r['source_price'] for r in rows),
                    'debtor_count': sum(1 for r in rows if r['due'] > 0),
                    'creditor_count': sum(1 for r in rows if r['refund'] > 0),
                    'settled_count': sum(1 for r in rows if r['settlement_status'] == 'settled'),
                }
                if not confirm:
                    return Response({'preview': True, **summary})

                capacity = max(_int(data.get('capacity'), len(members)), len(members), 2)
                src = anchor
                session = GroupSession.objects.create(
                    session_type=GroupSession.SessionType.WORKSHOP,
                    title=str(data.get('title') or '').strip()[:200],
                    is_online=src.is_online, meeting_link=src.meeting_link,
                    language_level=src.language_level, class_date=src.class_date,
                    session_duration=src.session_duration, session_count=src.session_count,
                    capacity=capacity, price_per_person=price,
                    notes=(f'تبدیل‌شده از کلاس {"خصوصی" if src.class_type == "private" else "جبرانی"} #{src.id}' + (f' — {src.notes}' if src.notes else '')),
                    created_by=request.user,
                )
                if src.status == ClassRequest.Status.CONFIRMED:
                    session.status = GroupSession.Status.CONFIRMED
                elif src.status == ClassRequest.Status.REFERRED:
                    session.status = GroupSession.Status.ASSIGNING
                assigned = {t.pk: t for m in members for t in m.assigned_teachers.all()}
                accepted = {t.pk: t for m in members for t in m.accepted_teachers.all()}
                if src.teacher and src.teacher.pk not in assigned:
                    assigned[src.teacher.pk] = src.teacher
                session.assigned_teachers.set(assigned.values())
                session.accepted_teachers.set(accepted.values())
                if src.teacher:
                    session.teacher = src.teacher
                session.save()

                now = timezone.now()
                reference = str(data.get('refund_reference') or '').strip()[:100]
                note = str(data.get('refund_note') or '').strip()
                parallel_group_key = f'multi-{uuid.uuid4().hex[:12]}' if len(members) > 1 else ''
                parallel_class_request_ids = []
                workshop_copy_note = f'ثبت موازی از ورکشاپ #{session.id} [workshop-blue]' + (' [workshop-free]' if price == 0 else '')
                for m, row in zip(members, rows):
                    GroupSessionParticipant.objects.get_or_create(
                        group_session=session, student=m.student,
                        defaults={'payment_status': GroupSessionParticipant.PaymentStatus.PAID if row['will_be_paid'] else GroupSessionParticipant.PaymentStatus.UNPAID},
                    )
                    parallel_request = ClassRequest.objects.create(
                        student=m.student,
                        teacher=m.teacher,
                        class_type=ClassRequest.ClassType.MAKEUP,
                        group_key=parallel_group_key,
                        group_size=len(members),
                        is_online=m.is_online,
                        meeting_link=m.meeting_link,
                        language_level=m.language_level,
                        proposed_time=m.proposed_time,
                        suggested_teacher_name=m.suggested_teacher_name,
                        class_date=m.class_date,
                        class_date_approved=m.class_date_approved,
                        teacher_coordinated=m.teacher_coordinated,
                        student_coordinated=m.student_coordinated,
                        workflow_stage=m.workflow_stage,
                        session_duration=m.session_duration,
                        session_count=m.session_count,
                        payment_status=ClassRequest.PaymentStatus.PAID if row['will_be_paid'] else ClassRequest.PaymentStatus.UNPAID,
                        payment_method=m.payment_method if row['will_be_paid'] and m.class_type == ClassRequest.ClassType.PRIVATE else '',
                        payment_reference=m.payment_reference if row['will_be_paid'] and m.class_type == ClassRequest.ClassType.PRIVATE else '',
                        payment_confirmed_at=m.payment_confirmed_at if row['will_be_paid'] and m.class_type == ClassRequest.ClassType.PRIVATE else None,
                        status=m.status,
                        is_urgent=m.is_urgent,
                        force_last=m.force_last,
                        source_level_test=m.source_level_test,
                        sequence_warning=m.sequence_warning,
                        sequence_warning_details=m.sequence_warning_details,
                        notes=workshop_copy_note,
                    )
                    parallel_request.assigned_teachers.set(m.assigned_teachers.all())
                    parallel_request.accepted_teachers.set(m.accepted_teachers.all())
                    parallel_class_request_ids.append(parallel_request.id)
                    m.status = ClassRequest.Status.CANCELLED
                    fields = ['status', 'updated_at', 'notes']
                    m.notes = ((m.notes + '\n') if m.notes else '') + f'تبدیل به ورکشاپ #{session.id}'
                    if row['refund'] > 0:
                        m.is_refunded = True
                        m.refund_amount = row['refund']
                        m.refund_date = now
                        m.refund_reference = reference
                        m.refund_note = note or f'استرداد بابت تبدیل به ورکشاپ #{session.id}'
                        m.refund_recorded_by = request.user
                        fields += ['is_refunded', 'refund_amount', 'refund_date', 'refund_reference', 'refund_note', 'refund_recorded_by']
                    m.save(update_fields=fields)  # update_fields مانع بازحساب قیمت می‌شود
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'preview': False, 'message': 'کلاس به ورکشاپ تبدیل شد و افراد هم در فهرست کلاس‌های خصوصی ثبت شدند', 'group_session_id': session.id, 'parallel_class_request_ids': parallel_class_request_ids, **summary}, status=status.HTTP_201_CREATED)


class ConvertWorkshopToRequestsView(APIView):
    """POST: {session_id, target_type: 'private'|'makeup', payments: {<participant_id>: {payment_status, payment_method, payment_reference, payment_confirmed_at}}}"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _can_convert(request.user):
            return Response({'error': 'فقط مدیر یا کارشناس اداری می‌تواند نوع کلاس را تغییر دهد'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data
        target = data.get('target_type')
        if target not in ('private', 'makeup'):
            return Response({'error': 'نوع مقصد باید خصوصی یا جبرانی باشد'}, status=status.HTTP_400_BAD_REQUEST)
        payments = data.get('payments') or {}
        keep_workshop = data.get('keep_workshop') in (True, 'true', '1', 1)
        show_as_workshop_blue = data.get('show_as_workshop_blue') in (True, 'true', '1', 1)
        try:
            with transaction.atomic():
                session = GroupSession.objects.select_for_update().get(pk=data.get('session_id'))
                if session.session_type != GroupSession.SessionType.WORKSHOP:
                    return Response({'error': 'فقط ورکشاپ قابل تبدیل به کلاس خصوصی/جبرانی است'}, status=status.HTTP_400_BAD_REQUEST)
                if session.status in (GroupSession.Status.COMPLETED, GroupSession.Status.CANCELLED, GroupSession.Status.REJECTED) or session.is_completed:
                    return Response({'error': 'ورکشاپ مختومه یا کنسل‌شده قابل تبدیل نیست'}, status=status.HTTP_400_BAD_REQUEST)
                participants = list(session.participants.select_related('student'))
                if not participants:
                    return Response({'error': 'این ورکشاپ هیچ شرکت‌کننده‌ای ندارد'}, status=status.HTTP_400_BAD_REQUEST)
                if target == 'private':
                    missing = [f'{p.student.first_name} {p.student.last_name}' for p in participants
                               if (payments.get(str(p.id)) or {}).get('payment_status') not in ('paid', 'unpaid')]
                    if missing:
                        return Response({'error': 'وضعیت پرداخت این افراد مشخص نشده است: ' + '، '.join(missing)}, status=status.HTTP_400_BAD_REQUEST)
                target_price = _private_destination_price(len(participants), session.session_duration, session.session_count) if target == 'private' else 0
                financial_rows = []
                for participant in participants:
                    source_price = max(int(participant.price_amount or 0), 0)
                    source_paid = source_price if participant.payment_status == GroupSessionParticipant.PaymentStatus.PAID else 0
                    applied_credit = source_paid if not keep_workshop else 0
                    pay = payments.get(str(participant.id)) or {}
                    due_before_new_payment = max(target_price - applied_credit, 0)
                    additional_payment = due_before_new_payment if target == 'private' and pay.get('payment_status') == 'paid' else 0
                    refund = max(source_paid - target_price, 0) if not keep_workshop else 0
                    due = max(target_price - applied_credit - additional_payment, 0) if not keep_workshop else max(target_price - additional_payment, 0)
                    settlement_status = 'creditor' if refund else 'debtor' if due else 'settled'
                    financial_rows.append({
                        'participant_id': participant.id,
                        'name': f'{participant.student.first_name} {participant.student.last_name}'.strip() or participant.student.username,
                        'source_price': source_price, 'source_paid': source_paid,
                        'destination_price': target_price, 'credit_applied': applied_credit,
                        'additional_payment': additional_payment, 'refund': refund, 'due': due,
                        'settlement_status': settlement_status,
                        'payment_status': 'paid' if due == 0 else 'unpaid',
                    })
                financial_summary = {
                    'members': financial_rows,
                    'source_price_total': sum(row['source_price'] for row in financial_rows),
                    'source_paid_total': sum(row['source_paid'] for row in financial_rows),
                    'destination_price_total': sum(row['destination_price'] for row in financial_rows),
                    'refund_total': sum(row['refund'] for row in financial_rows),
                    'due_total': sum(row['due'] for row in financial_rows),
                    'debtor_count': sum(1 for row in financial_rows if row['due'] > 0),
                    'creditor_count': sum(1 for row in financial_rows if row['refund'] > 0),
                    'settled_count': sum(1 for row in financial_rows if row['settlement_status'] == 'settled'),
                }
                if data.get('preview') in (True, 'true', '1', 1):
                    return Response({'preview': True, **financial_summary})
                if target == 'private' and not keep_workshop:
                    for participant, row in zip(participants, financial_rows):
                        pay = payments.get(str(participant.id)) or {}
                        if pay.get('payment_status') == 'paid' and row['additional_payment'] > 0 and not (pay.get('payment_method') and pay.get('payment_confirmed_at')):
                            return Response({'error': f'برای دریافت مانده از {participant.student.first_name} {participant.student.last_name} روش و تاریخ پرداخت را کامل کنید'}, status=status.HTTP_400_BAD_REQUEST)
                marker = f'ثبت موازی از ورکشاپ #{session.id}'
                if keep_workshop and ClassRequest.objects.filter(notes__contains=marker).exists():
                    return Response({'error': 'این ورکشاپ قبلاً در فهرست کلاس‌های خصوصی ثبت شده است'}, status=status.HTTP_400_BAD_REQUEST)
                group_key = f'multi-{uuid.uuid4().hex[:12]}' if len(participants) > 1 else ''
                req_status = {
                    GroupSession.Status.CONFIRMED: ClassRequest.Status.CONFIRMED,
                    GroupSession.Status.ASSIGNING: ClassRequest.Status.REFERRED,
                }.get(session.status, ClassRequest.Status.PENDING)
                assigned = list(session.assigned_teachers.all())
                accepted = list(session.accepted_teachers.all())
                created = []
                for p in participants:
                    kwargs = dict(
                        student=p.student, class_type=target, group_key=group_key, group_size=len(participants),
                        is_online=session.is_online, meeting_link=session.meeting_link, language_level=session.language_level,
                        class_date=session.class_date, session_duration=session.session_duration, session_count=session.session_count,
                        teacher=session.teacher, status=req_status,
                        notes=(f'{marker}' + (' [workshop-blue]' if show_as_workshop_blue else '') + (' [workshop-free]' if show_as_workshop_blue and int(session.price_per_person or 0) == 0 else '') + (f' — {session.notes}' if session.notes else '')) if keep_workshop else (f'تبدیل‌شده از ورکشاپ #{session.id}' + (f' — {session.notes}' if session.notes else '')),
                    )
                    if target == 'private':
                        pay = payments.get(str(p.id)) or {}
                        financial_row = next(row for row in financial_rows if row['participant_id'] == p.id)
                        kwargs['payment_status'] = pay['payment_status'] if keep_workshop else financial_row['payment_status']
                        if kwargs['payment_status'] == 'paid':
                            kwargs['payment_method'] = pay.get('payment_method', '')
                            kwargs['payment_reference'] = str(pay.get('payment_reference') or '')[:100]
                            confirmed_at = parse_datetime(str(pay.get('payment_confirmed_at') or ''))
                            if confirmed_at:
                                kwargs['payment_confirmed_at'] = confirmed_at
                    cr = ClassRequest.objects.create(**kwargs)  # قیمت خصوصی در model.save حساب می‌شود
                    financial_row = next(row for row in financial_rows if row['participant_id'] == p.id)
                    if financial_row['refund'] > 0:
                        cr.is_refunded = True
                        cr.refund_amount = financial_row['refund']
                        cr.refund_date = timezone.now()
                        cr.refund_note = f'استرداد بابت تبدیل ورکشاپ #{session.id} به کلاس'
                        cr.refund_recorded_by = request.user
                        cr.save(update_fields=['is_refunded', 'refund_amount', 'refund_date', 'refund_note', 'refund_recorded_by', 'updated_at'])
                    cr.assigned_teachers.set(assigned)
                    cr.accepted_teachers.set(accepted)
                    created.append(cr.id)
                if not keep_workshop:
                    session.status = GroupSession.Status.CANCELLED
                    session.notes = ((session.notes + '\n') if session.notes else '') + f'به کلاس {"خصوصی" if target == 'private' else 'جبرانی'} تبدیل شد'
                    session.save(update_fields=['status', 'notes', 'updated_at'])
        except GroupSession.DoesNotExist:
            return Response({'error': 'ورکشاپ پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'message': 'کلاس خصوصی از ورکشاپ ثبت شد' if keep_workshop else 'ورکشاپ تبدیل شد', 'class_request_ids': created, 'group_key': group_key, 'workshop_kept': keep_workshop, **financial_summary}, status=status.HTTP_201_CREATED)
