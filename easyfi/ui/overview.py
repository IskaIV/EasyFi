"""Weekly overview dashboard."""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk

from ..calculations import format_minutes, format_money
from ..database import Database, IncomeSource, OverviewSummary
from .theme import MUTED, PANEL_BACKGROUND, TEXT
from .widgets import DateInput, format_display_date, parse_display_date
ALL_SOURCES = "All income sources"


class OverviewPage(ttk.Frame):
    def __init__(self, parent: ttk.Frame, database: Database) -> None:
        super().__init__(parent, style="App.TFrame", padding=(26, 22))
        self.database = database
        self.sources_by_label: dict[str, IncomeSource] = {}

        self.reference_date_var = tk.StringVar(
            value=format_display_date(date.today())
        )
        self.source_var = tk.StringVar(value=ALL_SOURCES)
        self.week_label_var = tk.StringVar()
        self.hours_var = tk.StringVar(value="0h 00m")
        self.hours_context_var = tk.StringVar()
        self.gross_var = tk.StringVar(value="$0.00")
        self.gross_context_var = tk.StringVar()
        self.payments_var = tk.StringVar(value="$0.00")
        self.payments_context_var = tk.StringVar()
        self.owed_var = tk.StringVar(value="$0.00")
        self.owed_context_var = tk.StringVar()
        self.tax_var = tk.StringVar(value="$0.00")
        self.take_home_var = tk.StringVar(value="$0.00")
        self.overpaid_var = tk.StringVar(value="$0.00")

        self._build_ui()
        self._wire_updates()
        self.refresh()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        header = ttk.Frame(self, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        ttk.Label(header, text="Overview", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="A weekly view of hours, wages, payments, and employer balances.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        self._build_controls()
        self._build_metric_cards()
        self._build_financial_details()
        self._build_source_breakdown()

    def _build_controls(self) -> None:
        controls = ttk.Frame(self, style="Card.TFrame", padding=14)
        controls.grid(row=1, column=0, sticky="ew")
        controls.columnconfigure(4, weight=1)
        ttk.Button(
            controls,
            text="← Previous",
            style="Secondary.TButton",
            command=lambda: self.move_week(-1),
        ).grid(row=0, column=0)
        ttk.Button(
            controls,
            text="Today",
            style="Secondary.TButton",
            command=lambda: self.reference_date_var.set(
                format_display_date(date.today())
            ),
        ).grid(row=0, column=1, padx=8)
        ttk.Button(
            controls,
            text="Next →",
            style="Secondary.TButton",
            command=lambda: self.move_week(1),
        ).grid(row=0, column=2)
        DateInput(
            controls, textvariable=self.reference_date_var, width=12
        ).grid(
            row=0, column=3, padx=(12, 12)
        )
        ttk.Label(
            controls, textvariable=self.week_label_var, style="Field.TLabel"
        ).grid(row=0, column=4, sticky="w")
        self.source_combo = ttk.Combobox(
            controls, textvariable=self.source_var, state="readonly", width=26
        )
        self.source_combo.grid(row=0, column=5, sticky="e")

    def _build_metric_cards(self) -> None:
        metrics = ttk.Frame(self, style="App.TFrame")
        metrics.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        for column in range(4):
            metrics.columnconfigure(column, weight=1)
        self._metric_card(
            metrics,
            0,
            "Paid time",
            self.hours_var,
            self.hours_context_var,
        )
        self._metric_card(
            metrics,
            1,
            "Gross wages",
            self.gross_var,
            self.gross_context_var,
        )
        self._metric_card(
            metrics,
            2,
            "Payments this week",
            self.payments_var,
            self.payments_context_var,
        )
        self._metric_card(
            metrics,
            3,
            "Total amount owed",
            self.owed_var,
            self.owed_context_var,
        )

    @staticmethod
    def _metric_card(
        parent: ttk.Frame,
        column: int,
        title: str,
        value_var: tk.StringVar,
        context_var: tk.StringVar,
    ) -> None:
        left = 0 if column == 0 else 6
        right = 0 if column == 3 else 6
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.grid(row=0, column=column, sticky="nsew", padx=(left, right))
        ttk.Label(card, text=title, style="Field.TLabel").pack(anchor="w")
        tk.Label(
            card,
            textvariable=value_var,
            background=PANEL_BACKGROUND,
            foreground=TEXT,
            font=("Segoe UI", 19, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(7, 4))
        tk.Label(
            card,
            textvariable=context_var,
            background=PANEL_BACKGROUND,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=190,
        ).pack(fill="x")

    def _build_financial_details(self) -> None:
        panel = ttk.Frame(self, style="Card.TFrame", padding=(18, 13))
        panel.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        for column in range(3):
            panel.columnconfigure(column, weight=1)
        self._detail_value(panel, 0, "Estimated tax", self.tax_var)
        self._detail_value(panel, 1, "Estimated take-home", self.take_home_var)
        self._detail_value(panel, 2, "Total overpaid", self.overpaid_var)

    @staticmethod
    def _detail_value(
        parent: ttk.Frame, column: int, title: str, variable: tk.StringVar
    ) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 12, 0))
        ttk.Label(frame, text=title, style="Field.TLabel").pack(anchor="w")
        ttk.Label(frame, textvariable=variable, style="MoneyStrong.TLabel").pack(
            anchor="w", pady=(3, 0)
        )

    def _build_source_breakdown(self) -> None:
        panel = ttk.Frame(self, style="Card.TFrame", padding=18)
        panel.grid(row=4, column=0, sticky="nsew", pady=(16, 0))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        ttk.Label(panel, text="Income-source breakdown", style="PanelTitle.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 10)
        )
        columns = (
            "source",
            "hours",
            "regular",
            "overtime",
            "gross",
            "payments",
            "owed",
            "status",
        )
        self.breakdown_table = ttk.Treeview(
            panel, columns=columns, show="headings", height=7
        )
        headings = {
            "source": "Income source",
            "hours": "Paid time",
            "regular": "Regular",
            "overtime": "Overtime",
            "gross": "Gross (week)",
            "payments": "Paid (week)",
            "owed": "Total owed",
            "status": "Status",
        }
        widths = {
            "source": 155,
            "hours": 88,
            "regular": 80,
            "overtime": 80,
            "gross": 95,
            "payments": 95,
            "owed": 95,
            "status": 95,
        }
        for column in columns:
            self.breakdown_table.heading(column, text=headings[column])
            self.breakdown_table.column(column, width=widths[column], anchor="w")
        self.breakdown_table.grid(row=1, column=0, sticky="nsew")

    def _wire_updates(self) -> None:
        self.reference_date_var.trace_add(
            "write", lambda *_args: self.refresh_summary()
        )
        self.source_var.trace_add("write", lambda *_args: self.refresh_summary())

    def refresh(self) -> None:
        selected = self.sources_by_label.get(self.source_var.get())
        selected_id = selected.id if selected is not None else None
        sources = self.database.list_income_sources(include_inactive=True)
        self.sources_by_label = {
            f"{source.name}{' · archived' if not source.active else ''}": source
            for source in sources
        }
        values = [ALL_SOURCES, *self.sources_by_label]
        self.source_combo.configure(values=values)
        target = next(
            (
                label
                for label, source in self.sources_by_label.items()
                if source.id == selected_id
            ),
            ALL_SOURCES,
        )
        self.source_var.set(target)
        self.refresh_summary()

    def move_week(self, direction: int) -> None:
        try:
            reference = parse_display_date(self.reference_date_var.get())
        except ValueError:
            reference = date.today()
        self.reference_date_var.set(
            format_display_date(reference + timedelta(days=7 * direction))
        )

    def refresh_summary(self) -> None:
        try:
            reference = parse_display_date(self.reference_date_var.get())
        except ValueError:
            self.week_label_var.set("Work week: —")
            return
        source = self.sources_by_label.get(self.source_var.get())
        summary = self.database.overview_summary(
            reference_date=reference,
            income_source_id=source.id if source is not None else None,
        )
        self._show_summary(summary)

    def _show_summary(self, summary: OverviewSummary) -> None:
        self.week_label_var.set(
            f"{summary.week_start.strftime('%b %d')} – "
            f"{summary.week_end.strftime('%b %d, %Y')}"
        )
        self.hours_var.set(format_minutes(summary.paid_minutes))
        self.hours_context_var.set(
            f"{format_minutes(summary.regular_minutes)} regular · "
            f"{format_minutes(summary.overtime_minutes)} overtime\n"
            f"{self._minutes_comparison(summary.paid_minutes, summary.previous_paid_minutes)}"
        )
        self.gross_var.set(format_money(summary.gross_earned_cents))
        self.gross_context_var.set(
            self._money_comparison(
                summary.gross_earned_cents,
                summary.previous_gross_earned_cents,
            )
        )
        self.payments_var.set(format_money(summary.payments_received_cents))
        self.payments_context_var.set(
            "Employer deposits for pay periods ending this week"
        )
        self.owed_var.set(format_money(summary.amount_owed_cents))
        if summary.amount_owed_cents > 0:
            owed_status = "Still unpaid"
        elif summary.overpaid_cents > 0:
            owed_status = f"Overpaid by {format_money(summary.overpaid_cents)}"
        elif (
            summary.gross_earned_cents > 0
            or summary.payments_received_cents > 0
            or summary.previous_amount_owed_cents > 0
        ):
            owed_status = "Paid in full"
        else:
            owed_status = "No outstanding balance"
        self.owed_context_var.set(
            f"{owed_status} through this week\n"
            f"Previous total: {format_money(summary.previous_amount_owed_cents)}"
        )
        self.tax_var.set(format_money(summary.estimated_tax_cents))
        self.take_home_var.set(format_money(summary.estimated_take_home_cents))
        self.overpaid_var.set(format_money(summary.overpaid_cents))
        self._refresh_breakdown(summary)

    def _refresh_breakdown(self, summary: OverviewSummary) -> None:
        for item in self.breakdown_table.get_children():
            self.breakdown_table.delete(item)
        for row in summary.source_rows:
            if row.amount_owed_cents > 0:
                status = "Owed"
            elif row.overpaid_cents > 0:
                status = "Overpaid"
            elif row.gross_earned_cents > 0 or row.payments_received_cents > 0:
                status = "Paid"
            else:
                status = "Settled"
            self.breakdown_table.insert(
                "",
                "end",
                iid=str(row.income_source_id),
                values=(
                    row.source_name,
                    format_minutes(row.paid_minutes),
                    format_minutes(row.regular_minutes),
                    format_minutes(row.overtime_minutes),
                    format_money(row.gross_earned_cents),
                    format_money(row.payments_received_cents),
                    format_money(row.amount_owed_cents),
                    status,
                ),
            )

    @staticmethod
    def _minutes_comparison(current: int, previous: int) -> str:
        difference = current - previous
        if difference == 0:
            return "Same paid time as previous week"
        direction = "more" if difference > 0 else "less"
        return f"{format_minutes(abs(difference))} {direction} than previous week"

    @staticmethod
    def _money_comparison(current: int, previous: int) -> str:
        difference = current - previous
        if difference == 0:
            return "Same gross wages as previous week"
        direction = "more" if difference > 0 else "less"
        return f"{format_money(abs(difference))} {direction} than previous week"
