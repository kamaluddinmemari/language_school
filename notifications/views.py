from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db import models
from accounts.models import User
from django.conf import settings
from .models import REPEAT_FOREVER_DATE, Notification, ContactFeedback, WebPushSubscription, DailyTask, DailyTaskCompletion, DailyTaskReply
from .serializers import (
    NotificationSerializer, SendNotificationSerializer,
    ContactFeedbackSerializer, ContactFeedbackCreateSerializer, ContactFeedbackReplySerializer,
    DailyTaskSerializer, DailyTaskCompletionSerializer, DailyTaskStaffSerializer, DailyTaskReplySerializer,
)
from accounts.menu_permissions import can_edit_menu, can_view_menu

# منسوخ — از تنظیمات دسترسی (accounts.menu_permissions) جایگزین شد؛ فقط برای مرجع نگه داشته شده.
MANAGE_ROLES = ('admin', 'evaluator', 'office')


class NotificationListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(
            recipients=self.request.user
        ).order_by('-created_at')


class SendNotificationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in ('admin', 'office'):
            return Response(
                {'error': 'فقط مدیر می‌تونه نوتیف بفرسته'},
                status=status.HTTP_403_FORBIDDEN
            )
        serializer = SendNotificationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(sender=request.user)
            return Response(
                {'message': 'نوتیفیکیشن ارسال شد'},
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MarkAsReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            notification = Notification.objects.get(
                pk=pk,
                recipients=request.user
            )
            notification.is_read = True
            notification.save()
            return Response({'message': 'نوتیف خوانده شد'})
        except Notification.DoesNotExist:
            return Response(
                {'error': 'نوتیف پیدا نشد'},
                status=status.HTTP_404_NOT_FOUND
            )


# ---------- خواسته‌ی ۱۶: «تماس با ما» / ثبت نظرات از اپ + بخش «نظرات و پیشنهادات» در پنل ادمین ----------

class ContactFeedbackCreateView(APIView):
    """POST: هر کاربر (دانش‌آموز/استاد/...) از اپ برای مدیریت پیام می‌فرستد"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ContactFeedbackCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fb = ContactFeedback.objects.create(
            sender=request.user, subject=serializer.validated_data.get('subject', ''),
            message=serializer.validated_data['message'],
        )
        from .utils import send_web_push_to_roles
        send_web_push_to_roles(
            roles=('admin', 'office', 'employee'),
            title='پیام جدید — تماس با ما',
            body=f"{request.user.get_full_name()}: {fb.subject or fb.message[:60]}",
            url='/feedback',
        )
        return Response(ContactFeedbackSerializer(fb).data, status=status.HTTP_201_CREATED)


class MyContactFeedbackListView(generics.ListAPIView):
    """GET: پیام‌های خودِ کاربر به همراه پاسخ مدیریت (اگر داده شده) — برای نمایش در اپ"""
    permission_classes = [IsAuthenticated]
    serializer_class = ContactFeedbackSerializer

    def get_queryset(self):
        return ContactFeedback.objects.filter(sender=self.request.user)


class AdminContactFeedbackListView(generics.ListAPIView):
    """GET: لیست همه‌ی پیام‌های واصل‌شده از اپ — برای بخش «نظرات و پیشنهادات» در پنل ادمین"""
    permission_classes = [IsAuthenticated]
    serializer_class = ContactFeedbackSerializer

    def get_queryset(self):
        if not can_view_menu(self.request.user, 'feedback'):
            return ContactFeedback.objects.none()
        return ContactFeedback.objects.select_related('sender', 'replied_by')


class AdminContactFeedbackDetailView(APIView):
    """
    PATCH: ثبت/ویرایش پاسخ مدیر به یک پیام (و علامت‌گذاری «دیده‌شده»)
    DELETE: حذف کامل پیام
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if not can_edit_menu(request.user, 'feedback'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            fb = ContactFeedback.objects.get(pk=pk)
        except ContactFeedback.DoesNotExist:
            return Response({'error': 'پیام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ContactFeedbackReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fb.admin_reply = serializer.validated_data['admin_reply']
        fb.replied_by = request.user
        fb.replied_at = timezone.now()
        fb.seen_by_admin = True
        fb.save()
        return Response(ContactFeedbackSerializer(fb).data)

    def delete(self, request, pk):
        if not can_edit_menu(request.user, 'feedback'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            fb = ContactFeedback.objects.get(pk=pk)
        except ContactFeedback.DoesNotExist:
            return Response({'error': 'پیام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        fb.delete()
        return Response({'message': 'پیام حذف شد'})


class MarkContactFeedbackSeenView(APIView):
    """POST: فقط علامت‌گذاری «دیده‌شده» بدون ثبت پاسخ (برای وقتی مدیر فقط بازش کرده ولی هنوز پاسخ نداده)"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'feedback'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            fb = ContactFeedback.objects.get(pk=pk)
        except ContactFeedback.DoesNotExist:
            return Response({'error': 'پیام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        fb.seen_by_admin = True
        fb.save(update_fields=['seen_by_admin'])
        return Response({'message': 'علامت‌گذاری شد'})

# ---------- Web Push (اعلان ناتیو صدادار برای ادمین/اداری، حتی وقتی پنل بسته است) ----------

class WebPushPublicKeyView(APIView):
    """GET: کلید عمومی VAPID که مرورگر برای pushManager.subscribe لازم دارد"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({'public_key': settings.VAPID_PUBLIC_KEY})


class WebPushSubscribeView(APIView):
    """POST: مرورگر بعد از گرفتن اجازه‌ی نوتیف، خروجی pushManager.subscribe().toJSON() را اینجا می‌فرستد"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in ('admin', 'office', 'employee'):
            return Response({'error': 'این قابلیت فقط برای مدیر و کارکنان اداری است'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data
        endpoint = data.get('endpoint')
        keys = data.get('keys') or {}
        if not endpoint or not keys.get('p256dh') or not keys.get('auth'):
            return Response({'error': 'اطلاعات اشتراک ناقص است'}, status=status.HTTP_400_BAD_REQUEST)
        WebPushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                'user': request.user,
                'p256dh': keys['p256dh'],
                'auth': keys['auth'],
                'user_agent': request.META.get('HTTP_USER_AGENT', '')[:255],
            },
        )
        return Response({'message': 'اعلان دسکتاپ برای این مرورگر فعال شد'}, status=status.HTTP_201_CREATED)


class WebPushUnsubscribeView(APIView):
    """POST: خاموش‌کردن اعلان دسکتاپ برای همین مرورگر"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        endpoint = request.data.get('endpoint')
        if endpoint:
            WebPushSubscription.objects.filter(endpoint=endpoint, user=request.user).delete()
        return Response({'message': 'اعلان دسکتاپ برای این مرورگر خاموش شد'})


# ---------- «کارهایی که امروز باید انجام بدهم» ----------
TASK_MANAGER_ROLES = ('admin', 'office', 'evaluator')
TASK_STAFF_ROLES = ('admin', 'office', 'employee', 'evaluator')


def _apply_repeat(payload, task=None):
    """فیلد repeat_daily را به تاریخ پایانِ نمادین تبدیل می‌کند (بدون ستون جدید)."""
    if 'repeat_daily' not in payload:
        return
    raw = payload.pop('repeat_daily')
    flag = raw is True or str(raw).lower() in ('1', 'true', 'on', 'yes')
    if flag:
        payload['end_date'] = REPEAT_FOREVER_DATE.isoformat()
        payload['end_time'] = None
    elif task is not None and task.end_date == REPEAT_FOREVER_DATE:
        payload['end_date'] = None
        payload['end_time'] = None
    elif task is None and payload.get('end_date') == REPEAT_FOREVER_DATE.isoformat():
        payload['end_date'] = None


def _task_manager(user):
    return user.role in TASK_MANAGER_ROLES


class DailyTaskListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        qs = DailyTask.objects.filter(is_active=True, start_date__lte=today).filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=today)
        ).prefetch_related('assigned_to', 'completions', 'replies')
        if request.user.role not in TASK_MANAGER_ROLES:
            qs = qs.filter(models.Q(assigned_to__isnull=True) | models.Q(assigned_to=request.user)).distinct()
        return Response(DailyTaskSerializer(qs, many=True, context={'request': request}).data)

    def post(self, request):
        if not _task_manager(request.user):
            return Response({'error': 'فقط مدیر یا مسئول آموزش می‌تواند دستور کاری ثبت کند'}, status=status.HTTP_403_FORBIDDEN)
        payload = request.data.copy()
        assigned = payload.pop('assigned_to', [])
        if assigned is None:
            assigned = []
        _apply_repeat(payload)
        serializer = DailyTaskSerializer(data=payload, context={'request': request})
        serializer.is_valid(raise_exception=True)
        try:
            task = serializer.save(created_by=request.user)
            valid_staff = User.objects.filter(id__in=assigned, role__in=TASK_STAFF_ROLES, is_active=True)
            task.assigned_to.set(valid_staff)
            return Response(DailyTaskSerializer(task, context={'request': request}).data, status=status.HTTP_201_CREATED)
        except Exception as exc:  # علت واقعی خطا به‌جای ۵۰۰ مبهم نمایش داده شود و در لاگ هم بماند
            import logging
            logging.getLogger(__name__).exception('daily task create failed')
            return Response({'error': f'ثبت دستور انجام نشد ({type(exc).__name__}: {exc}). اگر مربوط به ستون/جدول است، migrate را اجرا و سرور را restart کنید.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DailyTaskDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if not _task_manager(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        task = DailyTask.objects.filter(pk=pk).first()
        if not task:
            return Response({'error': 'دستور کاری پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        payload = request.data.copy()
        assigned = payload.pop('assigned_to', None)
        _apply_repeat(payload, task)
        serializer = DailyTaskSerializer(task, data=payload, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        if assigned is not None:
            valid_staff = User.objects.filter(id__in=assigned, role__in=TASK_STAFF_ROLES, is_active=True)
            task.assigned_to.set(valid_staff)
        return Response(DailyTaskSerializer(task, context={'request': request}).data)

    def delete(self, request, pk):
        if not _task_manager(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        deleted, _ = DailyTask.objects.filter(pk=pk).delete()
        if not deleted:
            return Response({'error': 'دستور کاری پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'message': 'دستور کاری حذف شد'})


class DailyTaskStaffView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        if not _task_manager(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        staff = User.objects.filter(role__in=('office', 'employee'), is_active=True).order_by('first_name', 'last_name')
        return Response(DailyTaskStaffSerializer(staff, many=True).data)


class DailyTaskCompleteView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, pk):
        if request.user.role not in TASK_STAFF_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        task = DailyTask.objects.filter(pk=pk, is_active=True).first()
        if not task:
            return Response({'error': 'دستور کاری پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        today = timezone.localdate()
        if not (task.start_date <= today and (not task.end_date or today <= task.end_date)):
            return Response({'error': 'این دستور در بازهٔ امروز فعال نیست'}, status=status.HTTP_400_BAD_REQUEST)
        target = request.user
        requested_employee = request.data.get('employee_id')
        if request.user.role in MANAGE_ROLES and requested_employee:
            target = User.objects.filter(pk=requested_employee, role__in=('office', 'employee'), is_active=True).first()
            if not target:
                return Response({'error': 'کارمند انتخاب‌شده معتبر نیست'}, status=status.HTTP_400_BAD_REQUEST)
        elif requested_employee and str(requested_employee) != str(request.user.pk):
            return Response({'error': 'هر کارمند فقط می‌تواند انجام کار خودش را ثبت کند'}, status=status.HTTP_403_FORBIDDEN)
        if target.role not in ('admin', 'office', 'employee', 'evaluator'):
            return Response({'error': 'این کاربر کارمند نیست'}, status=status.HTTP_400_BAD_REQUEST)
        is_self_manager = target.pk == request.user.pk and request.user.role in TASK_MANAGER_ROLES
        if not is_self_manager and task.assigned_to.exists() and not task.assigned_to.filter(pk=target.pk).exists():
            return Response({'error': 'این دستور به این کارمند ارجاع نشده است'}, status=status.HTTP_403_FORBIDDEN)
        note = str(request.data.get('note') or '').strip()[:4000]
        completion, created = DailyTaskCompletion.objects.get_or_create(
            task=task, employee=target, completed_on=today, defaults={'note': note}
        )
        if not created and note and completion.note != note:
            completion.note = note
            completion.save(update_fields=['note'])
        return Response(DailyTaskCompletionSerializer(completion).data)


class DailyTaskReplyCreateView(APIView):
    """POST: پاسخ/توضیح روی یک دستور (با parent اختیاری برای حالت ریپلای)."""
    permission_classes = [IsAuthenticated]
    def post(self, request, pk):
        if request.user.role not in TASK_STAFF_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        task = DailyTask.objects.filter(pk=pk, is_active=True).first()
        if not task:
            return Response({'error': 'دستور کاری پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        if not _task_manager(request.user) and task.assigned_to.exists() and not task.assigned_to.filter(pk=request.user.pk).exists():
            return Response({'error': 'این دستور به شما ارجاع نشده است'}, status=status.HTTP_403_FORBIDDEN)
        body = str(request.data.get('body') or '').strip()[:4000]
        if not body:
            return Response({'error': 'متن پاسخ خالی است'}, status=status.HTTP_400_BAD_REQUEST)
        parent = None
        parent_id = request.data.get('parent')
        if parent_id:
            try:
                parent = DailyTaskReply.objects.filter(pk=parent_id, task=task).first()
            except Exception:
                parent = None
            if not parent:
                return Response({'error': 'پیام مورد نظر برای ریپلای پیدا نشد'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            reply = DailyTaskReply.objects.create(task=task, author=request.user, parent=parent, body=body)
            return Response(DailyTaskReplySerializer(reply, context={'request': request}).data, status=status.HTTP_201_CREATED)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception('daily task reply failed')
            return Response({'error': f'ثبت پاسخ انجام نشد ({type(exc).__name__}). احتمالاً باید python manage.py migrate اجرا و سرور restart شود.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DailyTaskReplyDetailView(APIView):
    permission_classes = [IsAuthenticated]
    def delete(self, request, pk):
        reply = DailyTaskReply.objects.filter(pk=pk).first()
        if not reply:
            return Response({'error': 'پاسخ پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        if reply.author_id != request.user.pk and not _task_manager(request.user):
            return Response({'error': 'فقط نویسنده یا مدیر می‌تواند حذف کند'}, status=status.HTTP_403_FORBIDDEN)
        reply.delete()
        return Response({'message': 'پاسخ حذف شد'})
