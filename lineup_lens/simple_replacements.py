"""Compact, position-specific replacement cards. Private, read-only.
Compare observed historical slots, not a manager's unverified intent.
All statistics precede kickoff; missing metrics remain missing.
"""
from collections import Counter,defaultdict
from math import ceil,isfinite
from archive_pitch import ROLE

SLOTS={
"G":"Τερματοφύλακας","LB":"Αριστερό μπακ","RB":"Δεξί μπακ","CBL":"Αριστερό στόπερ","CBR":"Δεξί στόπερ","CB":"Κεντρικό στόπερ",
"WL":"Αριστερή πλευρά","WR":"Δεξιά πλευρά","CM":"Κεντρικό χαφ","CML":"Αριστερό χαφ","CMR":"Δεξί χαφ","AM":"Επιτελικό χαφ",
"CF":"Σέντερ φορ","CFL":"Αριστερός επιθετικός","CFR":"Δεξιός επιθετικός"}
MAP={"G":"G","DL":"LB","LB":"LB","RB":"RB","CD-L":"CBL","CD-R":"CBR","CD":"CB","SW":"CB",
"LM":"WL","AM-L":"WL","LF":"WL","RM":"WR","AM-R":"WR","RF":"WR",
"CM":"CM","DM":"CM","CM-L":"CML","CM-R":"CMR","AM":"AM","F":"CF","CF-L":"CFL","CF-R":"CFR","RCF":"CFR"}
FORMATIONS={
"4-2-3-1":["G","LB","CD-L","CD-R","RB","CM-L","CM-R","AM-L","AM","AM-R","F"],
"4-3-3":["G","LB","CD-L","CD-R","RB","LM","CM","RM","LF","F","RF"],
"3-4-2-1":["G","CD-L","CD","CD-R","LM","CM-L","CM-R","RM","CF-L","CF-R","F"],
"4-4-2":["G","LB","CD-L","CD-R","RB","LM","CM-L","CM-R","RM","CF-L","CF-R"],
"3-5-2":["G","CD-L","CD","CD-R","LM","CM-L","CM","CM-R","RM","CF-L","CF-R"],
"3-4-3":["G","CD-L","CD","CD-R","LM","CM-L","CM-R","RM","LF","F","RF"]}
def current_codes(xi,formation):
    # Only use known explicit ordering when the input has broad position codes.
    shape=FORMATIONS.get(formation)
    if len(xi)!=11:return []
    out=[]
    for i,p in enumerate(xi):
        code=p.get("code")
        if code not in ROLE and shape and code in ("D","M","F","A"):
            code=shape[i]
        out.append(dict(p,code=code))
    return out

def slot_for(code,formation_counts):
    # LM/RM in the three-man central midfield of 4-3-3, or double
    # pivot of 4-2-3-1, are not the attacking wide slots.
    if code in ("LM","RM") and ((formation_counts.get("D")==4 and formation_counts.get("M")==3 and formation_counts.get("F")==3)
         or (formation_counts.get("D")==4 and formation_counts.get("M")==2 and formation_counts.get("A")==3 and formation_counts.get("F")==1)):
        return "CML" if code=="LM" else "CMR"
    return MAP.get(code)

def pairs(current,history):
    if len(current)!=11 or len({p["id"] for p in current})!=11:return []
    if any(p.get("code") not in MAP for p in current):return []
    names={};positions=defaultdict(Counter);freq=defaultdict(Counter);starts=Counter()
    games={r["match_id"] for r in history}
    if len(games)<5:return []
    shapes=defaultdict(Counter)
    for r in history:shapes[r["match_id"]][ROLE.get(r["position_code"])]+=1
    for r in history:
        pid=r["player_id"];names[pid]=r["player_name"];starts[pid]+=1
        slot=slot_for(r["position_code"],shapes[r["match_id"]])
        if slot:freq[slot][pid]+=1;positions[pid][slot]+=1
    shape=Counter(ROLE.get(p["code"]) for p in current)
    now={p["id"] for p in current};present=Counter(slot_for(p["code"],shape) for p in current)
    out=[];used=set()
    for p in current:
        slot=slot_for(p["code"],shape)
        if present[slot]!=1:continue
        ranking=freq[slot].most_common()
        if not ranking:continue
        old,n=ranking[0]
        if n<max(3,ceil(len(games)*.45)) or (len(ranking)>1 and ranking[1][1]==n):continue
        if old in now or old in used:continue
        if p.get("unresolved"):continue
        # An unresolved player elsewhere could be the historical reference.
        from archive_daily import compatible
        if any(q.get("unresolved") and compatible(names[old],q["name"]) for q in current):continue
        used.add(old)
        old_role=positions[old].most_common(1)[0][0]
        new_role=positions[p["id"]].most_common(1)[0][0] if positions[p["id"]] else None
        out.append({"slot":slot,"position":SLOTS[slot],"old":{"id":old,"name":names[old],"starts":starts[old],"usual_role":SLOTS[old_role]},
                    "new":{"id":p["id"],"name":p["name"],"starts":starts[p["id"]],"usual_role":SLOTS.get(new_role),"role_starts":freq[slot][p["id"]]},
                    "basis":"Ίδια πλευρά / θέση αναφοράς" if slot in ("WL","WR") else "Ίδια θέση αναφοράς"})
    return out

def number(v,signed=False):
    try:
        x=float(v)
        return x if isfinite(x) and (signed or x>=0) else None
    except (ValueError,TypeError,OverflowError):return None

def metric(rows,key):
    vals=[number(r["metrics"].get(key),key=="goals_prevented") for r in rows]
    valid=[v for v in vals if v is not None]
    return sum(valid) if valid and len(valid)==len(rows) else None

def profile(rows,slot):
    if not rows or len({r["match_id"] for r in rows})!=len(rows):return {}
    mins=[number(r.get("minutes")) for r in rows]
    if any(m is None or m<=0 or m>150 for m in mins):return {}
    total=sum(mins)
    if slot=="G":
        specs=[("Αποκρούσεις","saves"),("Γκολ που απέτρεψε","goals_prevented")]
    elif slot in ("LB","RB","CB","CBL","CBR"):
        specs=[("Κερδισμένες μονομαχίες","duels_won"),("Ανακτήσεις / 90′","recoveries")]
    elif slot in ("CM","CML","CMR"):
        specs=[("Ανακτήσεις / 90′","recoveries"),("Ευκαιρίες / 90′","chances_created")]
    else:specs=[("Γκολ","goals"),("Ασίστ","assists")]
    values=[]
    for label,key in specs:
        v=metric(rows,key)
        if key=="duels_won" and v is not None:
            lost=metric(rows,"duels_lost")
            v=f"{int(v)}/{int(v+lost)} ({round(100*v/(v+lost))}%)" if lost is not None and v+lost>0 else str(int(v))
        elif v is not None:
            v=round(v*90/total,1) if "/ 90" in label else round(v,2)
        values.append({"label":label,"value":v})
    return {"matches":len(rows),"minutes":round(total),"metrics":values}

def decorate(pair,sources):
    a,b=pair["old"],pair["new"];slot=pair["slot"]
    options=[]
    for name,pool in sources.items():
        x,y=profile(pool.get(a["id"],[]),slot),profile(pool.get(b["id"],[]),slot)
        common=sum(u["value"] is not None and v["value"] is not None for u,v in zip(x.get("metrics",[]),y.get("metrics",[])))
        coverage=min(x.get("matches",0),y.get("matches",0))
        options.append((common,coverage,x.get("matches",0)+y.get("matches",0),name,x,y))
    if options:
        _,_,_,source,x,y=max(options,key=lambda q:q[:3])
        a.update(x);b.update(y);pair["source"]=source
    else:pair["source"]=None
    msg="Δεν επαρκούν τα ατομικά στοιχεία για σύγκριση ποιότητας."
    kind="neutral"
    if b["role_starts"]<3 and a["starts"]>=5:
        msg="Λίγες βασικές συμμετοχές στη συγκεκριμένη θέση.";kind="attention"
    if b["usual_role"] and b["usual_role"]!=pair["position"] and b["role_starts"]<3:
        msg="Συνήθως παίζει "+b["usual_role"].lower()+". Αλλαγή ρόλου.";kind="attention"
    if slot in ("CF","CFL","CFR","WL","WR","AM"):
        av=[m["value"] for m in a.get("metrics",[])];bv=[m["value"] for m in b.get("metrics",[])]
        if len(av)==len(bv)==2 and all(isinstance(v,(float,int)) for v in av+bv):
            if sum(av)>=3 and sum(bv)==0 and a["minutes"]>=360 and b["minutes"]>=120:
                msg="Πιθανή απώλεια επιθετικής παραγωγής. Διαφορετικά λεπτά συμμετοχής.";kind="attention"
            elif sum(bv)>=3 and sum(av)==0 and b["minutes"]>=360 and a["minutes"]>=120:
                msg="Η σημερινή επιλογή έχει καταγεγραμμένη επιθετική παραγωγή.";kind="neutral"
            else:
                msg="Σύγκριση καταγεγραμμένων γκολ και ασίστ· όχι βαθμός ποιότητας."
    if slot in ("LB","RB","CB","CBL","CBR") and a.get("metrics") and b.get("metrics"):
        # Report observed strengths, without treating more defensive actions
        # as proof of overall quality. Compare rate and success separately.
        def pct(p):
            x=p["metrics"][0]["value"]
            if not isinstance(x,str) or "/" not in x:return None
            try:
                w,t=x.split(" ")[0].split("/");return int(w)/int(t)
            except (ValueError,ZeroDivisionError):return None
        x,y=pct(a),pct(b)
        ar,br=a["metrics"][1]["value"],b["metrics"][1]["value"]
        bits=[]
        if x is not None and y is not None:
            if abs(y-x)>=.08:bits.append("Μεγαλύτερη επιτυχία στις μονομαχίες." if y>x else "Μικρότερη επιτυχία στις μονομαχίες.")
            else:bits.append("Παρόμοια καταγεγραμμένη επιτυχία στις μονομαχίες.")
        if isinstance(ar,(int,float)) and isinstance(br,(int,float)) and abs(ar-br)>=.5:
            bits.append("Περισσότερες ανακτήσεις ανά 90′." if br>ar else "Λιγότερες ανακτήσεις ανά 90′.")
        if bits:msg=("Αλλαγή ρόλου. " if kind=="attention" else "")+" ".join(bits)
    pair.update({"summary":msg,"kind":kind})
    return pair

def load_history(db,league,tid,cutoff):
    args=(league,tid,cutoff)
    history=db.execute("""SELECT s.match_id,s.player_id,s.position_code,p.player_name,a.kickoff_utc FROM archive_starters s
        JOIN archive_matches a USING(match_id) JOIN archive_players p USING(player_id)
        WHERE a.season_year=2026 AND a.competition_code=%s AND s.team_id=%s AND a.kickoff_utc<%s""",args).fetchall()
    return history


def load_sources(db,league,tid,cutoff):
    args=(league,tid,cutoff)
    sources={}
    def add(name,rows):
        pool=defaultdict(list)
        for r in rows:
            if r["player_id"] is not None:pool[r["player_id"]].append(r)
        if pool:sources[name]=pool
    if league=="PL" and db.execute("SELECT to_regclass('lineup_fpl_played_metrics') t").fetchone()["t"]:
        add("FPL-Elo",db.execute("""SELECT p.match_id,p.player_id,p.minutes,p.metrics FROM lineup_fpl_played_metrics p JOIN archive_matches a USING(match_id)
        WHERE a.season_year=2026 AND a.competition_code=%s AND p.team_id=%s AND a.kickoff_utc<%s""",args).fetchall())
    if db.execute("SELECT to_regclass('lineup_private_match_stats') t").fetchone()["t"]:
        rows=db.execute("""SELECT p.match_id,p.player_id,p.metrics,(p.metrics->>'minutes_played')::numeric minutes FROM lineup_private_match_stats p JOIN archive_matches a USING(match_id)
        WHERE p.source='11footy' AND p.release_name='11footy-2026-11-10' AND a.season_year=2026 AND a.competition_code=%s AND p.team_id=%s AND a.kickoff_utc<%s""",args).fetchall()
        if db.execute("SELECT to_regclass('lineup_private_sub_stats') t").fetchone()["t"]:
            rows+=db.execute("""SELECT p.match_id,p.player_id,p.metrics,(p.metrics->>'minutes_played')::numeric minutes FROM lineup_private_sub_stats p JOIN archive_matches a USING(match_id)
            WHERE p.release_name='11footy-2026-11-10' AND a.season_year=2026 AND a.competition_code=%s AND p.team_id=%s AND a.kickoff_utc<%s""",args).fetchall()
        add("11footy",rows)
    if db.execute("SELECT to_regclass('soccer_stats_verified_match_players') t").fetchone()["t"]:
        add("Soccer Data",db.execute("""SELECT match_id,canonical_player_id player_id,minutes,jsonb_build_object('goals',goals,'assists',assists,'duels_won',duels_won,'duels_lost',duels_lost,'recoveries',recoveries,'chances_created',key_passes,'saves',saves,'xg',xg,'xa',xa) metrics
        FROM soccer_stats_verified_match_players WHERE season_year=2026 AND competition_code=%s AND team_id=%s AND kickoff_utc<%s AND canonical_player_id IS NOT NULL""",args).fetchall())
    if db.execute("SELECT to_regclass('lineup_espn_player_metrics') t").fetchone()["t"]:
        from espn_player_metrics import SOURCE
        add(SOURCE,db.execute("""SELECT p.match_id,p.player_id,p.minutes,p.metrics
        FROM lineup_espn_player_metrics p JOIN archive_matches a USING(match_id)
        JOIN lineup_espn_stats_state z USING(match_id)
        WHERE z.status='complete' AND a.season_year=2026 AND a.competition_code=%s
        AND p.team_id=%s AND a.kickoff_utc<%s""",args).fetchall())
    return sources


def load(db,league,tid,cutoff,xi,formation):
    result=pairs(current_codes(xi,formation),load_history(db,league,tid,cutoff))
    if not result:return []
    sources=load_sources(db,league,tid,cutoff)
    return [decorate(p,sources) for p in result]
