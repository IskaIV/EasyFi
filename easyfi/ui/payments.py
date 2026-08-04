"""Payments page and employer amount-owed tracking."""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from tkinter import messagebox, ttk

from ..calculations import format_money, work_week_bounds
from ..database import Database, IncomeSource, PaymentSummary, PaymentToSave
from .theme import ERROR, MUTED, PANEL_BACKGROUND, PRIMARY, SOFT_GREEN, WARNING
from .widgets import DateInput, format_display_date, parse_display_date


PAY_PERIOD_OPTIONS = tuple(
    f"{weeks} {'week' if weeks == 1 else 'weeks'}" for weeks in range(1, 9)
)


class PaymentsPage(ttk.Frame):
    def __init__(self, parent: ttk.Frame, database: Database) -> None:
        super().__init__(parent, style="App.TFrame", padding=(26, 22))
        self.database = database
        self.sources_by_label: dict[str, IncomeSource] = {}
        self.editing_payment_id: int | None = None

        self.form_title_var = tk.StringVar(value="Record a payment")
        self.save_button_var = tk.StringVar(value="Add payment")
        self.paid_on_var = tk.StringVar(value=format_display_date(date.today()))
        self.source_var = tk.StringVar()
        self.week_reference_var = tk.StringVar(
            value=format_display_date(date.today())
        )
        self.pay_period_var = tk.StringVar(value=PAY_PERIOD_OPTIONS[0])
        self.week_label_var = tk.StringVar()
        self.amount_var = tk.StringVar()
        self.notes_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.balance_status_var = tk.StringVar(value="No wages recorded")
        self.opening_balance_var = tk.StringVar(value="$0.00")
        self.gross_var = tk.StringVar(value="$0.00")
        self.received_var = tk.StringVar(value="$0.00")
        self.owed_var = tk.StringVar(value="$0.00")
        self.overpaid_var = tk.StringVar(value="$0.00")

        self._build_ui()
        self._wire_updates()
        self.refresh()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        ttk.Label(header, text="Payments", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Compare gross wages earned with employer payments received.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        upper = ttk.Frame(self, style="App.TFrame")
        upper.grid(row=1, column=0, sticky="ew")
        upper.columnconfigure(0, weight=3)
        upper.columnconfigure(1, weight=2)
        self._build_payment_form(upper)
        self._build_balance_summary(upper)
        self._build_payment_history()

    def _build_payment_form(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Card.TFrame", padding=20)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        panel.columnconfigure(0, weight=1)
        panel.columnconfigure(1, weight=1)
        ttk.Label(
            panel, textvariable=self.form_title_var, style="PanelTitle.TLabel"
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 16))

        self._field_label(panel, "Date paid", 1, 0)
        self._field_label(panel, "Income source", 1, 1, left=8)
        DateInput(panel, textvariable=self.paid_on_var).grid(
            row=2, column=0, sticky="ew", padx=(0, 8)
        )
        self.source_combo = ttk.Combobox(
            panel, textvariable=self.source_var, state="readonly"
        )
        self.source_combo.grid(row=2, column=1, sticky="ew", padx=(8, 0))

        self._field_label(
            panel, "Pay period ends with week containing", 3, 0, top=15
        )
        self._field_label(panel, "Covers", 3, 1, top=15, left=8)
        week_controls = ttk.Frame(panel, style="Panel.TFrame")
        week_controls.grid(row=4, column=0, sticky="ew", padx=(0, 8))
        week_controls.columnconfigure(1, weight=1)
        ttk.Button(
            week_controls,
            text="←",
            style="Secondary.TButton",
            command=lambda: self.move_week(-1),
        ).grid(row=0, column=0, padx=(0, 8))
        DateInput(week_controls, textvariable=self.week_reference_var).grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Button(
            week_controls,
            text="→",
            style="Secondary.TButton",
            command=lambda: self.move_week(1),
        ).grid(row=0, column=2, padx=(8, 0))
        self.pay_period_combo = ttk.Combobox(
            panel,
            textvariable=self.pay_period_var,
            values=PAY_PERIOD_OPTIONS,
            state="readonly",
        )
        self.pay_period_combo.grid(row=4, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(
            panel, textvariable=self.week_label_var, style="Field.TLabel"
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self._field_label(panel, "Amount received ($)", 6, 0, top=15)
        self._field_label(panel, "Notes (optional)", 6, 1, top=15, left=8)
        ttk.Entry(panel, textvariable=self.amount_var).grid(
            row=7, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Entry(panel, textvariable=self.notes_var).grid(
            row=7, column=1, sticky="ew", padx=(8, 0)
        )

        actions = ttk.Frame(panel, style="Panel.TFrame")
        actions.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(18, 0))
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
            command=self.delete_editing_payment,
        )
        self.delete_form_button.grid(row=0, column=1, padx=(8, 8))
        ttk.Button(
            actions,
            text="Clear",
            style="Secondary.TButton",
            command=self.clear_form,
        ).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(
            actions,
            textvariable=self.save_button_var,
            style="Primary.TButton",
            command=self.save_payment,
        ).grid(row=0, column=3)

    def _build_balance_summary(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Card.TFrame", padding=20)
        panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, text="Pay-period balance", style="PanelTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self.balance_status_label = tk.Label(
            panel,
            textvariable=self.balance_status_var,
            background=SOFT_GREEN,
            foreground=PRIMARY,
            font=("Segoe UI", 11, "bold"),
            padx=10,
            pady=8,
        )
        self.balance_status_label.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(14, 12)
        )
        rows = (
            ("Previous balance", self.opening_balance_var, "Money.TLabel"),
            ("Gross wages earned", self.gross_var, "MoneyStrong.TLabel"),
            ("Employer payments", self.received_var, "Money.TLabel"),
            ("Amount owed", self.owed_var, "MoneyStrong.TLabel"),
            ("Overpaid", self.overpaid_var, "Money.TLabel"),
        )
        for row_number, (label, variable, style) in enumerate(rows, start=2):
            ttk.Label(panel, text=label, style="Money.TLabel").grid(
                row=row_number, column=0, sticky="w", pady=7
            )
            ttk.Label(panel, textvariable=variable, style=style).grid(
                row=row_number, column=1, sticky="e", pady=7
            )
        ttk.Label(
            panel,
            text="Amount owed includes the previous unpaid balance plus gross wages in this pay period, minus employer payments.",
            style="Field.TLabel",
            wraplength=280,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(16, 0))

    def _build_payment_history(self) -> None:
        panel = ttk.Frame(self, style="Card.TFrame", padding=18)
        panel.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        header = ttk.Frame(panel, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Payment history", style="PanelTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            header,
            text="Edit selected",
            style="Secondary.TButton",
            command=self.edit_selected_payment,
        ).grid(row=0, column=1, padx=(8, 8))
        ttk.Button(
            header,
            text="Delete selected",
            style="Danger.TButton",
            command=self.delete_selected_payment,
        ).grid(row=0, column=2)

        columns = ("paid_on", "source", "week", "amount", "notes")
        self.payment_table = ttk.Treeview(
            panel, columns=columns, show="headings", height=6
        )
        headings = {
            "paid_on": "Date paid",
            "source": "Income source",
            "week": "Applied pay period",
            "amount": "Amount",
            "notes": "Notes",
        }
        widths = {
            "paid_on": 100,
            "source": 180,
            "week": 210,
            "amount": 110,
            "notes": 260,
        }
        for column in columns:
            self.payment_table.heading(column, text=headings[column])
            self.payment_table.column(column, width=widths[column], anchor="w")
        self.payment_table.grid(row=1, column=0, sticky="nsew")
        self.payment_table.bind(
            "<Double-1>", lambda _event: self.edit_selected_payment()
        )

    @staticmethod
    def _field_label(
        parent: ttk.Frame,
        text: str,
        row: int,
        column: int,
        *,
        top: int = 0,
        left: int = 0,
    ) -> None:
        ttk.Label(parent, text=text, style="Field.TLabel").grid(
            row=row,
            column=column,
            sticky="w",
            padx=(left, 0),
            pady=(top, 5),
        )

    def _wire_updates(self) -> None:
        self.source_var.trace_add("write", lambda *_args: self.refresh_summary())
        self.week_reference_var.trace_add(
            "write", lambda *_args: self.refresh_summary()
        )
        self.pay_period_var.trace_add(
            "write", lambda *_args: self.refresh_summary()
        )

    def refresh(self) -> None:
        selected = self.sources_by_label.get(self.source_var.get())
        selected_id = selected.id if selected is not None else None
        sources = self.database.list_income_sources(include_inactive=True)
        self.sources_by_label = {
            f"{source.name}{' · archived' if not source.active else ''}": source
            for source in sources
        }
        labels = list(self.sources_by_label)
        self.source_combo.configure(values=labels)
        if labels:
            target = next(
                (
                    label
                    for label, source in self.sources_by_label.items()
                    if source.id == selected_id
                ),
                labels[0],
            )
            self.source_var.set(target)
        else:
            self.source_var.set("")
        self.refresh_history()
        self.refresh_summary()

    def move_week(self, direction: int) -> None:
        try:
            reference = parse_display_date(self.week_reference_var.get())
        except ValueError:
            reference = date.today()
        self.week_reference_var.set(
            format_display_date(reference + timedelta(days=7 * direction))
        )

    def refresh_summary(self) -> None:
        try:
            source = self._selected_source_from_form()
            reference = parse_display_date(self.week_reference_var.get())
            pay_period_weeks = self._selected_pay_period_weeks()
            summary = self.database.payment_summary(
                income_source_id=source.id,
                reference_date=reference,
                pay_period_weeks=pay_period_weeks,
            )
        except ValueError:
            self.week_label_var.set("Work week: —")
            self._show_empty_summary()
            return
        self._show_summary(summary)

    def _show_summary(self, summary: PaymentSummary) -> None:
        self.week_label_var.set(
            f"Pay period ({summary.pay_period_weeks} "
            f"{'week' if summary.pay_period_weeks == 1 else 'weeks'}): "
            f"{summary.week_start.strftime('%b %d')} – "
            f"{summary.week_end.strftime('%b %d, %Y')}"
        )
        self.opening_balance_var.set(format_money(summary.opening_balance_cents))
        self.gross_var.set(format_money(summary.gross_earned_cents))
        self.received_var.set(format_money(summary.payments_received_cents))
        self.owed_var.set(format_money(summary.amount_owed_cents))
        self.overpaid_var.set(format_money(summary.overpaid_cents))
        if (
            summary.opening_balance_cents == 0
            and summary.gross_earned_cents == 0
            and summary.payments_received_cents == 0
        ):
            status, color = "No wages recorded", MUTED
        elif summary.amount_owed_cents > 0:
            status, color = "Payment still owed", ERROR
        elif summary.overpaid_cents > 0:
            status, color = "Overpaid", WARNING
        else:
            status, color = "Paid in full", PRIMARY
        self.balance_status_var.set(status)
        self.balance_status_label.configure(foreground=color)

    def _show_empty_summary(self) -> None:
        self.balance_status_var.set("Complete the source and pay period")
        self.balance_status_label.configure(foreground=MUTED)
        for variable in (
            self.opening_balance_var,
            self.gross_var,
            self.received_var,
            self.owed_var,
            self.overpaid_var,
        ):
            variable.set("—")

    def _payment_from_form(self) -> PaymentToSave:
        try:
            paid_on = parse_display_date(self.paid_on_var.get())
        except ValueError as exc:
            raise ValueError("Date paid must use MM/DD/YYYY format.") from exc
        try:
            reference_date = parse_display_date(self.week_reference_var.get())
        except ValueError as exc:
            raise ValueError("Work-week date must use MM/DD/YYYY format.") from exc
        pay_period_weeks = self._selected_pay_period_weeks()
        source = self._selected_source_from_form()
        try:
            amount_cents = int(
                (Decimal(self.amount_var.get().strip()) * 100).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
        except (InvalidOperation, OverflowError, ValueError) as exc:
            raise ValueError("Enter a valid payment amount.") from exc
        return PaymentToSave(
            income_source_id=source.id,
            paid_on=paid_on,
            work_week_reference_date=reference_date,
            amount_cents=amount_cents,
            pay_period_weeks=pay_period_weeks,
            notes=self.notes_var.get(),
        )

    def _selected_source_from_form(self) -> IncomeSource:
        source = self.sources_by_label.get(self.source_var.get())
        if source is None:
            raise ValueError("Choose an income source.")
        return source

    def save_payment(self) -> None:
        try:
            payment = self._payment_from_form()
            if self.database.has_duplicate_payment(
                payment, exclude_payment_id=self.editing_payment_id
            ) and not messagebox.askyesno(
                "Possible duplicate payment",
                "A payment with the same source, pay period, date, and amount "
                "already exists. Save it anyway?",
                parent=self.winfo_toplevel(),
            ):
                self._set_status("Duplicate payment was not saved.", error=True)
                return
            if self.editing_payment_id is None:
                payment_id = self.database.save_payment(payment)
                message = f"Payment #{payment_id} saved."
            else:
                payment_id = self.editing_payment_id
                self.database.update_payment(payment_id, payment)
                message = f"Payment #{payment_id} updated."
        except (OSError, ValueError) as exc:
            self._set_status(str(exc), error=True)
            return
        self.refresh_history()
        self._reset_form(clear_status=False, preserve_context=True)
        self._set_status(message)
        self.refresh_summary()

    def clear_form(self) -> None:
        self._reset_form(clear_status=True, preserve_context=True)

    def _reset_form(self, *, clear_status: bool, preserve_context: bool) -> None:
        selected_source = self.source_var.get()
        reference_date = self.week_reference_var.get()
        self.editing_payment_id = None
        self.form_title_var.set("Record a payment")
        self.save_button_var.set("Add payment")
        self.delete_form_button.configure(state="disabled")
        self.paid_on_var.set(format_display_date(date.today()))
        self.amount_var.set("")
        self.notes_var.set("")
        if preserve_context:
            self.source_var.set(selected_source)
            self.week_reference_var.set(reference_date)
        if clear_status:
            self.status_var.set("")

    def edit_selected_payment(self) -> None:
        payment_id = self._selected_payment_id()
        if payment_id is None:
            self._set_status("Select a payment to edit.", error=True)
            return
        payment = self.database.get_payment(payment_id)
        if payment is None:
            self._set_status("The selected payment no longer exists.", error=True)
            self.refresh_history()
            return
        source_label = next(
            (
                label
                for label, source in self.sources_by_label.items()
                if source.id == payment.income_source_id
            ),
            None,
        )
        if source_label is None:
            self.refresh()
            self._set_status("The payment's income source is unavailable.", error=True)
            return
        self.editing_payment_id = payment.id
        self.form_title_var.set(f"Edit payment #{payment.id}")
        self.save_button_var.set("Save changes")
        self.delete_form_button.configure(state="normal")
        self.paid_on_var.set(format_display_date(payment.paid_on))
        self.source_var.set(source_label)
        self.week_reference_var.set(
            format_display_date(payment.work_week_reference_date)
        )
        self.pay_period_var.set(
            f"{payment.pay_period_weeks} "
            f"{'week' if payment.pay_period_weeks == 1 else 'weeks'}"
        )
        self.amount_var.set(f"{payment.amount_cents / 100:.2f}")
        self.notes_var.set(payment.notes)
        self._set_status(f"Editing payment #{payment.id}.")

    def delete_selected_payment(self) -> None:
        payment_id = self._selected_payment_id()
        if payment_id is None:
            self._set_status("Select a payment to delete.", error=True)
            return
        self._delete_payment(payment_id)

    def delete_editing_payment(self) -> None:
        if self.editing_payment_id is not None:
            self._delete_payment(self.editing_payment_id)

    def _delete_payment(self, payment_id: int) -> None:
        payment = self.database.get_payment(payment_id)
        if payment is None:
            self._set_status("The selected payment no longer exists.", error=True)
            self.refresh_history()
            return
        if not messagebox.askyesno(
            "Delete payment?",
            f"Delete the {format_money(payment.amount_cents)} payment from "
            f"{payment.paid_on.isoformat()}?",
            icon="warning",
            parent=self.winfo_toplevel(),
        ):
            return
        if not self.database.delete_payment(payment_id):
            self._set_status("The selected payment no longer exists.", error=True)
            return
        if self.editing_payment_id == payment_id:
            self._reset_form(clear_status=False, preserve_context=True)
        self.refresh_history()
        self.refresh_summary()
        self._set_status(f"Payment #{payment_id} deleted.")

    def refresh_history(self) -> None:
        for item in self.payment_table.get_children():
            self.payment_table.delete(item)
        start_weekday = self.database.get_setting_int("work_week_start", 3)
        for payment in self.database.list_payments():
            _ending_start, period_end = work_week_bounds(
                payment.work_week_start, start_weekday
            )
            period_start = payment.work_week_start - timedelta(
                days=7 * (payment.pay_period_weeks - 1)
            )
            self.payment_table.insert(
                "",
                "end",
                iid=str(payment.id),
                values=(
                    format_display_date(payment.paid_on),
                    payment.source_name,
                    f"{period_start.strftime('%b %d')} – "
                    f"{period_end.strftime('%b %d, %Y')} "
                    f"({payment.pay_period_weeks}w)",
                    format_money(payment.amount_cents),
                    payment.notes,
                ),
            )

    def _selected_payment_id(self) -> int | None:
        selection = self.payment_table.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def _selected_pay_period_weeks(self) -> int:
        try:
            weeks = int(self.pay_period_var.get().split(maxsplit=1)[0])
        except (AttributeError, ValueError) as exc:
            raise ValueError("Choose a valid pay-period length.") from exc
        if not 1 <= weeks <= 8:
            raise ValueError("Pay period must be between 1 and 8 weeks.")
        return weeks

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.configure(foreground=ERROR if error else PRIMARY)
        self.status_var.set(message)
