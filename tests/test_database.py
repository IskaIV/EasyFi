from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from easyfi.calculations import calculate_shift
from easyfi.database import Database, ShiftToSave


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "easyfi-test.db"
        self.database = Database(self.database_path)
        self.database.initialize()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def make_shift(
        self,
        *,
        work_date: date,
        clock_in: str = "09:00",
        clock_out: str = "17:00",
        breaks: tuple[int, ...] = (),
        overtime_after_minutes: int = 2400,
    ) -> ShiftToSave:
        source = self.database.list_income_sources()[0]
        calculation = calculate_shift(
            clock_in=clock_in,
            clock_out=clock_out,
            break_durations=breaks,
            hourly_rate_cents=source.hourly_rate_cents,
            tax_rate_bps=source.tax_rate_bps,
            overtime_after_minutes=overtime_after_minutes,
            overtime_multiplier_milli=source.overtime_multiplier_milli,
        )
        return ShiftToSave(
            income_source_id=source.id,
            work_date=work_date,
            clock_in=clock_in,
            clock_out=clock_out,
            break_durations=breaks,
            hourly_rate_cents=source.hourly_rate_cents,
            tax_rate_bps=source.tax_rate_bps,
            overtime_after_minutes=overtime_after_minutes,
            overtime_multiplier_milli=source.overtime_multiplier_milli,
            calculation=calculation,
        )

    def test_initialize_creates_defaults_and_income_source(self) -> None:
        self.assertEqual(self.database.get_setting_int("work_week_start", -1), 3)
        sources = self.database.list_income_sources()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].name, "Main job")
        self.assertEqual(sources[0].hourly_rate_cents, 2400)

    def test_saved_shift_and_breaks_persist(self) -> None:
        source = self.database.list_income_sources()[0]
        calculation = calculate_shift(
            clock_in="08:30",
            clock_out="17:00",
            break_durations=(15, 15),
            hourly_rate_cents=source.hourly_rate_cents,
            tax_rate_bps=source.tax_rate_bps,
            overtime_after_minutes=source.overtime_after_minutes,
            overtime_multiplier_milli=source.overtime_multiplier_milli,
        )
        shift_id = self.database.save_shift(
            ShiftToSave(
                income_source_id=source.id,
                work_date=date(2026, 8, 3),
                clock_in="08:30",
                clock_out="17:00",
                break_durations=(15, 15),
                hourly_rate_cents=source.hourly_rate_cents,
                tax_rate_bps=source.tax_rate_bps,
                overtime_after_minutes=source.overtime_after_minutes,
                overtime_multiplier_milli=source.overtime_multiplier_milli,
                calculation=calculation,
            )
        )

        recent = self.database.list_recent_shifts()
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["id"], shift_id)
        self.assertEqual(recent[0]["paid_minutes"], 480)
        self.assertEqual(recent[0]["gross_pay_cents"], 19_200)

        with closing(sqlite3.connect(self.database_path)) as connection:
            breaks = connection.execute(
                "SELECT duration_minutes FROM shift_breaks ORDER BY sort_order"
            ).fetchall()
        self.assertEqual(breaks, [(15,), (15,)])

    def test_prior_paid_minutes_counts_saved_shifts_through_current_date(self) -> None:
        source = self.database.list_income_sources()[0]
        calculation = calculate_shift(
            clock_in="09:00",
            clock_out="17:00",
            break_durations=(),
            hourly_rate_cents=source.hourly_rate_cents,
            tax_rate_bps=source.tax_rate_bps,
        )
        self.database.save_shift(
            ShiftToSave(
                income_source_id=source.id,
                work_date=date(2026, 7, 31),
                clock_in="09:00",
                clock_out="17:00",
                break_durations=(),
                hourly_rate_cents=source.hourly_rate_cents,
                tax_rate_bps=source.tax_rate_bps,
                overtime_after_minutes=source.overtime_after_minutes,
                overtime_multiplier_milli=source.overtime_multiplier_milli,
                calculation=calculation,
            )
        )
        self.assertEqual(
            self.database.prior_paid_minutes(
                income_source_id=source.id,
                week_start=date(2026, 7, 30),
                work_date=date(2026, 7, 31),
                clock_in="18:00",
            ),
            480,
        )

    def test_duplicate_detection_can_exclude_shift_being_edited(self) -> None:
        source = self.database.list_income_sources()[0]
        shift_id = self.database.save_shift(
            self.make_shift(work_date=date(2026, 8, 3))
        )
        duplicate_arguments = {
            "income_source_id": source.id,
            "work_date": date(2026, 8, 3),
            "clock_in": "09:00",
            "clock_out": "17:00",
        }
        self.assertTrue(self.database.has_duplicate_shift(**duplicate_arguments))
        self.assertFalse(
            self.database.has_duplicate_shift(
                **duplicate_arguments, exclude_shift_id=shift_id
            )
        )

    def test_update_recalculates_later_overtime_and_breaks(self) -> None:
        first_id = self.database.save_shift(
            self.make_shift(
                work_date=date(2026, 7, 30),
                clock_in="08:00",
                clock_out="16:00",
                overtime_after_minutes=480,
            )
        )
        second_id = self.database.save_shift(
            self.make_shift(
                work_date=date(2026, 7, 31),
                clock_in="08:00",
                clock_out="12:00",
                overtime_after_minutes=480,
            )
        )
        with closing(sqlite3.connect(self.database_path)) as connection:
            before = connection.execute(
                "SELECT regular_minutes, overtime_minutes FROM shifts WHERE id = ?",
                (second_id,),
            ).fetchone()
        self.assertEqual(before, (0, 240))

        updated = self.make_shift(
            work_date=date(2026, 7, 30),
            clock_in="08:00",
            clock_out="13:00",
            breaks=(60,),
            overtime_after_minutes=480,
        )
        self.database.update_shift(first_id, updated)

        stored = self.database.get_shift(first_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.break_durations, (60,))
        with closing(sqlite3.connect(self.database_path)) as connection:
            after = connection.execute(
                "SELECT regular_minutes, overtime_minutes FROM shifts WHERE id = ?",
                (second_id,),
            ).fetchone()
        self.assertEqual(after, (240, 0))

    def test_delete_recalculates_later_overtime(self) -> None:
        first_id = self.database.save_shift(
            self.make_shift(
                work_date=date(2026, 7, 30),
                clock_in="08:00",
                clock_out="16:00",
                overtime_after_minutes=480,
            )
        )
        second_id = self.database.save_shift(
            self.make_shift(
                work_date=date(2026, 7, 31),
                clock_in="08:00",
                clock_out="12:00",
                overtime_after_minutes=480,
            )
        )

        self.assertTrue(self.database.delete_shift(first_id))
        self.assertFalse(self.database.delete_shift(first_id))
        with closing(sqlite3.connect(self.database_path)) as connection:
            recalculated = connection.execute(
                "SELECT regular_minutes, overtime_minutes FROM shifts WHERE id = ?",
                (second_id,),
            ).fetchone()
        self.assertEqual(recalculated, (240, 0))


if __name__ == "__main__":
    unittest.main()
