"""Conservative lineup footprint pilot: recent usual XI vs confirmed XI.
No outcome forecasts, no invented ratings. Strict pre-kickoff cutoff.
A change is not a weakness. Only compare individual contribution with
same-source, same-role and sufficient minutes; thresholds are uncalibrated.
"""
from collections import Counter,defaultdict
from math import isfinite
import season_db
from archive_pitch import ROLE

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
def assess(current,history,stats):
    unknown=lambda k:{"line":LABELS[k],"status":"unknown","text":"Ανεπαρκές ιστορικό ή άγνωστες θέσεις."}
    if len(current)!=11 or len({p["id"] for p in current})!=11 or any(line(p.get("code")) not in LINES for p in current):
        return [unknown(k) for k in LINES]
    recent=sorted(history,key=lambda m:m["kickoff_utc"],reverse=True)[:5]
    if len(recent)<5 or any(len(m["players"])!=11 or len({p["id"] for p in m["players"]})!=11 or any(line(p.get("code")) not in LINES for p in m["players"]) for m in recent):
        return [unknown(k) for k in LINES]
    current_ids={p["id"] for p in current}
    freq=Counter();roles=defaultdict(Counter);names={}
    for m in recent:
        for p in m["players"]:
            freq[p["id"]]+=1;roles[p["id"]][p["code"]]+=1;names[p["id"]]=p["name"]
    # Majority of last five starts; exact recent role must also have majority.
    regular={pid:c.most_common(1)[0][0] for pid,c in roles.items() if freq[pid]>=3 and c.most_common(1)[0][1]>=3}
    out=[]
    for k in LINES:
        usual={pid for pid,c in regular.items() if line(c)==k}
        now=[p for p in current if line(p["code"])==k]
        current_line={p["id"] for p in now}
        absent=usual-current_line
        newcomers=[p for p in now if p["id"] not in usual]
        if not usual or len(usual)!=len(now):
            out.append({"line":LABELS[k],"status":"unknown","text":"Αλλαγές ρόλων ή μη σταθερή συνήθης σύνθεση."});continue
        if not absent and not newcomers:
            out.append({"line":LABELS[k],"status":"usual","text":"Συνήθης σύνθεση."});continue
        if len(absent)!=1 or len(newcomers)!=1:
            out.append({"line":LABELS[k],"status":"unknown","text":"Πολλαπλές αλλαγές· η ποιότητά τους δεν έχει ακόμη αξιολογηθεί."});continue
        old=next(iter(absent));new=newcomers[0]
        if old in current_ids or role(regular[old])!=role(new["code"]):
            out.append({"line":LABELS[k],"status":"unknown","text":"Αλλαγή ρόλου· δεν υπάρχει ασφαλής σύγκριση."});continue
        status,msg=compare(stats.get(old,[]),stats.get(new["id"],[]),new["code"])
        out.append({"line":LABELS[k],"status":status,"text":names[old]+" → "+new["name"]+". "+msg})
    return out
def load_history(db,league,tid,cutoff):
    rows=db.execute("""SELECT a.match_id,a.kickoff_utc,s.player_id,p.player_name,s.position_code
      FROM archive_matches a JOIN archive_starters s USING(match_id) JOIN archive_players p USING(player_id)
      WHERE a.season_year=2026 AND a.competition_code=%s AND s.team_id=%s AND a.kickoff_utc<%s
      AND a.match_id IN (SELECT match_id FROM archive_matches WHERE season_year=2026 AND competition_code=%s
      AND kickoff_utc<%s AND %s IN(home_team_id,away_team_id) ORDER BY kickoff_utc DESC LIMIT 5)
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
def for_match(mid):
    import live_matchday
    d=live_matchday.lineup(mid)
    if not d.get("ready") or not d.get("confirmed"):return {"ready":False}
    from datetime import datetime
    cutoff=datetime.fromisoformat(d["kickoff"])
    results=[]
    with season_db.db() as db:
        for side in ("home","away"):
            t=d[side];tid=t["id"]
            xi=[{"id":p.get("stats_player_id"),"name":p["name"],"code":p.get("position_code")} for p in t["starting_xi"]]
            if not tid or any(p["id"] is None for p in xi):
                lines=[{"line":LABELS[k],"status":"unknown","text":"Ανεπαρκής αντιστοίχιση παικτών."} for k in LINES]
            else:lines=assess(xi,load_history(db,d["competition"],tid,cutoff),load_stats(db,d["competition"],tid,cutoff))
            results.append({"name":t["name"],"lines":lines})
    return {"ready":True,"teams":results,"note":"Πιλοτική αξιολόγηση της συνήθους σύνθεσης και διαθέσιμων ατομικών δεικτών. Όχι βαθμολογία ποιότητας ή πρόβλεψη. Τα όρια δεν έχουν βαθμονομηθεί."}
