"""Discover provider competition and current season IDs without guessing."""
import json
import unicodedata

TARGETS={
"PL":("England",["Premier League"],"competition_705uv6jm8myn"),
"BL":("Germany",["Bundesliga"],"competition_897d0j7x1ypu"),
"L1":("France",["Ligue 1"],"competition_7x8p84ket95z"),
"SA":("Italy",["Serie A"],None),
"LL":("Spain",["La Liga","LaLiga EA Sports","Primera Division"],None),
"UCL":("Europe",["UEFA Champions League"],"competition_yqdruci11rf8"),
"UEL":("Europe",["UEFA Europa League"],"competition_b25me9a3vyf7"),
"UECL":("Europe",["UEFA Conference League"],"competition_8b166lzvt99w"),
"GR1":("Greece",["Stoiximan Super League"],"competition_ua1u4o540wdm"),
"BE1":("Belgium",["Pro League"],"competition_e9jx9l3sjb54"),
"DK1":("Denmark",["Danish Superliga"],"competition_vxvwmzjsqpts"),
"DE2":("Germany",["2. Bundesliga"],"competition_nxb2xt6lb2gg"),
"NL1":("Netherlands",["Eredivisie"],None),
"NO1":("Norway",["Eliteserien"],None),
"TR1":("Turkey",["Super Lig","Trendyol Super Lig"],None),
"SC1":("Scotland",["Premiership","Scottish Premiership"],None),
"SE1":("Sweden",["Allsvenskan"],None),
}
ORDER=tuple(TARGETS)

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

def step(db,fetch):
    pages=db.execute("SELECT page,rows FROM soccer_stats_coverage_pages ORDER BY page").fetchall()
    if pages and len(pages[-1]["rows"])<200:return False
    page=pages[-1]["page"]+1 if pages else 1
    if page>10:raise ValueError("coverage pagination limit")
    rows=fetch("/coverage/leagues",{"data_type":"player_stats","per_page":200,"page":page})
    if not isinstance(rows,list):raise ValueError("invalid coverage list")
    db.execute("INSERT INTO soccer_stats_coverage_pages(page,rows) VALUES(%s,%s::jsonb)",(page,json.dumps(rows)))
    combined=[r for p in pages for r in p["rows"]]+rows
    if len(rows)==200:return True
    for code,(country,names,known) in TARGETS.items():
        matches=[r for r in combined if isinstance(r,dict) and
                 (r.get("id")==known if known else
                  norm(r.get("country")) in ({norm(country),"turkiye"} if code=="TR1" else {norm(country)})
                  and norm(r.get("name")) in {norm(n) for n in names})]
        if len(matches)==1:
            r=matches[0]; season=r.get("latest_season") or {}
            sid=season.get("id"); label=str(season.get("year") or "")
            valid=label in ({"2026","26"} if code in {"NO1","SE1"} else {"26/27","2026/27","2026/2027"})
            flag=(r.get("data_types") or {}).get("player_stats") or {}
            good=valid and isinstance(sid,str) and sid.startswith("season_") and flag.get("available") is True
            db.execute("""INSERT INTO soccer_stats_coverage(code,provider_id,season_id,season_label,coverage_status,detail)
                VALUES(%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING""",
                (code,r.get("id"),sid,label,"ready" if good else "season_or_coverage_unverified",
                json.dumps({"name":r.get("name"),"country":r.get("country"),"latest_season":season,"player_stats":flag})))
        else:
            db.execute("""INSERT INTO soccer_stats_coverage(code,coverage_status,detail)
                VALUES(%s,%s,%s::jsonb) ON CONFLICT DO NOTHING""",
                (code,"not_found" if not matches else "ambiguous",json.dumps({"matches":len(matches)})))
    return True
