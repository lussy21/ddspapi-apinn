"""Conservative lineup footprint pilot: recent usual XI vs confirmed XI.
No outcome forecasts, no invented ratings. Strict pre-kickoff cutoff.
A change is not a weakness. Only compare individual contribution with
same-source, same-role and sufficient minutes; thresholds are uncalibrated.
"""
from collections import Counter,defaultdict
from math import isfinite
import season_db
from archive_pitch import ROLE
import archive_daily as archive
import player_rating_evidence
import role_metric_evidence
import lineup_summary
import played_metric_evidence
import season_role_comparison
EUROPE={"UCL","UEL","UECL"}

LINES=("G","D","M","F")
LABELS={"G":"Τερματοφύλακας","D":"Άμυνα","M":"Κέντρο","F":"Επίθεση"}
def line(code):
    r=ROLE.get(code,code if code in ("G","D","M","A","F") else None)
    return "M" if r=="A" else r
def role(code):
    if code in ("DL","LB"):return "LB"
    if code=="RB":return "RB"
    if code in ("CD-L","CD","CD-R","SW"):return "CB"
    if code in ("CM-L","CM","CM-R"):return "CM"
    if code in ("CF-L","CF-R","F","RCF"):return "CF"
    return code
def num(x):
    try:
        v=float(x)
        return v if isfinite(v) and v>=0 else None
    except (ValueError,TypeError,OverflowError):return None
def sample(rows,fields):
    """Use only matches with all compared fields and real positive minutes."""
    used={}
    for r in rows:
        minutes=num(r["metrics"].get("minutes_played"))
        vals=[num(r["metrics"].get(k)) for k in fields]
        if minutes and minutes<=150 and all(v is not None for v in vals):
            used[r["match_id"]]=(minutes,vals)
    mins=sum(v[0] for v in used.values())
    if len(used)<4 or mins<360:return None
    return [90*sum(v[1][i] for v in used.values())/mins for i in range(len(fields))]
def compare(a,b,code):
    """Limited attacking/creative evidence, never a calibrated quality score.
    No conclusions from save counts, defensive activity, or minutes alone.
    """
    r=role(code)
    if r in ("CF","LF","RF"):
        fields=("shots_on_target","goals","assists")
    elif r in ("AM","AM-L","AM-R","LM","RM","CM"):
        fields=("key_passes","assists","shots_on_target")
    else:return "unknown","Δεν υπάρχουν ακόμη επαρκείς δείκτες ποιότητας για αυτή τη θέση."
    x,y=sample(a,fields),sample(b,fields)
    if x is None or y is None:return "unknown","Δεν επαρκεί το συγκρίσιμο δείγμα συμμετοχών."
    # Conservative pilot: two measures must agree and none strongly oppose.
    # Absolute minimum avoids calling 0.01 vs 0.02 a major difference.
    deltas=[v-u for u,v in zip(x,y)]
    pos=sum(d>=max(.15,.25*u) for d,u in zip(deltas,x))
    neg=sum(d<=-max(.15,.25*u) for d,u in zip(deltas,x))
    if pos>=2 and neg==0:return "positive","Καλύτερες ενδείξεις ατομικής συνεισφοράς."
    if neg>=2 and pos==0:return "negative","Χαμηλότερες ενδείξεις ατομικής συνεισφοράς."
    if all(abs(d)<max(.15,.25*u) for d,u in zip(deltas,x)):
        return "similar","Παρόμοιες καταγεγραμμένες ενδείξεις."
    return "unknown","Μικτές ενδείξεις· δεν προκύπτει σαφής διαφορά."
def assess(current,history,stats,ratings=None,team_starts=None,role_metrics=None,played_metrics=None):
    played_metrics=played_metrics or {}
    role_metrics=role_metrics or {}
    ratings=ratings or {}
    team_starts=team_starts or {}
    unknown=lambda k:{"line":LABELS[k],"status":"unknown","text":"Ανεπαρκές ιστορικό ή άγνωστες θέσεις."}
    if len(current)!=11 or len({p["id"] for p in current})!=11 or any(line(p.get("code")) not in LINES for p in current):
        return [unknown(k) for k in LINES]
    # At most two incomplete-position fixtures may be skipped, never older than
    # the latest seven. Five complete earlier XIs remain mandatory.
    recent=[m for m in sorted(history,key=lambda m:m["kickoff_utc"],reverse=True)[:7]
            if len(m["players"])==11 and len({p["id"] for p in m["players"]})==11 and all(line(p.get("code")) in LINES for p in m["players"])][:5]
    if len(recent)<5:
        return [unknown(k) for k in LINES]
    current_ids={p["id"] for p in current}
    freq=Counter();roles=defaultdict(Counter);line_counts=defaultdict(Counter);names={}
    for m in recent:
        for p in m["players"]:
            freq[p["id"]]+=1;roles[p["id"]][p["code"]]+=1;line_counts[p["id"]][line(p["code"])]+=1;names[p["id"]]=p["name"]
    # Majority of last five starts; exact recent role must also have majority.
    regular={pid:c.most_common(1)[0][0] for pid,c in line_counts.items() if c.most_common(1)[0][1]>=3}
    exact={pid:c.most_common(1)[0][0] for pid,c in roles.items() if c.most_common(1)[0][1]>=3}
    out=[]
    for k in LINES:
        usual={pid for pid,c in regular.items() if line(c)==k}
        now=[p for p in current if line(p["code"])==k]
        current_line={p["id"] for p in now}
        absent=usual-current_line
        newcomers=[p for p in now if p["id"] not in usual]
        missing=[names[pid] for pid in sorted(usual-current_ids)]
        details=(" Εκτός συνήθους 11άδας: "+", ".join(missing)+".") if missing else ""
        if any(p.get("unresolved") for p in now):
            out.append({"line":LABELS[k],"status":"unknown","text":"Μη επιβεβαιωμένη ταυτότητα παίκτη."+details});continue
        if not usual or len(usual)!=len(now):
            out.append({"line":LABELS[k],"status":"changes" if missing else "unknown","text":"Διαφορετική ή μη σταθερή διάταξη."+details});continue
        if not absent and not newcomers:
            out.append({"line":LABELS[k],"status":"usual","text":"Συνήθης σύνθεση."});continue
        if len(absent)!=1 or len(newcomers)!=1:
            old_ids=sorted(absent)
            new_ids=[p["id"] for p in newcomers]
            old_roles=Counter(role(exact[i]) for i in old_ids if i in exact)
            new_roles=Counter(role(p["code"]) for p in newcomers)
            comparable=(len(old_ids)==len(new_ids) and len(old_ids)>1
                        and not any(i in current_ids for i in old_ids)
                        and sum(old_roles.values())==len(old_ids)
                        and old_roles==new_roles)
            if comparable:
                broad={ROLE.get(p["code"],p["code"]) for p in newcomers}
                if len(broad)==1:
                    evidence=player_rating_evidence.compare_group(
                        [ratings.get(i,[]) for i in old_ids],
                        [ratings.get(i,[]) for i in new_ids],next(iter(broad)))
                    if evidence is not None:
                        status,msg=evidence
                        out.append({"line":LABELS[k],"status":status,"text":"Συνολική αξιολόγηση αντικαταστατών. "+msg+details});continue
            out.append({"line":LABELS[k],"status":"changes","text":"Πολλαπλές αλλαγές· δεν επαρκούν τα συγκρίσιμα στοιχεία."+details});continue
        old=next(iter(absent));new=newcomers[0]
        if old in current_ids or old not in exact or role(exact[old])!=role(new["code"]):
            out.append({"line":LABELS[k],"status":"changes","text":"Αλλαγή ρόλου· δεν υπάρχει ασφαλής σύγκριση."+details});continue
        rating=player_rating_evidence.compare(ratings.get(old,[]),ratings.get(new["id"],[]),ROLE.get(new["code"],new["code"]))
        metric=role_metric_evidence.evidence(role_metrics.get(old,[]),role_metrics.get(new["id"],[]),role(new["code"]))
        played=played_metric_evidence.compare(played_metrics.get(old,[]),played_metrics.get(new["id"],[]),role(new["code"]),line(new["code"]))
        basic=compare(stats.get(old,[]),stats.get(new["id"],[]),new["code"])
        # Conflicting directional signals from separate sources cannot become
        # a confident quality label. No sums across providers.
        evidence=[e for e in (rating,metric,played,basic) if e is not None and e[0] in ("positive","negative")]
        if len({e[0] for e in evidence})>1:
            status,msg="unknown","Οι διαθέσιμες πηγές δίνουν αντίθετες ενδείξεις."
        elif rating is not None and rating[0] in ("positive","negative","similar"):
            status,msg=rating
        elif played is not None:
            status,msg=played
        elif metric is not None:
            status,msg=metric
        elif rating is not None:
            status,msg=rating
        else:status,msg=basic
        if status=="unknown":
            # Presence is an independent continuity signal, NEVER a quality label.
            old_starts=team_starts.get(old,0);new_starts=team_starts.get(new["id"],0)
            if old_starts>=5 and new_starts>=5 and new_starts>=.75*old_starts:
                msg="Γνώριμη εναλλακτική της ομάδας. Η ποιοτική διαφορά δεν έχει τεκμηριωθεί."
                status="familiar"
        out.append({"line":LABELS[k],"status":status,"text":names[old]+" → "+new["name"]+". "+msg})
    return out
def load_history(db,league,tid,cutoff):
    rows=db.execute("""SELECT a.match_id,a.kickoff_utc,s.player_id,p.player_name,s.position_code
      FROM archive_matches a JOIN archive_starters s USING(match_id) JOIN archive_players p USING(player_id)
      WHERE a.season_year=2026 AND a.competition_code=%s AND s.team_id=%s AND a.kickoff_utc<%s
      AND a.match_id IN (SELECT match_id FROM archive_matches WHERE season_year=2026 AND competition_code=%s
      AND kickoff_utc<%s AND %s IN(home_team_id,away_team_id) ORDER BY kickoff_utc DESC LIMIT 7)
      ORDER BY a.kickoff_utc DESC,s.player_id""",(league,tid,cutoff,league,cutoff,tid)).fetchall()
    games={}
    for r in rows:
        g=games.setdefault(r["match_id"],{"kickoff_utc":r["kickoff_utc"],"players":[]})
        g["players"].append({"id":r["player_id"],"name":r["player_name"],"code":r["position_code"]})
    return list(games.values())
def load_stats(db,league,tid,cutoff):
    out=defaultdict(list)
    if not db.execute("SELECT to_regclass('lineup_private_match_stats') AS t").fetchone()["t"]:return out
    # Same 11footy release across both starters and played substitutes.
    rows=db.execute("""SELECT p.match_id,p.player_id,p.metrics FROM lineup_private_match_stats p
      JOIN archive_matches a USING(match_id) WHERE p.source='11footy' AND p.release_name='11footy-2026-11-10'
      AND a.season_year=2026 AND a.competition_code=%s AND p.team_id=%s AND a.kickoff_utc<%s""",(league,tid,cutoff)).fetchall()
    for r in rows:out[r["player_id"]].append(r)
    if db.execute("SELECT to_regclass('lineup_private_sub_stats') AS t").fetchone()["t"]:
        rows=db.execute("""SELECT p.match_id,p.player_id,p.metrics FROM lineup_private_sub_stats p
          JOIN archive_matches a USING(match_id) WHERE p.release_name='11footy-2026-11-10' AND p.player_id IS NOT NULL
          AND a.season_year=2026 AND a.competition_code=%s AND p.team_id=%s AND a.kickoff_utc<%s""",(league,tid,cutoff)).fetchall()
        for r in rows:out[r["player_id"]].append(r)
    return out
def load_ratings(db,league,tid,cutoff):
    out=defaultdict(list)
    if not db.execute("SELECT to_regclass('soccer_stats_player') AS t").fetchone()["t"]:return out
    # Stable provider ID plus complete verified match XI. Unlinked players,
    # missing ratings, unused substitutes and future matches never qualify.
    rows=db.execute("""SELECT p.match_id,p.canonical_player_id AS player_id,p.minutes,
        p.stats->>'position' AS position,(p.stats->>'rating')::numeric AS rating
        FROM soccer_stats_player p JOIN soccer_stats_fixture f USING(match_id)
        JOIN archive_matches a USING(match_id)
        WHERE a.season_year=2026 AND a.competition_code=%s AND p.team_id=%s AND a.kickoff_utc<%s
        AND f.fetched_at IS NOT NULL AND f.matched_starters=22
        AND p.played AND p.canonical_player_id IS NOT NULL
        AND jsonb_typeof(p.stats->'rating')='number'""",(league,tid,cutoff)).fetchall()
    for r in rows:out[r["player_id"]].append(r)
    return out

def load_role_metrics(db,league,tid,cutoff):
    out=defaultdict(list)
    if league!="PL" or not db.execute("SELECT to_regclass('lineup_research_verified_player_stats') AS t").fetchone()["t"]:return out
    rows=db.execute("""SELECT v.match_id,v.canonical_player_id player_id,v.minutes,v.xg,v.xa,
        v.shots_on_target,v.chances_created,v.duels_won,v.raw_metrics->>'duels_lost' duels_lost,
        v.interceptions,v.recoveries,s.position_code
        FROM lineup_research_verified_player_stats v JOIN archive_starters s
        ON s.match_id=v.match_id AND s.team_id=v.team_id AND s.player_id=v.canonical_player_id
        WHERE v.source='fpl_elo' AND v.season_year=2026 AND v.competition_code=%s
        AND v.team_id=%s AND v.kickoff_utc<%s""",(league,tid,cutoff)).fetchall()
    for r in rows:
        r=dict(r);r["role"]=role(r["position_code"]);out[r["player_id"]].append(r)
    return out

def load_team_starts(db,league,tid,cutoff):
    return {r["player_id"]:r["n"] for r in db.execute("""SELECT s.player_id,count(*)::int n
        FROM archive_starters s JOIN archive_matches a USING(match_id)
        WHERE a.season_year=2026 AND a.competition_code=%s AND s.team_id=%s AND a.kickoff_utc<%s
        GROUP BY s.player_id""",(league,tid,cutoff)).fetchall()}

def domestic_context(db,team,cutoff):
    """Use only the existing verified cross-competition team/player ID links."""
    rows=db.execute("""SELECT DISTINCT a.competition_code,t.team_id
        FROM archive_matches a JOIN archive_teams t ON t.team_id IN (a.home_team_id,a.away_team_id)
        WHERE a.season_year=2026 AND a.kickoff_utc<%s AND a.competition_code NOT IN ('UCL','UEL','UECL')
        AND (t.team_id=%s OR EXISTS(SELECT 1 FROM archive_source_links l
            WHERE l.competition_code=a.competition_code AND l.kind='team'
            AND l.source_id=%s AND l.canonical_id=t.team_id))""",(cutoff,team["id"],team["id"])).fetchall()
    if len(rows)!=1:return None
    code,tid=rows[0]["competition_code"],rows[0]["team_id"]
    links=archive.get_links(db,code)
    names={r["player_id"]:r["player_name"] for r in db.execute("""SELECT DISTINCT p.player_id,p.player_name
      FROM archive_players p JOIN archive_starters s USING(player_id) JOIN archive_matches a USING(match_id)
      WHERE a.season_year=2026 AND a.competition_code=%s AND s.team_id=%s AND a.kickoff_utc<%s""",(code,tid,cutoff)).fetchall()}
    xi=[]
    for p in team["starting_xi"]:
        source=p["id"]
        cid=links["player"].get(source,source)
        known=source not in links["blocked_player"] and cid in names and archive.compatible(names[cid],p["name"])
        # A player with no recorded starts is allowed only with a positively
        # linked source ID; no guessing a name match or counting it as weakness.
        if not known and source not in links["blocked_player"] and source in links["player"] and cid not in names:
            record=db.execute("SELECT player_name FROM archive_players WHERE player_id=%s",(cid,)).fetchone()
            known=bool(record and archive.compatible(record["player_name"],p["name"]))
        xi.append({"id":cid if known else -source,"name":p["name"],"code":p.get("position_code"),"unresolved":not known})
    return code,tid,xi

def for_match(mid):
    import live_matchday
    d=live_matchday.lineup(mid)
    if not d.get("ready") or not d.get("confirmed"):return {"ready":False}
    from datetime import datetime
    cutoff=datetime.fromisoformat(d["kickoff"])
    results=[]
    with season_db.db() as db:
        for side in ("home","away"):
            t=d[side];tid=t["id"];code=d["competition"]
            xi=[{"id":p.get("stats_player_id") or -p["id"],"name":p["name"],"code":p.get("position_code"),"unresolved":p.get("stats_player_id") is None} for p in t["starting_xi"]]
            if code in EUROPE:
                context=domestic_context(db,t,cutoff)
                if context:code,tid,xi=context
            if not tid:
                lines=[{"line":LABELS[k],"status":"unknown","text":"Ανεπαρκής αντιστοίχιση ομάδας."} for k in LINES]
            else:lines=assess(xi,load_history(db,code,tid,cutoff),load_stats(db,code,tid,cutoff),load_ratings(db,code,tid,cutoff),load_team_starts(db,code,tid,cutoff),load_role_metrics(db,code,tid,cutoff),played_metric_evidence.load(db,code,tid,cutoff))
            findings=lineup_summary.load(db,code,tid,cutoff,xi,lines,line) if tid else [{"kind":"neutral","text":"Δεν υπάρχει επαρκές ιστορικό ομάδας.","detail":""}]
            reference=season_role_comparison.load(db,code,tid,cutoff,xi) if tid else []
            # Season-reference findings describe a different baseline from
            # recent tactical lines. Keep their basis explicit and do not
            # overwrite the original tactical assessment.
            if reference:findings=reference+findings
            results.append({"name":t["name"],"lines":lines,"basis":code,"findings":findings})
    return {"ready":True,"teams":results,"note":"Πιλοτικό · Στις ευρωπαϊκές διοργανώσεις χρησιμοποιείται το διαθέσιμο εγχώριο ιστορικό. Γνώριμη επιλογή = συχνές βασικές συμμετοχές, όχι ισοδύναμη ποιότητα. Οι ατομικές ενδείξεις παραμένουν πιλοτικές."}
