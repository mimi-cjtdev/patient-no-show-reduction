/**
 * Brightside – Backend: stamps confirmed_at when the front desk confirms an appointment by hand.
 *
 * Patients who click "I'll be there" in an email get confirmed_at from the webapp. When a patient
 * phones instead and staff set status to Confirmed, this fills in the same column, so the dashboard
 * counts them as confirmed too.
 *
 * Install: in the sheet, Extensions > Apps Script, paste this file, save. It's a simple trigger:
 * it runs on every edit by a person, with no authorisation step. (Edits made through the API by the
 * webapp or sync don't trigger it; they write confirmed_at themselves.)
 *
 *   - status changed to Confirmed, confirmed_at empty  -> confirmed_at = now
 *   - status changed from Confirmed back to Booked      -> confirmed_at cleared (the confirmation was a mistake)
 *   - anything else (Arrived, No-show, Cancelled)       -> confirmed_at kept: it records that they confirmed
 * Works for one cell, a paste, or a fill-down across many rows.
 */

var TAB = 'appointments';
var TIMESTAMP_FORMAT = 'yyyy-MM-dd HH:mm';   // the format the sync reads

function onEdit(e) {
  var sheet = e.range.getSheet();
  if (sheet.getName() !== TAB) return;

  var header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  var statusCol = header.indexOf('status') + 1;
  var confirmedCol = header.indexOf('confirmed_at') + 1;
  if (!statusCol || !confirmedCol) return;

  // only edits that touch the status column, below the header
  var firstCol = e.range.getColumn(), lastCol = firstCol + e.range.getNumColumns() - 1;
  if (statusCol < firstCol || statusCol > lastCol) return;
  var firstRow = Math.max(e.range.getRow(), 2);
  var lastRow = e.range.getRow() + e.range.getNumRows() - 1;
  if (lastRow < firstRow) return;

  var count = lastRow - firstRow + 1;
  var statuses = sheet.getRange(firstRow, statusCol, count, 1).getValues();
  var stampRange = sheet.getRange(firstRow, confirmedCol, count, 1);
  var stamps = stampRange.getDisplayValues();
  var now = Utilities.formatDate(new Date(), e.source.getSpreadsheetTimeZone(), TIMESTAMP_FORMAT);
  var singleCell = e.range.getNumRows() === 1 && e.range.getNumColumns() === 1;
  var changed = false;

  for (var i = 0; i < count; i++) {
    var status = String(statuses[i][0]).trim().toLowerCase();
    if (status === 'confirmed' && !stamps[i][0]) {
      stamps[i][0] = now;
      changed = true;
    } else if (status === 'booked' && singleCell && String(e.oldValue).trim().toLowerCase() === 'confirmed'
               && stamps[i][0]) {
      stamps[i][0] = '';
      changed = true;
    }
  }
  if (changed) {
    stampRange.setNumberFormat('@');           // keep it as text, so Sheets doesn't turn it into a date
    stampRange.setValues(stamps);
  }
}
