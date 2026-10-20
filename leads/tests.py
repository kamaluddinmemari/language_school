from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from class_management.models import ClassSlot, ClassSlotEnrollment, Term
from accounts.services import sync_student_from_lead
from .models import Debtor, UnregisteredStudent, auto_mark_unregistered_registered
from .serializers import DebtorSerializer, UnregisteredStudentSerializer
from .views import DebtorSettleView, UnregisteredStudentClassEnrollView, _resolve_unregistered_student


class DebtorEnrollmentTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username='debtor-admin', password='test-password', role='admin',
            first_name='مدیر', last_name='آموزش', phone='09120000001',
        )
        self.student = User.objects.create_user(
            username='carried-student', password='test-password', role='student',
            first_name='دانش‌آموز', last_name='آزمایشی', phone='09120000002', gender='female',
        )
        self.previous_term = Term.objects.create(
            year=1404, term_number=1, start_date=date(2025, 3, 21), end_date=date(2025, 6, 20),
        )
        self.term = Term.objects.create(
            year=1404, term_number=2, start_date=date(2025, 6, 21), end_date=date(2025, 9, 21),
        )
        self.factory = APIRequestFactory()
        self.gray_class = self.make_class(21)
        self.other_class = self.make_class(22)

    def make_class(self, number):
        return ClassSlot.objects.create(
            number=number, term=self.term, day_type='even', time_slot='09:45-11:15',
            gender='girls', assigned_level='A1', capacity=20,
        )

    def make_debtor(self, first_name='دانش‌آموز', last_name='آزمایشی', phone='09120000002'):
        return Debtor.objects.create(
            first_name=first_name, last_name=last_name, phone=phone,
            class_level='A1', debt_amount=120000, term=self.term,
        )

    def call(self, method, debtor, data=None):
        if method == 'GET':
            request = self.factory.get(f'/api/leads/debtors/{debtor.pk}/settle/')
        else:
            request = self.factory.post(f'/api/leads/debtors/{debtor.pk}/settle/', data or {}, format='json')
        force_authenticate(request, user=self.admin)
        return DebtorSettleView.as_view()(request, pk=debtor.pk)

    def test_settle_moves_gray_carryover_to_selected_class_and_marks_registered(self):
        carried = ClassSlotEnrollment.objects.create(
            class_slot=self.gray_class, student=self.student,
            payment_method='cash', tuition_amount=0, payment_verified=True,
            is_carryover=True, carryover_confirmed=False, carried_from_term=self.previous_term,
        )
        debtor = self.make_debtor()

        options = self.call('GET', debtor)
        self.assertEqual(options.status_code, 200)
        self.assertEqual(options.data['preferred_class_id'], self.gray_class.pk)
        self.assertTrue(next(item for item in options.data['classes'] if item['id'] == self.gray_class.pk)['is_preferred'])

        response = self.call('POST', debtor, {'target_class_slot_id': self.other_class.pk})

        self.assertEqual(response.status_code, 200, response.data)
        debtor.refresh_from_db()
        carried.refresh_from_db()
        self.assertEqual(debtor.status, Debtor.Status.REGISTERED)
        self.assertEqual(carried.class_slot_id, self.other_class.pk)
        self.assertTrue(carried.carryover_confirmed)
        self.assertEqual(carried.tuition_amount, debtor.debt_amount)
        self.assertFalse(ClassSlotEnrollment.objects.filter(class_slot=self.gray_class, student=self.student).exists())

    def test_settle_adds_new_student_to_chosen_class(self):
        debtor = self.make_debtor()

        response = self.call('POST', debtor, {'target_class_slot_id': self.gray_class.pk})

        self.assertEqual(response.status_code, 200, response.data)
        debtor.refresh_from_db()
        self.assertEqual(debtor.status, Debtor.Status.REGISTERED)
        enrollment = ClassSlotEnrollment.objects.get(class_slot=self.gray_class, student=self.student)
        self.assertTrue(enrollment.payment_verified)
        self.assertFalse(enrollment.is_carryover)
        self.assertEqual(enrollment.tuition_amount, debtor.debt_amount)

    def test_unregistered_student_can_be_enrolled_from_followup_row(self):
        record = UnregisteredStudent.objects.create(
            first_name='زبان‌آموز', last_name='پیگیری', phone='09120000044',
            class_level='A1', tuition_price=90000, term=self.term,
        )
        get_request = self.factory.get(f'/api/leads/unregistered-students/{record.pk}/enroll/')
        force_authenticate(get_request, user=self.admin)
        options = UnregisteredStudentClassEnrollView.as_view()(get_request, pk=record.pk)
        self.assertEqual(options.status_code, 200)
        self.assertTrue(any(item['id'] == self.gray_class.pk for item in options.data['classes']))

        request = self.factory.post(
            f'/api/leads/unregistered-students/{record.pk}/enroll/',
            {'target_class_slot_id': self.gray_class.pk}, format='json',
        )
        force_authenticate(request, user=self.admin)
        response = UnregisteredStudentClassEnrollView.as_view()(request, pk=record.pk)

        self.assertEqual(response.status_code, 200, response.data)
        record.refresh_from_db()
        self.assertEqual(record.status, UnregisteredStudent.Status.REGISTERED)
        student = get_user_model().objects.get(role='student', phone='09120000044')
        enrollment = ClassSlotEnrollment.objects.get(class_slot=self.gray_class, student=student)
        self.assertEqual(enrollment.tuition_amount, 90000)
        self.assertTrue(enrollment.payment_verified)


class NationalCodeIdentityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.term = Term.objects.create(
            year=1405, term_number=1, start_date=date(2026, 3, 21), end_date=date(2026, 6, 20),
        )
        self.slot = ClassSlot.objects.create(
            number=9, term=self.term, day_type='even', time_slot='09:45-11:15',
            gender='girls', assigned_level='104', capacity=20,
        )
        self.registered = User.objects.create_user(
            username='raha-registered', password='test-password', role='student',
            first_name='رها', last_name='مقدسی', phone='09120000077',
            national_code='1111111111', gender='female',
        )
        ClassSlotEnrollment.objects.create(
            class_slot=self.slot, student=self.registered, payment_method='cash',
            tuition_amount=100000, payment_verified=True,
        )

    def test_same_name_and_shared_phone_do_not_assign_other_students_class(self):
        record = UnregisteredStudent.objects.create(
            first_name='رها', last_name='مقدسی', phone='09120000077',
            national_code='2222222222', class_level='104', term=self.term,
            is_misplaced=True, misplaced_from_slot=self.slot,
        )

        data = UnregisteredStudentSerializer(record).data

        self.assertFalse(data['has_current_class'])
        self.assertFalse(data['is_misplaced'])
        self.assertIsNone(data['class_slot'])
        self.assertIsNone(data['misplaced_class_number'])
        self.assertEqual(data['class_status'], 'none')

    def test_registering_one_person_does_not_auto_mark_same_name_other_code(self):
        registered_row = UnregisteredStudent.objects.create(
            first_name='رها', last_name='مقدسی', phone='09120000077',
            national_code='1111111111', class_level='A1', term=self.term,
        )
        other_row = UnregisteredStudent.objects.create(
            first_name='رها', last_name='مقدسی', phone='09120000077',
            national_code='2222222222', class_level='A2', term=self.term,
        )

        auto_mark_unregistered_registered(self.registered, term_id=self.term.pk, slot_id=self.slot.pk)

        registered_row.refresh_from_db()
        other_row.refresh_from_db()
        self.assertEqual(registered_row.status, UnregisteredStudent.Status.REGISTERED)
        self.assertEqual(other_row.status, UnregisteredStudent.Status.TRACKING)

    def test_resolve_and_sync_do_not_fallback_to_shared_phone_when_code_is_given(self):
        record = UnregisteredStudent(
            first_name='رها', last_name='مقدسی', phone='09120000077',
            national_code='2222222222', class_level='A2', term=self.term,
        )

        self.assertIsNone(_resolve_unregistered_student(record, create=False))
        student, created = sync_student_from_lead(
            first_name=record.first_name, last_name=record.last_name,
            phone=record.phone, national_code=record.national_code, language_level=record.class_level,
        )

        self.assertTrue(created)
        self.assertNotEqual(student.pk, self.registered.pk)
        self.assertEqual(student.national_code, '2222222222')


class DebtorDropoutLabelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.student = User.objects.create_user(
            username='dropout-debtor', password='test-password', role='student',
            first_name='زبان‌آموز', last_name='ریزش', phone='09120000088',
        )
        self.previous_term = Term.objects.create(
            year=1405, term_number=1, start_date=date(2026, 3, 21), end_date=date(2026, 6, 20),
        )
        self.current_term = Term.objects.create(
            year=1405, term_number=2, start_date=date(2026, 6, 21), end_date=date(2026, 9, 21),
        )
        self.old_slot = ClassSlot.objects.create(
            number=88, term=self.previous_term, day_type='even', time_slot='09:45-11:15',
            gender='girls', assigned_level='A1', capacity=20,
        )
        ClassSlotEnrollment.objects.create(
            class_slot=self.old_slot, student=self.student, payment_method='cash',
            tuition_amount=100000, payment_verified=True,
        )
        self.debtor = Debtor.objects.create(
            first_name=self.student.first_name, last_name=self.student.last_name,
            phone=self.student.phone, student=self.student, class_level='A1',
            debt_amount=100000, term=self.current_term,
        )

    def test_debtor_without_current_class_or_unregistered_row_is_labeled_dropout(self):
        data = DebtorSerializer(self.debtor).data

        self.assertEqual(data['class_status'], 'dropout')
        self.assertEqual(data['class_status_text'], 'فرد ریزشی می‌باشد و در این ترم سر هیچ کلاسی نیست')
        self.assertIsNone(data['class_slot_number'])

    def test_unregistered_counterpart_keeps_existing_class_status_behavior(self):
        UnregisteredStudent.objects.create(
            first_name=self.student.first_name, last_name=self.student.last_name,
            phone=self.student.phone, class_level='A1', term=self.current_term,
        )

        data = DebtorSerializer(self.debtor).data

        self.assertTrue(data['also_unregistered'])
        self.assertNotEqual(data['class_status'], 'dropout')
