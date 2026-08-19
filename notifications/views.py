from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from .models import Notification, ContactFeedback
from .serializers import (
    NotificationSerializer, SendNotificationSerializer,
    ContactFeedbackSerializer, ContactFeedbackCreateSerializer, ContactFeedbackReplySerializer,
)

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
        if self.request.user.role not in MANAGE_ROLES:
            return ContactFeedback.objects.none()
        return ContactFeedback.objects.select_related('sender', 'replied_by')


class AdminContactFeedbackDetailView(APIView):
    """
    PATCH: ثبت/ویرایش پاسخ مدیر به یک پیام (و علامت‌گذاری «دیده‌شده»)
    DELETE: حذف کامل پیام
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
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
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            fb = ContactFeedback.objects.get(pk=pk)
        except ContactFeedback.DoesNotExist:
            return Response({'error': 'پیام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        fb.seen_by_admin = True
        fb.save(update_fields=['seen_by_admin'])
        return Response({'message': 'علامت‌گذاری شد'})