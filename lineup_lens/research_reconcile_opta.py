"""Research-only reconcile public football roster fingerprints to Opta source rows.
No database credentials or private data in CI; never publish raw Opta data.
Missing values remain null. Match only unique, one-to-one complete starting XIs.
"""
import json,tempfile,re,unicodedata
from pathlib import Path
from collections import defaultdict,Counter
from urllib.request import Request,urlopen
import duckdb
BASE="https://github.com/peteowen1/pannadata/releases/download/opta-latest/"
LEAGUES=dict(PL="EPL",SA="Serie_A",LL="La_Liga",BL="Bundesliga",L1="Ligue_1",GR1="Greek_Super_League",BE1="Belgian_First_Division",DK1="Danish_Superliga",NO1="Eliteserien",NL1="Eredivisie",TR1="Super_Lig",SC1="Scottish_Premiership",SE1="Allsvenskan",UCL="UCL",UEL="UEL",UECL="Conference_League")
FIELDS=["minsPlayed","goals","goalAssist","totalScoringAtt","ontargetScoringAtt","totalAttAssist","totalPass","accuratePass","totalTackle","interception","totalClearance","ballRecovery","duelWon","aerialWon","saves","bigChanceCreated"]
TRANSLATE=str.maketrans({"ß":"ss","ð":"d","đ":"d","ı":"i","ł":"l","ø":"o"})
def tokens(s):
    t="".join(c for c in unicodedata.normalize("NFKD",str(s or "")) if not unicodedata.combining(c)).lower().translate(TRANSLATE)
    return re.findall(r"[a-z0-9]+",t)
def fingerprint(s):
    h=14695981039346656037
    for ch in s:
        h=((h^ord(ch))*1099511628211)&((1<<64)-1)
    return f"{h:016x}"
def teamfp(s):return fingerprint("".join(tokens(s)))
def int_or_none(v):
    try:
        if v is not None and float(v).is_integer():return int(v)
    except (TypeError,ValueError,OverflowError):pass
    return None
def profile(p):
    forms=[p.get(k) for k in ("player_name","known_name","last_name","short_last_name")]
    full_names=[]
    for a in ("first_name","short_first_name"):
        for b in ("last_name","short_last_name"):
            if p.get(a) and p.get(b):
                f=str(p[a])+" "+str(p[b])
                forms.append(f);full_names.append(f)
    if p.get("player_name"):full_names.append(p["player_name"])
    exact={fingerprint("".join(tokens(f))) for f in forms if tokens(f)}
    initials=set()
    for f in full_names:
        t=tokens(f)
        if len(t)>1:
            initials.update(fingerprint(t[0][0]+":"+last) for last in t[1:] if len(last)>=3)
    return int_or_none(p.get("shirt_number")),exact,initials
def reconcile_side(xi,source):
    if len(xi)!=11 or len(source)!=11 or len({str(p["player_id"]) for p in source})!=11:
        return None,0
    profiles=[profile(p) for p in source]
    resolved=[]
    for jersey,exact,initial in xi:
        j=int_or_none(jersey)
        matches=[]
        for i,(src_j,src_exact,src_initial) in enumerate(profiles):
            if j is not None and src_j!=j:continue
            if exact in src_exact or (j is not None and initial is not None and initial in src_initial):
                matches.append(i)
        if len(matches)==1:resolved.append(matches[0])
        else:resolved.append(None)
    n=sum(i is not None for i in resolved)
    if n==11 and len(set(resolved))==11:return [source[i] for i in resolved],11
    return None,n
def download(name,path,maxbytes):
    with urlopen(Request(BASE+name,headers={"User-Agent":"LineupLens-Personal-Research/1.0"}),timeout=90) as r,path.open("wb") as w:
        n=0
        while (chunk:=r.read(1024*1024)):
            n+=len(chunk)
            if n>maxbytes:raise ValueError("download limit")
            w.write(chunk)
def rows(db,sql,params=()):
    cur=db.execute(sql,params)
    keys=[x[0] for x in cur.description]
    return [dict(zip(keys,r)) for r in cur.fetchall()]
def main():
    directory=Path(__file__).parent/"research_fingerprints"
    canonical=[r for p in sorted(directory.glob("part*.json")) for r in json.loads(p.read_text())]
    assert len({r[0] for r in canonical})==len(canonical)
    with tempfile.TemporaryDirectory() as td:
        db=duckdb.connect()
        db.execute("SET memory_limit='600MB'")
        for alias,name,limit in [("stats","opta_player_stats.parquet",500_000_000),("fixtures","opta_fixtures.parquet",30_000_000),("xm","opta_xmetrics_bymatch.parquet",450_000_000)]:
            p=Path(td)/name
            download(name,p,limit)
            db.execute(f"CREATE VIEW {alias} AS SELECT * FROM read_parquet('{p}')")
        for code in sorted({r[1] for r in canonical}):
            archive=[r for r in canonical if r[1]==code]
            if code not in LEAGUES:
                print("AUDIT "+json.dumps({"code":code,"archive_matches":len(archive),"source_unavailable":True}),flush=True)
                continue
            comp=LEAGUES[code];season="2026" if code in ("NO1","SE1") else "2026-2027"
            source=rows(db,"SELECT * FROM fixtures WHERE competition=? AND season=? AND lower(match_status)='played'",[comp,season])
            stats=rows(db,"SELECT match_id,team_id,player_id,player_name,known_name,first_name,last_name,short_first_name,short_last_name,shirt_number,"+",".join(FIELDS)+" FROM stats WHERE competition=? AND season=? AND try_cast(gameStarted as integer)=1",[comp,season])
            xs=rows(db,"SELECT match_id,team_id,player_id,xg,xa FROM xm WHERE competition=? AND season=?",[comp,season])
            by_date=defaultdict(list);by_side=defaultdict(list);xlookup=defaultdict(list)
            for f in source:by_date[str(f["match_date"])[:10]].append(f)
            for p in stats:by_side[(str(p["match_id"]),str(p["team_id"]))].append(p)
            for p in xs:xlookup[(str(p["match_id"]),str(p["team_id"]),str(p["player_id"]))].append(p)
            counts=Counter();metrics=Counter();verified=[];fail=[];used=set()
            for reference,_,date,homehash,awayhash,hg,ag,hxi,axi in archive:
                candidates=[];best=0
                for f in by_date.get(date,[]):
                    if hg is not None and ag is not None and (int_or_none(f["home_score"])!=int_or_none(hg) or int_or_none(f["away_score"])!=int_or_none(ag)):continue
                    mid=str(f["match_id"])
                    home,hn=reconcile_side(hxi,by_side[(mid,str(f["home_team_id"]))])
                    away,an=reconcile_side(axi,by_side[(mid,str(f["away_team_id"]))])
                    names_agree=teamfp(f["home_team"])==homehash and teamfp(f["away_team"])==awayhash
                    if names_agree or hn+an>=15:best=max(best,hn+an)
                    if home is not None and away is not None:
                        if not names_agree:counts["team_alias_by_complete_xi"]+=1
                        candidates.append((mid,home+away))
                if len(candidates)!=1 or candidates[0][0] in used:
                    counts["unmatched_or_ambiguous"]+=1;fail.append([reference,best,len(candidates)]);continue
                mid,players=candidates[0];used.add(mid)
                if len({str(p["player_id"]) for p in players})!=22:
                    fail.append([reference,22,-1]);continue
                counts["verified_matches"]+=1
                verified.append(reference)
                for p in players:
                    for m in FIELDS:metrics[m]+=int(p.get(m) is not None)
                    k=(mid,str(p["team_id"]),str(p["player_id"]))
                    vals=xlookup.get(k,[])
                    if len(vals)==1:
                        for m in ("xg","xa"):metrics[m]+=int(vals[0].get(m) is not None)
                if all(len(xlookup.get((mid,str(p["team_id"]),str(p["player_id"])),[]))==1 and all(xlookup[(mid,str(p["team_id"]),str(p["player_id"]))][0].get(m) is not None for m in ("xg","xa")) for p in players):counts["complete_xg_xa_matches"]+=1
            print("AUDIT "+json.dumps({"code":code,"archive_matches":len(archive),"verified_matches":counts["verified_matches"],"starter_rows":22*counts["verified_matches"],"complete_xg_xa_matches":counts["complete_xg_xa_matches"],"metric_nonnull":dict(metrics),"verified_refs":verified,"failures":fail,"team_alias_matches":counts["team_alias_by_complete_xi"]}),flush=True)
if __name__=="__main__":main()
