"""Public simple-CONTRA gate; research rules and historical rows stay intact.

This restores the *numeric priority exclusions*, not historical missing-helper
or stale-buffer bugs. It is not a claim that the old eight-match sample is a
complete backtest: repairing missing BI/BJ reveals a ninth eligible fixture.
"""


def legacy_contra_blocked_expr(row_number):
    """Sheets expression: an old higher-priority rule excludes simple CONTRA.

    Strong Contra uses its original pre-migration condition, independently of
    the new OVER 1.5 entry-price gate. Retired research helpers are inspected
    regardless of ACTIVE status, without making them public again. Existing
    live simple-alert entry/continuation rules are left unchanged.
    """
    r = row_number
    return (
        'OR('
        f'NOT(AND(ISNUMBER($E{r});ISNUMBER($L{r});ISNUMBER($N{r})));'
        f'AND($E{r}>=1,5;$E{r}<=2,4;$L{r}<60;$N{r}>=50);'
        f'AND($E{r}>=1,7;$E{r}<=2,4;$L{r}<=70;'
        f'$N{r}>=50;$N{r}>=$L{r}+10);'
        f'$BO{r}<>"";$BP{r}<>"";'
        f'AND($BQ{r}="CLOSE";$BN{r}<>"");'
        f'$CA{r}<>"";$CB{r}<>"";$CC{r}<>"";$BZ{r}<>"";'
        f'AND($BQ{r}="CLOSE";$BT{r}<>"");'
        f'$BS{r}<>"";$BR{r}<>"";'
        # Before the home-only migration, FAV60 also preceded Contra away.
        f'AND($BQ{r}="CLOSE";ISNUMBER($E{r});$E{r}<=1,7;'
        f'ISNUMBER($BM{r});$BM{r}>=60))'
    )


def legacy_contra_guarded_expr(primary_expr, row_number):
    """Filter only the exact simple label, after normal public selection."""
    return (
        f'LET(rawpick;{primary_expr};'
        'IF(rawpick="🔔 ΚΟΝΤΡΑ";'
        f'IF(IFERROR({legacy_contra_blocked_expr(row_number)};TRUE);'
        '"";rawpick);rawpick))'
    )
