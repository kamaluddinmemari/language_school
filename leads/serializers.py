from rest_framework import serializers
from .models import NewLead, NewLeadFollowup, UnregisteredStudent, UnregisteredStudentFollowup, Debtor, DebtorFollowup, DiscountedPerson, normalize_national_code, normalize_phone


def current_unregistered_tuition(item, tariff_cache=None):
    """تعرفهٔ فعلیِ سطح را برمی‌گرداند؛ در نبود تعرفه، مبلغ ثبت‌شدهٔ فرد ملاک است."""
    level = getattr(item, 'latest_level', None) or getattr(item, 'class_level', '')
    if level:
        try:
            if tariff_cache is not None and level in tariff_cache:
                current_amount = tariff_cache[level]
            else:
                from class_management.carryover import _tuition_for_level
                current_amount = int(_tuition_for_level(level) or 0)
                if tariff_cache is not None:
                    tariff_cache[level] = current_amount
            if current_amount > 0:
                return current_amount
        except Exception:
            pass
    return item.tuition_price


class NewLeadFollowupSerializer(serializers.ModelSerializer):
    followed_up_at_jalali = serializers.ReadOnlyField()
    followed_up_by_name = serializers.SerializerMethodField()

    class Meta:
        model = NewLeadFollowup
        fields = ['id', 'followed_up_at', 'followed_up_at_jalali', 'followed_up_by_name']

    def get_followed_up_by_name(self, obj):
        return obj.followed_up_by.get_full_name() if obj.followed_up_by else None


class NewLeadSerializer(serializers.ModelSerializer):
    followups = NewLeadFollowupSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    followup1_at_jalali = serializers.ReadOnlyField()
    followup2_at_jalali = serializers.ReadOnlyField()
    registered_at_jalali = serializers.ReadOnlyField()
    cancelled_at_jalali = serializers.ReadOnlyField()
    followup1_by_name = serializers.SerializerMethodField()
    followup2_by_name = serializers.SerializerMethodField()
    birth_date_jalali = serializers.ReadOnlyField()
    needs_level_test_marked_at_jalali = serializers.ReadOnlyField()
    age = serializers.ReadOnlyField()
    level_test = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    registered_class = serializers.SerializerMethodField()

    def get_registered_class(self, obj):
        """کلاس مقصدِ ثبت‌نام قطعی (فقط برای «ثبت‌نام شد»ها؛ از نگاشت پیش‌محاسبه‌شدهٔ ویوی لیست)."""
        return (self.context.get('registered_class_map') or {}).get(obj.id)

    def get_assigned_to_name(self, obj):
        u = obj.assigned_to
        return (f'{u.first_name} {u.last_name}'.strip() or u.username) if u else None

    def get_followup1_by_name(self, obj):
        return obj.followup1_by.get_full_name() if obj.followup1_by else None

    def get_followup2_by_name(self, obj):
        return obj.followup2_by.get_full_name() if obj.followup2_by else None

    def get_level_test(self, obj):
        """
        اولویت با آزمونی است که مستقیماً از طریق تیک «نیاز به تعیین سطح دارد» برای همین
        سرنخ ساخته شده (obj.level_test). اگر چنین چیزی نبود (سرنخ‌های قدیمی‌تر یا کسی که
        خودش جدا از این‌جا در صف تعیین سطح ثبت شده)، بر اساس کد ملی و در نبود آن شماره
        موبایل (هر دو پس از نرمال‌سازی) به‌صورت حدسی تطبیق داده می‌شود.
        رنگ: pending → زرد، completed+paid → سبز، completed+unpaid → قرمز.
        """
        from level_tests.models import LevelTest
        match = obj.level_test
        if not match:
            national = normalize_national_code(obj.national_code)
            phone = normalize_phone(obj.phone)
            by_national = self.context.get('level_test_by_national')
            by_phone = self.context.get('level_test_by_phone')
            if by_national is not None or by_phone is not None:
                candidates = by_national.get(national, []) if national else []
                if not candidates and phone:
                    candidates = by_phone.get(phone, [])
            else:
                all_tests = list(LevelTest.objects.all())
                candidates = [t for t in all_tests if national and normalize_national_code(t.national_code) == national]
                if not candidates and phone:
                    candidates = [t for t in all_tests if normalize_phone(t.phone) == phone]
            if not candidates:
                return None
            match = sorted(candidates, key=lambda t: (t.status == LevelTest.Status.COMPLETED, t.id))[-1]
        if match.status == LevelTest.Status.COMPLETED:
            badge = 'paid' if match.payment_status == LevelTest.PaymentStatus.PAID else 'unpaid'
        else:
            badge = 'pending'
        return {
            'id': match.id, 'status': match.status, 'status_display': match.get_status_display(),
            'payment_status': match.payment_status, 'level': match.level, 'age_group': match.age_group,
            'age_group_display': match.get_age_group_display() if match.age_group else None,
            'test_date': match.test_date, 'test_date_jalali': match.test_date_jalali,
            'badge': badge,
        }

    class Meta:
        model = NewLead
        fields = [
            'id', 'first_name', 'last_name', 'father_name', 'national_code', 'birth_date', 'birth_date_jalali', 'age', 'phone',
            'requested_level', 'gender', 'assigned_to', 'assigned_to_name',
            'status', 'status_display', 'term', 'term_title',
            'followup1_at', 'followup1_at_jalali', 'followup1_by_name',
            'followup2_at', 'followup2_at_jalali', 'followup2_by_name',
            'registered_at', 'registered_at_jalali', 'cancelled_at', 'cancelled_at_jalali', 'no_response',
            'deposit_amount', 'deposit_paid_at', 'deposit_paid_at_jalali', 'registered_class',
            'description', 'followups',
            'needs_level_test', 'needs_level_test_marked_at', 'needs_level_test_marked_at_jalali',
            'created_at', 'created_at_jalali', 'updated_at', 'level_test',
        ]
        read_only_fields = [
            'status', 'term_title', 'followup1_at', 'followup2_at', 'registered_at', 'cancelled_at',
            'deposit_paid_at', 'created_at', 'updated_at',
            'needs_level_test', 'needs_level_test_marked_at',
        ]


class UnregisteredFollowupSerializer(serializers.ModelSerializer):
    followed_up_at_jalali = serializers.ReadOnlyField()
    followed_up_by_name = serializers.SerializerMethodField()

    class Meta:
        model = UnregisteredStudentFollowup
        fields = ['id', 'followed_up_at', 'followed_up_at_jalali', 'followed_up_by_name', 'note']

    def get_followed_up_by_name(self, obj):
        if not obj.followed_up_by:
            return None
        return f"{obj.followed_up_by.first_name} {obj.followed_up_by.last_name}"


def _norm_name(first, last):
    value = f"{first or ''} {last or ''}".replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', ' ')
    return ' '.join(value.split()).casefold()


def _norm_digits(value):
    value = str(value or '').translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))
    return ''.join(ch for ch in value if ch.isdigit())


def _norm_phone(value):
    digits = _norm_digits(value)
    return digits[-10:] if len(digits) >= 10 else digits


def _debt_breakdown(d):
    """بدهی یک رکورد بدهکار را به اقلام ساده (شهریه/کتاب/...) تقسیم می‌کند: [(عنوان, مبلغ)].
    بدهی‌های اضافه‌شده بعدی در description به شکل «[بدهی جدید تاریخ — N تومان] متن» ذخیره شده‌اند."""
    import re
    desc = d.description or ''
    total = int(d.debt_amount or 0)
    def label_of(text):
        t = (text or '').strip()
        for key, name in (('کتاب', 'کتاب'), ('شهریه', 'شهریه'), ('جزوه', 'جزوه'), ('جریمه', 'جریمه')):
            if key in t:
                return name
        t = re.sub(r'^بدهی\s*', '', t).strip()
        return (t[:30] or 'بدهی')
    items = []
    added = 0
    base_lines = []
    for line in desc.split('\n'):
        m = re.match(r'^\[بدهی جدید[^\]]*?(?:—\s*([\d,]+)\s*تومان)?\]\s*(.*)$', line.strip())
        if m:
            amt = int((m.group(1) or '0').replace(',', '') or 0)
            if amt:
                items.append((label_of(m.group(2)), amt))
                added += amt
        elif line.strip():
            base_lines.append(line.strip())
    base_amount = max(0, total - added)
    if base_amount or not items:
        items.insert(0, (label_of(' '.join(base_lines)), base_amount))
    merged = {}
    for name, amt in items:
        merged[name] = merged.get(name, 0) + amt
    return list(merged.items())


class _CrossListIndex:
    """
    فهرست «بازِ» طرف مقابل برای تشخیص فردی که هم بدهکار است و هم ثبت‌نام‌نشده.
    تطبیق با کد ملی، شماره همراه یا نام کامل. فقط یک‌بار برای هر درخواست ساخته می‌شود.
    """
    def __init__(self, kind):
        self.kind = kind
        self.items = []
        if kind == 'debtor':
            from .models import Debtor
            rows = Debtor.objects.filter(status=Debtor.Status.PENDING).select_related('student')
            for d in rows:
                code = getattr(d.student, 'national_code', '') if d.student_id else ''
                self.items.append((_norm_digits(code), _norm_phone(d.phone), _norm_name(d.first_name, d.last_name), d.debt_amount or 0, _debt_breakdown(d),
                                   {'id': d.pk, 'term': d.term_id, 'created': d.created_at.date() if d.created_at else None, 'carried': bool(d.carried_from_term_id)}))
        else:
            from .models import UnregisteredStudent
            rows = UnregisteredStudent.objects.filter(status=UnregisteredStudent.Status.TRACKING)
            for u in rows:
                self.items.append((_norm_digits(u.national_code), _norm_phone(u.phone), _norm_name(u.first_name, u.last_name), u.tuition_price or 0, '', {}))

    def match(self, code, phone, first, last):
        return [amount for amount, _desc, _prev, _id in self.match_items(code, phone, first, last)]

    def match_items(self, code, phone, first, last, ref=None):
        code = _norm_digits(code)
        phone = _norm_phone(phone)
        name = _norm_name(first, last)
        found = []
        for c, p, n, amount, desc, meta in self.items:
            # کد ملیِ هر دو طرف موجود باشد ملاک قطعی است. اگر فقط یک طرف کد دارد،
            # شماره همراه و نام کاملِ مشترک امکان match می‌دهد؛ کدهای متفاوت هرگز با هم یکی نمی‌شوند.
            if code and c:
                # اگر هر دو کد ملی موجودند، فقط برابری دقیق کد ملی معتبر است.
                matched = code == c
            elif code or c:
                # کد ملی فقط در یک سمت هست: تطبیقِ نام به‌تنهایی ممنوع؛
                # شماره همراه و نام کامل هر دو باید برابر باشند.
                matched = bool(phone and p and phone == p and name and n == name)
            elif phone and p:
                # در نبود کد ملی، موبایلِ مشترک به‌علاوهٔ نام کامل ملاک است.
                matched = bool(phone == p and name and n == name)
            elif phone or p:
                # اگر فقط یک سمت شماره دارد، نام یکسان دلیل کافی برای یکی‌گرفتن نیست.
                matched = False
            else:
                # فقط وقتی هر دو فاقد شناسه و شماره‌اند، نام کاملِ یکسان پذیرفته می‌شود.
                matched = bool(name and n == name)
            if matched:
                previous = False
                if ref is not None and meta:
                    ref_term = getattr(ref, 'term_id', None)
                    ref_created = getattr(ref, 'created_at', None)
                    previous = bool(
                        meta.get('carried')
                        or (meta.get('term') and ref_term and meta['term'] != ref_term)
                        or (meta.get('created') and ref_created and meta['created'] < ref_created.date())
                    )
                found.append((amount, desc, previous, (meta or {}).get('id')))
        return found



def _slot_day_text(slot):
    days = slot.schedule_days if isinstance(slot.schedule_days, list) and slot.schedule_days else None
    return '، '.join(str(d) for d in days) if days else slot.get_day_type_display()


def _slot_desc(slot):
    parts = [f'کلاس {slot.number}']
    if slot.assigned_level:
        parts.append(f'سطح {slot.assigned_level}')
    parts.append(f'استاد {slot.teacher_name or "نامشخص"}')
    when = ' '.join(x for x in (_slot_day_text(slot), slot.time_slot) if x)
    parts.append(f'ساعت {when}' if when else 'ساعت نامشخص')
    return '، '.join(parts)


def _norm_level(v):
    return ' '.join(str(v or '').split()).casefold()


def _unregistered_enrollment_q(obj):
    """نتیجه روی خودِ ردیف کش می‌شود تا برای هر ردیف فقط یک‌بار (نه چندبار) کوئری کاربر زده شود."""
    cached = getattr(obj, '_enrollment_q_cache', None)
    if cached is None:
        cached = _compute_unregistered_enrollment_q(obj)
        try:
            obj._enrollment_q_cache = cached
        except AttributeError:
            pass
    return cached


def _compute_unregistered_enrollment_q(obj):
    """برای یک ردیف ثبت‌نام‌نشده، شناسهٔ دانش‌آموز متناظر را بدون ادغام هم‌نام‌ها برمی‌گرداند."""
    from django.db.models import Q
    from accounts.models import User

    national_code = (obj.national_code or '').strip()
    if national_code:
        # کد ملی موجود، معیار قطعی است؛ هرگز با نام یا موبایل به شخص دیگری fallback نکن.
        return Q(student__role='student', student__national_code=national_code)

    students = User.objects.filter(role='student')
    phone = (obj.phone or '').strip()
    if phone:
        students = students.filter(phone=phone, first_name=obj.first_name, last_name=obj.last_name)
    else:
        students = students.filter(first_name=obj.first_name, last_name=obj.last_name)
    student_ids = list(students.values_list('id', flat=True)[:2])
    if len(student_ids) == 1:
        return Q(student_id=student_ids[0])
    # اگر بدون کد ملی تطبیق مبهم است، کلاسی به این ردیف نسبت نده.
    return Q(student_id__in=[])


class _EnrollmentIndex:
    """
    ثبت‌نام‌های کلاسیِ همهٔ ردیف‌های یک لیست را با چند کوئری ثابت می‌خواند (به‌جای چند کوئری برای هر ردیف).
    تطبیق فرد دقیقاً مثل _compute_unregistered_enrollment_q است: کد ملی ← موبایل+نام ← نام؛ تطبیق مبهم = هیچ.
    """
    def __init__(self, objs):
        from accounts.models import User
        self.by_nc, self.by_pfl, self.by_fl = {}, {}, {}
        for u in User.objects.filter(role='student').values('id', 'national_code', 'phone', 'first_name', 'last_name'):
            if u['national_code']:
                self.by_nc.setdefault(u['national_code'], []).append(u['id'])
            self.by_pfl.setdefault((u['phone'], u['first_name'], u['last_name']), []).append(u['id'])
            self.by_fl.setdefault((u['first_name'], u['last_name']), []).append(u['id'])
        self.by_student = {}
        self._load({sid for o in objs for sid in self.student_ids(o)})

    def student_ids(self, obj):
        nc = (obj.national_code or '').strip()
        if nc:
            return list(self.by_nc.get(nc, []))
        phone = (obj.phone or '').strip()
        ids = self.by_pfl.get((phone, obj.first_name, obj.last_name), []) if phone else self.by_fl.get((obj.first_name, obj.last_name), [])
        return list(ids) if len(ids) == 1 else []

    def _load(self, ids):
        from class_management.models import ClassSlotEnrollment
        ids = {i for i in ids if i not in self.by_student}
        for i in ids:
            self.by_student[i] = []
        if not ids:
            return
        for e in ClassSlotEnrollment.objects.filter(student_id__in=ids).select_related('class_slot').order_by('-created_at', '-id'):
            self.by_student[e.student_id].append(e)

    def enrollments(self, obj):
        ids = self.student_ids(obj)
        self._load(ids)
        rows = [e for i in ids for e in self.by_student.get(i, [])]
        rows.sort(key=lambda e: (e.created_at, e.id), reverse=True)
        return rows


def _unconfirmed_carryover(e):
    return bool(e.is_carryover and not e.carryover_confirmed)


def _has_current_misplaced_enrollment(obj, index=None):
    if not obj.is_misplaced or not obj.misplaced_from_slot_id:
        return False
    if index is not None:
        return any(e.class_slot_id == obj.misplaced_from_slot_id for e in index.enrollments(obj))
    from class_management.models import ClassSlotEnrollment
    return ClassSlotEnrollment.objects.filter(
        _unregistered_enrollment_q(obj), class_slot_id=obj.misplaced_from_slot_id,
    ).exists()


def _class_status_text(slot, misplaced):
    """متن دقیق: «به درستی / به اشتباه در کلاس فلان، استاد فلان، ساعت فلان»."""
    if not slot:
        return 'هنوز شهریه ترم را نداده و در سیستم در هیچ کلاسی ثبت نشده'
    return ('به اشتباه' if misplaced else 'به درستی') + ' در ' + _slot_desc(slot)


def _fa_key(v):
    return ''.join(str(v or '').replace('ي', 'ی').replace('ك', 'ک').split()).casefold()


def reported_candidates(u):
    """
    کلاس‌هایی که اپ/استاد برای این فرد ثبت کرده:
    - اگر کلاس دقیق ذخیره شده → همان.
    - رکوردهای قدیمی (بدون کلاس ذخیره‌شده): از روی استادِ ثبت‌کننده + سطح + جنسیت + ترم حدس زده می‌شود.
    خروجی: (slot_or_None, candidates_list, exact)
    """
    if u.reported_slot_id:
        return u.reported_slot, [u.reported_slot], True
    if not (u.submitted_by_id and u.term_id and u.class_level):
        return None, [], False
    from class_management.models import ClassSlot
    sub = u.submitted_by
    names = {_fa_key(f'{sub.first_name} {sub.last_name}'), _fa_key(f'{sub.last_name} {sub.first_name}')}
    names.discard('')
    if not names:
        return None, [], False
    slots = ClassSlot.objects.filter(term_id=u.term_id, assigned_level=u.class_level)
    cands = [s for s in slots if _fa_key(s.teacher_name) in names]
    if u.gender:
        want = {'female': 'girls', 'male': 'boys'}.get(u.gender)
        cands = [s for s in cands if s.gender in (want, 'mixed')] or cands
    cands.sort(key=lambda s: (s.number or 0))
    if len(cands) == 1:
        return cands[0], cands, False
    return None, cands[:4], False


def _classify_class(system_slot, reported_slot, reported_level, flagged=False, candidates=None, exact=True):
    """
    منبع «درست» = اطلاعاتی که استاد/اپ ثبت کرده (کلاس یا سطح گزارش‌شده)، نه لیست ثبت‌نام سیستم.
    اگر ثبت‌نام سیستم با آن فرق کند، ثبت‌نام سیستم «اشتباه» است.
    خروجی: (status, system_text, true_text)
    """
    if reported_slot:
        true_text = 'کلاس و سطح اصلی و درست (طبق ثبت اپ/استاد): ' + _slot_desc(reported_slot) + ('' if exact else ' (تشخیص از روی استاد ثبت‌کننده و سطح)')
    elif reported_level and candidates:
        true_text = f'سطح اصلی و درست (طبق ثبت اپ/استاد): {reported_level} — کلاس‌های محتمل: ' + ' | '.join(_slot_desc(c) for c in candidates)
    elif reported_level:
        true_text = f'سطح اصلی و درست (طبق ثبت اپ/استاد): {reported_level}'
    else:
        true_text = ''
    if not system_slot:
        return 'none', 'هنوز شهریه ترم را نداده و در سیستم در هیچ کلاسی ثبت نشده', true_text
    mismatch = bool(flagged)
    if reported_slot and reported_slot.pk != system_slot.pk:
        mismatch = True
    elif not reported_slot and reported_level and _norm_level(reported_level) != _norm_level(system_slot.assigned_level):
        mismatch = True
    if mismatch:
        return 'misplaced', 'در سیستم به اشتباه در ' + _slot_desc(system_slot) + ' ثبت شده — باید اصلاح شود', true_text
    return 'correct', 'در سیستم به درستی در ' + _slot_desc(system_slot) + ' ثبت شده', true_text


class UnregisteredStudentSerializer(serializers.ModelSerializer):
    current_tuition = serializers.SerializerMethodField()
    has_current_class = serializers.SerializerMethodField()
    is_misplaced = serializers.SerializerMethodField()

    def _enr_index(self):
        """ایندکس ثبت‌نام‌ها برای کل لیست (یک‌بار برای هر درخواست)."""
        idx = self.__dict__.get('_enr_index_cache')
        if idx is None:
            parent = getattr(self, 'parent', None)
            if parent is not None and getattr(parent, 'many', False) and parent.instance is not None:
                objs = list(parent.instance)
            else:
                objs = [self.instance] if isinstance(self.instance, UnregisteredStudent) else []
            idx = _EnrollmentIndex(objs)
            self.__dict__['_enr_index_cache'] = idx
        return idx

    def _misplaced_now(self, obj):
        return _has_current_misplaced_enrollment(obj, self._enr_index())

    def get_is_misplaced(self, obj):
        return self._misplaced_now(obj)

    def get_current_tuition(self, obj):
        cache = self.__dict__.setdefault('_current_tuition_tariffs', {})
        return current_unregistered_tuition(obj, cache)

    def get_has_current_class(self, obj):
        if obj.status == 'registered':
            return False
        return any(
            e.class_slot.term_id == obj.term_id and not _unconfirmed_carryover(e)
            for e in self._enr_index().enrollments(obj)
        )
    # خواسته: برای هر فرد ثبت‌نام‌نشده، مشخصات کلاس فعلی‌اش (شماره، سطح، روز/ساعت، استاد) هم نمایش داده شود.
    class_slot = serializers.SerializerMethodField()
    class_slot_number = serializers.SerializerMethodField()
    class_slot_level = serializers.SerializerMethodField()
    class_slot_day = serializers.SerializerMethodField()
    class_slot_time = serializers.SerializerMethodField()
    class_slot_teacher = serializers.SerializerMethodField()
    class_status = serializers.SerializerMethodField()
    class_status_text = serializers.SerializerMethodField()
    class_true_text = serializers.SerializerMethodField()

    def _system_slot(self, obj):
        enrollments = self._enr_index().enrollments(obj)
        if obj.misplaced_from_slot_id:
            # تیک «به اشتباه ثبت شده»: اگر اسمش هنوز در همان کلاس است، همان کلاس اشتباه است
            if any(e.class_slot_id == obj.misplaced_from_slot_id for e in enrollments):
                return obj.misplaced_from_slot
            # از آن کلاس خارج شده (اصلاح شده)؛ ثبت‌نام فعلی‌اش در همان ترم ملاک است
        if not obj.term_id:
            return None
        found = next((e for e in enrollments if e.class_slot.term_id == obj.term_id and not _unconfirmed_carryover(e)), None)
        return found.class_slot if found else None

    def _class_state(self, obj):
        cache = self.__dict__.setdefault('_cstate_cache', {})
        if obj.pk not in cache:
            # برای «جابجا شود»: سیستم همان کلاس لیست است (اشتباه)؛ سطح درست = سطح گزارش‌شده فقط وقتی ثبت اپ جداست
            reported_slot, cands, exact = reported_candidates(obj)
            level = obj.latest_level or obj.class_level
            if obj.is_misplaced and not reported_slot:
                level = ''  # سطح ثبت‌شده در این حالت همان سطح کلاس اشتباه است، منبع درست نیست
            system_slot = self._system_slot(obj)
            still_flagged = bool(obj.is_misplaced and obj.misplaced_from_slot_id and system_slot and system_slot.pk == obj.misplaced_from_slot_id)
            state = _classify_class(system_slot, reported_slot, level, flagged=still_flagged, candidates=cands, exact=exact)
            if still_flagged:
                state = ('misplaced', 'در این کلاس یا این سطح نیست و باید اصلاح شود — الان در ' + _slot_desc(system_slot) + ' ثبت شده (به اشتباه)', state[2])
            cache[obj.pk] = state
        return cache[obj.pk]

    def get_class_status(self, obj):
        return self._class_state(obj)[0]

    def get_class_status_text(self, obj):
        return self._class_state(obj)[1]

    def get_class_true_text(self, obj):
        return self._class_state(obj)[2]

    def _current_slot(self, obj):
        cache = self.__dict__.setdefault('_slot_cache', {})
        if obj.pk in cache:
            return cache[obj.pk]
        slot = None
        if self._misplaced_now(obj):
            slot = obj.misplaced_from_slot
        else:
            base = self._enr_index().enrollments(obj)
            # اول کلاس همین ترم (غیر از انتقالیِ تأییدنشده)، بعد ترم مبدأ ریزشی، و در نهایت آخرین کلاسی که داشته است
            candidates = (
                [e for e in base if obj.term_id and e.class_slot.term_id == obj.term_id and not _unconfirmed_carryover(e)],
                [e for e in base if obj.dropout_from_term_id and e.class_slot.term_id == obj.dropout_from_term_id],
                base,
            )
            for group in candidates:
                if group:
                    slot = group[0].class_slot
                    break
        cache[obj.pk] = slot
        return slot

    def get_class_slot(self, obj):
        slot = self._current_slot(obj)
        return slot.pk if slot else None

    def get_class_slot_number(self, obj):
        slot = self._current_slot(obj)
        return slot.number if slot else None

    def get_class_slot_level(self, obj):
        slot = self._current_slot(obj)
        return (slot.assigned_level or '') if slot else ''

    def get_class_slot_day(self, obj):
        slot = self._current_slot(obj)
        if not slot:
            return ''
        days = slot.schedule_days if isinstance(slot.schedule_days, list) and slot.schedule_days else None
        return '، '.join(str(d) for d in days) if days else slot.get_day_type_display()

    def get_class_slot_time(self, obj):
        slot = self._current_slot(obj)
        return (slot.time_slot or '') if slot else ''

    def get_class_slot_teacher(self, obj):
        slot = self._current_slot(obj)
        return (slot.teacher_name or '') if slot else ''

    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    registered_at_jalali = serializers.ReadOnlyField()
    followup_count = serializers.ReadOnlyField()
    last_followup_at_jalali = serializers.ReadOnlyField()
    submitted_by_name = serializers.SerializerMethodField()
    followups = UnregisteredFollowupSerializer(many=True, read_only=True)
    term_title = serializers.ReadOnlyField()
    dropout_from_term_title = serializers.SerializerMethodField()
    misplaced_class_number = serializers.SerializerMethodField()
    also_debtor = serializers.SerializerMethodField()
    also_debtor_amount = serializers.SerializerMethodField()
    also_debtor_text = serializers.SerializerMethodField()
    also_debtor_book = serializers.SerializerMethodField()
    previous_debtor_ids = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()

    def get_assigned_to_name(self, obj):
        u = obj.assigned_to
        return (f'{u.first_name} {u.last_name}'.strip() or u.username) if u else None

    def _debtor_matches(self, obj):
        if not hasattr(self, '_debtor_index'):
            self._debtor_index = _CrossListIndex('debtor')
        return self._debtor_index.match(obj.national_code, obj.phone, obj.first_name, obj.last_name)

    def get_also_debtor(self, obj):
        return bool(self._debtor_matches(obj))

    def get_also_debtor_amount(self, obj):
        return sum(self._debtor_matches(obj))

    def _debtor_items(self, obj):
        if not hasattr(self, '_debtor_index'):
            self._debtor_index = _CrossListIndex('debtor')
        return self._debtor_index.match_items(obj.national_code, obj.phone, obj.first_name, obj.last_name, ref=obj)

    def get_previous_debtor_ids(self, obj):
        return [i for _a, _d, prev, i in self._debtor_items(obj) if prev and i]

    def get_also_debtor_book(self, obj):
        return any(
            str(name).strip() == 'کتاب' and int(amount or 0) > 0
            for _total, breakdown, _is_previous, _debtor_id in self._debtor_items(obj)
            for name, amount in breakdown
        )

    def get_also_debtor_text(self, obj):
        # متن ساده: «بدهی قبلی: بابت شهریه … و بابت کتاب …» + «بدهی فعلی: …» + «جمع کل بدهی: …»
        def fmt(parts):
            return ' و '.join(f'بابت {name} {int(amt):,} تومان' for name, amt in parts)
        previous, current, total = {}, {}, 0
        for amount, breakdown, is_prev, _id in self._debtor_items(obj):
            total += max(0, int(amount or 0))
            target = previous if is_prev else current
            for name, amt in breakdown:
                if int(amt or 0) > 0:
                    target[name] = target.get(name, 0) + int(amt)
        out = []
        if previous:
            out.append('بدهی قبلی: ' + fmt(previous.items()))
        if current:
            out.append(('بدهی فعلی: ' if previous else 'بدهی: ') + fmt(current.items()))
        if out:
            out.append(f'جمع کل بدهی: {total:,} تومان')
        return ' | '.join(out)

    def get_misplaced_class_number(self, obj):
        return obj.misplaced_from_slot.number if self._misplaced_now(obj) else None

    def get_dropout_from_term_title(self, obj):
        return obj.dropout_from_term.title if obj.dropout_from_term_id else None

    class Meta:
        model = UnregisteredStudent
        fields = [
            'id', 'first_name', 'last_name', 'class_level', 'national_code', 'phone', 'tuition_price', 'current_tuition', 'row_description',
            'status', 'status_display', 'not_coming', 'contacted', 'registered_at', 'registered_at_jalali',
            'followup_count', 'last_followup_at_jalali', 'latest_level', 'followups', 'respondent', 'respondent',
            'submitted_by_name', 'term', 'term_title', 'claims_registered', 'claim_reviewed',
            'is_dropout', 'dropout_from_term', 'dropout_from_term_title',
            'is_misplaced', 'misplaced_from_slot', 'misplaced_class_number', 'attendance_transfer', 'relocation_note',
            'also_debtor', 'also_debtor_amount', 'also_debtor_text', 'also_debtor_book', 'previous_debtor_ids', 'assigned_to', 'assigned_to_name', 'gender', 'has_current_class',
            'class_slot', 'class_slot_number', 'class_slot_level', 'class_slot_day', 'class_slot_time', 'class_slot_teacher', 'class_status', 'class_status_text', 'class_true_text',
            'created_at', 'created_at_jalali', 'updated_at',
        ]
        read_only_fields = ['status', 'registered_at', 'created_at', 'updated_at', 'is_dropout', 'dropout_from_term', 'is_misplaced', 'misplaced_from_slot', 'attendance_transfer', 'relocation_note']

    def get_submitted_by_name(self, obj):
        if not obj.submitted_by:
            return None
        return f"{obj.submitted_by.first_name} {obj.submitted_by.last_name}"


class DebtorFollowupSerializer(serializers.ModelSerializer):
    followed_up_at_jalali = serializers.ReadOnlyField()
    followed_up_by_name = serializers.SerializerMethodField()

    class Meta:
        model = DebtorFollowup
        fields = ['id', 'followed_up_at', 'followed_up_at_jalali', 'followed_up_by_name', 'note']

    def get_followed_up_by_name(self, obj):
        if not obj.followed_up_by:
            return None
        return f"{obj.followed_up_by.first_name} {obj.followed_up_by.last_name}"


class DebtorSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    settled_at_jalali = serializers.ReadOnlyField()
    followup_count = serializers.ReadOnlyField()
    last_followup_at_jalali = serializers.ReadOnlyField()
    followups = DebtorFollowupSerializer(many=True, read_only=True)
    term_title = serializers.ReadOnlyField()
    carried_from_term_title = serializers.SerializerMethodField()
    source_slot_number = serializers.SerializerMethodField()
    class_slot_number = serializers.SerializerMethodField()
    class_slot_level = serializers.SerializerMethodField()
    class_slot_day = serializers.SerializerMethodField()
    class_slot_time = serializers.SerializerMethodField()
    class_slot_teacher = serializers.SerializerMethodField()
    class_status = serializers.SerializerMethodField()
    class_status_text = serializers.SerializerMethodField()
    class_true_text = serializers.SerializerMethodField()
    also_unregistered = serializers.SerializerMethodField()
    gender = serializers.SerializerMethodField()
    next_level = serializers.SerializerMethodField()
    also_unregistered_tuition = serializers.SerializerMethodField()
    unregistered_student_id = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    national_code = serializers.SerializerMethodField()
    debt_breakdown = serializers.SerializerMethodField()

    def get_debt_breakdown(self, obj):
        return [{'name': name, 'amount': int(amount or 0)} for name, amount in _debt_breakdown(obj)]

    def get_national_code(self, obj):
        if obj.student_id and obj.student and obj.student.national_code:
            return obj.student.national_code
        from accounts.models import User
        people = User.objects.filter(role='student', first_name=obj.first_name, last_name=obj.last_name)
        if obj.phone:
            people = people.filter(phone=obj.phone)
        person = people.order_by('id').first()
        return person.national_code if person else ''

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # پس از تغییر سطح از بخش مدیریت کلاس‌ها، سطح پروفایل دانش‌آموز مرجع نهایی است.
        if instance.student_id and instance.student and instance.student.language_level:
            data['class_level'] = instance.student.language_level
        return data

    def get_assigned_to_name(self, obj):
        u = obj.assigned_to
        return (f'{u.first_name} {u.last_name}'.strip() or u.username) if u else None

    def _unregistered_counterpart(self, obj):
        cache = self.__dict__.setdefault('_unregistered_counterparts', {})
        if obj.pk in cache:
            return cache[obj.pk]
        from .models import UnregisteredStudent
        index = self.__dict__.get('_open_unregistered_index')
        if index is None:
            index = {'by_code': {}, 'by_phone_name': {}, 'by_uncoded_name': {}}
            rows = UnregisteredStudent.objects.filter(
                status=UnregisteredStudent.Status.TRACKING,
            ).order_by('-created_at', '-id')
            for row in rows:
                row_code = _norm_digits(row.national_code)
                row_phone = _norm_phone(row.phone)
                row_name = _norm_name(row.first_name, row.last_name)
                if row_code:
                    index['by_code'].setdefault(row_code, []).append(row)
                if row_phone and row_name:
                    index['by_phone_name'].setdefault((row_phone, row_name), []).append(row)
                if not row_code and not row_phone and row_name:
                    index['by_uncoded_name'].setdefault(row_name, []).append(row)
                if row_name:
                    index.setdefault('by_name', {}).setdefault(row_name, []).append(row)
            self.__dict__['_open_unregistered_index'] = index

        code = _norm_digits(getattr(obj.student, 'national_code', '') if obj.student_id else '')
        phone = _norm_phone(obj.phone)
        name = _norm_name(obj.first_name, obj.last_name)
        if code:
            candidates = list(index['by_code'].get(code, []))
            if not candidates and phone:
                # کد ملی در یکی از دو فهرست خالی است؛ در آن حالت موبایل+نام کامل معیار تطبیق است.
                candidates = [r for r in index['by_phone_name'].get((phone, name), []) if not _norm_digits(r.national_code)]
        elif phone:
            candidates = list(index['by_phone_name'].get((phone, name), []))
        else:
            candidates = list(index['by_uncoded_name'].get(name, []))

        if not candidates and name:
            # کد/شماره‌ها نخوانده‌اند: نام کامل یکسان (و بدون تناقض در شماره همراه) کافی است
            candidates = [r for r in index.get('by_name', {}).get(name, [])
                          if not (phone and _norm_phone(r.phone) and _norm_phone(r.phone) != phone)
                          and not (code and _norm_digits(r.national_code) and _norm_digits(r.national_code) != code)]
            code = ''
        if obj.term_id:
            same_term = [r for r in candidates if r.term_id == obj.term_id]
            if same_term:
                candidates = same_term
        # فهرست از جدیدترین مرتب شده؛ بدون کد ملی فقط تطبیق یکتا پذیرفته می‌شود.
        match = candidates[0] if candidates and (code or len(candidates) == 1) else None
        cache[obj.pk] = match
        return match

    def get_also_unregistered(self, obj):
        return self._unregistered_counterpart(obj) is not None

    def get_next_level(self, obj):
        # کلاس/سطح بدهکار = یک سطح بالاتر از سطح ترم قبلی‌اش
        try:
            from class_management.views import _next_level_for_carryover
            return _next_level_for_carryover(obj.class_level)[0] or ''
        except Exception:
            return ''

    def get_also_unregistered_tuition(self, obj):
        match = self._unregistered_counterpart(obj)
        cache = self.__dict__.setdefault('_current_tuition_tariffs', {})
        return current_unregistered_tuition(match, cache) if match else None

    def get_gender(self, obj):
        g = getattr(obj.student, 'gender', '') if obj.student_id else ''
        if g in ('male', 'female'):
            return g
        match = self._unregistered_counterpart(obj)
        g = (getattr(match, 'gender', '') or '') if match else ''
        return g if g in ('male', 'female') else ''

    def get_unregistered_student_id(self, obj):
        match = self._unregistered_counterpart(obj)
        return match.pk if match else None

    def get_carried_from_term_title(self, obj):
        return obj.carried_from_term.title if obj.carried_from_term_id else None

    def get_source_slot_number(self, obj):
        return obj.source_slot.number if obj.source_slot_id else None

    def _debtor_info(self, obj):
        cache = self.__dict__.setdefault('_dslot_cache', {})
        if obj.pk in cache:
            return cache[obj.pk]
        from django.db.models import Q
        from class_management.models import ClassSlotEnrollment
        counterpart = self._unregistered_counterpart(obj)
        if not counterpart:
            # بدهکارِ تنها: فقط ثبت‌نام تأییدشده در ترم رکورد (یا ترم جاری) کلاس فعال است.
            # عضویت ترم‌های قبل یا صندلی خاکستری به‌تنهایی به معنی حضور در کلاس این ترم نیست.
            from accounts.models import User
            from .models import get_current_term
            term = obj.term or get_current_term()
            student_id = obj.student_id
            if not student_id:
                people = User.objects.filter(role='student', first_name=obj.first_name, last_name=obj.last_name)
                if obj.phone:
                    people = people.filter(phone=obj.phone)
                matches = list(people.order_by('id')[:2])
                if len(matches) == 1:
                    student_id = matches[0].pk
            current_enrollment = None
            if student_id and term:
                current_enrollment = ClassSlotEnrollment.objects.filter(
                    student_id=student_id,
                    class_slot__term_id=term.pk,
                    payment_verified=True,
                ).exclude(is_carryover=True, carryover_confirmed=False).select_related('class_slot').order_by('-created_at', '-id').first()
            if not current_enrollment:
                cache[obj.pk] = (
                    None,
                    ('dropout', 'فرد ریزشی می‌باشد و در این ترم سر هیچ کلاسی نیست', ''),
                )
                return cache[obj.pk]
            slot = current_enrollment.class_slot
            cache[obj.pk] = (slot, _classify_class(slot, None, '', flagged=False))
            return cache[obj.pk]

        slot = obj.source_slot if obj.source_slot_id else None
        code = getattr(obj.student, 'national_code', '') if obj.student_id else ''
        if not slot:
            q = Q(student__first_name=obj.first_name, student__last_name=obj.last_name)
            if obj.student_id:
                q |= Q(student_id=obj.student_id)
            if code:
                q |= Q(student__national_code=code)
            if obj.phone:
                q |= Q(student__phone=obj.phone)
            base = ClassSlotEnrollment.objects.filter(q).select_related('class_slot').order_by('-created_at', '-id')
            found = None
            if obj.term_id:
                found = base.filter(class_slot__term_id=obj.term_id).exclude(is_carryover=True, carryover_confirmed=False).first()
            found = found or base.first()
            slot = found.class_slot if found else None
        # منبع درست = ثبت اپ/استاد در لیست ثبت‌نام‌نشده‌ها (اگر برای این فرد وجود دارد)
        uq = Q(first_name=obj.first_name, last_name=obj.last_name)
        if code:
            uq |= Q(national_code=code)
        if obj.phone:
            uq |= Q(phone=obj.phone)
        urow = UnregisteredStudent.objects.filter(uq).exclude(status='registered').select_related('reported_slot', 'submitted_by').order_by('-created_at', '-id')
        if obj.term_id:
            urow = urow.filter(term_id=obj.term_id)
        u = urow.first()
        reported_slot, cands, exact = reported_candidates(u) if u else (None, [], False)
        level = ''
        if u and not (u.is_misplaced and not reported_slot):
            # برای توضیح زیر ردیف، آخرین سطح همان ترم را ملاک بگیر؛ class_level می‌تواند سطح قبلی باشد.
            level = u.latest_level or u.class_level
        cache[obj.pk] = (slot, _classify_class(slot, reported_slot, level, flagged=bool(u and u.is_misplaced), candidates=cands, exact=exact))
        return cache[obj.pk]

    def get_class_slot_number(self, obj):
        slot = self._debtor_info(obj)[0]
        return slot.number if slot else None

    def get_class_slot_level(self, obj):
        slot = self._debtor_info(obj)[0]
        return (slot.assigned_level or '') if slot else ''

    def get_class_slot_day(self, obj):
        slot = self._debtor_info(obj)[0]
        return _slot_day_text(slot) if slot else ''

    def get_class_slot_time(self, obj):
        slot = self._debtor_info(obj)[0]
        return (slot.time_slot or '') if slot else ''

    def get_class_slot_teacher(self, obj):
        slot = self._debtor_info(obj)[0]
        return (slot.teacher_name or '') if slot else ''

    def get_class_status(self, obj):
        return self._debtor_info(obj)[1][0]

    def get_class_status_text(self, obj):
        return self._debtor_info(obj)[1][1]

    def get_class_true_text(self, obj):
        return self._debtor_info(obj)[1][2]

    class Meta:
        model = Debtor
        fields = [
            'id', 'first_name', 'last_name', 'national_code', 'phone', 'class_level', 'debt_amount', 'description', 'row_description',
            'status', 'status_display', 'settled_at', 'settled_at_jalali', 'not_coming', 'contacted', 'respondent', 'respondent',
            'followup_count', 'last_followup_at_jalali', 'followups',
            'term', 'term_title', 'claims_settled', 'claim_reviewed', 'created_at', 'created_at_jalali', 'updated_at',
            'student', 'awaiting_registration', 'carried_from_term', 'carried_from_term_title',
            'source_slot', 'source_slot_number', 'class_slot_number', 'class_slot_level', 'class_slot_day', 'class_slot_time', 'class_slot_teacher', 'class_status', 'class_status_text', 'class_true_text', 'also_unregistered', 'gender', 'next_level', 'also_unregistered_tuition', 'unregistered_student_id', 'assigned_to', 'assigned_to_name', 'debt_breakdown',
        ]
        read_only_fields = ['status', 'settled_at', 'created_at', 'updated_at', 'student', 'awaiting_registration', 'carried_from_term', 'source_slot']
        extra_kwargs = {'phone': {'required': False, 'allow_blank': True}, 'debt_amount': {'required': False}}


class DiscountedPersonSerializer(serializers.ModelSerializer):
    created_at_jalali = serializers.ReadOnlyField()
    valid_until_jalali = serializers.ReadOnlyField()
    is_expired = serializers.ReadOnlyField()

    class Meta:
        model = DiscountedPerson
        fields = [
            'id', 'first_name', 'last_name', 'national_code',
            'discount_percent', 'reason', 'valid_until', 'valid_until_jalali', 'is_expired',
            'created_at', 'created_at_jalali', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_discount_percent(self, value):
        if not (0 <= value <= 100):
            raise serializers.ValidationError('درصد تخفیف باید بین ۰ تا ۱۰۰ باشد')
        return value
