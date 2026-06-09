from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from accounts.models import ClassRequest, User
from notifications.models import Notification
from .serializers import (
    ClassRequestSerializer,
    ClassRequestCreateSerializer,
    ClassRequestAdminSerializer
)


def send_notification(sender, recipients, title, body, notif_type='general'):
    notif = Notification.objects.create(
        sender=sender,
        title=title,
        body=body,
        notif_type=notif_type
    )
    notif.recipients.set(recipients)


class ClassRequestListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            if self.request.user.role in ['admin']:
                return ClassRequestAdminSerializer
            return ClassRequestCreateSerializer
        return ClassRequestSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return ClassRequest.objects.all().order_by('-created_at')
        elif user.role == 'teacher':
            return ClassRequest.objects.filter(
                assigned_teachers=user,
                status='approved'
            ).order_by('-created_at')
        return ClassRequest.objects.filter(student=user).order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(student=self.request.user)


class ClassRequestDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ClassRequestAdminSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return ClassRequest.objects.all()
        elif user.role == 'teacher':
            return ClassRequest.objects.filter(assigned_teachers=user)
        return ClassRequest.objects.filter(student=user)


class ApproveClassView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تونه تایید کنه'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.get(pk=pk)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        class_request.status = 'approved'
        class_request.save()

        teachers = list(class_request.assigned_teachers.all())
        if teachers:
            send_notification(
                sender=request.user,
                recipients=teachers,
                title='کلاس جدید',
                body='یک کلاس جدید به کارتابل شما اضافه شد',
                notif_type='class_approved'
            )
        send_notification(
            sender=request.user,
            recipients=[class_request.student],
            title='درخواست تایید شد',
            body='درخواست کلاس شما تایید شد',
            notif_type='class_approved'
        )
        return Response({'message': 'درخواست تایید شد'})


class RejectClassView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            class_request = ClassRequest.objects.get(pk=pk)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        if request.user.role == 'admin':
            class_request.status = 'rejected'
            class_request.save()
            send_notification(
                sender=request.user,
                recipients=[class_request.student],
title='درخواست رد شد',
                body='متاسفانه درخواست کلاس شما رد شد',
                notif_type='class_rejected'
            )
            return Response({'message': 'درخواست رد شد'})
        elif request.user.role == 'teacher':
            class_request.assigned_teachers.remove(request.user)
            admins = User.objects.filter(role='admin')
            send_notification(
                sender=request.user,
                recipients=list(admins),
                title='رد کلاس توسط استاد',
                body=f'استاد {request.user.get_full_name()} کلاس را رد کرد',
                notif_type='class_rejected'
            )
            return Response({'message': 'کلاس رد شد'})
        return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)


class TeacherAcceptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != 'teacher':
            return Response({'error': 'فقط استاد می‌تونه قبول کنه'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.get(pk=pk, assigned_teachers=request.user)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        class_request.teacher = request.user
        class_request.save()

        admins = User.objects.filter(role='admin')
        send_notification(
            sender=request.user,
            recipients=list(admins),
            title='پذیرش کلاس',
            body=f'استاد {request.user.get_full_name()} کلاس را پذیرفت',
            notif_type='class_accepted'
        )
        send_notification(
            sender=request.user,
            recipients=[class_request.student],
            title='استاد تخصیص داده شد',
            body=f'استاد {request.user.get_full_name()} به کلاس شما تخصیص داده شد',
            notif_type='class_accepted'
        )
        return Response({'message': 'کلاس پذیرفته شد'})


class CompleteClassView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != 'teacher':
            return Response({'error': 'فقط استاد می‌تونه کلاس رو تموم کنه'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.get(pk=pk, teacher=request.user)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        class_request.is_completed = True
        class_request.completed_at = timezone.now()
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


class AdminConfirmCompleteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تونه تایید کنه'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.get(pk=pk, is_completed=True)
        except ClassRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        class_request.status = 'completed'
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
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != 'student':
            return Response({'error': 'فقط دانش‌آموز می‌تونه نظر بده'}, status=status.HTTP_403_FORBIDDEN)
        try:
            class_request = ClassRequest.objects.get(pk=pk, student=request.user, status='completed')
        except ClassRequest.DoesNotExist:
            return Response({'error': 'کلاس پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        satisfaction = request.data.get('satisfaction')
        if not satisfaction or int(satisfaction) not in range(1, 6):
            return Response({'error': 'امتیاز باید بین ۱ تا ۵ باشه'}, status=status.HTTP_400_BAD_REQUEST)

        class_request.satisfaction = satisfaction
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