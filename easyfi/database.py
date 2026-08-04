"""SQLite persistence for EasyFi."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterator, Sequence

from .calculations import ShiftCalculation
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
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return default
        try:
            return int(row["value"])
        except ValueError:
            return default

    def list_income_sources(self) -> list[IncomeSource]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, hourly_rate_cents, tax_rate_bps,
                       overtime_after_minutes, overtime_multiplier_milli
                FROM income_sources
                WHERE active = 1
                ORDER BY name COLLATE NOCASE
                """
            ).fetchall()
        return [IncomeSource(**dict(row)) for row in rows]

    def prior_paid_minutes(
        self,
        *,
        income_source_id: int,
        week_start: date,
        through_date: date,
    ) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(paid_minutes), 0) AS total
                FROM shifts
                WHERE income_source_id = ?
                  AND work_date >= ?
                  AND work_date <= ?
                """,
                (income_source_id, week_start.isoformat(), through_date.isoformat()),
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
        return shift_id

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
