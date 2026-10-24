"""Legacy helper formulas for every live fixture; no HTTP or Sheet access."""


def legacy_alert_helper_updates(row_number, use_over15=False, side_goals=False):
    """Keep the existing strict, continuation and watch rules on new rows."""
    r = row_number
    # The previous fixed log endpoint (1498) stopped seeing newer alerts.
    previous = (
        '=LET(pa;IFERROR(INDEX(FILTER(\'ALERT LOG\'!$G$2:$G;'
        '\'ALERT LOG\'!$C$2:$C=ROW());COUNTIF(\'ALERT LOG\'!$C$2:$C;ROW()));"");'
        'pe;IFERROR(INDEX(FILTER(\'ALERT LOG\'!$F$2:$F;'
        '\'ALERT LOG\'!$C$2:$C=ROW());COUNTIF(\'ALERT LOG\'!$C$2:$C;ROW()));"");'
        'IF(AND(pa<>"";pe<>"ΕΦΥΓΕ");pa;""))'
    )
    if use_over15:
        # Apply the same continuation margins under the new market identity.
        # Retired legacy Contra/+10 labels must not return on new fixtures.
        strong_continuation = (
            f'=IF(NOT(AND(ISNUMBER($L{r});ISNUMBER($N{r})));"";'
            f'IFS(AND(REGEXMATCH($BF{r};"OVER 1[.]5");'
            f'ISNUMBER($E{r});$E{r}>=1,5;$E{r}<=2,4;$L{r}<62;$N{r}>=48);'
            '"🔔 OVER 1.5";'
            f'AND(REGEXMATCH($BF{r};"ΔΥΝΑΤΟ ΦΑΒΟΡΙ");'
            f'ISNUMBER($E{r});$E{r}>=1,25;$E{r}<=1,9;$L{r}>=88;$N{r}>=80);'
            f'$BF{r};TRUE;""))'
        )
    else:
        strong_continuation = (
            f'=IF(NOT(AND(ISNUMBER($L{r});ISNUMBER($N{r})));"";'
            fr'IFS(AND(REGEXMATCH($BF{r};"ΔΥΝΑΤΟ ΚΟΝΤΡΑ \(\+10\)");'
            f'ISNUMBER($E{r});$E{r}>=1,7;$E{r}<=2,4;$L{r}<=72;'
            f'$N{r}>=48;$N{r}-$L{r}>=8);$BF{r};'
            f'AND(REGEXMATCH($BF{r};"ΔΥΝΑΤΟ ΚΟΝΤΡΑ");'
            f'ISNUMBER($E{r});$E{r}>=1,5;$E{r}<=2,4;$L{r}<62;$N{r}>=48);$BF{r};'
            f'AND(REGEXMATCH($BF{r};"ΔΥΝΑΤΟ ΦΑΒΟΡΙ");'
            f'ISNUMBER($E{r});$E{r}>=1,25;$E{r}<=1,9;$L{r}>=88;$N{r}>=80);'
            f'$BF{r};TRUE;""))'
        )
    simple = (
        f'=IF(NOT(AND(ISNUMBER($L{r});ISNUMBER($N{r})));"";'
        f'IFS(AND(ISNUMBER($E{r});$E{r}>=1,5;$E{r}<=2,4;'
        f'$L{r}<=70;$N{r}>=50;$N{r}>=$L{r});"🔔 ΚΟΝΤΡΑ";'
        f'AND(ISNUMBER($E{r});$E{r}>=1,25;$E{r}<=1,9;'
        f'$L{r}>=80;$N{r}>=82);"🔔 ΦΑΒΟΡΙ";TRUE;""))'
    )
    simple_continuation = (
        f'=IF(NOT(AND(ISNUMBER($L{r});ISNUMBER($N{r})));"";'
        f'IFS(AND($BF{r}="🔔 ΚΟΝΤΡΑ";ISNUMBER($E{r});'
        f'$E{r}>=1,5;$E{r}<=2,4;$L{r}<=72;$N{r}>=48;$N{r}>=$L{r}-2);'
        '"🔔 ΚΟΝΤΡΑ";'
        f'AND($BF{r}="🔔 ΦΑΒΟΡΙ";ISNUMBER($E{r});'
        f'$E{r}>=1,25;$E{r}<=1,9;$L{r}>=78;$N{r}>=80);'
        '"🔔 ΦΑΒΟΡΙ";TRUE;""))'
    )
    watch = (
        f'=IF(NOT(AND(ISNUMBER($L{r});ISNUMBER($N{r})));"";'
        f'IFS(AND(ISNUMBER($E{r});$E{r}>=1,5;$E{r}<=2,4;'
        f'$L{r}<75;$N{r}>=65;$N{r}>$L{r});"👀 WATCH ΚΟΝΤΡΑ";'
        f'AND(ISNUMBER($E{r});$E{r}>=1,25;$E{r}<=2,1;'
        f'$L{r}>=80;$N{r}>=75);"👀 WATCH ΦΑΒΟΡΙ";TRUE;""))'
    )
    if side_goals:
        # A FLOW goal signal alone must not activate the original Contra buffer.
        # Both goal signals may coexist with a primary market in the log.
        strong_continuation = strong_continuation.replace(
            '"OVER 1[.]5"',
            '"(^|[|] )(🔔 Over1[.]5k|🔔 OVER 1[.]5([ ]*[(]ΚΟΝΤΡΑ[)])?)($|[ ]*[|])"',
        )
        for label in ("🔔 ΚΟΝΤΡΑ", "🔔 ΦΑΒΟΡΙ"):
            simple_continuation = simple_continuation.replace(
                f'$BF{r}="{label}"',
                f'REGEXMATCH($BF{r};"^{label}($| [|])")',
            )
        strong_continuation = strong_continuation.replace(
            f';$BF{r};TRUE;', f';TRIM(IFERROR(REGEXEXTRACT($BF{r};"^[^|]+");""));TRUE;',
        )
    return [
        {"range": f"BF{r}", "values": [[previous]]},
        {"range": f"BH{r}:BK{r}", "values": [[
            strong_continuation, simple, simple_continuation, watch,
        ]]},
    ]

