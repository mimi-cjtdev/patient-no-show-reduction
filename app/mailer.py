"""
Patient emails: booking confirmation, 72h and 24h reminders, waitlist offers.

BRIGHTSIDE_MAIL_MODE=outbox (default) writes each email to outbox/ as an .eml file you can
open in Mail; BRIGHTSIDE_MAIL_MODE=gmail sends through Gmail SMTP with an app password.
BRIGHTSIDE_MAIL_REDIRECT_TO sends everything to one inbox instead, and reserved demo
domains (example.com etc.) are never sent to, since every demo patient is fake.
"""
import re
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from common import fmt, new_id, now, parse
from config import (BASE_URL, CLINICS, GMAIL_APP_PASSWORD, GMAIL_USER, MAIL_MODE, MAIL_REDIRECT_TO,
                    OUTBOX_DIR, WAITLIST_OFFER_HOURS)

SENDER_NAME = "Brightside Family Health"
FAKE_DOMAINS = re.compile(r"@(.+\.)?(example\.(com|org|net)|test|invalid|localhost)$", re.I)


def send(to, subject, text, html, mode=None, redirect=None):
    """Returns (recipient actually used, result) — result is sent / outbox / skipped_fake_address / failed: ...
    mode and redirect override BRIGHTSIDE_MAIL_MODE / BRIGHTSIDE_MAIL_REDIRECT_TO (used by the test-email script)."""
    mode = mode or MAIL_MODE
    redirect = MAIL_REDIRECT_TO if redirect is None else redirect
    recipient = redirect or to
    if redirect:
        subject = f"[for {to}] {subject}"
    msg = EmailMessage()
    msg["From"] = f"{SENDER_NAME} <{GMAIL_USER or 'appointments@brightside.example'}>"
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="brightside.example")
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    if mode != "gmail":
        OUTBOX_DIR.mkdir(exist_ok=True)
        name = f"{now():%Y%m%d-%H%M}-{new_id('m')[2:]}-{re.sub(r'[^a-z0-9]+', '-', subject.lower())[:60]}.eml"
        (OUTBOX_DIR / name).write_bytes(bytes(msg))
        return recipient, "outbox"
    if FAKE_DOMAINS.search(recipient):
        return recipient, "skipped_fake_address"
    if not (GMAIL_USER and GMAIL_APP_PASSWORD):
        return recipient, "failed: BRIGHTSIDE_GMAIL_USER / BRIGHTSIDE_GMAIL_APP_PASSWORD not set"
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
            smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        return recipient, "sent"
    except (smtplib.SMTPException, OSError) as e:
        return recipient, f"failed: {e}"


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def _when(appt):
    return f"{parse(appt['start_at']):%A %d %B at %-I:%M %p}"


def _button(url, label, color):
    return (f'<a href="{url}" style="display:inline-block;padding:12px 22px;margin:4px 8px 4px 0;'
            f'background:{color};color:#fff;text-decoration:none;border-radius:8px;font-weight:600">{label}</a>')


def _wrap(body):
    return (f'<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:520px;'
            f'margin:0 auto;padding:24px;color:#1d2a33;line-height:1.5">'
            f'<div style="font-weight:700;color:#0f766e;font-size:18px;margin-bottom:16px">{SENDER_NAME}</div>'
            f'{body}<p style="color:#6b7780;font-size:12px;margin-top:28px">Brightside Family Health is a '
            f'fictional clinic in a portfolio project. Please do not reply to this email.</p></div>')


def _details(appt, provider_name):
    return (f'<table style="border-collapse:collapse;margin:12px 0 20px">'
            f'<tr><td style="padding:4px 16px 4px 0;color:#6b7780">When</td><td><b>{_when(appt)}</b></td></tr>'
            f'<tr><td style="padding:4px 16px 4px 0;color:#6b7780">What</td><td>{appt["visit_type"]}</td></tr>'
            f'<tr><td style="padding:4px 16px 4px 0;color:#6b7780">With</td><td>{provider_name}</td></tr>'
            f'<tr><td style="padding:4px 16px 4px 0;color:#6b7780">Where</td>'
            f'<td>{CLINICS[appt["clinic_code"]]} clinic</td></tr></table>')


def appointment_email(kind, appt, patient, provider_name):
    """kind: booking_confirmation / reminder_72h / reminder_24h. Returns (subject, text, html)."""
    first = patient["full_name"].split()[0]
    confirm, cancel = f"{BASE_URL}/a/{appt['token']}/confirm", f"{BASE_URL}/a/{appt['token']}/cancel"
    confirmed = appt["status"] == "Confirmed"
    if kind == "booking_confirmation":
        subject = f"You're booked: {_when(appt)}"
        intro = "Thanks for booking with us. Here are your appointment details."
    elif kind == "reminder_72h":
        subject = f"Reminder: your appointment on {_when(appt)}"
        intro = "Just a reminder that your appointment is coming up in a few days."
    else:
        subject = f"Tomorrow: your appointment at {_when(appt).split(' at ')[1]}"
        intro = "Your appointment is tomorrow."
    ask = ("You've already confirmed, thank you. If your plans change, please cancel so someone "
           "on our waitlist can have the time." if confirmed else
           "Please confirm you're coming, or cancel if you can't make it, so someone on our waitlist can have the time.")
    buttons = ("" if confirmed else _button(confirm, "I'll be there", "#0f766e")) + _button(cancel, "Cancel", "#9aa5ad")
    html = _wrap(f"<p>Hi {first},</p><p>{intro}</p>{_details(appt, provider_name)}<p>{ask}</p>"
                 f"<p>{buttons}</p>")
    text = (f"Hi {first},\n\n{intro}\n\n{_when(appt)}\n{appt['visit_type']} with {provider_name}\n"
            f"{CLINICS[appt['clinic_code']]} clinic\n\n{ask}\n\n"
            + ("" if confirmed else f"Confirm: {confirm}\n") + f"Cancel: {cancel}\n")
    return subject, text, html


def waitlist_email(entry, slot, patient, provider_name):
    first = patient["full_name"].split()[0]
    claim = f"{BASE_URL}/w/{entry['offer_token']}"
    appt_like = {"start_at": slot["start_at"], "visit_type": entry["visit_type"], "clinic_code": slot["clinic_code"]}
    subject = f"An earlier appointment just opened up: {_when(appt_like)}"
    html = _wrap(f"<p>Hi {first},</p><p>Good news: a {entry['visit_type'].lower()} you're waiting for has "
                 f"opened up.</p>{_details(appt_like, provider_name)}<p>It's held for you for "
                 f"{WAITLIST_OFFER_HOURS} hours, then we'll offer it to the next person.</p>"
                 f"<p>{_button(claim, 'Book this time', '#0f766e')}</p>")
    text = (f"Hi {first},\n\nA {entry['visit_type'].lower()} opened up: {_when(appt_like)} with {provider_name} "
            f"at {CLINICS[slot['clinic_code']]} clinic.\nIt's held for you for {WAITLIST_OFFER_HOURS} hours.\n\n"
            f"Book it: {claim}\n")
    return subject, text, html


def log_row(appointment_id, kind, recipient, result):
    return {"reminder_id": new_id("R"), "appointment_id": appointment_id, "kind": kind,
            "sent_at": fmt(now()), "recipient": recipient, "result": result}
