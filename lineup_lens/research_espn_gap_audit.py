"""Research-only bounded ESPN gap audit; no raw stats published, no database writes."""
import json,concurrent.futures
from pathlib import Path
from collections import Counter
from urllib.request import Request,urlopen
from research_reconcile_opta import fingerprint,profile,int_or_none
SLUGS={"BE1":"bel.1","DE2":"ger.2","DK1":"den.1","GR1":"gre.1","NO1":"nor.1","SC1":"sco.1","SE1":"swe.1","TR1":"tur.1","UECL":"uefa.europa.conf"}
def audit(item):
    ref,code,event,date,xi=item
    try:
        url=f"https://site.api.espn.com/apis/site/v2/sports/soccer/{SLUGS[code]}/summary?event={event}"
        with urlopen(Request(url,headers={"User-Agent":"LineupLens-Personal-Research/1.0"}),timeout=25) as f:data=json.loads(f.read(4_000_001))
        hdr=data.get("header",{});comp=(hdr.get("competitions") or [{}])[0]
        if str(hdr.get("id") or comp.get("id"))!=str(event):raise ValueError("wrong event ID")
        if comp.get("status",{}).get("type",{}).get("completed") is not True:raise ValueError("not complete")
        if str(comp.get("date") or hdr.get("date") or "")[:10] not in (date,""):
            raise ValueError("date differs")
        teams=data.get("rosters") or []
        if len(teams)!=2:raise ValueError("missing teams")
        competitors={str(c["team"]["id"]):c.get("homeAway") for c in comp.get("competitors",[])}
        metrics=Counter();resolved=0
        for t in teams:
            side=t.get("homeAway") or competitors.get(str(t.get("team",{}).get("id")))
            if side not in ("home","away"):raise ValueError("unknown side")
            canon=[(j,p) for h,j,p in xi if h==(side=="home")]
            source=[p for p in t.get("roster",[]) if p.get("starter") is True]
            if len(canon)!=11 or len(source)!=11:raise ValueError("incomplete XI")
            seen=set()
            for j,p in canon:
                if p is None:continue
                matched=[x for x in source if str(x.get("athlete",{}).get("id"))==str(p) and (j is None or int_or_none(x.get("jersey"))==int_or_none(j))]
                if len(matched)!=1 or p in seen:continue
                seen.add(p);resolved+=1
                for s in matched[0].get("stats") or []:
                    if isinstance(s,dict) and any(s.get(k) is not None for k in ("value","displayValue")):
                        name=s.get("name") or s.get("abbreviation") or s.get("label")
                        if name:metrics[str(name)]+=1
        return {"ref":ref,"code":code,"verified":resolved==22,"matched":resolved,"metric_counts":dict(metrics)}
    except Exception as exc:return {"ref":ref,"code":code,"error":str(exc)}
if __name__=="__main__":
    manifest=json.loads((Path(__file__).parent/"research_fingerprints/espn_missing_v4.json").read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for report in pool.map(audit,manifest):print("AUDIT "+json.dumps(report),flush=True)
