"""Lineup Lens: official lineup validation and season-long start counting.

This module is deliberately source-agnostic and makes ZERO API calls.
Never turn missing historical data into invented non-starts.
"""
from collections import defaultdict
from datetime import datetime

class InvalidXI(ValueError):
    pass

def normalize_official(match, lineup, source_reference):
    if not isinstance(match,dict) or not isinstance(lineup,dict):
        raise InvalidXI("Missing match or lineup")
    if lineup.get("type") not in ("team_sheet","played") or lineup.get("confirmed") is not True:
        raise InvalidXI("Only confirmed official lineups qualify")
    if not isinstance(source_reference,str) or not source_reference.strip():
        raise InvalidXI("Source reference missing")
    for key,prefix in (("id","match_"),("season_id","season_"),("competition_id","competition_")):
        if not str(match.get(key,"")).startswith(prefix):
            raise InvalidXI("Invalid "+key)
    try: datetime.fromisoformat(match["utc_date"].replace("Z","+00:00"))
    except (KeyError,ValueError,AttributeError): raise InvalidXI("Invalid kickoff date")
    result={"match_id":match["id"],"season_id":match["season_id"],
            "competition_id":match["competition_id"],"kickoff_utc":match["utc_date"],
            "source":"Soccer Data","source_reference":source_reference,"teams":[]}
    for side in ("home","away"):
        expected=(match.get(side+"_team") or {}).get("id")
        team=lineup.get(side) or {}
        if not isinstance(expected,str) or not expected.startswith("team_") or team.get("id")!=expected:
            raise InvalidXI("Team ID mismatch: "+side)
        xi=team.get("starting_xi")
        if not isinstance(xi,list) or len(xi)!=11: raise InvalidXI("Need 11 starters: "+side)
        players=[]; seen=set()
        for player in xi:
            if not isinstance(player,dict) or not isinstance(player.get("id"),str) or not player["id"].startswith("player_"):
                raise InvalidXI("Invalid player")
            if player["id"] in seen: raise InvalidXI("Repeated player")
            seen.add(player["id"])
            players.append({"id":player["id"],"name":player.get("name") or player["id"],
                            "position":player.get("position"),"number":player.get("jersey_number")})
        result["teams"].append({"id":expected,"starters":players})
    if result["teams"][0]["id"]==result["teams"][1]["id"]: raise InvalidXI("Identical teams")
    return result

def season_starts(confirmed_records):
    """Key: (season, competition, team, player) -> starts, verified_games.

    Verified-games counts only official XI coverage. The app must separately
    compare it with every finished fixture before displaying a full-season ratio.
    Duplicate imports of one match never increase the count.
    """
    games=defaultdict(set); players=defaultdict(set)
    for record in confirmed_records:
        for team in record["teams"]:
            root=(record["season_id"],record["competition_id"],team["id"])
            games[root].add(record["match_id"])
            for p in team["starters"]:
                players[root+(p["id"],)].add(record["match_id"])
    return {key:{"starts":len(ids),"verified_games":len(games[key[:3]])}
            for key,ids in players.items()}
