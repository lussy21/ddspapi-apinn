"""Two compact, uncalibrated lineup-adjusted team goal indicators.
Not shot-model xG, not opponent-specific score predictions.
Use goals alone for attack; one combined defensive unit for GA.
"""
from collections import defaultdict
from simple_replacements import current_codes,number
from lineup_impact import groups
from lineup_goal_context import history_groups
from lineup_shrinkage import individual,defensive

def load_goals_for(db,league,tid,cutoff):
    rows=db.execute("""SELECT a.match_id,CASE WHEN a.home_team_id=%s THEN r.home_goals ELSE r.away_goals END gf
        FROM archive_matches a JOIN archive_match_results r USING(match_id)
        WHERE a.season_year=2026 AND a.competition_code=%s AND a.kickoff_utc<%s
        AND %s IN(a.home_team_id,a.away_team_id) AND r.home_goals IS NOT NULL AND r.away_goals IS NOT NULL""",
        (tid,league,cutoff,tid)).fetchall()
    return {r["match_id"]:r["gf"] for r in rows}

def evaluate(current,history,sources,priors,gf,ga,formation=None):
    current=current_codes(current,formation);now=groups(current)
    # Both indicators share the same historical matches; each score enters once.
    scores={mid:(f,a) for mid,v in gf.items() if (f:=number(v)) is not None
            and (a:=number(ga.get(mid))) is not None}
    n=len(scores)
    empty=dict(status="unknown",baseline=None,current=None,reason="Δεν επαρκούν τα επιβεβαιωμένα σκορ.")
    if n<3:return dict(for_goals=dict(empty),against_goals=dict(empty),games=n)
    base_f=sum(v[0] for v in scores.values())/n
    base_a=sum(v[1] for v in scores.values())/n
    def indicator(base,adjustment=None,reason="",low=False):
        if adjustment is None:
            return dict(status="historical",baseline=round(base,3),current=round(base,3),
                        small_sample=True,reason=reason)
        return dict(status="estimated",baseline=round(base,3),current=round(max(0,base+adjustment),3),
                    adjustment=round(adjustment,3),small_sample=low or n<5,reason=reason)
    out=dict(for_goals=indicator(base_f,reason="Μέσος όρος σεζόν · χωρίς αξιολόγηση ενδεκάδας."),
             against_goals=indicator(base_a,reason="Μέσος όρος σεζόν · χωρίς αξιολόγηση ενδεκάδας."),games=n)
    matches=[(mid,g) for mid,g in history_groups(history) if mid in scores]
    recent=matches[:5]
    if not now or len(recent)<3:return out
    positions={p["id"]:p["code"] for p in current}
    hist_positions=defaultdict(dict)
    for r in history:hist_positions[r["match_id"]][r["player_id"]]=r["position_code"]
    def attacking(g):return g["F"]+g["M"]+g["D"]
    def defending(g):return g["M"]+g["D"]+g["G"]
    # Use all outfield scorers, never add assists to goals.
    # Exclude an unresolved identity's individual stats, even if a provider has that ID.
    unresolved={p["id"] for p in current if p.get("unresolved")}
    clean_sources={s:{pid:rows for pid,rows in pool.items() if pid not in unresolved} for s,pool in sources.items()}
    f=individual(attacking(now),[attacking(g) for mid,g in recent],positions,
                 [hist_positions[mid] for mid,g in recent],history,clean_sources,priors,
                 ("goals",),"sum","Γκολ / 90′")
    if f:
        out["for_goals"]=indicator(base_f,f["value"],
            "Μέσος όρος γκολ υπέρ σεζόν + μεταβολή ατομικών ρυθμών γκολ/90′ των 10 παικτών γηπέδου έναντι των τελευταίων έως 5 ενδεκάδων. Δεν προστίθενται ασίστ ή xG.",
            f.get("small_sample",False) or f.get("reference_games",0)<len(recent))
        out["for_goals"].update(source=f["source"],reference_games=f["reference_games"])
    # Midfield, defence and GK form a single unit. Historical full-match
    # goals conceded enter ONCE per fixture, not as three separate sums.
    joint=[(mid,{"unit":defending(g)}) for mid,g in matches]
    a=defensive(defending(now),[defending(g) for mid,g in recent],"unit",joint,
                {mid:v[1] for mid,v in scores.items()})
    if a:
        out["against_goals"]=indicator(base_a,a["value"],
            "Μέσος όρος γκολ κατά σεζόν + μεταβολή ιστορικών γκολ κατά για ενιαίο σύνολο κέντρου, άμυνας και τερματοφύλακα έναντι των τελευταίων έως 5 ενδεκάδων. Κάθε σκορ μετρά μία φορά.",
            a.get("small_sample",False) or bool(unresolved.intersection(defending(now))))
        out["against_goals"].update(source=a["source"],reference_games=a["reference_games"])
    return out
