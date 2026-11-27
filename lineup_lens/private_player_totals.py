"""Read-only, source-separated player totals as of selected fixture.
Never uses later matches or counts missing metrics as zero.
11footy data: CC BY-NC 4.0, private noncommercial use only.
"""
import season_db
METRICS={
    "11footy":{"minutes":"minutes_played","goals":"goals","assists":"assists","shots":"shots","shots_on_target":"shots_on_target","key_passes":"key_passes","saves":"saves"},
    "soccer_data":{k:k for k in ("minutes","goals","assists","shots","xg","xa","key_passes","tackles","interceptions","clearances","recoveries","duels_won","saves","passes","accurate_passes")}
}
def totals(rows,source):
    out={}
    for label,key in METRICS[source].items():
        values=[r.get(key) for r in rows if r.get(key) is not None]
        out[label]={"value":sum(values) if values else None,"matches":len(values)}
    return {"source":source,"matches":len(rows),"metrics":out}
def get_stats(mode,mid,tid,pid):
    if mode not in ("live","archive") or any(type(x) is not int or not 0<x<2147483648 for x in (mid,tid,pid)):
        raise ValueError("Μη έγκυρα στοιχεία αγώνα ή παίκτη.")
    with season_db.db() as db:
        table="lineup_live_fixtures" if mode=="live" else "archive_matches"
        context=db.execute(f"SELECT competition_code,kickoff_utc FROM {table} WHERE match_id=%s",(mid,)).fetchone()
        if not context:raise ValueError("Ο αγώνας δεν βρέθηκε.")
        code=context["competition_code"];cutoff=context["kickoff_utc"]
        op="<" if mode=="live" else "<="
        args=(code,tid,pid,cutoff)
        n=db.execute(f"""SELECT count(*)::int n FROM archive_starters s JOIN archive_matches a USING(match_id)
          WHERE a.season_year=2026 AND a.competition_code=%s AND s.team_id=%s AND s.player_id=%s AND a.kickoff_utc{op}%s""",args).fetchone()["n"]
        sources=[]
        if db.execute("SELECT to_regclass('public.lineup_private_match_stats') AS t").fetchone()["t"]:
            rows=db.execute(f"""SELECT DISTINCT ON (p.match_id) p.metrics
              FROM lineup_private_match_stats p JOIN archive_matches a USING(match_id)
              WHERE p.source='11footy' AND a.season_year=2026 AND a.competition_code=%s
              AND p.team_id=%s AND p.player_id=%s AND a.kickoff_utc{op}%s
              ORDER BY p.match_id,p.imported_at DESC,p.release_name DESC""",args).fetchall()
            if rows:sources.append(totals([r["metrics"] for r in rows],"11footy"))
        if db.execute("SELECT to_regclass('public.soccer_stats_verified_match_players') AS t").fetchone()["t"]:
            rows=db.execute(f"""SELECT DISTINCT ON (match_id) minutes,goals,assists,shots,xg,xa,key_passes,tackles,interceptions,clearances,recoveries,duels_won,saves,passes,accurate_passes
              FROM soccer_stats_verified_match_players WHERE season_year=2026 AND competition_code=%s
              AND team_id=%s AND canonical_player_id=%s AND kickoff_utc{op}%s AND started
              ORDER BY match_id,provider_player_id""",args).fetchall()
            if rows:sources.append(totals(rows,"soccer_data"))
        return {"competition":code,"starts":n,"cutoff":cutoff.isoformat(),"inclusive":mode=="archive","sources":sources,
                "note":"Μόνο αγώνες ως βασικός στην ίδια ομάδα/διοργάνωση. Οι πηγές δεν αθροίζονται."}
