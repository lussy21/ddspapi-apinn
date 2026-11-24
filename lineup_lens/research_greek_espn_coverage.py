"""Read-only audit: ALL ESPN Greek Super League 2026/27 games through 23 Nov.

The scoreboard's published 2026/27 calendar defines coverage. Only FINISHED
matches and starting players marked starter=True are accepted. Does not write
to Neon, Render, paid API, GitHub artifacts or any user spreadsheet.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
from urllib.request import Request,urlopen
import json,time

API="https://site.api.espn.com/apis/site/v2/sports/soccer/gre.1"
CUTOFF="2026-11-24"
MAX_EVENTS=150
def fetch(route):
    req=Request(API+route,headers={"User-Agent":"LineupLens-Private-Research/1.0"})
    with urlopen(req,timeout=20) as res:
        b=res.read(2300000)
    if len(b)>=2300000:raise ValueError("ESPN JSON too large")
    return json.loads(b)

def discover():
    base=fetch("/scoreboard?dates=20260822&limit=50")
    leagues=base.get("leagues") or []
    assert len(leagues)==1 and leagues[0].get("slug")=="gre.1", "wrong league"
    days=sorted({x[:10].replace("-","") for x in leagues[0].get("calendar",[]) if "2026-08-01" <= x[:10] < CUTOFF})
    print("CALENDAR_DAYS",len(days),days,flush=True)
    matches={}
    for i,day in enumerate(days):
        payload=fetch("/scoreboard?dates="+day+"&limit=50")
        events=payload.get("events",[])
        if i%5==0: print("DISCOVERED",i+1,"/",len(days),"games",len(matches),flush=True)
        for event in events:
            status=event.get("status",{}).get("type",{})
            if not status.get("completed"):continue
            if not event.get("date","").startswith("2026-"):continue
            event_id=str(event.get("id",""))
            if not event_id.isdigit():continue
            matches[event_id]=event
        if len(matches)>MAX_EVENTS:raise ValueError("Unexpected excess events")
        time.sleep(0.13)
    print("DISCOVERY_TOTAL",len(matches),flush=True)
    return sorted(matches.values(),key=lambda x:(x.get("date",""),int(x["id"])))

def run():
    matches=discover()
    codes=Counter();valid=[];bad=[];team_games=Counter();missing=Counter()
    if len(matches)<30:raise ValueError("Too few games to prove season coverage")
    for i,e in enumerate(matches):
        eid=e["id"]
        try: summary=fetch("/summary?event="+str(eid))
        except Exception as ex:
            bad.append((eid,"fetch "+str(ex)[:80]));continue
        rosters=summary.get("rosters") or []
        competitors=e.get("competitions",[{}])[0].get("competitors") or []
        expected={x.get("homeAway"):str(x.get("team",{}).get("id")) for x in competitors}
        if len(rosters)!=2 or len(expected)!=2:
            bad.append((eid,"missing roster/competitors"));continue
        failures=[];sides={}
        for side in ("home","away"):
            group=next((x for x in rosters if x.get("homeAway")==side),None)
            if not group or str(group.get("team",{}).get("id"))!=expected.get(side):
                failures.append(side+": wrong team")
                continue
            players=[p for p in (group.get("roster") or []) if p.get("starter") is True]
            ids=[str(p.get("athlete",{}).get("id") or "") for p in players]
            names=[p.get("athlete",{}).get("displayName","").strip() for p in players]
            abbrs=[p.get("position",{}).get("abbreviation") for p in players]
            for ab in abbrs:codes[ab]+=1
            if len(players)!=11 or len(set(ids))!=11 or not all(x.isdigit() for x in ids) or not all(names):
                failures.append(side+": invalid XI n="+str(len(players)))
                continue
            if abbrs.count("G")!=1 or any(not isinstance(code,str) or not code for code in abbrs):
                failures.append(side+": invalid positions="+str(abbrs))
                continue
            sides[side]=group
        if failures:
            bad.append((eid,e.get("date"),e.get("name"),failures))
        else:
            valid.append(e)
            for group in sides.values():
                team_games[group["team"]["displayName"]]+=1
        if i%15==0:print("CHECKED",i+1,"/",len(matches),"valid",len(valid),"missing",len(bad),flush=True)
        time.sleep(0.14)
    print("FULL_SEASON_AUDIT",json.dumps({
        "found_finished_games":len(matches),"valid_22_starters":len(valid),
        "invalid_games":len(bad),"teams":len(team_games),
        "min_games_per_team":min(team_games.values()) if team_games else 0,
        "max_games_per_team":max(team_games.values()) if team_games else 0,
        "first_day":matches[0]["date"][:10],
        "last_day":matches[-1]["date"][:10],
    },ensure_ascii=False),flush=True)
    print("POSITION_CODES",dict(codes),flush=True)
    print("TEAM_COUNTS",dict(sorted(team_games.items())),flush=True)
    print("MISSING_SAMPLE",bad[:15],flush=True)
    print("VALID_SAMPLE",[(x["id"],x.get("date"),x.get("name")) for x in valid[:4]],flush=True)
if __name__=="__main__":run()
