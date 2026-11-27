"""Short, evidence-first lineup summary. No inferred injury or future outcome.
Use prior-season-to-date starters and same-source observed contributions.
Missing data never becomes a negative grade.
"""
from collections import defaultdict,Counter
from math import ceil,isfinite

def value(v):
    try:
        x=float(v)
        return x if isfinite(x) and x>=0 else None
    except (TypeError,ValueError,OverflowError):return None

def summarize(current,prior,production,lines,role_to_line):
    if len(current)!=11 or len({p["id"] for p in current})!=11:
        return [{"kind":"neutral","text":"Δεν έχει επιβεβαιωθεί πλήρης ενδεκάδα.","detail":""}]
    if any(p.get("unresolved") for p in current):
        return [{"kind":"neutral","text":"Δεν έχουν αντιστοιχιστεί με ασφάλεια όλοι οι παίκτες.","detail":""}]
    games={r["match_id"] for r in prior}
    if len(games)<5:return [{"kind":"neutral","text":"Δεν υπάρχει αρκετό ιστορικό για ασφαλές συμπέρασμα.","detail":""}]
    players={};starts=defaultdict(set);roles=defaultdict(Counter)
    for r in prior:
        pid=r["player_id"];players[pid]=r["player_name"];starts[pid].add(r["match_id"])
        k=role_to_line(r["position_code"])
        if k:roles[pid][k]+=1
    now={p["id"] for p in current};n=len(games)
    # Choose one source per player by number of complete prior starting rows.
    # This never adds duplicate events from different sources.
    pools=defaultdict(lambda:defaultdict(dict))
    for r in production:
        pid=r["player_id"];mid=r["match_id"]
        if mid not in starts.get(pid,set()):continue
        g,a=value(r["goals"]),value(r["assists"])
        if g is not None and a is not None:pools[pid][r["source"]][mid]=(g,a)
    impacts=[]
    for pid in players.keys()-now:
        choices=pools.get(pid,{})
        if not choices:continue
        source,rows=max(choices.items(),key=lambda x:(len(x[1]),x[0]=="fpl_elo"))
        if len(rows)<3 or len(rows)<ceil(.75*len(starts[pid])):continue
        g=sum(x[0] for x in rows.values());a=sum(x[1] for x in rows.values())
        if g+a<3:continue
        impacts.append((g+a,len(starts[pid]),pid,g,a))
    impacts.sort(reverse=True)
    findings=[];mentioned=set()
    if impacts:
        _,_,pid,g,a=impacts[0]
        # Counts support the importance of the observed contribution, not
        # a claim that the replacement is weaker or that the same goals are lost.
        findings.append({"kind":"attention","text":players[pid]+": εκτός ενδεκάδας παίκτης με σημαντική καταγεγραμμένη επιθετική συνεισφορά.",
            "detail":f"{int(g)} γκολ, {int(a)} ασίστ στις διαθέσιμες βασικές συμμετοχές."})
        mentioned.add(pid)
    regular=sorted((p for p in players.keys()-now if len(starts[p])>=ceil(.65*n) and p not in mentioned),key=lambda p:(-len(starts[p]),players[p]))
    if regular:
        names=", ".join(players[p] for p in regular[:3])
        findings.append({"kind":"attention","text":"Εκτός συχνών βασικών: "+names+("." if len(regular)<=3 else " και άλλοι."),
            "detail":"Συχνές συμμετοχές δεν αποδεικνύουν ανώτερη ποιότητα."})
    keepers=[p for p in current if role_to_line(p.get("code"))=="G"]
    if len(keepers)==1:
        p=keepers[0];k=len(starts[p["id"]])
        if k>=ceil(.5*n) and any(l["line"]=="Τερματοφύλακας" and l["status"]!="usual" for l in lines):
            findings.append({"kind":"neutral","text":p["name"]+": συχνή επιλογή στο τέρμα, όχι άγνωστος αναπληρωματικός.",
                "detail":f"{k} από {n} προηγούμενες βασικές συμμετοχές. Δεν έχει τεκμηριωθεί διαφορά ποιότητας."})
    for l in lines:
        if l["status"] in ("positive","negative","similar"):
            findings.append({"kind":l["status"],"text":l["line"]+": "+l["text"],"detail":"Πιλοτική ένδειξη από συγκρίσιμα ατομικά στοιχεία."})
    if not findings:
        findings.append({"kind":"neutral","text":"Δεν εντοπίστηκε σημαντική καταγεγραμμένη απουσία με τα διαθέσιμα στοιχεία.","detail":"Δεν σημαίνει ότι αποδείχθηκε ισοδύναμη ενδεκάδα."})
    return findings

def load(db,league,tid,cutoff,current,lines,role_to_line):
    args=(league,tid,cutoff)
    prior=db.execute("""SELECT s.match_id,s.player_id,s.position_code,p.player_name
      FROM archive_starters s JOIN archive_matches a USING(match_id) JOIN archive_players p USING(player_id)
      WHERE a.season_year=2026 AND a.competition_code=%s AND s.team_id=%s AND a.kickoff_utc<%s""",args).fetchall()
    production=[]
    if db.execute("SELECT to_regclass('lineup_private_match_stats') AS t").fetchone()["t"]:
        production.extend(db.execute("""SELECT p.match_id,p.player_id,'11footy' source,
          p.metrics->>'goals' goals,p.metrics->>'assists' assists
          FROM lineup_private_match_stats p JOIN archive_matches a USING(match_id)
          WHERE p.source='11footy' AND p.release_name='11footy-2026-11-10'
          AND a.season_year=2026 AND a.competition_code=%s AND p.team_id=%s AND a.kickoff_utc<%s""",args).fetchall())
    if league=="PL" and db.execute("SELECT to_regclass('lineup_research_verified_player_stats') AS t").fetchone()["t"]:
        production.extend(db.execute("""SELECT match_id,canonical_player_id player_id,source,goals,assists
          FROM lineup_research_verified_player_stats WHERE source='fpl_elo'
          AND season_year=2026 AND competition_code=%s AND team_id=%s AND kickoff_utc<%s""",args).fetchall())
    if db.execute("SELECT to_regclass('soccer_stats_verified_match_players') AS t").fetchone()["t"]:
        production.extend(db.execute("""SELECT match_id,canonical_player_id player_id,'soccer_data' source,goals,assists
          FROM soccer_stats_verified_match_players WHERE started AND season_year=2026
          AND competition_code=%s AND team_id=%s AND kickoff_utc<%s""",args).fetchall())
    return summarize(current,prior,production,lines,role_to_line)
