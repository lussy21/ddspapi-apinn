"""Independent goal signals beside the existing primary market; no network I/O."""

import json
import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

START_DAY = "2026-10-24"
LEGACY_KEY = "🔔 OVER 1.5"
LEGACY_DISPLAY = "🔔 OVER 1.5 (ΚΟΝΤΡΑ)"
FLOW_DISPLAY = "🔔 OVER 1.5 (ΡΟΗ)"
FLOW_CONFIG = "OVER 1.5 ΡΟΗ"
FLOW_LEAGUES = frozenset({
    "UEFA - Champions League", "UEFA - Europa League", "UEFA - Conference League",
    "Netherlands - Eredivisie", "Finland - Veikkausliiga", "Scotland - Premiership",
    "Greece - Super League", "Sweden - Allsvenskan", "Italy - Serie A",
    "Spain - La Liga", "Belgium - Pro League", "Turkey - Super League",
    "Germany - Bundesliga", "France - Ligue 1", "Denmark - Superliga",
    "Norway - Eliteserien", "England - Premier League",
})


def is_goal_alert(text):
    return bool(re.match(r"^🔔\s*OVER\s+1[.,]5\b", str(text or "").strip()))


def has_legacy_over(text):
    return any(part.strip().split(" · ", 1)[0] in (LEGACY_KEY, LEGACY_DISPLAY)
               for part in str(text or "").split("|"))


def primary_without_goals(expression, row_number):
    """Remove only goal helpers from the primary hierarchy, before Contra gating."""
    for col in ("BG", "BH"):
        old = f'AND(${col}{row_number}<>"";'
        new = old + f'NOT(REGEXMATCH(TO_TEXT(${col}{row_number});"^🔔 OVER 1[.]5"));'
        if old not in expression:
            raise ValueError(f"Missing primary helper {col}")
        expression = expression.replace(old, new, 1)
    return expression


def active_expr(config):
    return ('IFERROR(INDEX(\'ALERT LEVELS\'!$E$2:$E$100;'
            f'MATCH("{config}";\'ALERT LEVELS\'!$A$2:$A$100;0));'
            '"RESEARCH_ONLY")="ACTIVE"')


def side_goal_formula(primary_expression, row_number):
    r = row_number
    return (
        f'=IF(AND(ISNUMBER($E{r});$E{r}>=1,39);'
        f'LET(pa;{primary_expression};'
        f'TEXTJOIN(" | ";TRUE;'
        f'IF(pa<>"";pa&IF(AND($BX{r}<>"";REGEXMATCH(TO_TEXT($BX{r});"/10"));'
        f'" · "&IFERROR(LEFT($BX{r};FIND(" · ";$BX{r})-1);$BX{r});"");"");'
        f'IF(AND({active_expr("OVER 1.5")};'
        f'OR($BG{r}="{LEGACY_KEY}";$BH{r}="{LEGACY_KEY}"));"{LEGACY_DISPLAY}";"");'
        f'IF({active_expr(FLOW_CONFIG)};$CE{r};"")));"")'
    )


def primary_success_formula(row_number=3):
    """A side goal must never mark a losing primary 1X2 market green."""
    r = row_number
    return (
        '=IFERROR(LET(head;TRIM(INDEX(SPLIT(TO_TEXT('
        f'$O{r});"|");1;1));scoretext;TO_TEXT($P{r});'
        'homegoals;VALUE(REGEXEXTRACT(scoretext;"^[ ]*([0-9]+)[ ]*-"));'
        'awaygoals;VALUE(REGEXEXTRACT(scoretext;"-[ ]*([0-9]+)[ ]*$"));'
        'IF(REGEXMATCH(head;"OVER 1[.,]5");homegoals+awaygoals>=2;'
        'OR(AND(REGEXMATCH(head;"ΚΟΝΤΡΑ");'
        f'OR(AND($D{r}="H";homegoals<=awaygoals);AND($D{r}="A";homegoals>=awaygoals)));'
        'AND(REGEXMATCH(head;"ΦΑΒΟΡΙ|ΦΑΒ 60|ΦΑΒ 75|ΤΖΙΡΟΣ ↑");'
        f'OR(AND($D{r}="H";homegoals>awaygoals);AND($D{r}="A";homegoals<awaygoals))))));FALSE)'
    )


def _cell(row, index):
    return row[index] if index < len(row) else ""


def _number(value, turnover=False):
    if isinstance(value, bool) or value is None or value == "":
        return math.nan
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("%", "").replace("\u00a0", "").replace(" ", "").strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif turnover and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return math.nan


def flow_evidence(row, now):
    """Frozen research rule at an actual observed 90..5 minute pre-match update."""
    if _cell(row, 0) not in FLOW_LEAGUES or _cell(row, 3) not in ("H", "A"):
        return None
    if str(_cell(row, 15)).strip():
        return None
    try:
        kickoff = datetime.fromisoformat(str(_cell(row, 76)))
        if kickoff.tzinfo is None or now.tzinfo is None:
            return None
        minutes = (kickoff - now).total_seconds() / 60
    except (TypeError, ValueError):
        return None
    if kickoff.date().isoformat() < START_DAY or not 5 <= minutes <= 90:
        return None
    e, f, g, k, l, t, u = [
        _number(_cell(row, i), i in (10, 19)) for i in (4, 5, 6, 10, 11, 19, 20)
    ]
    if not all(math.isfinite(x) for x in (e, f, g, k, l, t, u)):
        return None
    if e < 1.39 or f <= 0 or g <= 0 or not k > t > 0 or not (0 <= l <= 100 and 0 <= u <= 100):
        return None
    incremental = (k * l - t * u) / (k - t)
    drift = (f / g - 1) * 100
    if not (80 <= incremental <= 100 and drift <= 5):
        return None
    return {"rule": "c4eb752088f4", "market": FLOW_DISPLAY,
            "asof": now.astimezone(ZoneInfo("Europe/Athens")).isoformat(),
            "kickoff": kickoff.isoformat(), "event_id": str(_cell(row, 17)),
            "fixture": [str(_cell(row, i)) for i in (0, 1, 2, 3)],
            "new_money11": incremental, "odds_drop90": drift,
            "minutes_before": minutes,
            "values": {chr(65 + i): _cell(row, i) for i in range(25)}}


def freshly_updated_rows(updates):
    odds, turnover = set(), set()
    for update in updates:
        address = update["range"]
        match = re.fullmatch(r"G(\d+)", address)
        if match:
            odds.add(int(match[1]))
        match = re.fullmatch(r"K(\d+):M\d+", address)
        if match:
            turnover.add(int(match[1]))
    return odds & turnover


def collect_flow_updates(rows, now, fresh_rows=None):
    """Latch first real opening once, with timestamp and exact input evidence.

    Later market movement cannot erase an observed opening or fabricate old ones.
    A reused row must never inherit another fixture's latch.
    """
    updates = []
    for number, row in enumerate(rows[2:], 3):
        kickoff = str(_cell(row, 76))
        if kickoff[:10] < START_DAY or str(_cell(row, 15)).strip():
            continue
        existing = str(_cell(row, 82))
        if existing:
            try:
                old = json.loads(str(_cell(row, 84)))
                same = (old["event_id"] == str(_cell(row, 17))
                        and old["fixture"] == [str(_cell(row, i)) for i in (0, 1, 2, 3)]
                        and old["kickoff"] == kickoff)
            except (KeyError, TypeError, ValueError):
                same = False
            if same:
                continue
            updates.append({"range": f"CE{number}:CG{number}", "values": [["", "", ""]]})
        if fresh_rows is not None and number not in fresh_rows:
            continue
        evidence = flow_evidence(row, now)
        if evidence:
            updates.append({"range": f"CE{number}:CG{number}", "values": [[
                FLOW_DISPLAY, evidence["asof"], json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
            ]]})
    return updates
