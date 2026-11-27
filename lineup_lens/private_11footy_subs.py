"""Import played substitutes from the same licensed 11footy snapshot.
Fixture/team/player anchors come ONLY from the already verified 22 starter rows.
Private noncommercial CC BY-NC 4.0, no paid requests or edits to archive XIs.
"""
import json,lzma,sqlite3,tempfile,time
from pathlib import Path
from collections import defaultdict,Counter
import season_db
import private_11footy_stats as src
from archive_11footy import load_people,_download,BASE_URL
LOCK=614439857
ORDER=("PL","LL","BL","SA","L1","DE2","UCL","UEL","UECL")
def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS lineup_private_sub_stats (
      release_name text NOT NULL, match_id integer NOT NULL REFERENCES archive_matches(match_id),
      team_id integer NOT NULL REFERENCES archive_teams(team_id),
      provider_player_id text NOT NULL, player_id integer REFERENCES archive_players(player_id),
      player_name text NOT NULL, jersey_number integer, metrics jsonb NOT NULL,
      PRIMARY KEY(release_name,match_id,team_id,provider_player_id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS lineup_private_sub_state (
      release_name text NOT NULL, competition_code text NOT NULL,
      covered_matches integer NOT NULL, sub_rows integer NOT NULL, linked_rows integer NOT NULL,
      completed_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(release_name,competition_code))""")
def reconcile_subs(anchors,rosters,people):
    """Match both source sides to exactly 11 verified source starter IDs.
    Reuse a canonical player ID only when the verified anchors agree.
    """
    bymatch=defaultdict(list);identity=defaultdict(set)
    for a in anchors:
        bymatch[int(a["provider_match_id"])].append(a)
        identity[(a["team_id"],int(a["provider_player_id"]))].add(a["player_id"])
    out=[];covered=0
    for smid,aa in bymatch.items():
        if len(aa)!=22 or len({a["match_id"] for a in aa})!=1:continue
        groups=defaultdict(set)
        for a in aa:groups[a["team_id"]].add(int(a["provider_player_id"]))
        source=rosters.get(smid,{})
        if len(groups)!=2 or len(source)!=2:continue
        pairs={}
        for tid,ids in groups.items():
            hits=[st for st,rr in source.items() if {p["player_id"] for p in rr if p["started"]==1}==ids and len(ids)==11]
            if len(hits)==1:pairs[tid]=hits[0]
        if len(pairs)!=2 or len(set(pairs.values()))!=2:continue
        rows=[];valid=True
        for tid,st in pairs.items():
            rr=source[st]
            if len({p["player_id"] for p in rr})!=len(rr):valid=False;break
            for p in rr:
                if p["started"]!=0 or not src.valid_metrics(p):continue
                sid=p["player_id"];name=people.get(sid,"")
                if not name:continue
                candidates=identity.get((tid,sid),set())
                canonical=next(iter(candidates)) if len(candidates)==1 else None
                if canonical in {a["player_id"] for a in aa}:valid=False;break
                rows.append((src.RELEASE,aa[0]["match_id"],tid,str(sid),canonical,name,src.jersey(p["shirt_number"]),
                    json.dumps({k:p[k] for k in src.FIELDS},allow_nan=False)))
            if not valid:break
        if valid:out.extend(rows);covered+=1
    return out,covered
def import_league(code):
    with season_db.db() as db:
        setup(db)
        if db.execute("SELECT 1 FROM lineup_private_sub_state WHERE release_name=%s AND competition_code=%s",(src.RELEASE,code)).fetchone():return
        aa=db.execute("""SELECT p.match_id,p.team_id,p.player_id,p.provider_match_id,p.provider_player_id
          FROM lineup_private_match_stats p JOIN archive_matches a USING(match_id)
          WHERE p.source='11footy' AND p.release_name=%s AND a.competition_code=%s AND a.season_year=2026""",(src.RELEASE,code)).fetchall()
    if not aa:return
    with tempfile.TemporaryDirectory() as td:
        folder=Path(td);people=load_people(folder);compressed=folder/"a.xz";path=folder/"a.db"
        _download(BASE_URL+src.SPLITS[code],compressed,60_000_000)
        with lzma.open(compressed,"rb") as r,path.open("wb") as w:
            n=0
            while (chunk:=r.read(1048576)):
                n+=len(chunk)
                if n>400_000_000:raise ValueError("archive size limit")
                w.write(chunk)
        con=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True);con.row_factory=sqlite3.Row
        rosters=defaultdict(lambda:defaultdict(list))
        try:
            sql="""SELECT p.match_id,p.team_id,p.player_id,p.shirt_number,p.started,"""+",".join("s."+m for m in src.FIELDS)+"""
                FROM match_players p JOIN matches m USING(match_id) JOIN seasons sn USING(season_id)
                LEFT JOIN player_match_statistics s ON s.match_id=p.match_id AND s.team_id=p.team_id AND s.player_id=p.player_id
                WHERE sn.season=2026 AND m.status='played'"""
            mids={int(a["provider_match_id"]) for a in aa}
            for p in con.execute(sql):
                if p["match_id"] in mids:rosters[p["match_id"]][p["team_id"]].append(dict(p))
        finally:con.close()
        rows,covered=reconcile_subs(aa,rosters,people)
    if not rows or not covered:raise ValueError("no verified played substitutes")
    with season_db.db() as db:
        setup(db)
        if not db.execute("SELECT pg_try_advisory_xact_lock(%s) ok",(LOCK,)).fetchone()["ok"]:return
        with db.cursor() as cur:
            cur.executemany("""INSERT INTO lineup_private_sub_stats
              (release_name,match_id,team_id,provider_player_id,player_id,player_name,jersey_number,metrics)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING""",rows)
        db.execute("""INSERT INTO lineup_private_sub_state VALUES(%s,%s,%s,%s,%s,now()) ON CONFLICT DO NOTHING""",
                   (src.RELEASE,code,covered,len(rows),sum(r[4] is not None for r in rows)))
    print(f"11footy played subs {code}: {covered} matches, {len(rows)} rows, {sum(r[4] is not None for r in rows)} linked",flush=True)
def run():
    for code in ORDER:
        try:import_league(code)
        except Exception as exc:print(f"Played substitutes {code} held: {type(exc).__name__}",flush=True)
        time.sleep(2)
