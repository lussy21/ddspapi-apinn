"""Domestic starting appearances for European XIs, from the existing archive only."""
from datetime import timedelta
from zoneinfo import ZoneInfo
import archive_daily as archive
import archive_results

EUROPE={"UCL","UEL","UECL"}

def domestic_stats(db, team, kickoff):
    rows=db.execute("""SELECT DISTINCT m.competition_code,t.team_id
        FROM archive_matches m JOIN archive_teams t ON t.team_id IN (m.home_team_id,m.away_team_id)
        WHERE m.season_year=2026 AND m.competition_code NOT IN ('UCL','UEL','UECL')
        AND (t.team_id=%s OR EXISTS(SELECT 1 FROM archive_source_links l
            WHERE l.competition_code=m.competition_code AND l.kind='team'
            AND l.source_id=%s AND l.canonical_id=t.team_id))""",(team["id"],team["id"])).fetchall()
    if len(rows)!=1:
        return {"league":None,"played":None,"complete":False,"starts":{},"wins":{},"baseline":None}
    league,tid=rows[0]["competition_code"],rows[0]["team_id"]
    links=archive.get_links(db,league)
    cutoff=kickoff.astimezone(ZoneInfo(archive.MODULES[league][1])).date()-timedelta(days=1)
    state=db.execute("SELECT seeded,checked_through FROM archive_daily_state WHERE competition_code=%s",(league,)).fetchone()
    complete=bool(state and state["seeded"] and state["checked_through"]>=cutoff)
    played=db.execute("""SELECT count(*)::int n FROM archive_matches
        WHERE competition_code=%s AND season_year=2026 AND (home_team_id=%s OR away_team_id=%s)
        AND kickoff_utc<%s""",(league,tid,tid,kickoff)).fetchone()["n"]
    hist={r["player_id"]:r for r in db.execute("""SELECT s.player_id,p.player_name,count(*)::int starts
        FROM archive_starters s JOIN archive_matches m USING(match_id) JOIN archive_players p USING(player_id)
        WHERE m.competition_code=%s AND m.season_year=2026 AND s.team_id=%s AND m.kickoff_utc<%s
        GROUP BY s.player_id,p.player_name""",(league,tid,kickoff)).fetchall()}
    starts={}
    wins={}
    results=archive_results.history(db,league,tid,kickoff)
    for p in team["players"]:
        pid,name=p["player_id"],p["player_name"]
        if pid in links["blocked_player"]:
            continue
        cid=links["player"].get(pid,pid) if league in archive.MIXED else pid
        if cid in hist:
            if archive.compatible(hist[cid]["player_name"],name):
                starts[pid]=hist[cid]["starts"]
                wins[pid]=archive_results.player_stat(results,cid,starts[pid])
        elif (league not in archive.MIXED or pid in links["player"]) and not any(archive.compatible(r["player_name"],name) for r in hist.values()):
            # An absent, positively identified player has zero archived starts.
            # Unlinked mixed-source players remain unknown, never guessed by name.
            starts[pid]=0
    return {"league":league,"played":played if played else None,"complete":complete and bool(played),"starts":starts,"wins":wins,"baseline":archive_results.team_totals(db,league,tid,kickoff)}
