"""Use verified played-player evidence, including substitute minutes.
FPL's position is a roster category, not an observed tactical role.
Keeper goals prevented are compared only with adequate shot exposure.
"""
from collections import defaultdict
from math import isfinite,sqrt
import role_metric_evidence

def number(v,signed=False):
    try:
        x=float(v)
        return x if isfinite(x) and (signed or x>=0) else None
    except (TypeError,ValueError,OverflowError):return None

def keeper_profile(rows):
    used={}
    for r in rows:
        if r.get("position")!="G":continue
        m=number(r.get("minutes"))
        v=r.get("metrics",{})
        gp=number(v.get("goals_prevented"),True);x=number(v.get("xgot_faced"))
        saves=number(v.get("saves"));ga=number(v.get("goals_conceded"))
        if m is None or not 0<m<=150 or None in (gp,x,saves,ga):continue
        if abs(gp-(x-ga))>.06:continue
        mid=r["match_id"]
        if mid in used:return None
        used[mid]=(m,gp,x,saves+ga)
    if len(used)<3:return None
    mins=sum(v[0] for v in used.values());exposure=sum(v[2] for v in used.values())
    shots=sum(v[3] for v in used.values())
    if mins<270 or exposure<3 or shots<12:return None
    mean=90*sum(v[1] for v in used.values())/mins
    # Match-level uncertainty; do not treat each shot as independent.
    w=[min(v[0],90) for v in used.values()]
    effective=sum(w)**2/sum(v*v for v in w)
    variance=sum(wi*(90*v[1]/v[0]-mean)**2 for wi,v in zip(w,used.values()))/sum(w)
    return mean,sqrt(variance/max(1,effective-1)),sum(v[1] for v in used.values())/exposure

def keeper(a,b):
    x,y=keeper_profile(a),keeper_profile(b)
    if x is None or y is None:return None
    delta=y[0]-x[0];margin=max(.30,1.5*sqrt(x[1]**2+y[1]**2))
    relative=y[2]-x[2]
    if delta>=margin and relative>=.10:return "positive","Καλύτερη καταγεγραμμένη αποτροπή γκολ (FPL-Elo)."
    if delta<=-margin and relative<=-.10:return "negative","Χαμηλότερη καταγεγραμμένη αποτροπή γκολ (FPL-Elo)."
    return None

def compare(a,b,role,broad):
    if broad=="G":return keeper(a,b)
    # Exact current/recent role is checked by the caller. Historical substitute
    # data have roster position only, so conclusions are explicitly broad.
    # Require the same roster category on both profiles; never assign an
    # inferred tactical position to a substitute.
    if broad not in ("D","M","F"):return None
    def profile(rows):
        return [dict(r["metrics"],match_id=r["match_id"],minutes=r["minutes"],role=role)
                for r in rows if r.get("position")==broad]
    result=role_metric_evidence.evidence(profile(a),profile(b),role)
    if result is None:return None
    return result[0],result[1].replace("μόνο βασικές συμμετοχές","ίδια ευρεία θέση ρόστερ, βασικοί και αλλαγές")

def load(db,league,tid,cutoff):
    out=defaultdict(list)
    if league!="PL" or not db.execute("SELECT to_regclass('lineup_fpl_played_metrics') AS t").fetchone()["t"]:return out
    rows=db.execute("""SELECT p.match_id,p.player_id,p.minutes,p.position,p.started,p.metrics
        FROM lineup_fpl_played_metrics p JOIN archive_matches a USING(match_id)
        WHERE a.season_year=2026 AND a.competition_code=%s AND p.team_id=%s AND a.kickoff_utc<%s
        AND p.player_id IS NOT NULL""",(league,tid,cutoff)).fetchall()
    for r in rows:out[r["player_id"]].append(r)
    return out
