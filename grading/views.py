from django.db import transaction
from django.db.models import Q, Count
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.menu_permissions import can_edit_menu, can_view_menu
from class_management.models import ClassSlot, ClassSlotEnrollment, Term, infer_age_group_from_level
from class_management.serializers import TermSerializer

from .models import GradeFieldSetting, GradePassingSetting, StudentGrade, FIELD_KEYS, ensure_default_grade_settings
from .serializers import (
    GradeFieldSettingSerializer, GradePassingSettingSerializer,
    StudentGradeSerializer, StudentGradeUpsertItemSerializer,
)

User = get_user_model()

FIELD_SCORE_ATTR = {
    'cp': 'cp_score',
    'midterm': 'midterm_score',
    'writing1': 'writing1_score',
    'writing2': 'writing2_score',
    'final': 'final_score',
}


def _has_grading_access(user):
    """دسترسی مدیریتی (پنل ادمین) به این بخش — مدیر/اداری/آموزش طبق تنظیمات دسترسی."""
    return can_view_menu(user, 'grading') or getattr(user, 'role', None) == 'admin'


def _can_edit_grading(user):
    return can_edit_menu(user, 'grading')


def _teacher_owns_class(user, class_slot):
    if getattr(user, 'role', None) not in User.TEACHER_LIKE_ROLES:
        return False
    teacher_full_name = user.get_full_name().strip()
    return bool(teacher_full_name) and class_slot.teacher_name.strip().lower() == teacher_full_name.lower()


class GradeFieldSettingListView(APIView):
    """
    GET  /api/grading/field-settings/            -> همه‌ی ۱۵ ردیف (۳ رده سنی × ۵ فیلد)
    PATCH /api/grading/field-settings/            -> ویرایش گروهی: [{id, title, is_active, max_score, order}, ...]
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _has_grading_access(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        ensure_default_grade_settings()
        qs = GradeFieldSetting.objects.all().order_by('age_group', 'order')
        return Response(GradeFieldSettingSerializer(qs, many=True).data)

    def patch(self, request):
        if not _can_edit_grading(request.user):
            return Response({'error': 'دسترسی ویرایش ندارید'}, status=status.HTTP_403_FORBIDDEN)
        ensure_default_grade_settings()
        items = request.data if isinstance(request.data, list) else request.data.get('items', [])
        updated = []
        with transaction.atomic():
            for item in items:
                try:
                    obj = GradeFieldSetting.objects.get(pk=item.get('id'))
                except (GradeFieldSetting.DoesNotExist, TypeError, ValueError):
                    continue
                if 'title' in item and str(item['title']).strip():
                    obj.title = str(item['title']).strip()
                if 'is_active' in item:
                    obj.is_active = bool(item['is_active'])
                if 'max_score' in item:
                    try:
                        obj.max_score = max(0, int(item['max_score']))
                    except (TypeError, ValueError):
                        pass
                if 'order' in item:
                    try:
                        obj.order = int(item['order'])
                    except (TypeError, ValueError):
                        pass
                obj.save()
                updated.append(obj)
        qs = GradeFieldSetting.objects.all().order_by('age_group', 'order')
        return Response(GradeFieldSettingSerializer(qs, many=True).data)


class GradePassingSettingListView(APIView):
    """
    GET   /api/grading/passing-settings/          -> ۳ ردیف (به تفکیک رده سنی)
    PATCH /api/grading/passing-settings/           -> [{id, passing_score}, ...]
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _has_grading_access(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        ensure_default_grade_settings()
        qs = GradePassingSetting.objects.all().order_by('age_group')
        return Response(GradePassingSettingSerializer(qs, many=True).data)

    def patch(self, request):
        if not _can_edit_grading(request.user):
            return Response({'error': 'دسترسی ویرایش ندارید'}, status=status.HTTP_403_FORBIDDEN)
        ensure_default_grade_settings()
        items = request.data if isinstance(request.data, list) else request.data.get('items', [])
        with transaction.atomic():
            for item in items:
                try:
                    obj = GradePassingSetting.objects.get(pk=item.get('id'))
                    obj.passing_score = max(0, min(100, int(item.get('passing_score', obj.passing_score))))
                    obj.save()
                except (GradePassingSetting.DoesNotExist, TypeError, ValueError):
                    continue
        qs = GradePassingSetting.objects.all().order_by('age_group')
        return Response(GradePassingSettingSerializer(qs, many=True).data)


class GradingTermListView(APIView):
    """GET /api/grading/terms/ — فهرست ترم‌ها برای فیلد انتخاب ترم بالای صفحه"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _has_grading_access(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        terms = Term.objects.all().order_by('-year', '-term_number')
        return Response(TermSerializer(terms, many=True).data)


class GradingClassListView(APIView):
    """
    GET /api/grading/classes/?term=<id>&day_type=&q=&student_query=
    فهرست کلاس‌های یک ترم برای بخش «ثبت و ویرایش نمرات» — با فیلتر روز، سرچ آزاد
    (شماره کلاس/نام استاد/سطح) و سرچ دانش‌آموز (نام یا کد ملی، برای پیداکردن کلاسی که
    آن دانش‌آموز در آن ثبت‌نام است).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _has_grading_access(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        term_id = request.query_params.get('term')
        if not term_id:
            return Response({'error': 'ترم را انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
        term = Term.objects.filter(pk=term_id).first()
        if not term:
            return Response({'error': 'ترم پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        qs = ClassSlot.objects.filter(term=term)

        day_type = request.query_params.get('day_type')
        if day_type:
            qs = qs.filter(day_type=day_type)

        q = (request.query_params.get('q') or '').strip()
        if q:
            qs = qs.filter(
                Q(teacher_name__icontains=q) | Q(assigned_level__icontains=q) | Q(number__icontains=q)
            )

        student_query = (request.query_params.get('student_query') or '').strip()
        if student_query:
            qs = qs.filter(
                Q(enrollments__payment_verified=True) & (
                    Q(enrollments__student__first_name__icontains=student_query) |
                    Q(enrollments__student__last_name__icontains=student_query) |
                    Q(enrollments__student__national_code__icontains=student_query)
                )
            ).distinct()

        qs = qs.order_by('day_type', 'time_slot', 'number')

        result = []
        for c in qs:
            grade_count = StudentGrade.objects.filter(class_slot=c).count()
            finalized_count = StudentGrade.objects.filter(class_slot=c, is_finalized=True).count()
            enrolled = c.real_enrolled_count
            result.append({
                'id': c.id,
                'number': c.number,
                'day_type_display': c.day_type_display,
                'time_slot': c.time_slot,
                'assigned_level': c.assigned_level,
                'teacher_name': c.teacher_name,
                'gender_display': c.get_gender_display(),
                'enrolled_count': enrolled,
                'grade_entered_count': grade_count,
                'grade_finalized_count': finalized_count,
                'is_fully_finalized': enrolled > 0 and finalized_count >= enrolled,
            })
        return Response({'term': TermSerializer(term).data, 'classes': result})


def _serialize_field_settings(age_group):
    ensure_default_grade_settings()
    fields = GradeFieldSetting.objects.filter(age_group=age_group).order_by('order') if age_group else \
        GradeFieldSetting.objects.none()
    passing = GradePassingSetting.objects.filter(age_group=age_group).first() if age_group else None
    return {
        'fields': GradeFieldSettingSerializer(fields, many=True).data,
        'passing_score': passing.passing_score if passing else 60,
    }


class GradingClassRosterView(APIView):
    """
    GET  /api/grading/classes/<id>/roster/   -> اطلاعات کلاس + تنظیمات فیلد نمره‌ی رده سنی‌اش + لیست نمرات
    برای استاد در اپ هم همین endpoint استفاده می‌شود (چک مالکیت کلاس انجام می‌شود).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        class_slot = ClassSlot.objects.filter(pk=pk).first()
        if not class_slot:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        if not (_has_grading_access(request.user) or _teacher_owns_class(request.user, class_slot)):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        age_group = infer_age_group_from_level(class_slot.assigned_level) or ''

        enrollments = ClassSlotEnrollment.objects.filter(
            class_slot=class_slot, payment_verified=True
        ).select_related('student').order_by('student__first_name', 'student__last_name')

        grades = []
        for e in enrollments:
            grade, _created = StudentGrade.objects.get_or_create(
                class_slot=class_slot, student=e.student,
                defaults={'term': class_slot.term, 'entered_by': request.user},
            )
            if not grade.age_group:
                grade.apply_computation()
                grade.save()
            grades.append(grade)

        return Response({
            'class_slot': {
                'id': class_slot.id, 'number': class_slot.number,
                'day_type_display': class_slot.day_type_display, 'time_slot': class_slot.time_slot,
                'assigned_level': class_slot.assigned_level, 'age_group': age_group,
                'teacher_name': class_slot.teacher_name,
                'term_title': class_slot.term.title if class_slot.term else '',
            },
            'field_settings': _serialize_field_settings(age_group),
            'grades': StudentGradeSerializer(grades, many=True).data,
        })


class GradingClassSaveView(APIView):
    """
    POST /api/grading/classes/<id>/save/
    body: {"grades": [{"student_id": 1, "cp_score": 8, "midterm_score": 15, ...}, ...]}
    ثبت/ویرایش نمرات یک کلاس — هم برای پنل ادمین (اداری/آموزش) و هم اپ استاد (فقط کلاس خودش).
    رکوردهای قطعی‌شده‌ی قبول‌شده قابل ویرایش نیستند (is_editable=False).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        class_slot = ClassSlot.objects.filter(pk=pk).first()
        if not class_slot:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        is_admin_side = _can_edit_grading(request.user)
        is_teacher_side = _teacher_owns_class(request.user, class_slot)
        if not (is_admin_side or is_teacher_side):
            return Response({'error': 'دسترسی ثبت نمره ندارید'}, status=status.HTTP_403_FORBIDDEN)

        items = request.data.get('grades', [])
        serializer = StudentGradeUpsertItemSerializer(data=items, many=True)
        serializer.is_valid(raise_exception=True)

        saved, skipped_locked = [], []
        with transaction.atomic():
            for item in serializer.validated_data:
                enrollment = ClassSlotEnrollment.objects.filter(
                    class_slot=class_slot, student_id=item['student_id'], payment_verified=True
                ).first()
                if not enrollment:
                    continue
                grade, _created = StudentGrade.objects.get_or_create(
                    class_slot=class_slot, student_id=item['student_id'],
                    defaults={'term': class_slot.term},
                )
                if not grade.is_editable:
                    skipped_locked.append(item['student_id'])
                    continue
                for field_key, attr in FIELD_SCORE_ATTR.items():
                    if attr in item:
                        setattr(grade, attr, item[attr])
                grade.entered_by = request.user
                grade.apply_computation()
                grade.save()
                saved.append(grade)

        return Response({
            'saved': StudentGradeSerializer(saved, many=True).data,
            'skipped_locked_student_ids': skipped_locked,
        })


class GradingClassFinalizeView(APIView):
    """
    POST /api/grading/classes/<id>/finalize/
    قطعی‌کردن نمرات کل کلاس یکجا — فقط برای اداری/آموزش/مدیر (نه استاد در اپ).
    رکوردهای fail بعد از قطعی‌شدن هم قابل ویرایش می‌مانند (برای اصلاح بعدی).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _can_edit_grading(request.user):
            return Response({'error': 'فقط اداری/آموزش می‌توانند نمرات را قطعی کنند'}, status=status.HTTP_403_FORBIDDEN)
        class_slot = ClassSlot.objects.filter(pk=pk).first()
        if not class_slot:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        grades = StudentGrade.objects.filter(class_slot=class_slot)
        now = timezone.now()
        finalized = []
        with transaction.atomic():
            for grade in grades:
                grade.apply_computation()
                grade.is_finalized = True
                grade.finalized_by = request.user
                grade.finalized_at = now
                grade.save()
                finalized.append(grade)
        return Response({'finalized': StudentGradeSerializer(finalized, many=True).data})


class TeacherMyGradingClassesView(APIView):
    """
    GET /api/grading/my-classes/?term=
    برای اپ استاد: کلاس‌های ترمیک خودِ استاد در ترم انتخابی (پیش‌فرض ترم جاری) —
    همان الگوی تطبیق نام با TeacherTermClassesView.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in User.TEACHER_LIKE_ROLES:
            return Response({'error': 'این بخش فقط برای اساتید است'}, status=status.HTTP_403_FORBIDDEN)

        term_id = request.query_params.get('term')
        term = Term.objects.filter(pk=term_id).first() if term_id else None
        if not term:
            today = timezone.now().date()
            term = Term.objects.filter(start_date__lte=today, end_date__gte=today).order_by('-start_date').first()
        if not term:
            term = Term.objects.order_by('-year', '-term_number').first()
        if not term:
            return Response({'term': None, 'terms': [], 'classes': []})

        teacher_full_name = request.user.get_full_name().strip()
        slots = ClassSlot.objects.filter(term=term, teacher_name__iexact=teacher_full_name).order_by(
            'day_type', 'time_slot', 'number'
        )
        result = []
        for s in slots:
            grade_count = StudentGrade.objects.filter(class_slot=s).count()
            finalized_count = StudentGrade.objects.filter(class_slot=s, is_finalized=True).count()
            result.append({
                'id': s.id, 'number': s.number, 'day_type_display': s.day_type_display,
                'time_slot': s.time_slot, 'assigned_level': s.assigned_level,
                'enrolled_count': s.real_enrolled_count,
                'grade_entered_count': grade_count, 'grade_finalized_count': finalized_count,
            })
        all_terms = Term.objects.filter(
            class_slots__teacher_name__iexact=teacher_full_name
        ).distinct().order_by('-year', '-term_number')
        return Response({
            'term': TermSerializer(term).data,
            'terms': TermSerializer(all_terms, many=True).data,
            'classes': result,
        })


class StudentMyGradesView(APIView):
    """
    GET /api/grading/my-grades/?term=
    برای اپ دانش‌آموز — بخش «مشاهده سوابق تحصیلی»: فقط نمرات قطعی‌شده نمایش داده می‌شود.
    اگر term داده نشود، فهرست همه‌ی ترم‌هایی که نمره‌ی قطعی‌شده دارد + نمرات جدیدترین ترم برگردانده می‌شود.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'student':
            return Response({'error': 'این بخش فقط برای دانش‌آموزان است'}, status=status.HTTP_403_FORBIDDEN)

        base_qs = StudentGrade.objects.filter(student=request.user, is_finalized=True).select_related(
            'class_slot', 'term'
        )
        available_terms = Term.objects.filter(
            student_grades__student=request.user, student_grades__is_finalized=True
        ).distinct().order_by('-year', '-term_number')

        term_id = request.query_params.get('term')
        term = available_terms.filter(pk=term_id).first() if term_id else available_terms.first()

        grades = base_qs.filter(term=term) if term else base_qs.none()

        involved_age_groups = sorted({g.age_group for g in grades if g.age_group})
        field_settings_by_age_group = {
            ag: GradeFieldSettingSerializer(
                GradeFieldSetting.objects.filter(age_group=ag).order_by('order'), many=True
            ).data
            for ag in involved_age_groups
        }

        return Response({
            'terms': TermSerializer(available_terms, many=True).data,
            'selected_term': TermSerializer(term).data if term else None,
            'grades': StudentGradeSerializer(grades, many=True).data,
            'field_settings_by_age_group': field_settings_by_age_group,
        })


class StudentAcademicHistoryView(APIView):
    """
    GET /api/grading/students/<student_id>/history/
    برای پنل ادمین — بخش «سوابق تحصیلی» در پروفایل دانش‌آموز: همه‌ی نمرات قطعی‌شده‌ی
    این دانش‌آموز در تمام ترم‌ها/کلاس‌ها، برای مشاهده‌ی مدیر/اداری/آموزش.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        if not _has_grading_access(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        student = User.objects.filter(pk=student_id, role='student').first()
        if not student:
            return Response({'error': 'دانش‌آموز پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        grades = StudentGrade.objects.filter(student=student, is_finalized=True).select_related(
            'class_slot', 'term'
        ).order_by('-term__year', '-term__term_number')

        return Response({
            'student_id': student.id,
            'student_name': student.get_full_name(),
            'grades': StudentGradeSerializer(grades, many=True).data,
        })
