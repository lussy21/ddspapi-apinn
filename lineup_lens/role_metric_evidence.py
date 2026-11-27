"""Source-specific FPL-Elo evidence from verified historical starting XIs.
Not an overall quality score: role, tactics and opposition influence metrics.
Use only same-source, same-role, complete observations, without imputing zero.
"""
from math import isfinite,sqrt

def number(v):
    try:
        n=float(v)
        return n if isfinite(n) and n>=0 else None
    except (ValueError,TypeError,OverflowError):return None

def sample(rows,role,fields):
    used={}
    for r in rows:
        if r.get("role")!=role:continue
        m=number(r.get("minutes"))
        vals=[number(r.get(f)) for f in fields]
        if m is None or not 0<m<=150 or any(v is None for v in vals):continue
        if r["match_id"] in used:return None
        used[r["match_id"]]=(m,vals)
    if len(used)<5 or sum(m for m,v in used.values())<360:return None
    return list(used.values())

def rate(rows,i):
    minutes=sum(m for m,v in rows)
    return 90*sum(v[i] for m,v in rows)/minutes

def delta_status(a,b,minimum,relative=.20):
    d=b-a;limit=max(minimum,relative*a)
    return 1 if d>=limit else -1 if d<=-limit else 0

def compare(a,b,role):
    if role in ("CB","LB","RB","DM"):
        # Duel win rate measures success rather than activity alone.
        # Recoveries/interceptions provide a second, separate activity signal.
        fields=("duels_won","duels_lost","interceptions","recoveries")
        x,y=sample(a,role,fields),sample(b,role,fields)
        if x is None or y is None:return None
        def duel(rows):
            won=sum(v[0] for m,v in rows);lost=sum(v[1] for m,v in rows)
            return (won/(won+lost),won+lost) if won+lost>=30 else None
        dx,dy=duel(x),duel(y)
        if dx is None or dy is None:return None
        gap=dy[0]-dx[0]
        # Approximate independent-binomial uncertainty as a conservative
        # heuristic, not a significance test (duels are correlated).
        margin=max(.08,1.5*sqrt(dx[0]*(1-dx[0])/dx[1]+dy[0]*(1-dy[0])/dy[1]))
        direction=1 if gap>=margin else -1 if gap<=-margin else 0
        activity=[delta_status(rate(x,i),rate(y,i),.5) for i in (2,3)]
        if direction and direction in activity and -direction not in activity:
            return ("positive" if direction>0 else "negative",
              "Καλύτερες" if direction>0 else "Χαμηλότερες")
        return None
    if role in ("CF","LF","RF","AM","AM-L","AM-R","LM","RM","CM"):
        fields=("xg","xa","chances_created") if role not in ("CF","LF","RF") else ("xg","shots_on_target","xa")
        x,y=sample(a,role,fields),sample(b,role,fields)
        if x is None or y is None:return None
        limits=(.10,.10,.5) if fields[1]=="xa" else (.10,.5,.10)
        signals=[delta_status(rate(x,i),rate(y,i),limits[i]) for i in range(3)]
        if signals.count(1)>=2 and -1 not in signals:return "positive","Καλύτερες"
        if signals.count(-1)>=2 and 1 not in signals:return "negative","Χαμηλότερες"
    return None

def evidence(a,b,role):
    r=compare(a,b,role)
    if r is None:return None
    status,word=r
    what="ενδείξεις σε μονομαχίες και ανακτήσεις/κοψίματα" if role in ("CB","LB","RB","DM") else "ενδείξεις επιθετικής/δημιουργικής συνεισφοράς"
    return status,word+" "+what+" (FPL-Elo, μόνο βασικές συμμετοχές)."
