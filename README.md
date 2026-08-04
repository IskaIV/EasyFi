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
- No network requests, accounts, or cloud services

Tax values are user-configured estimates and are not tax-filing advice.

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

- `settings`: work-week and currency preferences
- `income_sources`: default rates, tax estimates, and overtime rules
- `shifts`: the original time entry plus immutable calculation snapshots
- `shift_breaks`: each break associated with a shift
- `payments`: reserved for the next amount-paid/amount-owed milestone

Money is stored as integer cents. Tax rates use basis points, and overtime
multipliers use thousandths, avoiding binary floating-point errors.
