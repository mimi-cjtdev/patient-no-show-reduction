"""Settings shared by the webapp, reminders and sync: clinics, visit types, sheet tabs, plus local config read from .env."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Local settings live in .env (never committed); real environment variables win
_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _key, _value = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _value.strip())

# "local" keeps every tab as a CSV in data/sheets/ so the whole system runs offline;
# "google" uses a real Google Sheet shared (Editor) with the service account.
SHEETS_BACKEND = os.environ.get("BRIGHTSIDE_SHEETS_BACKEND", "local")
SPREADSHEET_ID = os.environ.get("BRIGHTSIDE_SPREADSHEET_ID", "")
# ... or found by name in a Drive folder shared with the service account
DRIVE_FOLDER_ID = os.environ.get("BRIGHTSIDE_DRIVE_FOLDER", "")
SPREADSHEET_NAME = os.environ.get("BRIGHTSIDE_SPREADSHEET_NAME", "Brightside – Backend")
GOOGLE_KEY_FILE = os.path.expanduser(os.environ.get("BRIGHTSIDE_GOOGLE_KEY", "~/.brightside_google_key.json"))
LOCAL_SHEETS_DIR = ROOT / "data" / "sheets"
DB_PATH = Path(os.path.expanduser(os.environ.get("BRIGHTSIDE_DB_PATH", "data/brightside.db")))
DB_PATH = DB_PATH if DB_PATH.is_absolute() else ROOT / DB_PATH       # relative paths are from the project folder

# Email: "outbox" writes each email as an .eml file to outbox/ (nothing leaves the machine);
# "gmail" sends through Gmail SMTP with an app password.
MAIL_MODE = os.environ.get("BRIGHTSIDE_MAIL_MODE", "outbox")
GMAIL_USER = os.environ.get("BRIGHTSIDE_GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("BRIGHTSIDE_GMAIL_APP_PASSWORD", "")
# When set, every email goes to this inbox instead of the patient (the patients are fake)
MAIL_REDIRECT_TO = os.environ.get("BRIGHTSIDE_MAIL_REDIRECT_TO", "")
OUTBOX_DIR = Path(os.path.expanduser(os.environ.get("BRIGHTSIDE_OUTBOX", str(ROOT / "outbox"))))
BASE_URL = os.environ.get("BRIGHTSIDE_BASE_URL", "http://localhost:5050").rstrip("/")
# Metabase running in Docker without access to data/: the sync copies the database into this container
METABASE_CONTAINER = os.environ.get("BRIGHTSIDE_METABASE_CONTAINER", "")
METABASE_DB_FILE = os.environ.get("BRIGHTSIDE_METABASE_DB_FILE", "/brightside/brightside.db")   # path inside Metabase
CLINIC_TZ = os.environ.get("BRIGHTSIDE_TZ", "")          # e.g. America/New_York; empty = this machine's time

CLINICS = {
    "NTH": "Northgate",
    "RIV": "Riverside",
    "EST": "Eastview",
}

# What a patient can book. Each provider role offers one visit type.
VISIT_TYPES = {
    "GP consult":        {"role": "gp",        "minutes": 20, "fee": 95},
    "Physio session":    {"role": "physio",    "minutes": 45, "fee": 120},
    "Dietitian session": {"role": "dietitian", "minutes": 45, "fee": 130},
}

# Statuses as staff see them in the sheet's dropdown -> as stored in the database
STATUSES = {
    "Booked": "booked",
    "Confirmed": "confirmed",
    "Arrived": "arrived",
    "No-show": "no_show",
    "Cancelled": "cancelled",
}
STATUS_LABEL = {v: k for k, v in STATUSES.items()}

# The webapp, reminders and waitlist went live on this date; earlier bookings were by phone only
PROGRAM_LAUNCH = "2026-07-20"

REMINDER_WINDOWS = {            # kind -> send when the appointment is this many hours away (or less)
    "reminder_72h": (72, 26),   # ... but still more than the second number
    "reminder_24h": (24, 2),
}
WAITLIST_OFFER_HOURS = 2        # an unclaimed waitlist offer passes to the next patient after this

# Tabs in the backend sheet and their columns, in order.
# Front desk staff edit `status`; everything else is written by the webapp and scripts.
TABS = {
    "providers": ["provider_id", "provider_name", "clinic_code", "role"],
    "slots": ["slot_id", "provider_id", "clinic_code", "start_at", "minutes"],
    "patients": ["patient_id", "full_name", "email", "phone", "created_at", "sync_status"],
    "appointments": ["appointment_id", "booked_at", "booked_via", "patient_id", "slot_id", "clinic_code",
                     "provider_id", "visit_type", "start_at", "new_patient", "risk_score", "risk_band",
                     "status", "confirmed_at", "cancelled_at", "token", "sync_status"],
    "waitlist": ["waitlist_id", "added_at", "patient_id", "clinic_code", "visit_type", "status",
                 "offered_slot_id", "offered_at", "offer_token", "appointment_id"],
    "reminder_log": ["reminder_id", "appointment_id", "kind", "sent_at", "recipient", "result"],
}
