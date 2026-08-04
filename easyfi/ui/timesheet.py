"""Tkinter implementation of EasyFi's first timesheet workflow."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from ..calculations import (
    ShiftCalculation,
    calculate_shift,
    format_clock_time_12h,
    format_minutes,
    format_money,
    normalize_clock_time,
    work_week_bounds,
)
from ..database import Database, IncomeSource, ShiftToSave
from .overview import OverviewPage
from .payments import PaymentsPage
from .settings import SettingsPage
from .theme import (
    BORDER,
    ERROR,
    FIELD_BACKGROUND,
    MUTED,
    PANEL_BACKGROUND,
    PANEL_RAISED,
    PRIMARY,
    PRIMARY_HOVER,
    PRIMARY_TEXT,
    SIDEBAR_ACTIVE,
    SIDEBAR_BACKGROUND,
    SOFT_GREEN,
    TEXT,
    WINDOW_BACKGROUND,
)
from .widgets import DateInput, TimeInput, format_display_date, parse_display_date


class TimesheetApp:
    def __init__(self, root: tk.Tk, database: Database) -> None:
        self.root = root
        self.database = database
        self.sources: list[IncomeSource] = []
        self.source_by_label: dict[str, IncomeSource] = {}
        self.break_variables: list[tk.StringVar] = []
        self.editing_shift_id: int | None = None
        self.editing_source_id: int | None = None
        self.editing_overtime_after_minutes: int | None = None
        self.editing_overtime_multiplier_milli: int | None = None

        self.form_title_var = tk.StringVar(value="Add a shift")
        self.form_subtitle_var = tk.StringVar(
            value="Enter the times. EasyFi calculates the rest."
        )
        self.save_button_var = tk.StringVar(value="Add shift")
        self.date_var = tk.StringVar(value=format_display_date(date.today()))
        self.source_var = tk.StringVar()
        self.clock_in_var = tk.StringVar(
            value=format_clock_time_12h(
                self.database.get_setting("default_clock_in", "08:30")
            )
        )
        self.clock_out_var = tk.StringVar(
            value=format_clock_time_12h(
                self.database.get_setting("default_clock_out", "17:00")
            )
        )
        self.rate_var = tk.StringVar(value="24.00")
        self.tax_var = tk.StringVar(value="18.00")
        self.week_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.elapsed_var = tk.StringVar(value="—")
        self.break_total_var = tk.StringVar(value="—")
        self.paid_time_var = tk.StringVar(value="—")
        self.regular_pay_var = tk.StringVar(value="—")
        self.overtime_pay_var = tk.StringVar(value="—")
        self.gross_var = tk.StringVar(value="—")
        self.tax_money_var = tk.StringVar(value="—")
        self.net_var = tk.StringVar(value="—")
        self.overtime_context_var = tk.StringVar()

        self._configure_window()
        self._configure_styles()
        self._build_ui()
        self._load_sources()
        initial_break = self.database.get_setting("default_break_minutes", "30")
        if initial_break != "0":
            self.add_break(initial_break)
        self._wire_live_updates()
        self.refresh_calculation()
        self.refresh_recent_shifts()

    def _configure_window(self) -> None:
        self.root.title("EasyFi")
        self.root.geometry("1220x840")
        self.root.minsize(1000, 720)
        self.root.configure(background=WINDOW_BACKGROUND)
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(family="Segoe UI", size=10)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("App.TFrame", background=WINDOW_BACKGROUND)
        style.configure("Panel.TFrame", background=PANEL_BACKGROUND)
        style.configure(
            "Card.TFrame",
            background=PANEL_BACKGROUND,
            bordercolor=BORDER,
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "InputShell.TFrame",
            background=FIELD_BACKGROUND,
            bordercolor=BORDER,
            borderwidth=1,
            relief="solid",
        )
        style.configure("Sidebar.TFrame", background=SIDEBAR_BACKGROUND)
        style.configure(
            "Title.TLabel",
            background=WINDOW_BACKGROUND,
            foreground=TEXT,
            font=("Segoe UI", 22, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=WINDOW_BACKGROUND,
            foreground=MUTED,
        )
        style.configure(
            "PanelTitle.TLabel",
            background=PANEL_BACKGROUND,
            foreground=TEXT,
            font=("Segoe UI", 12, "bold"),
        )
        style.configure(
            "Field.TLabel", background=PANEL_BACKGROUND, foreground=MUTED
        )
        style.configure(
            "SummaryValue.TLabel",
            background=PANEL_BACKGROUND,
            foreground=PRIMARY,
            font=("Segoe UI", 25, "bold"),
        )
        style.configure(
            "Summary.TLabel", background=PANEL_BACKGROUND, foreground=MUTED
        )
        style.configure(
            "Money.TLabel", background=PANEL_BACKGROUND, foreground=TEXT
        )
        style.configure(
            "MoneyStrong.TLabel",
            background=PANEL_BACKGROUND,
            foreground=TEXT,
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "Primary.TButton",
            background=PRIMARY,
            foreground=PRIMARY_TEXT,
            bordercolor=PRIMARY,
            font=("Segoe UI", 10, "bold"),
            padding=(17, 10),
        )
        style.map("Primary.TButton", background=[("active", PRIMARY_HOVER)])
        style.configure(
            "Secondary.TButton",
            background=PANEL_BACKGROUND,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=(14, 8),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", PANEL_RAISED)],
            foreground=[("active", TEXT)],
        )
        style.configure(
            "Danger.TButton",
            background=PANEL_BACKGROUND,
            foreground=ERROR,
            bordercolor=BORDER,
            padding=(14, 8),
        )
        style.configure(
            "Sidebar.TButton",
            background=SIDEBAR_BACKGROUND,
            foreground="#DCEDE2",
            borderwidth=0,
            anchor="w",
            padding=(14, 11),
        )
        style.map(
            "Sidebar.TButton",
            background=[("active", SIDEBAR_ACTIVE)],
            foreground=[("active", "#FFFFFF")],
        )
        style.configure(
            "SidebarActive.TButton",
            background=SIDEBAR_ACTIVE,
            foreground="#FFFFFF",
            borderwidth=0,
            anchor="w",
            padding=(14, 11),
        )
        style.configure(
            "Treeview",
            background=PANEL_BACKGROUND,
            fieldbackground=PANEL_BACKGROUND,
            foreground=TEXT,
            rowheight=30,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=SOFT_GREEN,
            foreground=TEXT,
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
        )
        style.map(
            "Treeview",
            background=[("selected", SIDEBAR_ACTIVE)],
            foreground=[("selected", TEXT)],
        )
        style.configure(
            "TEntry",
            fieldbackground=FIELD_BACKGROUND,
            foreground=TEXT,
            insertcolor=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=(10, 8),
        )
        style.configure(
            "Picker.TEntry",
            fieldbackground=FIELD_BACKGROUND,
            foreground=TEXT,
            insertcolor=TEXT,
            borderwidth=0,
            padding=(10, 8),
        )
        style.configure(
            "PickerIcon.TButton",
            background=FIELD_BACKGROUND,
            foreground=TEXT,
            borderwidth=0,
            padding=(4, 7),
        )
        style.map(
            "PickerIcon.TButton",
            background=[("active", PANEL_RAISED)],
            foreground=[("active", PRIMARY)],
        )
        style.configure(
            "TCombobox",
            fieldbackground=FIELD_BACKGROUND,
            background=FIELD_BACKGROUND,
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=(9, 7),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", FIELD_BACKGROUND)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", FIELD_BACKGROUND)],
            selectforeground=[("readonly", TEXT)],
        )
        style.configure(
            "TSpinbox",
            fieldbackground=FIELD_BACKGROUND,
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=BORDER,
            padding=(8, 7),
        )
        style.configure(
            "TCheckbutton",
            background=PANEL_BACKGROUND,
            foreground=TEXT,
            indicatorcolor=FIELD_BACKGROUND,
        )
        style.map(
            "TCheckbutton",
            background=[("active", PANEL_BACKGROUND)],
            foreground=[("active", TEXT)],
            indicatorcolor=[("selected", PRIMARY)],
        )

    def _build_ui(self) -> None:
        shell = ttk.Frame(self.root, style="App.TFrame")
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(0, weight=1)

        self._build_sidebar(shell)
        self.page_host = ttk.Frame(shell, style="App.TFrame")
        self.page_host.grid(row=0, column=1, sticky="nsew")
        self.page_host.columnconfigure(0, weight=1)
        self.page_host.rowconfigure(0, weight=1)

        self.timesheet_page = ttk.Frame(
            self.page_host, style="App.TFrame", padding=(26, 22)
        )
        self.timesheet_page.grid(row=0, column=0, sticky="nsew")
        self.settings_page = SettingsPage(
            self.page_host, self.database, self._settings_changed
        )
        self.settings_page.grid(row=0, column=0, sticky="nsew")
        self.payments_page = PaymentsPage(self.page_host, self.database)
        self.payments_page.grid(row=0, column=0, sticky="nsew")
        self.overview_page = OverviewPage(self.page_host, self.database)
        self.overview_page.grid(row=0, column=0, sticky="nsew")
        self._build_timesheet_page(self.timesheet_page)
        self.show_page("timesheet")

    def _build_timesheet_page(self, content: ttk.Frame) -> None:
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)

        header = ttk.Frame(content, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, textvariable=self.form_title_var, style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            textvariable=self.form_subtitle_var,
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(header, textvariable=self.week_var, style="Subtitle.TLabel").grid(
            row=0, column=1, rowspan=2, sticky="e"
        )

        upper = ttk.Frame(content, style="App.TFrame")
        upper.grid(row=1, column=0, sticky="ew")
        upper.columnconfigure(0, weight=3)
        upper.columnconfigure(1, weight=2)
        self._build_shift_form(upper)
        self._build_summary(upper)
        self._build_recent_shifts(content)

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        sidebar = ttk.Frame(parent, style="Sidebar.TFrame", width=190, padding=(14, 24))
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        brand = tk.Label(
            sidebar,
            text="▣  EasyFi",
            font=("Segoe UI", 16, "bold"),
            background=SIDEBAR_BACKGROUND,
            foreground="#F1FFF5",
            anchor="w",
        )
        brand.pack(fill="x", padx=6, pady=(0, 24))
        self.overview_nav_button = ttk.Button(
            sidebar,
            text="▦   Overview",
            style="Sidebar.TButton",
            command=lambda: self.show_page("overview"),
        )
        self.overview_nav_button.pack(fill="x", pady=2)
        self.timesheet_nav_button = ttk.Button(
            sidebar,
            text="◷   Timesheet",
            style="SidebarActive.TButton",
            command=lambda: self.show_page("timesheet"),
        )
        self.timesheet_nav_button.pack(fill="x", pady=2)
        self.payments_nav_button = ttk.Button(
            sidebar,
            text="▤   Payments",
            style="Sidebar.TButton",
            command=lambda: self.show_page("payments"),
        )
        self.payments_nav_button.pack(fill="x", pady=2)
        self.settings_nav_button = ttk.Button(
            sidebar,
            text="☷   Settings",
            style="Sidebar.TButton",
            command=lambda: self.show_page("settings"),
        )
        self.settings_nav_button.pack(fill="x", pady=2)

    def show_page(self, page: str) -> None:
        self.overview_nav_button.configure(style="Sidebar.TButton")
        self.timesheet_nav_button.configure(style="Sidebar.TButton")
        self.payments_nav_button.configure(style="Sidebar.TButton")
        self.settings_nav_button.configure(style="Sidebar.TButton")
        if page == "settings":
            self.settings_page.refresh()
            self.settings_page.tkraise()
            self.settings_nav_button.configure(style="SidebarActive.TButton")
            return
        if page == "payments":
            self.payments_page.refresh()
            self.payments_page.tkraise()
            self.payments_nav_button.configure(style="SidebarActive.TButton")
            return
        if page == "overview":
            self.overview_page.refresh()
            self.overview_page.tkraise()
            self.overview_nav_button.configure(style="SidebarActive.TButton")
            return
        self.timesheet_page.tkraise()
        self.timesheet_nav_button.configure(style="SidebarActive.TButton")

    def _settings_changed(self) -> None:
        editing_source_id = self.editing_source_id
        self._load_sources()
        if (
            self.editing_shift_id is not None
            and editing_source_id is not None
            and all(source.id != editing_source_id for source in self.sources)
        ):
            self._reset_form(clear_status=False)
            self._set_status(
                "Shift editing was closed because its income source was archived.",
                error=True,
            )
        self._refresh_week_label()
        self.refresh_recent_shifts()
        self.refresh_calculation()
        self.payments_page.refresh()
        self.overview_page.refresh()

    def _build_shift_form(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Card.TFrame", padding=22)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        panel.columnconfigure(0, weight=1)
        panel.columnconfigure(1, weight=1)
        ttk.Label(panel, text="Shift details", style="PanelTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 16)
        )

        date_frame = ttk.Frame(panel, style="Panel.TFrame")
        date_frame.grid(row=1, column=0, sticky="ew")
        ttk.Label(date_frame, text="Date worked", style="Field.TLabel").pack(
            anchor="w", pady=(0, 6)
        )
        DateInput(date_frame, textvariable=self.date_var).pack(fill="x")
        source_frame = ttk.Frame(panel, style="Panel.TFrame")
        source_frame.grid(row=1, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(source_frame, text="Income source", style="Field.TLabel").pack(
            anchor="w", pady=(0, 5)
        )
        self.source_combo = ttk.Combobox(
            source_frame, textvariable=self.source_var, state="readonly"
        )
        self.source_combo.pack(fill="x")

        time_frame = ttk.Frame(panel, style="Panel.TFrame")
        time_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        time_frame.columnconfigure(0, weight=1)
        time_frame.columnconfigure(2, weight=1)
        clock_in_frame = ttk.Frame(time_frame, style="Panel.TFrame")
        clock_in_frame.grid(row=0, column=0, sticky="ew")
        ttk.Label(clock_in_frame, text="Clock in", style="Field.TLabel").pack(
            anchor="w", pady=(0, 6)
        )
        TimeInput(clock_in_frame, textvariable=self.clock_in_var).pack(fill="x")
        ttk.Label(time_frame, text="→", style="Field.TLabel").grid(
            row=0, column=1, padx=12, pady=(22, 0)
        )
        clock_out_frame = ttk.Frame(time_frame, style="Panel.TFrame")
        clock_out_frame.grid(row=0, column=2, sticky="ew")
        ttk.Label(clock_out_frame, text="Clock out", style="Field.TLabel").pack(
            anchor="w", pady=(0, 6)
        )
        TimeInput(clock_out_frame, textvariable=self.clock_out_var).pack(fill="x")

        breaks_header = ttk.Frame(panel, style="Panel.TFrame")
        breaks_header.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(16, 5))
        breaks_header.columnconfigure(0, weight=1)
        ttk.Label(breaks_header, text="Unpaid breaks", style="Field.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            breaks_header,
            text="+ Add break",
            style="Secondary.TButton",
            command=lambda: self.add_break("15"),
        ).grid(row=0, column=1, sticky="e")
        self.breaks_frame = ttk.Frame(panel, style="Panel.TFrame")
        self.breaks_frame.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.breaks_frame.columnconfigure(0, weight=1)

        rates = ttk.Frame(panel, style="Panel.TFrame")
        rates.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        rates.columnconfigure(0, weight=1)
        rates.columnconfigure(1, weight=1)
        self._labeled_entry(rates, "Hourly rate ($)", self.rate_var, 0, 0)
        self._labeled_entry(rates, "Estimated tax (%)", self.tax_var, 0, 1, left=8)

        actions = ttk.Frame(panel, style="Panel.TFrame")
        actions.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        actions.columnconfigure(0, weight=1)
        self.status_label = tk.Label(
            actions,
            textvariable=self.status_var,
            background=PANEL_BACKGROUND,
            foreground=PRIMARY,
            anchor="w",
        )
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.delete_form_button = ttk.Button(
            actions,
            text="Delete",
            style="Danger.TButton",
            state="disabled",
            command=self.delete_editing_shift,
        )
        self.delete_form_button.grid(row=0, column=1, padx=(8, 8))
        ttk.Button(
            actions, text="Clear", style="Secondary.TButton", command=self.clear_form
        ).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(
            actions,
            textvariable=self.save_button_var,
            style="Primary.TButton",
            command=self.save_shift,
        ).grid(row=0, column=3)

    def _build_summary(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Card.TFrame", padding=22)
        panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, text="Live calculation", style="PanelTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(panel, textvariable=self.paid_time_var, style="SummaryValue.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(15, 0)
        )
        summary_line = ttk.Frame(panel, style="Panel.TFrame")
        summary_line.grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 14))
        ttk.Label(summary_line, textvariable=self.elapsed_var, style="Summary.TLabel").pack(
            side="left"
        )
        ttk.Label(summary_line, text=" elapsed − ", style="Summary.TLabel").pack(
            side="left"
        )
        ttk.Label(
            summary_line, textvariable=self.break_total_var, style="Summary.TLabel"
        ).pack(side="left")
        ttk.Label(summary_line, text=" break", style="Summary.TLabel").pack(side="left")

        rows = [
            ("Regular pay", self.regular_pay_var, "Money.TLabel"),
            ("Overtime pay", self.overtime_pay_var, "Money.TLabel"),
            ("Gross pay", self.gross_var, "MoneyStrong.TLabel"),
            ("Estimated tax", self.tax_money_var, "Money.TLabel"),
            ("Estimated take-home", self.net_var, "MoneyStrong.TLabel"),
        ]
        for index, (label, variable, value_style) in enumerate(rows, start=3):
            ttk.Label(panel, text=label, style="Money.TLabel").grid(
                row=index, column=0, sticky="w", pady=5
            )
            ttk.Label(panel, textvariable=variable, style=value_style).grid(
                row=index, column=1, sticky="e", pady=5
            )

        note = tk.Label(
            panel,
            textvariable=self.overtime_context_var,
            wraplength=260,
            justify="left",
            background=SOFT_GREEN,
            foreground=MUTED,
            padx=10,
            pady=10,
        )
        note.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(15, 0))

    def _build_recent_shifts(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Card.TFrame", padding=18)
        panel.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        recent_header = ttk.Frame(panel, style="Panel.TFrame")
        recent_header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        recent_header.columnconfigure(0, weight=1)
        ttk.Label(
            recent_header, text="Recent shifts", style="PanelTitle.TLabel"
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            recent_header,
            text="Edit selected",
            style="Secondary.TButton",
            command=self.edit_selected_shift,
        ).grid(row=0, column=1, padx=(8, 8))
        ttk.Button(
            recent_header,
            text="Delete selected",
            style="Danger.TButton",
            command=self.delete_selected_shift,
        ).grid(row=0, column=2)
        columns = ("date", "source", "time", "paid", "gross", "take_home")
        self.shift_table = ttk.Treeview(
            panel, columns=columns, show="headings", height=6
        )
        headings = {
            "date": "Date",
            "source": "Income source",
            "time": "Clock time",
            "paid": "Paid time",
            "gross": "Gross",
            "take_home": "Take-home",
        }
        widths = {
            "date": 95,
            "source": 180,
            "time": 120,
            "paid": 95,
            "gross": 95,
            "take_home": 105,
        }
        for column in columns:
            self.shift_table.heading(column, text=headings[column])
            self.shift_table.column(column, width=widths[column], anchor="w")
        self.shift_table.grid(row=1, column=0, sticky="nsew")
        self.shift_table.bind("<Double-1>", lambda _event: self.edit_selected_shift())

    def _labeled_entry(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        row: int,
        column: int,
        *,
        left: int = 0,
    ) -> ttk.Entry:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.grid(row=row, column=column, sticky="ew", padx=(left, 0))
        ttk.Label(frame, text=label, style="Field.TLabel").pack(anchor="w", pady=(0, 5))
        entry = ttk.Entry(frame, textvariable=variable)
        entry.pack(fill="x")
        return entry

    def _load_sources(self) -> None:
        selected_source = self.source_by_label.get(self.source_var.get())
        selected_source_id = selected_source.id if selected_source is not None else None
        preserve_shift_values = (
            self.editing_shift_id is not None
            and self.editing_source_id == selected_source_id
        )
        preserved_rate = self.rate_var.get()
        preserved_tax = self.tax_var.get()
        self.sources = self.database.list_income_sources()
        self.source_by_label = {
            f"{source.name} · {format_money(source.hourly_rate_cents)}/hr": source
            for source in self.sources
        }
        labels = list(self.source_by_label)
        self.source_combo.configure(values=labels)
        if labels:
            selected_label = next(
                (
                    label
                    for label, source in self.source_by_label.items()
                    if source.id == selected_source_id
                ),
                labels[0],
            )
            self.source_var.set(selected_label)
            self._apply_selected_source()
            if preserve_shift_values and any(
                source.id == selected_source_id for source in self.sources
            ):
                self.rate_var.set(preserved_rate)
                self.tax_var.set(preserved_tax)

    def _wire_live_updates(self) -> None:
        for variable in (
            self.date_var,
            self.clock_in_var,
            self.clock_out_var,
            self.rate_var,
            self.tax_var,
        ):
            variable.trace_add("write", lambda *_args: self.refresh_calculation())
        self.source_var.trace_add("write", lambda *_args: self._source_changed())
        self.root.bind("<Control-Return>", lambda _event: self.save_shift())

    def _source_changed(self) -> None:
        self._apply_selected_source()
        self.refresh_calculation()

    def _apply_selected_source(self) -> None:
        source = self.source_by_label.get(self.source_var.get())
        if source is None:
            return
        self.rate_var.set(f"{source.hourly_rate_cents / 100:.2f}")
        self.tax_var.set(f"{source.tax_rate_bps / 100:.2f}")

    def add_break(self, minutes: str) -> None:
        variable = tk.StringVar(value=minutes)
        row = ttk.Frame(self.breaks_frame, style="Panel.TFrame")
        row.pack(fill="x", pady=3)
        row.columnconfigure(0, weight=1)
        selector = ttk.Combobox(
            row,
            textvariable=variable,
            values=("0", "15", "30", "45", "60"),
            width=10,
        )
        selector.grid(row=0, column=0, sticky="ew")
        ttk.Label(row, text="minutes", style="Field.TLabel").grid(
            row=0, column=1, padx=(8, 12)
        )
        ttk.Button(
            row,
            text="Remove",
            style="Secondary.TButton",
            command=lambda: self.remove_break(row, variable),
        ).grid(row=0, column=2)
        self.break_variables.append(variable)
        variable.trace_add("write", lambda *_args: self.refresh_calculation())
        self.refresh_calculation()

    def remove_break(self, row: ttk.Frame, variable: tk.StringVar) -> None:
        if variable in self.break_variables:
            self.break_variables.remove(variable)
        row.destroy()
        self.refresh_calculation()

    def _form_values(
        self,
    ) -> tuple[
        date,
        IncomeSource,
        str,
        str,
        tuple[int, ...],
        int,
        int,
        int,
        ShiftCalculation,
    ]:
        try:
            work_date = parse_display_date(self.date_var.get())
        except ValueError as exc:
            raise ValueError("Date must use MM/DD/YYYY format.") from exc

        source = self.source_by_label.get(self.source_var.get())
        if source is None:
            raise ValueError("Choose an income source.")
        try:
            hourly_rate_cents = int(
                (Decimal(self.rate_var.get().strip()) * 100).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            tax_rate_bps = int(
                (Decimal(self.tax_var.get().strip()) * 100).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            breaks = tuple(
                int(variable.get().strip()) for variable in self.break_variables
            )
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("Rate, tax, and breaks must be valid numbers.") from exc

        if hourly_rate_cents <= 0:
            raise ValueError("Hourly rate must be greater than $0.00.")
        if not 0 <= tax_rate_bps <= 10_000:
            raise ValueError("Estimated tax must be between 0% and 100%.")
        if any(duration < 0 or duration > 24 * 60 for duration in breaks):
            raise ValueError("Each break must be between 0 and 1,440 minutes.")
        breaks = tuple(duration for duration in breaks if duration > 0)

        clock_in = self._normalize_clock_time(self.clock_in_var.get())
        clock_out = self._normalize_clock_time(self.clock_out_var.get())

        work_week_start = self.database.get_setting_int("work_week_start", 3)
        week_start, _week_end = work_week_bounds(work_date, work_week_start)
        prior_minutes = self.database.prior_paid_minutes(
            income_source_id=source.id,
            week_start=week_start,
            work_date=work_date,
            clock_in=clock_in,
            exclude_shift_id=self.editing_shift_id,
        )
        overtime_after, overtime_multiplier = self._current_overtime_rules(source)
        calculation = calculate_shift(
            clock_in=clock_in,
            clock_out=clock_out,
            break_durations=breaks,
            hourly_rate_cents=hourly_rate_cents,
            tax_rate_bps=tax_rate_bps,
            prior_week_minutes=prior_minutes,
            overtime_after_minutes=overtime_after,
            overtime_multiplier_milli=overtime_multiplier,
        )
        return (
            work_date,
            source,
            clock_in,
            clock_out,
            breaks,
            hourly_rate_cents,
            tax_rate_bps,
            prior_minutes,
            calculation,
        )

    @staticmethod
    def _normalize_clock_time(value: str) -> str:
        return normalize_clock_time(value)

    def _current_overtime_rules(self, source: IncomeSource) -> tuple[int, int]:
        if (
            self.editing_shift_id is not None
            and self.editing_source_id == source.id
            and self.editing_overtime_after_minutes is not None
            and self.editing_overtime_multiplier_milli is not None
        ):
            return (
                self.editing_overtime_after_minutes,
                self.editing_overtime_multiplier_milli,
            )
        return source.overtime_after_minutes, source.overtime_multiplier_milli

    def refresh_calculation(self) -> None:
        self._refresh_week_label()
        try:
            *_values, prior_minutes, calculation = self._form_values()
        except ValueError:
            self._clear_summary()
            return
        self._show_summary(calculation, prior_minutes)

    def _refresh_week_label(self) -> None:
        try:
            work_date = parse_display_date(self.date_var.get())
            start_day = self.database.get_setting_int("work_week_start", 3)
            start, end = work_week_bounds(work_date, start_day)
        except ValueError:
            self.week_var.set("Work week: —")
            return
        self.week_var.set(
            f"Work week: {start.strftime('%a, %b %d')} – {end.strftime('%a, %b %d')}"
        )

    def _show_summary(
        self, calculation: ShiftCalculation, prior_minutes: int
    ) -> None:
        self.elapsed_var.set(format_minutes(calculation.elapsed_minutes))
        self.break_total_var.set(format_minutes(calculation.break_minutes))
        self.paid_time_var.set(format_minutes(calculation.paid_minutes))
        self.regular_pay_var.set(format_money(calculation.regular_pay_cents))
        self.overtime_pay_var.set(format_money(calculation.overtime_pay_cents))
        self.gross_var.set(format_money(calculation.gross_pay_cents))
        self.tax_money_var.set(f"−{format_money(calculation.tax_cents)}")
        self.net_var.set(format_money(calculation.net_pay_cents))
        self.overtime_context_var.set(
            f"{format_minutes(prior_minutes)} already logged before this shift. "
            "Overtime rules come from the selected income source."
        )

    def _clear_summary(self) -> None:
        for variable in (
            self.elapsed_var,
            self.break_total_var,
            self.paid_time_var,
            self.regular_pay_var,
            self.overtime_pay_var,
            self.gross_var,
            self.tax_money_var,
            self.net_var,
        ):
            variable.set("—")
        self.overtime_context_var.set(
            "Complete the shift details to see the pay calculation."
        )

    def save_shift(self) -> None:
        try:
            (
                work_date,
                source,
                clock_in,
                clock_out,
                breaks,
                hourly_rate_cents,
                tax_rate_bps,
                _prior_minutes,
                calculation,
            ) = self._form_values()
            if self.database.has_duplicate_shift(
                income_source_id=source.id,
                work_date=work_date,
                clock_in=clock_in,
                clock_out=clock_out,
                exclude_shift_id=self.editing_shift_id,
            ) and not messagebox.askyesno(
                "Possible duplicate shift",
                "A shift with the same date, income source, clock-in, and "
                "clock-out already exists. Save it anyway?",
                parent=self.root,
            ):
                self._set_status("Duplicate shift was not saved.", error=True)
                return

            overtime_after, overtime_multiplier = self._current_overtime_rules(source)
            shift = ShiftToSave(
                income_source_id=source.id,
                work_date=work_date,
                clock_in=clock_in,
                clock_out=clock_out,
                break_durations=breaks,
                hourly_rate_cents=hourly_rate_cents,
                tax_rate_bps=tax_rate_bps,
                overtime_after_minutes=overtime_after,
                overtime_multiplier_milli=overtime_multiplier,
                calculation=calculation,
            )
            if self.editing_shift_id is None:
                shift_id = self.database.save_shift(shift)
                success_message = f"Shift #{shift_id} saved locally."
            else:
                shift_id = self.editing_shift_id
                self.database.update_shift(shift_id, shift)
                success_message = f"Shift #{shift_id} updated."
        except (ValueError, OSError) as exc:
            self._set_status(str(exc), error=True)
            return

        self._set_status(success_message)
        self.refresh_recent_shifts()
        self._reset_form(clear_status=False)

    def clear_form(self) -> None:
        self._reset_form(clear_status=True)

    def _reset_form(self, *, clear_status: bool) -> None:
        self.editing_shift_id = None
        self.editing_source_id = None
        self.editing_overtime_after_minutes = None
        self.editing_overtime_multiplier_milli = None
        self.form_title_var.set("Add a shift")
        self.form_subtitle_var.set("Enter the times. EasyFi calculates the rest.")
        self.save_button_var.set("Add shift")
        self.delete_form_button.configure(state="disabled")
        self.date_var.set(format_display_date(date.today()))
        self.clock_in_var.set(
            format_clock_time_12h(
                self.database.get_setting("default_clock_in", "08:30")
            )
        )
        self.clock_out_var.set(
            format_clock_time_12h(
                self.database.get_setting("default_clock_out", "17:00")
            )
        )
        for child in self.breaks_frame.winfo_children():
            child.destroy()
        self.break_variables.clear()
        default_break = self.database.get_setting("default_break_minutes", "30")
        if default_break != "0":
            self.add_break(default_break)
        labels = list(self.source_by_label)
        if labels:
            self.source_var.set(labels[0])
        self._apply_selected_source()
        if clear_status:
            self.status_var.set("")
        self.refresh_calculation()

    def edit_selected_shift(self) -> None:
        shift_id = self._selected_shift_id()
        if shift_id is None:
            self._set_status("Select a shift to edit.", error=True)
            return
        shift = self.database.get_shift(shift_id)
        if shift is None:
            self._set_status("The selected shift no longer exists.", error=True)
            self.refresh_recent_shifts()
            return

        source_label = next(
            (
                label
                for label, source in self.source_by_label.items()
                if source.id == shift.income_source_id
            ),
            None,
        )
        if source_label is None:
            self._set_status(
                "The shift's income source is unavailable. Restore it before editing.",
                error=True,
            )
            return

        self.editing_shift_id = shift.id
        self.editing_source_id = shift.income_source_id
        self.editing_overtime_after_minutes = shift.overtime_after_minutes
        self.editing_overtime_multiplier_milli = shift.overtime_multiplier_milli
        self.form_title_var.set(f"Edit shift #{shift.id}")
        self.form_subtitle_var.set(
            "Update the shift and save. Weekly overtime will be recalculated."
        )
        self.save_button_var.set("Save changes")
        self.delete_form_button.configure(state="normal")

        self.date_var.set(format_display_date(shift.work_date))
        self.source_var.set(source_label)
        self.clock_in_var.set(format_clock_time_12h(shift.clock_in))
        self.clock_out_var.set(format_clock_time_12h(shift.clock_out))
        self.rate_var.set(f"{shift.hourly_rate_cents / 100:.2f}")
        self.tax_var.set(f"{shift.tax_rate_bps / 100:.2f}")
        for child in self.breaks_frame.winfo_children():
            child.destroy()
        self.break_variables.clear()
        for duration in shift.break_durations:
            self.add_break(str(duration))
        self._set_status(f"Editing shift #{shift.id}.")
        self.refresh_calculation()

    def delete_selected_shift(self) -> None:
        shift_id = self._selected_shift_id()
        if shift_id is None:
            self._set_status("Select a shift to delete.", error=True)
            return
        self._delete_shift(shift_id)

    def delete_editing_shift(self) -> None:
        if self.editing_shift_id is None:
            return
        self._delete_shift(self.editing_shift_id)

    def _delete_shift(self, shift_id: int) -> None:
        shift = self.database.get_shift(shift_id)
        if shift is None:
            self._set_status("The selected shift no longer exists.", error=True)
            self.refresh_recent_shifts()
            return
        if not messagebox.askyesno(
            "Delete shift?",
            f"Delete the {shift.work_date.isoformat()} shift from "
            f"{shift.clock_in} to {shift.clock_out}?\n\n"
            "This will recalculate overtime for the rest of that work week.",
            icon="warning",
            parent=self.root,
        ):
            return
        if not self.database.delete_shift(shift_id):
            self._set_status("The selected shift no longer exists.", error=True)
            self.refresh_recent_shifts()
            return

        was_editing = self.editing_shift_id == shift_id
        if was_editing:
            self._reset_form(clear_status=False)
        self._set_status(f"Shift #{shift_id} deleted.")
        self.refresh_recent_shifts()
        self.refresh_calculation()

    def _selected_shift_id(self) -> int | None:
        selection = self.shift_table.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.configure(foreground=ERROR if error else PRIMARY)
        self.status_var.set(message)

    def refresh_recent_shifts(self) -> None:
        for item in self.shift_table.get_children():
            self.shift_table.delete(item)
        for shift in self.database.list_recent_shifts():
            self.shift_table.insert(
                "",
                "end",
                iid=str(shift["id"]),
                values=(
                    format_display_date(date.fromisoformat(shift["work_date"])),
                    shift["source_name"],
                    f"{format_clock_time_12h(shift['clock_in'])} – "
                    f"{format_clock_time_12h(shift['clock_out'])}",
                    format_minutes(shift["paid_minutes"]),
                    format_money(shift["gross_pay_cents"]),
                    format_money(shift["net_pay_cents"]),
                ),
            )


def launch(database: Database) -> None:
    root = tk.Tk()
    TimesheetApp(root, database)
    root.mainloop()
