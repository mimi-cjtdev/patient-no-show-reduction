#!/usr/bin/env python3
"""
Brightside sync: backend sheet -> SQLite, for the Metabase dashboard.

For every tab it:
  1. reads all rows (the live sheet only holds a few weeks, so a full pass is cheap),
  2. cleans and validates them (validate.py),
  3. upserts the good rows in one transaction, logs the run in sync_runs and every
     rejected row in sync_errors (marking old errors resolved once a row comes through clean),
  4. writes a status back on the patients and appointments tabs, so the front desk
     can see exactly what to fix.

Re-running is safe: every write is an upsert on the row's ID, so nothing is duplicated.

Usage:  .venv/bin/python app/sync.py
Cron:   15 * * * * cd /path/to/patient-no-show-reduction && .venv/bin/python app/sync.py >> logs/sync.log 2>&1
"""
import json
import sqlite3
import subprocess
import sys
from dataclasses import dataclass

from common import fmt, now, utc_offset_minutes
from config import CLINICS, DB_PATH, METABASE_CONTAINER, METABASE_DB_FILE, ROOT, VISIT_TYPES
from sheets import backend
from validate import Cleaner, RowError

ACTIVE_OR_DONE = {"booked", "confirmed", "arrived", "no_show"}


@dataclass
class RunResult:
    source: str
    read: int = 0
    inserted: int = 0
    updated: int = 0
    rejected: int = 0
    fixed: int = 0
    status: str = "success"


def connect():
    if not DB_PATH.exists():
        raise SystemExit(f"No analytics database at {DB_PATH} (set BRIGHTSIDE_DB_PATH in .env).")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE IF NOT EXISTS clinic_clock (id INTEGER PRIMARY KEY CHECK (id = 1), "
                 "utc_offset_minutes INTEGER NOT NULL)")
    conn.executescript((ROOT / "sql" / "views.sql").read_text())    # keeps views current with the repo
    conn.execute("INSERT INTO clinic_clock VALUES (1, ?) ON CONFLICT (id) DO UPDATE SET "
                 "utc_offset_minutes = excluded.utc_offset_minutes", (utc_offset_minutes(),))
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Cleaning: sheet row -> record (or RowError)
# ---------------------------------------------------------------------------

def clean_provider(d, cl, lk):
    return {"provider_id": cl.required(d["provider_id"], "provider_id"),
            "provider_name": cl.required(d["provider_name"], "provider_name"),
            "clinic_code": cl.known(d["clinic_code"], CLINICS, "clinic_code", "unknown_clinic"),
            "role": cl.known(d["role"], {v["role"] for v in VISIT_TYPES.values()}, "role", "bad_value")}


def clean_slot(d, cl, lk):
    pid = cl.known(d["provider_id"], lk["providers"], "provider_id", "unknown_provider")
    return {"slot_id": cl.required(d["slot_id"], "slot_id"), "provider_id": pid,
            "clinic_code": lk["providers"][pid]["clinic_code"],
            "start_at": cl.timestamp(d["start_at"], "start_at"),
            "minutes": cl.integer(d["minutes"], "minutes", 5, 240)}


def clean_patient(d, cl, lk):
    name = " ".join(cl.required(d["full_name"], "full_name").split())
    return {"patient_id": cl.required(d["patient_id"], "patient_id"), "full_name": name,
            "email": cl.email(d["email"]), "phone": cl.phone(d["phone"]),
            "created_at": cl.timestamp(d["created_at"], "created_at")}


def clean_appointment(d, cl, lk):
    pid = cl.known(d["provider_id"], lk["providers"], "provider_id", "unknown_provider")
    provider = lk["providers"][pid]
    clinic = cl.known(d["clinic_code"], CLINICS, "clinic_code", "unknown_clinic")
    if clinic != provider["clinic_code"]:
        raise RowError("wrong_clinic", f"{provider['provider_name']} works at {CLINICS[provider['clinic_code']]}, "
                                       f"not {CLINICS[clinic]}")
    visit_type = cl.known(d["visit_type"], VISIT_TYPES, "visit_type", "bad_value")
    if VISIT_TYPES[visit_type]["role"] != provider["role"]:
        raise RowError("wrong_visit_type", f"{provider['provider_name']} doesn't do {visit_type.lower()}s")
    start_at = cl.timestamp(d["start_at"], "start_at")
    slot_id = cl.required(d["slot_id"], "slot_id")
    slot = lk["slots"].get(slot_id)
    if not slot:
        raise RowError("unknown_slot", f"unknown slot_id '{slot_id}'")
    if (slot["provider_id"], slot["start_at"]) != (pid, start_at):
        raise RowError("slot_mismatch", f"slot {slot_id} is {slot['start_at']} with {slot['provider_id']}, "
                                        f"but the row says {start_at} with {pid}")
    patient_id = cl.required(d["patient_id"], "patient_id")
    if patient_id not in lk["patients"]:
        raise RowError("unknown_patient", f"patient {patient_id} isn't in the database "
                                          "(check their row on the patients tab)")
    return {"appointment_id": cl.required(d["appointment_id"], "appointment_id"),
            "booked_at": cl.timestamp(d["booked_at"], "booked_at"),
            "booked_via": cl.known(d["booked_via"], {"phone", "web", "waitlist"}, "booked_via", "bad_value"),
            "patient_id": patient_id, "slot_id": slot_id, "clinic_code": clinic, "provider_id": pid,
            "visit_type": visit_type, "start_at": start_at,
            "new_patient": cl.flag(d["new_patient"], "new_patient"),
            "risk_score": cl.integer(d["risk_score"], "risk_score"),
            "risk_band": cl.known(d["risk_band"], {"low", "medium", "high"}, "risk_band", "bad_value"),
            "status": cl.status(d["status"], start_at),
            "confirmed_at": cl.timestamp(d["confirmed_at"], "confirmed_at", required=False),
            "cancelled_at": cl.timestamp(d["cancelled_at"], "cancelled_at", required=False),
            "synced_at": fmt(cl.now)}


def clean_waitlist(d, cl, lk):
    patient_id = cl.required(d["patient_id"], "patient_id")
    if patient_id not in lk["patients"]:
        raise RowError("unknown_patient", f"patient {patient_id} isn't in the database")
    return {"waitlist_id": cl.required(d["waitlist_id"], "waitlist_id"),
            "added_at": cl.timestamp(d["added_at"], "added_at"), "patient_id": patient_id,
            "clinic_code": cl.known(d["clinic_code"], CLINICS, "clinic_code", "unknown_clinic"),
            "visit_type": cl.known(d["visit_type"], VISIT_TYPES, "visit_type", "bad_value"),
            "status": cl.known(d["status"], {"waiting", "offered", "booked", "expired"}, "status", "bad_status"),
            "offered_slot_id": d["offered_slot_id"] or None,
            "offered_at": cl.timestamp(d["offered_at"], "offered_at", required=False),
            "appointment_id": d["appointment_id"] or None}


def clean_reminder(d, cl, lk):
    return {"reminder_id": cl.required(d["reminder_id"], "reminder_id"),
            "appointment_id": cl.required(d["appointment_id"], "appointment_id"),
            "kind": cl.required(d["kind"], "kind"), "sent_at": cl.timestamp(d["sent_at"], "sent_at"),
            "recipient": d["recipient"] or None, "result": cl.required(d["result"], "result")}


# tab -> (table, key column, cleaner, writes a status back to the sheet)
TABS = [
    ("providers", "providers", "provider_id", clean_provider, False),
    ("slots", "slots", "slot_id", clean_slot, False),
    ("patients", "patients", "patient_id", clean_patient, True),
    ("appointments", "appointments", "appointment_id", clean_appointment, True),
    ("waitlist", "waitlist", "waitlist_id", clean_waitlist, False),
    ("reminder_log", "reminders", "reminder_id", clean_reminder, False),
]


def lookups(conn):
    return {"providers": {r["provider_id"]: dict(r) for r in conn.execute("SELECT * FROM providers")},
            "slots": {r["slot_id"]: dict(r) for r in
                      conn.execute("SELECT slot_id, provider_id, start_at FROM slots")},
            "patients": {r[0] for r in conn.execute("SELECT patient_id FROM patients")}}


def double_bookings(records):
    """Two live appointments on one slot: the later booking is the mistake."""
    errors = {}
    by_slot = {}
    for key, rec in records.items():
        if rec["status"] in ACTIVE_OR_DONE:
            by_slot.setdefault(rec["slot_id"], []).append(rec)
    for slot_id, recs in by_slot.items():
        recs.sort(key=lambda r: r["booked_at"])
        for later in recs[1:]:
            errors[later["appointment_id"]] = RowError(
                "double_booked", f"slot {slot_id} is already taken by {recs[0]['appointment_id']}")
    return errors


# ---------------------------------------------------------------------------
# One tab
# ---------------------------------------------------------------------------

def sync_tab(conn, sheets, tab, table, key, clean, write_back, t):
    res = RunResult(tab)
    run_id = conn.execute("INSERT INTO sync_runs (started_at, source, status) VALUES (?, ?, 'running')",
                          (fmt(t), tab)).lastrowid
    conn.commit()
    try:
        rows = sheets.read(tab)
        res.read = len(rows)
        lk = lookups(conn)
        records, errors, fixes, seen = {}, {}, {}, {}
        for d in rows:
            raw_key = d.get(key) or f"row {d['_row']}"
            cl = Cleaner(t)
            try:
                rec = clean(d, cl, lk)
                if rec[key] in seen:
                    raise RowError("duplicate_id", f"{key} {rec[key]} is also on row {seen[rec[key]]}")
                seen[rec[key]] = d["_row"]
                records[rec[key]] = rec
                fixes[rec[key]] = cl.fixes
            except RowError as e:
                errors[raw_key] = (d, e)
        if tab == "appointments":
            for k, e in double_bookings(records).items():
                errors[k] = (next(r for r in rows if r.get(key) == k), e)
                del records[k]

        cols = None
        for rec in records.values():
            cols = cols or list(rec)
            existing = conn.execute(f"SELECT * FROM {table} WHERE {key} = ?", (rec[key],)).fetchone()
            if existing is None:
                res.inserted += 1
            elif any(existing[c] != rec[c] for c in cols if c != "synced_at"):
                res.updated += 1
            else:
                continue
            conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
                         f"ON CONFLICT ({key}) DO UPDATE SET "
                         + ", ".join(f"{c} = excluded.{c}" for c in cols if c != key),
                         [rec[c] for c in cols])
        res.fixed = sum(bool(f) for f in fixes.values())
        res.rejected = len(errors)

        stamp = fmt(t)
        conn.execute(f"UPDATE sync_errors SET resolved_at = ? WHERE source = ? AND resolved_at IS NULL "
                     f"AND row_key NOT IN ({', '.join('?' * len(errors)) or 'NULL'})", [stamp, tab, *errors])
        for row_key, (d, e) in errors.items():
            raw = json.dumps({k: v for k, v in d.items() if k not in ("_row", "token", "sync_status")})
            updated = conn.execute(
                "UPDATE sync_errors SET last_run_id = ?, last_seen_at = ?, sheet_row = ?, error_type = ?, "
                "message = ?, raw = ? WHERE source = ? AND row_key = ? AND resolved_at IS NULL",
                (run_id, stamp, d["_row"], e.error_type, e.message, raw, tab, row_key)).rowcount
            if not updated:
                conn.execute("INSERT INTO sync_errors (source, row_key, sheet_row, error_type, message, raw, "
                             "first_run_id, last_run_id, first_seen_at, last_seen_at) "
                             "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (tab, row_key, d["_row"], e.error_type, e.message, raw, run_id, run_id, stamp, stamp))
        conn.execute("UPDATE sync_runs SET finished_at = ?, rows_read = ?, inserted = ?, updated = ?, rejected = ?, "
                     "status = 'success' WHERE run_id = ?",
                     (fmt(now()), res.read, res.inserted, res.updated, res.rejected, run_id))
        conn.commit()          # the database commits before the sheet is stamped

        if write_back:
            changes = []
            for d in rows:
                k = d.get(key) or f"row {d['_row']}"
                if k in errors:
                    status = f"❌ {errors[k][1].message}"
                elif fixes.get(k):
                    status = "✅ synced · fixed: " + "; ".join(fixes[k])
                else:
                    status = "✅ synced"
                if d.get("sync_status") != status:
                    changes.append((d["_row"], {"sync_status": status}))
            sheets.update_many(tab, changes)
    except Exception as e:  # noqa: BLE001 — one broken tab must not stop the others
        conn.rollback()
        res.status = "failed"
        conn.execute("UPDATE sync_runs SET finished_at = ?, status = 'failed', message = ? WHERE run_id = ?",
                     (fmt(now()), f"{type(e).__name__}: {e}", run_id))
        conn.commit()
        print(f"  {tab:<13} FAILED  {type(e).__name__}: {e}", file=sys.stderr)
    return res


def copy_to_metabase():
    """Metabase in a container that can't see data/ reads its own copy of the database, refreshed here.
    The new copy is written over the old file in place (not renamed over it): Metabase keeps its SQLite
    connections open, and an open connection would go on reading a replaced file forever."""
    if not METABASE_CONTAINER:
        return True
    folder, tmp = METABASE_DB_FILE.rsplit("/", 1)[0], METABASE_DB_FILE + ".tmp"
    try:
        for cmd in (["docker", "exec", METABASE_CONTAINER, "mkdir", "-p", folder],
                    ["docker", "cp", str(DB_PATH), f"{METABASE_CONTAINER}:{tmp}"],
                    ["docker", "exec", METABASE_CONTAINER, "sh", "-c",
                     f"cat '{tmp}' > '{METABASE_DB_FILE}' && rm '{tmp}'"]):
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"  copy to Metabase FAILED: {getattr(e, 'stderr', '') or e}", file=sys.stderr)
        return False
    print(f"  copied to Metabase container {METABASE_CONTAINER}:{METABASE_DB_FILE}")
    return True


def main():
    t = now()
    conn = connect()
    sheets = backend()
    print(f"{fmt(t)}  sync {sheets.__class__.__name__} -> {DB_PATH.name}")
    results = [sync_tab(conn, sheets, *spec, t) for spec in TABS]
    for r in results:
        if r.status == "success":
            print(f"  {r.source:<13} read {r.read:>5}  inserted {r.inserted:>5}  updated {r.updated:>4}  "
                  f"fixed {r.fixed:>3}  rejected {r.rejected:>3}")
    open_errors = conn.execute("SELECT COUNT(*) FROM sync_errors WHERE resolved_at IS NULL").fetchone()[0]
    print(f"  rows waiting for a fix: {open_errors}")
    conn.close()
    copied = copy_to_metabase()
    return 1 if any(r.status == "failed" for r in results) or not copied else 0


if __name__ == "__main__":
    raise SystemExit(main())
