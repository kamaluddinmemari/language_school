from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Q
from accounts.models import ClassRequest, User
from notifications.utils import send_notification
from .models import ClassSession, ensure_sessions
from .serializers import (
    ClassRequestAdminSerializer,
    ClassRequestAdminCreateSerializer,
    ClassRequestCreateSerializer,
    ClassRequestTeacherSerializer,
    ClassRequestStudentSerializer,
    ClassSessionSerializer,
)


class ClassRequestListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            if self.request.user.role in ('admin', 'office'):
                return ClassRequestAdminCreateSerializer
            return ClassRequestCreateSerializer
        if self.request.user.role in ('admin', 'evaluator'):
            return ClassRequestAdminSerializer
        if self.request.user.role in User.TEACHER_LIKE_ROLES:
            return ClassRequestTeacherSerializer
        return ClassRequestStudentSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role in ('admin', 'evaluator'):
            return ClassRequest.objects.all().order_by('-created_at')
        elif user.role in User.TEACHER_LIKE_ROLES:
            from django.db.models import Q
            return ClassRequest.objects.filter(
                Q(assigned_teachers=user) | Q(teacher=user)
            ).distinct().order_by('-created_at')
        return ClassRequest.objects.filter(student=user).order_by('-created_at')

    def perform_create(self, serializer):
        if self.request.user.role == 'evaluator':
            raise PermissionDenied('مدیر آموزش نمی‌تواند درخواست کلاس بسازد — فقط گزارش‌گیری/ویرایش/حذف')
        if self.request.user.role in ('admin', 'office'):
            serializer.save()
        else:
            instance = serializer.save(student=self.request.user)
            admins = User.objects.filter(role='admin')
            send_notification(
                sender=self.request.user,
                recipients=list(admins),
                title='درخواست کلاس جدید از اپ',
                body=f'دانش‌آموز {self.request.user.get_full_name()} یک درخواست کلاس {instance.get_class_type_display()} ثبت کرد',
                notif_type='general'
            )


class ClassRequestDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    گزارش‌گیری/ویرایش/حذف: مدیر روی هر کلاسی، مدیر آموزش هم مثل مدیر (فقط دسترسی گزارشی —
    اکشن‌های گردش‌کاری مثل ارجاع/تایید/پرداخت جدا هستند و فقط مدیر می‌تواند آن‌ها را بزند).
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        user = self.request.user
        if user.role in User.TEACHER_LIKE_ROLES:
            return ClassRequestTeacherSerializer
        if user.role == 'student':
            return ClassRequestStudentSerializer
        return ClassRequestAdminSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role in ('admin', 'evaluator'):
            return ClassRequest.objects.all()
        elif user.role in User.TEACHER_LIKE_ROLES:
            from django.db.models import Q
            return ClassRequest.objects.filter(Q(assigned_teachers=user) | Q(teacher=user)).distinct()
        return ClassRequest.objects.filter(student=user)

    def update(self, request, *args, **kwargs):
        if request.user.role not in ('admin', 'evaluator'):
            return Response({'error': 'فقط مدیر یا مدیر آموزش می‌تونه ویرایش کنه'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role not in ('admin', 'evaluator'):
            return Response({'error': 'فقط مدیر یا مدیر آموزش می‌تونه حذف کنه'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class AssignTeachersView(APIView):
    """مرحله ۱: مدیر کلاس را به یک یا چند استاد ارجاع می‌دهد"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'فقط مدیر می‌تونه ارجاع بده'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.get(pk=pk)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        if class_request.status not in [ClassRequest.Status.PENDING, ClassRequest.Status.REFERRED]:
            return Response({'error': 'این کلاس در مرحله‌ای نیست که قابل ارجاع باشد'}, status=status.HTTP_400_BAD_REQUEST)

        teacher_ids = request.data.get('teacher_ids', [])
        teachers = list(User.objects.filter(id__in=teacher_ids, role__in=User.TEACHER_LIKE_ROLES))
        if not teachers:
            return Response({'error': 'حداقل یک استاد معتبر باید انتخاب شود'}, status=status.HTTP_400_BAD_REQUEST)

        class_request.assigned_teachers.set(teachers)
        class_request.accepted_teachers.clear()
        class_request.status = ClassRequest.Status.REFERRED
        class_request.save()

        send_notification(
            sender=request.user,
            recipients=teachers,
            title='کلاس جدید برای بررسی',
            body=f'یک کلاس {class_request.get_class_type_display()} سطح {class_request.language_level} به شما ارجاع شد',
            notif_type='class_approved'
        )
        return Response({'message': 'کلاس به استاد(ها) ارجاع شد'})


class TeacherAcceptView(APIView):
    """مرحله ۲: استاد ارجاع را تایید اولیه می‌کند (هنوز نهایی نشده)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in User.TEACHER_LIKE_ROLES:
            return Response({'error': 'فقط استاد می‌تونه قبول کنه'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.get(
                pk=pk, assigned_teachers=request.user, status=ClassRequest.Status.REFERRED
            )
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد یا در دسترس نیست'}, status=status.HTTP_404_NOT_FOUND)

        class_request.accepted_teachers.add(request.user)

        admins = User.objects.filter(role='admin')
        send_notification(
            sender=request.user,
            recipients=list(admins),
            title='تایید اولیه استاد',
            body=f'استاد {request.user.get_full_name()} کلاس را تایید اولیه کرد. منتظر تایید نهایی شما.',
            notif_type='class_accepted'
        )
        return Response({'message': 'تایید اولیه شما ثبت شد، منتظر تایید نهایی مدیر باشید'})


class TeacherDeclineView(APIView):
    """استاد ارجاع را رد می‌کند (قبل از تایید نهایی مدیر)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in User.TEACHER_LIKE_ROLES:
            return Response({'error': 'فقط استاد می‌تونه رد کنه'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.get(pk=pk, assigned_teachers=request.user)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        class_request.assigned_teachers.remove(request.user)
        class_request.accepted_teachers.remove(request.user)

        admins = User.objects.filter(role='admin')
        send_notification(
            sender=request.user,
            recipients=list(admins),
            title='رد ارجاع توسط استاد',
            body=f'استاد {request.user.get_full_name()} ارجاع کلاس را رد کرد',
            notif_type='class_rejected'
        )
        return Response({'message': 'ارجاع رد شد'})


class FinalizeClassView(APIView):
    """
    مرحله ۳: مدیر از بین استادهایی که تایید اولیه کرده‌اند، یک نفر را به صورت نهایی انتخاب می‌کند.
    به سایر استادهایی که تایید اولیه کرده بودند ولی انتخاب نشدند، اعلان «تایید نشد» ارسال می‌شود.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'فقط مدیر می‌تونه تایید نهایی کنه'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.get(pk=pk, status=ClassRequest.Status.REFERRED)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد یا در مرحله‌ی مناسب نیست'}, status=status.HTTP_404_NOT_FOUND)

        teacher_id = request.data.get('teacher_id')
        try:
            chosen_teacher = class_request.accepted_teachers.get(pk=teacher_id)
        except User.DoesNotExist:
            return Response({'error': 'این استاد در لیست تاییدکنندگان نیست'}, status=status.HTTP_400_BAD_REQUEST)

        class_request.teacher = chosen_teacher
        class_request.status = ClassRequest.Status.CONFIRMED
        class_request.save()
        ensure_sessions(class_request)

        not_chosen = class_request.accepted_teachers.exclude(pk=chosen_teacher.pk)
        send_notification(
            sender=request.user,
            recipients=list(not_chosen),
            title='کلاس تایید نهایی نشد',
            body='این کلاس به استاد دیگری ارجاع نهایی شد',
            notif_type='class_rejected'
        )
        send_notification(
            sender=request.user,
            recipients=[chosen_teacher],
            title='تایید نهایی کلاس',
            body=f'کلاس به شما تایید نهایی شد. سهم شما: {class_request.teacher_share:,} تومان',
            notif_type='class_accepted'
        )
        send_notification(
            sender=request.user,
            recipients=[class_request.student],
            title='استاد کلاس شما مشخص شد',
            body=(
                f'کلاس {class_request.get_language_level_display() if hasattr(class_request, "get_language_level_display") else class_request.language_level} '
                f'با استاد {chosen_teacher.get_full_name()} نهایی شد'
            ),
            notif_type='class_accepted'
        )
        return Response({'message': 'کلاس به صورت نهایی تایید شد'})


class CancelClassView(APIView):
    """مدیر کلاس را به طور کامل کنسل می‌کند — به دانش‌آموز و همه استادهای ارجاع‌شده اطلاع داده می‌شود"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'فقط مدیر می‌تونه کنسل کنه'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.exclude(
                status__in=[ClassRequest.Status.COMPLETED, ClassRequest.Status.CANCELLED]
            ).get(pk=pk)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد یا قابل کنسل کردن نیست'}, status=status.HTTP_404_NOT_FOUND)

        recipients = list(class_request.assigned_teachers.all())
        if class_request.teacher and class_request.teacher not in recipients:
            recipients.append(class_request.teacher)

        class_request.status = ClassRequest.Status.CANCELLED
        class_request.save()

        send_notification(
            sender=request.user,
            recipients=recipients + [class_request.student],
            title='کلاس کنسل شد',
            body='این کلاس توسط مدیر آموزشگاه کنسل شد',
            notif_type='class_rejected'
        )
        return Response({'message': 'کلاس کنسل شد'})


class RejectClassView(APIView):
    """رد درخواست در مرحله‌ی اولیه (قبل از ارجاع به استاد)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.get(pk=pk, status=ClassRequest.Status.PENDING)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد یا قابل رد کردن نیست'}, status=status.HTTP_404_NOT_FOUND)

        class_request.status = ClassRequest.Status.REJECTED
        class_request.save()
        send_notification(
            sender=request.user,
            recipients=[class_request.student],
            title='درخواست رد شد',
            body='متاسفانه درخواست کلاس شما رد شد',
            notif_type='class_rejected'
        )
        return Response({'message': 'درخواست رد شد'})


class CompleteClassView(APIView):
    """استاد پس از برگزاری کلاس، اتمام آن را اعلام می‌کند"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in User.TEACHER_LIKE_ROLES:
            return Response({'error': 'فقط استاد می‌تونه کلاس رو تموم کنه'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.get(
                pk=pk, teacher=request.user, status=ClassRequest.Status.CONFIRMED
            )
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        completed_at = request.data.get('completed_at')
        class_request.is_completed = True
        class_request.completed_at = completed_at if completed_at else timezone.now()
        class_request.save()

        admins = User.objects.filter(role='admin')
        send_notification(
            sender=request.user,
            recipients=list(admins),
            title='کلاس برگزار شد',
            body=f'کلاس توسط استاد {request.user.get_full_name()} برگزار شد',
            notif_type='class_accepted'
        )
        return Response({'message': 'کلاس تموم شد — منتظر تایید مدیر'})


class ClassSessionListView(APIView):
    """لیست جلسات یک کلاس (برای کلاس‌هایی با بیش از یک جلسه). ردیف‌های ناموجود خودکار ساخته می‌شن."""
    permission_classes = [IsAuthenticated]

    def _get_class_request(self, request, pk):
        user = request.user
        if user.role in ('admin', 'office'):
            qs = ClassRequest.objects.all()
        elif user.role in User.TEACHER_LIKE_ROLES:
            qs = ClassRequest.objects.filter(Q(assigned_teachers=user) | Q(teacher=user)).distinct()
        else:
            qs = ClassRequest.objects.filter(student=user)
        return qs.get(pk=pk)

    def get(self, request, pk):
        try:
            class_request = self._get_class_request(request, pk)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        sessions = ensure_sessions(class_request)
        return Response(ClassSessionSerializer(sessions, many=True).data)


class ClassSessionUpdateView(APIView):
    """
    ثبت/ویرایش تاریخ و ساعت اتمام یک جلسه‌ی مشخص.
    همیشه توسط استاد (کلاس خودش) یا مدیر قابل ویرایشه — حتی بعد از مختومه شدن کلاس.
    وقتی همه‌ی جلسات تاریخ اتمام داشته باشن، کلاس خودکار «برگزار شده» علامت می‌خوره (منتظر تایید مدیر).
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk, session_number):
        user = request.user
        if user.role not in ('admin', 'teacher'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            if user.role in ('admin', 'office'):
                class_request = ClassRequest.objects.get(pk=pk)
            else:
                class_request = ClassRequest.objects.filter(
                    Q(assigned_teachers=user) | Q(teacher=user)
                ).distinct().get(pk=pk)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        ensure_sessions(class_request)
        try:
            session = class_request.sessions.get(session_number=session_number)
        except ClassSession.DoesNotExist:
            return Response({'error': 'جلسه پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        completed_at = request.data.get('completed_at')
        if completed_at is not None:
            session.completed_at = completed_at or None
        notes = request.data.get('notes')
        if notes is not None:
            session.notes = notes
        session.completed_by = user
        session.save()

        total = class_request.session_count
        done = class_request.sessions.filter(completed_at__isnull=False).count()
        if done >= total and not class_request.is_completed:
            class_request.is_completed = True
            class_request.completed_at = timezone.now()
            class_request.save()
            admins = User.objects.filter(role='admin')
            send_notification(
                sender=user,
                recipients=list(admins),
                title='کلاس برگزار شد',
                body='همه‌ی جلسات این کلاس ثبت شدند — منتظر تایید مدیر',
                notif_type='class_accepted'
            )
        elif done < total and class_request.is_completed:
            # اگر یکی از جلسات ویرایش و تاریخش پاک شد، حالت «برگزار شده» رو برگردون
            class_request.is_completed = False
            class_request.save()

        return Response(ClassSessionSerializer(session).data)


class AdminConfirmCompleteView(APIView):
    """مدیر اتمام کلاس را تایید می‌کند و کلاس مختومه می‌شود"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'فقط مدیر می‌تونه تایید کنه'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.get(pk=pk, is_completed=True)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        class_request.status = ClassRequest.Status.COMPLETED
        class_request.save()

        send_notification(
            sender=request.user,
            recipients=[class_request.student],
            title='کلاس مختومه شد',
            body='کلاس شما به پایان رسید. لطفاً نظر خود را ثبت کنید',
            notif_type='class_accepted'
        )
        if class_request.teacher:
            send_notification(
                sender=request.user,
                recipients=[class_request.teacher],
                title='تایید اتمام کلاس',
                body='مدیر اتمام کلاس را تایید کرد',
                notif_type='class_accepted'
            )
        return Response({'message': 'کلاس مختومه شد'})


class SatisfactionView(APIView):
    """دانش‌آموز پس از اتمام کلاس به آن امتیاز می‌دهد (یا مدیر، به‌جای دانش‌آموزی که اپ ندارد)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role == 'student':
            try:
                class_request = ClassRequest.objects.get(
                    pk=pk, student=request.user, status=ClassRequest.Status.COMPLETED
                )
            except ClassRequest.DoesNotExist:
                return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        elif request.user.role in ('admin', 'office'):
            try:
                class_request = ClassRequest.objects.get(
                    pk=pk, status=ClassRequest.Status.COMPLETED
                )
            except ClassRequest.DoesNotExist:
                return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        satisfaction = request.data.get('satisfaction')
        if not satisfaction or int(satisfaction) not in range(1, 6):
            return Response({'error': 'امتیاز باید بین ۱ تا ۵ باشه'}, status=status.HTTP_400_BAD_REQUEST)

        class_request.satisfaction = satisfaction
        class_request.satisfaction_text = request.data.get('satisfaction_text', '')
        class_request.save()

        admins = User.objects.filter(role='admin')
        send_notification(
            sender=request.user,
            recipients=list(admins),
            title='نظر دانش‌آموز',
            body=f'دانش‌آموز {request.user.get_full_name()} امتیاز {satisfaction} داد',
            notif_type='general'
        )
        return Response({'message': 'نظر شما ثبت شد'})


class ApproveSatisfactionView(APIView):
    """مدیر نظر متنی دانش‌آموز را تایید می‌کند تا در اپ استاد قابل مشاهده شود"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'فقط مدیر می‌تونه تایید کنه'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.get(pk=pk, status=ClassRequest.Status.COMPLETED)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'کلاس پیدا نشد یا هنوز مختومه نشده'}, status=status.HTTP_404_NOT_FOUND)

        if not class_request.satisfaction:
            return Response({'error': 'دانش‌آموز هنوز نظری ثبت نکرده'}, status=status.HTTP_400_BAD_REQUEST)

        class_request.satisfaction_approved = True
        class_request.save()

        if class_request.teacher:
            send_notification(
                sender=request.user,
                recipients=[class_request.teacher],
                title='نظر دانش‌آموز شما تایید شد',
                body='نظر دانش‌آموز درباره‌ی این کلاس الان توی اپ شما قابل مشاهده‌ست',
                notif_type='general'
            )
        return Response({'message': 'نظر دانش‌آموز برای استاد نمایش داده شد'})


class PayTeacherView(APIView):
    """مدیر پرداخت سهم استاد را ثبت می‌کند"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'فقط مدیر می‌تونه پرداخت رو ثبت کنه'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.get(pk=pk)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        amount = request.data.get('amount', class_request.teacher_share)
        class_request.teacher_payment_status = True
        class_request.teacher_payment_date = timezone.now()
        class_request.teacher_payment_amount = amount
        class_request.save()

        if class_request.teacher:
            send_notification(
                sender=request.user,
                recipients=[class_request.teacher],
                title='پرداخت سهم شما ثبت شد',
                body=f'مبلغ {amount:,} تومان به شما پرداخت شد',
                notif_type='general'
            )
        return Response({'message': 'پرداخت ثبت شد'})


class ClassStatsView(APIView):
    """
    گزارش آمار تجمیعی کلاس‌های برگزار شده (مختومه) در یک بازه‌ی زمانی.
    پارامترهای اختیاری: start_date و end_date (فرمت YYYY-MM-DD) — بر اساس تاریخ اتمام کلاس.
    اگر داده نشوند، همه‌ی کلاس‌های مختومه در نظر گرفته می‌شوند.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'فقط مدیر به این گزارش دسترسی دارد'}, status=status.HTTP_403_FORBIDDEN)

        queryset = ClassRequest.objects.filter(status=ClassRequest.Status.COMPLETED)

        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        if start_date:
            queryset = queryset.filter(completed_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(completed_at__date__lte=end_date)

        total_classes = queryset.count()
        total_sessions = sum(c.session_count for c in queryset)
        total_price = sum(c.total_price for c in queryset)
        total_teacher_share = sum(c.teacher_share for c in queryset)
        total_school_share = sum(c.school_share for c in queryset)

        by_type = {}
        for c in queryset:
            key = c.class_type
            if key not in by_type:
                by_type[key] = {'count': 0, 'total_price': 0}
            by_type[key]['count'] += 1
            by_type[key]['total_price'] += c.total_price

        by_teacher = {}
        for c in queryset:
            if not c.teacher:
                continue
            key = c.teacher.id
            if key not in by_teacher:
                by_teacher[key] = {
                    'teacher_id': c.teacher.id,
                    'teacher_name': c.teacher.get_full_name(),
                    'count': 0,
                    'total_teacher_share': 0,
                }
            by_teacher[key]['count'] += 1
            by_teacher[key]['total_teacher_share'] += c.teacher_share

        return Response({
            'start_date': start_date,
            'end_date': end_date,
            'total_classes': total_classes,
            'total_sessions': total_sessions,
            'total_price': total_price,
            'total_teacher_share': total_teacher_share,
            'total_school_share': total_school_share,
            'by_class_type': by_type,
            'by_teacher': list(by_teacher.values()),
        })
