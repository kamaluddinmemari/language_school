from unittest import TestCase

from teacher_priority.scoring import (
    ScoringConfig, TermFacts, compute_term_score, one_day_points, price_factor, usage_penalty,
)

CFG = ScoringConfig()


def score(day_types, students=0, absences=0):
    return compute_term_score(TermFacts(day_types, students, absences), CFG)['score']


class TermScoreTests(TestCase):
    def test_parity_order_both_over_even_over_odd_over_none(self):
        self.assertGreater(score(['even', 'odd']), score(['even']))
        self.assertGreater(score(['even']), score(['odd']))
        self.assertGreater(score(['odd']), score([]))

    def test_friday_over_thursday_and_evening_over_morning(self):
        self.assertGreater(score(['friday_morning']), score(['thursday_morning']))
        self.assertGreater(score(['friday_evening']), score(['friday_morning']))
        self.assertGreater(score(['thursday_evening']), score(['thursday_morning']))

    def test_both_one_day_slots_get_bonus(self):
        self.assertGreater(score(['friday_morning', 'thursday_morning']), score(['friday_morning']))
        self.assertEqual(one_day_points(['friday_evening', 'thursday_evening'], CFG)[0], CFG.w_one_day)

    def test_students_and_class_count_are_capped(self):
        self.assertEqual(score([], 60), 25)
        self.assertEqual(score([], 600), 25)
        self.assertGreater(score(['even'] * 6), score(['even'] * 3))

    def test_perfect_teacher_is_100(self):
        full = ['even', 'odd', 'friday_evening', 'thursday_evening', 'even', 'odd']
        self.assertEqual(score(full, 60), 100)

    def test_absences_subtract_with_cap_and_floor(self):
        full = ['even', 'odd', 'friday_evening', 'thursday_evening', 'even', 'odd']
        self.assertEqual(score(full, 60, 2), 92)
        self.assertEqual(score(full, 60, 50), 80)
        self.assertEqual(score([], 0, 9), 0)


class PenaltyAndPriceTests(TestCase):
    def test_makeup_deducts_less_than_private(self):
        p = usage_penalty(4, 2, 3, 1.5)
        self.assertEqual(p['points'], 15)
        self.assertLess(usage_penalty(0, 1, 3, 1.5)['points'], usage_penalty(1, 0, 3, 1.5)['points'])

    def test_price_factor_respects_tick(self):
        self.assertEqual(price_factor(80, 0.2, False), 1.0)
        self.assertEqual(price_factor(80, 0.2, True), 1.16)
