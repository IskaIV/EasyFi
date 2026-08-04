"""Tkinter implementation of EasyFi's first timesheet workflow."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from tkinter import font as tkfont
from tkinter import ttk

from ..calculations import (
    ShiftCalculation,
    calculate_shift,
    format_minutes,
    format_money,
    work_week_bounds,
)
from ..database import Database, IncomeSource, ShiftToSave


WINDOW_BACKGROUND = "#F4F7F5"
PANEL_BACKGROUND = "#FFFFFF"
SIDEBAR_BACKGROUND = "#183F2B"
SIDEBAR_ACTIVE = "#2E5A40"
PRIMARY = "#17643C"
PRIMARY_HOVER = "#115332"
TEXT = "#17211B"
MUTED = "#627068"
BORDER = "#D8E1DB"
SOFT_GREEN = "#EEF6F0"
ERROR = "#A53A3A"


class TimesheetApp:
    def __init__(self, root: tk.Tk, database: Database) -> None:
        self.root = root
        self.database = database
        self.sources: list[IncomeSource] = []
        self.source_by_label: dict[str, IncomeSource] = {}
        self.break_variables: list[tk.StringVar] = []

        self.date_var = tk.StringVar(value=date.today().isoformat())
        self.source_var = tk.StringVar()
        self.clock_in_var = tk.StringVar(value="08:30")
        self.clock_out_var = tk.StringVar(value="17:00")
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
        self.add_break("30")
        self._wire_live_updates()
        self.refresh_calculation()
        self.refresh_recent_shifts()

    def _configure_window(self) -> None:
        self.root.title("EasyFi")
        self.root.geometry("1120x780")
        self.root.minsize(900, 680)
        self.root.configure(background=WINDOW_BACKGROUND)
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(family="Segoe UI", size=10)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("App.TFrame", background=WINDOW_BACKGROUND)
        style.configure("Panel.TFrame", background=PANEL_BACKGROUND)
        style.configure("Sidebar.TFrame", background=SIDEBAR_BACKGROUND)
        style.configure(
            "Title.TLabel",
            background=WINDOW_BACKGROUND,
            foreground=TEXT,
            font=("Segoe UI", 20, "bold"),
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
            foreground="#FFFFFF",
            bordercolor=PRIMARY,
            padding=(16, 9),
        )
        style.map("Primary.TButton", background=[("active", PRIMARY_HOVER)])
        style.configure(
            "Secondary.TButton",
            background=PANEL_BACKGROUND,
            foreground=TEXT,
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

    def _build_ui(self) -> None:
        shell = ttk.Frame(self.root, style="App.TFrame")
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(0, weight=1)

        self._build_sidebar(shell)
        content = ttk.Frame(shell, style="App.TFrame", padding=(26, 22))
        content.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)

        header = ttk.Frame(content, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Add a shift", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Enter the times. EasyFi calculates the rest.",
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
        sidebar = ttk.Frame(parent, style="Sidebar.TFrame", width=170, padding=(12, 20))
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        brand = tk.Label(
            sidebar,
            text="  EasyFi",
            font=("Segoe UI", 16, "bold"),
            background=SIDEBAR_BACKGROUND,
            foreground="#F1FFF5",
            anchor="w",
        )
        brand.pack(fill="x", padx=6, pady=(0, 24))
        ttk.Button(
            sidebar, text="Overview", style="Sidebar.TButton", state="disabled"
        ).pack(fill="x", pady=2)
        ttk.Button(
            sidebar, text="Timesheet", style="SidebarActive.TButton"
        ).pack(fill="x", pady=2)
        ttk.Button(
            sidebar, text="Payments", style="Sidebar.TButton", state="disabled"
        ).pack(fill="x", pady=2)
        ttk.Button(
            sidebar, text="Settings", style="Sidebar.TButton", state="disabled"
        ).pack(fill="x", pady=2)

    def _build_shift_form(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=20)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        panel.columnconfigure(0, weight=1)
        panel.columnconfigure(1, weight=1)
        ttk.Label(panel, text="Shift details", style="PanelTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 16)
        )

        self._labeled_entry(panel, "Date worked", self.date_var, 1, 0)
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
        self._labeled_entry(time_frame, "Clock in", self.clock_in_var, 0, 0)
        ttk.Label(time_frame, text="→", style="Field.TLabel").grid(
            row=0, column=1, padx=12, pady=(22, 0)
        )
        self._labeled_entry(time_frame, "Clock out", self.clock_out_var, 0, 2)

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
        ttk.Button(
            actions, text="Clear", style="Secondary.TButton", command=self.clear_form
        ).grid(row=0, column=1, padx=(8, 8))
        ttk.Button(
            actions, text="Add shift", style="Primary.TButton", command=self.save_shift
        ).grid(row=0, column=2)

    def _build_summary(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=20)
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
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=18)
        panel.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        ttk.Label(panel, text="Recent shifts", style="PanelTitle.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 10)
        )
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
        self.sources = self.database.list_income_sources()
        self.source_by_label = {
            f"{source.name} · {format_money(source.hourly_rate_cents)}/hr": source
            for source in self.sources
        }
        labels = list(self.source_by_label)
        self.source_combo.configure(values=labels)
        if labels:
            self.source_var.set(labels[0])
            self._apply_selected_source()

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
    ) -> tuple[date, IncomeSource, tuple[int, ...], int, int, int, ShiftCalculation]:
        try:
            work_date = date.fromisoformat(self.date_var.get().strip())
        except ValueError as exc:
            raise ValueError("Date must use YYYY-MM-DD format.") from exc

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

        work_week_start = self.database.get_setting_int("work_week_start", 3)
        week_start, _week_end = work_week_bounds(work_date, work_week_start)
        prior_minutes = self.database.prior_paid_minutes(
            income_source_id=source.id,
            week_start=week_start,
            through_date=work_date,
        )
        calculation = calculate_shift(
            clock_in=self.clock_in_var.get(),
            clock_out=self.clock_out_var.get(),
            break_durations=breaks,
            hourly_rate_cents=hourly_rate_cents,
            tax_rate_bps=tax_rate_bps,
            prior_week_minutes=prior_minutes,
            overtime_after_minutes=source.overtime_after_minutes,
            overtime_multiplier_milli=source.overtime_multiplier_milli,
        )
        return (
            work_date,
            source,
            breaks,
            hourly_rate_cents,
            tax_rate_bps,
            prior_minutes,
            calculation,
        )

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
            work_date = date.fromisoformat(self.date_var.get().strip())
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
                breaks,
                hourly_rate_cents,
                tax_rate_bps,
                _prior_minutes,
                calculation,
            ) = self._form_values()
            shift_id = self.database.save_shift(
                ShiftToSave(
                    income_source_id=source.id,
                    work_date=work_date,
                    clock_in=self.clock_in_var.get().strip(),
                    clock_out=self.clock_out_var.get().strip(),
                    break_durations=breaks,
                    hourly_rate_cents=hourly_rate_cents,
                    tax_rate_bps=tax_rate_bps,
                    overtime_after_minutes=source.overtime_after_minutes,
                    overtime_multiplier_milli=source.overtime_multiplier_milli,
                    calculation=calculation,
                )
            )
        except (ValueError, OSError) as exc:
            self.status_label.configure(foreground=ERROR)
            self.status_var.set(str(exc))
            return

        self.status_label.configure(foreground=PRIMARY)
        self.status_var.set(f"Shift #{shift_id} saved locally.")
        self.refresh_recent_shifts()
        self.refresh_calculation()

    def clear_form(self) -> None:
        self.date_var.set(date.today().isoformat())
        self.clock_in_var.set("08:30")
        self.clock_out_var.set("17:00")
        for child in self.breaks_frame.winfo_children():
            child.destroy()
        self.break_variables.clear()
        self.add_break("30")
        self._apply_selected_source()
        self.status_var.set("")

    def refresh_recent_shifts(self) -> None:
        for item in self.shift_table.get_children():
            self.shift_table.delete(item)
        for shift in self.database.list_recent_shifts():
            self.shift_table.insert(
                "",
                "end",
                values=(
                    shift["work_date"],
                    shift["source_name"],
                    f"{shift['clock_in']}–{shift['clock_out']}",
                    format_minutes(shift["paid_minutes"]),
                    format_money(shift["gross_pay_cents"]),
                    format_money(shift["net_pay_cents"]),
                ),
            )


def launch(database: Database) -> None:
    root = tk.Tk()
    TimesheetApp(root, database)
    root.mainloop()
