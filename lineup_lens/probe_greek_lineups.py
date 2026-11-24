"""Read-only, bounded ESPN Greece Super League 2026/27 starter coverage probe.

Test historical finished fixtures and one game summary; DO NOT import
a provider roster unless both teams have 11 confirmed starters.
"""
import json
import urllib.error
import urllib.request

BASE="https://site.api.espn.com/apis/site/v2/sports/soccer/gre.1"
HEADERS={"User-Agent":"LineupLens-Private-Research/1.0 (source-audit)"}
def fetch(route):
    req=urllib.request.Request(BASE+route,headers=HEADERS)
    with urllib.request.urlopen(req,timeout=16) as r:
        data=r.read(2200000)
        if len(data)>=2200000:raise ValueError("Oversized JSON")
        return json.loads(data)

def run():
    first_finished=None
    for day in ["20260830","20260912","20261018","20261121"]:
        try:
            d=fetch("/scoreboard?dates="+day+"&limit=50")
        except Exception as e:
            print("SCOREBOARD_ERROR",day,type(e).__name__,str(e)[:180],flush=True)
            continue
        arr=d.get("events",[])
        print("SCOREBOARD",day,"league",[(x.get("slug"),x.get("name")) for x in d.get("leagues",[])],
              "events",len(arr),flush=True)
        for evt in arr[:5]:
            comp=evt.get("competitions",[{}])[0]
            print("EVENT",evt.get("id"),evt.get("date"),evt.get("name"),
                  evt.get("status",{}).get("type",{}).get("name"),
                  [(c.get("homeAway"),c.get("team",{}).get("id"),c.get("team",{}).get("displayName")) for c in comp.get("competitors",[])],flush=True)
        if first_finished is None:
            first_finished=next((e for e in arr if e.get("status",{}).get("type",{}).get("completed")),None)
    if first_finished is None:
        print("NO_FINISHED_EVENTS",flush=True)
        return
    eid=first_finished["id"]
    try: d=fetch("/summary?event="+str(eid))
    except Exception as e:
        print("SUMMARY_ERROR",eid,type(e).__name__,str(e)[:180],flush=True);return
    print("SUMMARY",eid,"top_keys",sorted(d.keys()),"rosters_count",len(d.get("rosters",[])),flush=True)
    for ix,r in enumerate(d.get("rosters",[])[:2]):
        roster=r.get("roster",[])
        starters=[p for p in roster if p.get("starter") is True]
        print("TEAM",ix,"team",r.get("team",{}).get("displayName"),
            "roster_keys",sorted(r.keys()),
            "roster_size",len(roster),"starters",len(starters),
            "example_player_keys",sorted(roster[0].keys()) if roster else None,flush=True)
        print("STARTERS",[
          {"id":p.get("athlete",{}).get("id"),"name":p.get("athlete",{}).get("displayName"),
           "pos":p.get("position"),"formationPlace":p.get("formationPlace"),
           "jersey":p.get("jersey")}
          for p in starters[:3]],flush=True)
if __name__=="__main__":run()
