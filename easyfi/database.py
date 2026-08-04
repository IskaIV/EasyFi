"""SQLite persistence for EasyFi."""

from __future__ import annotations

import csv
import os
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator, Sequence

from .calculations import ShiftCalculation, calculate_shift, work_week_bounds
from .paths import database_path


SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class IncomeSource:
    id: int
    name: str
    hourly_rate_cents: int
    tax_rate_bps: int
    overtime_after_minutes: int
    overtime_multiplier_milli: int
    active: bool


@dataclass(frozen=True, slots=True)
class ShiftToSave:
    income_source_id: int
    work_date: date
    clock_in: str
    clock_out: str
    break_durations: tuple[int, ...]
    hourly_rate_cents: int
    tax_rate_bps: int
    overtime_after_minutes: int
    overtime_multiplier_milli: int
    calculation: ShiftCalculation
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ShiftRecord:
    id: int
    income_source_id: int
    work_date: date
    clock_in: str
    clock_out: str
    break_durations: tuple[int, ...]
    hourly_rate_cents: int
    tax_rate_bps: int
    overtime_after_minutes: int
    overtime_multiplier_milli: int
    notes: str


@dataclass(frozen=True, slots=True)
class PaymentToSave:
    income_source_id: int
    paid_on: date
    work_week_reference_date: date
    amount_cents: int
    notes: str = ""


@dataclass(frozen=True, slots=True)
class PaymentRecord:
    id: int
    income_source_id: int
    source_name: str
    paid_on: date
    work_week_start: date
    work_week_reference_date: date
    amount_cents: int
    notes: str


@dataclass(frozen=True, slots=True)
class PaymentSummary:
    income_source_id: int
    week_start: date
    week_end: date
    gross_earned_cents: int
    payments_received_cents: int
    amount_owed_cents: int
    overpaid_cents: int


@dataclass(frozen=True, slots=True)
class OverviewSourceSummary:
    income_source_id: int
    source_name: str
    paid_minutes: int
    regular_minutes: int
    overtime_minutes: int
    gross_earned_cents: int
    estimated_tax_cents: int
    estimated_take_home_cents: int
    payments_received_cents: int
    amount_owed_cents: int
    overpaid_cents: int


@dataclass(frozen=True, slots=True)
class OverviewSummary:
    week_start: date
    week_end: date
    source_rows: tuple[OverviewSourceSummary, ...]
    paid_minutes: int
    regular_minutes: int
    overtime_minutes: int
    gross_earned_cents: int
    estimated_tax_cents: int
    estimated_take_home_cents: int
    payments_received_cents: int
    amount_owed_cents: int
    overpaid_cents: int
    previous_paid_minutes: int
    previous_gross_earned_cents: int
    previous_amount_owed_cents: int


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or database_path()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS income_sources (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    hourly_rate_cents INTEGER NOT NULL CHECK (hourly_rate_cents >= 0),
                    tax_rate_bps INTEGER NOT NULL CHECK (tax_rate_bps BETWEEN 0 AND 10000),
                    overtime_after_minutes INTEGER NOT NULL DEFAULT 2400,
                    overtime_multiplier_milli INTEGER NOT NULL DEFAULT 1500,
                    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS shifts (
                    id INTEGER PRIMARY KEY,
                    income_source_id INTEGER NOT NULL REFERENCES income_sources(id),
                    work_date TEXT NOT NULL,
                    clock_in TEXT NOT NULL,
                    clock_out TEXT NOT NULL,
                    hourly_rate_cents INTEGER NOT NULL,
                    tax_rate_bps INTEGER NOT NULL,
                    overtime_after_minutes INTEGER NOT NULL,
                    overtime_multiplier_milli INTEGER NOT NULL,
                    elapsed_minutes INTEGER NOT NULL,
                    break_minutes INTEGER NOT NULL,
                    paid_minutes INTEGER NOT NULL,
                    regular_minutes INTEGER NOT NULL,
                    overtime_minutes INTEGER NOT NULL,
                    regular_pay_cents INTEGER NOT NULL,
                    overtime_pay_cents INTEGER NOT NULL,
                    gross_pay_cents INTEGER NOT NULL,
                    tax_cents INTEGER NOT NULL,
                    net_pay_cents INTEGER NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS shift_breaks (
                    id INTEGER PRIMARY KEY,
                    shift_id INTEGER NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
                    duration_minutes INTEGER NOT NULL CHECK (duration_minutes >= 0),
                    paid INTEGER NOT NULL DEFAULT 0 CHECK (paid IN (0, 1)),
                    sort_order INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY,
                    income_source_id INTEGER REFERENCES income_sources(id),
                    work_week_start TEXT,
                    work_week_reference_date TEXT,
                    paid_on TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_shifts_source_date
                    ON shifts(income_source_id, work_date);

                CREATE INDEX IF NOT EXISTS idx_payments_source_week
                    ON payments(income_source_id, work_week_start);
                """
            )
            self._ensure_payment_schema(connection)
            defaults = {
                "work_week_start": "3",
                "currency": "USD",
                "default_clock_in": "08:30",
                "default_clock_out": "17:00",
                "default_break_minutes": "30",
                "automatic_backups_enabled": "1",
                "automatic_backup_keep_count": "10",
                "last_automatic_backup": "",
            }
            connection.executemany(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                defaults.items(),
            )
            existing = connection.execute(
                "SELECT 1 FROM income_sources LIMIT 1"
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO income_sources(
                        name, hourly_rate_cents, tax_rate_bps,
                        overtime_after_minutes, overtime_multiplier_milli, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("Main job", 2400, 1800, 2400, 1500, _now()),
                )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def get_setting_int(self, key: str, default: int) -> int:
        value = self.get_setting(key, str(default))
        try:
            return int(value)
        except ValueError:
            return default

    def get_setting(self, key: str, default: str) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return default if row is None else str(row["value"])

    def update_settings(self, values: dict[str, str]) -> None:
        allowed = {
            "work_week_start",
            "currency",
            "default_clock_in",
            "default_clock_out",
            "default_break_minutes",
            "automatic_backups_enabled",
            "automatic_backup_keep_count",
            "last_automatic_backup",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Unsupported setting: {sorted(unknown)[0]}")
        with self.connect() as connection:
            old_week_start = self._get_setting_int(
                connection, "work_week_start", 3
            )
            connection.executemany(
                """
                INSERT INTO settings(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                [(key, str(value)) for key, value in values.items()],
            )
            new_week_start = self._get_setting_int(
                connection, "work_week_start", 3
            )
            if new_week_start != old_week_start:
                self._recalculate_all_shifts(connection)
                self._realign_payments(connection, new_week_start)

    def integrity_check(self, path: Path | None = None) -> tuple[bool, str]:
        target = Path(path) if path is not None else self.path
        if not target.exists() or not target.is_file():
            return False, "Database file does not exist."
        try:
            with closing(sqlite3.connect(target)) as connection:
                results = [
                    str(row[0])
                    for row in connection.execute("PRAGMA integrity_check").fetchall()
                ]
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
        except sqlite3.Error as exc:
            return False, f"SQLite could not read the file: {exc}"
        if results != ["ok"]:
            return False, "; ".join(results)
        required = {"settings", "income_sources", "shifts", "shift_breaks", "payments"}
        missing = sorted(required - tables)
        if missing:
            return False, f"Not an EasyFi database; missing table: {missing[0]}."
        return True, "Integrity check passed."

    def backup_to(self, destination: Path) -> Path:
        destination = Path(destination).expanduser().resolve()
        source = self.path.expanduser().resolve()
        if destination == source:
            raise ValueError("Choose a backup location different from the live database.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._temporary_database_path(destination.parent, "backup-")
        try:
            self._copy_database(source, temporary)
            valid, message = self.integrity_check(temporary)
            if not valid:
                raise ValueError(f"Backup verification failed: {message}")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def restore_from(self, source: Path) -> Path:
        source = Path(source).expanduser().resolve()
        live_database = self.path.expanduser().resolve()
        if source == live_database:
            raise ValueError("The selected file is already the live EasyFi database.")
        valid, message = self.integrity_check(source)
        if not valid:
            raise ValueError(f"Restore rejected: {message}")

        safety_directory = self.automatic_backup_directory()
        safety_directory.mkdir(parents=True, exist_ok=True)
        safety_backup = safety_directory / self._timestamped_name("easyfi-pre-restore")
        self.backup_to(safety_backup)

        live_database.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._temporary_database_path(live_database.parent, "restore-")
        try:
            self._copy_database(source, temporary)
            restored_database = Database(temporary)
            restored_database.initialize()
            valid, message = restored_database.integrity_check()
            if not valid:
                raise ValueError(f"Restored database verification failed: {message}")
            os.replace(temporary, live_database)
        finally:
            temporary.unlink(missing_ok=True)
        return safety_backup

    def export_csv(self, destination_directory: Path) -> Path:
        destination_directory = Path(destination_directory).expanduser().resolve()
        destination_directory.mkdir(parents=True, exist_ok=True)
        export_directory = destination_directory / datetime.now().strftime(
            "EasyFi-export-%Y%m%d-%H%M%S-%f"
        )
        export_directory.mkdir(parents=False, exist_ok=False)
        queries = {
            "settings.csv": "SELECT key, value FROM settings ORDER BY key",
            "income_sources.csv": """
                SELECT id, name, hourly_rate_cents, tax_rate_bps,
                       overtime_after_minutes, overtime_multiplier_milli,
                       active, created_at
                FROM income_sources ORDER BY name COLLATE NOCASE
            """,
            "shifts.csv": """
                SELECT shifts.*, income_sources.name AS income_source_name
                FROM shifts
                JOIN income_sources ON income_sources.id = shifts.income_source_id
                ORDER BY work_date, clock_in, shifts.id
            """,
            "shift_breaks.csv": """
                SELECT shift_breaks.* FROM shift_breaks
                ORDER BY shift_id, sort_order, id
            """,
            "payments.csv": """
                SELECT payments.*, income_sources.name AS income_source_name
                FROM payments
                JOIN income_sources ON income_sources.id = payments.income_source_id
                ORDER BY paid_on, payments.id
            """,
        }
        try:
            with self.connect() as connection:
                for filename, query in queries.items():
                    cursor = connection.execute(query)
                    headers = [item[0] for item in cursor.description]
                    with (export_directory / filename).open(
                        "w", newline="", encoding="utf-8-sig"
                    ) as output:
                        writer = csv.writer(output)
                        writer.writerow(headers)
                        writer.writerows(cursor.fetchall())
        except Exception:
            for exported_file in export_directory.glob("*.csv"):
                exported_file.unlink(missing_ok=True)
            export_directory.rmdir()
            raise
        return export_directory

    def automatic_backup_directory(self) -> Path:
        return self.path.parent / "backups"

    def create_automatic_backup_if_due(self) -> Path | None:
        if self.get_setting_int("automatic_backups_enabled", 1) != 1:
            return None
        today = date.today().isoformat()
        if self.get_setting("last_automatic_backup", "") == today:
            return None
        backup_directory = self.automatic_backup_directory()
        backup_directory.mkdir(parents=True, exist_ok=True)
        destination = backup_directory / self._timestamped_name("easyfi-auto")
        self.backup_to(destination)
        self.update_settings({"last_automatic_backup": today})
        keep_count = min(
            100,
            max(1, self.get_setting_int("automatic_backup_keep_count", 10)),
        )
        backups = sorted(
            backup_directory.glob("easyfi-auto-*.db"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
        for expired in backups[keep_count:]:
            expired.unlink(missing_ok=True)
        return destination

    @staticmethod
    def _copy_database(source: Path, destination: Path) -> None:
        if not source.exists():
            raise ValueError("Database file does not exist.")
        with closing(sqlite3.connect(source)) as source_connection:
            with closing(sqlite3.connect(destination)) as destination_connection:
                source_connection.backup(destination_connection)
                destination_connection.commit()

    @staticmethod
    def _temporary_database_path(directory: Path, prefix: str) -> Path:
        handle = tempfile.NamedTemporaryFile(
            prefix=prefix,
            suffix=".db.tmp",
            dir=directory,
            delete=False,
        )
        handle.close()
        return Path(handle.name)

    @staticmethod
    def _timestamped_name(prefix: str) -> str:
        return datetime.now().strftime(f"{prefix}-%Y%m%d-%H%M%S-%f.db")

    def list_income_sources(
        self, *, include_inactive: bool = False
    ) -> list[IncomeSource]:
        with self.connect() as connection:
            active_filter = "" if include_inactive else "WHERE active = 1"
            rows = connection.execute(
                f"""
                SELECT id, name, hourly_rate_cents, tax_rate_bps,
                       overtime_after_minutes, overtime_multiplier_milli, active
                FROM income_sources
                {active_filter}
                ORDER BY name COLLATE NOCASE
                """
            ).fetchall()
        return [
            IncomeSource(
                id=int(row["id"]),
                name=row["name"],
                hourly_rate_cents=int(row["hourly_rate_cents"]),
                tax_rate_bps=int(row["tax_rate_bps"]),
                overtime_after_minutes=int(row["overtime_after_minutes"]),
                overtime_multiplier_milli=int(row["overtime_multiplier_milli"]),
                active=bool(row["active"]),
            )
            for row in rows
        ]

    def add_income_source(
        self,
        *,
        name: str,
        hourly_rate_cents: int,
        tax_rate_bps: int,
        overtime_after_minutes: int,
        overtime_multiplier_milli: int,
    ) -> int:
        clean_name = self._validate_income_source_values(
            name,
            hourly_rate_cents,
            tax_rate_bps,
            overtime_after_minutes,
            overtime_multiplier_milli,
        )
        with self.connect() as connection:
            self._ensure_unique_source_name(connection, clean_name)
            cursor = connection.execute(
                """
                INSERT INTO income_sources(
                    name, hourly_rate_cents, tax_rate_bps,
                    overtime_after_minutes, overtime_multiplier_milli,
                    active, created_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    clean_name,
                    hourly_rate_cents,
                    tax_rate_bps,
                    overtime_after_minutes,
                    overtime_multiplier_milli,
                    _now(),
                ),
            )
        return int(cursor.lastrowid)

    def update_income_source(
        self,
        source_id: int,
        *,
        name: str,
        hourly_rate_cents: int,
        tax_rate_bps: int,
        overtime_after_minutes: int,
        overtime_multiplier_milli: int,
    ) -> None:
        clean_name = self._validate_income_source_values(
            name,
            hourly_rate_cents,
            tax_rate_bps,
            overtime_after_minutes,
            overtime_multiplier_milli,
        )
        with self.connect() as connection:
            self._ensure_unique_source_name(connection, clean_name, source_id)
            cursor = connection.execute(
                """
                UPDATE income_sources
                SET name = ?, hourly_rate_cents = ?, tax_rate_bps = ?,
                    overtime_after_minutes = ?, overtime_multiplier_milli = ?
                WHERE id = ?
                """,
                (
                    clean_name,
                    hourly_rate_cents,
                    tax_rate_bps,
                    overtime_after_minutes,
                    overtime_multiplier_milli,
                    source_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError("The selected income source no longer exists.")

    def set_income_source_active(self, source_id: int, active: bool) -> None:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT active FROM income_sources WHERE id = ?", (source_id,)
            ).fetchone()
            if existing is None:
                raise ValueError("The selected income source no longer exists.")
            if not active and bool(existing["active"]):
                active_count = connection.execute(
                    "SELECT COUNT(*) AS total FROM income_sources WHERE active = 1"
                ).fetchone()["total"]
                if int(active_count) <= 1:
                    raise ValueError("At least one income source must remain active.")
            connection.execute(
                "UPDATE income_sources SET active = ? WHERE id = ?",
                (1 if active else 0, source_id),
            )

    @staticmethod
    def _validate_income_source_values(
        name: str,
        hourly_rate_cents: int,
        tax_rate_bps: int,
        overtime_after_minutes: int,
        overtime_multiplier_milli: int,
    ) -> str:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Income source name is required.")
        if len(clean_name) > 100:
            raise ValueError("Income source name must be 100 characters or fewer.")
        if hourly_rate_cents <= 0:
            raise ValueError("Hourly rate must be greater than $0.00.")
        if not 0 <= tax_rate_bps <= 10_000:
            raise ValueError("Estimated tax must be between 0% and 100%.")
        if not 0 <= overtime_after_minutes <= 7 * 24 * 60:
            raise ValueError("Overtime threshold must be between 0 and 168 hours.")
        if not 1000 <= overtime_multiplier_milli <= 5000:
            raise ValueError("Overtime multiplier must be between 1.0x and 5.0x.")
        return clean_name

    @staticmethod
    def _ensure_unique_source_name(
        connection: sqlite3.Connection,
        name: str,
        exclude_source_id: int | None = None,
    ) -> None:
        duplicate = connection.execute(
            """
            SELECT 1 FROM income_sources
            WHERE name = ? COLLATE NOCASE
              AND id != COALESCE(?, -1)
            LIMIT 1
            """,
            (name, exclude_source_id),
        ).fetchone()
        if duplicate is not None:
            raise ValueError("An income source with that name already exists.")

    def save_payment(self, payment: PaymentToSave) -> int:
        with self.connect() as connection:
            self._validate_payment(connection, payment)
            week_start, _week_end = self._payment_week_bounds(
                connection, payment.work_week_reference_date
            )
            cursor = connection.execute(
                """
                INSERT INTO payments(
                    income_source_id, work_week_start, work_week_reference_date,
                    paid_on, amount_cents, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payment.income_source_id,
                    week_start.isoformat(),
                    payment.work_week_reference_date.isoformat(),
                    payment.paid_on.isoformat(),
                    payment.amount_cents,
                    payment.notes.strip(),
                    _now(),
                ),
            )
        return int(cursor.lastrowid)

    def get_payment(self, payment_id: int) -> PaymentRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT payments.id, payments.income_source_id,
                       income_sources.name AS source_name, payments.paid_on,
                       payments.work_week_start,
                       COALESCE(payments.work_week_reference_date,
                                payments.work_week_start) AS reference_date,
                       payments.amount_cents, payments.notes
                FROM payments
                JOIN income_sources ON income_sources.id = payments.income_source_id
                WHERE payments.id = ?
                """,
                (payment_id,),
            ).fetchone()
        return None if row is None else self._payment_record_from_row(row)

    def update_payment(self, payment_id: int, payment: PaymentToSave) -> None:
        with self.connect() as connection:
            self._validate_payment(connection, payment)
            week_start, _week_end = self._payment_week_bounds(
                connection, payment.work_week_reference_date
            )
            cursor = connection.execute(
                """
                UPDATE payments
                SET income_source_id = ?, work_week_start = ?,
                    work_week_reference_date = ?, paid_on = ?, amount_cents = ?,
                    notes = ?
                WHERE id = ?
                """,
                (
                    payment.income_source_id,
                    week_start.isoformat(),
                    payment.work_week_reference_date.isoformat(),
                    payment.paid_on.isoformat(),
                    payment.amount_cents,
                    payment.notes.strip(),
                    payment_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError("The selected payment no longer exists.")

    def delete_payment(self, payment_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM payments WHERE id = ?", (payment_id,)
            )
        return cursor.rowcount > 0

    def list_payments(self, limit: int = 30) -> list[PaymentRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT payments.id, payments.income_source_id,
                       income_sources.name AS source_name, payments.paid_on,
                       payments.work_week_start,
                       COALESCE(payments.work_week_reference_date,
                                payments.work_week_start) AS reference_date,
                       payments.amount_cents, payments.notes
                FROM payments
                JOIN income_sources ON income_sources.id = payments.income_source_id
                ORDER BY payments.paid_on DESC, payments.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._payment_record_from_row(row) for row in rows]

    def payment_summary(
        self, *, income_source_id: int, reference_date: date
    ) -> PaymentSummary:
        with self.connect() as connection:
            week_start, week_end = self._payment_week_bounds(
                connection, reference_date
            )
            earned = connection.execute(
                """
                SELECT COALESCE(SUM(gross_pay_cents), 0) AS total
                FROM shifts
                WHERE income_source_id = ?
                  AND work_date BETWEEN ? AND ?
                """,
                (
                    income_source_id,
                    week_start.isoformat(),
                    week_end.isoformat(),
                ),
            ).fetchone()["total"]
            received = connection.execute(
                """
                SELECT COALESCE(SUM(amount_cents), 0) AS total
                FROM payments
                WHERE income_source_id = ? AND work_week_start = ?
                """,
                (income_source_id, week_start.isoformat()),
            ).fetchone()["total"]
        gross = int(earned)
        payments = int(received)
        return PaymentSummary(
            income_source_id=income_source_id,
            week_start=week_start,
            week_end=week_end,
            gross_earned_cents=gross,
            payments_received_cents=payments,
            amount_owed_cents=max(gross - payments, 0),
            overpaid_cents=max(payments - gross, 0),
        )

    def has_duplicate_payment(
        self,
        payment: PaymentToSave,
        *,
        exclude_payment_id: int | None = None,
    ) -> bool:
        with self.connect() as connection:
            week_start, _week_end = self._payment_week_bounds(
                connection, payment.work_week_reference_date
            )
            row = connection.execute(
                """
                SELECT 1 FROM payments
                WHERE income_source_id = ?
                  AND work_week_start = ?
                  AND paid_on = ?
                  AND amount_cents = ?
                  AND id != COALESCE(?, -1)
                LIMIT 1
                """,
                (
                    payment.income_source_id,
                    week_start.isoformat(),
                    payment.paid_on.isoformat(),
                    payment.amount_cents,
                    exclude_payment_id,
                ),
            ).fetchone()
        return row is not None

    @staticmethod
    def _validate_payment(
        connection: sqlite3.Connection, payment: PaymentToSave
    ) -> None:
        if payment.amount_cents <= 0:
            raise ValueError("Payment amount must be greater than $0.00.")
        source = connection.execute(
            "SELECT 1 FROM income_sources WHERE id = ?",
            (payment.income_source_id,),
        ).fetchone()
        if source is None:
            raise ValueError("The selected income source no longer exists.")
        if len(payment.notes.strip()) > 500:
            raise ValueError("Payment notes must be 500 characters or fewer.")

    def _payment_week_bounds(
        self, connection: sqlite3.Connection, reference_date: date
    ) -> tuple[date, date]:
        start_weekday = self._get_setting_int(connection, "work_week_start", 3)
        return work_week_bounds(reference_date, start_weekday)

    @staticmethod
    def _payment_record_from_row(row: sqlite3.Row) -> PaymentRecord:
        return PaymentRecord(
            id=int(row["id"]),
            income_source_id=int(row["income_source_id"]),
            source_name=row["source_name"],
            paid_on=date.fromisoformat(row["paid_on"]),
            work_week_start=date.fromisoformat(row["work_week_start"]),
            work_week_reference_date=date.fromisoformat(row["reference_date"]),
            amount_cents=int(row["amount_cents"]),
            notes=row["notes"],
        )

    def overview_summary(
        self,
        *,
        reference_date: date,
        income_source_id: int | None = None,
    ) -> OverviewSummary:
        with self.connect() as connection:
            start_weekday = self._get_setting_int(
                connection, "work_week_start", 3
            )
            week_start, week_end = work_week_bounds(
                reference_date, start_weekday
            )
            source_rows = self._overview_source_rows(
                connection,
                week_start,
                week_end,
                income_source_id=income_source_id,
            )
            previous_start = week_start - timedelta(days=7)
            previous_end = week_end - timedelta(days=7)
            previous_rows = self._overview_source_rows(
                connection,
                previous_start,
                previous_end,
                income_source_id=income_source_id,
            )

        return OverviewSummary(
            week_start=week_start,
            week_end=week_end,
            source_rows=source_rows,
            paid_minutes=sum(row.paid_minutes for row in source_rows),
            regular_minutes=sum(row.regular_minutes for row in source_rows),
            overtime_minutes=sum(row.overtime_minutes for row in source_rows),
            gross_earned_cents=sum(
                row.gross_earned_cents for row in source_rows
            ),
            estimated_tax_cents=sum(
                row.estimated_tax_cents for row in source_rows
            ),
            estimated_take_home_cents=sum(
                row.estimated_take_home_cents for row in source_rows
            ),
            payments_received_cents=sum(
                row.payments_received_cents for row in source_rows
            ),
            amount_owed_cents=sum(
                row.amount_owed_cents for row in source_rows
            ),
            overpaid_cents=sum(row.overpaid_cents for row in source_rows),
            previous_paid_minutes=sum(
                row.paid_minutes for row in previous_rows
            ),
            previous_gross_earned_cents=sum(
                row.gross_earned_cents for row in previous_rows
            ),
            previous_amount_owed_cents=sum(
                row.amount_owed_cents for row in previous_rows
            ),
        )

    @staticmethod
    def _overview_source_rows(
        connection: sqlite3.Connection,
        week_start: date,
        week_end: date,
        *,
        income_source_id: int | None,
    ) -> tuple[OverviewSourceSummary, ...]:
        source_filter = ""
        shift_parameters: list[object] = [
            week_start.isoformat(),
            week_end.isoformat(),
        ]
        payment_parameters: list[object] = [week_start.isoformat()]
        if income_source_id is not None:
            source_filter = " AND income_source_id = ?"
            shift_parameters.append(income_source_id)
            payment_parameters.append(income_source_id)

        shift_rows = connection.execute(
            f"""
            SELECT income_source_id,
                   COALESCE(SUM(paid_minutes), 0) AS paid_minutes,
                   COALESCE(SUM(regular_minutes), 0) AS regular_minutes,
                   COALESCE(SUM(overtime_minutes), 0) AS overtime_minutes,
                   COALESCE(SUM(gross_pay_cents), 0) AS gross_earned_cents,
                   COALESCE(SUM(tax_cents), 0) AS estimated_tax_cents,
                   COALESCE(SUM(net_pay_cents), 0) AS estimated_take_home_cents
            FROM shifts
            WHERE work_date BETWEEN ? AND ?{source_filter}
            GROUP BY income_source_id
            """,
            shift_parameters,
        ).fetchall()
        payment_rows = connection.execute(
            f"""
            SELECT income_source_id,
                   COALESCE(SUM(amount_cents), 0) AS payments_received_cents
            FROM payments
            WHERE work_week_start = ?{source_filter}
            GROUP BY income_source_id
            """,
            payment_parameters,
        ).fetchall()

        shifts = {int(row["income_source_id"]): row for row in shift_rows}
        payments = {int(row["income_source_id"]): row for row in payment_rows}
        source_ids = set(shifts) | set(payments)
        if income_source_id is not None:
            exists = connection.execute(
                "SELECT 1 FROM income_sources WHERE id = ?",
                (income_source_id,),
            ).fetchone()
            if exists is not None:
                source_ids.add(income_source_id)
        if not source_ids:
            return ()

        placeholders = ",".join("?" for _item in source_ids)
        names = {
            int(row["id"]): row["name"]
            for row in connection.execute(
                f"SELECT id, name FROM income_sources WHERE id IN ({placeholders})",
                tuple(sorted(source_ids)),
            ).fetchall()
        }

        result: list[OverviewSourceSummary] = []
        for source_id in sorted(source_ids, key=lambda item: names.get(item, "").casefold()):
            shift = shifts.get(source_id)
            payment = payments.get(source_id)
            gross = int(shift["gross_earned_cents"]) if shift is not None else 0
            received = (
                int(payment["payments_received_cents"])
                if payment is not None
                else 0
            )
            result.append(
                OverviewSourceSummary(
                    income_source_id=source_id,
                    source_name=names.get(source_id, "Unknown source"),
                    paid_minutes=int(shift["paid_minutes"]) if shift is not None else 0,
                    regular_minutes=int(shift["regular_minutes"])
                    if shift is not None
                    else 0,
                    overtime_minutes=int(shift["overtime_minutes"])
                    if shift is not None
                    else 0,
                    gross_earned_cents=gross,
                    estimated_tax_cents=int(shift["estimated_tax_cents"])
                    if shift is not None
                    else 0,
                    estimated_take_home_cents=int(
                        shift["estimated_take_home_cents"]
                    )
                    if shift is not None
                    else 0,
                    payments_received_cents=received,
                    amount_owed_cents=max(gross - received, 0),
                    overpaid_cents=max(received - gross, 0),
                )
            )
        return tuple(result)

    def prior_paid_minutes(
        self,
        *,
        income_source_id: int,
        week_start: date,
        work_date: date,
        clock_in: str,
        exclude_shift_id: int | None = None,
    ) -> int:
        with self.connect() as connection:
            parameters: list[object] = [
                income_source_id,
                week_start.isoformat(),
                work_date.isoformat(),
                work_date.isoformat(),
                clock_in,
            ]
            same_time_clause = "clock_in <= ?"
            if exclude_shift_id is not None:
                same_time_clause = "(clock_in < ? OR (clock_in = ? AND id < ?))"
                parameters.extend([clock_in, exclude_shift_id])
            row = connection.execute(
                f"""
                SELECT COALESCE(SUM(paid_minutes), 0) AS total
                FROM shifts
                WHERE income_source_id = ?
                  AND work_date >= ?
                  AND (
                    work_date < ?
                    OR (work_date = ? AND {same_time_clause})
                  )
                  AND id != COALESCE(?, -1)
                """,
                (*parameters, exclude_shift_id),
            ).fetchone()
        return int(row["total"])

    def save_shift(self, shift: ShiftToSave) -> int:
        calc = shift.calculation
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO shifts(
                    income_source_id, work_date, clock_in, clock_out,
                    hourly_rate_cents, tax_rate_bps, overtime_after_minutes,
                    overtime_multiplier_milli, elapsed_minutes, break_minutes,
                    paid_minutes, regular_minutes, overtime_minutes,
                    regular_pay_cents, overtime_pay_cents, gross_pay_cents,
                    tax_cents, net_pay_cents, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    shift.income_source_id,
                    shift.work_date.isoformat(),
                    shift.clock_in,
                    shift.clock_out,
                    shift.hourly_rate_cents,
                    shift.tax_rate_bps,
                    shift.overtime_after_minutes,
                    shift.overtime_multiplier_milli,
                    calc.elapsed_minutes,
                    calc.break_minutes,
                    calc.paid_minutes,
                    calc.regular_minutes,
                    calc.overtime_minutes,
                    calc.regular_pay_cents,
                    calc.overtime_pay_cents,
                    calc.gross_pay_cents,
                    calc.tax_cents,
                    calc.net_pay_cents,
                    shift.notes.strip(),
                    _now(),
                ),
            )
            shift_id = int(cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO shift_breaks(shift_id, duration_minutes, paid, sort_order)
                VALUES (?, ?, 0, ?)
                """,
                [
                    (shift_id, duration, index)
                    for index, duration in enumerate(shift.break_durations)
                ],
            )
            self._recalculate_affected_week(
                connection, shift.income_source_id, shift.work_date
            )
        return shift_id

    def get_shift(self, shift_id: int) -> ShiftRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, income_source_id, work_date, clock_in, clock_out,
                       hourly_rate_cents, tax_rate_bps, overtime_after_minutes,
                       overtime_multiplier_milli, notes
                FROM shifts
                WHERE id = ?
                """,
                (shift_id,),
            ).fetchone()
            if row is None:
                return None
            breaks = connection.execute(
                """
                SELECT duration_minutes
                FROM shift_breaks
                WHERE shift_id = ? AND paid = 0
                ORDER BY sort_order, id
                """,
                (shift_id,),
            ).fetchall()
        return ShiftRecord(
            id=int(row["id"]),
            income_source_id=int(row["income_source_id"]),
            work_date=date.fromisoformat(row["work_date"]),
            clock_in=row["clock_in"],
            clock_out=row["clock_out"],
            break_durations=tuple(int(item["duration_minutes"]) for item in breaks),
            hourly_rate_cents=int(row["hourly_rate_cents"]),
            tax_rate_bps=int(row["tax_rate_bps"]),
            overtime_after_minutes=int(row["overtime_after_minutes"]),
            overtime_multiplier_milli=int(row["overtime_multiplier_milli"]),
            notes=row["notes"],
        )

    def update_shift(self, shift_id: int, shift: ShiftToSave) -> None:
        calc = shift.calculation
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT income_source_id, work_date FROM shifts WHERE id = ?",
                (shift_id,),
            ).fetchone()
            if existing is None:
                raise ValueError("The selected shift no longer exists.")

            old_source_id = int(existing["income_source_id"])
            old_work_date = date.fromisoformat(existing["work_date"])
            connection.execute(
                """
                UPDATE shifts
                SET income_source_id = ?, work_date = ?, clock_in = ?, clock_out = ?,
                    hourly_rate_cents = ?, tax_rate_bps = ?,
                    overtime_after_minutes = ?, overtime_multiplier_milli = ?,
                    elapsed_minutes = ?, break_minutes = ?, paid_minutes = ?,
                    regular_minutes = ?, overtime_minutes = ?, regular_pay_cents = ?,
                    overtime_pay_cents = ?, gross_pay_cents = ?, tax_cents = ?,
                    net_pay_cents = ?, notes = ?
                WHERE id = ?
                """,
                (
                    shift.income_source_id,
                    shift.work_date.isoformat(),
                    shift.clock_in,
                    shift.clock_out,
                    shift.hourly_rate_cents,
                    shift.tax_rate_bps,
                    shift.overtime_after_minutes,
                    shift.overtime_multiplier_milli,
                    calc.elapsed_minutes,
                    calc.break_minutes,
                    calc.paid_minutes,
                    calc.regular_minutes,
                    calc.overtime_minutes,
                    calc.regular_pay_cents,
                    calc.overtime_pay_cents,
                    calc.gross_pay_cents,
                    calc.tax_cents,
                    calc.net_pay_cents,
                    shift.notes.strip(),
                    shift_id,
                ),
            )
            connection.execute("DELETE FROM shift_breaks WHERE shift_id = ?", (shift_id,))
            connection.executemany(
                """
                INSERT INTO shift_breaks(shift_id, duration_minutes, paid, sort_order)
                VALUES (?, ?, 0, ?)
                """,
                [
                    (shift_id, duration, index)
                    for index, duration in enumerate(shift.break_durations)
                ],
            )

            affected = {
                (old_source_id, old_work_date),
                (shift.income_source_id, shift.work_date),
            }
            for income_source_id, work_date_value in affected:
                self._recalculate_affected_week(
                    connection, income_source_id, work_date_value
                )

    def delete_shift(self, shift_id: int) -> bool:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT income_source_id, work_date FROM shifts WHERE id = ?",
                (shift_id,),
            ).fetchone()
            if existing is None:
                return False
            connection.execute("DELETE FROM shifts WHERE id = ?", (shift_id,))
            self._recalculate_affected_week(
                connection,
                int(existing["income_source_id"]),
                date.fromisoformat(existing["work_date"]),
            )
        return True

    def has_duplicate_shift(
        self,
        *,
        income_source_id: int,
        work_date: date,
        clock_in: str,
        clock_out: str,
        exclude_shift_id: int | None = None,
    ) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM shifts
                WHERE income_source_id = ?
                  AND work_date = ?
                  AND clock_in = ?
                  AND clock_out = ?
                  AND id != COALESCE(?, -1)
                LIMIT 1
                """,
                (
                    income_source_id,
                    work_date.isoformat(),
                    clock_in,
                    clock_out,
                    exclude_shift_id,
                ),
            ).fetchone()
        return row is not None

    def _recalculate_affected_week(
        self,
        connection: sqlite3.Connection,
        income_source_id: int,
        reference_date: date,
    ) -> None:
        start_weekday = self._get_setting_int(connection, "work_week_start", 3)
        week_start, week_end = work_week_bounds(reference_date, start_weekday)
        rows = connection.execute(
            """
            SELECT id, clock_in, clock_out, hourly_rate_cents, tax_rate_bps,
                   overtime_after_minutes, overtime_multiplier_milli
            FROM shifts
            WHERE income_source_id = ?
              AND work_date BETWEEN ? AND ?
            ORDER BY work_date, clock_in, id
            """,
            (income_source_id, week_start.isoformat(), week_end.isoformat()),
        ).fetchall()

        prior_minutes = 0
        for row in rows:
            breaks = connection.execute(
                """
                SELECT duration_minutes
                FROM shift_breaks
                WHERE shift_id = ? AND paid = 0
                ORDER BY sort_order, id
                """,
                (row["id"],),
            ).fetchall()
            calculation = calculate_shift(
                clock_in=row["clock_in"],
                clock_out=row["clock_out"],
                break_durations=(int(item["duration_minutes"]) for item in breaks),
                hourly_rate_cents=int(row["hourly_rate_cents"]),
                tax_rate_bps=int(row["tax_rate_bps"]),
                prior_week_minutes=prior_minutes,
                overtime_after_minutes=int(row["overtime_after_minutes"]),
                overtime_multiplier_milli=int(row["overtime_multiplier_milli"]),
            )
            connection.execute(
                """
                UPDATE shifts
                SET elapsed_minutes = ?, break_minutes = ?, paid_minutes = ?,
                    regular_minutes = ?, overtime_minutes = ?, regular_pay_cents = ?,
                    overtime_pay_cents = ?, gross_pay_cents = ?, tax_cents = ?,
                    net_pay_cents = ?
                WHERE id = ?
                """,
                (
                    calculation.elapsed_minutes,
                    calculation.break_minutes,
                    calculation.paid_minutes,
                    calculation.regular_minutes,
                    calculation.overtime_minutes,
                    calculation.regular_pay_cents,
                    calculation.overtime_pay_cents,
                    calculation.gross_pay_cents,
                    calculation.tax_cents,
                    calculation.net_pay_cents,
                    row["id"],
                ),
            )
            prior_minutes += calculation.paid_minutes

    def _recalculate_all_shifts(self, connection: sqlite3.Connection) -> None:
        start_weekday = self._get_setting_int(connection, "work_week_start", 3)
        rows = connection.execute(
            "SELECT DISTINCT income_source_id, work_date FROM shifts"
        ).fetchall()
        affected_weeks: set[tuple[int, date]] = set()
        for row in rows:
            work_date_value = date.fromisoformat(row["work_date"])
            week_start, _week_end = work_week_bounds(
                work_date_value, start_weekday
            )
            affected_weeks.add((int(row["income_source_id"]), week_start))
        for income_source_id, week_start in affected_weeks:
            self._recalculate_affected_week(
                connection, income_source_id, week_start
            )

    @staticmethod
    def _ensure_payment_schema(connection: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(payments)")
        }
        if "work_week_reference_date" not in columns:
            connection.execute(
                "ALTER TABLE payments ADD COLUMN work_week_reference_date TEXT"
            )
        connection.execute(
            """
            UPDATE payments
            SET work_week_reference_date = work_week_start
            WHERE work_week_reference_date IS NULL
              AND work_week_start IS NOT NULL
            """
        )

    @staticmethod
    def _realign_payments(
        connection: sqlite3.Connection, start_weekday: int
    ) -> None:
        rows = connection.execute(
            """
            SELECT id, COALESCE(work_week_reference_date, work_week_start) AS reference_date
            FROM payments
            WHERE COALESCE(work_week_reference_date, work_week_start) IS NOT NULL
            """
        ).fetchall()
        for row in rows:
            reference_date = date.fromisoformat(row["reference_date"])
            week_start, _week_end = work_week_bounds(
                reference_date, start_weekday
            )
            connection.execute(
                "UPDATE payments SET work_week_start = ? WHERE id = ?",
                (week_start.isoformat(), row["id"]),
            )

    @staticmethod
    def _get_setting_int(
        connection: sqlite3.Connection, key: str, default: int
    ) -> int:
        row = connection.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        try:
            return int(row["value"])
        except ValueError:
            return default

    def list_recent_shifts(self, limit: int = 12) -> Sequence[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT shifts.id, shifts.work_date, income_sources.name AS source_name,
                       shifts.clock_in, shifts.clock_out, shifts.paid_minutes,
                       shifts.gross_pay_cents, shifts.net_pay_cents
                FROM shifts
                JOIN income_sources ON income_sources.id = shifts.income_source_id
                ORDER BY shifts.work_date DESC, shifts.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
