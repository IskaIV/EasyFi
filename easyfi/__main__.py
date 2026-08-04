"""Command-line entry point for EasyFi."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from .database import Database
from .display import configure_windows_dpi_awareness


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EasyFi local financial tracker")
    parser.add_argument(
        "--check",
        action="store_true",
        help="initialize the database and exit without opening a window",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="override the local data directory for this run",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.data_dir:
        os.environ["EASYFI_DATA_DIR"] = str(args.data_dir)

    # This must happen before importing the UI or constructing any Tk windows.
    configure_windows_dpi_awareness()

    database = Database()
    database.initialize()
    if args.check:
        print(f"EasyFi is ready. Database: {database.path}")
        return

    try:
        database.create_automatic_backup_if_due()
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"EasyFi automatic backup warning: {exc}", file=sys.stderr)

    from .ui.timesheet import launch

    launch(database)


if __name__ == "__main__":
    main()
