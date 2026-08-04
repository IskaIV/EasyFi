# EasyFi

> A private, local-first desktop app for tracking work hours, estimated pay,
> employer payments, and outstanding wages.

`Windows` · `Python 3.12+` · `Tkinter` · `SQLite` · `No cloud required`

EasyFi turns everyday time entries into a clear record of what you earned,
what you were paid, and what you are still owed. Everything runs locally on
your computer—there are no accounts, subscriptions, advertisements, or network
requests.

## At a glance

| Area | What EasyFi handles |
| --- | --- |
| **Timesheets** | Clock-in/out times, AM/PM selectors, multiple unpaid breaks, overnight shifts, and automatic paid-time calculations |
| **Earnings** | Hourly rates, customizable tax estimates, weekly overtime thresholds, multipliers, gross pay, and estimated take-home pay |
| **Payments** | Partial or multiple employer payments assigned to the correct income source and work week |
| **Balances** | Gross wages earned, total payments received, amount still owed, and any overpayment |
| **Overview** | Weekly totals, previous-week comparisons, source filters, and per-employer breakdowns |
| **Data safety** | Local SQLite storage, verified backups, guarded restore, automatic backup rotation, integrity checks, and CSV exports |

## Why EasyFi?

- **Know what your time is worth.** Enter a shift once and see paid time,
  regular pay, overtime, estimated tax, and take-home pay immediately.
- **Match the way you actually work.** Start the work week on any day, manage
  multiple income sources, and customize rates and overtime rules per source.
- **Track what an employer still owes.** Record deposits separately from earned
  wages instead of treating a paycheck as proof that the balance is settled.
- **Keep control of your records.** Your financial data stays in a local SQLite
  database that you can back up, restore, inspect, or export.

## Amount owed, clearly defined

EasyFi compares employer payments against **gross earned wages**:

```text
amount owed = gross earned wages - employer payments received
```

For example, if you earned `$1,000` and received `$500`, EasyFi reports `$500`
still owed. Estimated taxes and take-home pay are displayed separately and do
not reduce the employer's gross obligation.

Outstanding balances carry forward across work weeks. Payments recorded in the
selected week reduce the full running balance for that income source, not only
the wages earned during that week.

> **Tax notice:** Tax percentages in EasyFi are user-configured estimates for
> planning purposes. They are not tax-filing or financial advice.

## Quick start

### Use the packaged Windows app

Open `dist\EasyFi.exe`. The application is self-contained and does not require
Python to be installed. You can copy the executable to another folder without
moving your financial data.

Windows may display an **Unknown publisher** notice because personal builds are
not digitally signed. The executable is produced locally from the source in
this repository.

### Run from source

EasyFi currently uses only Python's standard library at runtime.

```powershell
cd C:\path\to\EasyFi
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m easyfi --check
python -m easyfi
```

The interface enables Windows Per-Monitor V2 DPI awareness before creating its
first window, keeping text and controls crisp at common display scaling levels.

## Releases

- [v1.0.0-alpha](docs/releases/v1.0.0-alpha.md) — first complete alpha preview

## Where your data lives

EasyFi stores personal data outside the source tree and outside the packaged
executable:

```text
%LOCALAPPDATA%\EasyFi\easyfi.db
```

Automatic backups are enabled by default and stored in:

```text
%LOCALAPPDATA%\EasyFi\backups
```

EasyFi creates at most one automatic backup per day and keeps the newest 10
copies by default. Both settings are customizable under **Settings → Data
safety**.

To use a different data directory for a source run:

```powershell
python -m easyfi --data-dir C:\path\to\portable-data
```

## Data protection

- Manual backups are verified after creation.
- Restore files are validated before replacing the active database.
- A separate `easyfi-pre-restore-*.db` recovery copy is created before every
  restore.
- SQLite integrity checks can be run from the Settings screen.
- CSV exports include settings, income sources, shifts, breaks, and payments.
- Saved shifts retain calculation snapshots, so later rate changes do not
  silently rewrite historical earnings.

## Build the Windows executable

Install the free build dependency once:

```powershell
python -m pip install ".[build]"
```

Then run the reproducible packaging script:

```powershell
.\packaging\build.ps1
```

The build produces a single windowed executable at `dist\EasyFi.exe`. It embeds
version metadata and `packaging/easyfi.manifest` for native Windows DPI
behavior. Personal databases and backups are never included in the executable.

## Run the test suite

```powershell
python -m unittest discover -s tests -v
```

The suite covers time calculations, overnight shifts, overtime boundaries,
payment reconciliation, database migrations, backup and restore safeguards,
CSV export, date/time input normalization, and display configuration.

## Project layout

```text
easyfi/
├── calculations.py    Pure time and pay calculations
├── database.py        SQLite persistence, summaries, and data protection
├── display.py         Windows DPI configuration
├── paths.py           Local application-data paths
└── ui/                Overview, timesheet, payments, settings, and widgets

packaging/             PyInstaller spec, manifest, metadata, and build script
tests/                 Calculation, database, display, and input-format tests
```

## Technical notes

- Money is stored as integer cents—never binary floating-point values.
- Tax rates use basis points and overtime multipliers use thousandths.
- Dates are stored in ISO format and times in normalized 24-hour format, while
  the interface presents friendly calendar and AM/PM controls.
- SQLite foreign keys, transactions, and guarded migrations protect relational
  consistency.
- The application has no runtime dependency outside Python's standard library.
