"""Same-provider match rating comparisons, using only identified played players.
An experimental descriptive indicator, not a calibrated measure of ability.
No ratings inferred from minutes, team score, or starts. No network calls.
"""
from math import isfinite,sqrt

def profile(rows,position):
    # Provider ratings are only comparable within the same broad role.
    seen={}
    for r in rows:
        if r.get("position")!=position:continue
        try:
            v=float(r["rating"]);m=int(r["minutes"])
        except (KeyError,ValueError,TypeError,OverflowError):continue
        if not isfinite(v) or not 0<v<=10 or not 15<=m<=150:continue
        mid=r["match_id"]
        if mid in seen:return None
        seen[mid]=(v,min(m,90))
    n=len(seen);w=sum(m for v,m in seen.values())
    if n<5 or w<360:return None
    mean=sum(v*m for v,m in seen.values())/w
    effective=w*w/sum(m*m for v,m in seen.values())
    if effective<4:return None
    variance=sum(m*(v-mean)**2 for v,m in seen.values())/w
    se=sqrt(variance/max(1,effective-1))
    return mean,se,n,w

def compare(a,b,position):
    x,y=profile(a,position),profile(b,position)
    if x is None or y is None:return None
    delta=y[0]-x[0];uncertainty=sqrt(x[1]**2+y[1]**2)
    # Deliberately conservative experimental margins; not an inference test
    # or estimated probability. Do not rank conflicting/noisy evidence.
    margin=max(.30,1.5*uncertainty)
    if delta>=margin:return "positive","Καλύτερη καταγεγραμμένη βαθμολογία στη συγκεκριμένη γραμμή (Soccer Data)."
    if delta<=-margin:return "negative","Χαμηλότερη καταγεγραμμένη βαθμολογία στη συγκεκριμένη γραμμή (Soccer Data)."
    if abs(delta)+uncertainty<=.30:return "similar","Παρόμοιες καταγεγραμμένες βαθμολογίες (Soccer Data)."
    return "unknown","Οι βαθμολογίες δεν δίνουν ακόμη σαφή διαφορά (Soccer Data)."
