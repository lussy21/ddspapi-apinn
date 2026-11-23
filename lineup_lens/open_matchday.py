"""Free daily fixture discovery for *private, non-commercial* Lineup Lens research.

Source: open-matchday by its contributors, published CSV under non-commercial
attribution terms: https://github.com/oladeeayo/open-matchday

Fixtures are NOT lineups. Times are kept raw: upstream uses a fixed CET
convention and does not provide an unambiguous timezone offset per fixture.
No calls to Soccer Data or betting APIs. This adapter does NOT write to Neon.
"""
import csv
import io
import re
from datetime import date
from urllib.parse import quote

import requests

BASE = "https://raw.githubusercontent.com/oladeeayo/open-matchday/master/data"
SOURCE = "https://github.com/oladeeayo/open-matchday"
LEAGUES = {
    "england": ("ENG_1_premier-league", "Premier League"),
    "italy": ("ITA_1_serie-a", "Serie A"),
    "spain": ("ESP_1_la-liga", "La Liga"),
    "germany": ("GER_1_bundesliga", "Bundesliga"),
    "france": ("FRA_1_ligue-1", "Ligue 1"),
    "netherlands": ("NED_1_eredivisie", "Eredivisie"),
    "portugal": ("POR_1_primeira-liga", "Primeira Liga"),
    "belgium": ("BEL_1_pro-league", "Belgian Pro League"),
    "turkey": ("TUR_1_super-lig", "Süper Lig"),
    "greece": ("GRE_1_super-league", "Super League Greece"),
    "champions-league": ("UEFA_1_champions-league", "Champions League"),
}
SEASON = "2627"
MAX_CSV_BYTES = 400_000


class FixtureSourceProblem(Exception):
    pass


def parse_fixture_csv(raw: str, on_day: str, league: str) -> list[dict]:
    """Turn a 2026/27 CSV into verified-format records without inventing IDs."""
    if league not in LEAGUES:
        raise FixtureSourceProblem("Unknown competition")
    try:
        date.fromisoformat(on_day)
    except (TypeError, ValueError) as exc:
        raise FixtureSourceProblem("Invalid date") from exc
    if len(raw.encode("utf-8")) > MAX_CSV_BYTES:
        raise FixtureSourceProblem("Fixture file unexpectedly large")
    rows = csv.DictReader(io.StringIO(raw))
    if not set(("date", "time", "home", "away")).issubset(set(rows.fieldnames or [])):
        raise FixtureSourceProblem("Missing required fixture columns")
    result=[]
    for row in rows:
        if row.get("date") != on_day:
            continue
        home,away=(row.get("home") or "").strip(),(row.get("away") or "").strip()
        source_time=(row.get("time") or "").strip()
        if not home or not away or home==away:
            continue
        if source_time and not re.fullmatch(r"\d{2}:\d{2}", source_time):
            source_time=""
        result.append({
            "league":league,
            "competition":LEAGUES[league][1],
            "day":on_day,
            "kickoff_source_time":source_time or None,
            "home":home,"away":away,
            "source":"open-matchday",
            "source_url":SOURCE,
            "confirmed_lineup":False,
            "has_lineup_data":False,
        })
    return result


def fetch_day(on_day: str, selected: tuple[str,...]=("england","italy"), *, get=None) -> dict:
    try:
        date.fromisoformat(on_day)
    except (TypeError, ValueError) as exc:
        raise FixtureSourceProblem("Invalid date") from exc
    if len(selected)>11 or any(k not in LEAGUES for k in selected):
        raise FixtureSourceProblem("Invalid league selection")
    get = get or requests.get
    data=[]
    unavailable={}
    for league in dict.fromkeys(selected):
        folder,_=LEAGUES[league]
        url=f"{BASE}/{quote(folder)}/fixtures_{SEASON}.csv"
        try:
            res=get(url,timeout=12,headers={"User-Agent":"LineupLens-Personal-Research/1.0"})
            res.raise_for_status()
            if len(res.content)>MAX_CSV_BYTES:
                raise FixtureSourceProblem("Fixture file exceeds allowed size")
            records=parse_fixture_csv(res.text,on_day,league)
            data.extend(records)
        except (requests.RequestException, FixtureSourceProblem, UnicodeError) as exc:
            unavailable[league]=type(exc).__name__
    return {
        "date":on_day, "fixtures":data,"count":len(data),
        "attempted_leagues":list(dict.fromkeys(selected)),
        "unavailable_leagues":unavailable,
        "source":SOURCE,
        "non_commercial_only":True,
        "disclaimer":"Daily fixture discovery only; not a live feed, not predicted or confirmed lineups.",
        "timezone_note":"Source times are in its published fixed CET convention; check the official kickoff before converting.",
    }
