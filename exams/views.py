from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.menu_permissions import can_edit_menu, can_view_menu
from class_management.models import ClassSlot, ClassSlotEnrollment

from . import services
from .ai_grading import AIGradingNotConfigured, grade_writing
from .models import GRADE_FIELD_FOR_KIND, ExamAttempt, ExamQuestion, WritingPrompt
from .serializers import (
    ExamAttemptAdminSerializer, ExamAttemptSummarySerializer, ExamAttemptTakeSerializer,
    ExamQuestionSerializer, WritingPromptSerializer,
)

SUBMIT_GRACE_SECONDS = 60


def _normalize_question_payload(data):
    """
    وقتی درخواست multipart باشد (برای آپلود فایل صوتی)، فیلدهای JSON (choices,
    correct_answer) و is_active به‌صورت رشته می‌رسند؛ اینجا به نوع واقعی برمی‌گردند.
    خروجی یک dict معمولی است (نه QueryDict) تا DRF serializer ساده مصرفش کند.
    """
    import json
    payload = {key: data.get(key) for key in data.keys()}
    for key in ('choices', 'correct_answer'):
        value = payload.get(key)
        if isinstance(value, str):
            try:
                payload[key] = json.loads(value)
            except ValueError:
                pass
    if isinstance(payload.get('is_active'), str):
        payload['is_active'] = payload['is_active'].lower() in ('true', '1', 'yes', 'on')
    return payload


def _has_bank_access(user):
    return can_view_menu(user, 'exam-question-bank') or getattr(user, 'role', None) == 'admin'


def _can_edit_bank(user):
    return can_edit_menu(user, 'exam-question-bank')


def _teacher_owns_class(user, class_slot):
    from accounts.models import User
    if getattr(user, 'role', None) not in User.TEACHER_LIKE_ROLES:
        return False
    teacher_full_name = user.get_full_name().strip()
    return bool(teacher_full_name) and class_slot.teacher_name.strip().lower() == teacher_full_name.lower()


# ---------------------------------------------------------------- مخزن سوالات

class ExamQuestionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _has_bank_access(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        qs = ExamQuestion.objects.select_related('level').all()
        level = request.query_params.get('level')
        exam_kind = request.query_params.get('exam_kind')
        if level:
            qs = qs.filter(level_id=level)
        if exam_kind:
            qs = qs.filter(exam_kind=exam_kind)
        return Response(ExamQuestionSerializer(qs, many=True).data)

    def post(self, request):
        if not _can_edit_bank(request.user):
            return Response({'error': 'دسترسی ویرایش ندارید'}, status=status.HTTP_403_FORBIDDEN)
        serializer = ExamQuestionSerializer(data=_normalize_question_payload(request.data))
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ExamQuestionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if not _can_edit_bank(request.user):
            return Response({'error': 'دسترسی ویرایش ندارید'}, status=status.HTTP_403_FORBIDDEN)
        obj = ExamQuestion.objects.filter(pk=pk).first()
        if not obj:
            return Response({'error': 'سوال پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ExamQuestionSerializer(obj, data=_normalize_question_payload(request.data), partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        if not _can_edit_bank(request.user):
            return Response({'error': 'دسترسی ویرایش ندارید'}, status=status.HTTP_403_FORBIDDEN)
        ExamQuestion.objects.filter(pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WritingPromptListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _has_bank_access(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        qs = WritingPrompt.objects.select_related('level').all()
        level = request.query_params.get('level')
        exam_kind = request.query_params.get('exam_kind')
        if level:
            qs = qs.filter(level_id=level)
        if exam_kind:
            qs = qs.filter(exam_kind=exam_kind)
        return Response(WritingPromptSerializer(qs, many=True).data)

    def post(self, request):
        if not _can_edit_bank(request.user):
            return Response({'error': 'دسترسی ویرایش ندارید'}, status=status.HTTP_403_FORBIDDEN)
        serializer = WritingPromptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class WritingPromptDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if not _can_edit_bank(request.user):
            return Response({'error': 'دسترسی ویرایش ندارید'}, status=status.HTTP_403_FORBIDDEN)
        obj = WritingPrompt.objects.filter(pk=pk).first()
        if not obj:
            return Response({'error': 'موضوع رایتینگ پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        serializer = WritingPromptSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        if not _can_edit_bank(request.user):
            return Response({'error': 'دسترسی ویرایش ندارید'}, status=status.HTTP_403_FORBIDDEN)
        WritingPrompt.objects.filter(pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExamLevelChoicesView(APIView):
    """فهرست سطوح استاندارد برای فیلتر مخزن سوالات (تفکیک بر اساس رده سنی هم مشخص است)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _has_bank_access(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from level_tests.models import StandardLevel
        levels = StandardLevel.objects.all().order_by('age_group', 'order', 'code')
        return Response([
            {
                'id': l.id, 'code': l.code, 'age_group': l.age_group, 'age_group_display': l.get_age_group_display(),
                'book': l.book, 'midterm_units': l.midterm_units, 'final_units': l.final_units,
            }
            for l in levels
        ])


# --------------------------------------------------------------- دانش‌آموز

class MyExamsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = request.user
        if student.role != 'student':
            return Response({'error': 'این بخش فقط برای دانش‌آموزان است'}, status=status.HTTP_403_FORBIDDEN)
        class_slots = ClassSlot.objects.filter(
            enrollments__student=student, enrollments__payment_verified=True,
        ).distinct()
        attempts = []
        for slot in class_slots:
            attempts.extend(services.sync_student_class_attempts(student, slot))
        attempts.sort(key=lambda a: a.window_opens_at, reverse=True)
        return Response(ExamAttemptSummarySerializer(attempts, many=True).data)


class ExamAttemptDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        attempt = ExamAttempt.objects.filter(pk=pk, student=request.user).first()
        if not attempt:
            return Response({'error': 'آزمون پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        attempt.refresh_expiry()
        attempt.save()
        if attempt.status in (ExamAttempt.Status.IN_PROGRESS, ExamAttempt.Status.AVAILABLE):
            return Response(ExamAttemptTakeSerializer(attempt).data)
        return Response(ExamAttemptSummarySerializer(attempt).data)


class ExamAttemptStartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        attempt = ExamAttempt.objects.filter(pk=pk, student=request.user).first()
        if not attempt:
            return Response({'error': 'آزمون پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        attempt.refresh_expiry()
        if attempt.status == ExamAttempt.Status.EXPIRED:
            attempt.save()
            return Response({'error': 'مهلت این آزمون به پایان رسیده است'}, status=status.HTTP_400_BAD_REQUEST)
        if attempt.status != ExamAttempt.Status.AVAILABLE:
            return Response({'error': 'این آزمون قبلاً شروع یا ثبت شده است'}, status=status.HTTP_400_BAD_REQUEST)
        from .models import EXAM_TIME_LIMIT_MINUTES
        now = timezone.now()
        attempt.status = ExamAttempt.Status.IN_PROGRESS
        attempt.started_at = now
        attempt.deadline_at = now + timezone.timedelta(minutes=EXAM_TIME_LIMIT_MINUTES)
        attempt.save()
        return Response(ExamAttemptTakeSerializer(attempt).data)


class ExamAttemptSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        attempt = ExamAttempt.objects.filter(pk=pk, student=request.user).first()
        if not attempt:
            return Response({'error': 'آزمون پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        if attempt.status != ExamAttempt.Status.IN_PROGRESS:
            return Response({'error': 'این آزمون در حال برگزاری نیست'}, status=status.HTTP_400_BAD_REQUEST)
        now = timezone.now()
        if attempt.deadline_at and now > attempt.deadline_at + timezone.timedelta(seconds=SUBMIT_GRACE_SECONDS):
            attempt.auto_submit()
            return Response(ExamAttemptSummarySerializer(attempt).data)

        if attempt.is_quiz_kind:
            answers = request.data.get('answers', {})
            if not isinstance(answers, dict):
                return Response({'error': 'قالب پاسخ‌ها نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
            attempt.answers = {str(k): v for k, v in answers.items()}
            attempt.submitted_at = now
            attempt.grade_quiz()
            attempt.save()
        else:
            writing_text = (request.data.get('writing_text') or '').strip()
            attempt.writing_text = writing_text
            attempt.status = ExamAttempt.Status.SUBMITTED
            attempt.submitted_at = now
            try:
                result = grade_writing(attempt.writing_prompt_snapshot, writing_text)
                attempt.ai_score = result['score']
                attempt.ai_corrections = result['corrections']
                attempt.auto_score = result['score']
                attempt.ai_graded_at = timezone.now()
                attempt.status = ExamAttempt.Status.GRADED
            except AIGradingNotConfigured as exc:
                attempt.ai_error = str(exc)
            except Exception as exc:  # noqa: BLE001 — هر خطای غیرمنتظره‌ی AI نباید ثبت رایتینگ را خراب کند
                attempt.ai_error = f'خطا در تصحیح هوشمند: {exc}'
            attempt.save()

        return Response(ExamAttemptSummarySerializer(attempt).data)


# ------------------------------------------------------------------ استاد

class TeacherWritingReviewView(APIView):
    """مشاهده‌ی فقط‌خواندنیِ رایتینگ‌های کلاسِ خودِ استاد — بدون امکان نمره‌دهی."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        class_slot_id = request.query_params.get('class_slot')
        if not class_slot_id:
            return Response({'error': 'کلاس را انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
        class_slot = ClassSlot.objects.filter(pk=class_slot_id).first()
        if not class_slot:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        if not _teacher_owns_class(request.user, class_slot):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        attempts = ExamAttempt.objects.filter(
            class_slot=class_slot, kind__in=[ExamAttempt.Kind.WRITING1, ExamAttempt.Kind.WRITING2],
        ).exclude(status=ExamAttempt.Status.AVAILABLE).select_related('student').order_by('-submitted_at')
        return Response(ExamAttemptAdminSerializer(attempts, many=True).data)


# ------------------------------------------------------------------- ادمین

class AdminClassAttemptsView(APIView):
    """
    فهرست تلاش‌های یک کلاس برای یک نوع آزمون — برای مرور/تصحیح دستی قبل از
    انتقال به سیستم نمرات. برای دانش‌آموزهایی که هنوز رکورد ندارند (چون
    پنجره‌شان باز نشده)، چیزی نشان داده نمی‌شود — طبیعی است.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, class_slot_id):
        if not can_view_menu(request.user, 'grading'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        class_slot = ClassSlot.objects.filter(pk=class_slot_id).first()
        if not class_slot:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        kind = request.query_params.get('kind')
        qs = ExamAttempt.objects.filter(class_slot=class_slot).select_related('student')
        if kind:
            qs = qs.filter(kind=kind)
        return Response(ExamAttemptAdminSerializer(qs, many=True).data)


class AdminAttemptUpdateView(APIView):
    """ویرایش دستی نمره‌ی یک تلاش (مثلاً وقتی AI وصل نیست و ادمین خودش رایتینگ را می‌خواند)."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if not can_edit_menu(request.user, 'grading'):
            return Response({'error': 'دسترسی ویرایش ندارید'}, status=status.HTTP_403_FORBIDDEN)
        attempt = ExamAttempt.objects.filter(pk=pk).first()
        if not attempt:
            return Response({'error': 'تلاش پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        if 'admin_override_score' in request.data:
            value = request.data['admin_override_score']
            attempt.admin_override_score = None if value in (None, '') else max(0, min(100, int(value)))
            if attempt.status == ExamAttempt.Status.SUBMITTED:
                attempt.status = ExamAttempt.Status.GRADED
            attempt.save()
        return Response(ExamAttemptAdminSerializer(attempt).data)


class AdminAttemptRetryAIView(APIView):
    """بعد از وصل‌شدن کلید API، برای رایتینگ‌هایی که قبلاً با خطا مواجه شده بودند."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'grading'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        attempt = ExamAttempt.objects.filter(pk=pk).first()
        if not attempt or attempt.is_quiz_kind:
            return Response({'error': 'تلاش رایتینگ پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        try:
            result = grade_writing(attempt.writing_prompt_snapshot, attempt.writing_text)
            attempt.ai_score = result['score']
            attempt.ai_corrections = result['corrections']
            attempt.auto_score = result['score']
            attempt.ai_graded_at = timezone.now()
            attempt.ai_error = ''
            attempt.status = ExamAttempt.Status.GRADED
            attempt.save()
        except AIGradingNotConfigured as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            return Response({'error': f'خطا در تصحیح هوشمند: {exc}'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ExamAttemptAdminSerializer(attempt).data)


class AdminSyncToGradesView(APIView):
    """نمرات تصحیح‌شده‌ی این کلاس/نوع را داخل StudentGrade می‌ریزد (نه قطعی — فقط پرکردن فیلد)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, class_slot_id):
        if not can_edit_menu(request.user, 'grading'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        class_slot = ClassSlot.objects.filter(pk=class_slot_id).first()
        if not class_slot:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        kind = request.data.get('kind')
        if kind not in GRADE_FIELD_FOR_KIND:
            return Response({'error': 'نوع آزمون نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)

        from grading.models import StudentGrade
        field_name = GRADE_FIELD_FOR_KIND[kind]
        attempts = ExamAttempt.objects.filter(
            class_slot=class_slot, kind=kind, status=ExamAttempt.Status.GRADED,
        )

        synced, skipped = [], []
        with transaction.atomic():
            for attempt in attempts:
                score = attempt.score_for_grade
                if score is None:
                    continue
                # مقیاس‌بندی از ۰..۱۰۰ به سهم واقعیِ این فیلد طبق تنظیم فیلدهای نمره
                from grading.models import GradeFieldSetting
                field_key = kind
                grade, _created = StudentGrade.objects.get_or_create(
                    class_slot=class_slot, student=attempt.student, defaults={'term': class_slot.term},
                )
                if not grade.is_editable:
                    skipped.append(attempt.student_id)
                    continue
                grade.refresh_snapshot()
                field_setting = GradeFieldSetting.objects.filter(age_group=grade.age_group, field_key=field_key).first()
                max_score = field_setting.max_score if field_setting else 100
                setattr(grade, field_name, round(score / 100 * max_score))
                grade.entered_by = request.user
                grade.apply_computation()
                grade.save()
                attempt.synced_to_grade_at = timezone.now()
                attempt.save()
                synced.append(attempt.id)

        return Response({'synced_attempt_ids': synced, 'skipped_locked_student_ids': skipped})
