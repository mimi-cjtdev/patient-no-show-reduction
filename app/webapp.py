#!/usr/bin/env python3
"""
Brightside booking webapp: patients book, confirm, cancel and claim waitlist offers.

Every write goes straight to the backend sheet (sheets.py), where front desk staff see it.
Confirm / cancel / claim links from emails open a page with one button rather than acting
on the GET itself, so email security scanners that pre-open links can't cancel anything.

Usage:  .venv/bin/python app/webapp.py          # http://localhost:5050
"""
from collections import OrderedDict

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

import booking
import mailer
import waitlist
from booking import BookingError
from common import parse
from config import CLINICS, VISIT_TYPES
from sheets import backend

app = Flask(__name__)


def send_appointment_email(sheets, kind, appt, patient=None):
    patient = patient or next(p for p in sheets.read("patients") if p["patient_id"] == appt["patient_id"])
    provider = booking.providers(sheets)[appt["provider_id"]]
    subject, text, html = mailer.appointment_email(kind, appt, patient, provider["provider_name"])
    recipient, result = mailer.send(patient["email"], subject, text, html)
    sheets.append("reminder_log", [mailer.log_row(appt["appointment_id"], kind, recipient, result)])


def clinics_offering(sheets):
    """visit type -> clinic codes that have a provider for it"""
    roles = {}
    for p in booking.providers(sheets).values():
        roles.setdefault(p["role"], set()).add(p["clinic_code"])
    return {v: sorted(roles.get(info["role"], ())) for v, info in VISIT_TYPES.items()}


@app.get("/")
def home():
    return render_template("book.html", visit_types=VISIT_TYPES, clinics=CLINICS,
                           offering=clinics_offering(backend()), form={}, error=None)


@app.get("/api/slots")
def api_slots():
    clinic, visit_type = request.args.get("clinic"), request.args.get("visit_type")
    if clinic not in CLINICS or visit_type not in VISIT_TYPES:
        return jsonify(days=[])
    days = OrderedDict()
    for s in booking.open_slots(backend(), clinic, visit_type):
        start = parse(s["start_at"])
        day = days.setdefault(start.date(), {"label": f"{start:%a %-d %b}", "slots": []})
        day["slots"].append({"slot_id": s["slot_id"], "time": f"{start:%-I:%M %p}".lower(),
                             "provider": s["provider_name"]})
    return jsonify(days=list(days.values())[:10])


@app.post("/book")
def book():
    sheets, f = backend(), request.form
    try:
        if f.get("visit_type") not in VISIT_TYPES or f.get("clinic_code") not in CLINICS:
            raise BookingError("Please choose what you need and a clinic.")
        if not f.get("slot_id"):
            raise BookingError("Please pick a time.")
        patient = booking.find_or_create_patient(sheets, f.get("full_name"), f.get("email"), f.get("phone"))
        appt = booking.book(sheets, f["slot_id"], patient, f["visit_type"])
    except BookingError as e:
        return render_template("book.html", visit_types=VISIT_TYPES, clinics=CLINICS,
                               offering=clinics_offering(sheets), form=f, error=str(e)), 400
    send_appointment_email(sheets, "booking_confirmation", appt, patient)
    return redirect(url_for("booked", token=appt["token"]))


@app.post("/waitlist")
def join_waitlist():
    sheets, f = backend(), request.form
    try:
        if f.get("visit_type") not in VISIT_TYPES or f.get("clinic_code") not in CLINICS:
            raise BookingError("Please choose what you need and a clinic.")
        patient = booking.find_or_create_patient(sheets, f.get("full_name"), f.get("email"), f.get("phone"))
    except BookingError as e:
        return render_template("book.html", visit_types=VISIT_TYPES, clinics=CLINICS,
                               offering=clinics_offering(sheets), form=f, error=str(e)), 400
    waitlist.join(sheets, patient, f["clinic_code"], f["visit_type"])
    return render_template("message.html", title="You're on the waitlist",
                           body=f"We'll email {patient['email']} as soon as a {f['visit_type'].lower()} opens up "
                                f"at {CLINICS[f['clinic_code']]}. Offers are held for you for a couple of hours.")


def _appt_or_404(token):
    appt = booking.by_token(backend(), token)
    if not appt:
        abort(404)
    return appt


def _details(appt):
    sheets = backend()
    return {"when": f"{parse(appt['start_at']):%A %-d %B, %-I:%M %p}", "what": appt["visit_type"],
            "who": booking.providers(sheets)[appt["provider_id"]]["provider_name"],
            "where": f"{CLINICS[appt['clinic_code']]} clinic", "status": appt["status"]}


@app.get("/booked/<token>")
def booked(token):
    appt = _appt_or_404(token)
    return render_template("appointment.html", title="You're booked", appt=_details(appt), token=token,
                           note="We've emailed you the details, and we'll send a reminder before your visit.",
                           action=None)


@app.route("/a/<token>/confirm", methods=["GET", "POST"])
def confirm(token):
    appt = _appt_or_404(token)
    if request.method == "POST":
        booking.confirm(backend(), appt)
    if appt["status"] == "Confirmed":
        return render_template("appointment.html", title="Thanks, see you then", appt=_details(appt),
                               token=token, note="You're confirmed.", action=None)
    if appt["status"] != "Booked":
        return render_template("appointment.html", title="This appointment can't be confirmed",
                               appt=_details(appt), token=token, note=None, action=None)
    return render_template("appointment.html", title="Confirm your appointment", appt=_details(appt),
                           token=token, note=None, action={"label": "Yes, I'll be there", "kind": "primary"})


@app.route("/a/<token>/cancel", methods=["GET", "POST"])
def cancel(token):
    appt = _appt_or_404(token)
    if request.method == "POST":
        booking.cancel(backend(), appt)
        return render_template("appointment.html", title="Your appointment is cancelled", appt=_details(appt),
                               token=token, note="Thanks for letting us know. Your time has been offered to "
                                                 "someone on our waitlist.", action=None, rebook=True)
    if appt["status"] not in booking.ACTIVE:
        return render_template("appointment.html", title="This appointment is no longer active",
                               appt=_details(appt), token=token, note=None, action=None, rebook=True)
    return render_template("appointment.html", title="Cancel this appointment?", appt=_details(appt),
                           token=token, note="Cancelling lets someone on our waitlist have this time.",
                           action={"label": "Cancel appointment", "kind": "danger"})


@app.route("/w/<token>", methods=["GET", "POST"])
def claim(token):
    sheets = backend()
    entry = waitlist.by_token(sheets, token)
    if not entry:
        abort(404)
    if entry["status"] == "booked":
        appt = next(a for a in sheets.read("appointments") if a["appointment_id"] == entry["appointment_id"])
        return redirect(url_for("booked", token=appt["token"]))
    slot = next(s for s in sheets.read("slots") if s["slot_id"] == entry["offered_slot_id"])
    details = {"when": f"{parse(slot['start_at']):%A %-d %B, %-I:%M %p}", "what": entry["visit_type"],
               "who": booking.providers(sheets)[slot["provider_id"]]["provider_name"],
               "where": f"{CLINICS[slot['clinic_code']]} clinic", "status": ""}
    if request.method == "POST":
        try:
            appt = waitlist.claim(sheets, entry)
        except BookingError as e:
            return render_template("message.html", title="This offer has gone", body=str(e)), 409
        send_appointment_email(sheets, "booking_confirmation", appt)
        return redirect(url_for("booked", token=appt["token"]))
    if not waitlist.offer_is_live(entry):
        return render_template("message.html", title="This offer has gone",
                               body="Sorry, it wasn't claimed in time and was passed to the next person. "
                                    "You can join the waitlist again from the booking page.")
    return render_template("appointment.html", title="A time opened up for you", appt=details, token=token,
                           note="It's held for you for a couple of hours.",
                           action={"label": "Book this time", "kind": "primary"})


@app.errorhandler(404)
def not_found(_):
    return render_template("message.html", title="We couldn't find that",
                           body="This link may be out of date. You can book a new appointment below."), 404


if __name__ == "__main__":
    app.run(port=5050, debug=True)
