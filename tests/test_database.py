from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from easyfi.calculations import calculate_shift
from easyfi.database import Database, PaymentToSave, ShiftToSave


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
        self.assertEqual(
            self.database.get_setting("default_clock_in", "missing"), "08:30"
        )
        self.assertEqual(
            self.database.get_setting("default_clock_out", "missing"), "17:00"
        )
        self.assertEqual(
            self.database.get_setting("default_break_minutes", "missing"), "30"
        )
        sources = self.database.list_income_sources()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].name, "Main job")
        self.assertEqual(sources[0].hourly_rate_cents, 2400)
        self.assertTrue(sources[0].active)

    def test_settings_and_income_source_lifecycle(self) -> None:
        self.database.update_settings(
            {
                "work_week_start": "6",
                "default_clock_in": "07:15",
                "default_clock_out": "15:45",
                "default_break_minutes": "45",
            }
        )
        self.assertEqual(self.database.get_setting_int("work_week_start", -1), 6)
        self.assertEqual(
            self.database.get_setting("default_clock_in", "missing"), "07:15"
        )

        source_id = self.database.add_income_source(
            name="Weekend job",
            hourly_rate_cents=1850,
            tax_rate_bps=1500,
            overtime_after_minutes=1800,
            overtime_multiplier_milli=2000,
        )
        self.database.update_income_source(
            source_id,
            name="Weekend work",
            hourly_rate_cents=2000,
            tax_rate_bps=1600,
            overtime_after_minutes=1920,
            overtime_multiplier_milli=1750,
        )
        source = next(
            item
            for item in self.database.list_income_sources(include_inactive=True)
            if item.id == source_id
        )
        self.assertEqual(source.name, "Weekend work")
        self.assertEqual(source.hourly_rate_cents, 2000)
        self.assertEqual(source.overtime_multiplier_milli, 1750)

        self.database.set_income_source_active(source_id, False)
        self.assertNotIn(source_id, [item.id for item in self.database.list_income_sources()])
        archived = next(
            item
            for item in self.database.list_income_sources(include_inactive=True)
            if item.id == source_id
        )
        self.assertFalse(archived.active)
        self.database.set_income_source_active(source_id, True)
        self.assertIn(source_id, [item.id for item in self.database.list_income_sources()])

        with self.assertRaisesRegex(ValueError, "already exists"):
            self.database.add_income_source(
                name="weekend WORK",
                hourly_rate_cents=2000,
                tax_rate_bps=0,
                overtime_after_minutes=2400,
                overtime_multiplier_milli=1500,
            )

    def test_last_active_income_source_cannot_be_archived(self) -> None:
        source = self.database.list_income_sources()[0]
        with self.assertRaisesRegex(ValueError, "At least one"):
            self.database.set_income_source_active(source.id, False)

    def test_changing_week_start_regroups_overtime(self) -> None:
        sunday_id = self.database.save_shift(
            self.make_shift(
                work_date=date(2026, 8, 2),
                clock_in="08:00",
                clock_out="16:00",
                overtime_after_minutes=480,
            )
        )
        monday_id = self.database.save_shift(
            self.make_shift(
                work_date=date(2026, 8, 3),
                clock_in="08:00",
                clock_out="12:00",
                overtime_after_minutes=480,
            )
        )
        self.assertGreater(sunday_id, 0)
        with closing(sqlite3.connect(self.database_path)) as connection:
            before = connection.execute(
                "SELECT regular_minutes, overtime_minutes FROM shifts WHERE id = ?",
                (monday_id,),
            ).fetchone()
        self.assertEqual(before, (0, 240))

        self.database.update_settings({"work_week_start": "0"})
        with closing(sqlite3.connect(self.database_path)) as connection:
            after = connection.execute(
                "SELECT regular_minutes, overtime_minutes FROM shifts WHERE id = ?",
                (monday_id,),
            ).fetchone()
        self.assertEqual(after, (240, 0))

    def test_payment_summary_uses_gross_wages_and_supports_partial_payments(self) -> None:
        source = self.database.list_income_sources()[0]
        self.database.save_shift(
            self.make_shift(
                work_date=date(2026, 8, 3),
                clock_in="09:00",
                clock_out="17:00",
            )
        )
        first_payment = PaymentToSave(
            income_source_id=source.id,
            paid_on=date(2026, 8, 7),
            work_week_reference_date=date(2026, 8, 3),
            amount_cents=5_000,
            notes="Partial deposit",
        )
        first_id = self.database.save_payment(first_payment)
        self.assertTrue(self.database.has_duplicate_payment(first_payment))
        self.assertFalse(
            self.database.has_duplicate_payment(
                first_payment, exclude_payment_id=first_id
            )
        )

        summary = self.database.payment_summary(
            income_source_id=source.id, reference_date=date(2026, 8, 3)
        )
        self.assertEqual(summary.gross_earned_cents, 19_200)
        self.assertEqual(summary.payments_received_cents, 5_000)
        self.assertEqual(summary.amount_owed_cents, 14_200)
        self.assertEqual(summary.overpaid_cents, 0)

        second_id = self.database.save_payment(
            PaymentToSave(
                income_source_id=source.id,
                paid_on=date(2026, 8, 8),
                work_week_reference_date=date(2026, 8, 3),
                amount_cents=14_200,
            )
        )
        paid = self.database.payment_summary(
            income_source_id=source.id, reference_date=date(2026, 8, 3)
        )
        self.assertEqual(paid.amount_owed_cents, 0)
        self.assertEqual(paid.overpaid_cents, 0)

        self.database.update_payment(
            second_id,
            PaymentToSave(
                income_source_id=source.id,
                paid_on=date(2026, 8, 8),
                work_week_reference_date=date(2026, 8, 3),
                amount_cents=15_000,
                notes="Corrected deposit",
            ),
        )
        overpaid = self.database.payment_summary(
            income_source_id=source.id, reference_date=date(2026, 8, 3)
        )
        self.assertEqual(overpaid.amount_owed_cents, 0)
        self.assertEqual(overpaid.overpaid_cents, 800)
        self.assertEqual(self.database.get_payment(second_id).notes, "Corrected deposit")

        self.assertTrue(self.database.delete_payment(second_id))
        self.assertFalse(self.database.delete_payment(second_id))
        remaining = self.database.payment_summary(
            income_source_id=source.id, reference_date=date(2026, 8, 3)
        )
        self.assertEqual(remaining.amount_owed_cents, 14_200)

    def test_payment_week_is_realigned_when_work_week_start_changes(self) -> None:
        source = self.database.list_income_sources()[0]
        payment_id = self.database.save_payment(
            PaymentToSave(
                income_source_id=source.id,
                paid_on=date(2026, 8, 7),
                work_week_reference_date=date(2026, 8, 3),
                amount_cents=10_000,
            )
        )
        self.assertEqual(
            self.database.get_payment(payment_id).work_week_start,
            date(2026, 7, 30),
        )
        self.database.update_settings({"work_week_start": "0"})
        self.assertEqual(
            self.database.get_payment(payment_id).work_week_start,
            date(2026, 8, 3),
        )

    def test_biweekly_payment_is_applied_to_covered_weeks_oldest_first(self) -> None:
        source_id = self.database.add_income_source(
            name="Biweekly employer",
            hourly_rate_cents=25_000,
            tax_rate_bps=0,
            overtime_after_minutes=2400,
            overtime_multiplier_milli=1500,
        )
        for work_date, clock_out in (
            (date(2026, 7, 24), "11:00"),
            (date(2026, 7, 31), "10:00"),
        ):
            calculation = calculate_shift(
                clock_in="09:00",
                clock_out=clock_out,
                break_durations=(),
                hourly_rate_cents=25_000,
                tax_rate_bps=0,
            )
            self.database.save_shift(
                ShiftToSave(
                    income_source_id=source_id,
                    work_date=work_date,
                    clock_in="09:00",
                    clock_out=clock_out,
                    break_durations=(),
                    hourly_rate_cents=25_000,
                    tax_rate_bps=0,
                    overtime_after_minutes=2400,
                    overtime_multiplier_milli=1500,
                    calculation=calculation,
                )
            )

        payment = PaymentToSave(
            income_source_id=source_id,
            paid_on=date(2026, 8, 3),
            work_week_reference_date=date(2026, 8, 3),
            amount_cents=65_000,
            pay_period_weeks=2,
        )
        payment_id = self.database.save_payment(payment)

        summary = self.database.payment_summary(
            income_source_id=source_id,
            reference_date=date(2026, 8, 3),
            pay_period_weeks=2,
        )
        self.assertEqual(summary.week_start, date(2026, 7, 23))
        self.assertEqual(summary.week_end, date(2026, 8, 5))
        self.assertEqual(summary.pay_period_weeks, 2)
        self.assertEqual(summary.gross_earned_cents, 75_000)
        self.assertEqual(summary.payments_received_cents, 65_000)
        self.assertEqual(summary.amount_owed_cents, 10_000)

        one_week_view = self.database.payment_summary(
            income_source_id=source_id,
            reference_date=date(2026, 8, 3),
            pay_period_weeks=1,
        )
        self.assertEqual(one_week_view.gross_earned_cents, 25_000)
        self.assertEqual(one_week_view.payments_received_cents, 0)
        self.assertEqual(self.database.get_payment(payment_id).pay_period_weeks, 2)
        self.assertTrue(self.database.has_duplicate_payment(payment))

        previous_overview = self.database.overview_summary(
            reference_date=date(2026, 7, 24),
            income_source_id=source_id,
        )
        self.assertEqual(previous_overview.gross_earned_cents, 50_000)
        self.assertEqual(previous_overview.payments_received_cents, 50_000)
        self.assertEqual(previous_overview.amount_owed_cents, 0)

        current_overview = self.database.overview_summary(
            reference_date=date(2026, 8, 3),
            income_source_id=source_id,
        )
        self.assertEqual(current_overview.gross_earned_cents, 25_000)
        self.assertEqual(current_overview.payments_received_cents, 15_000)
        self.assertEqual(current_overview.previous_amount_owed_cents, 0)
        self.assertEqual(current_overview.amount_owed_cents, 10_000)
        self.assertEqual(current_overview.overpaid_cents, 0)

    def test_existing_payment_table_is_migrated(self) -> None:
        migrated_path = Path(self.temp_directory.name) / "migration-test.db"
        with closing(sqlite3.connect(migrated_path)) as connection:
            connection.execute(
                """
                CREATE TABLE payments (
                    id INTEGER PRIMARY KEY,
                    income_source_id INTEGER,
                    work_week_start TEXT,
                    paid_on TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
        migrated_database = Database(migrated_path)
        migrated_database.initialize()
        with closing(sqlite3.connect(migrated_path)) as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(payments)")
            }
        self.assertIn("work_week_reference_date", columns)
        self.assertIn("pay_period_weeks", columns)

    def test_payment_summary_adds_prior_unpaid_balance_to_selected_period(self) -> None:
        source_id = self.database.add_income_source(
            name="Carry-forward employer",
            hourly_rate_cents=20_500,
            tax_rate_bps=0,
            overtime_after_minutes=6000,
            overtime_multiplier_milli=1500,
        )
        prior_calculation = calculate_shift(
            clock_in="09:00",
            clock_out="10:00",
            break_durations=(),
            hourly_rate_cents=20_500,
            tax_rate_bps=0,
            overtime_after_minutes=6000,
        )
        self.database.save_shift(
            ShiftToSave(
                income_source_id=source_id,
                work_date=date(2026, 5, 21),
                clock_in="09:00",
                clock_out="10:00",
                break_durations=(),
                hourly_rate_cents=20_500,
                tax_rate_bps=0,
                overtime_after_minutes=6000,
                overtime_multiplier_milli=1500,
                calculation=prior_calculation,
            )
        )
        self.database.save_payment(
            PaymentToSave(
                income_source_id=source_id,
                paid_on=date(2026, 5, 27),
                work_week_reference_date=date(2026, 5, 27),
                amount_cents=10_000,
            )
        )

        current_calculation = calculate_shift(
            clock_in="09:00",
            clock_out="10:00",
            break_durations=(),
            hourly_rate_cents=285_866,
            tax_rate_bps=0,
            overtime_after_minutes=6000,
        )
        self.database.save_shift(
            ShiftToSave(
                income_source_id=source_id,
                work_date=date(2026, 6, 1),
                clock_in="09:00",
                clock_out="10:00",
                break_durations=(),
                hourly_rate_cents=285_866,
                tax_rate_bps=0,
                overtime_after_minutes=6000,
                overtime_multiplier_milli=1500,
                calculation=current_calculation,
            )
        )
        self.database.save_payment(
            PaymentToSave(
                income_source_id=source_id,
                paid_on=date(2026, 6, 24),
                work_week_reference_date=date(2026, 6, 24),
                amount_cents=100_000,
                pay_period_weeks=4,
            )
        )

        summary = self.database.payment_summary(
            income_source_id=source_id,
            reference_date=date(2026, 6, 24),
            pay_period_weeks=4,
        )
        self.assertEqual(summary.opening_balance_cents, 10_500)
        self.assertEqual(summary.gross_earned_cents, 285_866)
        self.assertEqual(summary.payments_received_cents, 100_000)
        self.assertEqual(summary.amount_owed_cents, 196_366)
        self.assertEqual(summary.overpaid_cents, 0)

    def test_overview_aggregates_sources_without_offsetting_employer_balances(self) -> None:
        main_source = self.database.list_income_sources()[0]
        self.database.save_shift(
            self.make_shift(
                work_date=date(2026, 7, 27),
                clock_in="09:00",
                clock_out="17:00",
            )
        )
        self.database.save_shift(
            self.make_shift(
                work_date=date(2026, 8, 3),
                clock_in="09:00",
                clock_out="17:00",
            )
        )
        second_source_id = self.database.add_income_source(
            name="Second employer",
            hourly_rate_cents=2000,
            tax_rate_bps=0,
            overtime_after_minutes=2400,
            overtime_multiplier_milli=1500,
        )
        second_calculation = calculate_shift(
            clock_in="09:00",
            clock_out="14:00",
            break_durations=(),
            hourly_rate_cents=2000,
            tax_rate_bps=0,
        )
        self.database.save_shift(
            ShiftToSave(
                income_source_id=second_source_id,
                work_date=date(2026, 8, 4),
                clock_in="09:00",
                clock_out="14:00",
                break_durations=(),
                hourly_rate_cents=2000,
                tax_rate_bps=0,
                overtime_after_minutes=2400,
                overtime_multiplier_milli=1500,
                calculation=second_calculation,
            )
        )
        self.database.save_payment(
            PaymentToSave(
                income_source_id=main_source.id,
                paid_on=date(2026, 8, 6),
                work_week_reference_date=date(2026, 8, 3),
                amount_cents=20_000,
            )
        )

        overview = self.database.overview_summary(reference_date=date(2026, 8, 3))
        self.assertEqual(overview.paid_minutes, 780)
        self.assertEqual(overview.gross_earned_cents, 29_200)
        self.assertEqual(overview.payments_received_cents, 20_000)
        self.assertEqual(overview.amount_owed_cents, 28_400)
        self.assertEqual(overview.overpaid_cents, 0)
        self.assertEqual(overview.previous_paid_minutes, 480)
        self.assertEqual(overview.previous_gross_earned_cents, 19_200)
        self.assertEqual(overview.previous_amount_owed_cents, 19_200)
        self.assertEqual(len(overview.source_rows), 2)

        main_only = self.database.overview_summary(
            reference_date=date(2026, 8, 3),
            income_source_id=main_source.id,
        )
        self.assertEqual(main_only.gross_earned_cents, 19_200)
        self.assertEqual(main_only.amount_owed_cents, 18_400)
        self.assertEqual(main_only.overpaid_cents, 0)

    def test_overview_carries_unpaid_wages_forward_and_applies_current_payment(self) -> None:
        source_id = self.database.add_income_source(
            name="Cumulative balance employer",
            hourly_rate_cents=10_000,
            tax_rate_bps=0,
            overtime_after_minutes=6000,
            overtime_multiplier_milli=1500,
        )

        def save_shift(work_date: date, hours: int) -> None:
            calculation = calculate_shift(
                clock_in="09:00",
                clock_out=f"{9 + hours:02d}:00",
                break_durations=(),
                hourly_rate_cents=10_000,
                tax_rate_bps=0,
                overtime_after_minutes=6000,
            )
            self.database.save_shift(
                ShiftToSave(
                    income_source_id=source_id,
                    work_date=work_date,
                    clock_in="09:00",
                    clock_out=f"{9 + hours:02d}:00",
                    break_durations=(),
                    hourly_rate_cents=10_000,
                    tax_rate_bps=0,
                    overtime_after_minutes=6000,
                    overtime_multiplier_milli=1500,
                    calculation=calculation,
                )
            )

        save_shift(date(2026, 7, 17), 3)  # $300 in week one
        save_shift(date(2026, 7, 24), 3)  # $300 in week two
        save_shift(date(2026, 7, 31), 4)  # $400 in the current week
        self.database.save_payment(
            PaymentToSave(
                income_source_id=source_id,
                paid_on=date(2026, 8, 3),
                work_week_reference_date=date(2026, 8, 3),
                amount_cents=50_000,
            )
        )

        overview = self.database.overview_summary(
            reference_date=date(2026, 8, 3),
            income_source_id=source_id,
        )
        self.assertEqual(overview.gross_earned_cents, 40_000)
        self.assertEqual(overview.payments_received_cents, 50_000)
        self.assertEqual(overview.previous_amount_owed_cents, 60_000)
        self.assertEqual(overview.amount_owed_cents, 50_000)
        self.assertEqual(overview.overpaid_cents, 0)
        self.assertEqual(len(overview.source_rows), 1)
        self.assertEqual(overview.source_rows[0].amount_owed_cents, 50_000)

    def test_verified_backup_and_restore_preserve_recoverable_copy(self) -> None:
        backup_path = Path(self.temp_directory.name) / "manual-backup.db"
        self.database.backup_to(backup_path)
        self.assertTrue(backup_path.exists())
        self.assertEqual(self.database.integrity_check(backup_path), (True, "Integrity check passed."))

        added_id = self.database.add_income_source(
            name="Temporary source",
            hourly_rate_cents=3000,
            tax_rate_bps=0,
            overtime_after_minutes=2400,
            overtime_multiplier_milli=1500,
        )
        self.assertIn(
            added_id,
            [source.id for source in self.database.list_income_sources()],
        )

        safety_backup = self.database.restore_from(backup_path)
        self.assertTrue(safety_backup.exists())
        self.assertEqual(self.database.integrity_check()[0], True)
        self.assertNotIn(
            "Temporary source",
            [source.name for source in self.database.list_income_sources()],
        )
        safety_database = Database(safety_backup)
        self.assertIn(
            "Temporary source",
            [source.name for source in safety_database.list_income_sources()],
        )

    def test_csv_export_contains_all_data_tables(self) -> None:
        export_root = Path(self.temp_directory.name) / "exports"
        export_directory = self.database.export_csv(export_root)
        expected = {
            "settings.csv",
            "income_sources.csv",
            "shifts.csv",
            "shift_breaks.csv",
            "payments.csv",
        }
        self.assertEqual(
            {item.name for item in export_directory.iterdir()}, expected
        )
        source_export = (export_directory / "income_sources.csv").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("Main job", source_export)

    def test_automatic_backups_rotate_to_configured_retention(self) -> None:
        self.database.update_settings(
            {
                "automatic_backups_enabled": "1",
                "automatic_backup_keep_count": "2",
                "last_automatic_backup": "",
            }
        )
        for _index in range(3):
            backup = self.database.create_automatic_backup_if_due()
            self.assertIsNotNone(backup)
            self.database.update_settings({"last_automatic_backup": ""})
        backups = list(
            self.database.automatic_backup_directory().glob("easyfi-auto-*.db")
        )
        self.assertEqual(len(backups), 2)
        self.assertTrue(all(self.database.integrity_check(item)[0] for item in backups))

    def test_restore_rejects_non_easyfi_database(self) -> None:
        unrelated = Path(self.temp_directory.name) / "unrelated.db"
        with closing(sqlite3.connect(unrelated)) as connection:
            connection.execute("CREATE TABLE something_else(id INTEGER PRIMARY KEY)")
        with self.assertRaisesRegex(ValueError, "Restore rejected"):
            self.database.restore_from(unrelated)

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
