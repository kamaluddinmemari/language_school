from rest_framework import serializers
from .models import NewLead, NewLeadFollowup, UnregisteredStudent, UnregisteredStudentFollowup, Debtor, DebtorFollowup, DiscountedPerson, normalize_national_code, normalize_phone


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
            'status', 'status_display', 'term', 'term_title',
            'followup1_at', 'followup1_at_jalali', 'followup1_by_name',
            'followup2_at', 'followup2_at_jalali', 'followup2_by_name',
            'registered_at', 'registered_at_jalali', 'cancelled_at', 'cancelled_at_jalali',
            'deposit_amount', 'deposit_paid_at', 'deposit_paid_at_jalali',
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
    return ' '.join(f"{first or ''} {last or ''}".split()).casefold()


def _norm_phone(value):
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


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
                self.items.append((code or '', _norm_phone(d.phone), _norm_name(d.first_name, d.last_name), d.debt_amount or 0))
        else:
            from .models import UnregisteredStudent
            rows = UnregisteredStudent.objects.filter(status=UnregisteredStudent.Status.TRACKING)
            for u in rows:
                self.items.append((u.national_code or '', _norm_phone(u.phone), _norm_name(u.first_name, u.last_name), u.tuition_price or 0))

    def match(self, code, phone, first, last):
        code = (code or '').strip()
        phone = _norm_phone(phone)
        name = _norm_name(first, last)
        found = []
        for c, p, n, amount in self.items:
            if (code and c and code == c) or (phone and p and phone == p) or (name and n == name):
                found.append(amount)
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
    has_current_class = serializers.SerializerMethodField()

    def get_has_current_class(self, obj):
        if obj.status == 'registered':
            return False
        if obj.is_misplaced:
            return True
        from django.db.models import Q
        from class_management.models import ClassSlotEnrollment
        q = Q(student__first_name=obj.first_name, student__last_name=obj.last_name)
        if obj.national_code:
            q |= Q(student__national_code=obj.national_code)
        if obj.phone:
            q |= Q(student__phone=obj.phone)
        return ClassSlotEnrollment.objects.filter(q, class_slot__term_id=obj.term_id).exclude(is_carryover=True, carryover_confirmed=False).exists()
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
        from django.db.models import Q
        from class_management.models import ClassSlotEnrollment
        q = Q(student__first_name=obj.first_name, student__last_name=obj.last_name)
        if obj.national_code:
            q |= Q(student__national_code=obj.national_code)
        if obj.phone:
            q |= Q(student__phone=obj.phone)
        if obj.misplaced_from_slot_id:
            # تیک «به اشتباه ثبت شده»: اگر اسمش هنوز در همان کلاس است، همان کلاس اشتباه است
            if ClassSlotEnrollment.objects.filter(q, class_slot_id=obj.misplaced_from_slot_id).exists():
                return obj.misplaced_from_slot
            # از آن کلاس خارج شده (اصلاح شده)؛ ثبت‌نام فعلی‌اش در همان ترم ملاک است
            pass
        if not obj.term_id:
            return None
        found = ClassSlotEnrollment.objects.filter(q, class_slot__term_id=obj.term_id).exclude(
            is_carryover=True, carryover_confirmed=False).select_related('class_slot').order_by('-created_at', '-id').first()
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
        if obj.misplaced_from_slot_id:
            slot = obj.misplaced_from_slot
        else:
            from django.db.models import Q
            from class_management.models import ClassSlotEnrollment
            q = Q(student__first_name=obj.first_name, student__last_name=obj.last_name)
            if obj.national_code:
                q |= Q(student__national_code=obj.national_code)
            if obj.phone:
                q |= Q(student__phone=obj.phone)
            base = ClassSlotEnrollment.objects.filter(q).select_related('class_slot').order_by('-created_at', '-id')
            # اول کلاس همین ترم (غیر از انتقالیِ تأییدنشده)، بعد ترم مبدأ ریزشی، و در نهایت آخرین کلاسی که داشته است
            for qs in (
                base.filter(class_slot__term_id=obj.term_id).exclude(is_carryover=True, carryover_confirmed=False) if obj.term_id else base.none(),
                base.filter(class_slot__term_id=obj.dropout_from_term_id) if obj.dropout_from_term_id else base.none(),
                base,
            ):
                found = qs.first()
                if found:
                    slot = found.class_slot
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

    def get_misplaced_class_number(self, obj):
        return obj.misplaced_from_slot.number if obj.misplaced_from_slot_id else None

    def get_dropout_from_term_title(self, obj):
        return obj.dropout_from_term.title if obj.dropout_from_term_id else None

    class Meta:
        model = UnregisteredStudent
        fields = [
            'id', 'first_name', 'last_name', 'class_level', 'national_code', 'phone', 'tuition_price',
            'status', 'status_display', 'registered_at', 'registered_at_jalali',
            'followup_count', 'last_followup_at_jalali', 'latest_level', 'followups',
            'submitted_by_name', 'term', 'term_title', 'claims_registered', 'claim_reviewed',
            'is_dropout', 'dropout_from_term', 'dropout_from_term_title',
            'is_misplaced', 'misplaced_from_slot', 'misplaced_class_number',
            'also_debtor', 'also_debtor_amount', 'assigned_to', 'assigned_to_name', 'gender', 'has_current_class',
            'class_slot', 'class_slot_number', 'class_slot_level', 'class_slot_day', 'class_slot_time', 'class_slot_teacher', 'class_status', 'class_status_text', 'class_true_text',
            'created_at', 'created_at_jalali', 'updated_at',
        ]
        read_only_fields = ['status', 'registered_at', 'created_at', 'updated_at', 'is_dropout', 'dropout_from_term', 'is_misplaced', 'misplaced_from_slot']

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
    assigned_to_name = serializers.SerializerMethodField()

    def get_assigned_to_name(self, obj):
        u = obj.assigned_to
        return (f'{u.first_name} {u.last_name}'.strip() or u.username) if u else None

    def get_also_unregistered(self, obj):
        if not hasattr(self, '_unreg_index'):
            self._unreg_index = _CrossListIndex('unregistered')
        code = getattr(obj.student, 'national_code', '') if obj.student_id else ''
        return bool(self._unreg_index.match(code, obj.phone, obj.first_name, obj.last_name))

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
            level = u.class_level
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
            'id', 'first_name', 'last_name', 'phone', 'class_level', 'debt_amount', 'description',
            'status', 'status_display', 'settled_at', 'settled_at_jalali',
            'followup_count', 'last_followup_at_jalali', 'followups',
            'term', 'term_title', 'claims_settled', 'claim_reviewed', 'created_at', 'created_at_jalali', 'updated_at',
            'student', 'awaiting_registration', 'carried_from_term', 'carried_from_term_title',
            'source_slot', 'source_slot_number', 'class_slot_number', 'class_slot_level', 'class_slot_day', 'class_slot_time', 'class_slot_teacher', 'class_status', 'class_status_text', 'class_true_text', 'also_unregistered', 'assigned_to', 'assigned_to_name',
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
