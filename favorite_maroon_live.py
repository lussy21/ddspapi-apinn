"""Publish the three approved Maroon signals from actual recorded observations.

The entry ledger remains authoritative. An issued pick stays visible and counted,
like the existing latched goal signal, even if a later quote no longer qualifies.
No market data requests, retrospective qualification, or new sheet columns.
"""

from favorite_maroon_research import DEFAULT_PROFILE, evidence, fixture
from favorite_maroon80_research import PROFILE as MONEY_PROFILE
from favorite_maroon170_research import PROFILE as PRICE_PROFILE
from side_goal_alerts import active_expr

PROFILES = (DEFAULT_PROFILE, MONEY_PROFILE, PRICE_PROFILE)
LABELS = frozenset("🔔 " + profile.name for profile in PROFILES)
PREFIX = "=LET(maroonbase;"


def quoted(value):
    return '"' + str(value or "").replace('"', '""') + '"'


def base_formula(value):
    """Unwrap our one outer LET; repeated collector runs must not duplicate it."""
    text = str(value or "")
    if not text.startswith(PREFIX):
        return text if text.startswith("=") else "=" + quoted(text)
    depth, inside, index = 0, False, len(PREFIX)
    start = index
    while index < len(text):
        char = text[index]
        if char == '"':
            if inside and index + 1 < len(text) and text[index + 1] == '"':
                index += 2
                continue
            inside = not inside
        elif not inside:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == ";" and depth == 0:
                if not text[index:].startswith(";maroonextras;"):
                    raise ValueError("Unexpected Maroon live wrapper")
                return "=" + text[start:index]
        index += 1
    raise ValueError("Incomplete Maroon live wrapper")


def live_formula(base, source, row_number, profiles):
    """Join independently; the legacy E>=1.39 guard remains inside the base."""
    if not profiles:
        return base_formula(base)
    checks = [f'${column}{row_number}={quoted(source[index] if len(source) > index else "")}'
              for column, index in (("A", 0), ("B", 1), ("C", 2), ("D", 3), ("BY", 76))]
    picks = ";".join(f'IF({active_expr(profile.name)};{quoted("🔔 " + profile.name)};"")'
                     for profile in profiles)
    extras = f'IF(AND({";".join(checks)});TEXTJOIN(" | ";TRUE;{picks});"")'
    return (PREFIX + base_formula(base)[1:] + ";maroonextras;" + extras
            + ';TEXTJOIN(" | ";TRUE;maroonbase;maroonextras))')


def retain_maroon_below_legacy_floor(alert, eligible):
    """The existing opening floor is not part of any of the three new rules."""
    if eligible:
        return alert
    return " | ".join(part.strip() for part in str(alert or "").split("|")
                      if part.strip() in LABELS)


def refresh_live_alerts(spreadsheet, sheet, source_rows, now, first_row=1):
    """Publish issued entries only, preserving settled history and original O."""
    config = spreadsheet.worksheet("ALERT LEVELS").get("A2:E100", value_render_option="UNFORMATTED_VALUE")
    statuses = {str(row[0]).strip(): str(row[4]).strip().upper()
                for row in config if len(row) > 4}
    entries = {}
    for profile in PROFILES:
        if statuses.get(profile.name) != "ACTIVE":
            continue
        ledger = spreadsheet.worksheet(profile.sheet_name).get_all_values(value_render_option="UNFORMATTED_VALUE")
        if len(ledger) < 6 or ledger[5][:len(profile.headers)] != profile.headers:
            raise ValueError("Maroon live ledger header mismatch: " + profile.name)
        entries[profile.name] = {record[0]: record for record in ledger[6:]
                                 if len(record) > 18 and record[6]
                                 and str(record[0]).startswith(profile.key_prefix)}
    targets = []
    for index, source in enumerate(source_rows, start=first_row):
        profiles = []
        for profile in PROFILES:
            if profile.name not in entries:
                continue
            item = fixture(source, index, profile=profile)
            # Never rewrite the public record for a match that has started.
            if item is None or item["kickoff"] <= now or item["score"]:
                continue
            record = entries[profile.name].get(item["key"])
            if record and evidence(record).get("favorite_side") == item["side"]:
                profiles.append(profile)
        if profiles:
            targets.append((index, source, profiles))
    if not targets:
        print("FAV MAROON LIVE OK | active=" + str(len(entries)) + " | visible=0 | changed=0")
        return {"ok": True, "active": len(entries), "visible": 0, "changed": 0}
    previous = sheet.batch_get([f"O{index}" for index, _, _ in targets], value_render_option="FORMULA")
    if len(previous) != len(targets):
        raise ValueError("Incomplete Maroon public formula response")
    changes = []
    for (index, source, profiles), values in zip(targets, previous):
        old = values[0][0] if values and values[0] else ""
        updated = live_formula(old, source, index, profiles)
        if old != updated:
            changes.append({"range": f"O{index}", "values": [[updated]]})
    if changes:
        sheet.batch_update(changes, value_input_option="USER_ENTERED")
    print(f"FAV MAROON LIVE OK | active={len(entries)} | visible={len(targets)} | changed={len(changes)}")
    return {"ok": True, "active": len(entries), "visible": len(targets), "changed": len(changes)}
