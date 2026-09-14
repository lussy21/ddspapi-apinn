import os
import json
import time
import base64
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
import google.auth
from google.oauth2.service_account import Credentials


SPREADSHEET_ID = "1cabkyN1Nl74fIi-IhZ6Xxsbx2MeccjXHM3TSAvy-vzM"
SHEET_NAME = "PINNACLE"
LOG_SHEET_NAME = "ALERT LOG"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# -------------------------------------------------
# GOOGLE LOGIN
# -------------------------------------------------

def get_credentials():

    possible_names = (
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        "GOOGLE_CREDENTIALS_JSON",
        "GOOGLE_CREDENTIALS",
        "GCP_CREDENTIALS",
        "SERVICE_ACCOUNT_JSON",
        "GOOGLE_CREDS",
    )

    candidates = []

    for name in possible_names:
        value = os.getenv(name)

        if value:
            candidates.append(value)

    for key, value in os.environ.items():

        if not value:
            continue

        upper_key = key.upper()

        if any(
            word in upper_key
            for word in (
                "GOOGLE",
                "GCP",
                "CREDENTIAL",
                "SERVICE_ACCOUNT",
            )
        ):
            if value not in candidates:
                candidates.append(value)

    for value in candidates:

        value = value.strip()

        # JSON κατευθείαν
        if value.startswith("{"):

            try:

                info = json.loads(value)

                if (
                    "client_email" in info
                    and "private_key" in info
                ):
                    return Credentials.from_service_account_info(
                        info,
                        scopes=SCOPES,
                    )

            except Exception:
                pass

        # path σε αρχείο
        if os.path.isfile(value):

            try:

                return Credentials.from_service_account_file(
                    value,
                    scopes=SCOPES,
                )

            except Exception:
                pass

        # base64 JSON
        try:

            decoded = base64.b64decode(
                value
            ).decode("utf-8")

            info = json.loads(decoded)

            if (
                "client_email" in info
                and "private_key" in info
            ):
                return Credentials.from_service_account_info(
                    info,
                    scopes=SCOPES,
                )

        except Exception:
            pass

    # γνωστά paths
    possible_files = (
        "credentials.json",
        "service_account.json",
        "google_credentials.json",
        "/etc/secrets/credentials.json",
        "/etc/secrets/google-credentials.json",
    )

    for path in possible_files:

        if os.path.isfile(path):

            return Credentials.from_service_account_file(
                path,
                scopes=SCOPES,
            )

    # τελευταίο fallback
    creds, _ = google.auth.default(
        scopes=SCOPES
    )

    return creds


# -------------------------------------------------
# HELPERS
# -------------------------------------------------

def now_athens():

    return datetime.now(
        ZoneInfo("Europe/Athens")
    ).strftime("%d/%m/%Y %H:%M:%S")


def col_letter(number):

    result = ""

    while number:

        number, remainder = divmod(
            number - 1,
            26,
        )

        result = (
            chr(65 + remainder)
            + result
        )

    return result


def column_number(letter):

    result = 0

    for char in letter:

        result = (
            result * 26
            + ord(char)
            - 64
        )

    return result


FRIENDLY_NAMES = {

    "E": "Open Fav",
    "F": "90m Fav",
    "G": "Current Fav",

    "H": "Open Contra",
    "I": "90m Contra",
    "J": "Current Contra",

    "K": "Τζίρος",
    "L": "Fav%",
    "M": "Contra%",
    "N": "Sofa%",

    "T": "Arbworld 11:00",
    "U": "Arbworld 11:00",
    "V": "Arbworld 11:00",

    "W": "Arbworld 90m",
    "X": "Arbworld 90m",
    "Y": "Arbworld 90m",

    "AZ": "90m Fav",
    "BA": "90m Contra",
}


def pretty_name(letter):

    return FRIENDLY_NAMES.get(
        letter,
        letter,
    )


def referenced_columns(formula):

    if not formula:
        return []

    matches = re.findall(
        r"\$?([A-Z]{1,2})\$?\d+",
        formula.upper(),
    )

    unique = []

    for item in matches:

        if item not in unique:
            unique.append(item)

    return unique


def make_snapshot(row, formula):

    values = {}

    # A έως BA
    for index in range(53):

        letter = col_letter(
            index + 1
        )

        if index < len(row):
            values[letter] = str(
                row[index]
            ).strip()
        else:
            values[letter] = ""

    return {
        "time": now_athens(),
        "formula": formula or "",
        "references": referenced_columns(
            formula
        ),
        "values": values,
    }


def compact_open_text(snapshot):

    refs = snapshot.get(
        "references",
        [],
    )

    values = snapshot.get(
        "values",
        {},
    )

    important = []

    # Αν η φόρμουλα χρησιμοποιεί συγκεκριμένα
    # πεδία, δείχνουμε αυτά.
    for letter in refs:

        value = values.get(
            letter,
            "",
        )

        important.append(
            f"{pretty_name(letter)}={value}"
        )

    # Αν για οποιονδήποτε λόγο
    # δεν βρέθηκαν references
    if not important:

        for letter in (
            "E",
            "G",
            "L",
            "N",
        ):

            value = values.get(
                letter,
                "",
            )

            important.append(
                f"{pretty_name(letter)}={value}"
            )

    return (
        f"{snapshot['time']} | "
        + " | ".join(important)
    )


def compare_snapshots(
    old_snapshot,
    new_snapshot,
):

    messages = []

    old_formula = old_snapshot.get(
        "formula",
        "",
    )

    new_formula = new_snapshot.get(
        "formula",
        "",
    )

    # Αν αλλάξαμε εμείς τον κανόνα
    if old_formula != new_formula:

        messages.append(
            "ΑΛΛΑΞΕ Η ΦΟΡΜΟΥΛΑ / Ο ΚΑΝΟΝΑΣ ΤΟΥ ALERT"
        )

    old_refs = old_snapshot.get(
        "references",
        [],
    )

    new_refs = new_snapshot.get(
        "references",
        [],
    )

    # Κοιτάμε όλες τις στήλες που
    # χρησιμοποιούσε είτε ο παλιός
    # είτε ο νέος κανόνας.
    refs = []

    for ref in (
        old_refs
        + new_refs
    ):

        if ref not in refs:
            refs.append(ref)

    refs.sort(
        key=column_number
    )

    old_values = old_snapshot.get(
        "values",
        {},
    )

    new_values = new_snapshot.get(
        "values",
        {},
    )

    changes = []

    for letter in refs:

        old_value = str(
            old_values.get(
                letter,
                "",
            )
        ).strip()

        new_value = str(
            new_values.get(
                letter,
                "",
            )
        ).strip()

        if old_value != new_value:

            changes.append(
                f"{pretty_name(letter)}: "
                f"{old_value or '-'} → "
                f"{new_value or '-'}"
            )

    if changes:

        messages.extend(
            changes
        )

    if not messages:

        messages.append(
            "Το alert δεν επιστρέφεται πλέον από τη στήλη O, "
            "χωρίς εμφανή αλλαγή στα πεδία που χρησιμοποιεί η φόρμουλα."
        )

    return " | ".join(
        messages
    )


# -------------------------------------------------
# ALERT LOG SHEET
# -------------------------------------------------

def get_log_sheet(spreadsheet):

    try:

        ws = spreadsheet.worksheet(
            LOG_SHEET_NAME
        )

    except gspread.WorksheetNotFound:

        ws = spreadsheet.add_worksheet(
            title=LOG_SHEET_NAME,
            rows=3000,
            cols=10,
        )

        ws.update(
            "A1:J1",
            [[
                "TIME",
                "KEY",
                "ROW",
                "LEAGUE",
                "MATCH",
                "EVENT",
                "ALERT",
                "DETAILS",
                "SNAPSHOT_JSON",
                "FORMULA",
            ]],
        )

    return ws


def load_baselines(log_ws):

    rows = log_ws.get_all_values()

    baselines = {}

    if len(rows) <= 1:
        return baselines

    for row in rows[1:]:

        row = row + [""] * (
            10 - len(row)
        )

        key = row[1].strip()
        event = row[5].strip()
        snapshot_json = row[8].strip()

        if not key:
            continue

        if event in (
            "ΑΝΟΙΞΕ",
            "ΑΛΛΑΞΕ ALERT",
            "ΑΛΛΑΞΕ ΚΑΝΟΝΑΣ",
            "ΣΥΓΧΡΟΝΙΣΜΟΣ",
        ):

            try:

                snapshot = json.loads(
                    snapshot_json
                )

                baselines[key] = {
                    "alert": row[6].strip(),
                    "snapshot": snapshot,
                }

            except Exception:
                pass

        elif event == "ΕΦΥΓΕ":

            baselines.pop(
                key,
                None,
            )

    return baselines


# -------------------------------------------------
# MAIN
# -------------------------------------------------

def main():

    # Περιμένουμε λίγο ώστε η Google Sheet
    # να προλάβει να υπολογίσει τις φόρμουλες.
    time.sleep(3)

    credentials = get_credentials()

    client = gspread.authorize(
        credentials
    )

    spreadsheet = client.open_by_key(
        SPREADSHEET_ID
    )

    ws = spreadsheet.worksheet(
        SHEET_NAME
    )

    log_ws = get_log_sheet(
        spreadsheet
    )

    baselines = load_baselines(
        log_ws
    )

    # Κανονικές τιμές
    rows = ws.get(
        "A3:BE1000",
        value_render_option="FORMATTED_VALUE",
    )

    # Πραγματική φόρμουλα της O
    formulas = ws.get(
        "O3:O1000",
        value_render_option="FORMULA",
    )

    sheet_updates = []
    log_rows = []

    for list_index, row in enumerate(
        rows
    ):

        sheet_row = (
            list_index + 3
        )

        row = row + [""] * (
            57 - len(row)
        )

        formula = ""

        if list_index < len(formulas):

            if formulas[list_index]:

                formula = str(
                    formulas[list_index][0]
                ).strip()

        league = str(
            row[0]
        ).strip()

        home = str(
            row[1]
        ).strip()

        away = str(
            row[2]
        ).strip()

        alert = str(
            row[14]
        ).strip()

        event_id = str(
            row[17]
        ).strip()

        # Αν υπάρχει event ID το χρησιμοποιούμε.
        # Αλλιώς φτιάχνουμε σταθερό κλειδί
        # από το ματς.
        if event_id:

            key = event_id

        else:

            key = (
                f"{league}|"
                f"{home}|"
                f"{away}"
            )

        if not home and not away:
            continue

        old_status = str(
            row[53]
        ).strip()

        old_alert = str(
            row[54]
        ).strip()

        old_open_text = str(
            row[55]
        ).strip()

        old_active = (
            "ΕΝΕΡΓ" in
            old_status.upper()
        )

        snapshot = make_snapshot(
            row,
            formula,
        )

        baseline = baselines.get(
            key
        )


        # =========================================
        # 1. ΝΕΟ ALERT
        # =========================================

        if alert and not old_active:

            open_text = compact_open_text(
                snapshot
            )

            sheet_updates.append({
                "range": (
                    f"BB{sheet_row}:BE{sheet_row}"
                ),
                "values": [[
                    "ΕΝΕΡΓΟ",
                    alert,
                    open_text,
                    "",
                ]],
            })

            log_rows.append([
                now_athens(),
                key,
                sheet_row,
                league,
                f"{home} - {away}",
                "ΑΝΟΙΞΕ",
                alert,
                open_text,
                json.dumps(
                    snapshot,
                    ensure_ascii=False,
                ),
                formula,
            ])

            baselines[key] = {
                "alert": alert,
                "snapshot": snapshot,
            }

            continue


        # =========================================
        # 2. ALERT ΑΛΛΑΞΕ ΤΥΠΟ
        # π.χ ΚΟΝΤΡΑ -> ΔΥΝΑΤΟ ΚΟΝΤΡΑ
        # =========================================

        if (
            alert
            and old_active
            and old_alert != alert
        ):

            open_text = compact_open_text(
                snapshot
            )

            detail = (
                f"{old_alert} → {alert}"
            )

            sheet_updates.append({
                "range": (
                    f"BB{sheet_row}:BE{sheet_row}"
                ),
                "values": [[
                    "ΕΝΕΡΓΟ",
                    alert,
                    open_text,
                    detail,
                ]],
            })

            log_rows.append([
                now_athens(),
                key,
                sheet_row,
                league,
                f"{home} - {away}",
                "ΑΛΛΑΞΕ ALERT",
                alert,
                detail,
                json.dumps(
                    snapshot,
                    ensure_ascii=False,
                ),
                formula,
            ])

            baselines[key] = {
                "alert": alert,
                "snapshot": snapshot,
            }

            continue


        # =========================================
        # 3. ALERT ΠΑΡΑΜΕΝΕΙ ΙΔΙΟ
        # ΑΛΛΑ ΕΜΕΙΣ ΑΛΛΑΞΑΜΕ ΤΗ ΦΟΡΜΟΥΛΑ
        # =========================================

        if (
            alert
            and old_active
            and old_alert == alert
        ):

            # Αν είναι η πρώτη φορά που
            # τρέχει το history
            if baseline is None:

                log_rows.append([
                    now_athens(),
                    key,
                    sheet_row,
                    league,
                    f"{home} - {away}",
                    "ΣΥΓΧΡΟΝΙΣΜΟΣ",
                    alert,
                    "Το history ξεκίνησε ενώ το alert ήταν ήδη ενεργό.",
                    json.dumps(
                        snapshot,
                        ensure_ascii=False,
                    ),
                    formula,
                ])

                baselines[key] = {
                    "alert": alert,
                    "snapshot": snapshot,
                }

                continue

            old_formula = (
                baseline[
                    "snapshot"
                ].get(
                    "formula",
                    "",
                )
            )

            if old_formula != formula:

                detail = (
                    "Άλλαξε η φόρμουλα του Alert "
                    "ενώ το Alert παρέμεινε ενεργό."
                )

                log_rows.append([
                    now_athens(),
                    key,
                    sheet_row,
                    league,
                    f"{home} - {away}",
                    "ΑΛΛΑΞΕ ΚΑΝΟΝΑΣ",
                    alert,
                    detail,
                    json.dumps(
                        snapshot,
                        ensure_ascii=False,
                    ),
                    formula,
                ])

                baselines[key] = {
                    "alert": alert,
                    "snapshot": snapshot,
                }

            continue


        # =========================================
        # 4. ALERT ΕΦΥΓΕ
        # =========================================

        if (
            not alert
            and old_active
        ):

            if baseline:

                reason = compare_snapshots(
                    baseline[
                        "snapshot"
                    ],
                    snapshot,
                )

            else:

                reason = (
                    "Το alert έφυγε. "
                    "Δεν υπήρχε παλιό machine snapshot "
                    "για σύγκριση."
                )

            sheet_updates.append({
                "range": (
                    f"BB{sheet_row}:BE{sheet_row}"
                ),
                "values": [[
                    "ΕΦΥΓΕ",
                    old_alert,
                    old_open_text,
                    reason,
                ]],
            })

            log_rows.append([
                now_athens(),
                key,
                sheet_row,
                league,
                f"{home} - {away}",
                "ΕΦΥΓΕ",
                old_alert,
                reason,
                json.dumps(
                    snapshot,
                    ensure_ascii=False,
                ),
                formula,
            ])

            baselines.pop(
                key,
                None,
            )

            continue


    # -------------------------------------------------
    # ΓΡΑΨΙΜΟ PINNACLE
    # -------------------------------------------------

    if sheet_updates:

        ws.batch_update(
            sheet_updates,
            raw=False,
        )


    # -------------------------------------------------
    # ΓΡΑΨΙΜΟ ALERT LOG
    # -------------------------------------------------

    if log_rows:

        log_ws.append_rows(
            log_rows,
            value_input_option="RAW",
        )


    print(
        "alert_history OK | "
        f"sheet_updates={len(sheet_updates)} | "
        f"log_events={len(log_rows)}"
    )


# -------------------------------------------------
# SAFE RUN
# -------------------------------------------------

if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        # Αν χαλάσει μόνο το ιστορικό,
        # δεν θέλουμε να χαλάσει
        # το βασικό πρόγραμμα.
        print(
            "alert_history ERROR | "
            f"{type(exc).__name__}: "
            f"{exc}"
        )
