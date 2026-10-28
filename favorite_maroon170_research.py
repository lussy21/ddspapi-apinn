"""Variant C: maroon, total favorite money >=80%, and current G <=1.70."""

from datetime import datetime

import favorite_maroon_research as core

ALERT_NAME = "ΦΑΒΟΡΙ ΜΠΟΡΝΤΟ ≤1,70"
SHEET_NAME = ALERT_NAME
RULE_VERSION = "favorite-maroon-money80-price170-v1"
START_AT = datetime.fromisoformat("2026-10-28T13:11:00+02:00")
PROFILE = core.ResearchProfile(ALERT_NAME, SHEET_NAME, RULE_VERSION, START_AT,
                               "maroon170:", "FAV MAROON170", money80=True,
                               include_other=True, max_price=1.70)
HEADERS = PROFILE.headers


def fixture(row, sheet_row):
    return core.fixture(row, sheet_row, profile=PROFILE)


def qualifies(f90, current, rank, money_share):
    return core.qualifies(f90, current, rank, money_share, profile=PROFILE)


def advance_record(old, item, now, fresh=False, enabled=True):
    return core.advance_record(old, item, now, fresh, enabled, profile=PROFILE)


def update_research(spreadsheet, pinnacle_rows, now, fresh_rows=(), first_row=1, quote_sheet=None):
    return core.update_research(spreadsheet, pinnacle_rows, now, fresh_rows, first_row,
                                quote_sheet, profile=PROFILE)


def settle_results(spreadsheet, pinnacle_sheet, history_rows, now):
    return core.settle_results(spreadsheet, pinnacle_sheet, history_rows, now, profile=PROFILE)
