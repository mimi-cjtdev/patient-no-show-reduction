"""
Cleaning and validation rules for rows in the backend sheet.

Each parser either returns a clean value or raises RowError with an error_type
(logged to sync_errors) and a message the front desk can act on. Harmless mess is
fixed rather than rejected, and every fix is recorded so the sheet can say what
was changed ("read status 'DNA' as No-show").
"""
import difflib
import re
from datetime import datetime

from config import STATUSES

STATUS_SYNONYMS = {
    "dna": "no_show", "did not attend": "no_show", "no show": "no_show", "noshow": "no_show",
    "no-show": "no_show", "ns": "no_show", "missed": "no_show",
    "arrived": "arrived", "attended": "arrived", "seen": "arrived", "checked in": "arrived",
    "cancelled": "cancelled", "canceled": "cancelled", "cxl": "cancelled", "cancel": "cancelled",
    "booked": "booked", "confirmed": "confirmed",
}
OUTCOMES = {"arrived", "no_show"}
TS_FORMATS = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


class RowError(Exception):
    def __init__(self, error_type, message):
        super().__init__(message)
        self.error_type = error_type
        self.message = message


class Cleaner:
    """Parses the fields of one sheet row and remembers what it had to fix."""

    def __init__(self, now):
        self.now = now
        self.fixes = []

    def required(self, value, field):
        if not (value or "").strip():
            raise RowError("missing_value", f"{field} is empty")
        return value.strip()

    def timestamp(self, value, field, required=True):
        v = (value or "").strip()
        if not v:
            if required:
                raise RowError("missing_value", f"{field} is empty")
            return None
        for f in TS_FORMATS:
            try:
                return datetime.strptime(v, f).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                continue
        raise RowError("bad_timestamp", f"can't read {field} '{v}' (use YYYY-MM-DD HH:MM)")

    def known(self, value, known, field, error_type):
        v = self.required(value, field)
        if v in known:
            return v
        hint = difflib.get_close_matches(v, list(known), n=1)
        raise RowError(error_type, f"unknown {field} '{v}'" + (f" (did you mean {hint[0]}?)" if hint else ""))

    def status(self, value, start_at):
        v = (value or "").strip()
        if not v:
            raise RowError("missing_value", "status is empty")
        if v in STATUSES:
            status = STATUSES[v]
        else:
            status = STATUS_SYNONYMS.get(re.sub(r"\s+", " ", v.lower()))
            if not status:
                raise RowError("bad_status", f"status '{v}' isn't one of: {', '.join(STATUSES)}")
            label = next(k for k, s in STATUSES.items() if s == status)
            self.fixes.append(f"status '{v}' → {label}")
        start = datetime.strptime(start_at, "%Y-%m-%d %H:%M")
        if status in OUTCOMES and start > self.now:
            raise RowError("outcome_too_early",
                           f"marked {value.strip()} but the appointment isn't until {start:%a %d %b %-I:%M %p}")
        if status in ("booked", "confirmed") and (self.now - start).total_seconds() > 24 * 3600:
            raise RowError("missing_outcome",
                           f"appointment was on {start:%a %d %b %-I:%M %p}: set Arrived or No-show")
        return status

    def flag(self, value, field):
        v = (value or "").strip().upper()
        if v in ("Y", "YES", "TRUE", "1"):
            return 1
        if v in ("N", "NO", "FALSE", "0"):
            return 0
        raise RowError("bad_value", f"{field} must be Y or N, not '{value}'")

    def integer(self, value, field, low=0, high=100):
        try:
            n = int(str(value).strip())
        except ValueError:
            raise RowError("bad_value", f"{field} must be a whole number, not '{value}'")
        if not low <= n <= high:
            raise RowError("bad_value", f"{field} must be between {low} and {high}")
        return n

    def email(self, value):
        v = self.required(value, "email")
        clean = v.lower()
        if not EMAIL_RE.match(clean):
            raise RowError("bad_email", f"email '{v}' isn't a valid address")
        if clean != (value or ""):
            self.fixes.append(f"email '{value}' → {clean}")
        return clean

    def phone(self, value):
        v = (value or "").strip()
        digits = re.sub(r"\D", "", v)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10:
            raise RowError("bad_phone", f"phone '{v}' needs 10 digits including area code")
        clean = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        if clean != v:
            self.fixes.append(f"phone '{v}' → {clean}")
        return clean
