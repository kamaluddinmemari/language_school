from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Notification
from .serializers import NotificationSerializer, SendNotificationSerializer


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
        if request.user.role != 'admin':
            return Response(
                {'error': 'فقط مدیر می‌تونه نوتیف بفرسته'},
                status=status.HTTP_403_FORBIDDEN
            )
        serializer = SendNotificationSerializer(data=request.data)
        if serializer.is_valid():
            notification = serializer.save(sender=request.user)
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