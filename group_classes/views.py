from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Q
from django.core.exceptions import ValidationError as DjangoValidationError
from accounts.models import User
from accounts.validators import username_validator, password_validator
from notifications.utils import send_notification
from .models import (
    GroupSession, GroupSessionParticipant, GroupSessionMeeting, GroupPriceSetting,
    GroupSessionAttendance, ensure_meetings, ensure_attendance_rows,
)
from .serializers import (
    GroupSessionAdminSerializer,
    GroupSessionCreateSerializer,
    GroupSessionTeacherSerializer,
    GroupSessionStudentSerializer,
    GroupSessionMeetingSerializer,
    GroupSessionMeetingDetailSerializer,
    ParticipantSerializer,
    GroupPriceSettingSerializer,
    AttendanceSerializer,
)


def _serializer_for(request, instance=None, many=False):
    role = request.user.role
    if role in ('admin', 'evaluator'):
        return GroupSessionAdminSerializer
    if role in User.TEACHER_LIKE_ROLES:
        return GroupSessionTeacherSerializer
    return GroupSessionStudentSerializer


class GroupSessionListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.role in ('admin', 'evaluator'):
            qs = GroupSession.objects.all()
        elif user.role in User.TEACHER_LIKE_ROLES:
            qs = GroupSession.objects.filter(Q(assigned_teachers=user) | Q(teacher=user)).distinct()
        else:
            qs = GroupSession.objects.filter(Q(status=GroupSession.Status.OPEN) | Q(participants__student=user)).distinct()
        qs = qs.order_by('-created_at')
        serializer_cls = _serializer_for(request)
        return Response(serializer_cls(qs, many=True, context={'request': request}).data)

    def post(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تواند جلسه‌ی گروهی بسازد'}, status=status.HTTP_403_FORBIDDEN)
        serializer = GroupSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group_session = serializer.save(created_by=request.user)
        return Response(GroupSessionAdminSerializer(group_session, context={'request': request}).data, status=status.HTTP_201_CREATED)


class GroupSessionDetailView(APIView):
    """
    گزارش‌گیری/ویرایش/حذف: مدیر روی هر جلسه‌ای، مدیر آموزش هم مثل مدیر (فقط دسترسی گزارشی —
    اکشن‌های گردش‌کاری مثل ارجاع/تایید/پرداخت جدا هستند و فقط مدیر می‌تواند آن‌ها را بزند).
    """
    permission_classes = [IsAuthenticated]

    def _get(self, request, pk):
        user = request.user
        if user.role in ('admin', 'evaluator'):
            qs = GroupSession.objects.all()
        elif user.role in User.TEACHER_LIKE_ROLES:
            qs = GroupSession.objects.filter(Q(assigned_teachers=user) | Q(teacher=user)).distinct()
        else:
            qs = GroupSession.objects.filter(Q(status=GroupSession.Status.OPEN) | Q(participants__student=user)).distinct()
        return qs.get(pk=pk)

    def get(self, request, pk):
        try:
            group_session = self._get(request, pk)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        serializer_cls = _serializer_for(request)
        return Response(serializer_cls(group_session, context={'request': request}).data)

    def patch(self, request, pk):
        if request.user.role not in ('admin', 'evaluator'):
            return Response({'error': 'فقط مدیر یا مدیر آموزش می‌تواند ویرایش کند'}, status=status.HTTP_403_FORBIDDEN)
        try:
            group_session = GroupSession.objects.get(pk=pk)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        serializer = GroupSessionAdminSerializer(group_session, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        if request.user.role not in ('admin', 'evaluator'):
            return Response({'error': 'فقط مدیر یا مدیر آموزش می‌تواند حذف کند'}, status=status.HTTP_403_FORBIDDEN)
        try:
            group_session = GroupSession.objects.get(pk=pk)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        group_session.delete()
        return Response({'message': 'حذف شد'})


class JoinGroupSessionView(APIView):
    """
    ثبت‌نام یک نفر در جلسه‌ی گروهی — هم از وب (مدیر، با اطلاعات دانش‌آموز) هم از اپ (خودِ دانش‌آموز).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            group_session = GroupSession.objects.get(pk=pk)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        is_staff = user.role in ('admin', 'evaluator')

        # مدیر/مسئول آموزش می‌توانند در هر وضعیتی (حتی بعد از بسته‌شدن ثبت‌نام یا تایید نهایی) نفر
        # اضافه کنند — چون ممکن است بعد از شروع دوره هم لازم باشد کسی به کلاس اضافه شود.
        # فقط ثبت‌نام مستقیم خودِ دانش‌آموز (از اپ) باید همچنان به وضعیت «باز» و ظرفیت خالی محدود بماند.
        if not is_staff:
            if group_session.status != GroupSession.Status.OPEN:
                return Response({'error': 'ثبت‌نام این جلسه بسته شده'}, status=status.HTTP_400_BAD_REQUEST)
            if group_session.seats_left <= 0:
                return Response({'error': 'ظرفیت این جلسه تکمیل شده'}, status=status.HTTP_400_BAD_REQUEST)

        if is_staff:
            student_id = request.data.get('student_id')
            if student_id:
                try:
                    student = User.objects.get(pk=student_id, role='student')
                except User.DoesNotExist:
                    return Response({'error': 'دانش‌آموز پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
            else:
                phone = request.data.get('phone')
                first_name = request.data.get('first_name')
                last_name = request.data.get('last_name')
                if not (phone and first_name and last_name):
                    return Response({'error': 'شماره موبایل و نام و نام‌خانوادگی لازم است'}, status=status.HTTP_400_BAD_REQUEST)
                username = request.data.get('username') or phone
                password = request.data.get('password')
                try:
                    username_validator(username)
                    if password:
                        password_validator(password)
                except DjangoValidationError as exc:
                    return Response({'error': ' / '.join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
                student, created = User.objects.get_or_create(
                    phone=phone,
                    defaults={
                        'username': username,
                        'first_name': first_name,
                        'last_name': last_name,
                        'national_code': request.data.get('national_code'),
                        'language_level': request.data.get('language_level', ''),
                        'role': User.Role.STUDENT,
                    }
                )
                if created:
                    if password:
                        student.set_password(password)
                    else:
                        student.set_unusable_password()
                    student.save()
        elif user.role == 'student':
            student = user
        else:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        if GroupSessionParticipant.objects.filter(group_session=group_session, student=student).exists():
            return Response({'error': 'این نفر قبلاً ثبت‌نام کرده'}, status=status.HTTP_400_BAD_REQUEST)

        participant = GroupSessionParticipant.objects.create(group_session=group_session, student=student)

        serializer_cls = _serializer_for(request)
        return Response(serializer_cls(group_session, context={'request': request}).data, status=status.HTTP_201_CREATED)


class LeaveGroupSessionView(APIView):
    """انصراف از یک جلسه‌ی باز — خودِ دانش‌آموز یا مدیر (برای حذف هرکسی)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            group_session = GroupSession.objects.get(pk=pk)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        if user.role in ('admin', 'evaluator'):
            student_id = request.data.get('student_id')
            if not student_id:
                return Response({'error': 'student_id لازم است'}, status=status.HTTP_400_BAD_REQUEST)
            participant_qs = GroupSessionParticipant.objects.filter(group_session=group_session, student_id=student_id)
        elif user.role == 'student':
            if group_session.status != GroupSession.Status.OPEN:
                return Response({'error': 'دیگر امکان انصراف نیست، با کانتر تماس بگیرید'}, status=status.HTTP_400_BAD_REQUEST)
            participant_qs = GroupSessionParticipant.objects.filter(group_session=group_session, student=user)
        else:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        deleted, _ = participant_qs.delete()
        if not deleted:
            return Response({'error': 'ثبت‌نامی پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'message': 'انصراف ثبت شد'})


class CloseRegistrationView(APIView):
    """بستن ثبت‌نام و رفتن به مرحله‌ی ارجاع به استاد (فقط مدیر)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            group_session = GroupSession.objects.get(pk=pk, status=GroupSession.Status.OPEN)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد یا قبلاً بسته شده'}, status=status.HTTP_404_NOT_FOUND)
        if group_session.participant_count < 1:
            return Response({'error': 'حداقل یک نفر باید ثبت‌نام کرده باشد'}, status=status.HTTP_400_BAD_REQUEST)
        group_session.status = GroupSession.Status.ASSIGNING
        group_session.save()
        return Response(GroupSessionAdminSerializer(group_session, context={'request': request}).data)


class AssignTeachersView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            group_session = GroupSession.objects.get(pk=pk, status=GroupSession.Status.ASSIGNING)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد یا در مرحله‌ی ارجاع نیست'}, status=status.HTTP_404_NOT_FOUND)

        teacher_ids = request.data.get('teacher_ids', [])
        teachers = User.objects.filter(pk__in=teacher_ids, role__in=User.TEACHER_LIKE_ROLES)
        group_session.assigned_teachers.set(teachers)
        group_session.save()

        send_notification(
            sender=request.user,
            recipients=list(teachers),
            title='یک کلاس گروهی جدید برای شما ارجاع شد',
            body=f'{group_session.get_session_type_display()} — سطح {group_session.language_level} — {group_session.participant_count} نفر',
            notif_type='class_assigned'
        )
        return Response(GroupSessionAdminSerializer(group_session, context={'request': request}).data)


class TeacherAcceptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        user = request.user
        if user.role not in User.TEACHER_LIKE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            group_session = GroupSession.objects.filter(assigned_teachers=user, status=GroupSession.Status.ASSIGNING).get(pk=pk)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        group_session.accepted_teachers.add(user)
        admins = User.objects.filter(role='admin')
        send_notification(
            sender=user, recipients=list(admins),
            title='استاد کلاس گروهی را پذیرفت',
            body=f'{user.get_full_name()} کلاس گروهی #{group_session.id} را پذیرفت',
            notif_type='class_accepted'
        )
        return Response({'message': 'پذیرفته شد'})


class TeacherDeclineView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        user = request.user
        if user.role not in User.TEACHER_LIKE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            group_session = GroupSession.objects.filter(assigned_teachers=user).get(pk=pk)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        group_session.assigned_teachers.remove(user)
        group_session.accepted_teachers.remove(user)
        return Response({'message': 'رد شد'})


class FinalizeGroupSessionView(APIView):
    """انتخاب نهایی یکی از استادهای پذیرفته و شروع کلاس (فقط مدیر)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            group_session = GroupSession.objects.get(pk=pk, status=GroupSession.Status.ASSIGNING)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد یا در مرحله‌ی ارجاع نیست'}, status=status.HTTP_404_NOT_FOUND)

        teacher_id = request.data.get('teacher_id')
        try:
            chosen_teacher = group_session.accepted_teachers.get(pk=teacher_id)
        except User.DoesNotExist:
            return Response({'error': 'این استاد هنوز کلاس را نپذیرفته'}, status=status.HTTP_400_BAD_REQUEST)

        group_session.teacher = chosen_teacher
        group_session.status = GroupSession.Status.CONFIRMED
        group_session.save()
        ensure_meetings(group_session)

        other_teachers = group_session.assigned_teachers.exclude(pk=chosen_teacher.pk)
        if other_teachers.exists():
            send_notification(
                sender=request.user, recipients=list(other_teachers),
                title='کلاس گروهی به استاد دیگری داده شد',
                body=f'کلاس گروهی #{group_session.id} نهایی شد',
                notif_type='class_finalized'
            )
        return Response(GroupSessionAdminSerializer(group_session, context={'request': request}).data)


class CancelGroupSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            group_session = GroupSession.objects.exclude(
                status__in=[GroupSession.Status.COMPLETED, GroupSession.Status.CANCELLED]
            ).get(pk=pk)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد یا قابل کنسل نیست'}, status=status.HTTP_404_NOT_FOUND)
        group_session.status = GroupSession.Status.CANCELLED
        group_session.save()
        return Response({'message': 'کنسل شد'})


class GroupSessionMeetingListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        user = request.user
        try:
            if user.role == 'admin':
                group_session = GroupSession.objects.get(pk=pk)
            elif user.role in User.TEACHER_LIKE_ROLES:
                group_session = GroupSession.objects.filter(Q(assigned_teachers=user) | Q(teacher=user)).distinct().get(pk=pk)
            else:
                group_session = GroupSession.objects.filter(participants__student=user).get(pk=pk)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        meetings = ensure_meetings(group_session)
        return Response(GroupSessionMeetingSerializer(meetings, many=True).data)


class GroupSessionMeetingUpdateView(APIView):
    """
    ثبت/ویرایش تاریخ و ساعت اتمام یک جلسه‌ی مشخص از یک دوره‌ی گروهی — همیشه توسط استاد آن دوره یا مدیر
    قابل ویرایش است. وقتی همه‌ی جلسات تاریخ داشته باشن، خودکار برگزار شده علامت می‌خورد (منتظر تایید مدیر).
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk, meeting_number):
        user = request.user
        if user.role not in ('admin', 'teacher'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            if user.role == 'admin':
                group_session = GroupSession.objects.get(pk=pk)
            else:
                group_session = GroupSession.objects.filter(Q(assigned_teachers=user) | Q(teacher=user)).distinct().get(pk=pk)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        ensure_meetings(group_session)
        try:
            meeting = group_session.meetings.get(meeting_number=meeting_number)
        except GroupSessionMeeting.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        completed_at = request.data.get('completed_at')
        if completed_at is not None:
            meeting.completed_at = completed_at or None
        notes = request.data.get('notes')
        if notes is not None:
            meeting.notes = notes
        meeting.completed_by = user
        meeting.save()

        total = group_session.session_count
        done = group_session.meetings.filter(completed_at__isnull=False).count()
        if done >= total and not group_session.is_completed:
            group_session.is_completed = True
            group_session.completed_at = timezone.now()
            group_session.save()
            admins = User.objects.filter(role='admin')
            send_notification(
                sender=user, recipients=list(admins),
                title='کلاس گروهی برگزار شد',
                body=f'همه‌ی جلسات کلاس گروهی #{group_session.id} ثبت شدند — منتظر تایید مدیر',
                notif_type='class_accepted'
            )
        elif done < total and group_session.is_completed:
            group_session.is_completed = False
            group_session.save()

        return Response(GroupSessionMeetingSerializer(meeting).data)


class GroupSessionAttendanceUpdateView(APIView):
    """
    ثبت/ویرایش حضور و غیاب + وضعیت پرداخت یک شرکت‌کننده‌ی مشخص برای یک جلسه‌ی مجزا.
    قابل استفاده توسط مدیر یا استاد ارجاع‌شده/نهایی همان دوره — هم از پنل وب هم از اپ استاد.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk, meeting_number, participant_id):
        user = request.user
        if user.role not in ('admin', 'teacher', 'evaluator'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            if user.role in ('admin', 'evaluator'):
                group_session = GroupSession.objects.get(pk=pk)
            else:
                group_session = GroupSession.objects.filter(Q(assigned_teachers=user) | Q(teacher=user)).distinct().get(pk=pk)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        ensure_meetings(group_session)
        try:
            meeting = group_session.meetings.get(meeting_number=meeting_number)
        except GroupSessionMeeting.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        try:
            participant = group_session.participants.get(pk=participant_id)
        except GroupSessionParticipant.DoesNotExist:
            return Response({'error': 'شرکت‌کننده پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        attendance, _ = GroupSessionAttendance.objects.get_or_create(meeting=meeting, participant=participant)

        status_value = request.data.get('status')
        if status_value is not None:
            if status_value not in GroupSessionAttendance.Status.values:
                return Response({'error': 'وضعیت نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
            attendance.status = status_value
        if 'paid' in request.data:
            attendance.paid = bool(request.data.get('paid'))
        attendance.updated_by = user
        attendance.save()
        return Response(AttendanceSerializer(attendance).data)


class AdminConfirmCompleteView(APIView):
    """تایید نهایی مختومه شدن دوره‌ی گروهی توسط مدیر"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            group_session = GroupSession.objects.get(pk=pk, status=GroupSession.Status.CONFIRMED, is_completed=True)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد یا آماده‌ی تایید نیست'}, status=status.HTTP_404_NOT_FOUND)
        group_session.status = GroupSession.Status.COMPLETED
        group_session.save()
        return Response(GroupSessionAdminSerializer(group_session, context={'request': request}).data)


class ParticipantSatisfactionView(APIView):
    """ثبت/ویرایش نظر یک شرکت‌کننده — خودِ دانش‌آموز، یا مدیر به‌جای او (با participant_id)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            group_session = GroupSession.objects.get(pk=pk, status=GroupSession.Status.COMPLETED)
        except GroupSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد یا هنوز مختومه نشده'}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        if user.role == 'admin':
            participant_id = request.data.get('participant_id')
            try:
                participant = group_session.participants.get(pk=participant_id)
            except GroupSessionParticipant.DoesNotExist:
                return Response({'error': 'شرکت‌کننده پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        elif user.role == 'student':
            try:
                participant = group_session.participants.get(student=user)
            except GroupSessionParticipant.DoesNotExist:
                return Response({'error': 'شما در این جلسه ثبت‌نام نکرده‌اید'}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        satisfaction = request.data.get('satisfaction')
        if satisfaction is None or not (1 <= int(satisfaction) <= 5):
            return Response({'error': 'امتیاز باید بین ۱ تا ۵ باشد'}, status=status.HTTP_400_BAD_REQUEST)
        participant.satisfaction = satisfaction
        participant.satisfaction_text = request.data.get('satisfaction_text', '')
        participant.save()
        return Response(ParticipantSerializer(participant).data)


class ApproveParticipantSatisfactionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ('admin', 'evaluator'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        participant_id = request.data.get('participant_id')
        try:
            participant = GroupSessionParticipant.objects.get(pk=participant_id, group_session_id=pk)
        except GroupSessionParticipant.DoesNotExist:
            return Response({'error': 'شرکت‌کننده پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        participant.satisfaction_approved = True
        participant.save()
        return Response(ParticipantSerializer(participant).data)


class ParticipantPaymentView(APIView):
    """ثبت وضعیت پرداخت یک شرکت‌کننده‌ی خاص (فقط مدیر)"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk, participant_id):
        if request.user.role not in ('admin', 'evaluator'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            participant = GroupSessionParticipant.objects.get(pk=participant_id, group_session_id=pk)
        except GroupSessionParticipant.DoesNotExist:
            return Response({'error': 'شرکت‌کننده پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        payment_status = request.data.get('payment_status')
        if payment_status:
            participant.payment_status = payment_status
        if 'receipt' in request.data:
            participant.receipt = request.data['receipt']
        participant.save()
        return Response(ParticipantSerializer(participant).data)


class GroupPriceSettingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        setting = GroupPriceSetting.objects.order_by('-updated_at').first()
        if not setting:
            setting = GroupPriceSetting.objects.create()
        return Response(GroupPriceSettingSerializer(setting).data)

    def patch(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        setting = GroupPriceSetting.objects.order_by('-updated_at').first()
        if not setting:
            setting = GroupPriceSetting.objects.create()
        serializer = GroupPriceSettingSerializer(setting, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
