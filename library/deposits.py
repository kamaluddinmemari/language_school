"""سفارش کتاب بر اساس بیعانه و پیش‌ثبت‌نام."""
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.menu_permissions import can_edit_menu
from . import forecast as fc
from .models import Book, BookDeposit, LibrarySetting

GENDER_LABELS = {'male': 'پسر', 'female': 'دختر'}


def _denied(request):
    return not can_edit_menu(request.user, 'library')


def _deny():
    return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)


class LibrarySettingView(APIView):
    """GET/PATCH: روش محاسبه‌ی سفارش (بیعانه یا روش قبلی) و مبلغ پیش‌فرض بیعانه."""
    permission_classes = [IsAuthenticated]

    def _payload(self, s):
        return {'forecast_mode': s.forecast_mode, 'default_deposit_amount': s.default_deposit_amount}

    def get(self, request):
        if _denied(request):
            return _deny()
        return Response(self._payload(LibrarySetting.get()))

    def patch(self, request):
        if _denied(request):
            return _deny()
        s = LibrarySetting.get()
        mode = request.data.get('forecast_mode')
        if mode is not None:
            if mode not in {v for v, _l in LibrarySetting.ForecastMode.choices}:
                return Response({'error': 'روش نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
            s.forecast_mode = mode
        if request.data.get('default_deposit_amount') not in (None, ''):
            try:
                s.default_deposit_amount = max(int(request.data.get('default_deposit_amount')), 0)
            except (TypeError, ValueError):
                return Response({'error': 'مبلغ نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        s.save()
        return Response(self._payload(s))


def _rows_for_term(term):
    """ثبت‌نام‌شده‌های قطعی ترم ملاک که سطحشان ملاک حداقل یک کتاب است."""
    from class_management.models import ClassSlotEnrollment
    books = list(Book.objects.all())
    level_books = {}
    for b in books:
        for level in fc.levels_for_book(b):
            level_books.setdefault(level, []).append(b.title)
    enrollments = (
        ClassSlotEnrollment.objects.filter(
            class_slot__term_id=term.id,
            class_slot__day_type__in=fc.ONE_AND_TWO_DAY_TYPES,
            payment_verified=True,
        ).exclude(is_carryover=True, carryover_confirmed=False)
        .select_related('student', 'class_slot').order_by('class_slot__assigned_level', 'class_slot__number', 'student__last_name')
    )
    deposits = {d.student_id: d for d in BookDeposit.objects.filter(term_id=term.id)}
    rows, seen = [], set()
    for e in enrollments:
        level = fc.normalize_level(e.class_slot.assigned_level)
        if level not in level_books or e.student_id in seen:
            continue
        seen.add(e.student_id)
        st, slot = e.student, e.class_slot
        gender = st.gender or ''
        if not gender and slot.gender in ('girls', 'boys'):
            gender = 'female' if slot.gender == 'girls' else 'male'
        dep = deposits.get(st.id)
        rows.append({
            'student_id': st.id,
            'name': st.get_full_name().strip(),
            'phone': st.phone or '',
            'national_code': st.national_code or '',
            'gender': gender,
            'gender_display': GENDER_LABELS.get(gender, '—'),
            'level': slot.assigned_level,
            'day_type': slot.day_type,
            'day_display': slot.get_day_type_display(),
            'class_number': slot.number,
            'time_slot': slot.time_slot,
            'teacher_name': slot.teacher_name,
            'books': level_books[level],
            'paid': bool(dep and dep.paid),
            'amount': dep.amount if dep else 0,
        })
    return rows, books


class BookDepositListView(APIView):
    """GET: فهرست زبان‌آموزان ثبت‌نام‌شده در سطح‌های موردنیاز کتاب‌ها + وضعیت بیعانه + خلاصه‌ی هر کتاب."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if _denied(request):
            return _deny()
        term, terms = fc.resolve_term(request.query_params.get('forecast_term'))
        setting = LibrarySetting.get()
        if not term:
            return Response({'term': None, 'rows': [], 'books': [], 'settings': {
                'forecast_mode': setting.forecast_mode, 'default_deposit_amount': setting.default_deposit_amount}})
        rows, books = _rows_for_term(term)
        by_level = {}
        for r in rows:
            by_level.setdefault(fc.normalize_level(r['level']), []).append(r)
        summary = []
        for b in books:
            levels = fc.levels_for_book(b)
            people = {r['student_id']: r for lv in levels for r in by_level.get(lv, [])}
            if not people:
                continue
            paid = [r for r in people.values() if r['paid']]
            summary.append({
                'book_id': b.id, 'title': b.title, 'levels': levels,
                'registered_count': len(people), 'deposit_count': len(paid),
                'deposit_total': sum(r['amount'] for r in paid),
            })
        return Response({
            'term': {'id': term.id, 'title': term.title},
            'rows': rows,
            'books': summary,
            'total_paid': sum(1 for r in rows if r['paid']),
            'total_amount': sum(r['amount'] for r in rows if r['paid']),
            'settings': {'forecast_mode': setting.forecast_mode, 'default_deposit_amount': setting.default_deposit_amount},
        })


class BookDepositSaveView(APIView):
    """POST: ثبت/به‌روزرسانی گروهیِ بیعانه — بدنه: {term_id, items:[{student_id, paid, amount}]}"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if _denied(request):
            return _deny()
        term, _terms = fc.resolve_term(request.data.get('term_id'))
        if not term:
            return Response({'error': 'ترمی پیدا نشد'}, status=status.HTTP_400_BAD_REQUEST)
        items = request.data.get('items')
        if not isinstance(items, list):
            return Response({'error': 'فهرست items الزامی است'}, status=status.HTTP_400_BAD_REQUEST)
        from accounts.models import User
        saved = 0
        with transaction.atomic():
            for item in items:
                try:
                    student = User.objects.get(pk=int(item.get('student_id')), role='student')
                    amount = max(int(item.get('amount') or 0), 0)
                except (TypeError, ValueError, User.DoesNotExist):
                    continue
                BookDeposit.objects.update_or_create(
                    student=student, term=term,
                    defaults={'paid': bool(item.get('paid')), 'amount': amount, 'updated_by': request.user},
                )
                saved += 1
        return Response({'saved': saved})
