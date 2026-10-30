"""
End-to-end tests of the booking flow on local CSV sheets in a temp folder:
book -> double-book refused -> cancel -> waitlist offer -> claim -> reminders sent once.
Run: python3 -m unittest discover tests
"""
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ.update(BRIGHTSIDE_SHEETS_BACKEND="local", BRIGHTSIDE_MAIL_MODE="outbox", BRIGHTSIDE_MAIL_REDIRECT_TO="",
                  BRIGHTSIDE_DB_PATH=str(TMP / "none.db"), BRIGHTSIDE_OUTBOX=str(TMP / "outbox"),
                  BRIGHTSIDE_NOW="2026-10-21 08:00")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import booking  # noqa: E402
import reminders  # noqa: E402
import waitlist  # noqa: E402
from sheets import LocalSheets  # noqa: E402


def make_sheets():
    sheets = LocalSheets(Path(tempfile.mkdtemp(dir=TMP)))
    for tab in ("providers", "slots", "patients", "appointments", "waitlist", "reminder_log"):
        sheets.reset(tab)
    sheets.append("providers", [{"provider_id": "PR-RIV-01", "provider_name": "Dr. Test", "clinic_code": "RIV",
                                 "role": "gp"}])
    sheets.append("slots", [
        {"slot_id": "S1", "provider_id": "PR-RIV-01", "clinic_code": "RIV", "start_at": "2026-10-23 10:00",
         "minutes": 20},
        {"slot_id": "S2", "provider_id": "PR-RIV-01", "clinic_code": "RIV", "start_at": "2026-11-16 08:00",
         "minutes": 20},
        {"slot_id": "OLD", "provider_id": "PR-RIV-01", "clinic_code": "RIV", "start_at": "2026-10-20 10:00",
         "minutes": 20},
    ])
    return sheets


class TestBookingFlow(unittest.TestCase):
    def setUp(self):
        self.sheets = make_sheets()
        self.ana = booking.find_or_create_patient(self.sheets, "ana  silva", "Ana@Example.com", "(212) 555-0142")

    def test_patient_is_cleaned_and_matched_by_email(self):
        self.assertEqual(self.ana["full_name"], "Ana Silva")
        self.assertEqual(self.ana["phone"], "212-555-0142")
        again = booking.find_or_create_patient(self.sheets, "Ana Silva", "ana@example.com", "2125550142")
        self.assertEqual(again["patient_id"], self.ana["patient_id"])
        self.assertEqual(len(self.sheets.read("patients")), 1)

    def test_rejects_bad_details(self):
        with self.assertRaises(booking.BookingError):
            booking.find_or_create_patient(self.sheets, "Ana", "ana@example.com", "2125550142")
        with self.assertRaises(booking.BookingError):
            booking.find_or_create_patient(self.sheets, "Ana Silva", "ana@example", "2125550142")
        with self.assertRaises(booking.BookingError):
            booking.find_or_create_patient(self.sheets, "Ana Silva", "ana@example.com", "555-0142")

    def test_book_scores_risk_and_hides_the_slot(self):
        appt = booking.book(self.sheets, "S2", self.ana, "GP consult")
        self.assertEqual(appt["status"], "Booked")
        self.assertEqual(appt["new_patient"], "Y")
        self.assertEqual((appt["risk_score"], appt["risk_band"]), (50, "high"))   # new, 26 days, 8am, Monday
        open_ids = [s["slot_id"] for s in booking.open_slots(self.sheets, "RIV", "GP consult")]
        self.assertEqual(open_ids, ["S1"])                                        # S2 taken, OLD in the past

    def test_double_booking_and_past_slots_refused(self):
        booking.book(self.sheets, "S1", self.ana, "GP consult")
        ben = booking.find_or_create_patient(self.sheets, "Ben Ito", "ben@example.com", "2125550143")
        with self.assertRaisesRegex(booking.BookingError, "someone just booked"):
            booking.book(self.sheets, "S1", ben, "GP consult")
        with self.assertRaisesRegex(booking.BookingError, "already passed"):
            booking.book(self.sheets, "OLD", ben, "GP consult")

    def test_two_bookings_at_once_only_one_gets_the_slot(self):
        ben = booking.find_or_create_patient(self.sheets, "Ben Ito", "ben@example.com", "2125550143")
        results = []

        def try_book(patient):
            try:
                results.append(booking.book(self.sheets, "S1", patient, "GP consult")["slot_id"])
            except booking.BookingError:
                results.append("refused")
        threads = [threading.Thread(target=try_book, args=(p,)) for p in (self.ana, ben, self.ana, ben)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), ["S1", "refused", "refused", "refused"])

    def test_cancel_offers_slot_to_waitlist_and_claim_books_it(self):
        appt = booking.book(self.sheets, "S1", self.ana, "GP consult")
        ben = booking.find_or_create_patient(self.sheets, "Ben Ito", "ben@example.com", "2125550143")
        waitlist.join(self.sheets, ben, "RIV", "GP consult")

        booking.cancel(self.sheets, booking.by_token(self.sheets, appt["token"]))
        entry = self.sheets.read("waitlist")[0]
        self.assertEqual((entry["status"], entry["offered_slot_id"]), ("offered", "S1"))
        self.assertIn("waitlist_offer", [r["kind"] for r in self.sheets.read("reminder_log")])
        # held for Ben: nobody else can book it while the offer is live
        self.assertNotIn("S1", [s["slot_id"] for s in booking.open_slots(self.sheets, "RIV", "GP consult")])

        new_appt = waitlist.claim(self.sheets, waitlist.by_token(self.sheets, entry["offer_token"]))
        self.assertEqual((new_appt["slot_id"], new_appt["booked_via"]), ("S1", "waitlist"))
        self.assertEqual(self.sheets.read("waitlist")[0]["status"], "booked")

    def test_confirm(self):
        appt = booking.book(self.sheets, "S1", self.ana, "GP consult")
        booking.confirm(self.sheets, booking.by_token(self.sheets, appt["token"]))
        row = booking.by_token(self.sheets, appt["token"])
        self.assertEqual(row["status"], "Confirmed")
        self.assertEqual(row["confirmed_at"], "2026-10-21 08:00")

    def test_no_reminder_right_after_a_late_booking(self):
        booking.book(self.sheets, "S1", self.ana, "GP consult")              # booked 50 hours ahead
        reminders.run(self.sheets)
        self.assertEqual(self.sheets.read("reminder_log"), [])               # the booking email covers the 72h one

    def test_reminders_sent_once(self):
        appt = booking.book(self.sheets, "S1", self.ana, "GP consult")       # 50 hours away: 72h reminder due
        row = booking.by_token(self.sheets, appt["token"])
        self.sheets.update("appointments", row["_row"], {"booked_at": "2026-10-14 09:00"})   # booked a week ago
        reminders.run(self.sheets)
        reminders.run(self.sheets)
        kinds = [r["kind"] for r in self.sheets.read("reminder_log")]
        self.assertEqual(kinds, ["reminder_72h"])
        self.assertTrue(list((TMP / "outbox").glob("*.eml")))


if __name__ == "__main__":
    unittest.main()
