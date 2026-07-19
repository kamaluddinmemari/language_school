from django.utils import timezone
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import NewLead, UnregisteredStudent, UnregisteredStudentFollowup, Debtor, DebtorFollowup, DiscountedPerson
from .serializers import (
    NewLeadSerializer,
    UnregisteredStudentSerializer,
    DebtorSerializer,
    DiscountedPersonSerializer,
)


# ---------------------------------------------------------------------------
# لیست انتظار ورودی‌های جدید — فقط مدیر
# ---------------------------------------------------------------------------

class NewLeadListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NewLeadSerializer

    def get_queryset(self):
        if self.request.user.role not in ('admin', 'office'):
            return NewLead.objects.none()
        return NewLead.objects.all()

    def create(self, request, *args, **kwargs):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class NewLeadDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NewLeadSerializer
    queryset = NewLead.objects.all()

    def _forbidden_if_not_admin(self, request):
        return request.user.role not in ('admin', 'office')

    def update(self, request, *args, **kwargs):
        if self._forbidden_if_not_admin(request):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if self._forbidden_if_not_admin(request):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class NewLeadActionView(APIView):
    """POST: یکی از اکشن‌های followup1 / followup2 / register / cancel روی یک سرنخ"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            lead = NewLead.objects.get(pk=pk)
        except NewLead.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        now = timezone.now()
        if action == 'followup1':
            lead.followup1_at = now
            lead.followup1_by = request.user
        elif action == 'followup2':
            lead.followup2_at = now
            lead.followup2_by = request.user
        elif action == 'register':
            lead.status = NewLead.Status.REGISTERED
            lead.registered_at = now
        elif action == 'cancel':
            lead.status = NewLead.Status.CANCELLED
            lead.cancelled_at = now
        elif action == 'deposit':
            amount = request.data.get('amount')
            if amount in (None, ''):
                return Response({'error': 'مبلغ بیعانه را وارد کنید'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                lead.deposit_amount = int(amount)
            except (TypeError, ValueError):
                return Response({'error': 'مبلغ بیعانه نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
            lead.deposit_paid_at = now
        else:
            return Response({'error': 'اکشن نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        lead.save()
        return Response(NewLeadSerializer(lead).data)


# ---------------------------------------------------------------------------
# زبان‌آموزان ثبت‌نام‌نشده — ثبت توسط استاد، پیگیری فقط توسط مدیر
# ---------------------------------------------------------------------------

class UnregisteredStudentListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UnregisteredStudentSerializer

    def get_queryset(self):
        if self.request.user.role not in ('admin', 'office'):
            return UnregisteredStudent.objects.none()
        return UnregisteredStudent.objects.all()

    def create(self, request, *args, **kwargs):
        from accounts.models import User
        if request.user.role not in User.TEACHER_LIKE_ROLES and request.user.role not in ('admin', 'office'):
            return Response({'error': 'فقط استاد یا مدیر می‌تواند ثبت کند'}, status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(submitted_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class UnregisteredStudentDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UnregisteredStudentSerializer
    queryset = UnregisteredStudent.objects.all()

    def update(self, request, *args, **kwargs):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class UnregisteredStudentFollowupView(APIView):
    """POST: ثبت یک پیگیری جدید — بدون محدودیت تعداد"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            student = UnregisteredStudent.objects.get(pk=pk)
        except UnregisteredStudent.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        UnregisteredStudentFollowup.objects.create(
            student=student, followed_up_by=request.user, note=request.data.get('note', '')
        )
        return Response(UnregisteredStudentSerializer(student).data, status=status.HTTP_201_CREATED)


class UnregisteredStudentRegisterView(APIView):
    """POST: ثبت‌نام شد — بایگانی می‌شود ولی همیشه قابل ویرایش باقی می‌ماند"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            student = UnregisteredStudent.objects.get(pk=pk)
        except UnregisteredStudent.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        student.status = UnregisteredStudent.Status.REGISTERED
        student.registered_at = timezone.now()
        student.save()
        return Response(UnregisteredStudentSerializer(student).data)


class UnregisteredStudentStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        qs = UnregisteredStudent.objects.all()
        tracking = qs.filter(status=UnregisteredStudent.Status.TRACKING)
        registered = qs.filter(status=UnregisteredStudent.Status.REGISTERED)
        now_local = timezone.localtime(timezone.now())
        import jdatetime
        return Response({
            'total': qs.count(),
            'tracking_count': tracking.count(),
            'registered_count': registered.count(),
            'total_tuition_potential': sum(s.tuition_price or 0 for s in tracking),
            'total_tuition_registered': sum(s.tuition_price or 0 for s in registered),
            'generated_at_jalali': jdatetime.datetime.fromgregorian(datetime=now_local).strftime('%Y/%m/%d - %H:%M:%S'),
        })


# ---------------------------------------------------------------------------
# بدهکاران — فقط مدیر
# ---------------------------------------------------------------------------

class DebtorListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DebtorSerializer

    def get_queryset(self):
        if self.request.user.role not in ('admin', 'office'):
            return Debtor.objects.none()
        return Debtor.objects.all()

    def create(self, request, *args, **kwargs):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class DebtorDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DebtorSerializer
    queryset = Debtor.objects.all()

    def update(self, request, *args, **kwargs):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class DebtorFollowupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            debtor = Debtor.objects.get(pk=pk)
        except Debtor.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        DebtorFollowup.objects.create(debtor=debtor, followed_up_by=request.user, note=request.data.get('note', ''))
        return Response(DebtorSerializer(debtor).data, status=status.HTTP_201_CREATED)


class DebtorSettleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            debtor = Debtor.objects.get(pk=pk)
        except Debtor.DoesNotExist:
            return Response({'error': 'مورد پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        debtor.status = Debtor.Status.SETTLED
        debtor.settled_at = timezone.now()
        debtor.save()
        return Response(DebtorSerializer(debtor).data)


class DebtorStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        qs = Debtor.objects.all()
        pending = qs.filter(status=Debtor.Status.PENDING)
        settled = qs.filter(status=Debtor.Status.SETTLED)
        now_local = timezone.localtime(timezone.now())
        import jdatetime
        return Response({
            'total': qs.count(),
            'pending_count': pending.count(),
            'settled_count': settled.count(),
            'total_debt_pending': sum(d.debt_amount for d in pending),
            'total_debt_settled': sum(d.debt_amount for d in settled),
            'generated_at_jalali': jdatetime.datetime.fromgregorian(datetime=now_local).strftime('%Y/%m/%d - %H:%M:%S'),
        })


# ---------------------------------------------------------------------------
# افراد دارای تخفیف — فقط مدیر
# ---------------------------------------------------------------------------

class DiscountedPersonListView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DiscountedPersonSerializer

    def get_queryset(self):
        if self.request.user.role not in ('admin', 'office'):
            return DiscountedPerson.objects.none()
        return DiscountedPerson.objects.all()

    def create(self, request, *args, **kwargs):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class DiscountedPersonDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DiscountedPersonSerializer
    queryset = DiscountedPerson.objects.all()

    def update(self, request, *args, **kwargs):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role not in ('admin', 'office'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)
