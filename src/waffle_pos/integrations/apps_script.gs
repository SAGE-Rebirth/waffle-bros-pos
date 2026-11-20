/**
 * Waffle Bros POS -> Google Sheet bridge.
 *
 * Setup (once):
 *  1. Open the Google Sheet, then Extensions -> Apps Script. Delete what's there and paste this file.
 *  2. SECRET below must be the "Secret" from POS Admin -> Modules -> Google Sheet sync. The POS fills
 *     it in for you when you copy this script after saving a secret; otherwise replace
 *     PASTE_THE_SECRET_FROM_THE_POS with it (the same text in both places).
 *  3. Deploy -> New deployment -> type "Web app". Execute as: Me. Who has access: Anyone.
 *     Approve the permissions Google asks for (it only needs this spreadsheet).
 *  4. Copy the web app URL (ends in /exec) into the POS admin page, switch sync on, press Sync now.
 *
 * "Anyone" only means the URL needs no Google sign-in: every request must carry the secret, and
 * the script can only write the POS tabs in this one spreadsheet.
 */
const SECRET = 'PASTE_THE_SECRET_FROM_THE_POS';
// Split in two so that a find-and-replace of the placeholder above can't change this one too.
const PLACEHOLDER = 'PASTE_THE_' + 'SECRET_FROM_THE_POS';
const ALLOWED_TABS = ['Orders', 'OrderItems', 'Expenses', 'Daily', 'Items', 'Monthly'];
const MAX_ROWS = 5000;

function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply_({ ok: false, error: 'The request was not valid JSON' });
  }
  if (!SECRET || SECRET === PLACEHOLDER || SECRET.length < 16) {
    return reply_({ ok: false, error: 'Set SECRET in the Apps Script (at least 16 characters)' });
  }
  if (typeof body.secret !== 'string' || !safeEquals_(body.secret, SECRET)) {
    return reply_({ ok: false, error: 'Wrong secret: it must match the POS admin page' });
  }
  const tabs = Array.isArray(body.tabs) ? body.tabs : [];
  for (const t of tabs) {
    if (ALLOWED_TABS.indexOf(t.name) < 0) return reply_({ ok: false, error: 'Unknown tab ' + t.name });
    if (!Array.isArray(t.header) || !Array.isArray(t.rows) || t.rows.length > MAX_ROWS) {
      return reply_({ ok: false, error: 'Bad data for tab ' + t.name });
    }
  }
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    tabs.forEach(function (t) { writeTab_(ss, t); });
    return reply_({ ok: true, tabs: tabs.length });
  } catch (err) {
    return reply_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function writeTab_(ss, t) {
  const width = t.header.length;
  let sheet = ss.getSheetByName(t.name) || ss.insertSheet(t.name);
  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, width).setValues([t.header]).setFontWeight('bold');
    sheet.setFrozenRows(1);
  }
  const rows = t.rows.map(function (r) {
    const row = r.slice(0, width).map(clean_);
    while (row.length < width) row.push('');
    return row;
  });
  if (t.mode === 'append') {
    if (rows.length) sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, width).setValues(rows);
    return;
  }
  // Summary tab: write the new rows first, then clear what's left below them, so the tab is never
  // empty in between (charts lose their series when their columns go blank).
  if (rows.length) sheet.getRange(2, 1, rows.length, width).setValues(rows);
  const last = sheet.getLastRow();
  if (last > rows.length + 1) sheet.getRange(rows.length + 2, 1, last - rows.length - 1, width).clearContent();
}

// Text that starts with = + - @, a tab or a carriage return could run as a formula; keep it as plain text.
function clean_(v) {
  if (typeof v === 'string' && /^[=+\-@\t\r]/.test(v) && isNaN(Number(v))) return "'" + v;
  return v;
}

function safeEquals_(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function reply_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
