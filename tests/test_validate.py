"""Unit tests for the sheet-row cleaning rules and the risk score.  Run: python3 -m unittest discover tests"""
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import risk  # noqa: E402
from validate import Cleaner, RowError  # noqa: E402

NOW = datetime(2026, 10, 21, 8, 0)


def rejects(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except RowError as e:
        return e.error_type
    raise AssertionError("expected a RowError")


class TestStatus(unittest.TestCase):
    def test_maps_front_desk_shorthand_and_records_fix(self):
        c = Cleaner(NOW)
        self.assertEqual(c.status("DNA", "2026-10-20 09:00"), "no_show")
        self.assertEqual(c.status("No Show", "2026-10-20 09:00"), "no_show")
        self.assertEqual(c.status("seen", "2026-10-20 09:00"), "arrived")
        self.assertEqual(c.status("cxl", "2026-10-25 09:00"), "cancelled")
        self.assertEqual(len(c.fixes), 4)
        self.assertIn("'DNA' → No-show", c.fixes[0])

    def test_dropdown_values_need_no_fix(self):
        c = Cleaner(NOW)
        self.assertEqual(c.status("No-show", "2026-10-20 09:00"), "no_show")
        self.assertEqual(c.status("Confirmed", "2026-10-25 09:00"), "confirmed")
        self.assertEqual(c.fixes, [])

    def test_rejects_unknown_status(self):
        self.assertEqual(rejects(Cleaner(NOW).status, "Left early", "2026-10-20 09:00"), "bad_status")
        self.assertEqual(rejects(Cleaner(NOW).status, "", "2026-10-20 09:00"), "missing_value")

    def test_rejects_outcome_before_the_appointment(self):
        self.assertEqual(rejects(Cleaner(NOW).status, "No-show", "2026-10-27 08:00"), "outcome_too_early")
        self.assertEqual(rejects(Cleaner(NOW).status, "Arrived", "2026-10-21 09:00"), "outcome_too_early")

    def test_rejects_past_appointment_with_no_outcome_after_a_day(self):
        self.assertEqual(rejects(Cleaner(NOW).status, "Booked", "2026-10-19 15:00"), "missing_outcome")
        # yesterday afternoon is still within the grace period
        self.assertEqual(Cleaner(NOW).status("Booked", "2026-10-20 15:00"), "booked")


class TestContactDetails(unittest.TestCase):
    def test_normalises_phone_formats(self):
        c = Cleaner(NOW)
        self.assertEqual(c.phone("(212) 555-0142"), "212-555-0142")
        self.assertEqual(c.phone("+1 212 555 0142"), "212-555-0142")
        self.assertEqual(c.phone("212-555-0142"), "212-555-0142")
        self.assertEqual(len(c.fixes), 2)

    def test_rejects_phone_without_area_code(self):
        self.assertEqual(rejects(Cleaner(NOW).phone, "555-0142"), "bad_phone")

    def test_lowercases_email_and_rejects_invalid(self):
        c = Cleaner(NOW)
        self.assertEqual(c.email("Ana.Silva@Example.com"), "ana.silva@example.com")
        self.assertEqual(rejects(c.email, "ana.silva@example"), "bad_email")
        self.assertEqual(rejects(c.email, ""), "missing_value")


class TestOtherFields(unittest.TestCase):
    def test_timestamp(self):
        c = Cleaner(NOW)
        self.assertEqual(c.timestamp("2026-10-23 09:00", "start_at"), "2026-10-23 09:00")
        self.assertEqual(c.timestamp("2026-10-23 09:00:00", "start_at"), "2026-10-23 09:00")
        self.assertEqual(rejects(c.timestamp, "23/10/2026 9am", "start_at"), "bad_timestamp")
        self.assertIsNone(c.timestamp("", "confirmed_at", required=False))

    def test_known_value_suggests_closest_match(self):
        with self.assertRaises(RowError) as e:
            Cleaner(NOW).known("PR-RIV-1", {"PR-RIV-01", "PR-NTH-01"}, "provider_id", "unknown_provider")
        self.assertIn("did you mean PR-RIV-01", e.exception.message)


class TestRiskScore(unittest.TestCase):
    def test_low_risk_returning_patient(self):
        points, band, reasons = risk.score(datetime(2026, 10, 22, 10, 0), NOW, False, 0)
        self.assertEqual((points, band, reasons), (0, "low", []))

    def test_new_patient_far_ahead_early_monday_is_high(self):
        points, band, reasons = risk.score(datetime(2026, 11, 16, 8, 0), NOW, True, 0)
        self.assertEqual(points, 20 + 15 + 10 + 5)
        self.assertEqual(band, "high")
        self.assertIn("booked 26 days ahead", reasons)

    def test_past_no_shows(self):
        self.assertEqual(risk.score(datetime(2026, 10, 22, 10, 0), NOW, False, 1)[:2], (30, "medium"))
        self.assertEqual(risk.score(datetime(2026, 10, 22, 10, 0), NOW, False, 2)[:2], (45, "high"))


if __name__ == "__main__":
    unittest.main()
