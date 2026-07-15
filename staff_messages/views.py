from django.utils import timezone
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from accounts.models import User
from notifications.utils import send_notification
from .models import TeacherNotice, EntryExitPermissionRequest
from .serializers import (
    TeacherNoticeSerializer,
    TeacherNoticeCreateSerializer,
    EntryExitPermissionRequestSerializer,
)


# ---------------------------------------------------------------------------
# یادآور ثبت غیاب / پیام‌های آزاد مدیر به استاد
# ---------------------------------------------------------------------------

class TeacherNoticeListView(generics.ListAPIView):
    """GET: مدیر همه‌ی پیام‌های (حذف‌نشده‌ی) ارسالی را می‌بیند، استاد فقط پیام‌های خودش را"""
    permission_classes = [IsAuthenticated]
    serializer_class = TeacherNoticeSerializer

    def get_queryset(self):
        user = self.request.user
        qs = TeacherNotice.objects.filter(is_deleted=False)
        if user.role == 'admin':
            teacher_id = self.request.query_params.get('teacher_id')
            if teacher_id:
                qs = qs.filter(teacher_id=teacher_id)
            return qs
        return qs.filter(teacher=user)


class TeacherNoticeSendView(APIView):
    """POST: مدیر یک پیام را هم‌زمان برای چند استاد می‌فرستد (برای هرکدام یک ردیف مجزا)"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تواند پیام بفرستد'}, status=status.HTTP_403_FORBIDDEN)
        serializer = TeacherNoticeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        teacher_ids = serializer.validated_data['teacher_ids']
        body = serializer.validated_data['body']

        teachers = list(User.objects.filter(id__in=teacher_ids))
        created = []
        for teacher in teachers:
            notice = TeacherNotice.objects.create(sender=request.user, teacher=teacher, body=body)
            created.append(notice)

        send_notification(
            sender=request.user,
            recipients=teachers,
            title='یادآوری از مدیریت',
            body=body,
            notif_type='general',
        )
        return Response(TeacherNoticeSerializer(created, many=True).data, status=status.HTTP_201_CREATED)


class TeacherNoticeDetailView(APIView):
    """PATCH: ویرایش متن پیام (فقط مدیر) — DELETE: حذف نرم با ثبت لاگ حذف‌کننده/زمان (فقط مدیر)"""
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        try:
            return TeacherNotice.objects.get(pk=pk, is_deleted=False)
        except TeacherNotice.DoesNotExist:
            return None

    def patch(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        notice = self._get(pk)
        if not notice:
            return Response({'error': 'پیام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        body = request.data.get('body')
        if not body:
            return Response({'error': 'متن پیام نمی‌تواند خالی باشد'}, status=status.HTTP_400_BAD_REQUEST)
        notice.body = body
        notice.save()
        return Response(TeacherNoticeSerializer(notice).data)

    def delete(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        notice = self._get(pk)
        if not notice:
            return Response({'error': 'پیام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        notice.is_deleted = True
        notice.deleted_by = request.user
        notice.deleted_at = timezone.now()
        notice.save()
        return Response({'message': 'پیام حذف شد'})


class TeacherNoticeAcknowledgeView(APIView):
    """POST: استاد با دیدن پیام، مشاهده‌اش را تایید می‌کند"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            notice = TeacherNotice.objects.get(pk=pk, teacher=request.user, is_deleted=False)
        except TeacherNotice.DoesNotExist:
            return Response({'error': 'پیام پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        if not notice.seen_at:
            notice.seen_at = timezone.now()
            notice.save()
        return Response(TeacherNoticeSerializer(notice).data)


# ---------------------------------------------------------------------------
# مجوز ورود/خروج دانش‌آموز
# ---------------------------------------------------------------------------

class EntryExitRequestListView(generics.ListCreateAPIView):
    """GET: مدیر همه را می‌بیند، استاد فقط درخواست‌های خودش — POST: فقط استاد"""
    permission_classes = [IsAuthenticated]
    serializer_class = EntryExitPermissionRequestSerializer

    def get_queryset(self):
        user = self.request.user
        qs = EntryExitPermissionRequest.objects.filter(is_deleted=False)
        if user.role == 'admin':
            status_filter = self.request.query_params.get('status')
            if status_filter:
                qs = qs.filter(status=status_filter)
            return qs
        return qs.filter(teacher=user)

    def create(self, request, *args, **kwargs):
        if request.user.role not in User.TEACHER_LIKE_ROLES:
            return Response({'error': 'فقط استاد می‌تواند درخواست مجوز ثبت کند'}, status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        req = serializer.save(teacher=request.user)

        admins = list(User.objects.filter(role='admin'))
        send_notification(
            sender=request.user,
            recipients=admins,
            title='درخواست مجوز ورود/خروج جدید',
            body=f"{request.user.first_name} {request.user.last_name} برای «{req.student_name}» درخواست {req.get_permission_type_display()} ثبت کرد.",
            notif_type='general',
        )
        return Response(EntryExitPermissionRequestSerializer(req).data, status=status.HTTP_201_CREATED)


class EntryExitRequestDetailView(APIView):
    """PATCH: مدیر هر فیلدی، استاد فقط درخواست خودش و فقط تا وقتی «در انتظار بررسی» است — DELETE: حذف نرم با لاگ"""
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        try:
            return EntryExitPermissionRequest.objects.get(pk=pk, is_deleted=False)
        except EntryExitPermissionRequest.DoesNotExist:
            return None

    def patch(self, request, pk):
        req = self._get(pk)
        if not req:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        user = request.user
        if user.role == 'admin':
            for field in ['student_name', 'class_level', 'permission_type', 'request_message', 'response_message', 'coordination_person', 'coordination_phone']:
                if field in request.data:
                    setattr(req, field, request.data[field])
            req.save()
            return Response(EntryExitPermissionRequestSerializer(req).data)
        if req.teacher_id == user.id:
            if req.status != EntryExitPermissionRequest.Status.PENDING:
                return Response({'error': 'این درخواست دیگر در انتظار بررسی نیست و قابل ویرایش نیست'}, status=status.HTTP_400_BAD_REQUEST)
            for field in ['student_name', 'class_level', 'permission_type', 'request_message']:
                if field in request.data:
                    setattr(req, field, request.data[field])
            req.save()
            return Response(EntryExitPermissionRequestSerializer(req).data)
        return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

    def delete(self, request, pk):
        req = self._get(pk)
        if not req:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        user = request.user
        if not (user.role == 'admin' or req.teacher_id == user.id):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        req.is_deleted = True
        req.deleted_by = user
        req.deleted_at = timezone.now()
        req.save()
        return Response({'message': 'درخواست حذف شد'})


class EntryExitRequestDecideView(APIView):
    """POST: تصمیم مدیر — بدنه: {status: approved|rejected, response_message}"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تواند تصمیم بگیرد'}, status=status.HTTP_403_FORBIDDEN)
        try:
            req = EntryExitPermissionRequest.objects.get(pk=pk, is_deleted=False)
        except EntryExitPermissionRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        decision = request.data.get('status')
        if decision not in (EntryExitPermissionRequest.Status.APPROVED, EntryExitPermissionRequest.Status.REJECTED):
            return Response({'error': 'وضعیت باید approved یا rejected باشد'}, status=status.HTTP_400_BAD_REQUEST)

        req.status = decision
        req.response_message = request.data.get(
            'response_message',
            'اجازه‌ی ' + req.get_permission_type_display() + (' صادر شد.' if decision == 'approved' else ' صادر نشد.')
        )
        if 'coordination_person' in request.data:
            req.coordination_person = request.data.get('coordination_person') or ''
        if 'coordination_phone' in request.data:
            req.coordination_phone = request.data.get('coordination_phone') or ''
        req.decided_by = request.user
        req.decided_at = timezone.now()
        req.save()

        coordination_note = ''
        if req.coordination_person or req.coordination_phone:
            coordination_note = f" — هماهنگی با: {req.coordination_person or ''} {req.coordination_phone or ''}".strip()
        send_notification(
            sender=request.user,
            recipients=[req.teacher],
            title='نتیجه‌ی درخواست مجوز ورود/خروج',
            body=f"«{req.student_name}» — {req.get_permission_type_display()}: {req.response_message}{coordination_note}",
            notif_type='general',
        )
        return Response(EntryExitPermissionRequestSerializer(req).data)
