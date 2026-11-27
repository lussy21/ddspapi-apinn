"""Read-only public ESPN match-summary audit. No credentials, database or API quota.
Only prints counts/schema, never publishes player records."""
import json
from urllib.request import Request,urlopen
from collections import Counter
import concurrent.futures

SAMPLES={
"BE1":("bel.1",401878942),"BL":("ger.1",401884733),
"DE2":("ger.2",401885052),"DK1":("den.1",401874538),
"GR1":("gre.1",401896728),"L1":("fra.1",401876401),
"LL":("esp.1",401882802),"NL1":("ned.1",401875547),
"NO1":("nor.1",401843490),"PL":("eng.1",401879237),
"SA":("ita.1",401875009),"SC1":("sco.1",401878348),
"SE1":("swe.1",401842888),"TR1":("tur.1",401888370),
"UCL":("uefa.champions",401915378),"UEL":("uefa.europa",401915521),
"UECL":("uefa.europa.conf",401915816)}
def audit(code,slug,event):
    url=f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={event}"
    with urlopen(Request(url,headers={"User-Agent":"LineupLens-Personal-Research/1.0"}),timeout=25) as f:
        data=json.loads(f.read(4_000_001))
    hdr=data.get("header",{})
    comp=(hdr.get("competitions") or [{}])[0]
    if str(hdr.get("id") or comp.get("id"))!=str(event):
        raise ValueError("unverified event ID")
    if comp.get("status",{}).get("type",{}).get("completed") is not True:
        raise ValueError("not a completed match")
    teams=data.get("rosters") or []
    starters=[p for t in teams for p in (t.get("roster") or []) if p.get("starter") is True]
    if len(teams)!=2 or len(starters)!=22 or any(sum(p.get("starter") is True for p in t.get("roster",[]))!=11 for t in teams):
        raise ValueError("incomplete XI")
    if len({str(p.get("athlete",{}).get("id")) for p in starters})!=22:
        raise ValueError("nonunique starter IDs")
    schema=Counter()
    for p in starters:
        stats=p.get("stats") or p.get("statistics") or []
        if isinstance(stats,list):
            for s in stats:
                if isinstance(s,dict):
                    name=s.get("name") or s.get("abbreviation") or s.get("label")
                    if name and any(s.get(k) is not None for k in ("value","displayValue")):schema[str(name)]+=1
        elif isinstance(stats,dict):
            for k,v in stats.items():
                if v is not None:schema[k]+=1
    return {"code":code,"event":event,"verified_source_xi":22,"roster_keys":sorted(set().union(*(p.keys() for p in starters))),"stat_coverage":dict(schema),"boxscore_keys":sorted((data.get("boxscore") or {}).keys()),"boxscore_player_groups":len((data.get("boxscore") or {}).get("players") or [])}
def safe(item):
    code,(slug,event)=item
    try:return audit(code,slug,event)
    except Exception as exc:return {"code":code,"event":event,"error":str(exc)}
if __name__=="__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for report in pool.map(safe,SAMPLES.items()):print("AUDIT "+json.dumps(report,ensure_ascii=False),flush=True)
