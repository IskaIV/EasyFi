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
        TimePickerDialog(self, self.variable.get(), self._set_time)

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
    """Dropdown-style hour/minute/AM-PM list picker."""

    PICKER_BACKGROUND = "#383838"
    SELECTED_BACKGROUND = "#94C6FA"
    SELECTED_FOREGROUND = "#1C2B35"

    def __init__(self, anchor: tk.Misc, current: str, on_select) -> None:
        owner = anchor.winfo_toplevel()
        super().__init__(owner)
        self.withdraw()
        self.owner = owner
        self._owner_click_binding: str | None = None
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

        self.overrideredirect(True)
        self.resizable(False, False)
        self.configure(background=BORDER)
        self.transient(owner)
        body = tk.Frame(
            self,
            background=self.PICKER_BACKGROUND,
            padx=6,
            pady=6,
        )
        body.pack(fill="both", expand=True, padx=1, pady=1)

        lists = tk.Frame(body, background=self.PICKER_BACKGROUND)
        lists.pack(fill="both", expand=True)
        for column in range(3):
            lists.columnconfigure(column, weight=1)

        self.hour_list = self._listbox(lists)
        self.minute_list = self._listbox(lists)
        self.meridiem_list = self._listbox(lists)
        self.hour_list.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        self.minute_list.grid(row=0, column=1, sticky="nsew", padx=3)
        self.meridiem_list.grid(row=0, column=2, sticky="nsew", padx=(3, 0))

        hours = tuple(f"{value:02d}" for value in range(1, 13))
        minutes = tuple(f"{value:02d}" for value in range(60))
        meridiems = ("AM", "PM")
        self._fill_list(
            self.hour_list, self._rotate_values(hours, f"{int(hour):02d}")
        )
        self._fill_list(
            self.minute_list, self._rotate_values(minutes, minute)
        )
        self._fill_list(
            self.meridiem_list, self._rotate_values(meridiems, meridiem)
        )
        self.hour_list.bind(
            "<<ListboxSelect>>",
            lambda _event: self._update_variable(self.hour_list, self.hour_var),
        )
        self.minute_list.bind(
            "<<ListboxSelect>>",
            lambda _event: self._update_variable(self.minute_list, self.minute_var),
        )
        self.meridiem_list.bind(
            "<<ListboxSelect>>",
            lambda _event: self._update_variable(
                self.meridiem_list, self.meridiem_var
            ),
        )
        for listbox in (self.hour_list, self.minute_list, self.meridiem_list):
            listbox.bind("<Double-1>", lambda _event: self.after_idle(self._apply))
            listbox.bind(
                "<MouseWheel>",
                lambda event, target=listbox: self._scroll_list(target, event),
            )

        buttons = tk.Frame(body, background=self.PICKER_BACKGROUND)
        buttons.pack(fill="x", pady=(7, 0))
        tk.Button(
            buttons,
            text="Cancel",
            command=self.destroy,
            background=self.PICKER_BACKGROUND,
            foreground=TEXT,
            activebackground="#474747",
            activeforeground=TEXT,
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=("Segoe UI", 10),
            padx=15,
            pady=7,
            cursor="hand2",
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Button(
            buttons,
            text="Use time",
            command=self._apply,
            background=PRIMARY,
            foreground=PRIMARY_TEXT,
            activebackground=PRIMARY,
            activeforeground=PRIMARY_TEXT,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 10, "bold"),
            padx=15,
            pady=8,
            cursor="hand2",
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.bind("<Return>", lambda _event: self._apply())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<FocusOut>", lambda _event: self.after(20, self._close_if_unfocused))
        self.update_idletasks()
        self._position_below(anchor)
        self._owner_click_binding = owner.bind(
            "<Button-1>", lambda _event: self.destroy(), add="+"
        )
        self.lift()
        self.hour_list.focus_set()

    def _listbox(self, parent: tk.Misc) -> tk.Listbox:
        return tk.Listbox(
            parent,
            width=6,
            height=7,
            background=self.PICKER_BACKGROUND,
            foreground=TEXT,
            selectbackground=self.SELECTED_BACKGROUND,
            selectforeground=self.SELECTED_FOREGROUND,
            activestyle="none",
            exportselection=False,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 12),
            justify="center",
            cursor="hand2",
        )

    @staticmethod
    def _rotate_values(values: tuple[str, ...], selected: str) -> tuple[str, ...]:
        selected_index = values.index(selected)
        return values[selected_index:] + values[:selected_index]

    @staticmethod
    def _fill_list(listbox: tk.Listbox, values: tuple[str, ...]) -> None:
        for value in values:
            listbox.insert("end", value)
        listbox.selection_set(0)
        listbox.activate(0)
        listbox.yview(0)

    @staticmethod
    def _update_variable(listbox: tk.Listbox, variable: tk.StringVar) -> None:
        selection = listbox.curselection()
        if selection:
            variable.set(listbox.get(selection[0]))

    @staticmethod
    def _scroll_list(listbox: tk.Listbox, event: tk.Event) -> str:
        listbox.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _position_below(self, anchor: tk.Misc) -> None:
        anchor.update_idletasks()
        self.update_idletasks()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 3
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = min(x, screen_width - width - 8)
        if y + height > screen_height - 8:
            y = anchor.winfo_rooty() - height - 3
        self.geometry(f"{width}x{height}+{max(8, x)}+{max(8, y)}")
        self.deiconify()

    def _close_if_unfocused(self) -> None:
        if not self.winfo_exists():
            return
        focused = self.focus_get()
        if focused is None or focused.winfo_toplevel() is not self:
            self.destroy()

    def destroy(self) -> None:
        if self._owner_click_binding is not None and self.owner.winfo_exists():
            self.owner.unbind("<Button-1>", self._owner_click_binding)
            self._owner_click_binding = None
        super().destroy()

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
