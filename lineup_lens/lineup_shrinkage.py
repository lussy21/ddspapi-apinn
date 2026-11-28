"""Experimental pre-kickoff shrinkage of observed goal contributions.
Rates are estimates, not predictions. Same source, league and positional prior.
No missing metric becomes zero; never substitute a prior if no reference evidence.
"""
from collections import defaultdict, Counter
from archive_pitch import ROLE
from simple_replacements import number,load_sources
from lineup_impact import group

PRIOR_MINUTES=450
PRIOR_GAMES=5
MIN_PRIOR_PLAYERS=8
MIN_PRIOR_MINUTES=900
FIELDSETS=(("goals","assists"),("goals",),("xg",),("xa",),("goals_conceded",),
           ("goals_prevented","xgot_faced","goals_conceded","saves"))

def role(code):
    return ROLE.get(code,code if code in ("G","D","M","A","F") else None)

def read_row(r,fields):
    m=number(r.get("minutes"))
    if m is None or not 0<m<=150:return None
    raw=r.get("metrics") or {}
    vals=[number(raw.get(k),k=="goals_prevented") for k in fields]
    if any(x is None for x in vals):return None
    if fields[0]=="goals_prevented" and abs(vals[0]-(vals[1]-vals[2]))>.06:return None
    return m,vals

def priors_from(sources,positions):
    # Position is from the actual starting sheet in the same historical match.
    # Substitutes are included in individual profiles, not guessed into positions.
    result={}
    for source,pool in sources.items():
        acc={}
        for pid,rows in pool.items():
            counts=Counter(r["match_id"] for r in rows)
            for r in rows:
                mid=r["match_id"];code=positions.get((mid,pid));broad=role(code)
                if counts[mid]!=1 or not broad:continue
                for fields in FIELDSETS:
                    if fields[0] in ("goals_conceded","goals_prevented") and broad!="G":continue
                    pair=read_row(r,fields)
                    if pair is None:continue
                    m,vals=pair
                    for key in {code,broad}:
                        v=acc.setdefault((key,fields),[0,[0]*len(fields),set()])
                        v[0]+=m;v[2].add(pid)
                        for j,x in enumerate(vals):v[1][j]+=x
        result[source]={key:{"rates":[90*x/v[0] for x in v[1]],"minutes":v[0],"players":len(v[2])}
                        for key,v in acc.items() if v[0]>=MIN_PRIOR_MINUTES and len(v[2])>=MIN_PRIOR_PLAYERS}
    return result

def load_priors(db,league,cutoff):
    rows=db.execute("""SELECT s.match_id,s.player_id,s.position_code FROM archive_starters s
        JOIN archive_matches a USING(match_id) WHERE a.season_year=2026
        AND a.competition_code=%s AND a.kickoff_utc<%s""",(league,cutoff)).fetchall()
    return priors_from(load_sources(db,league,None,cutoff),
                       {(r["match_id"],r["player_id"]):r["position_code"] for r in rows})

def player_profile(rows,fields,prior,starts):
    ids=set();valid=[];all_minutes=0
    for r in rows:
        mid=r["match_id"]
        if mid in ids:return None
        ids.add(mid)
        m=number(r.get("minutes"))
        if m is None or m>150:return None
        all_minutes+=m
        pair=read_row(r,fields)
        if pair is not None:valid.append(pair)
    minutes=sum(m for m,v in valid)
    totals=[sum(v[j] for m,v in valid) for j in range(len(fields))]
    # A missing profile is not a recorded zero. The prior alone is explicitly marked.
    weight=min(minutes/PRIOR_MINUTES,1.0)
    raw=[90*x/minutes for x in totals] if minutes else None
    # From 450 valid minutes onward, no positional shrinkage at all.
    # Below the threshold the individual weight increases linearly.
    if weight<1 and prior is None:return None
    rates=prior["rates"] if prior else None
    adjusted=raw if weight==1 else [(90*x+(PRIOR_MINUTES-minutes)*p)/PRIOR_MINUTES for x,p in zip(totals,rates)]
    state=("χωρίς καταγεγραμμένα λεπτά" if not rows and not starts else "ελλιπή στατιστικά") if not minutes else (
           "μερικά στατιστικά" if minutes<all_minutes else ("μικρό δείγμα" if minutes<PRIOR_MINUTES else "ιστορικό διαθέσιμο"))
    return dict(values=adjusted,minutes=minutes,observed_minutes=all_minutes,matches=len(valid),
                raw=raw,totals=totals if minutes else None,
                prior=rates,prior_players=prior["players"] if prior else 0,weight=weight,
                state=state,starts=starts)

def individual(ids,refs,positions,ref_positions,history,sources,priors,fields,mode,metric):
    starts=Counter(r["player_id"] for r in history)
    names={r["player_id"]:r["player_name"] for r in history}
    choices=[]
    def total(profiles):
        if not profiles:return None
        if mode=="keeper":return profiles[0]["values"][0] if len(profiles)==1 else None
        return sum(sum(p["values"]) for p in profiles)
    for source,pool in sources.items():
        source_priors=priors.get(source,{})
        def collect(group_ids,pos):
            out=[]
            for pid in group_ids:
                code=pos.get(pid);broad=role(code)
                prior=source_priors.get((code,fields)) or source_priors.get((broad,fields))
                profile=player_profile(pool.get(pid,[]),fields,prior,starts[pid])
                if profile is None:return None
                out.append(dict(profile,id=pid))
            return out
        cur=collect(ids,positions)
        if not cur:continue
        bases=[ps for ref,pos in zip(refs,ref_positions) if (ps:=collect(ref,pos))]
        if len(bases)<3:continue
        # A league-only reference would provide no team-specific comparison.
        if not any(p["minutes"] for ps in bases for p in ps):continue
        cv=total(cur);bv=[total(ps) for ps in bases]
        if cv is None or any(v is None for v in bv):continue
        baseline=sum(bv)/len(bv)
        current_weight=sum(p["weight"] for p in cur)/len(cur)
        ref_weight=sum(sum(p["weight"] for p in ps)/len(ps) for ps in bases)/len(bases)
        quality=(min(current_weight,ref_weight),ref_weight+current_weight,len(bases))
        choices.append((quality,source,cur,bases,cv,baseline,current_weight,ref_weight))
    if not choices:return None
    _,source,cur,bases,cv,baseline,cw,rw=max(choices,key=lambda x:x[0])
    low=min(p["minutes"] for p in cur+[p for ps in bases for p in ps])
    missing=sum(p["minutes"]==0 for p in cur)
    short=sum(0<p["minutes"]<PRIOR_MINUTES for p in cur)
    fully_observed=all(p["weight"]==1 and p["minutes"]==p["observed_minutes"] for p in cur+[p for ps in bases for p in ps])
    out=dict(status="measured" if fully_observed else "estimated",metric=metric,unit="absolute",lower_better=False,
             baseline=round(baseline,3),current=round(cv,3),value=round(cv-baseline,3),source=source,
             reference_games=len(bases),reference_total=len(refs),min_minutes=round(low),
             sample_label=f"{missing} χωρίς στοιχεία · {short} μικρό δείγμα · ατομικό βάρος {round(cw*100)}%",
             small_sample=min(cw,rw)<.5 or missing>0,individual_weight=round(cw,3),
             reference_weight=round(rw,3),prior_minutes=PRIOR_MINUTES,profiles=cur,
             reason="Ρυθμοί ανά 90′: από 450 έγκυρα λεπτά και πάνω αποκλειστικά ατομικά στοιχεία, κάτω από 450 γραμμική εξομάλυνση προς πραγματικό μέσο όρο ίδιας θέσης/πρωταθλήματος/πηγής. Περιλαμβάνει αλλαγές. Χωρίς ιστορικό δεν σημαίνει μηδέν ούτε βέβαιο ντεμπούτο. Δεν είναι πρόβλεψη ομαδικών γκολ.")
    if fields==("goals","assists"):
        out["components"]=[dict(label=label,baseline=round(sum(sum(p["values"][j] for p in ps) for ps in bases)/len(bases),3),
           current=round(sum(p["values"][j] for p in cur),3)) for j,label in enumerate(("Γκολ","Ασίστ"))]
    return out

def defensive(ids,refs,line,matches,scores):
    valid=[(mid,g,ga) for mid,g in matches if (ga:=number(scores.get(mid))) is not None]
    if len(valid)<3 or not ids:return None
    # Team prior includes only pre-kickoff known final scores. Fraction of
    # today's line present in prior starting XI determines effective games.
    team=sum(number(x) for x in scores.values() if number(x) is not None)
    n=sum(number(x) is not None for x in scores.values())
    if n<3:return None
    prior=team/n
    def estimate(group_ids):
        ids=set(group_ids)
        if not ids:return None
        total=weight=0;counts=Counter()
        for mid,g,ga in valid:
            common=ids.intersection(g[line]);w=len(common)/len(ids)
            counts.update(common);total+=w*ga;weight+=w
        return (total+PRIOR_GAMES*prior)/(weight+PRIOR_GAMES),weight,counts
    cur=estimate(ids);bases=[p for ref in refs if (p:=estimate(ref))]
    if cur is None or len(bases)<3:return None
    bv=sum(p[0] for p in bases)/len(bases);cv,w,counts=cur
    missing=sum(counts[i]==0 for i in ids)
    return dict(status="estimated",metric="Γκολ κατά / αγώνα",unit="absolute",lower_better=True,
        baseline=round(bv,3),current=round(cv,3),value=round(cv-bv,3),
        source="Επιβεβαιωμένα τελικά σκορ",reference_games=len(bases),reference_total=len(refs),
        sample_label=f"{w:.1f} ισοδύναμοι αγώνες · {missing} χωρίς ιστορικό βασικού στη γραμμή",
        small_sample=w<PRIOR_GAMES or missing>0,
        reason="Ομαδικά γκολ κατά σε ολόκληρους αγώνες, σταθμισμένα με την επικάλυψη της γραμμής και εξομαλυμένα προς τον μέσο όρο της ομάδας (5 αγώνες). Όχι ατομική αμυντική ευθύνη ούτε γκολ κατά στα λεπτά του παίκτη. Δεν προσαρμόζεται για αντίπαλο/έδρα.")
