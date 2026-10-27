"""Show approved independent alerts together, preserving the original head."""

from contra_priority import legacy_contra_guarded_expr
from side_goal_alerts import active_expr, LEGACY_KEY, LEGACY_DISPLAY, FLOW_DISPLAY


START_DAY = "2026-10-27"


def parallel_alert_formula(primary_expression, row_number):
    """Keep the old primary/strength; append each other approved signal once.

    Core strong/simple/watch remains one family. Research helpers never become
    public through this join, and the actionable Contra exclusions still apply.
    Caller installs this only on upcoming fixtures from START_DAY onward.
    """
    r = row_number

    def approved(column, config, close=False):
        phase = f'$BQ{r}="CLOSE";' if close else ""
        return (f'IF(AND({phase}${column}{r}<>"";{active_expr(config)});'
                f'${column}{r};"")')

    strong = []
    for column in ("BG", "BH"):
        strong.append(
            f'IF(AND(REGEXMATCH(TO_TEXT(${column}{r});"ΔΥΝΑΤΟ ΦΑΒΟΡΙ");'
            f'{active_expr("ΔΥΝΑΤΟ ΦΑΒΟΡΙ")});${column}{r};"")'
        )
    simple = (
        f'IF($BI{r}<>"";$BI{r};$BJ{r})'
    )
    simple = legacy_contra_guarded_expr(simple, r)
    simple = (
        f'LET(simplepick;{simple};IF(OR('
        f'AND(simplepick="🔔 ΚΟΝΤΡΑ";{active_expr("ΚΟΝΤΡΑ")});'
        f'AND(simplepick="🔔 ΦΑΒΟΡΙ";{active_expr("ΦΑΒΟΡΙ")}));simplepick;""))'
    )
    # WATCH Contra was already visible to this personal/admin sheet.
    watch_contra = active_expr("WATCH ΚΟΝΤΡΑ")
    watch_contra = watch_contra.replace('="ACTIVE"', '="ADMIN_ONLY"')
    watch = (
        f'IF(OR(AND($BK{r}="👀 WATCH ΚΟΝΤΡΑ";'
        f'OR({active_expr("WATCH ΚΟΝΤΡΑ")};{watch_contra}));'
        f'AND($BK{r}="👀 WATCH ΦΑΒΟΡΙ";{active_expr("WATCH ΦΑΒΟΡΙ")}));'
        f'$BK{r};"")'
    )
    core = (
        f'LET(strongopen;{strong[0]};strongheld;{strong[1]};'
        f'IF(strongopen<>"";strongopen;IF(strongheld<>"";strongheld;'
        f'IF(OR($BI{r}<>"";$BJ{r}<>"");{simple};{watch}))))'
    )
    candidates = [
        ("corealert", core),
        ("sofaalert", approved("BO", "ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ")),
        ("turnalert", approved("BN", "ΦΑΒΟΡΙ ΤΖΙΡΟΥ", close=True)),
        ("reversalalert", approved("BP", "ΦΑΒΟΡΙ ΓΥΡΙΣΜΑΤΟΣ")),
        ("turnthree", approved("CA", "ΦΑΒΟΡΙ ΤΖΙΡΟΥ 3X")),
        ("sofathree", approved("CB", "ΦΑΒΟΡΙ SOFA+3X")),
        ("dropalert", approved("CC", "ΦΑΒΟΡΙ ΠΤΩΣΗ 2%")),
        ("plusalert", approved("BZ", "ΦΑΒΟΡΙ 84+P60")),
        ("risealert", approved("BT", "ΤΖΙΡΟΣ ↑", close=True)),
        ("seventyfive", approved("BS", "ΦΑΒ 75+")),
        ("sixty", approved("BR", "ΦΑΒ 60+")),
    ]
    bindings = "".join(f"{name};{expression};" for name, expression in candidates)
    head_is_approved = ";".join(f"rawhead={name}" for name, _ in candidates)
    strength = (
        f'IF(AND($BX{r}<>"";REGEXMATCH(TO_TEXT($BX{r});"/10"));'
        f'" · "&IFERROR(LEFT($BX{r};FIND(" · ";$BX{r})-1);$BX{r});"")'
    )
    extra = ";".join(f'IF({name}<>pa;{name};"")' for name, _ in candidates)
    return (
        f'=IF(AND(ISNUMBER($E{r});$E{r}>=1,39);'
        f'LET(rawhead;{primary_expression};{bindings}'
        f'pa;IF(OR({head_is_approved});rawhead;"");'
        f'TEXTJOIN(" | ";TRUE;IF(pa<>"";pa&{strength};"");{extra};'
        f'IF(AND({active_expr("Over1.5k")};'
        f'OR($BG{r}="{LEGACY_KEY}";$BH{r}="{LEGACY_KEY}"));"{LEGACY_DISPLAY}";"");'
        f'IF(AND({active_expr("Over1.5")};$CE{r}<>"");"{FLOW_DISPLAY}";"")));"")'
    )
