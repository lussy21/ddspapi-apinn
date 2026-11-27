"""Research-only reconcile 11footy public XIs to canonical roster fingerprints.
No credentials, no raw source rows in logs. 11footy CC BY-NC 4.0 attribution.
"""
import csv,io,json,lzma,sqlite3,tempfile,zipfile,concurrent.futures
from pathlib import Path
from collections import defaultdict,Counter
from urllib.request import urlopen,Request
from research_reconcile_opta import reconcile_side,teamfp
BASE="https://github.com/fm-devlab/11footy-dataset/releases/download/11footy-2026-11-10/"
LEAGUES={"PL":"england.premier-league","SA":"italy.serie-a","LL":"spain.la-liga","BL":"germany.bundesliga","L1":"france.ligue-1","DE2":"germany.2-bundesliga","UCL":"european-cups.champions-league","UEL":"european-cups.europa-league","UECL":"european-cups.conference-league"}
METRICS=["minutes_played","goals","assists","shots","shots_on_target","key_passes","fouls_committed","fouls_suffered","yellow_cards","red_cards","saves","goals_conceded"]
def download(name,path,limit):
    with urlopen(Request(BASE+name,headers={"User-Agent":"LineupLens-Personal-Research/1.0"}),timeout=90) as r,path.open("wb") as w:
        n=0
        while (chunk:=r.read(1024*1024)):
            n+=len(chunk)
            if n>limit:raise ValueError("download limit")
            w.write(chunk)
def audit(code,slug,archive,people):
    try:
        with tempfile.TemporaryDirectory() as td:
            compressed=Path(td)/"source.xz"; path=Path(td)/"source.db"
            download(slug+".db.xz",compressed,60_000_000)
            with lzma.open(compressed,"rb") as r,path.open("wb") as w:
                n=0
                while (chunk:=r.read(1024*1024)):
                    n+=len(chunk)
                    if n>400_000_000:raise ValueError("uncompressed size limit")
                    w.write(chunk)
            db=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)
            db.row_factory=sqlite3.Row
            try:
                fixtures=[dict(r) for r in db.execute("""SELECT m.match_id,m.local_date,m.home_team_id,m.away_team_id,h.name home_team,a.name away_team
                FROM matches m JOIN seasons s ON m.season_id=s.season_id
                JOIN teams h ON h.team_id=m.home_team_id JOIN teams a ON a.team_id=m.away_team_id
                WHERE s.season=2026 AND m.status='played'""")]
                by_date=defaultdict(list);by_side=defaultdict(list)
                for f in fixtures:by_date[str(f["local_date"])[:10]].append(f)
                mids={f["match_id"] for f in fixtures}
                for p in db.execute("""SELECT p.match_id,p.team_id,p.player_id,p.shirt_number,"""+",".join("s."+m for m in METRICS)+"""
                FROM match_players p JOIN matches m USING(match_id) JOIN seasons sn USING(season_id)
                LEFT JOIN player_match_statistics s ON s.match_id=p.match_id AND s.team_id=p.team_id AND s.player_id=p.player_id
                WHERE sn.season=2026 AND m.status='played' AND p.started=1"""):
                    p=dict(p);p["player_name"]=people.get(int(p["player_id"]),"")
                    if p["match_id"] in mids:by_side[(p["match_id"],p["team_id"])].append(p)
                verified=[];fail=[];used=set();metrics=Counter()
                for reference,_,date,homehash,awayhash,hg,ag,hxi,axi in archive:
                    candidates=[];best=0
                    for f in by_date.get(date,[]):
                        mid=f["match_id"];h,hn=reconcile_side(hxi,by_side[(mid,f["home_team_id"])]);a,an=reconcile_side(axi,by_side[(mid,f["away_team_id"])])
                        if teamfp(f["home_team"])==homehash and teamfp(f["away_team"])==awayhash or hn+an>=15:best=max(best,hn+an)
                        if h is not None and a is not None and all(p["minutes_played"] is not None and p["minutes_played"]>0 for p in h+a):candidates.append((mid,h+a))
                    if len(candidates)!=1 or candidates[0][0] in used:fail.append([reference,best,len(candidates)]);continue
                    mid,players=candidates[0];used.add(mid);verified.append(reference)
                    for p in players:
                        for k in METRICS:metrics[k]+=int(p.get(k) is not None)
                return {"code":code,"archive_matches":len(archive),"verified_matches":len(verified),"starter_rows":22*len(verified),"metric_nonnull":dict(metrics),"verified_refs":verified,"failures":fail}
            finally:db.close()
    except Exception as exc:return {"code":code,"error":str(exc)}
def main():
    directory=Path(__file__).parent/"research_fingerprints"
    canonical=[r for p in sorted(directory.glob("part*.json")) for r in json.loads(p.read_text())]
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/"players.csv.zip";download("players.csv.zip",path,8_000_000)
        with zipfile.ZipFile(path) as z:
            name=next(x for x in z.namelist() if x.split("/")[-1]=="players.csv")
            with z.open(name) as f:people={int(x["player_id"]):x["name"] for x in csv.DictReader(io.TextIOWrapper(f,encoding="utf-8-sig"))}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            tasks=[pool.submit(audit,code,slug,[r for r in canonical if r[1]==code],people) for code,slug in LEAGUES.items()]
            for task in tasks:print("AUDIT "+json.dumps(task.result()),flush=True)
if __name__=="__main__":main()
