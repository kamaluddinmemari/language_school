from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.conf import settings
from .models import Notification, ContactFeedback, WebPushSubscription
from .serializers import (
    NotificationSerializer, SendNotificationSerializer,
    ContactFeedbackSerializer, ContactFeedbackCreateSerializer, ContactFeedbackReplySerializer,
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
