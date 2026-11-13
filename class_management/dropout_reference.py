"""منبع مرجعِ بایگانی ریزشی به‌ازای ترم و وضعیت ثبت‌نام زندهٔ افراد آن."""
from .models import DropoutExtractList, DropoutExtractReference, Term


def reference_anchor_term():
    """اولین ترم شمارهٔ ۶ با ترتیب تحصیلی؛ نقطهٔ شروع الزام انتخاب مرجع برای ترم‌های بعدی."""
    return Term.objects.filter(term_number=6).order_by('year', 'term_number', 'id').first()


def reference_is_required(term):
    anchor = reference_anchor_term()
    return bool(term and anchor and (term.year, term.term_number, term.id) >= (anchor.year, anchor.term_number, anchor.id))


def reference_is_anchor(term):
    anchor = reference_anchor_term()
    return bool(term and anchor and term.pk == anchor.pk)


def get_dropout_reference(term=None, auto_select=True):
    """یک آرشیو یکتا برای کل سامانه؛ اگر هنوز انتخاب نشده، آرشیو واجد شرایط ترم مبنا را می‌گیرد."""
    ref_qs = DropoutExtractReference.objects.select_related('saved_list', 'term').filter(scope='global').order_by('pk')
    anchor = reference_anchor_term()
    ref = ref_qs.first()
    if ref or not auto_select or not anchor:
        return ref
    candidates = []
    for item in DropoutExtractList.objects.filter(term=anchor).order_by('-created_at', '-id'):
        meta = item.meta if isinstance(item.meta, dict) else {}
        source = meta.get('a_source') or (meta.get('a') or {}).get('source')
        target = meta.get('term2_id') or (meta.get('term2') or {}).get('id') or item.term_id
        if item.mode != 'carryover' and str(source or '').lower() == 'excel' and str(target) == str(anchor.pk) and item.rows:
            candidates.append(item)
    # اگر بیش از یک آرشیو واجد شرایط باشد، انتخاب خودکار می‌تواند دادهٔ اشتباه را مرجع کند.
    if len(candidates) != 1:
        return None
    ref, _ = DropoutExtractReference.objects.get_or_create(term=anchor, defaults={'saved_list': candidates[0]})
    return DropoutExtractReference.objects.select_related('saved_list', 'term').get(pk=ref.pk)


def reference_rows(saved, term=None):
    """ردیف‌های یکتای آرشیو با وضعیت زنده در ترم مورد گزارش (پیش‌فرض: ترم خود آرشیو)."""
    target_term_id = getattr(term, 'pk', None) or getattr(term, 'id', None) or saved.term_id
    if target_term_id == saved.term_id:
        from .carryover import list_registration_status
        statuses = list_registration_status(saved)
    else:
        statuses = {}
    raw_rows = [dict(row) for row in (saved.rows or []) if isinstance(row, dict)]
    merged = {}
    for row in raw_rows:
        raw = str(row.get('national_code') or row.get('key') or '')
        table = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
        code = ''.join(ch for ch in raw.translate(table) if ch.isdigit())
        # لیست مرجع فقط با کد ملی ده‌رقمی قابل اتکاست؛ دادهٔ فاقد کد معتبر نباید بی‌صدا در جمع وارد شود.
        if len(code) != 10:
            continue
        key = f'nc:{code}'
        if key not in merged:
            merged[key] = row
        else:
            for field, value in row.items():
                if merged[key].get(field) in (None, '') and value not in (None, ''):
                    merged[key][field] = value
    from django.contrib.auth import get_user_model
    from .models import ClassSlotEnrollment
    codes = {identity[3:] for identity in merged}
    code_to_student, status_by_code, status_rank = {}, {}, {}
    for code, student_id in get_user_model().objects.filter(role='student', national_code__in=codes).values_list('national_code', 'id'):
        code_to_student.setdefault(code, student_id)
    enrollments = ClassSlotEnrollment.objects.filter(
        class_slot__term_id=target_term_id, student__national_code__in=codes, student__role='student',
    ).order_by('-payment_verified', '-created_at').values_list(
        'student__national_code', 'student_id', 'payment_verified', 'is_carryover', 'carryover_confirmed',
    )
    for code, student_id, verified, is_carryover, carryover_confirmed in enrollments:
        if verified and (not is_carryover or carryover_confirmed):
            label, rank = 'ثبت‌نام قطعی شد', 3
        elif not is_carryover:
            label, rank = 'در انتظار تأیید پرداخت', 2
        else:
            label, rank = 'منتظر ثبت‌نام', 1
        if rank > status_rank.get(code, 0):
            status_by_code[code] = label
            status_rank[code] = rank
            code_to_student[code] = student_id
    result = []
    for identity, row in merged.items():
        code = identity[3:]
        saved_key = str(row.get('key') or code)
        state = status_by_code.get(code) or statuses.get(saved_key) or statuses.get(code) or ''
        if code in code_to_student:
            row['student_id'] = code_to_student[code]
        row.update({
            'key': code, 'national_code': code, 'reg_status': state,
            'is_confirmed': state == 'ثبت‌نام قطعی شد', 'has_enrollment': bool(state),
            'payment_verified': state == 'ثبت‌نام قطعی شد',
            'is_carryover': state == 'منتظر ثبت‌نام', 'carryover_confirmed': False,
            'sources': ['آرشیو مرجع ریزشی'], 'sources_text': 'آرشیو مرجع ریزشی',
            'student_name': ' '.join((row.get('first_name') or '', row.get('last_name') or '')).strip(),
            'day_type': row.get('day_type') or row.get('day') or '',
            'time': row.get('time') or row.get('time_slot') or '',
            'teacher': row.get('teacher') or '', 'has_class': bool(row.get('slot_id')),
            'level': row.get('level') or '—',
        })
        result.append(row)
    return result
