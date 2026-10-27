"""Compact PINNACLE presentation; canonical formula values remain untouched."""

import re


ALERT_COLUMN = 14
FIRST_FIXTURE_ROW = 3
ROW_HEIGHT = 24
COLUMN_WIDTH = 245
MAX_FONT_SIZE = 11
MIN_FONT_SIZE = 6
LABELS = {
    "ΦΑΒΟΡΙ ΓΥΡΙΣΜΑΤΟΣ": "ΓΥΡ",
    "ΚΟΝΤΡΑ ΓΥΡΙΣΜΑΤΟΣ": "ΚΓ",
    "ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ": "Σ+Τ",
    "ΦΑΒΟΡΙ SOFA+3X": "Σ3X",
    "ΦΑΒΟΡΙ ΤΖΙΡΟΥ 3X": "ΤΖ3X",
    "ΦΑΒΟΡΙ ΠΤΩΣΗ 2%": "ΠΤ2%",
    "ΦΑΒΟΡΙ 84+P60": "84+",
    "ΦΑΒΟΡΙ ΤΖΙΡΟΥ": "ΤΖ",
    "ΤΖΙΡΟΣ ↑": "ΤΖ↑",
    "ΦΑΒ 75+": "75+",
    "ΦΑΒ 60+": "60+",
    "WATCH ΚΟΝΤΡΑ": "WΚ",
    "WATCH ΦΑΒΟΡΙ": "WΦ",
    "ΔΥΝΑΤΟ ΚΟΝΤΡΑ +10": "ΔΚ+10",
    "ΔΥΝΑΤΟ ΚΟΝΤΡΑ (+10)": "ΔΚ+10",
    "ΔΥΝΑΤΟ ΚΟΝΤΡΑ": "ΔΚ",
    "ΔΥΝΑΤΟ ΦΑΒΟΡΙ": "ΔΦ",
    "ΚΟΝΤΡΑ": "ΚΟΝ",
    "ΦΑΒΟΡΙ": "ΦΑΒ",
    "Over1.5k": "O1.5k",
    "OVER 1.5": "O1.5k",
    "OVER 1.5 (ΚΟΝΤΡΑ)": "O1.5k",
    "Over1.5": "O1.5",
    "OVER 1.5 (ΡΟΗ)": "O1.5",
}
STRENGTH = re.compile(r"\s+·\s+(\d+(?:[.,]\d+)?/10)(?:\s+·.*)?$")


def compact_alert(value):
    """Return a display label, or None for blanks/errors/unknown alert families."""
    if not isinstance(value, str) or not value.strip() or value.startswith("#"):
        return None
    parts = []
    watching = False
    for part in value.split("|"):
        part = part.strip()
        if not part:
            continue
        strength = STRENGTH.search(part)
        name = part[:strength.start()] if strength else part
        name = re.sub(r"^[^\w]+", "", name).strip()
        label = LABELS.get(name)
        if label is None:
            # Preserve unfamiliar labels verbatim rather than conceal a new rule.
            return None
        watching = watching or name.startswith("WATCH")
        parts.append(label + (" " + strength.group(1) if strength else ""))
    if not parts:
        return None
    label = ("👀 " if watching else "🔔 ") + " | ".join(parts)
    # Keep all markets visible at the existing width, including longer families.
    # A score is still out of ten when the repeated unit is omitted for fit.
    return label.replace("/10", "") if len(label) > 27 else label


def alert_number_format(value):
    label = compact_alert(value)
    if label is None:
        return {"type": "TEXT", "pattern": "@"}
    escaped = label.replace("\\", "\\\\").replace('"', '\\"')
    return {"type": "NUMBER", "pattern": '0;-0;0;"' + escaped + '"'}


def alert_font_size(value):
    """Conservative bold-glyph estimate at 11pt; no extra runtime dependency."""
    label = compact_alert(value)
    if label is None:
        return MAX_FONT_SIZE
    width = 0
    for char in label:
        if char == " ":
            width += 5.2
        elif char in "|.,/":
            width += 5.7
        elif char in "🔔👀":
            width += 18
        elif char in "WΜΩ":
            width += 15
        elif char in "+↑":
            width += 12.5
        elif char.isdigit() or char.islower():
            width += 10.5
        else:
            width += 12
    available = COLUMN_WIDTH - 10
    return max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(MAX_FONT_SIZE * available / max(1, width))))


def canonical_alert_rows(sheet, rows, first_row=1):
    """Overlay only O with raw values; retain Greek money/percentage formatting."""
    if not rows:
        return rows
    raw = sheet.get(
        f"O{first_row}:O{first_row + len(rows) - 1}",
        value_render_option="UNFORMATTED_VALUE",
    )
    result = [list(row) for row in rows]
    for i, row in enumerate(result):
        value = raw[i][0] if i < len(raw) and raw[i] else ""
        if len(row) > ALERT_COLUMN or value:
            row.extend([""] * max(0, ALERT_COLUMN + 1 - len(row)))
            row[ALERT_COLUMN] = value
    return result


def last_fixture_row(rows, first_row=1):
    return max(
        (first_row + i for i, row in enumerate(rows)
         if first_row + i >= FIRST_FIXTURE_ROW
         and len(row) > 2 and str(row[1]).strip() and str(row[2]).strip()),
        default=FIRST_FIXTURE_ROW - 1,
    )


def display_requests(sheet_id, values, first_row=FIRST_FIXTURE_ROW):
    if not values:
        return []
    start = first_row - 1
    end = start + len(values)
    return [
        {"updateCells": {
            "range": {"sheetId": sheet_id, "startRowIndex": start,
                      "endRowIndex": end, "startColumnIndex": ALERT_COLUMN,
                      "endColumnIndex": ALERT_COLUMN + 1},
            "rows": [{"values": [{"userEnteredFormat": {
                "numberFormat": alert_number_format(row[0] if row else ""),
                "wrapStrategy": "CLIP",
                "textFormat": {"fontSize": alert_font_size(row[0] if row else "")},
            }}]} for row in values],
            "fields": "userEnteredFormat.numberFormat,userEnteredFormat.wrapStrategy,userEnteredFormat.textFormat.fontSize",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "ROWS",
                      "startIndex": start, "endIndex": end},
            "properties": {"pixelSize": ROW_HEIGHT}, "fields": "pixelSize",
        }},
    ]


def reset_alert_display(book, sheet, rows, first_row=1):
    """Expose canonical text while a writer changes inputs, avoiding stale badges."""
    end = last_fixture_row(rows, first_row)
    if end < FIRST_FIXTURE_ROW:
        return
    request = {"repeatCell": {
        "range": {"sheetId": sheet.id, "startRowIndex": FIRST_FIXTURE_ROW - 1,
                  "endRowIndex": end, "startColumnIndex": ALERT_COLUMN,
                  "endColumnIndex": ALERT_COLUMN + 1},
        "cell": {"userEnteredFormat": {
            "numberFormat": {"type": "TEXT", "pattern": "@"},
            "wrapStrategy": "CLIP",
        }},
        "fields": "userEnteredFormat.numberFormat,userEnteredFormat.wrapStrategy",
    }}
    try:
        book.batch_update({"requests": [request]})
    except Exception as exc:
        # Presentation must never prevent odds writes or canonical event recording.
        print("ALERT DISPLAY RESET ERROR:", repr(exc))
        return False
    return True


def refresh_alert_display(book, sheet, rows, first_row=1):
    """Re-read the final formula state, including withdrawals and selector scores."""
    end = last_fixture_row(rows, first_row)
    if end < FIRST_FIXTURE_ROW:
        return
    values = list(sheet.get(
        f"O{FIRST_FIXTURE_ROW}:O{end}", value_render_option="UNFORMATTED_VALUE",
    ))
    # A trimmed empty tail must clear its old display format too.
    values.extend([[] for _ in range(end - FIRST_FIXTURE_ROW + 1 - len(values))])
    requests = display_requests(sheet.id, values)
    book.batch_update({"requests": requests})
    print("ALERT DISPLAY REFRESH:", len(values), "rows")
