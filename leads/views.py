from django.utils import timezone
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Q
from .models import NewLead, UnregisteredStudent, UnregisteredStudentFollowup, DropoutFollowup, Debtor, DebtorFollowup, DiscountedPerson, build_identity_key, build_person_key, get_current_term
from .serializers import (
    NewLeadSerializer,
    UnregisteredStudentSerializer,
    DebtorSerializer,
    DiscountedPersonSerializer,
)
from accounts.menu_permissions import can_edit_menu


def duplicate_warning(queryset, identity_key, term):
    if not term or not identity_key:
        return None
    same = queryset.filter(term=term, identity_key=identity_key).first()
    if same:
        return {'error': 'این شخص در ترم انتخاب‌شده قبلاً ثبت شده است و ثبت تکراری مجاز نیست.', 'duplicate_in_term': True, 'existing_record_id': same.id, 'existing_term': getattr(same.term, 'title', None)}
    history = queryset.filter(identity_key=identity_key).exclude(term=term).select_related('term').order_by('-created_at')
    if history.exists():
        return {'warning': 'این شخص در ترم دیگری سابقه دارد. آیا می‌خواهید برای ترم فعلی هم ثبت شود؟', 'existing_in_other_terms': True, 'history': [{'id': row.id, 'term': getattr(row.term, 'title', None)} for row in history[:10]]}
    return None


# ---------------------------------------------------------------------------
# لیست انتظار ورودی‌های جدید — فقط مدیر
# ---------------------------------------------------------------------------

class NewLeadListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NewLeadSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, "new-leads"):
            return NewLead.objects.none()
        return NewLead.objects.all()

    def create(self, request, *args, **kwargs):
        from accounts.services import sync_student_from_lead
        if not can_edit_menu(request.user, "new-leads"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data.copy()
        confirmed = str(data.pop('confirm_new_term', '')).lower() in ('1', 'true', 'yes')
        term = data.get('term') or get_current_term()
        data['term'] = getattr(term, 'pk', term) if term else None
        identity = build_identity_key(data.get('national_code'), data.get('phone'), data.get('first_name'), data.get('last_name'))
        warning = duplicate_warning(NewLead.objects, identity, term)
        if warning and warning.get('duplicate_in_term'):
            return Response(warning, status=status.HTTP_409_CONFLICT)
        if warning and warning.get('existing_in_other_terms') and not confirmed:
            return Response(warning, status=status.HTTP_409_CONFLICT)
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        lead = serializer.save(created_by=request.user, term=term)
        sync_student_from_lead(
            first_name=lead.first_name, last_name=lead.last_name,
            phone=lead.phone, national_code=lead.national_code,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class NewLeadDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NewLeadSerializer
    queryset = NewLead.objects.all()

    def _forbidden_if_not_admin(self, request):
        return not can_edit_menu(request.user, "new-leads")

    def update(self, request, *args, **kwargs):
        if self._forbidden_if_not_admin(request):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if self._forbidden_if_not_admin(request):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class NewLeadActionView(APIView):
    """POST: یکی از اکشن‌های followup1 / followup2 / register / cancel روی یک سرنخ"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        if not can_edit_menu(request.user, "new-leads"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            lead = NewLead.objects.get(pk=pk)
        except NewLead.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        now = timezone.now()
        if action == 'followup1':
            lead.followup1_at = now
            lead.followup1_by = request.user
        elif action == 'followup2':
            lead.followup2_at = now
            lead.followup2_by = request.user
        elif action == 'register':
            lead.status = NewLead.Status.REGISTERED
            lead.registered_at = now
        elif action == 'cancel':
            lead.status = NewLead.Status.CANCELLED
            lead.cancelled_at = now
        elif action == 'deposit':
            amount = request.data.get('amount')
            if amount in (None, ''):
                return Response({'error': 'مبلغ بیعانه را وارد کنید'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                lead.deposit_amount = int(amount)
            except (TypeError, ValueError):
                return Response({'error': 'مبلغ بیعانه نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
            lead.deposit_paid_at = now
        else:
            return Response({'error': 'اکشن نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        lead.save()
        return Response(NewLeadSerializer(lead).data)


# ---------------------------------------------------------------------------
# زبان‌آموزان ثبت‌نام‌نشده — ثبت توسط استاد، پیگیری فقط توسط مدیر
# ---------------------------------------------------------------------------

class UnregisteredStudentListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UnregisteredStudentSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, "followups"):
            return UnregisteredStudent.objects.none()
        qs = UnregisteredStudent.objects.all()
        term_id = self.request.query_params.get('term_id')
        if term_id:
            from class_management.models import Term
            from django.db.models import Q
            try:
                term = Term.objects.get(pk=term_id)
            except Term.DoesNotExist:
                return qs.none()
            earlier_terms = Term.objects.filter(
                Q(year__lt=term.year) | Q(year=term.year, term_number__lt=term.term_number)
            )
            qs = qs.filter(
                Q(term_id=term_id) |
                (Q(term__in=earlier_terms) & ~Q(status=UnregisteredStudent.Status.REGISTERED))
            )
        return qs

    def create(self, request, *args, **kwargs):
        from accounts.models import User
        from accounts.services import sync_student_from_lead
        from .models import get_current_term
        if request.user.role not in User.TEACHER_LIKE_ROLES and request.user.role not in ('admin', 'office'):
            return Response({'error': 'فقط استاد یا مدیر می‌تواند ثبت کند'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data.copy()
        confirmed = str(data.pop('confirm_new_term', '')).lower() in ('1', 'true', 'yes')
        term = data.get('term') or get_current_term()
        data['term'] = getattr(term, 'pk', term) if term else None
        identity = build_identity_key(data.get('national_code'), data.get('phone'), data.get('first_name'), data.get('last_name'), data.get('class_level'))
        person_prefix = build_person_key(data.get('national_code'), data.get('phone'), data.get('first_name'), data.get('last_name')) + '|level:'
        exact_person = UnregisteredStudent.objects.filter(term=term, identity_key__startswith=person_prefix).order_by('-created_at', '-id')
        if exact_person.exists():
            return Response({'error': 'این شخص در ترم انتخاب‌شده قبلاً ثبت شده است؛ ثبت دوباره حتی با سطح متفاوت مجاز نیست.', 'duplicate_in_term': True, 'existing_record_id': exact_person.first().id}, status=status.HTTP_409_CONFLICT)

        normalized_level = ' '.join(str(data.get('class_level') or '').split()).casefold()
        same_name = UnregisteredStudent.objects.filter(
            term=term, first_name__iexact=data.get('first_name', ''), last_name__iexact=data.get('last_name', '')
        ).order_by('-created_at', '-id')
        if same_name.exists():
            same_level = same_name.filter(identity_key__endswith=f'|level:{normalized_level}').first()
            if same_level:
                return Response({'error': 'فردی با همین نام و همین سطح در این ترم قبلاً ثبت شده است.', 'duplicate_in_term': True, 'existing_record_id': same_level.id}, status=status.HTTP_409_CONFLICT)
            if not confirmed:
                return Response({'warning': 'فردی با نام و نام‌خانوادگی مشابه در این ترم وجود دارد، اما شناسهٔ فرد متفاوت و سطح متفاوت است. آیا ثبت شود؟', 'same_name_different_person': True, 'existing_levels': list(same_name.values_list('class_level', flat=True))}, status=status.HTTP_409_CONFLICT)

        other_term = UnregisteredStudent.objects.filter(identity_key__startswith=person_prefix).exclude(term=term).select_related('term').order_by('-created_at', '-id').first()
        warning = None
        if other_term and not confirmed:
            warning = {
                'warning': 'این شخص در ترم دیگری سابقه دارد. آیا می‌خواهید برای ترم فعلی و سطح جدید هم ثبت شود؟',
                'existing_in_other_terms': True,
                'history': [{'id': other_term.id, 'term': other_term.term.title if other_term.term else None}],
                'same_person_latest_level': UnregisteredStudent.objects.filter(term=term, identity_key__startswith=person_prefix).order_by('-created_at', '-id').values_list('class_level', flat=True).first(),
            }
            return Response(warning, status=status.HTTP_409_CONFLICT)
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        lead = serializer.save(submitted_by=request.user, term=term)
        sync_student_from_lead(
            first_name=lead.first_name, last_name=lead.last_name,
            phone=lead.phone, national_code=lead.national_code,
            language_level=lead.class_level,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class UnregisteredStudentDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UnregisteredStudentSerializer
    queryset = UnregisteredStudent.objects.all()

    def update(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class UnregisteredStudentFollowupView(APIView):
    """POST: ثبت یک پیگیری جدید — بدون محدودیت تعداد"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            student = UnregisteredStudent.objects.get(pk=pk)
        except UnregisteredStudent.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        UnregisteredStudentFollowup.objects.create(
            student=student, followed_up_by=request.user, note=request.data.get('note', '')
        )
        return Response(UnregisteredStudentSerializer(student).data, status=status.HTTP_201_CREATED)


class UnregisteredStudentRegisterView(APIView):
    """POST: ثبت‌نام شد — بایگانی می‌شود ولی همیشه قابل ویرایش باقی می‌ماند"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            student = UnregisteredStudent.objects.get(pk=pk)
        except UnregisteredStudent.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        student.status = UnregisteredStudent.Status.REGISTERED
        student.registered_at = timezone.now()
        student.save()
        return Response(UnregisteredStudentSerializer(student).data)


class UnregisteredStudentStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        qs = UnregisteredStudent.objects.all()
        tracking = qs.filter(status=UnregisteredStudent.Status.TRACKING)
        registered = qs.filter(status=UnregisteredStudent.Status.REGISTERED)
        now_local = timezone.localtime(timezone.now())
        import jdatetime
        return Response({
            'total': qs.count(),
            'tracking_count': tracking.count(),
            'registered_count': registered.count(),
            'total_tuition_potential': sum(s.tuition_price or 0 for s in tracking),
            'total_tuition_registered': sum(s.tuition_price or 0 for s in registered),
            'generated_at_jalali': jdatetime.datetime.fromgregorian(datetime=now_local).strftime('%Y/%m/%d - %H:%M:%S'),
        })


# ---------------------------------------------------------------------------
# دانشجویان ریزشی — دانش‌آموز ترم مبدأ که در ترم مقصد ثبت‌نام ندارد
# ---------------------------------------------------------------------------

class DropoutStudentListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, "dropout-students"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from class_management.models import Term, ClassSlotEnrollment
        from accounts.models import User
        from django.utils.dateparse import parse_date
        from datetime import date
        from_term_id = request.query_params.get('from_term_id')
        to_term_id = request.query_params.get('to_term_id')
        date_from = parse_date(request.query_params.get('date_from', '')) if request.query_params.get('date_from') else None
        date_to = parse_date(request.query_params.get('date_to', '')) if request.query_params.get('date_to') else None
        try:
            from_term = Term.objects.get(pk=from_term_id) if from_term_id else None
            to_term = Term.objects.get(pk=to_term_id) if to_term_id else None
        except Term.DoesNotExist:
            return Response({'error': 'ترم انتخاب‌شده پیدا نشد'}, status=status.HTTP_400_BAD_REQUEST)
        if from_term and to_term and from_term.id == to_term.id:
            return Response({'error': 'ترم مبدأ و مقصد باید متفاوت باشند'}, status=status.HTTP_400_BAD_REQUEST)

        source_qs = ClassSlotEnrollment.objects.filter(student__role='student').select_related('student', 'class_slot', 'class_slot__term')
        if from_term:
            source_qs = source_qs.filter(class_slot__term=from_term)
        if date_from:
            source_qs = source_qs.filter(created_at__date__gte=date_from)
        if date_to:
            source_qs = source_qs.filter(created_at__date__lte=date_to)
        source_rows = list(source_qs.order_by('student_id', '-created_at'))
        latest_by_student = {}
        for row in source_rows:
            latest_by_student.setdefault(row.student_id, row)
        target_ids = set()
        if to_term:
            target_ids = set(ClassSlotEnrollment.objects.filter(class_slot__term=to_term, student_id__in=latest_by_student).values_list('student_id', flat=True))
        rows = []
        today = timezone.localdate()
        for student_id, last in latest_by_student.items():
            if to_term and student_id in target_ids:
                continue
            student = last.student
            last_date = timezone.localtime(last.created_at).date()
            days_missing = max(0, (today - last_date).days)
            missing_terms = 1
            if from_term and to_term:
                terms = list(Term.objects.order_by('year', 'term_number'))
                positions = {t.id: i for i, t in enumerate(terms)}
                missing_terms = max(1, positions.get(to_term.id, positions.get(from_term.id, 0)) - positions.get(from_term.id, 0))
            followups = DropoutFollowup.objects.filter(student=student, from_term=from_term, to_term=to_term).select_related('followed_up_by').order_by('-followed_up_at')
            rows.append({
                'student_id': student.id, 'first_name': student.first_name, 'last_name': student.last_name,
                'father_name': getattr(student, 'father_name', ''), 'national_code': getattr(student, 'national_code', ''),
                'phone': getattr(student, 'phone', ''), 'gender': getattr(student, 'gender', ''),
                'last_level': last.class_slot.assigned_level or getattr(student, 'language_level', ''),
                'last_enrollment_date': last.created_at.date().isoformat(),
                'last_enrollment_date_jalali': getattr(last, 'created_at_jalali', None),
                'days_since_last_registration': days_missing, 'missing_terms': missing_terms,
                'needs_retest': days_missing > 60,
                'followups': [{'id': f.id, 'date': f.followed_up_at_jalali, 'by': f.followed_up_by_name, 'note': f.note} for f in followups],
            })
        return Response(rows)


class DropoutStudentFollowupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, student_id):
        if not can_edit_menu(request.user, "dropout-students"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from class_management.models import Term
        from_term = Term.objects.filter(pk=request.data.get('from_term_id')).first() if request.data.get('from_term_id') else None
        to_term = Term.objects.filter(pk=request.data.get('to_term_id')).first() if request.data.get('to_term_id') else None
        item = DropoutFollowup.objects.create(student_id=student_id, from_term=from_term, to_term=to_term, followed_up_by=request.user, note=request.data.get('note', ''))
        return Response({'id': item.id, 'date': item.followed_up_at_jalali, 'by': item.followed_up_by_name, 'note': item.note}, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# بدهکاران — فقط مدیر
# ---------------------------------------------------------------------------

class DebtorListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DebtorSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, "followups"):
            return Debtor.objects.none()
        qs = Debtor.objects.all()
        term_id = self.request.query_params.get('term_id')
        if term_id:
            from class_management.models import Term
            from django.db.models import Q
            try:
                term = Term.objects.get(pk=term_id)
            except Term.DoesNotExist:
                return qs.none()
            earlier_terms = Term.objects.filter(
                Q(year__lt=term.year) | Q(year=term.year, term_number__lt=term.term_number)
            )
            qs = qs.filter(
                Q(term_id=term_id) |
                (Q(term__in=earlier_terms) & ~Q(status=Debtor.Status.SETTLED))
            )
        return qs

    def create(self, request, *args, **kwargs):
        from accounts.services import sync_student_from_lead
        from .models import get_current_term
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data.copy()
        confirmed = str(data.pop('confirm_new_term', '')).lower() in ('1', 'true', 'yes')
        term = data.get('term') or get_current_term()
        data['term'] = getattr(term, 'pk', term) if term else None
        identity = build_identity_key('', data.get('phone'), data.get('first_name'), data.get('last_name'))
        warning = duplicate_warning(Debtor.objects, identity, term)
        if warning and warning.get('duplicate_in_term'):
            return Response(warning, status=status.HTTP_409_CONFLICT)
        if warning and warning.get('existing_in_other_terms') and not confirmed:
            return Response(warning, status=status.HTTP_409_CONFLICT)
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        debtor = serializer.save(created_by=request.user, term=term)
        sync_student_from_lead(
            first_name=debtor.first_name, last_name=debtor.last_name,
            phone=debtor.phone, language_level=debtor.class_level,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class DebtorDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DebtorSerializer
    queryset = Debtor.objects.all()

    def update(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class DebtorFollowupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            debtor = Debtor.objects.get(pk=pk)
        except Debtor.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        DebtorFollowup.objects.create(debtor=debtor, followed_up_by=request.user, note=request.data.get('note', ''))
        return Response(DebtorSerializer(debtor).data, status=status.HTTP_201_CREATED)


class DebtorSettleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            debtor = Debtor.objects.get(pk=pk)
        except Debtor.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        debtor.status = Debtor.Status.SETTLED
        debtor.settled_at = timezone.now()
        debtor.save()
        return Response(DebtorSerializer(debtor).data)


class DebtorStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        qs = Debtor.objects.all()
        pending = qs.filter(status=Debtor.Status.PENDING)
        settled = qs.filter(status=Debtor.Status.SETTLED)
        now_local = timezone.localtime(timezone.now())
        import jdatetime
        return Response({
            'total': qs.count(),
            'pending_count': pending.count(),
            'settled_count': settled.count(),
            'total_debt_pending': sum(d.debt_amount for d in pending),
            'total_debt_settled': sum(d.debt_amount for d in settled),
            'generated_at_jalali': jdatetime.datetime.fromgregorian(datetime=now_local).strftime('%Y/%m/%d - %H:%M:%S'),
        })


# ---------------------------------------------------------------------------
# افراد دارای تخفیف — فقط مدیر
# ---------------------------------------------------------------------------

class DiscountedPersonListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DiscountedPersonSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, "discounts"):
            return DiscountedPerson.objects.none()
        return DiscountedPerson.objects.all()

    def create(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, "discounts"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class DiscountedPersonDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DiscountedPersonSerializer
    queryset = DiscountedPerson.objects.all()

    def update(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, "discounts"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, "discounts"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)
