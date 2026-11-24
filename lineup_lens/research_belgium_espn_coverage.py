"""Read-only coverage audit for Belgium's 2026/27 ESPN Pro League results.

No Neon writes, paid calls or service changes. Check match-day starter=True
on both teams, identify missing data and position codes before any import.
"""
from __future__ import annotations
from collections import Counter
from urllib.request import Request,urlopen
from datetime import datetime, timezone
import json,time

BASE="https://site.api.espn.com/apis/site/v2/sports/soccer/bel.1"
CUTOFF="2026-11-24"
MAX_EVENTS=225

def fetch(path):
    req=Request(BASE+path,headers={"User-Agent":"LineupLens-Private-Research/1.0"})
    with urlopen(req,timeout=25) as result:
        b=result.read(2_300_001)
    if len(b)>2_300_000:raise ValueError("ESPN response unexpectedly large")
    return json.loads(b)

def discover():
    doc=fetch("/scoreboard?dates=20260801&limit=100")
    leagues=doc.get("leagues",[])
    print("LEAGUE",[{"slug":x.get("slug"),"name":x.get("name"),"season":x.get("season"),"days":len(x.get("calendar") or [])} for x in leagues],flush=True)
    assert len(leagues)==1 and leagues[0].get("slug")=="bel.1"
    assert (leagues[0].get("season") or {}).get("year")==2026
    days=sorted({x[:10].replace("-","") for x in leagues[0].get("calendar",[])
                 if "2026-07-01"<=x[:10]<CUTOFF})
    print("CALENDAR_DAYS",len(days),days[:6],days[-6:],flush=True)
    events={}
    for i,day in enumerate(days):
        info=fetch("/scoreboard?dates="+day+"&limit=50")
        for match in info.get("events") or []:
            if not match.get("status",{}).get("type",{}).get("completed"):continue
            if not "2026-07-01"<=match.get("date","")[:10]<CUTOFF:continue
            event_id=str(match.get("id") or "")
            if not event_id.isdigit():continue
            events[event_id]=match
        if len(events)>MAX_EVENTS:raise ValueError("ESPN unusually large match count")
        if i%6==0:print("CALENDAR_PROGRESS",i+1,len(days),"games",len(events),flush=True)
        time.sleep(0.15)
    print("FINISHED_GAMES",len(events),flush=True)
    return sorted(events.values(),key=lambda m:(m.get("date",""),int(m["id"])))

def run():
    matches=discover()
    if len(matches)<50:raise ValueError("Too few completed fixtures for coverage audit")
    team_matches=Counter()
    positions=Counter()
    problems=[]
    unknown_positions=[]
    for idx,event in enumerate(matches):
        eid=event["id"]
        try:summary=fetch("/summary?event="+str(eid))
        except Exception as exc:
            problems.append((eid,"summary_fetch",str(exc)[:120]))
            continue
        groups=summary.get("rosters") or []
        comps=(event.get("competitions") or [{}])[0].get("competitors") or []
        expected={x.get("homeAway"):str(x.get("team",{}).get("id")) for x in comps}
        errors=[]
        names={}
        if len(groups)!=2 or set(expected)!={"home","away"}:
            errors.append("not 2 matching team sheets")
        for side in ("home","away"):
            if errors:break
            g=next((r for r in groups if r.get("homeAway")==side),None)
            if not g or str(g.get("team",{}).get("id"))!=expected.get(side):
                errors.append(side+" missing/mismatched team");continue
            xi=[p for p in (g.get("roster") or []) if p.get("starter") is True]
            ids=[str(p.get("athlete",{}).get("id") or "") for p in xi]
            nms=[(p.get("athlete",{}).get("displayName") or "").strip() for p in xi]
            codes=[(p.get("position") or {}).get("abbreviation") for p in xi]
            positions.update(codes)
            if len(xi)!=11 or len(set(ids))!=11 or not all(a.isdigit() for a in ids) or not all(nms):
                errors.append(side+" incorrect 11/names: "+str(len(xi)));continue
            if not(codes.count("G")==1 or all(c=="SUB" for c in codes)):
                errors.append(side+" positions "+str(codes));continue
            if all(c=="SUB" for c in codes):unknown_positions.append((eid,side))
            names[side]=g["team"]["displayName"]
        if errors:
            problems.append((eid,event.get("date"),event.get("name"),errors))
        else:
            for name in names.values():team_matches[name]+=1
        if idx%20==0:print("AUDITED",idx+1,len(matches),"errors",len(problems),flush=True)
        time.sleep(0.15)
    print("RESULT",json.dumps({"season":"2026-27","finished":len(matches),
          "matches_with_22_starters":len(matches)-len(problems),
          "incomplete_or_inconsistent":len(problems),"teams":len(team_matches),
          "first":matches[0]["date"][:10],"latest":matches[-1]["date"][:10],
          "min_matches_per_team":min(team_matches.values()) if team_matches else None,
          "max_matches_per_team":max(team_matches.values()) if team_matches else None,
          "unknown_position_sheets":len(unknown_positions)},ensure_ascii=False),flush=True)
    print("POSITION_CODES",dict(positions),flush=True)
    print("TEAM_COUNTS",dict(sorted(team_matches.items())),flush=True)
    print("PROBLEMS",problems[:30],flush=True)
    print("UNKNOWN_POSITION_SHEETS",unknown_positions[:35],flush=True)

if __name__=="__main__":run()
