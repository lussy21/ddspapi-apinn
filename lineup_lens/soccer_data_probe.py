"""One-off, quota-limited Soccer Data feasibility check. No secret or raw payload logged."""
import json
import season_db

PROBE="soccer-data-player-stats-2026-11-27-v1"

def run(api, key_present, usage):
    with season_db.db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS lineup_source_probe (
            probe_id text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz, result jsonb NOT NULL DEFAULT '{}'::jsonb)""")
        if not db.execute("INSERT INTO lineup_source_probe(probe_id) VALUES(%s) ON CONFLICT DO NOTHING RETURNING probe_id",(PROBE,)).fetchone():
            return
    result={"key_configured":bool(key_present),"request_cap":3,"tests":{}}
    def call(label,path,params=None):
        try:
            d=api(path,params=params,ttl=86400)
            result["tests"][label]={"ok":True,"type":type(d).__name__,"rows":len(d) if isinstance(d,list) else None}
            return d
        except Exception as e:
            result["tests"][label]={"ok":False,"error":str(e)[:200] if type(e).__name__=="Problem" else type(e).__name__}
            return None
    try:
        if key_present:
            data=call("coverage","/coverage/leagues",{"data_type":"player_stats","per_page":100})
            if isinstance(data,list):
                result["coverage_sample"]=[{k:x[k] for k in ("id","competition_id","name","competition_name","country","has_player_stats","xg_available") if k in x} for x in data if isinstance(x,dict)]
            elif isinstance(data,dict):
                result["coverage_keys"]=sorted(data)
            if result["tests"]["coverage"]["ok"] or "HTTP 401" not in result["tests"]["coverage"].get("error",""):
                rows=call("current_fixtures","/matches",{"date_from":"2026-11-23","date_to":"2026-11-23","utc_offset":"+00:00","sort":"utc_date","per_page":100})
                if isinstance(rows,list):
                    candidates=[m for m in rows if isinstance(m,dict) and "brentford" in str((m.get("home_team") or {}).get("name","")).casefold() and "everton" in str((m.get("away_team") or {}).get("name","")).casefold()]
                    if len(candidates)==1:
                        m=candidates[0]
                        mid=m.get("id","")
                        result["match"]={k:m.get(k) for k in ("id","utc_date","status","competition_id","season_id")}
                        if isinstance(mid,str) and mid.startswith("match_") and mid[6:].isalnum():
                            stats=call("player_stats","/matches/"+mid+"/player-stats")
                            if isinstance(stats,list):
                                fields={}
                                starters=0
                                for p in stats:
                                    if not isinstance(p,dict):continue
                                    starters+=p.get("started") is True
                                    for group in ("passing","shooting","duels","defending","goalkeeping"):
                                        obj=p.get(group)
                                        if isinstance(obj,dict):
                                            for k,v in obj.items():
                                                f=group+"."+k
                                                fields[f]=fields.get(f,0)+(isinstance(v,(float,int)) and not isinstance(v,bool))
                                    for k in ("minutes_played","rating"):
                                        if isinstance(p.get(k),(float,int)):fields[k]=fields.get(k,0)+1
                                result["player_fields_nonnull"]=fields
                                result["starter_count"]=starters
                    else:
                        result["fixture_match_count"]=len(candidates)
                        result["fixture_keys"]=sorted(rows[0]) if rows and isinstance(rows[0],dict) else []
            result["quota"]=usage()
    except Exception as e:
        result["internal_error"]=type(e).__name__
    finally:
        with season_db.db() as db:
            db.execute("UPDATE lineup_source_probe SET finished_at=now(),result=%s::jsonb WHERE probe_id=%s",(json.dumps(result,ensure_ascii=False),PROBE))
        print("Soccer Data one-off player stats probe finished",flush=True)
