/**
 * SharpVision read-only Sheet bridge.
 * Create a NEW standalone Apps Script project. Never modify the existing automation project.
 * Store a long random SHARPVISION_FEED_KEY under Project Settings > Script Properties.
 * Deploy as Web app: Execute as Me; Access: Anyone.
 * The key MUST stay secret; it is passed server-to-server, never to browser users.
 * This script never writes anything to the spreadsheet.
 */
function doGet(e) {
  try {
    var configuredKey = PropertiesService.getScriptProperties().getProperty('SHARPVISION_FEED_KEY');
    var presentedKey = (e && e.parameter && e.parameter.key) ? String(e.parameter.key) : '';
    if (!configuredKey || !presentedKey || configuredKey !== presentedKey) {
      return json_({ok:false,error:'UNAUTHORIZED'});
    }
    var workbook = SpreadsheetApp.openById('1cabkyN1Nl74fIi-IhZ6Xxsbx2MeccjXHM3TSAvy-vzM');
    var sheet = workbook.getSheetByName('PINNACLE');
    if (!sheet) return json_({ok:false,error:'SHEET_NOT_FOUND'});
    var lastRow = sheet.getLastRow();
    var values = lastRow >= 3 ? sheet.getRange(3,1,Math.min(lastRow-2,4500),25).getDisplayValues() : [];
    return json_({ok:true,updatedAt:new Date().toISOString(),rows:values});
  } catch (err) {
    return json_({ok:false,error:'SHEET_READ_FAILED'});
  }
}
function json_(payload) {
  return ContentService.createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
