"""Observed contribution of confirmed XI vs recent actual starting groups.

This is NOT a calibrated strength rating or a match prediction.
All profiles use only pre-kickoff same-team, same-competition data.
One metric and one provider per line; incomplete observations never
become zero. All played minutes (including substitutes) are eligible.
"""
from collections import defaultdict
from math import isfinite
from archive_pitch import ROLE
from simple_replacements import current_codes,number

LABELS={"F":"Επίθεση","M":"Κέντρο","D":"Άμυνα","G":"Τέρμα"}
# Attacking midfield belongs to attacking group; actual tactical position
# codes decide group membership, not the roster's nominal position.
def group(code):
    g=ROLE.get(code,code if code in ("G","D","M","A","F") else None)
    return "F" if g=="A" else g

SPECS={
 "F":[("xG + xA / 90′",("xg","xa"),"sum","relative"),
      ("Γκολ + ασίστ / 90′",("goals","assists"),"sum","relative")],
 "M":[("Ευκαιρίες / 90′",("chances_created",),"sum","relative"),
      ("Πάσες-κλειδιά / 90′",("key_passes",),"sum","relative")],
 "D":[("Επιτυχία μονομαχιών",("duels_won","duels_lost"),"duels","pp"),
      ("Ανακτήσεις / 90′",("recoveries",),"sum","relative")],
 "G":[("Αποτροπή γκολ / 90′",("goals_prevented","xgot_faced","goals_conceded","saves"),"keeper","absolute")],
}

def profile(rows,fields,mode):
    if not rows:return None
    ids=set();used=[];all_minutes=0
    for r in rows:
        mid=r["match_id"];m=number(r.get("minutes"))
        if mid in ids:return None
        ids.add(mid)
        if m is None or m>150:return None
        if not m:continue
        all_minutes+=m
        raw=r.get("metrics") or {}
        v=[number(raw.get(k),k=="goals_prevented") for k in fields]
        if any(x is None for x in v):continue
        if mode=="keeper" and abs(v[0]-(v[1]-v[2]))>.06:continue
        used.append((m,v))
    mins=sum(m for m,v in used)
    if len(used)<3 or mins<120 or mins<.8*all_minutes:return None
    totals=[sum(v[i] for m,v in used) for i in range(len(fields))]
    if mode=="duels" and totals[0]+totals[1]<15:return None
    if mode=="keeper" and (mins<270 or totals[1]<3 or totals[2]+totals[3]<12):return None
    vals=[90*x/mins for x in totals]
    return {"values":vals,"minutes":mins,"matches":len(used),"coverage":mins/all_minutes}

def aggregate(ids,profiles,mode):
    if not ids or any(i not in profiles for i in ids):return None
    vals=[profiles[i]["values"] for i in ids]
    if mode=="duels":
        w=sum(v[0] for v in vals);total=w+sum(v[1] for v in vals)
        return 100*w/total if total else None
    if mode=="keeper":return vals[0][0] if len(vals)==1 else None
    return sum(sum(v) for v in vals)

def groups(players):
    if len(players)!=11 or len({p["id"] for p in players})!=11:return None
    out={k:[] for k in LABELS}
    for p in players:
        k=group(p.get("code"))
        if not k:return None
        out[k].append(p["id"])
    if len(out["G"])!=1 or any(not v for v in out.values()):return None
    return out

def evaluate(current,history,sources,formation=None):
    current=current_codes(current,formation)
    now=groups(current)
    by=defaultdict(list);dates={};names={p["id"]:p["name"] for p in current}
    for r in history:
        by[r["match_id"]].append({"id":r["player_id"],"name":r["player_name"],"code":r["position_code"]})
        dates[r["match_id"]]=r["kickoff_utc"];names.setdefault(r["player_id"],r["player_name"])
    recent=[]
    for mid in sorted(by,key=lambda m:(dates[m],m),reverse=True):
        g=groups(by[mid])
        if g:recent.append(g)
        if len(recent)==5:break
    results=[]
    for k,label in LABELS.items():
        row={"line":k,"label":label,"status":"unknown","value":None,"reason":"Δεν επαρκούν τα συγκρίσιμα δεδομένα."}
        results.append(row)
        if not now or len(recent)<3:continue
        ids=now[k]
        if any(p.get("unresolved") and p["id"] in ids for p in current):
            row["reason"]="Μη επιβεβαιωμένη ταυτότητα παίκτη.";continue
        refs=[g[k] for g in recent]
        if all(set(ids)==set(ref) for ref in refs):
            row.update(status="unchanged",reason="Ίδια σύνθεση γραμμής στους τελευταίους "+str(len(refs))+" αγώνες.")
            continue
        all_ids=set(ids)|{i for ref in refs for i in ref}
        choices=[]
        for priority,(metric,fields,mode,unit) in enumerate(SPECS[k]):
            for source,pool in sources.items():
                profiles={i:p for i in all_ids if (p:=profile(pool.get(i,[]),fields,mode)) is not None}
                cur=aggregate(ids,profiles,mode)
                if cur is None:continue
                bases=[(ref,v) for ref in refs if (v:=aggregate(ref,profiles,mode)) is not None]
                if len(bases)<3:continue
                baseline=sum(v for ref,v in bases)/len(bases)
                if not isfinite(baseline) or (unit=="relative" and baseline<=0):continue
                value=(cur-baseline)/baseline*100 if unit=="relative" else cur-baseline
                if not isfinite(value):continue
                used=set(ids)|{i for ref,v in bases for i in ref}
                low=min(profiles[i]["minutes"] for i in used)
                # Maximize actual reference coverage, then use preferred metric
                # and largest minimum observed minutes across players.
                choices.append(((len(bases),-priority,low),metric,unit,value,cur,baseline,source,bases,profiles,low))
        if not choices:continue
        _,metric,unit,val,cur,baseline,source,bases,profiles,low=max(choices,key=lambda x:x[0])
        ref_ids={i for ref,v in bases for i in ref}
        row.update(status="measured",metric=metric,unit=unit,value=round(val,2),current=round(cur,3),baseline=round(baseline,3),
                   source=source,reference_games=len(bases),reference_total=len(refs),min_minutes=round(low),
                   small_sample=low<360,reason="Ιστορική διαφορά δείκτη, όχι πρόβλεψη.",
                   today=[names[i] for i in ids],reference=[names[i] for i in sorted(ref_ids)],
                   current_only=[names[i] for i in ids if i not in ref_ids],
                   reference_only=[names[i] for i in sorted(ref_ids-set(ids))],
                   players=[{"name":names[i],"minutes":round(profiles[i]["minutes"]),"matches":profiles[i]["matches"],
                    "value":round(aggregate([i],profiles,mode),3) if aggregate([i],profiles,mode) is not None else None,
                    "today":i in ids,"reference_count":sum(i in ref for ref,v in bases)} for i in sorted(set(ids)|ref_ids)])
    return results

def load(db,league,tid,cutoff,xi,formation):
    from simple_replacements import load_history,load_sources
    return evaluate(xi,load_history(db,league,tid,cutoff),load_sources(db,league,tid,cutoff),formation)
