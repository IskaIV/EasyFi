"""Command-line entry point for EasyFi."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .database import Database


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

    database = Database()
    database.initialize()
    if args.check:
        print(f"EasyFi is ready. Database: {database.path}")
        return

    from .ui.timesheet import launch

    launch(database)


if __name__ == "__main__":
    main()

