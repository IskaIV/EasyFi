"""SQLite persistence for EasyFi."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterator, Sequence

from .calculations import ShiftCalculation, calculate_shift, work_week_bounds
from .paths import database_path


SCHEMA_VERSION = 1


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
                    paid_on TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_shifts_source_date
                    ON shifts(income_source_id, work_date);
                """
            )
            defaults = {
                "work_week_start": "3",
                "currency": "USD",
                "default_clock_in": "08:30",
                "default_clock_out": "17:00",
                "default_break_minutes": "30",
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
