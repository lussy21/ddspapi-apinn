"""Offline coverage of new helper rows and history after row 1000."""

import ast
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime
import io
import json
from pathlib import Path
import re
import types
import unittest
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from alert_formulas import legacy_alert_helper_updates
from test_pinnodds import Clock, FakeSpreadsheet, NOW, fixture, row, run_main

# Verified pre-existing PINNACLE!BH887:BK887, captured before the repair.
GOLDEN = json.loads(r'''{"BH":"=IF(NOT(AND(ISNUMBER($L887);ISNUMBER($N887)));\"\";IFS(AND(REGEXMATCH($BF887;\"ΔΥΝΑΤΟ ΚΟΝΤΡΑ \\(\\+10\\)\");ISNUMBER($E887);$E887>=1,7;$E887<=2,4;$L887<=72;$N887>=48;$N887-$L887>=8);$BF887;AND(REGEXMATCH($BF887;\"ΔΥΝΑΤΟ ΚΟΝΤΡΑ\");ISNUMBER($E887);$E887>=1,5;$E887<=2,4;$L887<62;$N887>=48);$BF887;AND(REGEXMATCH($BF887;\"ΔΥΝΑΤΟ ΦΑΒΟΡΙ\");ISNUMBER($E887);$E887>=1,25;$E887<=1,9;$L887>=88;$N887>=80);$BF887;TRUE;\"\"))","BI":"=IF(NOT(AND(ISNUMBER($L887);ISNUMBER($N887)));\"\";IFS(AND(ISNUMBER($E887);$E887>=1,5;$E887<=2,4;$L887<=70;$N887>=50;$N887>=$L887);\"🔔 ΚΟΝΤΡΑ\";AND(ISNUMBER($E887);$E887>=1,25;$E887<=1,9;$L887>=80;$N887>=82);\"🔔 ΦΑΒΟΡΙ\";TRUE;\"\"))","BJ":"=IF(NOT(AND(ISNUMBER($L887);ISNUMBER($N887)));\"\";IFS(AND($BF887=\"🔔 ΚΟΝΤΡΑ\";ISNUMBER($E887);$E887>=1,5;$E887<=2,4;$L887<=72;$N887>=48;$N887>=$L887-2);\"🔔 ΚΟΝΤΡΑ\";AND($BF887=\"🔔 ΦΑΒΟΡΙ\";ISNUMBER($E887);$E887>=1,25;$E887<=1,9;$L887>=78;$N887>=80);\"🔔 ΦΑΒΟΡΙ\";TRUE;\"\"))","BK":"=IF(NOT(AND(ISNUMBER($L887);ISNUMBER($N887)));\"\";IFS(AND(ISNUMBER($E887);$E887>=1,5;$E887<=2,4;$L887<75;$N887>=65;$N887>$L887);\"👀 WATCH ΚΟΝΤΡΑ\";AND(ISNUMBER($E887);$E887>=1,25;$E887<=2,1;$L887>=80;$N887>=75);\"👀 WATCH ΦΑΒΟΡΙ\";TRUE;\"\"))"}''')


class AlertPipelineTests(unittest.TestCase):
    def test_original_rule_formulas_are_preserved_on_new_rows(self):
        for number in (887, 1017, 5001):
            actual = legacy_alert_helper_updates(number)[1]["values"][0]
            expected = [
                re.sub(r"(\$[A-Z]+)887", lambda m: m[1] + str(number), GOLDEN[col])
                for col in ("BH", "BI", "BJ", "BK")
            ]
            self.assertEqual(actual, expected)

    def test_over_continuation_uses_new_identity_and_live_history_range(self):
        updates = legacy_alert_helper_updates(1019, use_over15=True)
        previous = updates[0]["values"][0][0]
        continuation = updates[1]["values"][0][0]
        self.assertNotIn("1498", previous)
        self.assertIn("'ALERT LOG'!$C$2:$C=ROW()", previous)
        self.assertIn("OVER 1[.]5", continuation)
        self.assertNotIn("ΔΥΝΑΤΟ ΚΟΝΤΡΑ", continuation)

    def test_writer_restores_helpers_after_1000_and_preserves_completed_rows(self):
        Clock.instant = NOW
        archived = row("Done Home", "Done Away", "completed",
                       kickoff="2026-10-21T19:00:00+03:00")
        archived[15] = "1-0"
        archived[57:63] = ["old previous", "old strong", "old buffer",
                           "old simple", "old continuation", "old watch"]
        live = row(event_id="pinnodds:1")
        live[4:10] = [1.8, "", 1.8, 2.1, "", 2.1]
        data = [[], []] + [[] for _ in range(997)] + [archived, live]
        book = FakeSpreadsheet(data)
        calls, feeds, _ = run_main(book, [fixture()])
        self.assertEqual(book.main.rows[999][57:63], archived[57:63])
        actual = book.main.rows[1000]
        self.assertTrue(all(str(value).startswith("=") for value in actual[57:63]))
        self.assertTrue(any(item["range"] == "BH1001:BK1001" for item in book.main.writes))
        self.assertEqual(len(feeds), 1)

    def test_real_history_state_machine_records_new_event_after_row_1000(self):
        source = ast.parse(Path(__file__).with_name("alert_history.py").read_text())
        nodes = [node for node in source.body if isinstance(node, ast.FunctionDef)]
        ns = {"json": json, "re": re, "datetime": datetime, "ZoneInfo": ZoneInfo}
        for node in source.body:
            if isinstance(node, ast.Assign):
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        ns[target.id] = value
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "alert_history.py", "exec"), ns)
        live = [""] * 57
        live[:5] = ["UEFA - Conference League", "Monaco", "Freiburg", "H", "2,22"]
        live[14], live[17] = "🔔 OVER 1.5", "pinnodds:after-1000"
        data = [[] for _ in range(1001)] + [live]
        writes, appended, reads = [], [], []

        def column(text):
            total = 0
            for char in text:
                total = total * 26 + ord(char) - 64
            return total - 1

        def get(address, value_render_option=None):
            reads.append(address)
            a, first, b, last = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", address).groups()
            result = deepcopy(data[int(first)-1:min(int(last), len(data))])
            if value_render_option == "FORMULA":
                return [["=TRUE()"] if values else [] for values in result]
            return [values[column(a):column(b)+1] for values in result]

        sheet = types.SimpleNamespace(
            id=978226074,
            row_count=9887, get=get,
            batch_update=lambda items, **kwargs: writes.extend(items),
        )
        log = types.SimpleNamespace(
            append_rows=lambda items, **kwargs: appended.extend(items),
        )
        book = types.SimpleNamespace(worksheet=lambda _: sheet, batch_update=lambda _: None)
        ns.update({
            "SPREADSHEET_ID": "offline-only", "SHEET_NAME": "PINNACLE",
            "get_credentials": lambda: None,
            "gspread": types.SimpleNamespace(authorize=lambda _: types.SimpleNamespace(open_by_key=lambda _: book)),
            "time": types.SimpleNamespace(sleep=lambda _: None),
            "get_log_sheet": lambda _: log, "load_baselines": lambda _: {},
            "now_athens": lambda: "22/10/2026 16:40:00",
            "compact_open_text": lambda _: "offline snapshot",
            "send_pending_pushes": Mock(), "run_level_review_if_due": Mock(),
        })
        with redirect_stdout(io.StringIO()):
            ns["main"]()
        self.assertEqual(reads, ["A3:BE9887", "O3:O1002", "O3:O1002", "O3:O1002"])
        self.assertEqual(len(appended), 1)
        self.assertEqual(appended[0][1:3], ["pinnodds:after-1000", 1002])
        self.assertEqual(appended[0][5:7], ["ΑΝΟΙΞΕ", "🔔 OVER 1.5"])
        self.assertEqual(writes[0]["range"], "BB1002:BE1002")


if __name__ == "__main__":
    unittest.main()


