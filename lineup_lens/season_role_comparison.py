"""Season reference role-group comparison; evidence, not outcome prediction.
Uses FPL played minutes, verified XI, and nominal positions, never guesses
an exact tactical replacement from a change of formation.
"""
from collections import defaultdict,Counter
from math import isfinite,ceil
import played_metric_evidence

LABELS={"G":"Τέρμα","D":"Άμυνα","M":"Κέντρο","F":"Επίθεση"}

def profile(rows):
    if len({r["match_id"] for r in rows})!=len(rows):return None
    valid=[]
    for r in rows:
        try:
            m=float(r["minutes"]);g=float(r["metrics"]["goals"]);a=float(r["metrics"]["assists"])
        except (ValueError,TypeError,KeyError):continue
        if all(isfinite(x) for x in (m,g,a)) and 0<m<=150 and g>=0 and a>=0:valid.append((m,g,a))
    mins=sum(r[0] for r in valid)
    total=sum(float(r["minutes"]) for r in rows)
    if len(valid)<3 or mins<120 or mins<.8*total:return None
    return {"minutes":mins,"events":sum(g+a for m,g,a in valid),"games":len(valid)}

def findings(current,rows):
    if len(current)!=11 or any(p.get("unresolved") for p in current):return []
    ids={p["id"] for p in current}
    by=defaultdict(list);pos=defaultdict(set);names={};games=defaultdict(list)
    for r in rows:
        pid=r["player_id"];by[pid].append(r);pos[pid].add(r["position"]);names[pid]=r["player_name"]
        if r["started"]:games[r["match_id"]].append(r)
    if not ids<=by.keys() or any(len(pos[p])!=1 for p in ids):return []
    complete=[g for g in games.values() if len(g)==11 and len({r["player_id"] for r in g})==11]
    if len(complete)<6:return []
    current_roles={k:{p for p in ids if pos[p]=={k}} for k in LABELS}
    out=[]
    for k in ("G","D","M","F"):
        # Choose the most-used group size in the verified season, with at
        # least half the fixtures supporting this group size.
        groups=[{r["player_id"] for r in g if r["position"]==k} for g in complete]
        size,count=Counter(map(len,groups)).most_common(1)[0]
        if count<ceil(len(groups)/2) or size<1:continue
        chosen=current_roles[k]
        if len(chosen)!=size:continue
        freq=Counter(p for g in groups for p in g)
        ranked=sorted(freq,key=lambda p:(-freq[p],p))
        if len(ranked)<size or (len(ranked)>size and freq[ranked[size-1]]==freq[ranked[size]]):continue
        baseline=set(ranked[:size])
        absent=baseline-chosen;new=chosen-baseline
        if not absent and k=="G":
            out.append({"kind":"neutral","line":k,"text":"Τέρμα: η συχνότερη επιλογή της σεζόν ξεκινά κανονικά.","detail":"Η συνέχεια στη θέση δεν αποδεικνύει ισοδύναμη αγωνιστική απόδοση."})
            continue
        if not absent or len(absent)!=len(new):continue
        if any(freq[p]<ceil(.5*len(groups)) for p in absent):continue
        if any(len(pos[p])!=1 for p in absent|new):continue
        # Roster-category evidence is not an assertion of precise formation.
        old_names=", ".join(names[p] for p in sorted(absent));new_names=", ".join(names[p] for p in sorted(new))
        if k=="G":
            e=played_metric_evidence.keeper(by[next(iter(absent))],by[next(iter(new))])
            if e:out.append({"kind":e[0],"line":k,"text":"Τέρμα: "+e[1],"detail":old_names+" → "+new_names})
        elif k in ("F","M"):
            aa=[profile(by[p]) for p in absent];bb=[profile(by[p]) for p in new]
            if any(p is None for p in aa+bb):continue
            # This is observed production risk, not a proof of worse quality.
            # Only flag clear absence of established contributions; one short
            # sample cannot prove a weaker player. No per90 extrapolation.
            if all(p["minutes"]>=360 and p["events"]>=3 for p in aa) and all(p["events"]==0 and p["minutes"]<360 for p in bb):
                out.append({"kind":"attention","line":k,"text":LABELS[k]+": πιθανό ρίσκο παραγωγής — η καταγεγραμμένη συνεισφορά των απόντων δεν έχει ακόμη καλυφθεί από τις επιλογές που ξεκινούν.",
                    "detail":old_names+" → "+new_names+". Διαφορετικό μέγεθος δείγματος. Σύγκριση ευρείας θέσης ρόστερ, όχι ακριβούς τακτικού ρόλου."})
            elif all(p["minutes"]>=360 and p["events"]>=3 for p in bb) and all(p["events"]==0 and p["minutes"]<360 for p in aa):
                out.append({"kind":"positive","line":k,"text":LABELS[k]+": οι επιλογές που ξεκινούν έχουν μεγαλύτερη καταγεγραμμένη παραγωγή από τους απόντες με περιορισμένο δείγμα.",
                    "detail":old_names+" → "+new_names+". Δεν αποδεικνύει συνολική υπεροχή."})
    return out

def load(db,league,tid,cutoff,current):
    if league!="PL" or not db.execute("SELECT to_regclass('lineup_fpl_played_metrics') AS t").fetchone()["t"]:return []
    rows=db.execute("""SELECT p.match_id,p.player_id,p.started,p.position,p.minutes,p.metrics,n.player_name
      FROM lineup_fpl_played_metrics p JOIN archive_matches a USING(match_id)
      JOIN archive_players n ON n.player_id=p.player_id
      WHERE p.team_id=%s AND a.competition_code=%s AND a.season_year=2026 AND a.kickoff_utc<%s
      AND p.player_id IS NOT NULL""",(tid,league,cutoff)).fetchall()
    return findings(current,rows)
