from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from accounts.models import ClassRequest, User
from .serializers import (
    ClassRequestSerializer,
    ClassRequestCreateSerializer,
    ClassRequestAdminSerializer
)


class ClassRequestListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            if self.request.user.role in ['admin', 'teacher']:
                return ClassRequestAdminSerializer
            return ClassRequestCreateSerializer
        return ClassRequestSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return ClassRequest.objects.all()
        elif user.role == 'teacher':
            return ClassRequest.objects.filter(
                status='approved',
                teacher=None
            )
        else:
            return ClassRequest.objects.filter(student=user)


class ClassRequestDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ClassRequestAdminSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return ClassRequest.objects.all()
        elif user.role == 'teacher':
            return ClassRequest.objects.filter(teacher=user)
        return ClassRequest.objects.filter(student=user)


class ApproveClassView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != 'admin':
            return Response(
                {'error': 'فقط مدیر می‌تونه تایید کنه'},
                status=status.HTTP_403_FORBIDDEN
            )
        try:
            class_request = ClassRequest.objects.get(pk=pk)
        except ClassRequest.DoesNotExist:
            return Response(
                {'error': 'درخواست پیدا نشد'},
                status=status.HTTP_404_NOT_FOUND
            )
        class_request.status = 'approved'
        class_request.save()
        return Response({'message': 'درخواست تایید شد'})


class TeacherAcceptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != 'teacher':
            return Response(
                {'error': 'فقط استاد می‌تونه قبول کنه'},
                status=status.HTTP_403_FORBIDDEN
            )
        try:
            class_request = ClassRequest.objects.get(
                pk=pk,
                status='approved',
                teacher=None
            )
        except ClassRequest.DoesNotExist:
            return Response(
                {'error': 'درخواست پیدا نشد'},
                status=status.HTTP_404_NOT_FOUND
            )
        class_request.teacher = request.user
        class_request.save()
        return Response({'message': 'کلاس با موفقیت پذیرفته شد'})

# Create your views here.
