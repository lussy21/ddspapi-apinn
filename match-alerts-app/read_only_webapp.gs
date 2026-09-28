/**
 * Match Alerts - READ ONLY connector
 * Separate from the core system.
 *
 * Returns ONLY active alert display data from PINNACLE:
 * league, home, away, alert.
 * It never writes to the spreadsheet.
 */
const SPREADSHEET_ID = "1cabkyN1Nl74fIi-IhZ6Xxsbx2MeccjXHM3TSAvy-vzM";
const SHEET_NAME = "PINNACLE";

function doGet(e) {
  const callback = sanitizeCallback_(e && e.parameter ? e.parameter.callback : "");
  const payload = buildPayload_();
  const json = JSON.stringify(payload);

  // JSONP avoids browser CORS issues for the separate static PWA.
  if (callback) {
    return ContentService
      .createTextOutput(callback + "(" + json + ");")
      .setMimeType(ContentService.MimeType.JAVASCRIPT);
  }

  return ContentService
    .createTextOutput(json)
    .setMimeType(ContentService.MimeType.JSON);
}

function buildPayload_() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    return { ok: false, error: "PINNACLE_NOT_FOUND", alerts: [] };
  }

  const lastRow = sheet.getLastRow();
  if (lastRow < 3) {
    return { ok: true, updatedAt: new Date().toISOString(), alerts: [] };
  }

  // Read A:P only. No formulas are changed and no writes are made.
  const values = sheet.getRange(3, 1, lastRow - 2, 16).getDisplayValues();
  const alerts = [];

  values.forEach(function(row) {
    const league = (row[0] || "").trim(); // A
    const home   = (row[1] || "").trim(); // B
    const away   = (row[2] || "").trim(); // C
    const alert  = (row[14] || "").trim(); // O
    const result = (row[15] || "").trim(); // P

    // Same active-alert rule used in the workbook: alert exists, result empty.
    if (!league || !home || !away || !alert || result) return;

    alerts.push({
      league: league,
      home: home,
      away: away,
      alert: alert
    });
  });

  return {
    ok: true,
    updatedAt: new Date().toISOString(),
    count: alerts.length,
    alerts: alerts
  };
}

function sanitizeCallback_(value) {
  if (!value) return "";
  return /^[A-Za-z_$][0-9A-Za-z_$\.]*$/.test(value) ? value : "";
}
