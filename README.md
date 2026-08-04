# EasyFi

EasyFi is a private, local-first desktop timesheet and income tracker. The
current scaffold implements the first complete workflow: record a shift,
calculate its pay, save it to SQLite, and view it after restarting the app.

## Current features

- Clock-in and clock-out entry, including overnight shifts
- Multiple unpaid breaks per shift
- Configurable work-week start (Thursday by default)
- Hourly-rate and estimated-tax snapshots on every shift
- Weekly overtime threshold and multiplier
- Live gross, tax, and estimated take-home calculation
- Local SQLite persistence and a recent-shifts table
- Edit or delete saved shifts with automatic weekly overtime recalculation
- Duplicate-shift warning before saving matching entries
- Normalized clock times and guarded date, rate, tax, and break inputs
- Settings screen for work-week, clock-time, and default-break preferences
- Add, edit, archive, and restore income sources
- Per-source hourly rate, tax estimate, overtime threshold, and multiplier
- Payment records assigned to an income source and work week
- Live gross-earned, employer-paid, amount-owed, and overpaid balances
- Partial and multiple payments with edit, delete, and duplicate protection
- Weekly Overview dashboard with source filters and previous-week comparisons
- Per-employer hours, overtime, gross wages, payments, owed, and overpaid breakdown
- No network requests, accounts, or cloud services

Tax values are user-configured estimates and are not tax-filing advice.

The Payments screen defines employer balance as:

```text
amount owed = gross earned wages - employer payments received
```

Estimated taxes and take-home pay will be shown separately and will not reduce
the employer's gross amount owed.

## Run locally

EasyFi uses only the Python standard library at this stage. From PowerShell:

```powershell
cd C:\Users\iskan\Documents\repos\EasyFi
.\.venv\Scripts\Activate.ps1
python -m easyfi --check
python -m easyfi
```

The database is created at `%LOCALAPPDATA%\EasyFi\easyfi.db`. You can select a
different location for a run with:

```powershell
python -m easyfi --data-dir C:\path\to\portable-data
```

## Run tests

```powershell
python -m unittest discover -s tests -v
```

## Data model

- `settings`: work-week, clock-time, break, and currency preferences
- `income_sources`: active or archived default rates, tax estimates, and overtime rules
- `shifts`: the original time entry plus immutable calculation snapshots
- `shift_breaks`: each break associated with a shift
- `payments`: employer deposits assigned to an income source and work week

Money is stored as integer cents. Tax rates use basis points, and overtime
multipliers use thousandths, avoiding binary floating-point errors.
