/**
 * SharpVision — read-only mirror of the private PINNACLE sheet.
 * Run in the user's separate "SharpVision Feed" Apps Script project.
 * Required explicit appsscript.json oauthScopes:
 * https://www.googleapis.com/auth/spreadsheets.readonly
 * https://www.googleapis.com/auth/script.external_request
 * Keep the existing Script Property SHARPVISION_FEED_KEY unchanged.
 *
 * Do not add this to the existing Excel update/alerts project.
 */
var SV_SHEET_ID = "1cabkyN1Nl74fIi-IhZ6Xxsbx2MeccjXHM3TSAvy-vzM";

function svFetch_(url) {
  return UrlFetchApp.fetch(url, {
    method: "get",
    headers: { Authorization: "Bearer " + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true
  });
}
function svRgb_(color) {
  if (!color) return "";
  function toByte(v) { return Math.max(0, Math.min(255, Math.round(Number(v || 0) * 255))); }
  function hex(v) { return toByte(v).toString(16).padStart(2, "0"); }
  return "#" + hex(color.red) + hex(color.green) + hex(color.blue);
}
function svResult_(data) {
  return ContentService.createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet(e) {
  try {
    var secret = PropertiesService.getScriptProperties().getProperty("SHARPVISION_FEED_KEY");
    var presented = e && e.parameter ? String(e.parameter.key || "") : "";
    if (!secret || !presented || secret !== presented) {
      return svResult_({ ok: false, error: "UNAUTHORIZED" });
    }

    // Read the native formatted values, including BL/BM league percentiles,
    // P final scores, O alerts and the original early/90-minute snapshots.
    var valueRange = encodeURIComponent("PINNACLE!A3:CD4502");
    var valueUrl = "https://sheets.googleapis.com/v4/spreadsheets/"
      + SV_SHEET_ID + "/values/" + valueRange
      + "?valueRenderOption=FORMATTED_VALUE&majorDimension=ROWS";
    var valueResponse = svFetch_(valueUrl);
    if (valueResponse.getResponseCode() !== 200) {
      return svResult_({ ok:false, error:"SHEETS_API_ERROR", status:valueResponse.getResponseCode() });
    }
    var rawRows = JSON.parse(valueResponse.getContentText()).values || [];
    var rows = rawRows.map(function(row) {
      var result = [];
      for (var i = 0; i < 82; i++) {
        result.push(row[i] === undefined ? "" : row[i]);
      }
      return result;
    });

    // Effective format already includes conditional formatting applied by Excel.
    // These are the source cells: K:P (turnover, shares, SofaScore, alerts,
    // result) and U:Y (11:00/90-minute shares and 90-minute turnover).
    // Unlike re-implementing the rules, this stays exact if the Excel changes.
    var formats = new Array(rows.length);
    var formatError = null;
    if (rows.length) {
      var last = Math.min(4502, rows.length + 2);
      var fields = "sheets(data(startRow,startColumn,rowData(values(effectiveFormat(backgroundColor,textFormat(foregroundColor))))))";
      var formatUrl = "https://sheets.googleapis.com/v4/spreadsheets/" + SV_SHEET_ID
        + "?includeGridData=true"
        + "&ranges=" + encodeURIComponent("PINNACLE!K3:P" + last)
        + "&ranges=" + encodeURIComponent("PINNACLE!U3:Y" + last)
        + "&fields=" + encodeURIComponent(fields);
      var formatResponse = svFetch_(formatUrl);
      if (formatResponse.getResponseCode() === 200) {
        var sheets = JSON.parse(formatResponse.getContentText()).sheets || [];
        sheets.forEach(function(sheet) {
          (sheet.data || []).forEach(function(block) {
            var colStart = Number(block.startColumn || 0);
            var rowStart = Number(block.startRow || 0) - 2;
            (block.rowData || []).forEach(function(row, i) {
              var target = rowStart + i;
              if (target < 0 || target >= rows.length) return;
              var rec = formats[target] || {};
              (row.values || []).forEach(function(cell, j) {
                var fmt = (cell || {}).effectiveFormat || {};
                var bg = svRgb_(fmt.backgroundColor);
                var fg = svRgb_((fmt.textFormat || {}).foregroundColor);
                // White/no-color cells use the neutral mobile theme.
                // Keep only Excel conditional fills to reduce feed size.
                if (bg && bg.toLowerCase() !== "#ffffff") rec[String(colStart + j)] = [bg, fg];
              });
              formats[target] = rec;
            });
          });
        });
      } else {
        // Continue serving valid match data if the optional style request fails.
        formatError = "FORMAT_API_" + formatResponse.getResponseCode();
      }
    }

    return svResult_({
      ok: true,
      updatedAt: new Date().toISOString(),
      rows: rows,
      formats: formats,
      formatError: formatError
    });
  } catch (err) {
    // Deliberately do not return tokens or internal error messages.
    return svResult_({ ok:false, error:"SHEET_READ_FAILED" });
  }
}
