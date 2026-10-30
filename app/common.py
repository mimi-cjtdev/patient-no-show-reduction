"""Small helpers shared by every script: clinic-local time, timestamp formats and IDs."""
import os
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from config import CLINIC_TZ

TS = "%Y-%m-%d %H:%M"          # how every timestamp is written in the sheet and database


def now():
    """Clinic-local time, without tzinfo (the sheet stores plain local times).
    BRIGHTSIDE_NOW="2026-10-22 09:00" pins the clock, for demos and tests."""
    if os.environ.get("BRIGHTSIDE_NOW"):
        return datetime.strptime(os.environ["BRIGHTSIDE_NOW"], TS)
    current = datetime.now(ZoneInfo(CLINIC_TZ)) if CLINIC_TZ else datetime.now()
    return current.replace(tzinfo=None, second=0, microsecond=0)


def utc_offset_minutes():
    current = datetime.now(ZoneInfo(CLINIC_TZ)) if CLINIC_TZ else datetime.now().astimezone()
    return int(current.utcoffset().total_seconds() // 60)


def fmt(dt):
    return dt.strftime(TS) if dt else ""


def parse(value):
    return datetime.strptime(value, TS) if value else None


def try_parse(value):
    """parse() for cells staff may have retyped: None instead of an error."""
    try:
        return parse(value)
    except ValueError:
        return None


def new_id(prefix):
    return f"{prefix}-{secrets.token_hex(4).upper()}"


def new_token():
    return secrets.token_urlsafe(12)
