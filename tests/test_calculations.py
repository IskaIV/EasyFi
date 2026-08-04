from __future__ import annotations

import unittest
from datetime import date

from easyfi.calculations import (
    calculate_shift,
    elapsed_minutes,
    format_money,
    work_week_bounds,
)


class TimeCalculationTests(unittest.TestCase):
    def test_elapsed_minutes_supports_overnight_shift(self) -> None:
        self.assertEqual(elapsed_minutes("22:30", "06:15"), 465)

    def test_thursday_work_week_contains_following_wednesday(self) -> None:
        start, end = work_week_bounds(date(2026, 8, 3), start_weekday=3)
        self.assertEqual(start, date(2026, 7, 30))
        self.assertEqual(end, date(2026, 8, 5))

    def test_regular_shift_deducts_break_and_estimates_tax(self) -> None:
        result = calculate_shift(
            clock_in="08:30",
            clock_out="17:00",
            break_durations=(30,),
            hourly_rate_cents=2400,
            tax_rate_bps=1800,
        )
        self.assertEqual(result.elapsed_minutes, 510)
        self.assertEqual(result.break_minutes, 30)
        self.assertEqual(result.paid_minutes, 480)
        self.assertEqual(result.gross_pay_cents, 19_200)
        self.assertEqual(result.tax_cents, 3_456)
        self.assertEqual(result.net_pay_cents, 15_744)

    def test_shift_crossing_threshold_splits_regular_and_overtime(self) -> None:
        result = calculate_shift(
            clock_in="08:00",
            clock_out="10:00",
            break_durations=(),
            hourly_rate_cents=2000,
            tax_rate_bps=1000,
            prior_week_minutes=39 * 60,
            overtime_after_minutes=40 * 60,
            overtime_multiplier_milli=1500,
        )
        self.assertEqual(result.regular_minutes, 60)
        self.assertEqual(result.overtime_minutes, 60)
        self.assertEqual(result.regular_pay_cents, 2000)
        self.assertEqual(result.overtime_pay_cents, 3000)
        self.assertEqual(result.gross_pay_cents, 5000)
        self.assertEqual(result.net_pay_cents, 4500)

    def test_break_cannot_consume_entire_shift(self) -> None:
        with self.assertRaisesRegex(ValueError, "shorter than the shift"):
            calculate_shift(
                clock_in="09:00",
                clock_out="10:00",
                break_durations=(60,),
                hourly_rate_cents=2000,
                tax_rate_bps=0,
            )

    def test_money_format_uses_integer_cents(self) -> None:
        self.assertEqual(format_money(123_456), "$1,234.56")
        self.assertEqual(format_money(-99), "-$0.99")


if __name__ == "__main__":
    unittest.main()

