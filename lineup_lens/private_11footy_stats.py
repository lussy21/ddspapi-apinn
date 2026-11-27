"""Private noncommercial 11footy player match stats importer.
Source: https://github.com/fm-devlab/11footy-dataset (CC BY-NC 4.0).
Only writes an independent staging table. Never edits archive XIs or Soccer Data.
Run with LINEUP_DATABASE_URL on the existing private Lineup Lens host.
"""
import json,lzma,sqlite3,tempfile,time,unicodedata,re
from collections import defaultdict,Counter
from pathlib import Path
import season_db
import archive_11footy as source

RELEASE=source.RELEASE
SPLITS={**source.SPLITS,"DE2":"germany.2-bundesliga.db.xz",
 "UCL":"european-cups.champions-league.db.xz",
 "UEL":"european-cups.europa-league.db.xz",
 "UECL":"european-cups.conference-league.db.xz"}
FIELDS=("minutes_played","goals","assists","shots","shots_on_target","key_passes","fouls_committed","fouls_suffered","yellow_cards","red_cards","saves","goals_conceded")
LOCK=614439856
TRANS=str.maketrans({"ß":"ss","ð":"d","đ":"d","ı":"i","ł":"l","ø":"o"})
def norm(s):
    return "".join(c for c in unicodedata.normalize("NFKD",str(s or "")).lower().translate(TRANS) if c.isascii() and c.isalnum())
def jersey(v):
    try:return int(v) if v is not None else None
    except (TypeError,ValueError):return None
def valid_metrics(p):
    for k in FIELDS:
        v=p[k]
        if v is not None and (type(v) not in (int,float) or not 0<=v<=10000):return False
    return type(p["minutes_played"]) in (int,float) and 0<p["minutes_played"]<=150
def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS lineup_private_match_stats (
      source text NOT NULL, release_name text NOT NULL,
      match_id integer NOT NULL, team_id integer NOT NULL, player_id integer NOT NULL,
      provider_match_id text NOT NULL, provider_player_id text NOT NULL,
      metrics jsonb NOT NULL, imported_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(source,release_name,match_id,team_id,player_id),
      FOREIGN KEY(match_id,team_id,player_id) REFERENCES archive_starters(match_id,team_id,player_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS lineup_private_stats_import_state (
       source text NOT NULL, release_name text NOT NULL, competition_code text NOT NULL,
       matched_matches integer NOT NULL, player_rows integer NOT NULL,
       unmatched_matches integer NOT NULL, completed_at timestamptz NOT NULL DEFAULT now(),
       PRIMARY KEY(source,release_name,competition_code))""")
def read_source(path,people):
    con=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)
    con.row_factory=sqlite3.Row
    try:
        games=[dict(r) for r in con.execute("""SELECT m.match_id,m.local_date,m.home_team_id,m.away_team_id,h.name home_name,a.name away_name
          FROM matches m JOIN seasons s ON s.season_id=m.season_id
          JOIN teams h ON h.team_id=m.home_team_id JOIN teams a ON a.team_id=m.away_team_id
          WHERE s.season=2026 AND m.status='played'""")]
        sides=defaultdict(list)
        mids={r["match_id"] for r in games}
        sql="""SELECT p.match_id,p.team_id,p.player_id,p.shirt_number,"""+",".join("s."+m for m in FIELDS)+"""
          FROM match_players p JOIN matches m USING(match_id) JOIN seasons sn USING(season_id)
          LEFT JOIN player_match_statistics s ON s.match_id=p.match_id AND s.team_id=p.team_id AND s.player_id=p.player_id
          WHERE sn.season=2026 AND m.status='played' AND p.started=1"""
        for p in con.execute(sql):
            p=dict(p);p["player_name"]=people.get(int(p["player_id"]),"")
            if p["match_id"] in mids:sides[(p["match_id"],p["team_id"])].append(p)
        return games,sides
    finally:con.close()
def match_side(canonical,provider,direct=False):
    if len(canonical)!=11 or len(provider)!=11 or len({p["player_id"] for p in provider})!=11:return None
    result=[]
    for a in canonical:
        j=jersey(a["jersey_number"])
        matches=[p for p in provider if
          (p["player_id"]==a["player_id"] if direct else
            norm(a["player_name"])==norm(p["player_name"]) and bool(norm(p["player_name"]))) and
          (j is None or j==jersey(p["shirt_number"])) and valid_metrics(p)]
        if len(matches)!=1:return None
        result.append((a,matches[0]))
    return result if len({p["player_id"] for _,p in result})==11 else None
def reconcile(canonical,starters,games,sides):
    bydate=defaultdict(list)
    for f in games:bydate[str(f["local_date"])[:10]].append(f)
    used=set();out=[];miss=[]
    for a in canonical:
        mid=a["match_id"];direct=a["source_release"]==RELEASE
        home=starters[(mid,a["home_team_id"])];away=starters[(mid,a["away_team_id"])]
        candidates=[]
        for f in bydate.get(str(a["local_date"])[:10],[]):
            if direct and f["match_id"]!=mid:continue
            if direct and (a["home_team_id"],a["away_team_id"])!=(f["home_team_id"],f["away_team_id"]):continue
            h=match_side(home,sides[(f["match_id"],f["home_team_id"])],direct)
            w=match_side(away,sides[(f["match_id"],f["away_team_id"])],direct)
            if h is not None and w is not None and len({p["player_id"] for _,p in h+w})==22:candidates.append((f,h+w))
        if len(candidates)!=1 or candidates[0][0]["match_id"] in used:miss.append(mid);continue
        f,rows=candidates[0];used.add(f["match_id"])
        out.extend((mid,c["team_id"],c["player_id"],str(f["match_id"]),str(p["player_id"]),
                     json.dumps({k:p[k] for k in FIELDS},allow_nan=False)) for c,p in rows)
    return out,miss
def import_league(code,log=print):
    if code not in SPLITS:raise ValueError("unsupported competition")
    with season_db.db() as db:
        setup(db)
        if db.execute("SELECT 1 FROM lineup_private_stats_import_state WHERE source='11footy' AND release_name=%s AND competition_code=%s",(RELEASE,code)).fetchone():return None
        games=db.execute("""SELECT * FROM archive_matches WHERE season_year=2026 AND competition_code=%s ORDER BY local_date,match_id""",(code,)).fetchall()
        starters=defaultdict(list)
        for r in db.execute("""SELECT s.*,p.player_name FROM archive_starters s JOIN archive_players p USING(player_id)
          JOIN archive_matches a USING(match_id) WHERE a.season_year=2026 AND a.competition_code=%s""",(code,)).fetchall():
            starters[(r["match_id"],r["team_id"])].append(r)
    if not games:return None
    with tempfile.TemporaryDirectory() as td:
        folder=Path(td);people=source.load_people(folder)
        compressed=folder/"source.xz";path=folder/"source.db"
        source._download(source.BASE_URL+SPLITS[code],compressed,60_000_000)
        with lzma.open(compressed,"rb") as r,path.open("wb") as w:
            n=0
            while (chunk:=r.read(1024*1024)):
                n+=len(chunk)
                if n>400_000_000:raise ValueError("uncompressed archive too large")
                w.write(chunk)
        src,sides=read_source(path,people)
        rows,missing=reconcile(games,starters,src,sides)
    counts=Counter(r[0] for r in rows)
    assert all(n==22 for n in counts.values())
    if not rows:raise ValueError("No complete canonical matches")
    with season_db.db() as db:
        setup(db)
        if not db.execute("SELECT pg_try_advisory_xact_lock(%s) ok",(LOCK,)).fetchone()["ok"]:return None
        with db.cursor() as cur:
            cur.executemany("""INSERT INTO lineup_private_match_stats
              (source,release_name,match_id,team_id,player_id,provider_match_id,provider_player_id,metrics)
              VALUES('11footy',%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING""",
              [(RELEASE,*r) for r in rows])
        actual=db.execute("""SELECT count(*) n,count(distinct match_id) matches FROM lineup_private_match_stats
          WHERE source='11footy' AND release_name=%s AND match_id IN (SELECT match_id FROM archive_matches WHERE competition_code=%s AND season_year=2026)""",(RELEASE,code)).fetchone()
        if actual["n"]!=len(rows) or actual["matches"]!=len(counts):raise ValueError("Stored rows differ from validated rows")
        db.execute("""INSERT INTO lineup_private_stats_import_state
          (source,release_name,competition_code,matched_matches,player_rows,unmatched_matches)
          VALUES('11footy',%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",(RELEASE,code,len(counts),len(rows),len(missing)))
    log(f"Private 11footy stats {code}: {len(counts)} matches, {len(rows)} starters, {len(missing)} gaps")
    return {"competition":code,"matches":len(counts),"rows":len(rows),"missing":len(missing)}
def run(log=print):
    # Sequential; bounded disk usage; no API quota and no new service.
    for code in SPLITS:
        try:import_league(code,log=log)
        except Exception as e:log(f"Private 11footy stats {code}: {type(e).__name__}")
        time.sleep(3)
if __name__=="__main__":run()
