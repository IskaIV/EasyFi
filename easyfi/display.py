"""Platform-specific display setup performed before Tk creates a window."""

from __future__ import annotations

import sys


def configure_windows_dpi_awareness() -> str:
    """Request crisp, per-monitor rendering on Windows.

    The newest API is attempted first, with fallbacks for older Windows
    releases. This function must run before Tkinter creates the root window.
    The return value is intended for diagnostics and tests; startup should
    continue even when an API is unavailable.
    """

    if sys.platform != "win32":
        return "not-windows"

    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
    except (AttributeError, OSError):
        return "unavailable"

    try:
        set_awareness_context = user32.SetProcessDpiAwarenessContext
        set_awareness_context.argtypes = [ctypes.c_void_p]
        set_awareness_context.restype = ctypes.c_bool
        per_monitor_v2 = ctypes.c_void_p(-4)
        if set_awareness_context(per_monitor_v2):
            return "per-monitor-v2"
        if ctypes.get_last_error() == 5:
            return "already-configured"
    except (AttributeError, OSError):
        pass

    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        set_process_awareness = shcore.SetProcessDpiAwareness
        set_process_awareness.argtypes = [ctypes.c_int]
        set_process_awareness.restype = ctypes.c_long
        if set_process_awareness(2) == 0:
            return "per-monitor"
    except (AttributeError, OSError):
        pass

    try:
        set_dpi_aware = user32.SetProcessDPIAware
        set_dpi_aware.argtypes = []
        set_dpi_aware.restype = ctypes.c_bool
        if set_dpi_aware():
            return "system-aware"
    except (AttributeError, OSError):
        pass

    return "unavailable"

