from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from class_management.models import Term
from leads.models import Debtor, EmployeeFollowupDeadlineRule, NewLead, UnregisteredStudent
from leads.views import (
    DebtorListView, EmployeeFollowupDeadlineView, NewLeadListView,
    UnregisteredStudentListView,
)


class EmployeeFollowupDeadlineAndArchiveTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username='employee_followup_admin', password='test-password', role='admin',
            first_name='مدیر', last_name='آزمایش', phone='09120009001',
        )
        self.term1 = Term.objects.create(
            year=1405, term_number=1, start_date=date(2026, 3, 21), end_date=date(2026, 9, 22),
        )
        self.term2 = Term.objects.create(
            year=1405, term_number=2, start_date=date(2026, 10, 1), end_date=date(2027, 3, 20),
        )
        self.factory = APIRequestFactory()

    def call(self, view, method='GET', path='/', query=None, data=None):
        if method == 'GET':
            request = self.factory.get(path, query or {})
        else:
            request = getattr(self.factory, method.lower())(path, data or {}, format='json')
        force_authenticate(request, user=self.admin)
        return view.as_view()(request)

    def test_deadline_can_be_disabled_set_by_date_or_term_week(self):
        initial = self.call(EmployeeFollowupDeadlineView, path='/api/leads/employee-followup-deadline/', query={'term_id': self.term2.id, 'followup_type': 'debtors'})
        self.assertEqual(initial.status_code, 200)
        self.assertFalse(initial.data['enabled'])

        dated = self.call(EmployeeFollowupDeadlineView, method='POST', path='/api/leads/employee-followup-deadline/', data={
            'term_id': self.term2.id, 'followup_type': 'debtors', 'enabled': True, 'mode': 'date',
            'deadline_date': '2026-10-30', 'deadline_time': '17:15',
        })
        self.assertEqual(dated.status_code, 200)
        self.assertEqual(dated.data['deadline_date'], '2026-10-30')
        self.assertTrue(dated.data['due_at'].startswith('2026-10-30T17:15:00'))

        weekly = self.call(EmployeeFollowupDeadlineView, method='POST', path='/api/leads/employee-followup-deadline/', data={
            'term_id': self.term2.id, 'followup_type': 'debtors', 'enabled': True, 'mode': 'term_week', 'deadline_week': 2,
        })
        self.assertEqual(weekly.status_code, 200)
        self.assertEqual(weekly.data['deadline_week'], 2)
        self.assertTrue(weekly.data['due_at'].startswith('2026-10-14T23:59:00'))

        disabled = self.call(EmployeeFollowupDeadlineView, method='POST', path='/api/leads/employee-followup-deadline/', data={
            'term_id': self.term2.id, 'followup_type': 'debtors', 'enabled': False, 'mode': 'term_week', 'deadline_week': 2,
        })
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.data['enabled'])
        self.assertFalse(EmployeeFollowupDeadlineRule.objects.get(term=self.term2, followup_type='debtors').enabled)

    def test_each_followup_type_has_its_own_deadline(self):
        url = '/api/leads/employee-followup-deadline/'
        self.call(EmployeeFollowupDeadlineView, method='POST', path=url, data={
            'term_id': self.term2.id, 'followup_type': 'debtors', 'enabled': True, 'mode': 'date',
            'deadline_date': '2026-10-30', 'deadline_time': '17:15',
        })
        self.call(EmployeeFollowupDeadlineView, method='POST', path=url, data={
            'term_id': self.term2.id, 'followup_type': 'class-survey', 'enabled': True, 'mode': 'term_week', 'deadline_week': 3,
        })
        graduate_deadline = self.call(EmployeeFollowupDeadlineView, method='POST', path=url, data={
            'term_id': self.term2.id, 'followup_type': 'graduate-information', 'enabled': True, 'mode': 'date',
            'deadline_date': '2020-01-01', 'deadline_time': '00:01',
        })
        self.assertEqual(graduate_deadline.status_code, 200)
        self.assertTrue(graduate_deadline.data['is_overdue'])
        missing = self.call(EmployeeFollowupDeadlineView, method='POST', path=url, data={'term_id': self.term2.id, 'enabled': True})
        self.assertEqual(missing.status_code, 400)
        overview = self.call(EmployeeFollowupDeadlineView, path=url, query={'term_id': self.term2.id})
        items = overview.data['items']
        self.assertEqual(set(items), {'unregistered', 'debtors', 'waiting-list', 'consecutive-dropouts', 'class-survey', 'graduate-information'})
        self.assertTrue(items['debtors']['due_at'].startswith('2026-10-30T17:15:00'))
        self.assertTrue(items['class-survey']['due_at'].startswith('2026-10-21T23:59:00'))
        self.assertFalse(items['unregistered']['enabled'])
        self.assertFalse(items['waiting-list']['enabled'])
        self.assertTrue(items['graduate-information']['is_overdue'])

    def test_graduate_information_deadline_supports_multiple_assignees(self):
        User = get_user_model()
        staff1 = User.objects.create_user(username='graduate_staff_1', password='test-password', role='employee', first_name='کارمند', last_name='یک')
        staff2 = User.objects.create_user(username='graduate_staff_2', password='test-password', role='office', first_name='کارمند', last_name='دو')
        response = self.call(EmployeeFollowupDeadlineView, method='POST', path='/api/leads/employee-followup-deadline/', data={
            'term_id': self.term2.id, 'followup_type': 'graduate-information', 'enabled': False,
            'mode': 'date', 'assigned_employee_ids': [staff1.id, staff2.id],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data['assigned_employee_ids']), {staff1.id, staff2.id})
        rule = EmployeeFollowupDeadlineRule.objects.get(term=self.term2, followup_type='graduate-information')
        self.assertEqual(set(rule.assigned_employees.values_list('id', flat=True)), {staff1.id, staff2.id})

    def test_archives_are_exact_by_term_and_resolved_rows_are_retained(self):
        old_lead = NewLead.objects.create(first_name='آرشیو', last_name='ترم یک', phone='09120009011', term=self.term1, status='registered')
        current_lead = NewLead.objects.create(first_name='جاری', last_name='ترم دو', phone='09120009012', term=self.term2)
        old_student = UnregisteredStudent.objects.create(first_name='ثبت', last_name='قدیمی', class_level='101', term=self.term1, status='registered')
        current_student = UnregisteredStudent.objects.create(first_name='باز', last_name='جاری', class_level='101', term=self.term2)
        old_debtor = Debtor.objects.create(first_name='تسویه', last_name='قدیمی', term=self.term1, status='settled')
        current_debtor = Debtor.objects.create(first_name='بدهکار', last_name='جاری', term=self.term2, status='pending')

        leads = self.call(NewLeadListView, path='/api/leads/new-leads/', query={'term_id': self.term1.id, 'archive': '1'})
        students = self.call(UnregisteredStudentListView, path='/api/leads/unregistered-students/', query={'term_id': self.term1.id, 'archive': '1'})
        debtors = self.call(DebtorListView, path='/api/leads/debtors/', query={'term_id': self.term1.id, 'archive': '1'})
        self.assertEqual(leads.status_code, 200)
        self.assertEqual({row['id'] for row in leads.data}, {old_lead.id})
        self.assertEqual({row['id'] for row in students.data}, {old_student.id})
        self.assertEqual({row['id'] for row in debtors.data}, {old_debtor.id})

        # مشاهدهٔ ترم جاری بدون حالت آرشیو همچنان موارد بازِ ترم‌های پیشین را برای carry-forward حفظ می‌کند.
        active_students = self.call(UnregisteredStudentListView, path='/api/leads/unregistered-students/', query={'term_id': self.term2.id})
        active_debtors = self.call(DebtorListView, path='/api/leads/debtors/', query={'term_id': self.term2.id})
        self.assertEqual({row['id'] for row in active_students.data}, {current_student.id})
        self.assertEqual({row['id'] for row in active_debtors.data}, {current_debtor.id})
