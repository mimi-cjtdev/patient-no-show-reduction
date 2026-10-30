"""
Waitlist backfill: when a slot is cancelled, offer it to the patient who has waited
longest for that visit type at that clinic. The offer holds the slot for
WAITLIST_OFFER_HOURS; if it isn't claimed, it passes to the next patient.
"""
from datetime import timedelta

import booking
import mailer
from common import fmt, new_id, new_token, now, parse
from config import VISIT_TYPES, WAITLIST_OFFER_HOURS


def join(sheets, patient, clinic_code, visit_type):
    for w in sheets.read("waitlist"):
        if (w["patient_id"], w["clinic_code"], w["visit_type"]) == (patient["patient_id"], clinic_code, visit_type) \
                and w["status"] in ("waiting", "offered"):
            return w
    entry = {"waitlist_id": new_id("W"), "added_at": fmt(now()), "patient_id": patient["patient_id"],
             "clinic_code": clinic_code, "visit_type": visit_type, "status": "waiting",
             "offered_slot_id": "", "offered_at": "", "offer_token": "", "appointment_id": ""}
    sheets.append("waitlist", [entry])
    return entry


def offer_slot(sheets, slot_id, skip_patients=()):
    """Offers a freed slot to the next waiting patient. Returns the waitlist entry, or None."""
    slot = next((s for s in sheets.read("slots") if s["slot_id"] == slot_id), None)
    if not slot or parse(slot["start_at"]) < now() + timedelta(hours=WAITLIST_OFFER_HOURS + 1):
        return None             # too soon for anyone to claim it
    if slot_id in booking.taken_slot_ids(sheets):
        return None
    provider = booking.providers(sheets)[slot["provider_id"]]
    visit_type = next(v for v, info in VISIT_TYPES.items() if info["role"] == provider["role"])
    waiting = sorted((w for w in sheets.read("waitlist")
                      if w["status"] == "waiting" and w["clinic_code"] == slot["clinic_code"]
                      and w["visit_type"] == visit_type and w["patient_id"] not in skip_patients),
                     key=lambda w: w["added_at"])
    if not waiting:
        return None
    entry = waiting[0]
    entry.update(status="offered", offered_slot_id=slot_id, offered_at=fmt(now()), offer_token=new_token())
    sheets.update("waitlist", entry["_row"], {k: entry[k] for k in
                                              ("status", "offered_slot_id", "offered_at", "offer_token")})
    patient = next(p for p in sheets.read("patients") if p["patient_id"] == entry["patient_id"])
    subject, text, html = mailer.waitlist_email(entry, slot, patient, provider["provider_name"])
    recipient, result = mailer.send(patient["email"], subject, text, html)
    sheets.append("reminder_log", [mailer.log_row(entry["waitlist_id"], "waitlist_offer", recipient, result)])
    return entry


def by_token(sheets, token):
    return next((w for w in sheets.read("waitlist") if token and w["offer_token"] == token), None)


def offer_is_live(entry):
    return entry["status"] == "offered" and parse(entry["offered_at"]) > now() - timedelta(hours=WAITLIST_OFFER_HOURS)


def claim(sheets, entry):
    if not offer_is_live(entry):
        raise booking.BookingError("Sorry, this offer has expired and the time was passed to the next person.")
    patient = next(p for p in sheets.read("patients") if p["patient_id"] == entry["patient_id"])
    appt = booking.book(sheets, entry["offered_slot_id"], patient, entry["visit_type"], via="waitlist")
    sheets.update("waitlist", entry["_row"], {"status": "booked", "appointment_id": appt["appointment_id"]})
    return appt


def expire_offers(sheets):
    """Unclaimed offers past their hold time pass to the next patient. Returns how many expired."""
    expired = 0
    for w in sheets.read("waitlist"):
        if w["status"] == "offered" and not offer_is_live(w):
            sheets.update("waitlist", w["_row"], {"status": "expired"})
            offer_slot(sheets, w["offered_slot_id"], skip_patients={w["patient_id"]})
            expired += 1
    return expired
