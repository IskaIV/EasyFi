"""Filesystem paths used by EasyFi."""

from __future__ import annotations

import os
from pathlib import Path


def user_data_dir() -> Path:
    """Return EasyFi's writable local data directory.

    EASYFI_DATA_DIR is intentionally supported for tests, portable installs,
    and users who want to choose their own storage location.
    """

    override = os.environ.get("EASYFI_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "EasyFi"
    return Path.home() / ".easyfi"


def database_path() -> Path:
    return user_data_dir() / "easyfi.db"

