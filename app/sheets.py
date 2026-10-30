"""
The operational backend: one spreadsheet with a tab per table (see config.TABS).

Two interchangeable backends with the same four calls:
  read(tab)                     -> list of dicts, each with "_row" (its 1-based sheet row)
  append(tab, rows)             -> add rows at the bottom
  update(tab, row, values)      -> change some cells of one row
  replace(tab, rows)            -> overwrite everything under the header

GoogleSheets talks to a real Google Sheet; LocalSheets keeps each tab as a CSV in
data/sheets/, so the webapp and scripts can be run and tested with no Google account.
Every value is a string, exactly as staff would see it in the sheet.
"""
import csv
import threading
import time

from config import (DRIVE_FOLDER_ID, GOOGLE_KEY_FILE, LOCAL_SHEETS_DIR, SHEETS_BACKEND, SPREADSHEET_ID,
                    SPREADSHEET_NAME, STATUSES, TABS)

_lock = threading.Lock()


class LocalSheets:
    def __init__(self, folder=LOCAL_SHEETS_DIR):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)

    def _path(self, tab):
        return self.folder / f"{tab}.csv"

    def _load(self, tab):
        path = self._path(tab)
        if not path.exists():
            return list(TABS[tab]), []
        with path.open(newline="") as f:
            rows = list(csv.reader(f))
        return (rows[0], rows[1:]) if rows else (list(TABS[tab]), [])

    def _save(self, tab, header, rows):
        tmp = self._path(tab).with_suffix(".tmp")
        with tmp.open("w", newline="") as f:
            csv.writer(f).writerows([header] + rows)
        tmp.replace(self._path(tab))

    def read(self, tab):
        with _lock:
            header, rows = self._load(tab)
        return [_as_dict(header, r, i + 2) for i, r in enumerate(rows)]

    def append(self, tab, new_rows):
        with _lock:
            header, rows = self._load(tab)
            rows += [[str(r.get(c, "")) for c in header] for r in new_rows]
            self._save(tab, header, rows)

    def update(self, tab, row, values):
        with _lock:
            header, rows = self._load(tab)
            line = rows[row - 2]
            line += [""] * (len(header) - len(line))
            for col, value in values.items():
                line[header.index(col)] = str(value)
            self._save(tab, header, rows)

    def update_many(self, tab, changes):
        with _lock:
            header, rows = self._load(tab)
            for row, values in changes:
                line = rows[row - 2]
                line += [""] * (len(header) - len(line))
                for col, value in values.items():
                    line[header.index(col)] = str(value)
            self._save(tab, header, rows)

    def replace(self, tab, new_rows):
        with _lock:
            header = list(TABS[tab])
            self._save(tab, header, [[str(r.get(c, "")) for c in header] for r in new_rows])

    def reset(self, tab):
        self.replace(tab, [])


class GoogleSheets:
    """A real Google Sheet. Reads are cached for a few seconds so the booking page stays fast
    and inside the Sheets API quota (60 reads per minute)."""

    CACHE_SECONDS = 10
    SLOW_CHANGING = {"providers": 300, "slots": 300}   # the schedule changes rarely; cache it for 5 minutes

    def __init__(self, spreadsheet_id=SPREADSHEET_ID, key_file=GOOGLE_KEY_FILE):
        import gspread
        from gspread.http_client import BackOffHTTPClient
        client = gspread.service_account(filename=key_file, http_client=BackOffHTTPClient)
        # never wait forever on Google: a request left hanging (e.g. the Mac slept mid-call) fails after
        # a minute and is retried, instead of freezing the hourly job
        client.set_timeout((10, 60))
        if not spreadsheet_id and DRIVE_FOLDER_ID:
            def same(name):         # "Brightside - Backend" typed with a hyphen still matches
                return " ".join(name.replace("–", "-").lower().split())
            found = [f["id"] for f in client.list_spreadsheet_files(folder_id=DRIVE_FOLDER_ID)
                     if same(f["name"]) == same(SPREADSHEET_NAME)]
            spreadsheet_id = found[0] if found else ""
        if not spreadsheet_id:
            raise SystemExit(f"No backend sheet: create an empty Google Sheet named '{SPREADSHEET_NAME}' in the "
                             "Drive folder (BRIGHTSIDE_DRIVE_FOLDER), or set BRIGHTSIDE_SPREADSHEET_ID in .env.")
        self.book = client.open_by_key(spreadsheet_id)
        self._ws = {}
        self._cache = {}

    def worksheet(self, tab):
        if tab not in self._ws:
            self._ws[tab] = self.book.worksheet(tab)
        return self._ws[tab]

    def read(self, tab):
        hit = self._cache.get(tab)
        if hit and time.monotonic() - hit[0] < self.SLOW_CHANGING.get(tab, self.CACHE_SECONDS):
            return [dict(r) for r in hit[1]]
        values = self.worksheet(tab).get_all_values()
        header, rows = (values[0], values[1:]) if values else (list(TABS[tab]), [])
        records = [_as_dict(header, r, i + 2) for i, r in enumerate(rows)]
        self._cache[tab] = (time.monotonic(), records)
        return [dict(r) for r in records]

    def _header(self, tab):
        return self.worksheet(tab).row_values(1) or list(TABS[tab])

    def append(self, tab, new_rows):
        header = self._header(tab)
        self.worksheet(tab).append_rows([[str(r.get(c, "")) for c in header] for r in new_rows],
                                        value_input_option="RAW")
        self._cache.pop(tab, None)

    def update(self, tab, row, values):
        from gspread.utils import rowcol_to_a1
        header = self._header(tab)
        self.worksheet(tab).batch_update(
            [{"range": rowcol_to_a1(row, header.index(c) + 1), "values": [[str(v)]]} for c, v in values.items()],
            value_input_option="RAW")
        self._cache.pop(tab, None)

    def update_many(self, tab, changes):
        """[(row, {col: value}), ...] in one API call (used by the sync's status write-back)."""
        from gspread.utils import rowcol_to_a1
        if not changes:
            return
        header = self._header(tab)
        self.worksheet(tab).batch_update(
            [{"range": rowcol_to_a1(row, header.index(c) + 1), "values": [[str(v)]]}
             for row, values in changes for c, v in values.items()], value_input_option="RAW")
        self._cache.pop(tab, None)

    def replace(self, tab, new_rows):
        ws = self.worksheet(tab)
        header = list(TABS[tab])
        ws.clear()
        ws.resize(rows=max(len(new_rows) + 1, 2), cols=len(header))
        ws.update([header] + [[str(r.get(c, "")) for c in header] for r in new_rows], "A1",
                  value_input_option="RAW")
        self._cache.pop(tab, None)

    def reset(self, tab):
        """Create the tab if needed and leave only its header row."""
        import gspread
        try:
            self.worksheet(tab)
        except gspread.WorksheetNotFound:
            self._ws[tab] = self.book.add_worksheet(tab, rows=100, cols=len(TABS[tab]))
        self.replace(tab, [])

    def format(self):
        """Makes the sheet usable by the front desk: tabs in order, bold frozen headers, a status
        dropdown, the token column hidden, a warning on every column staff shouldn't edit,
        and the default empty "Sheet1" removed."""
        import gspread
        for ws in self.book.worksheets():
            if ws.title not in TABS and len(self.book.worksheets()) > 1:
                try:
                    self.book.del_worksheet(ws)
                except gspread.exceptions.APIError:
                    pass
        meta = self.book.fetch_sheet_metadata()
        old_protections = [p["protectedRangeId"] for s in meta["sheets"] for p in s.get("protectedRanges", [])
                           if p.get("description", "").startswith("Brightside")]
        requests = [{"deleteProtectedRange": {"protectedRangeId": pid}} for pid in old_protections]
        for index, (tab, columns) in enumerate(TABS.items()):
            sid = self.worksheet(tab).id
            requests += [
                {"updateSheetProperties": {"properties": {"sheetId": sid, "index": index,
                                                          "gridProperties": {"frozenRowCount": 1}},
                                           "fields": "index,gridProperties.frozenRowCount"}},
                {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                                "cell": {"userEnteredFormat": {"textFormat": {"bold": True},
                                                               "backgroundColor": {"red": .89, "green": .95, "blue": .94}}},
                                "fields": "userEnteredFormat(textFormat,backgroundColor)"}},
                {"autoResizeDimensions": {"dimensions": {"sheetId": sid, "dimension": "COLUMNS",
                                                         "startIndex": 0, "endIndex": len(columns)}}},
            ]
        appts = self.worksheet("appointments")
        status_col, token_col = TABS["appointments"].index("status"), TABS["appointments"].index("token")
        requests += [
            {"setDataValidation": {
                "range": {"sheetId": appts.id, "startRowIndex": 1, "startColumnIndex": status_col,
                          "endColumnIndex": status_col + 1},
                # not strict: a typo still gets in (as in real life), and the sync flags it
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": s} for s in STATUSES]},
                         "showCustomUi": True, "strict": False}}},
            {"updateDimensionProperties": {
                "range": {"sheetId": appts.id, "dimension": "COLUMNS", "startIndex": token_col,
                          "endIndex": token_col + 1},
                "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
            # staff edit status; everything else shows a "are you sure?" warning
            {"addProtectedRange": {"protectedRange": {
                "range": {"sheetId": appts.id, "startColumnIndex": 0, "endColumnIndex": status_col},
                "description": "Brightside: written by the booking system", "warningOnly": True}}},
            {"addProtectedRange": {"protectedRange": {
                "range": {"sheetId": appts.id, "startColumnIndex": status_col + 1},
                "description": "Brightside: written by the booking system", "warningOnly": True}}},
        ]
        for tab in ("slots", "reminder_log"):
            requests.append({"addProtectedRange": {"protectedRange": {
                "range": {"sheetId": self.worksheet(tab).id},
                "description": "Brightside: written by the booking system", "warningOnly": True}}})
        self.book.batch_update({"requests": requests})

def _as_dict(header, values, row_number):
    values = list(values) + [""] * (len(header) - len(values))
    d = dict(zip(header, (v.strip() if isinstance(v, str) else v for v in values)))
    d["_row"] = row_number
    return d


_backend = None


def backend():
    global _backend
    if _backend is None:
        _backend = GoogleSheets() if SHEETS_BACKEND == "google" else LocalSheets()
    return _backend
