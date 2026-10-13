"""
لایه‌ی داده‌ی سیستم امتیاز استادها: از دیتابیس «واقعیت‌های هر استاد در هر ترم» را جمع می‌کند،
با scoring.py امتیاز می‌دهد و رتبه‌بندی نهایی را می‌سازد.

نکته: ClassSlot رابطه‌ی FK به استاد ندارد و استاد با نام کامل (teacher_name) ثبت می‌شود؛
پس تطبیق با «نام نرمال‌شده» (یکسان‌سازی ی/ک عربی، نیم‌فاصله، فاصله‌ی اضافه) انجام می‌شود.

محاسبه همیشه «زنده» انجام می‌شود (هیچ امتیازی ذخیره نمی‌شود) تا اولویت‌ها همیشه با آخرین
داده‌ی ترم/غیبت/کلاس‌ها هم‌خوان باشند.
"""
import re
from collections import defaultdict
from datetime import datetime, time

from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import ClassRequest
from class_management.models import ClassSlot, ClassSlotEnrollment, Term, TeacherSessionEvent, TeacherCompensationSetting

from .models import TeacherPriorityConfig
from .scoring import TermFacts, compute_term_score, price_factor, usage_penalty

_TRANS = str.maketrans({'ي': 'ی', 'ك': 'ک', '‌': ' ', '‏': '', '‎': ''})


def normalize_name(value):
    s = str(value or '').translate(_TRANS)
    return re.sub(r'\s+', ' ', s).strip().casefold()


def _name_keys(user):
    first, last = normalize_name(user.first_name), normalize_name(user.last_name)
    return {normalize_name(f'{first} {last}'), normalize_name(f'{last} {first}')} - {''}


def _private_usage(teacher_ids, since):
    """
    جلسه‌های خصوصی/جبرانی که از شروع آخرین ترم به هر استاد «تخصیص نهایی» شده‌اند.
    - فقط وضعیت تایید نهایی/مختومه؛ جلسه‌های کنسل‌شده شمرده نمی‌شوند.
    - کلاس خصوصیِ چندنفره (group_key یکسان) فقط یک‌بار شمرده می‌شود.
    """
    qs = ClassRequest.objects.filter(
        teacher_id__in=teacher_ids,
        class_type__in=[ClassRequest.ClassType.PRIVATE, ClassRequest.ClassType.MAKEUP],
        status__in=[ClassRequest.Status.CONFIRMED, ClassRequest.Status.COMPLETED],
    )
    usage = defaultdict(lambda: {'private': 0, 'makeup': 0, 'items': []})
    seen_groups = set()
    for c in qs.order_by('id'):
        stamp = c.teacher_assigned_at or c.created_at
        if since and stamp and stamp < since:
            continue
        if c.group_key:
            gk = (c.teacher_id, c.group_key)
            if gk in seen_groups:
                continue
            seen_groups.add(gk)
        sessions = c.active_session_count
        kind = 'makeup' if c.class_type == ClassRequest.ClassType.MAKEUP else 'private'
        usage[c.teacher_id][kind] += sessions
        usage[c.teacher_id]['items'].append({
            'class_id': c.id, 'kind': kind, 'sessions': sessions,
            'level': c.language_level, 'assigned_at': stamp.isoformat() if stamp else None,
        })
    return usage


def build_ranking(include_history=True, term_id=None):
    cfg_obj = TeacherPriorityConfig.get()
    cfg = cfg_obj.scoring_config()
    User = get_user_model()
    # پیش‌فرض فقط از تاریخ واقعی شروع ترم و تاریخ محلی تهران ساخته می‌شود؛
    # ترتیب سال/شماره یا تاریخ پایان هرگز نمی‌تواند ترم آینده را جاری جلو بیندازد.
    today = timezone.localdate()
    terms = list(Term.objects.filter(start_date__isnull=False).order_by('-start_date', '-id'))
    started_terms = [term for term in terms if term.start_date <= today]
    current_term = started_terms[0] if started_terms else (terms[-1] if terms else None)
    if term_id not in (None, ''):
        try:
            requested_id = int(term_id)
        except (TypeError, ValueError):
            requested_id = None
        selected_term = next((term for term in terms if term.id == requested_id), None) or current_term
    else:
        selected_term = current_term

    teachers = list(User.objects.filter(role__in=User.TEACHER_LIKE_ROLES, is_active=True)
                    .order_by('last_name', 'first_name'))
    key_to_teacher = {}
    for t in teachers:
        for k in _name_keys(t):
            key_to_teacher.setdefault(k, t.id)

    # ---- کلاس‌های ترمی هر استاد در هر ترم
    facts = defaultdict(TermFacts)      # (teacher_id, term_id) -> facts
    slot_owner = {}                     # slot_id -> (teacher_id, term_id)
    for s in ClassSlot.objects.exclude(teacher_name='').filter(term__isnull=False).only('id', 'term_id', 'teacher_name', 'day_type'):
        tid = key_to_teacher.get(normalize_name(s.teacher_name))
        if not tid:
            continue
        facts[(tid, s.term_id)].day_types.append(s.day_type)
        slot_owner[s.id] = (tid, s.term_id)

    # ---- دانش‌آموزانِ یکتا (فقط ثبت‌نام‌های تاییدشده)
    students = defaultdict(set)
    for slot_id, student_id in ClassSlotEnrollment.objects.filter(
            class_slot_id__in=list(slot_owner), payment_verified=True).values_list('class_slot_id', 'student_id'):
        students[slot_owner[slot_id]].add(student_id)
    for key, ids in students.items():
        facts[key].student_count = len(ids)

    # ---- غیبت‌های تاییدشده
    for term_id, name in TeacherSessionEvent.objects.filter(
            event_type=TeacherSessionEvent.EventType.ABSENCE,
            status=TeacherSessionEvent.ApprovalStatus.APPROVED,
    ).values_list('term_id', 'requested_teacher_name'):
        tid = key_to_teacher.get(normalize_name(name))
        if tid:
            facts[(tid, term_id)].absence_count += 1

    # ---- کسر بابت کلاس‌های خصوصی/جبرانی (از شروع ترم انتخاب‌شده)
    since = None
    if selected_term and selected_term.start_date:
        since = timezone.make_aware(datetime.combine(selected_term.start_date, time.min))
    usage = _private_usage([t.id for t in teachers], since)
    comp_by_teacher = {s.teacher_id: s for s in TeacherCompensationSetting.objects.all()}

    rows = []
    for t in teachers:
        history = []
        for term in terms:
            f = facts.get((t.id, term.id))
            res = compute_term_score(f or TermFacts(), cfg)
            history.append({
                'term_id': term.id, 'term_title': term.title,
                'is_selected': bool(selected_term and term.id == selected_term.id),
                'has_data': f is not None, **res,
            })
        selected_entry = next((h for h in history if selected_term and h['term_id'] == selected_term.id), None)
        latest_entry = selected_entry or {
            'term_id': None, 'term_title': '—', 'has_data': False,
            **compute_term_score(TermFacts(), cfg),
        }
        u = usage.get(t.id, {'private': 0, 'makeup': 0, 'items': []})
        pen = usage_penalty(u['private'], u['makeup'],
                            float(cfg_obj.private_session_penalty), float(cfg_obj.makeup_session_penalty))
        pen['items'] = u['items']
        priority = max(0.0, round(latest_entry['score'] - pen['points'], 2))

        if t.role != 'teacher' and not (any(h['has_data'] for h in history) or u['items']):
            continue  # مدیر آموزشی که تدریس نمی‌کند در صف نمی‌آید

        factor = price_factor(priority, float(cfg_obj.price_coefficient), cfg_obj.apply_to_hourly_price)
        comp = comp_by_teacher.get(t.id)
        base_price = comp.session_price if comp else 0
        rows.append({
            'teacher_id': t.id, 'teacher_name': f'{t.first_name} {t.last_name}'.strip(),
            'phone': t.phone, 'role': t.role,
            'term_score': latest_entry['score'], 'term_id': latest_entry['term_id'],
            'term_title': latest_entry['term_title'], 'criteria': latest_entry['criteria'],
            'facts': latest_entry['facts'],
            'usage_penalty': pen, 'priority_score': priority,
            'price_factor': factor, 'base_session_price': base_price,
            'effective_session_price': round(base_price * factor),
            'terms': history if include_history else [],
        })

    # مرتب‌سازی: امتیاز اولویت ↓، سپس امتیاز ترم ↓، سپس کسر کمتر، سپس نام
    rows.sort(key=lambda r: (-r['priority_score'], -r['term_score'], r['usage_penalty']['points'], r['teacher_name']))
    for i, r in enumerate(rows, 1):
        r['rank'] = i
    def term_payload(term):
        if not term:
            return None
        return {
            'id': term.id,
            'title': term.title,
            'start_date': term.start_date.isoformat() if term.start_date else None,
            'start_date_jalali': term.start_date_jalali,
            'is_started': bool(term.start_date and term.start_date <= today),
        }
    return {
        'config': cfg_obj.payload(),
        # latest_term برای سازگاری با مصرف‌کننده‌های قبلی، ترم انتخاب‌شده است.
        'latest_term': term_payload(selected_term),
        'selected_term': term_payload(selected_term),
        'current_term': term_payload(current_term),
        'as_of_date': today.isoformat(),
        'terms': [term_payload(term) for term in terms],
        'teachers': rows,
    }


def pay_factor_map():
    """{teacher_id: ضریب} — فقط وقتی تیک «اثر روی قیمت» روشن است؛ در غیر این صورت {} (هیچ تغییری در دستمزد)."""
    cfg = TeacherPriorityConfig.get()
    if not cfg.apply_to_hourly_price:
        return {}
    return {r['teacher_id']: r['price_factor'] for r in build_ranking(include_history=False)['teachers']}
