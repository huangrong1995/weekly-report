"""ISO week arithmetic."""

import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from wreport import weeks  # noqa: E402


class TestWeekMath(unittest.TestCase):
    def test_week_of_known_dates(self):
        # 2026-09-21 is a Monday and starts ISO week 39.
        self.assertEqual("2026-W39", weeks.week_of(dt.date(2026, 9, 21)))
        self.assertEqual("2026-W39", weeks.week_of(dt.date(2026, 9, 27)))
        self.assertEqual("2026-W40", weeks.week_of(dt.date(2026, 9, 28)))

    def test_bounds_are_monday_to_sunday(self):
        start, end = weeks.week_bounds("2026-W39")
        self.assertEqual(dt.date(2026, 9, 21), start)
        self.assertEqual(dt.date(2026, 9, 27), end)
        self.assertEqual(0, start.weekday())
        self.assertEqual(6, end.weekday())

    def test_week_dates_has_seven_days(self):
        days = weeks.week_dates("2026-W39")
        self.assertEqual(7, len(days))
        self.assertEqual(dt.date(2026, 9, 21), days[0])
        self.assertEqual(dt.date(2026, 9, 27), days[-1])

    def test_previous_and_next_cross_year(self):
        self.assertEqual("2026-W38", weeks.previous_week("2026-W39"))
        self.assertEqual("2026-W40", weeks.next_week("2026-W39"))
        # 2026-W01 -> previous must roll into 2025
        self.assertTrue(weeks.previous_week("2026-W01").startswith("2025-"))

    def test_label(self):
        self.assertEqual("2026 W39（09/21 – 09/27）", weeks.week_label("2026-W39"))

    def test_parse_date_accepts_keywords(self):
        today = dt.date.today()
        self.assertEqual(today, weeks.parse_date("today"))
        self.assertEqual(today, weeks.parse_date(""))
        self.assertEqual(today - dt.timedelta(days=1), weeks.parse_date("yesterday"))

    def test_bad_input_raises(self):
        for bad in ("2026-9-1x", "W39", "hello"):
            with self.assertRaises(ValueError):
                weeks.parse_date(bad)
        for bad in ("2026-39", "39", "x"):
            with self.assertRaises(ValueError):
                weeks.parse_week(bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)