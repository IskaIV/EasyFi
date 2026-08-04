from __future__ import annotations

import unittest
from datetime import date

from easyfi.ui.widgets import format_display_date, parse_display_date


class DisplayDateTests(unittest.TestCase):
    def test_friendly_date_round_trip(self) -> None:
        value = date(2026, 8, 4)
        self.assertEqual(format_display_date(value), "08/04/2026")
        self.assertEqual(parse_display_date("08/04/2026"), value)

    def test_legacy_iso_input_is_still_accepted(self) -> None:
        self.assertEqual(parse_display_date("2026-08-04"), date(2026, 8, 4))

    def test_invalid_date_has_friendly_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "MM/DD/YYYY"):
            parse_display_date("August 4")


if __name__ == "__main__":
    unittest.main()
