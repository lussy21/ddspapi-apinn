import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

LEVELS_SHEET = "ALERT LEVELS"
PINNACLE_SHEET = "PINNACLE"
ATHENS = ZoneInfo("Europe/Athens")
REVIEW_DAYS = 15

# Current live-rule exclusions for the three older data-driven alerts.
OLDER_DATA_ALERT_EXCLUDED_PREFIXES = (
    "Finland - ", "Norway - ", "Sweden - ", "Denmark - ", "Scotland - ",
    "USA - ", "Brazil - ", "Argentina - ",
)


def _num(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _score(value):
    text = str(value or "").strip().replace("–", "-").replace("—", "-")
    parts = [x.strip() for x in text.split("-")]
    if len(parts) == 2 and all(x.isdigit() for x in parts):
        return int(parts[0]), int(parts[1])
    return None


def _allowed_scope(league):
    league = str(league or "").strip()
    if league.startswith(("USA - ", "Brazil - ", "Argentina - ")):
        return False
    if league.startswith("ΕΘΝΙΚΕΣ - "):
        return False
    if league == "Greece - Super League 2":
        return False
    return True


def _older_data_rule_scope(league):
    league = str(league or "").strip()
    return not league.startswith(OLDER_DATA_ALERT_EXCLUDED_PREFIXES)


def _favorite_won(row):
    if len(row) <= 15:
        return None
    parsed = _score(row[15])
    side = str(row[3] or "").strip().upper() if len(row) > 3 else ""
    if parsed is None or side not in ("H", "A"):
        return None
    home, away = parsed
    return home > away if side == "H" else away > home


def _core_alert(row):
    e = _num(row[4]) if len(row) > 4 else None
    l = _num(row[11]) if len(row) > 11 else None
    n = _num(row[13]) if len(row) > 13 else None
    if e is None or l is None or n is None:
        return ""

    # Must match the live IFS priority exactly.
    if 1.5 <= e <= 2.4 and l < 60 and n >= 50:
        return "ΔΥΝΑΤΟ ΚΟΝΤΡΑ"
    if 1.7 <= e <= 2.4 and l <= 70 and n >= 50 and (n - l) >= 10:
        return "ΔΥΝΑΤΟ ΚΟΝΤΡΑ (+10)"
    if 1.25 <= e <= 1.9 and l >= 90 and n >= 82:
        return "ΔΥΝΑΤΟ ΦΑΒΟΡΙ"
    if 1.5 <= e <= 2.4 and l <= 70 and n >= 50 and n >= l:
        return "ΚΟΝΤΡΑ"
    if 1.25 <= e <= 1.9 and l >= 80 and n >= 82:
        return "ΦΑΒΟΡΙ"
    if 1.5 <= e <= 2.4 and l < 75 and n >= 65 and n > l:
        return "WATCH ΚΟΝΤΡΑ"
    if 1.25 <= e <= 2.1 and l >= 80 and n >= 75:
        return "WATCH ΦΑΒΟΡΙ"
    return ""


def _fav_odds(row):
    for i in (6, 5, 4):
        value = _num(row[i]) if len(row) > i else None
        if value is not None and value > 1:
            return value
    return None


def _contra_odds(row):
    for i in (9, 8, 7):
        value = _num(row[i]) if len(row) > i else None
        if value is not None and value > 1:
            return value
    return None


def _matches(alert, row):
    e = _num(row[4]) if len(row) > 4 else None
    f90 = _num(row[5]) if len(row) > 5 else None
    g = _num(row[6]) if len(row) > 6 else None
    k = _num(row[10]) if len(row) > 10 else None
    l = _num(row[11]) if len(row) > 11 else None
    n = _num(row[13]) if len(row) > 13 else None
    t = _num(row[19]) if len(row) > 19 else None
    w = _num(row[22]) if len(row) > 22 else None
    bl = _num(row[63]) if len(row) > 63 else None
    bm = _num(row[64]) if len(row) > 64 else None
    league = str(row[0] or "").strip() if row else ""

    if alert in (
        "ΔΥΝΑΤΟ ΚΟΝΤΡΑ", "ΔΥΝΑΤΟ ΚΟΝΤΡΑ (+10)", "ΚΟΝΤΡΑ",
        "ΔΥΝΑΤΟ ΦΑΒΟΡΙ", "ΦΑΒΟΡΙ", "WATCH ΚΟΝΤΡΑ", "WATCH ΦΑΒΟΡΙ",
    ):
        return _core_alert(row) == alert

    if alert == "ΦΑΒΟΡΙ ΤΖΙΡΟΥ":
        return (
            _older_data_rule_scope(league)
            and e is not None and 1.2 <= e <= 1.5
            and bm is not None and bm >= 65
        )
    if alert == "ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ":
        return (
            _older_data_rule_scope(league)
            and e is not None and 1.2 <= e <= 1.7
            and n is not None and n >= 82
            and bm is not None and bm >= 65
        )
    if alert == "ΚΟΝΤΡΑ ΓΥΡΙΣΜΑΤΟΣ":
        return (
            _older_data_rule_scope(league)
            and e is not None and 1.6 <= e <= 2.1
            and f90 is not None and g is not None and f90 <= e and g >= f90
            and k is not None and w is not None and w > 0 and (k / w) >= 1.5
        )
    if alert == "ΦΑΒ 60+":
        return e is not None and e <= 1.7 and bm is not None and bm >= 60
    if alert == "ΦΑΒ 75+":
        return e is not None and e <= 1.7 and bm is not None and bm >= 75
    if alert == "ΤΖΙΡΟΣ ↑":
        return bl is not None and bl <= 75 and bm is not None and bm > 75
    if alert == "ΦΑΒΟΡΙ ΠΤΩΣΗ 2%":
        return (
            g is not None and 1.4 <= g <= 1.9
            and n is not None and n >= 75
            and f90 is not None and f90 > 0
            and g <= f90 * 0.98
        )
    if alert == "ΦΑΒΟΡΙ 84+P60":
        return (
            e is not None and 1.55 <= e <= 1.85
            and l is not None and l >= 84
            and bm is not None and bm >= 60
        )
    if alert == "ΦΑΒΟΡΙ ΤΖΙΡΟΥ 3X":
        return (
            g is not None and 1.65 <= g <= 1.90
            and k is not None and t is not None and t > 0 and (k / t) >= 3
            and f90 is not None and g <= f90
        )
    if alert == "ΦΑΒΟΡΙ SOFA+3X":
        return (
            g is not None and 1.65 <= g <= 2.05
            and n is not None and n >= 70
            and k is not None and t is not None and t > 0 and (k / t) >= 3
            and f90 is not None and g <= f90
        )
    return False


def _family(alert):
    return "CONTRA" if "ΚΟΝΤΡΑ" in str(alert).upper() else "FAVORITE"


def _wilson_lower(wins, total, z=1.281551565545):
    if total <= 0:
        return 0.0
    p = wins / total
    z2 = z * z
    return (
        p + z2 / (2 * total)
        - z * math.sqrt((p * (1 - p) + z2 / (4 * total)) / total)
    ) / (1 + z2 / total)


def _clip(value, lo=0.0, hi=1.0):
    return max(lo, min(hi, value))


def _metrics(alert, rows):
    family = _family(alert)
    picks = []

    for row in rows:
        if not row or not _allowed_scope(row[0] if row else ""):
            continue
        fav_won = _favorite_won(row)
        if fav_won is None or not _matches(alert, row):
            continue
        odds = _contra_odds(row) if family == "CONTRA" else _fav_odds(row)
        if odds is None or odds <= 1:
            continue
        picks.append({
            "win": (not fav_won) if family == "CONTRA" else fav_won,
            "odds": odds,
        })

    total = len(picks)
    wins = sum(1 for p in picks if p["win"])
    hit = wins / total if total else 0.0
    avg_odds = sum(p["odds"] for p in picks) / total if total else 0.0
    profit = sum((p["odds"] - 1) if p["win"] else -1 for p in picks)
    roi = profit / total if total else 0.0

    if total:
        break_even = sum(1 / p["odds"] for p in picks) / total
        conservative_edge = _wilson_lower(wins, total) - break_even
    else:
        conservative_edge = -1.0

    roi_score = 100 * _clip((roi + 0.10) / 0.60)
    edge_score = 100 * _clip((conservative_edge + 0.10) / 0.30)
    sample_score = 100 * _clip(total / 25.0)

    stability_score = 50.0
    if total >= 8:
        mid = total // 2
        halves = (picks[:mid], picks[mid:])
        half_metrics = []
        for part in halves:
            part_wins = sum(1 for p in part if p["win"])
            part_profit = sum((p["odds"] - 1) if p["win"] else -1 for p in part)
            half_metrics.append({
                "hit": part_wins / len(part),
                "roi": part_profit / len(part),
            })
        stability_score = 100 * _clip(
            1 - abs(half_metrics[0]["hit"] - half_metrics[1]["hit"]) * 1.5
        )
        if half_metrics[0]["roi"] < 0 or half_metrics[1]["roi"] < 0:
            stability_score = max(0.0, stability_score - 25)

    quality = (
        0.35 * roi_score
        + 0.30 * edge_score
        + 0.20 * sample_score
        + 0.15 * stability_score
    )

    return {
        "wins": wins,
        "total": total,
        "hit": hit,
        "avg_odds": avg_odds,
        "roi": roi,
        "score": quality,
    }


def _natural_level(family, m):
    n, hit, roi = m["total"], m["hit"], m["roi"]

    if family == "FAVORITE":
        if n >= 15 and hit >= 0.88 and roi >= 0.10:
            return 3
        if n >= 12 and hit >= 0.80 and roi >= 0.00:
            return 2
        if n >= 10 and hit >= 0.65 and roi >= 0.00:
            return 1
        return 0

    if n >= 20 and hit >= 0.85 and roi >= 0.20:
        return 3
    if n >= 12 and hit >= 0.75 and roi >= 0.15:
        return 2
    if n >= 10 and hit >= 0.60 and roi >= 0.00:
        return 1
    return 0


def _symbol(family, level):
    if family == "CONTRA":
        return {1: "🎯", 2: "⚡", 3: "💣"}.get(level, "")
    return {1: "🔷", 2: "💎", 3: "👑"}.get(level, "")


def _parse_iso_date(value):
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def run_level_review_if_due(spreadsheet, force=False):
    """
    Refresh alert metrics/suggestions on the 15-day review date.

    AUTO_APPLY is read from ALERT LEVELS!S2.
    It is intentionally FALSE before public launch. With AUTO_APPLY false,
    this function never changes live LEVEL/SYMBOL/STATUS.
    """
    try:
        levels = spreadsheet.worksheet(LEVELS_SHEET)
        pin = spreadsheet.worksheet(PINNACLE_SHEET)
    except Exception as exc:
        print("ALERT LEVEL REVIEW SKIP | missing_sheet |", repr(exc))
        return {"ok": False, "reason": "missing_sheet"}

    config = levels.get("A1:T100", value_render_option="UNFORMATTED_VALUE")
    if len(config) < 2:
        print("ALERT LEVEL REVIEW SKIP | empty_config")
        return {"ok": False, "reason": "empty_config"}

    today = datetime.now(ATHENS).date()
    auto_apply = bool(config[1][18]) if len(config[1]) > 18 else False

    due_dates = []
    for row in config[1:]:
        if not row or not str(row[0] or "").strip():
            continue
        next_review = _parse_iso_date(row[12] if len(row) > 12 else "")
        if next_review is not None:
            due_dates.append(next_review)

    if not force and due_dates and today < min(due_dates):
        print(
            "ALERT LEVEL REVIEW NOT DUE | next=",
            min(due_dates).isoformat(),
            "| auto_apply=",
            auto_apply,
        )
        return {"ok": True, "due": False, "next": min(due_dates).isoformat()}

    pin_rows = pin.get("A3:CC10000", value_render_option="FORMATTED_VALUE")
    next_date = today + timedelta(days=REVIEW_DAYS)
    batch = []
    changed = []

    for sheet_row, row in enumerate(config[1:], start=2):
        if not row:
            continue
        alert = str(row[0] or "").strip()
        if not alert:
            continue
        family = str(row[1] or _family(alert)).strip().upper()
        status = str(row[4] or "").strip().upper() if len(row) > 4 else ""
        current_level = int(_num(row[2]) or 0)

        m = _metrics(alert, pin_rows)

        if status == "ADMIN_ONLY":
            target = 0
            suggested_symbol = ""
            state = "ADMIN_ONLY"
        else:
            target = _natural_level(family, m)
            suggested_symbol = _symbol(family, target)
            if target > current_level:
                state = "UP_CANDIDATE"
            elif target < current_level:
                state = "DOWN_CANDIDATE"
            else:
                state = "STAY" if target > 0 else "TEST"

        # Metrics F:K, review dates L:M, suggestions P:R.
        values = [
            round(m["score"], 1),
            m["wins"],
            m["total"],
            round(m["hit"], 4),
            round(m["avg_odds"], 4),
            round(m["roi"], 4),
            today.isoformat(),
            next_date.isoformat(),
        ]
        levels.update(
            range_name=f"F{sheet_row}:M{sheet_row}",
            values=[values],
            raw=True,
        )
        levels.update(
            range_name=f"P{sheet_row}:R{sheet_row}",
            values=[[target, suggested_symbol, state]],
            raw=True,
        )

        if not auto_apply or status == "ADMIN_ONLY":
            continue

        new_level = current_level
        new_status = status
        if target > current_level:
            new_level = min(3, current_level + 1)
        elif target < current_level:
            new_level = max(0, current_level - 1)

        if new_level <= 0:
            new_status = "TEST"
        elif status == "TEST" or status == "":
            new_status = "ACTIVE"

        if new_level != current_level or new_status != status:
            new_symbol = _symbol(family, new_level)
            levels.update(
                range_name=f"C{sheet_row}:E{sheet_row}",
                values=[[new_level, new_symbol, new_status]],
                raw=True,
            )
            changed.append(
                f"{alert}:{current_level}->{new_level}"
            )

    print(
        "ALERT LEVEL REVIEW OK | "
        f"auto_apply={auto_apply} | changes={len(changed)} | "
        f"next={next_date.isoformat()}"
    )
    return {
        "ok": True,
        "due": True,
        "auto_apply": auto_apply,
        "changes": changed,
        "next": next_date.isoformat(),
    }
