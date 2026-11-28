"""Descriptive goal-oriented lineup comparison, not a causal rating.
Attacking rates include all verified played minutes. Defensive context is
a weighted average of FULL MATCH goals conceded in prior starting groups.
Each match enters once with weight equal to fraction of group present.
No assumption about when goals or substitutions occurred.
"""
from collections import defaultdict,Counter
from lineup_impact import groups,profile,aggregate
from simple_replacements import current_codes,number

ROWS=[("F","Επίθεση"),("M","Κέντρο επιθετικά"),("MD","Κέντρο αμυντικά"),("D","Άμυνα"),("G","Τέρμα")]
def history_groups(history):
    by=defaultdict(list);dates={}
    for r in history:
        by[r["match_id"]].append(dict(id=r["player_id"],name=r["player_name"],code=r["position_code"]))
        dates[r["match_id"]]=r["kickoff_utc"]
    return [(m,g) for m in sorted(by,key=lambda m:(dates[m],m),reverse=True) if (g:=groups(by[m]))]

def context(ids,line,matches,scores):
    """Match-level overlap weighting, not a player's individual GA/90."""
    if not ids:return None
    ids=set(ids);counts=Counter();weighted=0;weights=0;games=0
    for mid,g in matches:
        ga=number(scores.get(mid))
        if ga is None:continue
        common=ids.intersection(g[line])
        if not common:continue
        counts.update(common)
        w=len(common)/len(ids)
        weighted+=w*ga;weights+=w;games+=1
    if games<3 or any(counts[i]<3 for i in ids) or weights<3:return None
    return dict(value=weighted/weights,games=games,weight=weights,min_starts=min(counts[i] for i in ids))

def defensive(ids,refs,line,matches,scores):
    today=context(ids,line,matches,scores)
    if today is None:return None
    bases=[x for ref in refs if (x:=context(ref,line,matches,scores)) is not None]
    if len(bases)<3:return None
    base=sum(x["value"] for x in bases)/len(bases)
    low=min([today["min_starts"]]+[x["min_starts"] for x in bases])
    return dict(status="measured",metric="Γκολ κατά / αγώνα",unit="absolute",lower_better=True,
                baseline=round(base,3),current=round(today["value"],3),value=round(today["value"]-base,3),
                source="Επιβεβαιωμένα τελικά σκορ",reference_games=len(bases),reference_total=len(refs),
                sample_label=f'{today["games"]} ιστορικοί αγώνες · ελάχιστο {low} ενάρξεις ανά παίκτη',
                small_sample=low<5,reason="Σταθμισμένος μέσος όρος ομαδικών γκολ κατά σε ολόκληρους αγώνες με παίκτες της γραμμής στην αρχική 11άδα. Όχι γκολ κατά όσο ήταν στο γήπεδο, ούτε ατομική ευθύνη. Δεν γίνεται προσαρμογή αντιπάλου/έδρας.")

def individual(ids,refs,sources,fields,mode,metric):
    all_ids=set(ids)|{i for ref in refs for i in ref}
    choices=[]
    for source,pool in sources.items():
        profiles={i:p for i in all_ids if (p:=profile(pool.get(i,[]),fields,mode)) is not None}
        cur=aggregate(ids,profiles,mode)
        if cur is None:continue
        bases=[(ref,v) for ref in refs if (v:=aggregate(ref,profiles,mode)) is not None]
        if len(bases)<3:continue
        used=set(ids)|{i for ref,v in bases for i in ref}
        low=min(profiles[i]["minutes"] for i in used)
        choices.append(((len(bases),low),source,profiles,cur,bases,low))
    if not choices:return None
    _,source,profiles,cur,bases,low=max(choices,key=lambda x:x[0])
    base=sum(v for ref,v in bases)/len(bases)
    out=dict(status="measured",metric=metric,unit="absolute",lower_better=False,
             baseline=round(base,3),current=round(cur,3),value=round(cur-base,3),
             source=source,reference_games=len(bases),reference_total=len(refs),min_minutes=round(low),
             sample_label=f'ελάχιστο {round(low)} λεπτά',small_sample=low<360,
             reason="Άθροισμα ατομικών ιστορικών ρυθμών ανά 90′, όχι πρόβλεψη ομαδικών γκολ.")
    if len(fields)==2 and mode=="sum":
        out["components"]=[dict(label=label,baseline=round(sum(sum(profiles[i]["values"][j] for i in ref) for ref,v in bases)/len(bases),3),
           current=round(sum(profiles[i]["values"][j] for i in ids),3)) for j,label in enumerate(("Γκολ","Ασίστ") if fields==("goals","assists") else ("xG","xA"))]
    return out

def evaluate(current,history,sources,scores,formation=None):
    current=current_codes(current,formation);now=groups(current)
    matches=history_groups(history);recent=matches[:5]
    names={r["player_id"]:r["player_name"] for r in history}
    names.update({p["id"]:p["name"] for p in current})
    results=[]
    for key,label in ROWS:
        line="M" if key=="MD" else key
        row=dict(line=key,label=label,status="unknown",value=None,reason="Δεν επαρκούν τα συγκρίσιμα δεδομένα.")
        results.append(row)
        if not now or len(recent)<3:continue
        ids=now[line];refs=[g[line] for m,g in recent]
        if any(p.get("unresolved") and p["id"] in ids for p in current):continue
        same=all(set(ids)==set(ref) for ref in refs)
        if key in ("MD","D"):
            result=defensive(ids,refs,line,matches,scores)
        elif key=="G":
            result=individual(ids,refs,sources,("goals_prevented","xgot_faced","goals_conceded","saves"),"keeper","Γκολ που απέτρεψε / 90′")
        else:
            actual=individual(ids,refs,sources,("goals","assists"),"sum","Γκολ + ασίστ / 90′")
            xg=individual(ids,refs,sources,("xg",),"sum","xG / 90′")
            xa=individual(ids,refs,sources,("xa",),"sum","xA / 90′")
            # Prefer real production as the common headline, show expected
            # metrics separately. Never add xG to xA or actual goals.
            available=[m for m in (actual,xg,xa) if m is not None]
            result=available[0] if available else None
            if result:result["additional"]=available[1:]
        if result:
            row.update(result)
            row["same_lineup"]=same
            row["today"]=[names[i] for i in ids]
            row["reference_only"]=[names[i] for i in sorted(set().union(*map(set,refs))-set(ids))]
            row["current_only"]=[names[i] for i in ids if not any(i in ref for ref in refs)]
        elif same:
            row.update(status="unchanged",reason="Ίδια σύνθεση γραμμής · δεν υπάρχουν πλήρη στατιστικά.")
    return results

def load_scores(db,league,tid,cutoff):
    rows=db.execute("""SELECT a.match_id,CASE WHEN a.home_team_id=%s THEN r.away_goals ELSE r.home_goals END ga
        FROM archive_matches a JOIN archive_match_results r USING(match_id)
        WHERE a.season_year=2026 AND a.competition_code=%s AND a.kickoff_utc<%s
        AND %s IN(a.home_team_id,a.away_team_id) AND r.home_goals IS NOT NULL AND r.away_goals IS NOT NULL""",
        (tid,league,cutoff,tid)).fetchall()
    return {r["match_id"]:r["ga"] for r in rows}
