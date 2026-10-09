from django.utils import timezone
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Q
from .models import NewLead, NewLeadFollowup, UnregisteredStudent, UnregisteredStudentFollowup, DropoutFollowup, Debtor, DebtorFollowup, DiscountedPerson, build_identity_key, build_person_key, get_current_term
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
        return NewLead.objects.all().prefetch_related('followups__followed_up_by')

    def get_serializer_context(self):
        """
        همه‌ی آزمون‌های تعیین‌سطح را یک‌بار می‌خوانیم و بر اساس کد ملی/موبایلِ نرمال‌شده
        (ارقام فارسی/عربی، صفر ابتدایی، پیش‌شماره ۹۸) نگاشت می‌کنیم، تا سریالایزر برای
        هر سرنخ به‌جای یک کوئری جداگانه، فقط از این دیکشنری در حافظه استفاده کند
        (جلوگیری از N+1 روی لیست ورودی‌های جدید).
        """
        context = super().get_serializer_context()
        from level_tests.models import LevelTest
        from .models import normalize_national_code, normalize_phone
        by_national, by_phone = {}, {}
        for t in LevelTest.objects.all().order_by('id'):
            national = normalize_national_code(t.national_code)
            phone = normalize_phone(t.phone)
            if national:
                by_national.setdefault(national, []).append(t)
            if phone:
                by_phone.setdefault(phone, []).append(t)
        context['level_test_by_national'] = by_national
        context['level_test_by_phone'] = by_phone
        return context

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
    """POST: یکی از اکشن‌های followup (نامحدود) / register / cancel / flag_level_test / unflag_level_test روی یک سرنخ"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        if not can_edit_menu(request.user, "new-leads"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            lead = NewLead.objects.get(pk=pk)
        except NewLead.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        now = timezone.now()
        if action == 'followup':
            # پیگیری نامحدود: هر بار یک ردیف جدید با تاریخ و ساعت همان لحظه
            NewLeadFollowup.objects.create(lead=lead, followed_up_by=request.user)
            lead.refresh_from_db()
            return Response(NewLeadSerializer(lead).data)
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
        elif action == 'flag_level_test':
            from level_tests.models import LevelTest
            from .models import normalize_national_code, normalize_phone
            from django.utils.dateparse import parse_datetime

            # تاریخ/ساعتِ تیک را کاربر دستی وارد می‌کند (نه لزوماً همین لحظه)؛ اگر نفرستد یا
            # نامعتبر باشد، به لحظه‌ی فعلی برمی‌گردیم.
            marked_at = now
            raw_marked_at = request.data.get('marked_at')
            if raw_marked_at:
                parsed = parse_datetime(raw_marked_at)
                if parsed is not None:
                    if timezone.is_naive(parsed):
                        parsed = timezone.make_aware(parsed)
                    marked_at = parsed
            lead.needs_level_test = True
            lead.needs_level_test_marked_at = marked_at
            if not lead.level_test:
                try:
                    test = LevelTest.objects.create(
                        first_name=lead.first_name, last_name=lead.last_name, father_name=lead.father_name,
                        birth_date=lead.birth_date,
                        # نرمال‌سازی و کوتاه‌کردن به حداکثر طول فیلدهای LevelTest تا با کد ملی/موبایلِ
                        # دارای فاصله یا خط تیره یا رقم فارسی، خطای «مقدار طولانی‌تر از فیلد» رخ ندهد.
                        national_code=normalize_national_code(lead.national_code)[:10],
                        phone=normalize_phone(lead.phone)[:11],
                        created_by=request.user,
                    )
                    # created_at با auto_now_add پر می‌شود و مستقیم قابل ست‌کردن نیست؛ برای اینکه صفِ
                    # تعیین سطح بر اساس همان تاریخ/ساعتِ دستیِ انتخاب‌شده مرتب شود (نه لحظه‌ی کلیک)،
                    # با یک UPDATE جداگانه (که auto_now_add را دور می‌زند) اصلاحش می‌کنیم.
                    LevelTest.objects.filter(pk=test.pk).update(created_at=marked_at)
                    test.created_at = marked_at
                    lead.level_test = test
                except Exception as exc:
                    return Response({'error': f'ساخت آزمون تعیین‌سطح ناموفق بود: {exc}'}, status=status.HTTP_400_BAD_REQUEST)
        elif action == 'unflag_level_test':
            from level_tests.models import LevelTest
            # اگر آزمونی که خودکار ساخته شده هنوز دست‌نخورده و در انتظار است، پاکش می‌کنیم؛
            # اگر مدیر آموزش رویش کار کرده (تکمیل شده)، برای جلوگیری از گم‌شدن نتیجه فقط لینکش را نگه می‌داریم.
            if lead.level_test and lead.level_test.status == LevelTest.Status.PENDING and not lead.level_test.self_requested:
                lead.level_test.delete()
                lead.level_test = None
            lead.needs_level_test = False
            lead.needs_level_test_marked_at = None
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
        # سطح خودکار از کلاسی که فرد در آن قرار دارد (نیازی به تایپ سطح نیست)
        class_slot_id = data.pop('class_slot', None)
        if isinstance(class_slot_id, list):
            class_slot_id = class_slot_id[0] if class_slot_id else None
        if class_slot_id not in (None, ''):
            from class_management.models import ClassSlot
            picked_slot = ClassSlot.objects.filter(pk=class_slot_id).first()
            if not picked_slot:
                return Response({'error': 'کلاس انتخاب‌شده پیدا نشد'}, status=status.HTTP_400_BAD_REQUEST)
            data['class_level'] = picked_slot.assigned_level or data.get('class_level') or ''
            data['class_slot'] = picked_slot.pk
            data['class_number'] = str(picked_slot.number or '')
            data['class_teacher'] = picked_slot.teacher_name or ''
            data['class_time'] = picked_slot.time_slot or ''
            data['class_day'] = picked_slot.get_day_type_display() or picked_slot.day_type or ''
            if not data.get('term') and picked_slot.term_id:
                data['term'] = picked_slot.term_id
        if not str(data.get('class_level') or '').strip():
            return Response({'error': 'کلاسی را که فرد در آن قرار دارد انتخاب کنید (سطح از کلاس خودکار پر می‌شود)'}, status=status.HTTP_400_BAD_REQUEST)
        data['phone'] = str(data.get('phone') or '').strip()
        data['national_code'] = str(data.get('national_code') or '').strip()
        term = data.get('term') or get_current_term()
        if term is not None and not hasattr(term, 'pk'):
            from class_management.models import Term as _Term
            term = _Term.objects.filter(pk=term).first()
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


def _resolve_unregistered_student(item, create=False):
    from accounts.models import User
    from accounts.services import sync_student_from_lead
    students = User.objects.filter(role='student')
    found = None
    if item.national_code:
        found = students.filter(national_code=item.national_code).first()
    if not found and item.phone:
        found = students.filter(phone=item.phone).first()
    if not found:
        same_name = list(students.filter(first_name=item.first_name, last_name=item.last_name)[:2])
        found = same_name[0] if len(same_name) == 1 else None
    if not found and create:
        found, _ = sync_student_from_lead(
            first_name=item.first_name, last_name=item.last_name, phone=item.phone,
            national_code=item.national_code, language_level=item.class_level,
        )
    return found


class UnregisteredStudentRegisterOptionsView(APIView):
    """GET: کلاس‌های پیشنهادی برای «ثبت در کلاس» یک فرد ثبت‌نام‌نشده (از جمله ریزشی‌های استخراج‌شده)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            item = UnregisteredStudent.objects.select_related('term').get(pk=pk)
        except UnregisteredStudent.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        from class_management.models import Term
        from class_management.carryover import gray_enrollments
        term_param = request.query_params.get('term_id')
        term = Term.objects.filter(pk=term_param).first() if str(term_param or '').isdigit() else None
        term = term or item.term or get_current_term()
        term_id = getattr(term, 'pk', None)
        student = _resolve_unregistered_student(item, create=False)
        gray_slot_ids = [row.class_slot_id for row in gray_enrollments(student, term_id)] if (student and term_id) else []
        level, classes = _register_class_options(term_id, student, item.class_level, gray_slot_ids)
        return Response({
            'id': item.id, 'student_id': getattr(student, 'id', None),
            'student_name': f'{item.first_name} {item.last_name}', 'level': level,
            'term': term_id, 'term_title': getattr(term, 'title', ''),
            'debt_amount': getattr(item, 'tuition_price', 0) or 0, 'has_gray_class': bool(gray_slot_ids),
            'classes': classes,
        })


class UnregisteredStudentRegisterView(APIView):
    """
    POST: ثبت‌نام شد — بایگانی می‌شود ولی همیشه قابل ویرایش باقی می‌ماند.
    با class_slot_id (همراه payment_method و tuition_amount): فرد واقعاً در همان کلاس ثبت‌نام قطعی می‌شود.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from django.db import transaction
        with transaction.atomic():
            try:
                student = UnregisteredStudent.objects.select_for_update().get(pk=pk)
            except UnregisteredStudent.DoesNotExist:
                return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
            slot_id = request.data.get('class_slot_id')
            registered_class = None
            if slot_id:
                from class_management.models import ClassSlot, ClassSlotEnrollment
                from class_management.carryover import register_student_in_slot
                try:
                    slot = ClassSlot.objects.select_for_update().get(pk=slot_id)
                except (ClassSlot.DoesNotExist, ValueError, TypeError):
                    return Response({'error': 'کلاس انتخاب‌شده پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
                real_student = _resolve_unregistered_student(student, create=True)
                if not real_student:
                    return Response({'error': 'ساخت/پیدا کردن پرونده‌ی دانش‌آموز ممکن نشد'}, status=status.HTTP_400_BAD_REQUEST)
                payment_method = str(request.data.get('payment_method') or ClassSlotEnrollment.PaymentMethod.CASH)
                if payment_method not in {v for v, _l in ClassSlotEnrollment.PaymentMethod.choices}:
                    return Response({'error': 'روش پرداخت نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
                try:
                    tuition_amount = max(int(request.data.get('tuition_amount') or 0), 0)
                except (TypeError, ValueError):
                    return Response({'error': 'مبلغ نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
                _enrollment, error = register_student_in_slot(
                    real_student, slot, payment_method=payment_method, tuition_amount=tuition_amount,
                    pos_reference_code=str(request.data.get('pos_reference_code') or '')[:50],
                )
                if error:
                    transaction.set_rollback(True)
                    return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
                registered_class = slot.number
            student.status = UnregisteredStudent.Status.REGISTERED
            student.registered_at = timezone.now()
            student.save()
        data = UnregisteredStudentSerializer(student).data
        data['registered_class_number'] = registered_class
        return Response(data)


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
        if from_term and to_term:
            from .models import ExcelDropout
            have = {row['student_id'] for row in rows}
            for extracted in ExcelDropout.objects.filter(from_term=from_term, to_term=to_term).select_related('student'):
                student = extracted.student
                if student.id in have or ClassSlotEnrollment.objects.filter(class_slot__term=to_term, student=student).exists():
                    continue
                days_missing = max(0, (today - from_term.end_date).days) if getattr(from_term, 'end_date', None) else 0
                followups = DropoutFollowup.objects.filter(student=student, from_term=from_term, to_term=to_term).select_related('followed_up_by').order_by('-followed_up_at')
                rows.append({
                    'student_id': student.id, 'first_name': student.first_name, 'last_name': student.last_name,
                    'father_name': getattr(student, 'father_name', ''), 'national_code': getattr(student, 'national_code', ''),
                    'phone': getattr(student, 'phone', ''), 'gender': getattr(student, 'gender', ''),
                    'last_level': extracted.level or getattr(student, 'language_level', ''),
                    'last_enrollment_date': extracted.created_at.date().isoformat(),
                    'last_enrollment_date_jalali': None,
                    'days_since_last_registration': days_missing, 'missing_terms': 1,
                    'needs_retest': days_missing > 60, 'from_excel': True,
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
        # کلاسی که فرد در آن قرار دارد: سطح، (و در نبود مبلغ) شهریه‌ی همان سطح و شماره‌ی کلاس خودکار پر می‌شود
        class_slot_id = data.pop('class_slot', None)
        if isinstance(class_slot_id, list):
            class_slot_id = class_slot_id[0] if class_slot_id else None
        source_slot = None
        if class_slot_id not in (None, ''):
            from class_management.models import ClassSlot
            source_slot = ClassSlot.objects.select_related('term').filter(pk=class_slot_id).first()
            if not source_slot:
                return Response({'error': 'کلاس انتخاب‌شده پیدا نشد'}, status=status.HTTP_400_BAD_REQUEST)
            data['class_level'] = source_slot.assigned_level or data.get('class_level') or ''
            if not data.get('term') and source_slot.term_id:
                data['term'] = source_slot.term_id
        if not str(data.get('debt_amount') or '').strip() or str(data.get('debt_amount')).strip() == '0':
            from class_management.carryover import _tuition_for_level
            data['debt_amount'] = _tuition_for_level(data.get('class_level'))
        data['phone'] = str(data.get('phone') or '').strip()
        term = data.get('term') or get_current_term()
        if term is not None and not hasattr(term, 'pk'):
            from class_management.models import Term as _Term
            term = _Term.objects.filter(pk=term).first()
        data['term'] = getattr(term, 'pk', term) if term else None
        identity = build_identity_key('', data.get('phone'), data.get('first_name'), data.get('last_name'))
        warning = duplicate_warning(Debtor.objects, identity, term)
        if warning and warning.get('duplicate_in_term'):
            return Response(warning, status=status.HTTP_409_CONFLICT)
        if warning and warning.get('existing_in_other_terms') and not confirmed:
            return Response(warning, status=status.HTTP_409_CONFLICT)
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        debtor = serializer.save(created_by=request.user, term=term, source_slot=source_slot)
        student, _created = sync_student_from_lead(
            first_name=debtor.first_name, last_name=debtor.last_name,
            phone=debtor.phone, language_level=debtor.class_level,
            national_code=''.join(ch for ch in str(request.data.get('national_code') or '') if ch.isdigit()),
        )
        if student and not debtor.student_id:
            debtor.student = student
            debtor.save(update_fields=['student'])
        return Response(DebtorSerializer(debtor).data, status=status.HTTP_201_CREATED)


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


def _resolve_debtor_student(debtor, create=False):
    """دانش‌آموزِ واقعیِ یک بدهکار را پیدا می‌کند (student → موبایل → هم‌نامِ یکتا)؛ در صورت نیاز می‌سازد."""
    from accounts.models import User
    from accounts.services import sync_student_from_lead
    if debtor.student_id:
        return debtor.student
    students = User.objects.filter(role='student')
    phone = (debtor.phone or '').strip()
    found = students.filter(phone=phone).first() if phone else None
    if not found:
        same_name = list(students.filter(first_name=debtor.first_name, last_name=debtor.last_name)[:2])
        found = same_name[0] if len(same_name) == 1 else None
    if not found and create:
        found, _ = sync_student_from_lead(
            first_name=debtor.first_name, last_name=debtor.last_name,
            phone=debtor.phone, language_level=debtor.class_level,
        )
    if found and not debtor.student_id:
        debtor.student = found
        debtor.save(update_fields=['student'])
    return found


def _register_class_options(term_id, student, level_hint, gray_slot_ids):
    """
    کلاس‌های پیشنهادی برای ثبت در کلاس: اول کلاس خاکستری (پیشنهاد اصلی)، بعد هم‌سطح و هم‌جنسیت.
    اگر سطح نامشخص باشد همه‌ی کلاس‌های هم‌جنسیت ترم نشان داده می‌شود (هیچ‌وقت خطای نبودن سطح نمی‌دهد).
    """
    from class_management.models import ClassSlot
    from class_management.serializers import ClassSlotSerializer
    from class_management.views import _compute_level_suggestion, _normalize_level

    slots = list(ClassSlot.objects.filter(term_id=term_id).order_by('number', 'day_type', 'time_slot')) if term_id else []
    by_id = {slot.id: slot for slot in slots}
    level = ''
    for slot_id in gray_slot_ids:
        if by_id.get(slot_id) and by_id[slot_id].assigned_level:
            level = by_id[slot_id].assigned_level
            break
    if not level:
        level = (level_hint or '').strip()
    if not level and student:
        level = _compute_level_suggestion(student).get('level') or ''
    gender = getattr(student, 'gender', '') if student else ''

    def gender_ok(slot):
        if slot.gender == ClassSlot.Gender.MIXED or not gender:
            return True
        return (slot.gender == ClassSlot.Gender.GIRLS and gender == 'female') or (slot.gender == ClassSlot.Gender.BOYS and gender == 'male')

    target_level = _normalize_level(level)
    suggested, same_level, others = [], [], []
    for slot in slots:
        if not gender_ok(slot):
            continue
        if slot.id in gray_slot_ids:
            suggested.append(slot)
        elif target_level and _normalize_level(slot.assigned_level) == target_level:
            same_level.append(slot)
        else:
            others.append(slot)
    rest = same_level if (target_level and (same_level or suggested)) else (same_level + others)
    classes = []
    for slot, tag in [(sl, 'suggested') for sl in suggested] + [(sl, 'other') for sl in rest]:
        item = ClassSlotSerializer(slot).data
        item['suggested'] = tag == 'suggested'
        item['suggestion_reason'] = 'اسم فرد در این کلاس به‌صورت «منتظر ثبت‌نام» (خاکستری) آمده است' if tag == 'suggested' else (
            'هم‌سطح و هم‌جنسیت' if target_level and _normalize_level(slot.assigned_level) == target_level else 'سطح فرد مشخص نیست / کلاس هم‌جنسیت'
        )
        classes.append(item)
    return level, classes


class DebtorRegisterOptionsView(APIView):
    """
    GET: کلاس‌های پیشنهادی برای «تسویه بدهی و ثبت در کلاس».
    اول کلاسی که اسم فرد در آن خاکستری است (پیشنهاد اصلی)، بعد سایر کلاس‌های هم‌سطح و هم‌جنسیتِ همان ترم.
    هیچ‌وقت به‌خاطر نداشتن سطح خطا نمی‌دهد: اگر سطح مشخص نباشد، همه‌ی کلاس‌های هم‌جنسیتِ ترم نشان داده می‌شود.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            debtor = Debtor.objects.select_related('term', 'source_slot').get(pk=pk)
        except Debtor.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        from class_management.models import ClassSlot
        from class_management.serializers import ClassSlotSerializer
        from class_management.carryover import gray_enrollments
        from class_management.views import _compute_level_suggestion, _normalize_level

        from class_management.models import Term
        term_param = request.query_params.get('term_id')
        term = Term.objects.filter(pk=term_param).first() if str(term_param or '').isdigit() else None
        term = term or debtor.term or get_current_term()
        term_id = getattr(term, 'pk', None)
        student = _resolve_debtor_student(debtor, create=False)
        gray_slot_ids = []
        if student and term_id:
            gray_slot_ids = [row.class_slot_id for row in gray_enrollments(student, term_id)]
        if debtor.source_slot_id and debtor.source_slot_id not in gray_slot_ids and debtor.awaiting_registration:
            gray_slot_ids.append(debtor.source_slot_id)

        level, classes = _register_class_options(term_id, student, debtor.class_level, gray_slot_ids)
        return Response({
            'debtor_id': debtor.id, 'student_id': getattr(student, 'id', None),
            'student_name': f'{debtor.first_name} {debtor.last_name}', 'level': level,
            'term': term_id, 'term_title': getattr(term, 'title', ''),
            'debt_amount': debtor.debt_amount, 'has_gray_class': bool(gray_slot_ids),
            'classes': classes,
        })


class DebtorSettleView(APIView):
    """
    POST: «تسویه بدهی و ثبت در کلاس».
    body (اختیاری): class_slot_id, payment_method, tuition_amount, pos_reference_code.
    - با class_slot_id: فرد در همان کلاس ثبت‌نام قطعی می‌شود (اسم خاکستری ← مشکی، خاکستریِ کلاس‌های دیگر حذف)
    - بدون class_slot_id: فقط تسویه؛ اگر اسمش در کلاسی خاکستری بود همان کلاس مشکی می‌شود
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from django.db import transaction
        from class_management.models import ClassSlot, ClassSlotEnrollment
        from class_management.carryover import register_student_in_slot, finalize_registration, gray_enrollments

        with transaction.atomic():
            try:
                debtor = Debtor.objects.select_for_update().get(pk=pk)
            except Debtor.DoesNotExist:
                return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
            slot_id = request.data.get('class_slot_id')
            registered_class = None
            if slot_id:
                try:
                    slot = ClassSlot.objects.select_for_update().get(pk=slot_id)
                except (ClassSlot.DoesNotExist, ValueError, TypeError):
                    return Response({'error': 'کلاس انتخاب‌شده پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
                student = _resolve_debtor_student(debtor, create=True)
                if not student:
                    return Response({'error': 'ساخت/پیدا کردن پرونده‌ی دانش‌آموز ممکن نشد'}, status=status.HTTP_400_BAD_REQUEST)
                payment_method = str(request.data.get('payment_method') or ClassSlotEnrollment.PaymentMethod.CASH)
                if payment_method not in {v for v, _l in ClassSlotEnrollment.PaymentMethod.choices}:
                    return Response({'error': 'روش پرداخت نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
                try:
                    tuition_amount = int(request.data.get('tuition_amount', debtor.debt_amount) or 0)
                except (TypeError, ValueError):
                    return Response({'error': 'مبلغ نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
                enrollment, error = register_student_in_slot(
                    student, slot, payment_method=payment_method, tuition_amount=max(tuition_amount, 0),
                    pos_reference_code=str(request.data.get('pos_reference_code') or '')[:50],
                )
                if error:
                    transaction.set_rollback(True)
                    return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
                registered_class = slot.number
            else:
                student = _resolve_debtor_student(debtor, create=False)
                if student and debtor.term_id:
                    grays = list(gray_enrollments(student, debtor.term_id))
                    if grays:
                        finalize_registration(student, grays[0].class_slot)
                        registered_class = grays[0].class_slot.number
            debtor.refresh_from_db()
            debtor.status = Debtor.Status.SETTLED
            debtor.settled_at = timezone.now()
            debtor.awaiting_registration = False
            debtor.save()
        data = DebtorSerializer(debtor).data
        data['registered_class_number'] = registered_class
        return Response(data)


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
