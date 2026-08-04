"""Reusable, standard-library date and time controls for EasyFi."""

from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date, datetime
from tkinter import ttk

from ..calculations import format_clock_time_12h, normalize_clock_time
from .theme import (
    BORDER,
    FIELD_BACKGROUND,
    MUTED,
    PANEL_BACKGROUND,
    PRIMARY,
    PRIMARY_TEXT,
    TEXT,
    WINDOW_BACKGROUND,
)


DISPLAY_DATE_FORMAT = "%m/%d/%Y"


def parse_display_date(value: str) -> date:
    """Accept the friendly UI date as well as legacy ISO input."""

    cleaned = value.strip()
    for date_format in (DISPLAY_DATE_FORMAT, "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, date_format).date()
        except ValueError:
            continue
    raise ValueError("Date must use MM/DD/YYYY format.")


def format_display_date(value: date) -> str:
    return value.strftime(DISPLAY_DATE_FORMAT)


class DateInput(ttk.Frame):
    """An editable date field with a button that opens a calendar."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        textvariable: tk.StringVar,
        width: int | None = None,
    ) -> None:
        super().__init__(parent, style="InputShell.TFrame")
        self.variable = textvariable
        self.columnconfigure(0, weight=1)
        self.entry = ttk.Entry(
            self,
            textvariable=textvariable,
            style="Picker.TEntry",
            width=width,
        )
        self.entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(
            self,
            text="▦",
            width=3,
            style="PickerIcon.TButton",
            command=self.open_picker,
        ).grid(row=0, column=1, sticky="ns")

    def open_picker(self) -> None:
        try:
            selected = parse_display_date(self.variable.get())
        except ValueError:
            selected = date.today()
        CalendarDialog(self.winfo_toplevel(), selected, self._set_date)

    def _set_date(self, selected: date) -> None:
        self.variable.set(format_display_date(selected))
        self.entry.focus_set()
        self.entry.icursor("end")


class TimeInput(ttk.Frame):
    """An editable 12-hour time field with a clock picker button."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        textvariable: tk.StringVar,
        width: int | None = None,
    ) -> None:
        super().__init__(parent, style="InputShell.TFrame")
        self.variable = textvariable
        self.columnconfigure(0, weight=1)
        self.entry = ttk.Entry(
            self,
            textvariable=textvariable,
            style="Picker.TEntry",
            width=width,
        )
        self.entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(
            self,
            text="◷",
            width=3,
            style="PickerIcon.TButton",
            command=self.open_picker,
        ).grid(row=0, column=1, sticky="ns")

    def open_picker(self) -> None:
        TimePickerDialog(self.winfo_toplevel(), self.variable.get(), self._set_time)

    def _set_time(self, selected: str) -> None:
        self.variable.set(selected)
        self.entry.focus_set()
        self.entry.icursor("end")


class CalendarDialog(tk.Toplevel):
    """Compact month calendar without any third-party dependency."""

    def __init__(
        self,
        parent: tk.Misc,
        selected: date,
        on_select,
    ) -> None:
        super().__init__(parent)
        self.selected = selected
        self.visible_year = selected.year
        self.visible_month = selected.month
        self.on_select = on_select
        self.title("Choose a date")
        self.resizable(False, False)
        self.configure(background=WINDOW_BACKGROUND)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.body = tk.Frame(self, background=PANEL_BACKGROUND, padx=14, pady=14)
        self.body.pack(fill="both", expand=True, padx=1, pady=1)
        self._draw()
        self.update_idletasks()
        self._center_over_parent(parent)
        self.grab_set()
        self.focus_set()

    def _draw(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()

        header = tk.Frame(self.body, background=PANEL_BACKGROUND)
        header.grid(row=0, column=0, columnspan=7, sticky="ew", pady=(0, 10))
        tk.Button(
            header,
            text="‹",
            command=lambda: self._move_month(-1),
            **self._button_options(),
        ).pack(side="left")
        tk.Label(
            header,
            text=date(self.visible_year, self.visible_month, 1).strftime("%B %Y"),
            background=PANEL_BACKGROUND,
            foreground=TEXT,
            font=("Segoe UI", 11, "bold"),
            width=18,
        ).pack(side="left", padx=6)
        tk.Button(
            header,
            text="›",
            command=lambda: self._move_month(1),
            **self._button_options(),
        ).pack(side="left")

        for column, weekday in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
            tk.Label(
                self.body,
                text=weekday,
                background=PANEL_BACKGROUND,
                foreground=MUTED,
                font=("Segoe UI", 9, "bold"),
                width=4,
            ).grid(row=1, column=column, pady=(0, 4))

        month = calendar.Calendar(firstweekday=calendar.MONDAY).monthdayscalendar(
            self.visible_year, self.visible_month
        )
        for row_index, week in enumerate(month, start=2):
            for column, day_number in enumerate(week):
                if day_number == 0:
                    tk.Label(
                        self.body,
                        text="",
                        background=PANEL_BACKGROUND,
                        width=4,
                    ).grid(row=row_index, column=column, padx=1, pady=1)
                    continue
                candidate = date(self.visible_year, self.visible_month, day_number)
                is_selected = candidate == self.selected
                button = tk.Button(
                    self.body,
                    text=str(day_number),
                    width=3,
                    command=lambda value=candidate: self._choose(value),
                    **self._button_options(selected=is_selected),
                )
                button.grid(row=row_index, column=column, padx=1, pady=1)

        footer_row = 2 + len(month)
        tk.Button(
            self.body,
            text="Today",
            command=lambda: self._choose(date.today()),
            **self._button_options(),
        ).grid(row=footer_row, column=0, columnspan=3, sticky="w", pady=(10, 0))
        tk.Button(
            self.body,
            text="Cancel",
            command=self.destroy,
            **self._button_options(),
        ).grid(row=footer_row, column=4, columnspan=3, sticky="e", pady=(10, 0))

    @staticmethod
    def _button_options(*, selected: bool = False) -> dict[str, object]:
        return {
            "background": PRIMARY if selected else PANEL_BACKGROUND,
            "foreground": PRIMARY_TEXT if selected else TEXT,
            "activebackground": PRIMARY,
            "activeforeground": PRIMARY_TEXT,
            "relief": "flat",
            "borderwidth": 0,
            "font": ("Segoe UI", 10),
            "cursor": "hand2",
            "padx": 6,
            "pady": 4,
        }

    def _move_month(self, amount: int) -> None:
        month_index = self.visible_year * 12 + self.visible_month - 1 + amount
        self.visible_year, zero_based_month = divmod(month_index, 12)
        self.visible_month = zero_based_month + 1
        self._draw()

    def _choose(self, selected: date) -> None:
        self.on_select(selected)
        self.destroy()

    def _center_over_parent(self, parent: tk.Misc) -> None:
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_width()) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self.winfo_height()) // 2)
        self.geometry(f"+{x}+{y}")


class TimePickerDialog(tk.Toplevel):
    """Simple hour/minute/AM-PM picker."""

    def __init__(self, parent: tk.Misc, current: str, on_select) -> None:
        super().__init__(parent)
        try:
            normalized = normalize_clock_time(current)
        except ValueError:
            normalized = "08:00"
        display = format_clock_time_12h(normalized)
        time_text, meridiem = display.rsplit(" ", 1)
        hour, minute = time_text.split(":", 1)
        self.hour_var = tk.StringVar(value=str(int(hour)))
        self.minute_var = tk.StringVar(value=minute)
        self.meridiem_var = tk.StringVar(value=meridiem)
        self.on_select = on_select

        self.title("Choose a time")
        self.resizable(False, False)
        self.configure(background=WINDOW_BACKGROUND)
        self.transient(parent)
        body = tk.Frame(self, background=PANEL_BACKGROUND, padx=20, pady=18)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(
            body,
            text="Select a time",
            background=PANEL_BACKGROUND,
            foreground=TEXT,
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 12))

        hour_box = ttk.Spinbox(
            body, from_=1, to=12, textvariable=self.hour_var, width=4, wrap=True
        )
        hour_box.grid(row=1, column=0)
        tk.Label(
            body,
            text=":",
            background=PANEL_BACKGROUND,
            foreground=TEXT,
            font=("Segoe UI", 14, "bold"),
        ).grid(row=1, column=1, padx=4)
        minute_box = ttk.Spinbox(
            body, from_=0, to=59, textvariable=self.minute_var, width=4, wrap=True
        )
        minute_box.grid(row=1, column=2)
        ttk.Combobox(
            body,
            textvariable=self.meridiem_var,
            values=("AM", "PM"),
            state="readonly",
            width=5,
        ).grid(row=1, column=3, padx=(8, 0))

        buttons = tk.Frame(body, background=PANEL_BACKGROUND)
        buttons.grid(row=2, column=0, columnspan=5, sticky="e", pady=(16, 0))
        ttk.Button(
            buttons, text="Cancel", style="Secondary.TButton", command=self.destroy
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            buttons, text="Use time", style="Primary.TButton", command=self._apply
        ).pack(side="left")
        self.bind("<Return>", lambda _event: self._apply())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.update_idletasks()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_width()) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self.winfo_height()) // 2)
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        hour_box.focus_set()

    def _apply(self) -> None:
        try:
            hour = int(self.hour_var.get())
            minute = int(self.minute_var.get())
            if not 1 <= hour <= 12 or not 0 <= minute <= 59:
                raise ValueError
            normalized = normalize_clock_time(
                f"{hour}:{minute:02d} {self.meridiem_var.get()}"
            )
        except ValueError:
            return
        self.on_select(format_clock_time_12h(normalized))
        self.destroy()

