"""Pure timesheet and pay calculations.

All monetary inputs and outputs use integer cents. Rates such as tax and
overtime multipliers use integer scaled values so historical calculations are
repeatable and do not depend on binary floating-point arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


MINUTES_PER_DAY = 24 * 60
MINUTES_PER_HOUR = 60


@dataclass(frozen=True, slots=True)
class ShiftCalculation:
    elapsed_minutes: int
    break_minutes: int
    paid_minutes: int
    regular_minutes: int
    overtime_minutes: int
    regular_pay_cents: int
    overtime_pay_cents: int
    gross_pay_cents: int
    tax_cents: int
    net_pay_cents: int


def parse_clock_time(value: str) -> int:
    """Convert a 24-hour HH:MM value to minutes after midnight."""

    try:
        hours_text, minutes_text = value.strip().split(":", maxsplit=1)
        hours = int(hours_text)
        minutes = int(minutes_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Time must use HH:MM format.") from exc
    if not 0 <= hours <= 23 or not 0 <= minutes <= 59:
        raise ValueError("Time must be a valid 24-hour clock value.")
    return hours * MINUTES_PER_HOUR + minutes


def elapsed_minutes(clock_in: str, clock_out: str) -> int:
    """Calculate elapsed shift time, supporting a shift that crosses midnight."""

    start = parse_clock_time(clock_in)
    end = parse_clock_time(clock_out)
    if end < start:
        end += MINUTES_PER_DAY
    return end - start


def work_week_bounds(work_date: date, start_weekday: int) -> tuple[date, date]:
    """Return inclusive work-week bounds.

    start_weekday follows date.weekday(): Monday is 0 and Sunday is 6.
    """

    if not 0 <= start_weekday <= 6:
        raise ValueError("Work-week start must be between 0 and 6.")
    days_since_start = (work_date.weekday() - start_weekday) % 7
    start = work_date - timedelta(days=days_since_start)
    return start, start + timedelta(days=6)


def calculate_shift(
    *,
    clock_in: str,
    clock_out: str,
    break_durations: Iterable[int],
    hourly_rate_cents: int,
    tax_rate_bps: int,
    prior_week_minutes: int = 0,
    overtime_after_minutes: int = 40 * MINUTES_PER_HOUR,
    overtime_multiplier_milli: int = 1500,
) -> ShiftCalculation:
    """Calculate paid time, overtime, and estimated take-home pay.

    tax_rate_bps is basis points (18% == 1800). The overtime multiplier is
    thousandths (1.5x == 1500).
    """

    if hourly_rate_cents < 0:
        raise ValueError("Hourly rate cannot be negative.")
    if not 0 <= tax_rate_bps <= 10_000:
        raise ValueError("Tax rate must be between 0% and 100%.")
    if prior_week_minutes < 0 or overtime_after_minutes < 0:
        raise ValueError("Weekly minutes cannot be negative.")
    if overtime_multiplier_milli < 1000:
        raise ValueError("Overtime multiplier must be at least 1.0x.")

    durations = tuple(int(duration) for duration in break_durations)
    if any(duration < 0 for duration in durations):
        raise ValueError("Break durations cannot be negative.")

    shift_elapsed = elapsed_minutes(clock_in, clock_out)
    total_breaks = sum(durations)
    if shift_elapsed <= 0:
        raise ValueError("Clock-out must result in a shift longer than zero minutes.")
    if total_breaks >= shift_elapsed:
        raise ValueError("Break time must be shorter than the shift.")

    paid = shift_elapsed - total_breaks
    regular_capacity = max(0, overtime_after_minutes - prior_week_minutes)
    regular = min(paid, regular_capacity)
    overtime = paid - regular

    cents_per_minute = Decimal(hourly_rate_cents) / Decimal(MINUTES_PER_HOUR)
    regular_pay = _round_cents(cents_per_minute * Decimal(regular))
    overtime_pay = _round_cents(
        cents_per_minute
        * Decimal(overtime)
        * Decimal(overtime_multiplier_milli)
        / Decimal(1000)
    )
    gross = regular_pay + overtime_pay
    tax = _round_cents(Decimal(gross) * Decimal(tax_rate_bps) / Decimal(10_000))

    return ShiftCalculation(
        elapsed_minutes=shift_elapsed,
        break_minutes=total_breaks,
        paid_minutes=paid,
        regular_minutes=regular,
        overtime_minutes=overtime,
        regular_pay_cents=regular_pay,
        overtime_pay_cents=overtime_pay,
        gross_pay_cents=gross,
        tax_cents=tax,
        net_pay_cents=gross - tax,
    )


def _round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_minutes(total_minutes: int) -> str:
    hours, minutes = divmod(max(0, total_minutes), MINUTES_PER_HOUR)
    return f"{hours}h {minutes:02d}m"


def format_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    absolute = abs(cents)
    dollars, remainder = divmod(absolute, 100)
    return f"{sign}${dollars:,}.{remainder:02d}"

