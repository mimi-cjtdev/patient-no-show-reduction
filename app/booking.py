"""
Booking rules shared by the webapp, the waitlist and the reminder job.

The appointments tab is the single source of truth for whether a slot is taken:
a slot is free when no appointment on it is still Booked or Confirmed, and no
waitlist offer is holding it.
"""
import re
import sqlite3
import threading
from datetime import timedelta

import risk
from common import fmt, new_id, new_token, now, parse
from config import DB_PATH, STATUS_LABEL, VISIT_TYPES, WAITLIST_OFFER_HOURS

ACTIVE = {"Booked", "Confirmed"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
MAX_DAYS_AHEAD = 60


# One booking at a time: checking a slot is free and saving the booking must not interleave,
# or a double-click on "Book appointment" saves the same slot twice
_booking_lock = threading.Lock()


class BookingError(Exception):
    pass


def providers(sheets):
    return {p["provider_id"]: p for p in sheets.read("providers")}


def taken_slot_ids(sheets):
    taken = {a["slot_id"] for a in sheets.read("appointments") if a["status"] in ACTIVE}
    hold_since = now() - timedelta(hours=WAITLIST_OFFER_HOURS)
    taken |= {w["offered_slot_id"] for w in sheets.read("waitlist")
              if w["status"] == "offered" and parse(w["offered_at"]) > hold_since}
    return taken


def open_slots(sheets, clinic_code, visit_type, provider_id=None):
    """Free slots for a visit type at a clinic, soonest first (at least 1 hour from now)."""
    role = VISIT_TYPES[visit_type]["role"]
    provs = providers(sheets)
    taken = taken_slot_ids(sheets)
    earliest, latest = now() + timedelta(hours=1), now() + timedelta(days=MAX_DAYS_AHEAD)
    slots = []
    for s in sheets.read("slots"):
        p = provs.get(s["provider_id"])
        if (s["clinic_code"] == clinic_code and p and p["role"] == role and s["slot_id"] not in taken
                and (not provider_id or s["provider_id"] == provider_id)
                and earliest <= parse(s["start_at"]) <= latest):
            slots.append({**s, "provider_name": p["provider_name"]})
    return sorted(slots, key=lambda s: s["start_at"])


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

def clean_phone(value):
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise BookingError("Please enter a 10-digit phone number.")
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def _db():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def find_or_create_patient(sheets, full_name, email, phone):
    """Matches on email: the patients tab first, then patients known only from history."""
    full_name = " ".join((full_name or "").split()).title()
    email = (email or "").strip().lower()
    if len(full_name.split()) < 2:
        raise BookingError("Please enter your first and last name.")
    if not EMAIL_RE.match(email):
        raise BookingError("Please enter a valid email address.")
    phone = clean_phone(phone)
    for p in sheets.read("patients"):
        if p["email"].lower() == email:
            return p
    conn = _db()
    row = conn and conn.execute("SELECT * FROM patients WHERE lower(email) = ?", (email,)).fetchone()
    patient = {"patient_id": row["patient_id"] if row else new_id("P"), "full_name": full_name, "email": email,
               "phone": phone, "created_at": row["created_at"] if row else fmt(now()), "sync_status": ""}
    sheets.append("patients", [patient])
    return patient


def patient_history(sheets, patient_id):
    """(visits attended, no-shows in the last 12 months) across the sheet and the history database."""
    since = fmt(now() - timedelta(days=365))
    sheet_rows = [a for a in sheets.read("appointments") if a["patient_id"] == patient_id]
    attended = sum(a["status"] == "Arrived" for a in sheet_rows)
    no_shows = sum(a["status"] == "No-show" and a["start_at"] >= since for a in sheet_rows)
    conn = _db()
    if conn:
        in_sheet = {a["appointment_id"] for a in sheet_rows}
        for r in conn.execute("SELECT appointment_id, status, start_at FROM appointments WHERE patient_id = ?",
                              (patient_id,)):
            if r["appointment_id"] in in_sheet:
                continue
            attended += r["status"] == "arrived"
            no_shows += r["status"] == "no_show" and r["start_at"] >= since
    return attended, no_shows


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------

def book(sheets, slot_id, patient, visit_type, via="web"):
    with _booking_lock:
        return _book(sheets, slot_id, patient, visit_type, via)


def _book(sheets, slot_id, patient, visit_type, via):
    slot = next((s for s in sheets.read("slots") if s["slot_id"] == slot_id), None)
    if not slot:
        raise BookingError("That time doesn't exist any more. Please pick another.")
    booked_already = any(a["slot_id"] == slot_id and a["status"] in ACTIVE for a in sheets.read("appointments"))
    if booked_already or (via != "waitlist" and slot_id in taken_slot_ids(sheets)):
        raise BookingError("Sorry, someone just booked that time. Please pick another.")
    start, booked = parse(slot["start_at"]), now()
    if start < booked:
        raise BookingError("That time has already passed.")
    attended, no_shows = patient_history(sheets, patient["patient_id"])
    points, band, _ = risk.score(start, booked, attended == 0, no_shows)
    appt = {"appointment_id": new_id("A"), "booked_at": fmt(booked), "booked_via": via,
            "patient_id": patient["patient_id"], "slot_id": slot_id, "clinic_code": slot["clinic_code"],
            "provider_id": slot["provider_id"], "visit_type": visit_type, "start_at": slot["start_at"],
            "new_patient": "Y" if attended == 0 else "N", "risk_score": points, "risk_band": band,
            "status": STATUS_LABEL["booked"], "confirmed_at": "", "cancelled_at": "", "token": new_token(),
            "sync_status": ""}
    sheets.append("appointments", [appt])
    return appt


def by_token(sheets, token):
    return next((a for a in sheets.read("appointments") if token and a["token"] == token), None)


def confirm(sheets, appt):
    if appt["status"] == "Booked":
        sheets.update("appointments", appt["_row"], {"status": "Confirmed", "confirmed_at": fmt(now())})
        appt.update(status="Confirmed")


def cancel(sheets, appt):
    """Cancels and immediately offers the freed slot to the waitlist."""
    import waitlist          # imported here because waitlist imports this module
    if appt["status"] not in ACTIVE:
        return
    sheets.update("appointments", appt["_row"], {"status": "Cancelled", "cancelled_at": fmt(now())})
    appt.update(status="Cancelled")
    waitlist.offer_slot(sheets, appt["slot_id"])
