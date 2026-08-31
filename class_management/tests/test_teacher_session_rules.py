from datetime import date
from types import SimpleNamespace
from unittest import TestCase

from class_management.models import (
    ClassSlot,
    THURSDAY_MORNING_EVENT_SLOTS,
    THURSDAY_EVENING_EVENT_SLOTS,
    FRIDAY_EVENT_SLOTS,
)
from class_management.views import _teacher_event_time_options, _teacher_multiplier, _term_length_days


class TeacherSessionRulesTests(TestCase):
    def test_thursday_morning_slots(self):
        slot = ClassSlot(day_type=ClassSlot.DayType.THURSDAY_MORNING, time_slot='08:00-13:00')
        self.assertEqual(_teacher_event_time_options(slot), THURSDAY_MORNING_EVENT_SLOTS)

    def test_thursday_evening_slots(self):
        slot = ClassSlot(day_type=ClassSlot.DayType.THURSDAY_EVENING, time_slot='13:00-17:30')
        self.assertEqual(_teacher_event_time_options(slot), THURSDAY_EVENING_EVENT_SLOTS)

    def test_friday_slot(self):
        slot = ClassSlot(day_type=ClassSlot.DayType.FRIDAY, time_slot='08:00-13:00')
        self.assertEqual(_teacher_event_time_options(slot), FRIDAY_EVENT_SLOTS)

    def test_ordinary_multiplier_is_used(self):
        setting = SimpleNamespace(ordinary_multiplier=1.25, thursday_multiplier=1.5, friday_multiplier=2)
        self.assertEqual(_teacher_multiplier(setting, ClassSlot.DayType.EVEN), 1.25)

    def test_term_length_defaults_to_one_month_and_one_week(self):
        term = SimpleNamespace(start_date=None, end_date=None)
        self.assertEqual(_term_length_days(term), 37)

    def test_term_length_uses_actual_dates(self):
        term = SimpleNamespace(start_date=date(2026, 1, 1), end_date=date(2026, 2, 6))
        self.assertEqual(_term_length_days(term), 37)
