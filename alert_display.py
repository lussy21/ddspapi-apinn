"""PINNACLE font fitting; names and canonical formula values stay intact."""



ALERT_COLUMN = 14
FIRST_FIXTURE_ROW = 3
COLUMN_WIDTH = 245
MAX_FONT_SIZE = 11
MIN_FONT_SIZE = 6
# Carlito Bold glyph advances at 11pt/96dpi, embedded without a runtime font dependency.
_CHAR_WIDTHS = {' ': 3.316, '!': 4.777, '"': 6.431, '#': 7.305, '$': 7.434, '%': 10.692, '&': 10.334, "'": 3.423, '(': 4.569, ')': 4.569, '*': 7.305, '+': 7.305, ',': 3.781, '-': 4.49, '.': 3.917, '/': 6.302, '0': 7.434, '1': 7.434, '2': 7.434, '3': 7.434, '4': 7.434, '5': 7.434, '6': 7.434, '7': 7.434, '8': 7.434, '9': 7.434, ':': 4.046, ';': 4.046, '<': 7.305, '=': 7.305, '>': 7.305, '?': 6.796, '@': 13.177, 'A': 8.887, 'B': 8.221, 'C': 7.763, 'D': 9.245, 'E': 7.154, 'F': 6.732, 'G': 9.346, 'H': 9.253, 'I': 3.91, 'J': 4.855, 'K': 8.021, 'L': 6.202, 'M': 12.819, 'N': 9.661, 'O': 9.919, 'P': 7.806, 'Q': 10.062, 'R': 8.257, 'S': 6.932, 'T': 7.262, 'U': 9.575, 'V': 8.672, 'W': 13.292, 'X': 8.078, 'Y': 7.62, 'Z': 7.011, '[': 4.762, '\\': 6.302, ']': 4.762, '^': 7.305, '_': 7.305, '`': 4.404, 'a': 7.24, 'b': 7.87, 'c': 6.137, 'd': 7.87, 'e': 7.384, 'f': 4.641, 'g': 6.954, 'h': 7.87, 'i': 3.602, 'j': 3.745, 'k': 7.04, 'l': 3.602, 'm': 11.931, 'n': 7.87, 'o': 7.885, 'p': 7.87, 'q': 7.87, 'r': 5.214, 's': 5.851, 't': 5.085, 'u': 7.87, 'v': 6.939, 'w': 10.928, 'x': 6.739, 'y': 6.947, 'z': 5.829, '{': 5.042, '|': 6.968, '}': 5.042, '~': 7.305, 'Α': 8.887, 'Β': 8.221, 'Γ': 6.009, 'Δ': 8.472, 'Ε': 7.154, 'Ζ': 7.011, 'Η': 9.253, 'Θ': 9.919, 'Ι': 3.91, 'Κ': 8.021, 'Λ': 8.708, 'Μ': 12.819, 'Ν': 9.661, 'Ξ': 7.219, 'Ο': 9.919, 'Π': 9.253, 'Ρ': 7.806, '\u03a2': 7.434, 'Σ': 6.889, 'Τ': 7.262, 'Υ': 7.62, 'Φ': 11.752, 'Χ': 8.078, 'Ψ': 11.845, 'Ω': 9.983, '·': 3.925, '↑': 13.277}


def compact_alert(value):
    """Compatibility name: return the full original text, never an alias."""
    if not isinstance(value, str) or not value.strip() or value.startswith("#"):
        return None
    return value


def alert_number_format(value):
    """Show actual formula text; clear former literal-label number formats."""
    return {"type": "TEXT", "pattern": "@"}


def alert_font_size(value):
    label = compact_alert(value)
    if label is None:
        return MAX_FONT_SIZE
    width = sum(0 if char in "\ufe0e\ufe0f" else _CHAR_WIDTHS.get(char, 14.667)
                for char in label)
    available = COLUMN_WIDTH - 10
    return max(MIN_FONT_SIZE, min(MAX_FONT_SIZE,
               int(MAX_FONT_SIZE * available / max(1, width))))


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
    """Only O cell formats; never resize rows or alter neighboring columns."""
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
