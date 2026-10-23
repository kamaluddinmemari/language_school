from datetime import date, timedelta
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from class_management.attendance import attendance_session_dates_for_slot
from class_management.models import (
    ClassSlot, ClassSlotEnrollment, ClassSurveyList, ClassSurveyQuestion,
    ClassSurveyResponse, Term, TermHoliday,
)
from class_management.survey import (
    SurveyAssignView, SurveyDeadlineAlertsView, SurveyDeadlineView, SurveyDeadlinesView,
    SurveyListView, SurveyReportExcelView, SurveyReportView, SurveyResponseView,
)


class SurveyFollowUpTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username='survey_admin', password='test-password', role='admin',
            first_name='مدیر', last_name='آزمایش', phone='09120001001',
        )
        self.staff1 = User.objects.create_user(
            username='survey_office', password='test-password', role='office',
            first_name='کارمند', last_name='اول', phone='09120001002',
        )
        self.staff2 = User.objects.create_user(
            username='survey_employee', password='test-password', role='employee',
            first_name='کارمند', last_name='دوم', phone='09120001003',
        )
        self.term = Term.objects.create(
            year=1405, term_number=1, start_date=date(2026, 3, 21), end_date=date(2026, 9, 22),
        )
        self.survey = ClassSurveyList.objects.create(
            name='آزمایشی', term=self.term, percentage=100,
            rows=[{'key': f'{index}:1', 'row_number': index} for index in range(1, 6)],
            created_by=self.admin,
        )
        self.students = []
        self.slots = []
        self.responses = []
        for index in range(1, 6):
            student = User.objects.create_user(
                username=f'survey_student_{index}', password='test-password', role='student',
                first_name='دانش‌آموز', last_name=f'شماره {index}', phone=f'0912000200{index}',
                national_code=f'200000000{index}',
            )
            slot = ClassSlot.objects.create(
                number=index, term=self.term, day_type='even', time_slot='09:45-11:15',
                assigned_level='101',
            )
            ClassSlotEnrollment.objects.create(class_slot=slot, student=student, payment_method='cash')
            response = ClassSurveyResponse.objects.create(
                survey_list=self.survey, student=student, class_slot=slot,
                answers={'legacy': 'preserve'},
            )
            self.students.append(student)
            self.slots.append(slot)
            self.responses.append(response)
        ClassSurveyQuestion.objects.create(age_group='all', text='پرسش یک', sort_order=1)
        self.factory = APIRequestFactory()

    def call(self, view, method, data=None, user=None, survey_id=None, query=None):
        path = '/api/class-management/surveys/'
        if survey_id:
            path += f'{survey_id}/'
        if method == 'GET':
            request = self.factory.get(path, query or {})
        else:
            request = getattr(self.factory, method.lower())(path, data or {}, format='json')
        force_authenticate(request, user=user or self.admin)
        if survey_id is not None:
            return view.as_view()(request, survey_id=survey_id)
        return view.as_view()(request)

    def test_response_uses_server_time_and_answers_autosave_does_not_change_call_time(self):
        fixed = timezone.now().replace(microsecond=0)
        with patch('class_management.survey.timezone.now', return_value=fixed):
            result = self.call(SurveyResponseView, 'POST', {
                'student_id': self.students[0].id,
                'class_slot_id': self.slots[0].id,
                'record_call': True,
                'call_status': 'answered',
                'respondent_name': 'پاسخگو',
                'answers': {'1': {'answer': 'yes'}},
                'contacted_at': '2000-01-01T00:00:00Z',
            }, survey_id=self.survey.id)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertTrue(result.data['ok'])
        self.assertEqual(result.data['call_status'], 'answered')
        self.assertEqual(result.data['contacted_at'], fixed.isoformat())
        self.assertEqual(result.data['respondent_name'], 'پاسخگو')
        self.assertTrue(result.data['completed'])
        prior = result.data['contacted_at']
        later = fixed + timedelta(minutes=2)
        with patch('class_management.survey.timezone.now', return_value=later):
            autosave = self.call(SurveyResponseView, 'POST', {
                'student_id': self.students[0].id,
                'class_slot_id': self.slots[0].id,
                'answers': {'1': {'answer': 'no'}},
            }, survey_id=self.survey.id)
        self.assertEqual(autosave.data['contacted_at'], prior)

    def test_no_answer_keeps_prior_answers_and_is_incomplete(self):
        record = self.responses[0]
        result = self.call(SurveyResponseView, 'POST', {
            'student_id': record.student_id, 'class_slot_id': record.class_slot_id,
            'record_call': True, 'call_status': 'no_answer', 'answers': {},
        }, survey_id=self.survey.id)
        record.refresh_from_db()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(record.answers, {'legacy': 'preserve'})
        self.assertFalse(record.completed)
        self.assertEqual(record.call_status, 'no_answer')
        self.assertIsNotNone(record.contacted_at)

    def test_assignment_balanced_and_rejects_inactive_or_wrong_role(self):
        result = self.call(SurveyAssignView, 'POST', {
            'mode': 'distribute', 'employee_ids': [self.staff1.id, self.staff2.id],
            'only_unassigned': True,
        }, survey_id=self.survey.id)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data['assigned_count'], 5)
        self.assertEqual(sorted(item['count'] for item in result.data['distribution']), [2, 3])
        wrong_role = self.students[0].id
        bad = self.call(SurveyAssignView, 'POST', {
            'mode': 'all', 'employee_ids': [wrong_role], 'only_unassigned': False,
        }, survey_id=self.survey.id)
        self.assertEqual(bad.status_code, 400)

    def test_deadline_date_automatic_none_validation_and_jalali(self):
        result = self.call(SurveyDeadlineView, 'PATCH', {
            'deadline_enabled': True, 'deadline_mode': 'date',
            'deadline_at': '2026-06-01T12:30:00+03:30',
        }, survey_id=self.survey.id)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data['deadline_mode'], 'date')
        self.assertTrue(result.data['deadline_at_jalali'])
        bad = self.call(SurveyDeadlineView, 'PATCH', {
            'deadline_enabled': True, 'deadline_mode': 'automatic', 'deadline_days': 366,
        }, survey_id=self.survey.id)
        self.assertEqual(bad.status_code, 400)
        automatic = self.call(SurveyDeadlineView, 'PATCH', {
            'deadline_enabled': True, 'deadline_mode': 'automatic', 'deadline_days': 7,
        }, survey_id=self.survey.id)
        self.assertEqual(automatic.status_code, 200)
        self.assertEqual(automatic.data['deadline_days'], 7)
        cleared = self.call(SurveyDeadlineView, 'PATCH', {
            'deadline_enabled': False, 'deadline_mode': 'none',
        }, survey_id=self.survey.id)
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.data['deadline_at'])
        self.responses[0].refresh_from_db()
        self.assertIsNone(self.responses[0].due_at)

    def test_session_options_are_common_to_all_classes_and_session_deadline_has_real_end_time(self):
        holiday = self.term.start_date + timedelta(days=(5 - self.term.start_date.weekday()) % 7)
        TermHoliday.objects.create(term=self.term, date=holiday, description='تست تعطیلی')
        self.assertEqual(len(attendance_session_dates_for_slot(self.slots[0], 15)), 15)
        detail = self.call(SurveyListView, 'GET', query={'id': self.survey.id, 'assigned_to': self.staff1.id})
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data['session_options'][0]['session_number'], 1)
        result = self.call(SurveyDeadlineView, 'PATCH', {
            'deadline_enabled': True, 'deadline_mode': 'session', 'deadline_session_number': 1,
        }, survey_id=self.survey.id)
        self.assertEqual(result.status_code, 200, result.data)
        self.responses[0].refresh_from_db()
        self.assertIsNotNone(self.responses[0].due_at)
        self.assertEqual(timezone.localtime(self.responses[0].due_at).strftime('%H:%M'), '11:15')

    def test_session_rejected_when_any_slot_has_no_requested_date(self):
        short_term = Term.objects.create(
            year=1405, term_number=2, start_date=date(2026, 3, 21), end_date=date(2026, 3, 23),
        )
        self.survey.term = short_term
        self.survey.save(update_fields=['term'])
        ClassSlot.objects.filter(pk__in=[slot.pk for slot in self.slots]).update(term=short_term)
        self.assertEqual(
            self.call(SurveyDeadlineView, 'PATCH', {
                'deadline_enabled': True, 'deadline_mode': 'session', 'deadline_session_number': 15,
            }, survey_id=self.survey.id).status_code,
            400,
        )

    def test_alert_permissions_and_overdue_grouping(self):
        past = timezone.now() - timedelta(days=1)
        configured = self.call(SurveyDeadlineView, 'PATCH', {
            'deadline_enabled': True, 'deadline_mode': 'date', 'deadline_at': past.isoformat(),
        }, survey_id=self.survey.id)
        self.assertEqual(configured.status_code, 200, configured.data)
        self.responses[0].assigned_to = self.staff2
        self.responses[0].save(update_fields=['assigned_to'])
        employee_alerts = self.call(SurveyDeadlineAlertsView, 'GET', user=self.staff2)
        self.assertEqual(employee_alerts.status_code, 200)
        self.assertTrue(employee_alerts.data['alerts'])
        self.assertTrue(employee_alerts.data['alerts'][0]['overdue'])
        forbidden = self.call(SurveyDeadlineAlertsView, 'GET', user=self.students[0])
        self.assertEqual(forbidden.status_code, 403)

    def test_teacher_class_sampling_selects_classes_then_percentage_of_students(self):
        # ابتدا یک کلاس از هر استاد و سپس ۲۰٪ از دانش‌آموزان همان کلاس به لیست می‌آیند.
        for index, slot in enumerate(self.slots):
            slot.teacher_name = 'استاد الف' if index < 3 else 'استاد ب'
            slot.save(update_fields=['teacher_name'])
        for teacher, slot_index, suffix in (
            ('استاد الف', 0, 6), ('استاد الف', 1, 7),
            ('استاد ب', 3, 8), ('استاد ب', 4, 9),
        ):
            student = get_user_model().objects.create_user(
                username=f'survey_student_{suffix}', password='test-password', role='student',
                first_name='همکلاسی', last_name=str(suffix), phone=f'0912000300{suffix}',
                national_code=f'300000000{suffix}',
            )
            ClassSlotEnrollment.objects.create(class_slot=self.slots[slot_index], student=student, payment_method='cash')
        with patch('class_management.survey.random.SystemRandom.sample', side_effect=lambda population, count: list(population)[:count]):
            request = self.factory.post('/api/class-management/surveys/', {
                'term_id': self.term.id,
                'percentage': 20,
                'use_teacher_class_sampling': True,
                'teacher_class_percentage': 34,
            }, format='json')
            force_authenticate(request, user=self.admin)
            result = SurveyListView.as_view()(request)
        self.assertEqual(result.status_code, 201, result.data)
        generated = ClassSurveyList.objects.get(pk=result.data['id'])
        selected = {row['class_slot_id'] for row in generated.rows}
        selected_teachers = {slot.teacher_name for slot in ClassSlot.objects.filter(pk__in=selected)}
        self.assertEqual(selected_teachers, {'استاد الف', 'استاد ب'})
        for slot_id in selected:
            enrolled_count = ClassSlotEnrollment.objects.filter(class_slot_id=slot_id, student__role='student').count()
            expected_students = max(1, round(enrolled_count * 20 / 100))
            self.assertEqual(
                len([row for row in generated.rows if row['class_slot_id'] == slot_id]),
                expected_students,
            )
        self.assertTrue(generated.use_teacher_class_sampling)
        self.assertEqual(generated.teacher_class_percentage, 34)

    def test_deadline_selection_includes_surveys_without_an_existing_deadline(self):
        result = self.call(SurveyDeadlinesView, 'GET', user=self.admin)
        self.assertEqual(result.status_code, 200)
        self.assertIn(self.survey.id, [item['id'] for item in result.data['lists']])
        self.assertFalse(next(item for item in result.data['lists'] if item['id'] == self.survey.id)['deadline_enabled'])

    def test_teacher_report_satisfaction_and_excel_filters(self):
        for index in (0, 1):
            self.slots[index].teacher_name = 'استاد گزارش'
            self.slots[index].save(update_fields=['teacher_name'])
            self.responses[index].completed = True
            self.responses[index].answers = {'1': {'answer': 'yes' if index == 0 else 'no'}}
            self.responses[index].save(update_fields=['completed', 'answers'])
        unfiltered_request = self.factory.get(f'/api/class-management/surveys/{self.survey.id}/report/')
        force_authenticate(unfiltered_request, user=self.admin)
        unfiltered_result = SurveyReportView.as_view()(unfiltered_request, survey_id=self.survey.id)
        self.assertEqual(unfiltered_result.status_code, 200)
        self.assertEqual(unfiltered_result.data['total_completed'], 2)
        request = self.factory.get(f'/api/class-management/surveys/{self.survey.id}/report/', {'level': '101'})
        force_authenticate(request, user=self.admin)
        result = SurveyReportView.as_view()(request, survey_id=self.survey.id)
        self.assertEqual(result.status_code, 200)
        summary = result.data['teacher_summary'][0]
        self.assertEqual(summary['teacher'], 'استاد گزارش')
        self.assertEqual(summary['response_count'], 2)
        self.assertEqual(summary['yes_count'], 1)
        self.assertEqual(summary['no_count'], 1)
        self.assertEqual(summary['satisfaction_percent'], 50)
        self.assertEqual(result.data['overall_summary']['satisfaction_percent'], 50)
        self.assertIn('kids', summary['age_groups'])
        self.assertIn('teen', summary['age_groups'])
        self.assertIn('adult', summary['age_groups'])
        question_summary = result.data['question_summary'][0]
        self.assertEqual(question_summary['yes_count'], 1)
        self.assertEqual(question_summary['no_count'], 1)
        self.assertEqual(question_summary['yes_percent'], 50)
        self.assertEqual(question_summary['no_percent'], 50)
        class_age_summary = result.data['class_age_summary'][0]
        self.assertEqual(class_age_summary['yes_count'], 1)
        self.assertEqual(class_age_summary['no_count'], 1)
        self.assertEqual(class_age_summary['yes_percent'], 50)
        self.assertIn('استاد گزارش', result.data['teacher_options'])
        self.assertIn('101', result.data['levels_by_teacher']['استاد گزارش'])

        excel_request = self.factory.get(
            f'/api/class-management/surveys/{self.survey.id}/report.xlsx/',
            {'teacher': 'استاد گزارش', 'level': '101'},
        )
        force_authenticate(excel_request, user=self.admin)
        excel = SurveyReportExcelView.as_view()(excel_request, survey_id=self.survey.id)
        self.assertEqual(excel.status_code, 200)
        self.assertEqual(excel['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        from openpyxl import load_workbook
        workbook = load_workbook(BytesIO(excel.content), data_only=True)
        summary_sheet = workbook['رضایت استادان']
        self.assertEqual(summary_sheet.auto_filter.ref, 'A1:J3')
        self.assertEqual(summary_sheet['G2'].value, 50)
        self.assertEqual(workbook['نتایج هر سؤال'].auto_filter.ref, 'A1:K2')
        self.assertEqual(workbook['نتایج هر سؤال']['G2'].value, 50)
        self.assertEqual(workbook['رضایت کلاس و رده سنی'].auto_filter.ref, 'A1:K2')
        self.assertEqual(workbook['رضایت کلاس و رده سنی']['K2'].value, 50)
        self.assertEqual(workbook['جزئیات پاسخ‌ها'].auto_filter.ref, 'A1:J3')
