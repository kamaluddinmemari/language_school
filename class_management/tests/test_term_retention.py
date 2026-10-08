from datetime import date
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from ..attendance import roster_attendance_payload
from ..models import ClassSlot, ClassSlotEnrollment, Term, TermRetentionFollowUp
from ..views import (
    ConfirmCarryoverEnrollmentView,
    ClassSlotEnrollView,
    ClassSlotExcelImportView,
    ClassSlotRosterView,
    MarkCarryoverEnrollmentView,
    TermRetentionFollowUpView,
    TransferEnrollmentView,
    VerifyEnrollmentPaymentView,
)


class TermRetentionFollowUpTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username='retention_admin', password='test-password', role='admin',
            first_name='مدیر', last_name='آموزش', phone='09120000001',
        )
        self.previous_term = Term.objects.create(
            year=1404, term_number=1, start_date=date(2025, 3, 21), end_date=date(2025, 6, 20),
        )
        self.current_term = Term.objects.create(
            year=1404, term_number=2, start_date=date(2025, 6, 21), end_date=date(2025, 9, 21),
        )
        self.factory = APIRequestFactory()

    def make_student(self, username, phone, national_code):
        return get_user_model().objects.create_user(
            username=username, password='test-password', role='student',
            first_name='دانش‌آموز', last_name='آزمایشی', phone=phone, national_code=national_code,
        )

    def make_enrollment(
        self, student, term, number, payment_verified=True, is_carryover=False,
        carryover_confirmed=False, carried_from_term=None, day_type='even',
        level='A1', gender='girls', teacher_name='',
    ):
        slot = ClassSlot.objects.create(
            number=number, term=term, day_type=day_type, time_slot='09:45-11:15',
            gender=gender, assigned_level=level, teacher_name=teacher_name,
        )
        enrollment = ClassSlotEnrollment.objects.create(
            class_slot=slot, student=student, payment_method='cash',
            payment_verified=payment_verified, is_carryover=is_carryover,
            carryover_confirmed=carryover_confirmed, carried_from_term=carried_from_term,
        )
        return enrollment

    def call_view(self, method, data):
        if method == 'GET':
            request = self.factory.get('/api/class-management/term-retention/', data)
        else:
            request = self.factory.post('/api/class-management/term-retention/', data, format='json')
        force_authenticate(request, user=self.admin)
        return TermRetentionFollowUpView.as_view()(request)

    def get_retention_rows(self, **filters):
        response = self.call_view('GET', {
            'previous_term_id': self.previous_term.pk,
            'current_term_id': self.current_term.pk,
            **filters,
        })
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_get_returns_unique_previous_students_and_separates_pending_payment(self):
        registered = self.make_student('continued_student', '09120000002', '1000000001')
        pending = self.make_student('pending_student', '09120000003', '1000000002')
        absent = self.make_student('absent_student', '09120000004', '1000000003')

        self.make_enrollment(registered, self.previous_term, 1)
        self.make_enrollment(registered, self.previous_term, 2)
        self.make_enrollment(pending, self.previous_term, 3)
        self.make_enrollment(absent, self.previous_term, 4)
        self.make_enrollment(registered, self.current_term, 1)
        self.make_enrollment(pending, self.current_term, 2, payment_verified=False)

        data = self.get_retention_rows()

        self.assertEqual(data['summary']['previous_total'], 3)
        self.assertEqual(data['summary']['registered_count'], 1)
        self.assertEqual(data['summary']['pending_payment_count'], 1)
        self.assertEqual(data['summary']['not_registered_count'], 1)
        rows = {row['student_id']: row for row in data['results']}
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(rows[registered.pk]['previous_classes']), 2)
        self.assertEqual(rows[pending.pk]['current_state'], 'pending_payment')
        self.assertEqual(rows[absent.pk]['follow_up_status'], TermRetentionFollowUp.Status.NEEDS_FOLLOW_UP)

    def test_carried_student_is_follow_up_candidate_but_remains_on_attendance_roster(self):
        student = self.make_student('carried_student', '09120000007', '1000000006')
        self.make_enrollment(student, self.previous_term, 7)
        carried = self.make_enrollment(
            student, self.current_term, 7, is_carryover=True, carried_from_term=self.previous_term,
        )

        data = self.get_retention_rows()
        row = next(item for item in data['results'] if item['student_id'] == student.pk)
        attendance_data = roster_attendance_payload(carried.class_slot)
        roster_request = self.factory.get(f'/api/class-management/slots/{carried.class_slot_id}/roster/')
        force_authenticate(roster_request, user=self.admin)
        roster_response = ClassSlotRosterView.as_view()(roster_request, pk=carried.class_slot_id)
        roster_rows = roster_response.data.get('results', []) if isinstance(roster_response.data, dict) else roster_response.data

        self.assertEqual(row['current_state'], 'carried_forward')
        self.assertTrue(row['needs_follow_up'])
        self.assertEqual(data['summary']['carried_forward_count'], 1)
        self.assertEqual([item['student_id'] for item in attendance_data['roster']], [student.pk])
        self.assertTrue(attendance_data['roster'][0]['needs_follow_up'])
        self.assertEqual(attendance_data['roster'][0]['needs_follow_up_label'], 'منتظر ثبت‌نام')
        self.assertEqual(attendance_data['roster'][0]['student_name_color'], '#6c757d')
        self.assertEqual(attendance_data['roster'][0]['student_row_color'], '#e9ecef')
        self.assertEqual(roster_response.status_code, 200)
        self.assertTrue(roster_rows[0]['needs_follow_up'])

    def test_registration_in_another_class_in_same_term_removes_student_from_follow_up(self):
        student = self.make_student('other_class_student', '09120000008', '1000000007')
        self.make_enrollment(student, self.previous_term, 8)
        self.make_enrollment(
            student, self.current_term, 8, is_carryover=True, carried_from_term=self.previous_term,
        )
        self.make_enrollment(student, self.current_term, 9, is_carryover=False)

        data = self.get_retention_rows()
        row = next(item for item in data['results'] if item['student_id'] == student.pk)

        self.assertEqual(row['current_state'], 'registered')
        self.assertFalse(row['needs_follow_up'])

    def test_moving_carried_student_to_another_class_in_same_term_confirms_continuation(self):
        student = self.make_student('moved_carry_student', '09120000012', '1000000011')
        self.make_enrollment(student, self.previous_term, 11)
        carried = self.make_enrollment(
            student, self.current_term, 11, is_carryover=True, carried_from_term=self.previous_term,
        )
        target = ClassSlot.objects.create(
            number=10, term=self.current_term, day_type='odd', time_slot='11:30-13:00',
            gender='girls', assigned_level='A1', capacity=20,
        )
        request = self.factory.post(
            '/api/class-management/transfer/', {'target_slot_id': target.pk}, format='json',
        )
        force_authenticate(request, user=self.admin)

        response = TransferEnrollmentView.as_view()(request, pk=carried.class_slot_id, student_id=student.pk)

        self.assertEqual(response.status_code, 200)
        moved = ClassSlotEnrollment.objects.get(class_slot=target, student=student)
        self.assertTrue(moved.is_carryover)
        self.assertTrue(moved.carryover_confirmed)
        row = next(item for item in self.get_retention_rows()['results'] if item['student_id'] == student.pk)
        self.assertEqual(row['current_state'], 'registered')
        self.assertFalse(row['needs_follow_up'])

    def test_day_level_and_gender_filters_apply_to_class_details(self):
        matching = self.make_student('filtered_student', '09120000009', '1000000008')
        other_gender = self.make_student('other_gender_student', '09120000010', '1000000009')
        self.make_enrollment(matching, self.previous_term, 1, day_type='even', level='A1', gender='girls')
        self.make_enrollment(other_gender, self.previous_term, 2, day_type='odd', level='A2', gender='boys')

        data = self.get_retention_rows(day_type='even', level='A1', gender='girls')
        self.assertEqual([row['student_id'] for row in data['results']], [matching.pk])
        self.assertEqual(data['active_filters'], {'day_type': 'even', 'level': 'A1', 'gender': 'girls', 'teacher_name': ''})

    def test_teacher_filter_returns_only_matching_classes_and_teacher_option(self):
        matches = self.make_student('teacher_match_student', '09120000021', '1000000021')
        other = self.make_student('teacher_other_student', '09120000022', '1000000022')
        self.make_enrollment(matches, self.previous_term, 21, teacher_name='استاد یک')
        self.make_enrollment(other, self.previous_term, 22, teacher_name='استاد دو')

        data = self.get_retention_rows(teacher_name='استاد یک')

        self.assertEqual([row['student_id'] for row in data['results']], [matches.pk])
        self.assertEqual(data['active_filters']['teacher_name'], 'استاد یک')
        self.assertEqual(data['teacher_options'], ['استاد دو', 'استاد یک'])

    def test_excel_import_creates_gray_carryover_without_charging_payment(self):
        student = self.make_student('excel_carryover_student', '09120000023', '1000000023')
        self.make_enrollment(student, self.previous_term, 23)
        target = ClassSlot.objects.create(
            number=24, term=self.current_term, day_type='even', time_slot='09:45-11:15',
            gender='girls', assigned_level='A1', capacity=20,
        )
        request = self.factory.post('/api/class-management/slots/24/import-excel/', {
            'mode': 'commit',
            'rows': json.dumps([{
                'row_number': 14, 'first_name': student.first_name, 'last_name': student.last_name,
                'national_code': student.national_code, 'phone': student.phone,
            }]),
            'approved_rows': '[]',
        }, format='multipart')
        force_authenticate(request, user=self.admin)

        response = ClassSlotExcelImportView.as_view()(request, pk=target.pk)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['carried_count'], 1)
        carried = ClassSlotEnrollment.objects.get(class_slot=target, student=student)
        self.assertTrue(carried.is_carryover)
        self.assertFalse(carried.carryover_confirmed)
        self.assertTrue(carried.payment_verified)
        self.assertEqual(carried.carried_from_term_id, self.previous_term.pk)
        self.assertEqual(carried.tuition_amount, 0)
        row = next(item for item in self.get_retention_rows()['results'] if item['student_id'] == student.pk)
        self.assertTrue(row['needs_follow_up'])

    def test_manual_registration_promotes_carryover_to_confirmed_registration(self):
        student = self.make_student('manual_carryover_student', '09120000024', '1000000024')
        self.make_enrollment(student, self.previous_term, 24)
        carried = self.make_enrollment(
            student, self.current_term, 25, is_carryover=True, carried_from_term=self.previous_term,
        )
        request = self.factory.post('/api/class-management/slots/25/enroll/', {
            'student_id': student.pk,
            'payment_method': 'cash',
            'tuition_amount': 1000,
        }, format='json')
        force_authenticate(request, user=self.admin)

        response = ClassSlotEnrollView.as_view()(request, pk=carried.class_slot_id)

        self.assertEqual(response.status_code, 201, response.data)
        carried.refresh_from_db()
        self.assertTrue(carried.carryover_confirmed)
        self.assertTrue(carried.payment_verified)
        self.assertEqual(carried.tuition_amount, 1000)
        row = next(item for item in self.get_retention_rows()['results'] if item['student_id'] == student.pk)
        self.assertEqual(row['current_state'], 'registered')
        self.assertFalse(row['needs_follow_up'])
        self.assertEqual(response.data['enrollment']['student_name_color'], '#212529')
        self.assertEqual(response.data['enrollment']['needs_follow_up_label'], '')

    def test_app_payment_verification_confirms_carryover_automatically(self):
        student = self.make_student('app_confirmed_carryover', '09120000025', '1000000025')
        self.make_enrollment(student, self.previous_term, 26)
        carried = self.make_enrollment(
            student, self.current_term, 27, payment_verified=False,
            is_carryover=True, carried_from_term=self.previous_term,
        )
        request = self.factory.post('/api/class-management/slots/27/verify-payment/', {}, format='json')
        force_authenticate(request, user=self.admin)

        response = VerifyEnrollmentPaymentView.as_view()(request, pk=carried.class_slot_id, student_id=student.pk)

        self.assertEqual(response.status_code, 200, response.data)
        carried.refresh_from_db()
        self.assertTrue(carried.payment_verified)
        self.assertTrue(carried.carryover_confirmed)
        self.assertFalse(response.data['enrollment']['needs_follow_up'])
        self.assertEqual(response.data['enrollment']['student_name_color'], '#212529')

    def test_payment_verification_moves_student_to_selected_same_level_class(self):
        student = self.make_student('settled_payment_student', '09120000031', '1000000031')
        pending = self.make_enrollment(student, self.current_term, 31, payment_verified=False)
        target = ClassSlot.objects.create(
            number=32, term=self.current_term, day_type='odd', time_slot='11:30-13:00',
            gender='girls', assigned_level='A1', capacity=20,
        )
        request = self.factory.post(
            f'/api/class-management/slots/{pending.class_slot_id}/enroll/{student.pk}/verify-payment/',
            {'target_class_slot_id': target.pk}, format='json',
        )
        force_authenticate(request, user=self.admin)

        response = VerifyEnrollmentPaymentView.as_view()(request, pk=pending.class_slot_id, student_id=student.pk)

        self.assertEqual(response.status_code, 200, response.data)
        pending.refresh_from_db()
        self.assertEqual(pending.class_slot_id, target.pk)
        self.assertTrue(pending.payment_verified)
        target_roster = roster_attendance_payload(target)
        self.assertEqual([item['student_id'] for item in target_roster['roster']], [student.pk])
        self.assertEqual(target_roster['roster'][0]['student_name_color'], '#212529')

    def test_manual_confirmation_turns_off_follow_up_without_removing_roster_entry(self):
        student = self.make_student('confirmed_carry_student', '09120000011', '1000000010')
        self.make_enrollment(student, self.previous_term, 10)
        carried = self.make_enrollment(
            student, self.current_term, 10, is_carryover=True, carried_from_term=self.previous_term,
        )
        request = self.factory.post('/api/class-management/confirm-carryover/', {}, format='json')
        force_authenticate(request, user=self.admin)

        response = ConfirmCarryoverEnrollmentView.as_view()(request, pk=carried.class_slot_id, student_id=student.pk)

        self.assertEqual(response.status_code, 200)
        carried.refresh_from_db()
        self.assertTrue(carried.carryover_confirmed)
        self.assertTrue(ClassSlotEnrollment.objects.filter(pk=carried.pk).exists())
        row = next(item for item in self.get_retention_rows()['results'] if item['student_id'] == student.pk)
        self.assertEqual(row['current_state'], 'registered')
        self.assertFalse(row['needs_follow_up'])

    def test_old_current_term_row_can_be_marked_as_carryover_for_selected_previous_term(self):
        student = self.make_student('old_carry_student', '09120000013', '1000000012')
        self.make_enrollment(student, self.previous_term, 3)
        current = self.make_enrollment(student, self.current_term, 3)
        request = self.factory.post(
            '/api/class-management/mark-carryover/',
            {'source_term_id': self.previous_term.pk}, format='json',
        )
        force_authenticate(request, user=self.admin)

        response = MarkCarryoverEnrollmentView.as_view()(request, pk=current.class_slot_id, student_id=student.pk)

        self.assertEqual(response.status_code, 200)
        current.refresh_from_db()
        self.assertTrue(current.is_carryover)
        self.assertFalse(current.carryover_confirmed)
        self.assertEqual(current.carried_from_term_id, self.previous_term.pk)
        row = next(item for item in self.get_retention_rows()['results'] if item['student_id'] == student.pk)
        self.assertEqual(row['current_state'], 'carried_forward')
        self.assertTrue(row['needs_follow_up'])

    def test_post_persists_dropout_result_and_reason(self):
        student = self.make_student('dropout_student', '09120000005', '1000000004')
        self.make_enrollment(student, self.previous_term, 5)

        response = self.call_view('POST', {
            'student_id': student.pk,
            'previous_term_id': self.previous_term.pk,
            'current_term_id': self.current_term.pk,
            'follow_up_status': TermRetentionFollowUp.Status.DROPOUT_CONFIRMED,
            'reason': TermRetentionFollowUp.Reason.FINANCIAL,
            'notes': 'پس از تماس، انصراف قطعی را تأیید کرد.',
            'next_follow_up_date': '',
        })

        self.assertEqual(response.status_code, 200)
        record = TermRetentionFollowUp.objects.get(student=student)
        self.assertEqual(record.status, TermRetentionFollowUp.Status.DROPOUT_CONFIRMED)
        self.assertEqual(record.reason, TermRetentionFollowUp.Reason.FINANCIAL)
        self.assertIn('انصراف قطعی', record.notes)
        self.assertIsNotNone(record.last_contacted_at)

    def test_post_rejects_dropout_for_student_enrolled_in_current_term(self):
        student = self.make_student('active_student', '09120000006', '1000000005')
        self.make_enrollment(student, self.previous_term, 6)
        self.make_enrollment(student, self.current_term, 6)

        response = self.call_view('POST', {
            'student_id': student.pk,
            'previous_term_id': self.previous_term.pk,
            'current_term_id': self.current_term.pk,
            'follow_up_status': TermRetentionFollowUp.Status.DROPOUT_CONFIRMED,
        })

        self.assertEqual(response.status_code, 400)
        self.assertFalse(TermRetentionFollowUp.objects.filter(student=student).exists())
