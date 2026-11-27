"""Discover provider competition and current season IDs without guessing."""
import json
import unicodedata

TARGETS={
"PL":("England",["Premier League"],"competition_705uv6jm8myn"),
"BL":("Germany",["Bundesliga"],"competition_897d0j7x1ypu"),
"L1":("France",["Ligue 1"],"competition_7x8p84ket95z"),
"SA":("Italy",["Serie A","Serie A Enilive"],None),
"LL":("Spain",["La Liga","LaLiga EA Sports","Primera Division"],None),
"UCL":("Europe",["UEFA Champions League"],"competition_yqdruci11rf8"),
"UEL":("Europe",["UEFA Europa League"],"competition_b25me9a3vyf7"),
"UECL":("Europe",["UEFA Conference League"],"competition_8b166lzvt99w"),
"GR1":("Greece",["Stoiximan Super League","Super League","Super League 1"],"competition_ua1u4o540wdm"),
"BE1":("Belgium",["Pro League","Jupiler Pro League"],"competition_e9jx9l3sjb54"),
"DK1":("Denmark",["Danish Superliga","Superliga","3F Superliga"],"competition_vxvwmzjsqpts"),
"DE2":("Germany",["2. Bundesliga"],"competition_nxb2xt6lb2gg"),
"NL1":("Netherlands",["Eredivisie"],None),
"NO1":("Norway",["Eliteserien"],None),
"TR1":("Turkey",["Super Lig","Trendyol Super Lig","Süper Lig","Trendyol Süper Lig"],None),
"SC1":("Scotland",["Premiership","Scottish Premiership"],None),
"SE1":("Sweden",["Allsvenskan"],None),
}
ORDER=tuple(TARGETS)
DETAIL_ORDER=("TR1","GR1","BE1","DK1","NL1","NO1","SC1","SE1","PL","BL","LL","SA","L1","DE2","UCL","UEL","UECL")

def norm(s):
    return "".join(c for c in unicodedata.normalize("NFKD",str(s or "")).casefold() if c.isascii() and c.isalnum())

def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS soccer_stats_coverage (
        code text PRIMARY KEY, provider_id text, season_id text, season_label text,
        coverage_status text NOT NULL, detail jsonb NOT NULL DEFAULT '{}'::jsonb,
        checked_at timestamptz NOT NULL DEFAULT now())""")
    db.execute("""CREATE TABLE IF NOT EXISTS soccer_stats_coverage_pages (
        page integer PRIMARY KEY, rows jsonb NOT NULL)""")
    db.execute("""INSERT INTO soccer_stats_coverage(code,provider_id,season_id,season_label,coverage_status)
        VALUES('PL','competition_705uv6jm8myn','season_hr1ie7yrsdmt','26/27','ready')
        ON CONFLICT DO NOTHING""")
    db.execute("""CREATE TABLE IF NOT EXISTS soccer_stats_listing_v2 (
        code text NOT NULL,start_day date NOT NULL,attempted_at timestamptz NOT NULL DEFAULT now(),
        matched integer,error text,PRIMARY KEY(code,start_day))""")
    db.execute("""INSERT INTO soccer_stats_listing_v2(code,start_day,attempted_at,matched,error)
        SELECT 'PL',start_day,attempted_at,matched,error FROM soccer_stats_listing
        ON CONFLICT DO NOTHING""")

def season_label_ok(code,label):
    return str(label or "") in ({"2026","26"} if code in {"NO1","SE1"} else {"26/27","2026/27","2026/2027"})

def match_competition(code,rows):
    country,names,known=TARGETS[code]
    exact=[r for r in rows if isinstance(r,dict) and known and r.get("id")==known]
    if len(exact)==1:return exact[0],"found"
    countries={norm(country),"turkiye"} if code=="TR1" else {norm(country)}
    matches=[r for r in rows if isinstance(r,dict) and norm(r.get("country")) in countries
             and norm(r.get("name")) in {norm(n) for n in names}]
    return (matches[0],"found") if len(matches)==1 else (None,"ambiguous" if matches or exact else "not_found")

def verify_season(code,provider_id,doc):
    if not isinstance(doc,dict) or doc.get("id")!=provider_id:raise ValueError("coverage identity mismatch")
    seasons=doc.get("seasons")
    if not isinstance(seasons,list):raise ValueError("coverage seasons missing")
    valid=[r for r in seasons if isinstance(r,dict) and season_label_ok(code,r.get("year"))]
    if len(valid)!=1:return None,None,"season_unverified",{"season_candidates":len(valid)}
    season=valid[0];sid=season.get("id");flag=(season.get("data_types") or {}).get("player_stats") or {}
    good=isinstance(sid,str) and sid.startswith("season_") and flag.get("available") is True
    state="ready" if good else "no_current_season_stats"
    return sid,str(season.get("year") or ""),state,{"name":doc.get("name"),"country":doc.get("country"),"player_stats":flag,"events":season.get("events"),"season_status":season.get("status"),"season_verified":True}

def step(db,fetch):
    pages=db.execute("SELECT page,rows FROM soccer_stats_coverage_pages ORDER BY page").fetchall()
    # Existing successful PL pilot stays usable; all newly discovered leagues
    # require the current season's own coverage detail, not a league-wide flag.
    if not pages or len(pages[-1]["rows"])>=200:
        page=pages[-1]["page"]+1 if pages else 1
        if page>10:raise ValueError("coverage pagination limit")
        rows=fetch("/coverage/leagues",{"data_type":"player_stats","per_page":200,"page":page})
        if not isinstance(rows,list) or len(rows)>200:raise ValueError("invalid coverage list")
        db.execute("INSERT INTO soccer_stats_coverage_pages(page,rows) VALUES(%s,%s::jsonb)",(page,json.dumps(rows)))
        if len(rows)==200:return True
        combined=[r for p in pages for r in p["rows"]]+rows
        for code in TARGETS:
            r,state=match_competition(code,combined)
            if r:
                db.execute("""INSERT INTO soccer_stats_coverage(code,provider_id,coverage_status,detail)
                    VALUES(%s,%s,'discovered',%s::jsonb) ON CONFLICT DO NOTHING""",
                    (code,r.get("id"),json.dumps({"name":r.get("name"),"country":r.get("country"),"latest_season":r.get("latest_season")})))
            else:
                db.execute("""INSERT INTO soccer_stats_coverage(code,coverage_status,detail)
                    VALUES(%s,%s,%s::jsonb) ON CONFLICT DO NOTHING""",(code,state,json.dumps({"reason":"no unique current provider competition"})))
        return True
    rows=db.execute("""SELECT code,provider_id,coverage_status,detail FROM soccer_stats_coverage
        WHERE provider_id IS NOT NULL AND (
           coverage_status IN ('discovered','season_or_coverage_unverified') OR
           (coverage_status='ready' AND NOT (detail ? 'season_verified')) OR
           (coverage_status IN ('coverage_retry','season_unverified','no_current_season_stats') AND checked_at<now()-interval '1 day'))
        ORDER BY checked_at""").fetchall()
    if not rows:return False
    r=min(rows,key=lambda x:DETAIL_ORDER.index(x["code"]))
    try:
        doc=fetch("/coverage/leagues/"+r["provider_id"],None)
        sid,label,state,detail=verify_season(r["code"],r["provider_id"],doc)
    except Exception as exc:
        if str(exc)=="daily quota reserve reached" or getattr(exc,"status",None)==429:raise
        # A temporary provider error cannot permanently block other leagues.
        db.execute("""UPDATE soccer_stats_coverage SET coverage_status='coverage_retry',checked_at=now(),
            detail=detail||%s::jsonb WHERE code=%s""",(json.dumps({"error":type(exc).__name__}),r["code"]))
        return True
    db.execute("""UPDATE soccer_stats_coverage SET season_id=%s,season_label=%s,coverage_status=%s,
        detail=%s::jsonb,checked_at=now() WHERE code=%s""",(sid,label,state,json.dumps(detail),r["code"]))
    return True
