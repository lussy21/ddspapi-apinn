"""Offline checks for compact presentation and canonical recording boundaries."""

from copy import deepcopy
import unittest

import alert_display as d


CANONICAL = "🔔💎 ΦΑΒΟΡΙ ΓΥΡΙΣΜΑΤΟΣ · 5,5/10 | 🔔 Over1.5k | 🔔 Over1.5"


class Sheet:
    id = 978226074

    def __init__(self, raw):
        self.raw = deepcopy(raw)
        self.reads = []

    def get(self, address, value_render_option=None):
        self.reads.append((address, value_render_option))
        return deepcopy(self.raw)


class Book:
    def __init__(self):
        self.writes = []

    def batch_update(self, body):
        self.writes.append(deepcopy(body))


def fixtures(n):
    return [[], []] + [["League", "Home", "Away"] for _ in range(n)]


class CompactDisplayTests(unittest.TestCase):
    def test_three_market_example_preserves_full_names_and_score(self):
        self.assertEqual(d.compact_alert(CANONICAL), CANONICAL)
        self.assertEqual(d.alert_number_format(CANONICAL), {"type": "TEXT", "pattern": "@"})

    def test_independent_goal_names_and_watch_are_distinct(self):
        for value in ("🔔 Over1.5k", "🔔 Over1.5", "🔔 OVER 1.5 (ΡΟΗ)",
                      "👀 WATCH ΚΟΝΤΡΑ · 5,7/10", "🔔 ΚΟΝΤΡΑ · 5,7/10"):
            self.assertEqual(d.compact_alert(value), value)

    def test_unknown_labels_errors_and_blanks_remain_truthful(self):
        for value in ("", None, False, "#REF!"):
            self.assertIsNone(d.compact_alert(value))
            self.assertEqual(d.alert_number_format(value), {"type": "TEXT", "pattern": "@"})
        for value in ("🔔 New rule", '🔔 "quoted rule"'):
            self.assertEqual(d.compact_alert(value), value)

    def test_recording_reads_raw_alerts_without_changing_other_formatted_fields(self):
        sheet = Sheet([[CANONICAL], []])
        row = ["League", "Home", "Away", "H", "1,80", "", "", "", "", "", "128.365", "58,4%", "", "74%", "🔔 ΓΥΡ 5,5/10 | O1.5k | O1.5"]
        rows = [row, ["League", "Other", "Match"] + [""] * 12]
        original = deepcopy(rows)
        actual = d.canonical_alert_rows(sheet, rows, first_row=3)
        self.assertEqual(actual[0][14], CANONICAL)
        self.assertEqual(actual[0][:14], original[0][:14])
        self.assertEqual(actual[1][14], "")
        self.assertEqual(rows, original)
        self.assertEqual(sheet.reads, [("O3:O4", "UNFORMATTED_VALUE")])

    def test_withdrawal_clears_old_display_including_trimmed_empty_tail(self):
        sheet, book, rows = Sheet([[CANONICAL], ["🔔 Over1.5"]]), Book(), fixtures(2)
        d.refresh_alert_display(book, sheet, rows)
        sheet.raw = []  # Google values.get trims a newly empty tail.
        d.refresh_alert_display(book, sheet, rows)
        cells = book.writes[-1]["requests"][0]["updateCells"]["rows"]
        self.assertEqual(len(cells), 2)
        self.assertTrue(all(c["values"][0]["userEnteredFormat"]["numberFormat"]
                            == {"type": "TEXT", "pattern": "@"} for c in cells))
        self.assertEqual(sheet.raw, [])

    def test_changed_alert_replaces_display_without_modifying_formula_values(self):
        sheet, book, rows = Sheet([[CANONICAL]]), Book(), fixtures(1)
        d.refresh_alert_display(book, sheet, rows)
        sheet.raw = [["🔔 ΦΑΒ 75+ · 6,5/10 | 🔔 Over1.5"]]
        d.refresh_alert_display(book, sheet, rows)
        update = book.writes[-1]["requests"][0]["updateCells"]
        self.assertEqual(update["fields"], "userEnteredFormat.numberFormat,userEnteredFormat.wrapStrategy,userEnteredFormat.textFormat.fontSize")
        self.assertEqual(update["rows"][0]["values"][0]["userEnteredFormat"]["numberFormat"],
                         {"type": "TEXT", "pattern": "@"})
        self.assertNotIn("userEnteredValue", update["rows"][0]["values"][0])

    def test_reset_exposes_current_formula_text_before_input_writes(self):
        sheet, book = Sheet([[CANONICAL]]), Book()
        d.reset_alert_display(book, sheet, fixtures(1))
        reset = book.writes[0]["requests"][0]["repeatCell"]
        self.assertEqual(reset["range"]["startRowIndex"], 2)
        self.assertEqual(reset["range"]["endRowIndex"], 3)
        self.assertEqual(reset["cell"]["userEnteredFormat"]["numberFormat"], {"type": "TEXT", "pattern": "@"})
        self.assertEqual(sheet.raw, [[CANONICAL]])

    def test_formatting_is_scoped_to_alert_cells_without_dimension_or_neighbor_changes(self):
        requests = d.display_requests(978226074, [[CANONICAL], ["🔔 ΦΑΒ 75+"]])
        self.assertEqual(len(requests), 1)
        update = requests[0]["updateCells"]
        self.assertEqual(update["range"]["startColumnIndex"], 14)
        self.assertEqual(update["range"]["endColumnIndex"], 15)
        for row in update["rows"]:
            self.assertEqual(set(row["values"][0]), {"userEnteredFormat"})
            self.assertEqual(set(row["values"][0]["userEnteredFormat"]["textFormat"]), {"fontSize"})

    def test_presentation_failure_does_not_block_data_writer(self):
        class UnavailableBook:
            def batch_update(self, body):
                raise RuntimeError("simulated formatting outage")

        sheet = Sheet([[CANONICAL]])
        self.assertFalse(d.reset_alert_display(UnavailableBook(), sheet, fixtures(1)))
        self.assertEqual(sheet.raw, [[CANONICAL]])

    def test_font_shrinks_for_parallel_alerts_and_recovers_after_withdrawal(self):
        short = "🔔 ΦΑΒ 75+ · 6,5/10"
        long = ("🔔💎 ΦΑΒΟΡΙ SOFA+ΤΖΙΡΟΥ · 8,0/10 | 🔔 ΦΑΒ 75+ | "
                "🔔 ΦΑΒ 60+ | 🔔 ΦΑΒΟΡΙ | 🔔 Over1.5k | 🔔 Over1.5")
        self.assertGreater(d.alert_font_size(short), d.alert_font_size(long))
        self.assertGreaterEqual(d.alert_font_size(long), d.MIN_FONT_SIZE)
        sheet, book, rows = Sheet([[long]]), Book(), fixtures(1)
        d.refresh_alert_display(book, sheet, rows)
        sheet.raw = [[short]]
        d.refresh_alert_display(book, sheet, rows)
        cell = book.writes[-1]["requests"][0]["updateCells"]["rows"][0]["values"][0]
        self.assertEqual(cell["userEnteredFormat"]["textFormat"]["fontSize"], d.MAX_FONT_SIZE)
        self.assertNotIn("userEnteredValue", cell)


if __name__ == "__main__":
    unittest.main()
