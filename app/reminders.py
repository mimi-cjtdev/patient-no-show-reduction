#!/usr/bin/env python3
"""
Hourly reminder job.

  1. Passes unclaimed waitlist offers on to the next patient.
  2. Emails a reminder 72 hours and 24 hours before every Booked / Confirmed appointment
     (each one once: reminder_log is checked first, so re-running sends nothing twice).
     A reminder whose time had already passed when the patient booked is skipped: the booking
     confirmation they just got covers it (booked this morning for 3pm = one email, not two).

Usage:  .venv/bin/python app/reminders.py
Cron:   5 * * * * cd /path/to/patient-no-show-reduction && .venv/bin/python app/reminders.py >> logs/reminders.log 2>&1
"""
from datetime import timedelta

import booking
import mailer
import waitlist
from common import fmt, now, parse, try_parse
from config import REMINDER_WINDOWS
from sheets import backend


def run(sheets):
    t = now()
    expired = waitlist.expire_offers(sheets)

    sent_before = {(r["appointment_id"], r["kind"]) for r in sheets.read("reminder_log")
                   if not r["result"].startswith("failed")}
    patients = {p["patient_id"]: p for p in sheets.read("patients")}
    providers = booking.providers(sheets)
    # rows staff have mangled (bad time, unknown patient or provider) are skipped here and flagged by the sync
    active = [a for a in sheets.read("appointments") if a["status"] in booking.ACTIVE]
    appointments = [a for a in active if try_parse(a["start_at"]) and a["patient_id"] in patients
                    and a["provider_id"] in providers]
    skipped = len(active) - len(appointments)

    log, counts = [], {kind: 0 for kind in REMINDER_WINDOWS}
    for a in appointments:
        start = parse(a["start_at"])
        hours_away = (start - t).total_seconds() / 3600
        booked_at = try_parse(a["booked_at"]) or start - timedelta(days=365)
        for kind, (upper, lower) in REMINDER_WINDOWS.items():
            booked_too_late = booked_at > start - timedelta(hours=upper)
            if lower < hours_away <= upper and not booked_too_late and (a["appointment_id"], kind) not in sent_before:
                patient = patients[a["patient_id"]]
                subject, text, html = mailer.appointment_email(kind, a, patient,
                                                               providers[a["provider_id"]]["provider_name"])
                recipient, result = mailer.send(patient["email"], subject, text, html)
                log.append(mailer.log_row(a["appointment_id"], kind, recipient, result))
                counts[kind] += 1
    if log:
        sheets.append("reminder_log", log)
    failed = sum(r["result"].startswith("failed") for r in log)

    print(f"{fmt(t)}  72h reminders: {counts['reminder_72h']}  24h reminders: {counts['reminder_24h']}  "
          f"failed: {failed}  waitlist offers expired: {expired}  unreadable rows skipped: {skipped}")
    return failed


if __name__ == "__main__":
    raise SystemExit(1 if run(backend()) else 0)
