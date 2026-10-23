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

ARCHIVE_KEEP_DAYS = 5


def purge_old_archives():
    """سوابق حل‌شده برای بایگانی بر اساس ترم نگهداری می‌شوند و اینجا سخت‌حذف نمی‌شوند."""
    return None



class NewLeadListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NewLeadSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, "new-leads"):
            return NewLead.objects.none()
        qs = NewLead.objects.all().select_related('assigned_to', 'term').prefetch_related('followups__followed_up_by')
        term_id = self.request.query_params.get('term_id')
        if term_id:
            return qs.filter(term_id=term_id)
        return qs

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
        purge_old_archives()
        qs = UnregisteredStudent.objects.all().select_related('term', 'assigned_to', 'submitted_by', 'reported_slot', 'dropout_from_term', 'misplaced_from_slot').prefetch_related('followups__followed_up_by')
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
            if str(self.request.query_params.get('archive') or '').lower() in ('1', 'true', 'yes'):
                qs = qs.filter(term_id=term_id)
            else:
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
            # جنسیت خودکار از نوع کلاس (دخترانه/پسرانه)؛ کلاس مختلط = نامشخص
            data['gender'] = {'girls': 'female', 'boys': 'male'}.get(picked_slot.gender, '')
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
        # وقتی کد ملی موجود است، identity_key بالا تشخیص تکرار را انجام می‌دهد؛
        # افراد هم‌نام با کد ملی متفاوت افراد جداگانه‌اند و نباید هشدار/توقف بگیرند.
        if not data.get('national_code'):
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
        lead = serializer.save(submitted_by=request.user, term=term, **({'reported_slot': picked_slot} if class_slot_id not in (None, '') else {}))
        synced = sync_student_from_lead(
            first_name=lead.first_name, last_name=lead.last_name,
            phone=lead.phone, national_code=lead.national_code,
            language_level=lead.class_level,
        )
        try:
            user_obj = synced[0] if isinstance(synced, (tuple, list)) else synced
            if lead.gender and user_obj is not None and not getattr(user_obj, 'gender', ''):
                user_obj.gender = lead.gender
                user_obj.save(update_fields=['gender'])
        except Exception:
            pass
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
    elif item.phone:
        # شمارهٔ همراه ممکن است بین اعضای خانواده مشترک باشد؛ در نبود کد ملی
        # فقط شماره همراهِ همراه با نام کامل و تطبیق یکتا قابل استفاده است.
        same_person = students.filter(
            phone=item.phone, first_name=item.first_name, last_name=item.last_name,
        )
        matches = list(same_person[:2])
        found = matches[0] if len(matches) == 1 else None
    else:
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
        level, classes = _register_class_options(term_id, student, item.class_level, gray_slot_ids, item.gender)
        return Response({
            'id': item.id, 'student_id': getattr(student, 'id', None),
            'student_name': f'{item.first_name} {item.last_name}', 'level': level,
            'term': term_id, 'term_title': getattr(term, 'title', ''),
            'standard_level': _standard_level(student),
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
            tuition_amount = 0
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
                from class_management.disciplinary import disciplinary_guard
                warning = disciplinary_guard(request, [real_student], skip_unregistered=True)
                if warning:
                    transaction.set_rollback(True)
                    return warning
                person_gender = real_student.gender or student.gender
                if not _slot_gender_ok(slot, person_gender):
                    transaction.set_rollback(True)
                    return Response({'error': 'جنسیت این فرد با کلاس انتخاب‌شده (دخترانه/پسرانه) مغایرت دارد؛ ثبت‌نام انجام نشد'}, status=status.HTTP_400_BAD_REQUEST)
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
            if slot_id and tuition_amount:
                student.tuition_price = tuition_amount  # شهریه‌ی محقق‌شده = مبلغ واقعاً دریافتی
            student.save()
        data = UnregisteredStudentSerializer(student).data
        data['registered_class_number'] = registered_class
        return Response(data)


def _new_lead_student(lead, create=False):
    """پروندهٔ دانش‌آموزیِ متناظر با سرنخ لیست انتظار (اگر create=True و نبود، ساخته می‌شود)."""
    from types import SimpleNamespace
    proxy = SimpleNamespace(
        national_code=lead.national_code, phone=lead.phone, first_name=lead.first_name,
        last_name=lead.last_name, class_level=lead.requested_level,
    )
    return _resolve_unregistered_student(proxy, create=create)


class NewLeadRegisterOptionsView(APIView):
    """GET: کلاس‌های پیشنهادی (هم‌سطح و هم‌جنسیت با سطح درخواستی) برای «ثبت در کلاس» یک فرد لیست انتظار."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not can_edit_menu(request.user, "new-leads"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            lead = NewLead.objects.select_related('term').get(pk=pk)
        except NewLead.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        from class_management.models import Term
        term_param = request.query_params.get('term_id')
        term = Term.objects.filter(pk=term_param).first() if str(term_param or '').isdigit() else None
        term = term or get_current_term() or lead.term
        term_id = getattr(term, 'pk', None)
        student = _new_lead_student(lead, create=False)
        level, classes = _register_class_options(term_id, student, lead.requested_level, [], lead.gender)
        return Response({
            'id': lead.id, 'student_id': getattr(student, 'id', None),
            'student_name': f'{lead.first_name} {lead.last_name}', 'level': level,
            'term': term_id, 'term_title': getattr(term, 'title', ''), 'classes': classes,
        })


class NewLeadRegisterView(APIView):
    """POST: ثبت قطعی فرد لیست انتظار در یک کلاس (class_slot_id، payment_method، tuition_amount) و علامت‌گذاری «ثبت‌نام شد»."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, "new-leads"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from django.db import transaction
        from class_management.models import ClassSlot, ClassSlotEnrollment
        from class_management.carryover import register_student_in_slot
        from class_management.disciplinary import disciplinary_guard
        with transaction.atomic():
            try:
                lead = NewLead.objects.select_for_update().get(pk=pk)
            except NewLead.DoesNotExist:
                return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
            try:
                slot = ClassSlot.objects.select_for_update().get(pk=request.data.get('class_slot_id'))
            except (ClassSlot.DoesNotExist, ValueError, TypeError):
                return Response({'error': 'کلاس انتخاب‌شده پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
            student = _new_lead_student(lead, create=True)
            if not student:
                return Response({'error': 'ساخت/پیدا کردن پرونده‌ی دانش‌آموز ممکن نشد'}, status=status.HTTP_400_BAD_REQUEST)
            warning = disciplinary_guard(request, [student])
            if warning:
                transaction.set_rollback(True)
                return warning
            if not _slot_gender_ok(slot, student.gender or lead.gender):
                transaction.set_rollback(True)
                return Response({'error': 'جنسیت این فرد با کلاس انتخاب‌شده (دخترانه/پسرانه) مغایرت دارد؛ ثبت‌نام انجام نشد'}, status=status.HTTP_400_BAD_REQUEST)
            payment_method = str(request.data.get('payment_method') or ClassSlotEnrollment.PaymentMethod.CASH)
            if payment_method not in {v for v, _l in ClassSlotEnrollment.PaymentMethod.choices}:
                return Response({'error': 'روش پرداخت نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                tuition_amount = max(int(request.data.get('tuition_amount') or 0), 0)
            except (TypeError, ValueError):
                return Response({'error': 'مبلغ نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
            _enrollment, error = register_student_in_slot(
                student, slot, payment_method=payment_method, tuition_amount=tuition_amount,
                pos_reference_code=str(request.data.get('pos_reference_code') or '')[:50],
            )
            if error:
                transaction.set_rollback(True)
                return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
            lead.status = NewLead.Status.REGISTERED
            lead.registered_at = timezone.now()
            lead.save()
        return Response({'id': lead.id, 'status': lead.status, 'registered_class_number': slot.number})


def _term_scoped_stats_qs(qs, term_id, resolved_status, archive=False):
    """آمار هم‌دامنه با لیست: ترم انتخاب‌شده + موارد حل‌نشده‌ی ترم‌های قبل (مثل UnregisteredStudentListView/DebtorListView)."""
    if not term_id:
        return qs
    from class_management.models import Term
    term = Term.objects.filter(pk=term_id).first()
    if not term:
        return qs.none()
    if archive:
        return qs.filter(term_id=term.pk)
    earlier = Term.objects.filter(Q(year__lt=term.year) | Q(year=term.year, term_number__lt=term.term_number))
    return qs.filter(Q(term_id=term.pk) | (Q(term__in=earlier) & ~Q(status=resolved_status)))


class UnregisteredStudentStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        archive = str(request.query_params.get('archive') or '').lower() in ('1', 'true', 'yes')
        qs = _term_scoped_stats_qs(UnregisteredStudent.objects.all(), request.query_params.get('term_id'), UnregisteredStudent.Status.REGISTERED, archive=archive)
        tracking = qs.filter(status=UnregisteredStudent.Status.TRACKING)
        registered = qs.filter(status=UnregisteredStudent.Status.REGISTERED)
        now_local = timezone.localtime(timezone.now())
        import jdatetime
        from class_management.carryover import _tuition_for_level

        def potential_price(s):
            # اگر شهریه‌ی پیشنهادی ثبت نشده باشد، شهریه‌ی تعریف‌شده‌ی همان سطح محاسبه می‌شود
            if s.tuition_price:
                return s.tuition_price
            try:
                return int(_tuition_for_level(s.latest_level or s.class_level) or 0)
            except Exception:
                return 0
        return Response({
            'total': qs.count(),
            'tracking_count': tracking.count(),
            'registered_count': registered.count(),
            'total_tuition_potential': sum(potential_price(s) for s in tracking) + sum(
                d.debt_amount for d in _term_scoped_stats_qs(Debtor.objects.all(), request.query_params.get('term_id'), Debtor.Status.SETTLED, archive=archive).filter(status=Debtor.Status.PENDING, awaiting_registration=True)),
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
        if to_term:
            from .models import ExcelDropout
            have = {row['student_id'] for row in rows}
            extracted_qs = ExcelDropout.objects.filter(to_term=to_term)
            if from_term:
                extracted_qs = extracted_qs.filter(Q(from_term=from_term) | Q(from_term__isnull=True))
            for extracted in extracted_qs.select_related('student'):
                student = extracted.student
                if student.id in have or ClassSlotEnrollment.objects.filter(class_slot__term=to_term, student=student).exists():
                    continue
                days_missing = max(0, (today - from_term.end_date).days) if from_term and getattr(from_term, 'end_date', None) else 0
                followups = DropoutFollowup.objects.filter(student=student, from_term=extracted.from_term, to_term=to_term).select_related('followed_up_by').order_by('-followed_up_at')
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
        purge_old_archives()
        qs = Debtor.objects.all().select_related('student', 'term', 'assigned_to', 'source_slot', 'carried_from_term').prefetch_related('followups__followed_up_by')
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
            if str(self.request.query_params.get('archive') or '').lower() in ('1', 'true', 'yes'):
                qs = qs.filter(term_id=term_id)
            else:
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
        # مبلغ خالی فقط برای بدهیِ «شهریه» خودکار از روی سطح پر می‌شود؛ بدهی کتاب/سایر موارد هرگز شهریه نمی‌گیرد.
        auto_flag = str(data.pop('auto_tuition', '')).strip().lower()
        desc_text = str(data.get('description') or '')
        non_tuition_words = ('کتاب', 'جزوه', 'جریمه', 'غیبت', 'ثبت‌نام‌نشده')
        if auto_flag in ('1', 'true', 'yes'):
            auto_tuition = True
        elif auto_flag in ('0', 'false', 'no'):
            auto_tuition = False
        else:
            auto_tuition = not any(w in desc_text for w in non_tuition_words)
        if auto_tuition and (not str(data.get('debt_amount') or '').strip() or str(data.get('debt_amount')).strip() == '0'):
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
        if student and source_slot and not getattr(student, 'gender', ''):
            slot_gender = {'girls': 'female', 'boys': 'male'}.get(source_slot.gender, '')
            if slot_gender:
                student.gender = slot_gender
                student.save(update_fields=['gender'])
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
    """دانش‌آموز واقعی را با FK، سپس موبایل+نام کاملِ یکتا پیدا می‌کند؛ موبایل تنها کافی نیست."""
    from accounts.models import User
    from accounts.services import sync_student_from_lead
    if debtor.student_id:
        return debtor.student
    students = User.objects.filter(role='student')
    phone = (debtor.phone or '').strip()
    if phone:
        matches = list(students.filter(
            phone=phone, first_name=debtor.first_name, last_name=debtor.last_name,
        ).order_by('id')[:2])
        found = matches[0] if len(matches) == 1 else None
    else:
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


def _slot_gender_ok(slot, gender):
    """کلاس مختلط یا جنسیت نامشخص = مجاز؛ وگرنه جنسیت باید با کلاس بخواند."""
    from class_management.models import ClassSlot
    if not gender or slot.gender == ClassSlot.Gender.MIXED:
        return True
    return (slot.gender == ClassSlot.Gender.GIRLS and gender == 'female') or (slot.gender == ClassSlot.Gender.BOYS and gender == 'male')


def _gender_from_enrolled_slot(slot):
    """روز فرد را آقا و روز زوج را خانم می‌گیرد؛ جنسیت صریحِ ناسازگارِ کلاس مقدم است."""
    if not slot:
        return ''
    day_gender = {'even': 'female', 'odd': 'male'}.get(slot.day_type, '')
    class_gender = {'girls': 'female', 'boys': 'male'}.get(slot.gender, '')
    if class_gender and day_gender and class_gender != day_gender:
        return class_gender
    return day_gender or class_gender or ''


def _standard_level(student):
    """سطح استاندارد (پیشنهادیِ سیستم) دانش‌آموز؛ اگر دانش‌آموز پرونده ندارد خالی."""
    if not student:
        return ''
    try:
        from class_management.views import _compute_level_suggestion
        return _compute_level_suggestion(student).get('level') or ''
    except Exception:
        return ''


def _register_class_options(term_id, student, level_hint, gray_slot_ids, gender_hint='', progressive_levels=False):
    """
    کلاس‌های پیشنهادی برای ثبت در کلاس: اول کلاس خاکستری (پیشنهاد اصلی)، بعد هم‌سطح و هم‌جنسیت.
    اگر سطح نامشخص باشد همه‌ی کلاس‌های هم‌جنسیت ترم نشان داده می‌شود (هیچ‌وقت خطای نبودن سطح نمی‌دهد).
    در حالت progressive_levels، از سطح فعلی به بعد و سپس همه‌ی سطح‌های گروه‌های سنی بعدی پیشنهاد می‌شوند.
    """
    from class_management.models import ClassSlot
    from class_management.serializers import ClassSlotSerializer
    from class_management.views import _compute_level_suggestion, _normalize_level
    from level_tests.models import StandardLevel
    from types import SimpleNamespace
    import re

    slots = list(ClassSlot.objects.filter(term_id=term_id).order_by('number', 'day_type', 'time_slot')) if term_id else []
    by_id = {slot.id: slot for slot in slots}
    level = ''
    if progressive_levels:
        # برای استخراج ریزشی، مبنا سطح استاندارد فعلی فرد است؛ نه سطح کلاس آخر یا کلاس خاکستری.
        level = (level_hint or '').strip()
        if not level and student:
            level = _compute_level_suggestion(student).get('level') or ''
    if not level:
        for slot_id in gray_slot_ids:
            if by_id.get(slot_id) and by_id[slot_id].assigned_level:
                level = by_id[slot_id].assigned_level
                break
    if not level:
        level = (level_hint or '').strip()
    if not level and student:
        level = _compute_level_suggestion(student).get('level') or ''
    # جنسیت ثبت‌نام‌شده از روی کلاس مبدأ تعیین می‌شود، نه از جنسیت پروفایل قدیمی فرد.
    enrolled_slot = next((by_id.get(slot_id) for slot_id in gray_slot_ids if by_id.get(slot_id)), None)
    gender = _gender_from_enrolled_slot(enrolled_slot) or (getattr(student, 'gender', '') if student else '') or gender_hint or ''

    def gender_ok(slot):
        if slot.gender == ClassSlot.Gender.MIXED or not gender:
            return True
        return (slot.gender == ClassSlot.Gender.GIRLS and gender == 'female') or (slot.gender == ClassSlot.Gender.BOYS and gender == 'male')

    def canon(code):
        # «Teen 2»، «teen2»، «TEEN-2» و «Teen_2» همه یک سطح‌اند؛ فاصله/خط‌تیره/زیرخط و حروف بزرگ‌وکوچک نادیده گرفته می‌شوند.
        return re.sub(r'[\s_\-]+', '', str(code or '')).lower()

    db_levels = {canon(item.code): item for item in StandardLevel.objects.all()}
    kids_prefixes = ('e', 's', 'g', 'u', 'm', 'h', 'i')

    def natural_level(code):
        """
        (گروه سنی، شماره‌ی ترتیبی) مستقیم از خودِ کد سطح: teenstarter=۰، teen1..teen15، کودک E1..I5، بزرگسال ۱۰۱..۶۰۶.
        ترتیبِ سطح‌ها فقط از روی همین کد گرفته می‌شود تا به ستون order جدول (که ممکن است خالی/تکراری/یک‌واحد جابه‌جا
        باشد) یا به شکل نوشتن کد (فاصله/حروف) وابسته نباشد — وابستگی قبلی باعث می‌شد سطح خودِ فرد (مثلاً teen2)
        پیشنهاد داده نشود و فهرست از teen3 شروع شود.
        """
        c = canon(code)
        if c == 'teenstarter':
            return 'teen', 0
        m = re.fullmatch(r'teen(\d{1,2})', c)
        if m:
            return 'teen', int(m.group(1))
        m = re.fullmatch(r'([a-z])(\d)', c)
        if m and m.group(1) in kids_prefixes:
            return 'kids', kids_prefixes.index(m.group(1)) * 10 + int(m.group(2))
        if re.fullmatch(r'\d{3}', c):
            return 'adult', int(c)
        return None

    def level_meta(code):
        raw = str(code or '').strip()
        if not raw:
            return None
        natural = natural_level(raw)
        db_level = db_levels.get(canon(raw))
        if db_level:
            # گروه سنی از جدول سطوح استاندارد؛ ترتیب از خودِ کد (در صورت قابل‌تشخیص بودن) وگرنه ستون order
            return SimpleNamespace(
                age_group=db_level.age_group,
                order=natural[1] if natural and natural[0] == db_level.age_group else db_level.order,
            )
        if natural:
            return SimpleNamespace(age_group=natural[0], order=natural[1])
        return None

    target_level = _normalize_level(level)
    current_standard = level_meta(level)
    age_rank = {'kids': 0, 'teen': 1, 'adult': 2}
    current_age_rank = age_rank.get(current_standard.age_group) if current_standard else None
    allowed_age_groups = {
        'kids': {'kids', 'teen'},
        'teen': {'teen', 'adult'},
        'adult': {'adult'},
    }
    slot_level_meta = {
        canon(slot.assigned_level): level_meta(slot.assigned_level)
        for slot in slots if slot.assigned_level
    }

    def progressive_ok(slot):
        """سطح فعلی و همه‌ی سطح‌های بعدی؛ بعد از کودک، نوجوان و بعد از نوجوان، بزرگسال هم مجاز است."""
        if not progressive_levels:
            return True
        slot_level = slot_level_meta.get(canon(slot.assigned_level))
        if not current_standard:
            return bool(canon(slot.assigned_level) and canon(slot.assigned_level) == canon(level))
        if canon(slot.assigned_level) == canon(level):
            return True  # خودِ سطح فرد همیشه پیشنهاد می‌شود (مثلاً teen2 ← teen2 و بالاتر)
        if not slot_level:
            return False
        slot_age_rank = age_rank.get(slot_level.age_group)
        if slot_age_rank is None or current_age_rank is None or slot_level.age_group not in allowed_age_groups.get(current_standard.age_group, set()):
            return False
        return slot_age_rank > current_age_rank or slot_level.order >= current_standard.order

    suggested, same_level, progressive_others, others = [], [], [], []
    for slot in slots:
        if not gender_ok(slot):
            continue
        if not progressive_ok(slot):
            continue
        if slot.id in gray_slot_ids:
            suggested.append(slot)
        elif target_level and canon(slot.assigned_level) == canon(level):
            same_level.append(slot)
        elif progressive_levels and current_standard:
            progressive_others.append(slot)
        else:
            others.append(slot)
    rest = (same_level + progressive_others) if progressive_levels and current_standard else (same_level if (target_level and (same_level or suggested)) else (same_level + others))
    from class_management.models import TuitionSetting, infer_age_group_from_level
    tuition_cache = {}

    def slot_tuition(slot):
        lvl = str(slot.assigned_level or '').strip()
        if lvl not in tuition_cache:
            age = infer_age_group_from_level(lvl) if lvl else ''
            st = TuitionSetting.objects.filter(level=lvl, age_group=age).first() if lvl and age else None
            tuition_cache[lvl] = st.amount if st else 0
        return tuition_cache[lvl]

    ordered = [(sl, 'suggested') for sl in suggested] + [(sl, 'other') for sl in rest]
    if progressive_levels and current_standard:
        # سطح‌ها از کم به زیاد؛ کلاس خاکستری فقط در سطح خودش اولویت دارد، نه اینکه
        # ترتیب سطح‌ها را به‌هم بزند. در یک سطح، شماره/ترتیب کلاس همان ترتیب قبلی است.
        ordered.sort(key=lambda pair: (
            age_rank.get(slot_level_meta.get(canon(pair[0].assigned_level)).age_group, 99)
            if slot_level_meta.get(canon(pair[0].assigned_level)) else 99,
            slot_level_meta.get(canon(pair[0].assigned_level)).order
            if slot_level_meta.get(canon(pair[0].assigned_level)) else 999999,
            0 if pair[1] == 'suggested' else 1,
            pair[0].number,
            pair[0].day_type,
            pair[0].time_slot,
        ))

    classes = []
    for slot, tag in ordered:
        item = ClassSlotSerializer(slot).data
        item['suggested'] = tag == 'suggested'
        item['tuition_amount'] = slot_tuition(slot)
        item['suggestion_reason'] = 'اسم فرد در این کلاس به‌صورت «منتظر ثبت‌نام» (خاکستری) آمده است' if tag == 'suggested' else (
            'هم‌سطح و هم‌جنسیت' if target_level and canon(slot.assigned_level) == canon(level) else ('از این سطح به بعد و گروه سنی بعدی' if progressive_levels and current_standard else 'سطح فرد مشخص نیست / کلاس هم‌جنسیت')
        )
        classes.append(item)
    return level, classes


class DebtorRegisterOptionsView(APIView):
    """
    GET: کلاس‌های پیشنهادی برای ثبت در کلاس؛ این endpoint بدهی را تسویه نمی‌کند.
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
            'standard_level': _standard_level(student),
            'debt_amount': debtor.debt_amount, 'has_gray_class': bool(gray_slot_ids),
            'classes': classes,
        })


class DebtorRegisterView(APIView):
    """ثبت بدهکار/انتقالی در کلاس، بدون تسویه یا تغییر وضعیت بدهی."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        slot_id = request.data.get('class_slot_id')
        if not slot_id:
            return Response({'error': 'کلاس مقصد الزامی است'}, status=status.HTTP_400_BAD_REQUEST)
        from django.db import transaction
        from class_management.models import ClassSlot, ClassSlotEnrollment
        from class_management.carryover import register_student_in_slot

        with transaction.atomic():
            try:
                debtor = Debtor.objects.select_for_update().get(pk=pk)
            except Debtor.DoesNotExist:
                return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
            try:
                slot = ClassSlot.objects.select_for_update().get(pk=slot_id)
            except (ClassSlot.DoesNotExist, ValueError, TypeError):
                return Response({'error': 'کلاس انتخاب‌شده پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
            student = _resolve_debtor_student(debtor, create=True)
            if not student:
                return Response({'error': 'ساخت/پیدا کردن پرونده‌ی دانش‌آموز ممکن نشد'}, status=status.HTTP_400_BAD_REQUEST)
            from class_management.disciplinary import disciplinary_guard
            warning = disciplinary_guard(request, [student], skip_debtor=True)
            if warning:
                transaction.set_rollback(True)
                return warning
            if not _slot_gender_ok(slot, student.gender):
                transaction.set_rollback(True)
                return Response({'error': 'جنسیت این فرد با کلاس انتخاب‌شده (دخترانه/پسرانه) مغایرت دارد؛ ثبت‌نام انجام نشد'}, status=status.HTTP_400_BAD_REQUEST)
            payment_method = str(request.data.get('payment_method') or ClassSlotEnrollment.PaymentMethod.CASH)
            if payment_method not in {value for value, _label in ClassSlotEnrollment.PaymentMethod.choices}:
                return Response({'error': 'روش پرداخت نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                tuition_amount = max(int(request.data.get('tuition_amount') or 0), 0)
            except (TypeError, ValueError):
                return Response({'error': 'مبلغ نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
            _enrollment, error = register_student_in_slot(
                student, slot, payment_method=payment_method, tuition_amount=tuition_amount,
                pos_reference_code=str(request.data.get('pos_reference_code') or '')[:50],
            )
            if error:
                transaction.set_rollback(True)
                return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
            if debtor.awaiting_registration:
                debtor.awaiting_registration = False
                debtor.save(update_fields=['awaiting_registration', 'student'])

        data = DebtorSerializer(debtor).data
        data['registered_class_number'] = slot.number
        return Response(data)


class DebtorSettleView(APIView):
    """POST: فقط وضعیت بدهی را تسویه می‌کند؛ ثبت‌نام کلاسی endpoint جداگانه دارد."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        if request.data.get('class_slot_id'):
            return Response({'error': 'تسویه بدهی از ثبت در کلاس جداست؛ برای ثبت در کلاس از دکمهٔ مربوط استفاده کنید.'}, status=status.HTTP_400_BAD_REQUEST)
        from django.db import transaction
        with transaction.atomic():
            try:
                debtor = Debtor.objects.select_for_update().get(pk=pk)
            except Debtor.DoesNotExist:
                return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
            if debtor.awaiting_registration:
                return Response({'error': 'این مورد بدهی نیست؛ باید جداگانه در کلاس ثبت شود.'}, status=status.HTTP_400_BAD_REQUEST)
            debtor.status = Debtor.Status.SETTLED
            debtor.settled_at = timezone.now()
            debtor.save(update_fields=['status', 'settled_at'])
        return Response(DebtorSerializer(debtor).data)


class DebtorStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, "followups"):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        archive = str(request.query_params.get('archive') or '').lower() in ('1', 'true', 'yes')
        qs = _term_scoped_stats_qs(Debtor.objects.all(), request.query_params.get('term_id'), Debtor.Status.SETTLED, archive=archive)
        # «منتظر ثبت‌نام»های انتقالی در واقع ثبت‌نام‌نشده‌اند و در جمع بدهی‌ها نمی‌آیند
        pending = qs.filter(status=Debtor.Status.PENDING, awaiting_registration=False)
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


class FollowupStaffListView(APIView):
    """GET: فهرست کارمندان دفتر برای «ارجاع پیگیری» ثبت‌نام‌نشده‌ها و بدهکاران."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not (can_edit_menu(request.user, 'followups') or can_edit_menu(request.user, 'new-leads')):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from accounts.models import User
        users = User.objects.filter(role__in=('admin', 'office', 'employee'), is_active=True).order_by('first_name', 'last_name')
        return Response([
            {'id': u.id, 'name': (f'{u.first_name} {u.last_name}'.strip() or u.username), 'role': u.role}
            for u in users
        ])


def _misplaced_enrollment(item):
    """ثبت‌نامِ فعلیِ فردِ «در کلاس درست ثبت‌نام نشده» در همان کلاس اشتباه."""
    from django.db.models import Q
    from class_management.models import ClassSlotEnrollment
    q = Q(student__first_name=item.first_name, student__last_name=item.last_name)
    if item.national_code:
        q |= Q(student__national_code=item.national_code)
    if item.phone:
        q |= Q(student__phone=item.phone)
    qs = ClassSlotEnrollment.objects.filter(q).select_related('student', 'class_slot')
    if item.misplaced_from_slot_id:
        return qs.filter(class_slot_id=item.misplaced_from_slot_id).first()
    return qs.filter(class_slot__term_id=item.term_id).exclude(is_carryover=True, carryover_confirmed=False).order_by('-created_at').first()


class UnregisteredMoveOptionsView(APIView):
    """
    GET: برای «انتقال کلاس» / «تغییر سطح» فردِ «در این کلاس نیست».
    بدون level: کلاس‌های هم‌سطح (سطح کلاس فعلی)؛ با level: کلاس‌های همان سطح.
    همیشه: همان ترم، همه‌ی روزهای هفته، فقط هم‌جنس یا مختلط. به‌علاوه فهرست سطح‌های دارای کلاس برای «تغییر سطح».
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not can_edit_menu(request.user, 'followups'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            item = UnregisteredStudent.objects.select_related('misplaced_from_slot').get(pk=pk)
        except UnregisteredStudent.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        enrollment = _misplaced_enrollment(item)
        if not enrollment:
            return Response({'error': 'ثبت‌نام فعلی این فرد در کلاس مبدأ پیدا نشد (شاید قبلاً جابجا شده است)'}, status=status.HTTP_404_NOT_FOUND)
        from class_management.models import ClassSlot
        from class_management.serializers import ClassSlotSerializer
        from class_management.views import _normalize_level, tuition_difference
        source = enrollment.class_slot
        gender = _gender_from_enrolled_slot(source)
        level = (request.query_params.get('level') or '').strip() or source.assigned_level or ''
        pool = [
            c for c in ClassSlot.objects.filter(term_id=source.term_id).exclude(pk=source.pk).order_by('number', 'day_type', 'time_slot')
            if _slot_gender_ok(c, gender)
        ]
        # همه‌ی سطوح استاندارد؛ available=False یعنی در این ترم (برای این جنسیت/مختلط) کلاسی با آن سطح نداریم
        from level_tests.models import StandardLevel
        have = {}
        for c in pool:
            if c.assigned_level:
                have.setdefault(_normalize_level(c.assigned_level), c.assigned_level)
        group_labels = dict(StandardLevel.AgeGroup.choices)
        all_levels, seen = [], set()
        for lv in StandardLevel.objects.all().order_by('age_group', 'order', 'code'):
            key = _normalize_level(lv.code)
            if key in seen:
                continue
            seen.add(key)
            all_levels.append({
                'value': have.get(key, lv.code), 'label': lv.code, 'group': lv.age_group,
                'group_label': group_labels.get(lv.age_group, lv.age_group), 'available': key in have,
            })
        for key, label in have.items():  # سطح‌هایی که کلاس دارند ولی جزو سطوح استاندارد نیستند
            if key not in seen:
                all_levels.append({'value': label, 'label': label, 'group': 'other', 'group_label': 'سایر', 'available': True})
        levels = [l['value'] for l in all_levels if l['available']]
        target = _normalize_level(level)
        classes = []
        for c in pool:
            if target and _normalize_level(c.assigned_level) != target:
                continue
            row = ClassSlotSerializer(c).data
            row['seats_left'] = c.real_seats_left
            diff = tuition_difference(enrollment, c)
            row['tuition_amount'] = diff['target_due']
            row['tuition_difference'] = diff['difference']
            row['tuition_message'] = diff['message']
            classes.append(row)
        return Response({
            'id': item.id, 'student_id': enrollment.student_id,
            'student_name': f'{item.first_name} {item.last_name}',
            'source_slot': source.id, 'source_number': source.number, 'source_level': source.assigned_level,
            'gender': gender, 'level': level, 'levels': levels, 'all_levels': all_levels, 'classes': classes,
        })


class UnregisteredMoveView(APIView):
    """
    POST {target_slot_id, change_level?, force_over_capacity?}: فرد از کلاس اشتباه به کلاس مقصد منتقل می‌شود
    (در لیست کلاسیِ مدیریت کلاس‌ها هم جابجا می‌شود) و از لیست ثبت‌نام‌نشده‌ها خارج می‌شود.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'followups'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from django.db import transaction
        from class_management.models import ClassSlot, ClassSlotEnrollment
        from class_management.views import _same_term_enrollments, _enrollment_class_label, tuition_difference
        with transaction.atomic():
            try:
                item = UnregisteredStudent.objects.select_for_update().get(pk=pk)
            except UnregisteredStudent.DoesNotExist:
                return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
            enrollment = _misplaced_enrollment(item)
            if not enrollment:
                return Response({'error': 'ثبت‌نام فعلی این فرد در کلاس مبدأ پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
            try:
                target = ClassSlot.objects.select_for_update().get(pk=request.data.get('target_slot_id'))
            except (ClassSlot.DoesNotExist, ValueError, TypeError):
                return Response({'error': 'کلاس مقصد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
            source = enrollment.class_slot
            student = enrollment.student
            if target.pk == source.pk:
                return Response({'error': 'کلاس مقصد نمی‌تواند همان کلاس فعلی باشد'}, status=status.HTTP_400_BAD_REQUEST)
            if not _slot_gender_ok(target, _gender_from_enrolled_slot(source)):
                return Response({'error': 'جنسیت این فرد با کلاس مقصد (دخترانه/پسرانه) مغایرت دارد؛ جابجایی انجام نشد'}, status=status.HTTP_400_BAD_REQUEST)
            force = str(request.data.get('force_over_capacity', '')).lower() in ('1', 'true', 'yes')
            if target.real_seats_left <= 0 and not force:
                return Response({'error': 'کلاس مقصد ظرفیت خالی ندارد', 'over_capacity': True}, status=status.HTTP_400_BAD_REQUEST)
            others = list(_same_term_enrollments(target, [student.id]).exclude(pk=enrollment.pk))
            if others:
                labels = '؛ '.join(_enrollment_class_label(o.class_slot) for o in others)
                return Response({'error': f'این فرد در همین ترم در {labels} هم ثبت‌نام دارد'}, status=status.HTTP_400_BAD_REQUEST)
            ClassSlotEnrollment.objects.create(
                class_slot=target, student=student,
                payment_method=enrollment.payment_method, tuition_amount=enrollment.tuition_amount,
                discount_percent=enrollment.discount_percent, pos_reference_code=enrollment.pos_reference_code,
                is_carryover=enrollment.is_carryover,
                carryover_confirmed=(enrollment.carryover_confirmed or (enrollment.is_carryover and source.term_id == target.term_id)),
                carried_from_term=enrollment.carried_from_term,
            )
            tuition_note = tuition_difference(enrollment, target)
            enrollment.delete()
            if str(request.data.get('change_level', '')).lower() in ('1', 'true', 'yes') and target.assigned_level:
                student.language_level = target.assigned_level
                student.save(update_fields=['language_level'])
                item.class_level = target.assigned_level
            item.status = UnregisteredStudent.Status.REGISTERED
            item.registered_at = timezone.now()
            item.save()
        return Response({
            'message': f'{item.first_name} {item.last_name} به کلاس {target.number} منتقل شد',
            'target_number': target.number, 'tuition_difference': tuition_note,
        })


class PersonFinanceStatusView(APIView):
    """
    برای پنجره‌ی «جستجو در میان کلیه دانش‌آموزان»: آیا فرد در ثبت‌نام‌نشده‌ها و/یا بدهکاران (همان ترم یا ترم‌های قبل‌تر که هنوز حل نشده) هست؟
    GET ?student_id=<id>&term_id=<id>
    """
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _unreg_row(u):
        from .serializers import _slot_desc, reported_candidates
        slot, cands, exact = reported_candidates(u)
        level = u.latest_level or u.class_level
        if slot:
            text = _slot_desc(slot)
        elif level and cands:
            text = f'سطح {level} — کلاس‌های محتمل: ' + ' | '.join(_slot_desc(c) for c in cands)
        else:
            text = f'سطح {level}' if level else ''
        return {
            'id': u.id, 'tuition_price': u.tuition_price, 'term_title': u.term_title,
            'app_class_text': text, 'app_class_exact': bool(slot or cands),
        }

    def get(self, request):
        from accounts.models import User
        from accounts.menu_permissions import can_view_menu
        if not (can_edit_menu(request.user, 'followups') or can_view_menu(request.user, 'followups')
                or can_edit_menu(request.user, 'class-management') or can_view_menu(request.user, 'class-management')):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        student = User.objects.filter(pk=request.query_params.get('student_id'), role='student').first()
        if not student:
            return Response({'unregistered': [], 'debtors': []})
        term_id = request.query_params.get('term_id')
        if student.national_code:
            person = Q(national_code=student.national_code)
        elif student.phone:
            person = Q(phone=student.phone, first_name=student.first_name, last_name=student.last_name)
        else:
            person = Q(first_name=student.first_name, last_name=student.last_name)
        dperson = Q(student_id=student.pk)
        if student.phone:
            dperson |= Q(phone=student.phone, first_name=student.first_name, last_name=student.last_name)
        unreg = UnregisteredStudent.objects.filter(person).exclude(status=UnregisteredStudent.Status.REGISTERED)
        debt = Debtor.objects.filter(dperson).exclude(status=Debtor.Status.SETTLED)
        if term_id:
            from class_management.models import Term
            term = Term.objects.filter(pk=term_id).first()
            if term:
                earlier = Term.objects.filter(Q(year__lt=term.year) | Q(year=term.year, term_number__lt=term.term_number))
                unreg = unreg.filter(Q(term_id=term.pk) | Q(term__in=earlier))
                debt = debt.filter(Q(term_id=term.pk) | Q(term__in=earlier))
        return Response({
            'unregistered': [self._unreg_row(u) for u in unreg.select_related('reported_slot', 'submitted_by')[:5]],
            'debtors': [{'id': d.id, 'debt_amount': d.debt_amount, 'term_title': d.term_title, 'awaiting_registration': d.awaiting_registration} for d in debt[:5]],
        })


class EmployeeFollowupDeadlineView(APIView):
    """تنظیم اختیاری موعد مشترک پنج نوع پیگیری برای یک ترم."""
    permission_classes = [IsAuthenticated]

    def _allowed(self, user):
        return can_edit_menu(user, 'followups') or can_edit_menu(user, 'new-leads')

    def _serialize(self, rule, term):
        from datetime import timedelta
        duration = max(1, (term.end_date - term.start_date).days + 1)
        week_count = max(1, (duration + 6) // 7)
        due = rule.resolved_deadline_at() if rule else None
        due_jalali = None
        if due:
            import jdatetime
            due_jalali = jdatetime.datetime.fromgregorian(datetime=timezone.localtime(due)).strftime('%Y/%m/%d - %H:%M')
        return {
            'term_id': term.pk, 'term_title': term.title,
            'enabled': bool(rule.enabled) if rule else False,
            'mode': rule.mode if rule else 'date',
            'deadline_date': rule.deadline_date.isoformat() if rule and rule.deadline_date else '',
            'deadline_time': str(rule.deadline_time)[:5] if rule and rule.deadline_time else '23:59',
            'deadline_week': rule.deadline_week if rule and rule.deadline_week else 1,
            'week_count': week_count,
            'due_at': due.isoformat() if due else '', 'due_at_jalali': due_jalali or '',
            'is_overdue': bool(due and due <= timezone.now()),
        }

    def get(self, request):
        if not self._allowed(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from class_management.models import Term
        term = Term.objects.filter(pk=request.query_params.get('term_id')).first()
        if not term:
            return Response({'error': 'ترم انتخاب‌شده پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        from .models import EmployeeFollowupDeadlineRule
        rule = EmployeeFollowupDeadlineRule.objects.filter(term=term).first()
        return Response(self._serialize(rule, term))

    def post(self, request):
        if not self._allowed(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from class_management.models import Term
        from .models import EmployeeFollowupDeadlineRule
        term = Term.objects.filter(pk=request.data.get('term_id')).first()
        if not term:
            return Response({'error': 'ترم انتخاب‌شده پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        enabled = str(request.data.get('enabled', '')).lower() in ('1', 'true', 'yes', 'on')
        mode = str(request.data.get('mode') or EmployeeFollowupDeadlineRule.Mode.DATE)
        if mode not in (EmployeeFollowupDeadlineRule.Mode.DATE, EmployeeFollowupDeadlineRule.Mode.TERM_WEEK):
            return Response({'error': 'مبنای ددلاین نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        duration = max(1, (term.end_date - term.start_date).days + 1)
        week_count = max(1, (duration + 6) // 7)
        due_date = None
        due_time = None
        due_week = None
        if enabled and mode == EmployeeFollowupDeadlineRule.Mode.DATE:
            from django.utils.dateparse import parse_date, parse_time
            due_date = parse_date(str(request.data.get('deadline_date') or ''))
            due_time = parse_time(str(request.data.get('deadline_time') or '23:59'))
            if not due_date or not due_time:
                return Response({'error': 'تاریخ و ساعت ددلاین را کامل وارد کنید'}, status=status.HTTP_400_BAD_REQUEST)
        elif enabled:
            try:
                due_week = int(request.data.get('deadline_week'))
            except (TypeError, ValueError):
                due_week = 0
            if due_week < 1 or due_week > week_count:
                return Response({'error': f'شماره هفته باید بین ۱ تا {week_count} باشد'}, status=status.HTTP_400_BAD_REQUEST)
            from datetime import time
            due_time = time(23, 59)
        rule, _ = EmployeeFollowupDeadlineRule.objects.get_or_create(term=term)
        rule.enabled = enabled
        rule.mode = mode
        rule.deadline_date = due_date
        if due_time is None:
            from datetime import time
            due_time = time(23, 59)
        rule.deadline_time = due_time
        rule.deadline_week = due_week
        rule.updated_by = request.user
        rule.save()
        return Response(self._serialize(rule, term))


class EmployeeFollowupProgressView(APIView):
    """تعداد کل و انجام‌شده‌ی پنج نوع پیگیری برای یک کارمند و ترم."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not (can_edit_menu(request.user, 'followups') or can_edit_menu(request.user, 'new-leads')):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        employee_id, term_id = request.query_params.get('employee_id'), request.query_params.get('term_id')
        if not employee_id or not term_id:
            return Response({'items': {}})
        try:
            employee_id, term_id = int(employee_id), int(term_id)
        except (TypeError, ValueError):
            return Response({'error': 'شناسه کارمند یا ترم نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        from class_management.models import ClassSurveyResponse, DropoutExtractFollowUp
        items = {}
        def add(key, total, completed):
            total, completed = int(total), min(int(completed), int(total))
            items[key] = {'total': total, 'completed': completed, 'percent': round(completed * 100 / total) if total else 0}
        waiting = NewLead.objects.filter(term_id=term_id, assigned_to_id=employee_id)
        add('waiting-list', waiting.exclude(status=NewLead.Status.CANCELLED).count(), waiting.filter(Q(followup1_at__isnull=False) | Q(registered_at__isnull=False)).count())
        unregistered = UnregisteredStudent.objects.filter(term_id=term_id, assigned_to_id=employee_id)
        add('unregistered', unregistered.exclude(status=UnregisteredStudent.Status.REGISTERED).count(), unregistered.filter(followups__isnull=False).distinct().count())
        debtors = Debtor.objects.filter(term_id=term_id, assigned_to_id=employee_id)
        add('debtors', debtors.exclude(status=Debtor.Status.SETTLED).count(), debtors.filter(followups__isnull=False).distinct().count())
        dropout = DropoutExtractFollowUp.objects.filter(term_id=term_id, assigned_to_id=employee_id)
        add('consecutive-dropouts', dropout.exclude(not_coming=True).count(), dropout.filter(Q(contacted=True) | Q(not_coming=True)).count())
        survey = ClassSurveyResponse.objects.filter(survey_list__term_id=term_id, assigned_to_id=employee_id)
        add('class-survey', survey.count(), survey.filter(completed=True).count())
        return Response({'employee_id': employee_id, 'term_id': term_id, 'items': items})


class EmployeeFollowupTermListView(APIView):
    """فهرست ترم‌ها برای Hub پیگیری، با همان مجوزهای دسترسی به پیگیری‌ها."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not (can_edit_menu(request.user, 'followups') or can_edit_menu(request.user, 'new-leads')):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from class_management.models import Term
        return Response([
            {
                'id': term.id, 'year': term.year, 'term_number': term.term_number,
                'title': term.title, 'start_date': term.start_date.isoformat(),
                'end_date': term.end_date.isoformat(),
                'start_date_jalali': term.start_date_jalali,
                'end_date_jalali': term.end_date_jalali,
            }
            for term in Term.objects.all().order_by('-start_date', '-id')
        ])
