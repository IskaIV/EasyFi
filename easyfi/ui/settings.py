"""Settings page for work defaults and income-source management."""

from __future__ import annotations

import tkinter as tk
import sqlite3
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..calculations import format_money, parse_clock_time
from ..database import Database, IncomeSource


WINDOW_BACKGROUND = "#F4F7F5"
PANEL_BACKGROUND = "#FFFFFF"
PRIMARY = "#17643C"
TEXT = "#17211B"
MUTED = "#627068"
SOFT_GREEN = "#EEF6F0"
ERROR = "#A53A3A"

WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


class SettingsPage(ttk.Frame):
    def __init__(
        self,
        parent: ttk.Frame,
        database: Database,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent, style="App.TFrame", padding=(26, 22))
        self.database = database
        self.on_change = on_change
        self.sources_by_id: dict[int, IncomeSource] = {}
        self.editing_source_id: int | None = None

        self.week_start_var = tk.StringVar()
        self.default_clock_in_var = tk.StringVar()
        self.default_clock_out_var = tk.StringVar()
        self.default_break_var = tk.StringVar()
        self.source_name_var = tk.StringVar()
        self.source_rate_var = tk.StringVar()
        self.source_tax_var = tk.StringVar()
        self.source_overtime_hours_var = tk.StringVar()
        self.source_overtime_multiplier_var = tk.StringVar()
        self.source_form_title_var = tk.StringVar(value="Income source")
        self.archive_button_var = tk.StringVar(value="Archive selected")
        self.status_var = tk.StringVar()
        self.automatic_backups_var = tk.BooleanVar(value=True)
        self.backup_keep_count_var = tk.StringVar(value="10")
        self.data_status_var = tk.StringVar()
        self.database_location_var = tk.StringVar(value=str(self.database.path))
        self.last_backup_var = tk.StringVar()

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        header = ttk.Frame(self, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        ttk.Label(header, text="Settings", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Customize new shifts and manage where your income comes from.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        self._build_defaults_panel()
        self._build_data_safety_panel()
        self._build_sources_panel()

    def _build_defaults_panel(self) -> None:
        panel = ttk.Frame(self, style="Panel.TFrame", padding=18)
        panel.grid(row=1, column=0, sticky="ew")
        for column in range(5):
            panel.columnconfigure(column, weight=1 if column < 4 else 0)

        ttk.Label(panel, text="Timesheet defaults", style="PanelTitle.TLabel").grid(
            row=0, column=0, columnspan=5, sticky="w", pady=(0, 14)
        )
        self._field_label(panel, "Work week starts", 1, 0)
        week_combo = ttk.Combobox(
            panel,
            textvariable=self.week_start_var,
            values=WEEKDAYS,
            state="readonly",
        )
        week_combo.grid(row=2, column=0, sticky="ew", padx=(0, 8))

        self._field_label(panel, "Default clock in", 1, 1)
        ttk.Entry(panel, textvariable=self.default_clock_in_var).grid(
            row=2, column=1, sticky="ew", padx=8
        )
        self._field_label(panel, "Default clock out", 1, 2)
        ttk.Entry(panel, textvariable=self.default_clock_out_var).grid(
            row=2, column=2, sticky="ew", padx=8
        )
        self._field_label(panel, "Default unpaid break", 1, 3)
        break_frame = ttk.Frame(panel, style="Panel.TFrame")
        break_frame.grid(row=2, column=3, sticky="ew", padx=8)
        break_frame.columnconfigure(0, weight=1)
        ttk.Entry(break_frame, textvariable=self.default_break_var).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Label(break_frame, text=" min", style="Field.TLabel").grid(
            row=0, column=1
        )
        ttk.Button(
            panel,
            text="Save defaults",
            style="Primary.TButton",
            command=self.save_defaults,
        ).grid(row=2, column=4, sticky="e", padx=(12, 0))
        ttk.Label(
            panel,
            text="Changing the work-week start recalculates overtime grouping for saved shifts.",
            style="Field.TLabel",
        ).grid(row=3, column=0, columnspan=5, sticky="w", pady=(10, 0))

    def _build_data_safety_panel(self) -> None:
        panel = ttk.Frame(self, style="Panel.TFrame", padding=18)
        panel.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        panel.columnconfigure(0, weight=1)

        ttk.Label(panel, text="Data safety", style="PanelTitle.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 10)
        )
        backup_options = ttk.Frame(panel, style="Panel.TFrame")
        backup_options.grid(row=0, column=1, sticky="e", pady=(0, 10))
        ttk.Checkbutton(
            backup_options,
            text="Automatic daily backups",
            variable=self.automatic_backups_var,
        ).pack(side="left")
        ttk.Label(backup_options, text="Keep", style="Field.TLabel").pack(
            side="left", padx=(14, 5)
        )
        ttk.Entry(
            backup_options, textvariable=self.backup_keep_count_var, width=5
        ).pack(side="left")
        ttk.Label(backup_options, text="copies", style="Field.TLabel").pack(
            side="left", padx=(5, 10)
        )
        ttk.Button(
            backup_options,
            text="Save safety settings",
            style="Secondary.TButton",
            command=self.save_safety_settings,
        ).pack(side="left")

        actions = ttk.Frame(panel, style="Panel.TFrame")
        actions.grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Button(
            actions,
            text="Backup now",
            style="Primary.TButton",
            command=self.backup_now,
        ).pack(side="left")
        ttk.Button(
            actions,
            text="Restore backup",
            style="Danger.TButton",
            command=self.restore_backup,
        ).pack(side="left", padx=8)
        ttk.Button(
            actions,
            text="Export CSV",
            style="Secondary.TButton",
            command=self.export_csv,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            actions,
            text="Check integrity",
            style="Secondary.TButton",
            command=self.check_integrity,
        ).pack(side="left")

        details = ttk.Frame(panel, style="Panel.TFrame")
        details.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(9, 0))
        details.columnconfigure(0, weight=1)
        tk.Label(
            details,
            textvariable=self.database_location_var,
            background=PANEL_BACKGROUND,
            foreground=MUTED,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        ttk.Label(
            details, textvariable=self.last_backup_var, style="Field.TLabel"
        ).grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.data_status_label = tk.Label(
            details,
            textvariable=self.data_status_var,
            background=PANEL_BACKGROUND,
            foreground=PRIMARY,
            anchor="w",
        )
        self.data_status_label.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )

    def _build_sources_panel(self) -> None:
        panel = ttk.Frame(self, style="Panel.TFrame", padding=18)
        panel.grid(row=3, column=0, sticky="nsew", pady=(18, 0))
        panel.columnconfigure(0, weight=3)
        panel.columnconfigure(1, weight=2)
        panel.rowconfigure(1, weight=1)

        header = ttk.Frame(panel, style="Panel.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Income sources", style="PanelTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            header,
            text="Add new",
            style="Secondary.TButton",
            command=self.start_new_source,
        ).grid(row=0, column=1, padx=(8, 8))
        ttk.Button(
            header,
            text="Edit selected",
            style="Secondary.TButton",
            command=self.edit_selected_source,
        ).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(
            header,
            textvariable=self.archive_button_var,
            style="Danger.TButton",
            command=self.toggle_selected_source,
        ).grid(row=0, column=3)

        columns = ("name", "rate", "tax", "overtime", "status")
        self.source_table = ttk.Treeview(
            panel, columns=columns, show="headings", height=7
        )
        headings = {
            "name": "Name",
            "rate": "Rate",
            "tax": "Tax estimate",
            "overtime": "Overtime",
            "status": "Status",
        }
        widths = {
            "name": 155,
            "rate": 85,
            "tax": 90,
            "overtime": 145,
            "status": 70,
        }
        for column in columns:
            self.source_table.heading(column, text=headings[column])
            self.source_table.column(column, width=widths[column], anchor="w")
        self.source_table.tag_configure("inactive", foreground=MUTED)
        self.source_table.grid(row=1, column=0, sticky="nsew", padx=(0, 18))
        self.source_table.bind(
            "<<TreeviewSelect>>", lambda _event: self._selection_changed()
        )
        self.source_table.bind(
            "<Double-1>", lambda _event: self.edit_selected_source()
        )

        editor = ttk.Frame(panel, style="Panel.TFrame")
        editor.grid(row=1, column=1, sticky="nsew")
        editor.columnconfigure(0, weight=1)
        editor.columnconfigure(1, weight=1)
        ttk.Label(
            editor,
            textvariable=self.source_form_title_var,
            style="PanelTitle.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self._field_label(editor, "Name", 1, 0, columnspan=2)
        ttk.Entry(editor, textvariable=self.source_name_var).grid(
            row=2, column=0, columnspan=2, sticky="ew"
        )
        self._field_label(editor, "Hourly rate ($)", 3, 0, top=12)
        self._field_label(editor, "Estimated tax (%)", 3, 1, top=12)
        ttk.Entry(editor, textvariable=self.source_rate_var).grid(
            row=4, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Entry(editor, textvariable=self.source_tax_var).grid(
            row=4, column=1, sticky="ew", padx=(6, 0)
        )
        self._field_label(editor, "Overtime after (hours)", 5, 0, top=12)
        self._field_label(editor, "Overtime multiplier", 5, 1, top=12)
        ttk.Entry(editor, textvariable=self.source_overtime_hours_var).grid(
            row=6, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Entry(editor, textvariable=self.source_overtime_multiplier_var).grid(
            row=6, column=1, sticky="ew", padx=(6, 0)
        )

        ttk.Label(
            editor,
            text="Rate and overtime changes apply to new shifts; saved shifts keep their original values.",
            style="Field.TLabel",
            wraplength=300,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(12, 0))

        actions = ttk.Frame(editor, style="Panel.TFrame")
        actions.grid(row=8, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(
            actions,
            text="Cancel",
            style="Secondary.TButton",
            command=self.cancel_source_edit,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            actions,
            text="Save source",
            style="Primary.TButton",
            command=self.save_source,
        ).pack(side="left")

        self.status_label = tk.Label(
            panel,
            textvariable=self.status_var,
            background=PANEL_BACKGROUND,
            foreground=PRIMARY,
            anchor="w",
        )
        self.status_label.grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0)
        )

    @staticmethod
    def _field_label(
        parent: ttk.Frame,
        text: str,
        row: int,
        column: int,
        *,
        columnspan: int = 1,
        top: int = 0,
    ) -> None:
        ttk.Label(parent, text=text, style="Field.TLabel").grid(
            row=row,
            column=column,
            columnspan=columnspan,
            sticky="w",
            pady=(top, 5),
        )

    def refresh(self) -> None:
        week_start = self.database.get_setting_int("work_week_start", 3)
        self.week_start_var.set(WEEKDAYS[week_start] if 0 <= week_start <= 6 else "Thursday")
        self.default_clock_in_var.set(
            self.database.get_setting("default_clock_in", "08:30")
        )
        self.default_clock_out_var.set(
            self.database.get_setting("default_clock_out", "17:00")
        )
        self.default_break_var.set(
            self.database.get_setting("default_break_minutes", "30")
        )
        self.automatic_backups_var.set(
            self.database.get_setting_int("automatic_backups_enabled", 1) == 1
        )
        self.backup_keep_count_var.set(
            self.database.get_setting("automatic_backup_keep_count", "10")
        )
        self.database_location_var.set(f"Database: {self.database.path}")
        last_backup = self.database.get_setting("last_automatic_backup", "")
        self.last_backup_var.set(
            f"Last automatic backup: {last_backup}"
            if last_backup
            else "No automatic backup created yet"
        )
        self.refresh_sources()

    def refresh_sources(self, select_id: int | None = None) -> None:
        sources = self.database.list_income_sources(include_inactive=True)
        self.sources_by_id = {source.id: source for source in sources}
        for item in self.source_table.get_children():
            self.source_table.delete(item)
        for source in sources:
            threshold_hours = Decimal(source.overtime_after_minutes) / Decimal(60)
            threshold_text = self._decimal_text(threshold_hours)
            multiplier = Decimal(source.overtime_multiplier_milli) / Decimal(1000)
            self.source_table.insert(
                "",
                "end",
                iid=str(source.id),
                values=(
                    source.name,
                    f"{format_money(source.hourly_rate_cents)}/hr",
                    f"{source.tax_rate_bps / 100:g}%",
                    f"{threshold_text}h at {self._decimal_text(multiplier)}×",
                    "Active" if source.active else "Archived",
                ),
                tags=() if source.active else ("inactive",),
            )
        target = select_id if select_id in self.sources_by_id else None
        if target is not None:
            self.source_table.selection_set(str(target))
            self.source_table.focus(str(target))
            self.source_table.see(str(target))
        self._selection_changed()

    def save_defaults(self) -> None:
        try:
            start_day = WEEKDAYS.index(self.week_start_var.get())
            clock_in = self._normalize_time(self.default_clock_in_var.get())
            clock_out = self._normalize_time(self.default_clock_out_var.get())
            break_minutes = int(self.default_break_var.get().strip())
            if not 0 <= break_minutes <= 24 * 60:
                raise ValueError
        except (ValueError, TypeError):
            self._set_status(
                "Use valid times and a default break between 0 and 1,440 minutes.",
                error=True,
            )
            return
        self.database.update_settings(
            {
                "work_week_start": str(start_day),
                "default_clock_in": clock_in,
                "default_clock_out": clock_out,
                "default_break_minutes": str(break_minutes),
            }
        )
        self.default_clock_in_var.set(clock_in)
        self.default_clock_out_var.set(clock_out)
        self.default_break_var.set(str(break_minutes))
        self._set_status("Timesheet defaults saved.")
        self.on_change()

    def save_safety_settings(self) -> None:
        try:
            keep_count = int(self.backup_keep_count_var.get().strip())
            if not 1 <= keep_count <= 100:
                raise ValueError
        except ValueError:
            self._set_data_status(
                "Backup retention must be between 1 and 100 copies.", error=True
            )
            return
        self.database.update_settings(
            {
                "automatic_backups_enabled": (
                    "1" if self.automatic_backups_var.get() else "0"
                ),
                "automatic_backup_keep_count": str(keep_count),
            }
        )
        self.backup_keep_count_var.set(str(keep_count))
        self._set_data_status("Automatic-backup settings saved.")

    def backup_now(self) -> None:
        backup_directory = self.database.automatic_backup_directory()
        backup_directory.mkdir(parents=True, exist_ok=True)
        destination = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(),
            title="Save EasyFi backup",
            initialdir=str(backup_directory),
            initialfile=f"easyfi-manual-{date.today().isoformat()}.db",
            defaultextension=".db",
            filetypes=(("EasyFi database", "*.db"), ("All files", "*.*")),
        )
        if not destination:
            return
        try:
            saved = self.database.backup_to(Path(destination))
        except (OSError, sqlite3.Error, ValueError) as exc:
            self._set_data_status(str(exc), error=True)
            return
        self._set_data_status(f"Verified backup saved: {saved}")

    def restore_backup(self) -> None:
        source = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title="Choose an EasyFi backup",
            initialdir=str(self.database.automatic_backup_directory()),
            filetypes=(("EasyFi database", "*.db"), ("All files", "*.*")),
        )
        if not source:
            return
        valid, result = self.database.integrity_check(Path(source))
        if not valid:
            self._set_data_status(f"Restore rejected: {result}", error=True)
            return
        if not messagebox.askyesno(
            "Restore EasyFi backup?",
            "Restoring replaces the current EasyFi data. A verified recovery "
            "copy of the current database will be created first. Continue?",
            icon="warning",
            parent=self.winfo_toplevel(),
        ):
            return
        try:
            safety_backup = self.database.restore_from(Path(source))
        except (OSError, sqlite3.Error, ValueError) as exc:
            self._set_data_status(str(exc), error=True)
            return
        self.on_change()
        self.refresh()
        self._set_data_status(
            f"Backup restored. Previous data preserved at: {safety_backup}"
        )

    def export_csv(self) -> None:
        destination = filedialog.askdirectory(
            parent=self.winfo_toplevel(),
            title="Choose a folder for the EasyFi CSV export",
        )
        if not destination:
            return
        try:
            export_directory = self.database.export_csv(Path(destination))
        except (OSError, sqlite3.Error, ValueError) as exc:
            self._set_data_status(str(exc), error=True)
            return
        self._set_data_status(f"CSV export created: {export_directory}")

    def check_integrity(self) -> None:
        valid, result = self.database.integrity_check()
        self._set_data_status(result, error=not valid)

    def start_new_source(self) -> None:
        self.editing_source_id = None
        self.source_form_title_var.set("Add income source")
        self.source_name_var.set("")
        self.source_rate_var.set("")
        self.source_tax_var.set("0")
        self.source_overtime_hours_var.set("40")
        self.source_overtime_multiplier_var.set("1.5")
        self._set_status("Enter the new income source details.")

    def edit_selected_source(self) -> None:
        source = self._selected_source()
        if source is None:
            self._set_status("Select an income source to edit.", error=True)
            return
        self.editing_source_id = source.id
        self.source_form_title_var.set(f"Edit {source.name}")
        self.source_name_var.set(source.name)
        self.source_rate_var.set(f"{source.hourly_rate_cents / 100:.2f}")
        self.source_tax_var.set(f"{source.tax_rate_bps / 100:.2f}")
        self.source_overtime_hours_var.set(
            self._decimal_text(Decimal(source.overtime_after_minutes) / Decimal(60))
        )
        self.source_overtime_multiplier_var.set(
            self._decimal_text(
                Decimal(source.overtime_multiplier_milli) / Decimal(1000)
            )
        )
        self._set_status(f"Editing {source.name}.")

    def cancel_source_edit(self) -> None:
        self.editing_source_id = None
        self.source_form_title_var.set("Income source")
        self.source_name_var.set("")
        self.source_rate_var.set("")
        self.source_tax_var.set("")
        self.source_overtime_hours_var.set("")
        self.source_overtime_multiplier_var.set("")
        self._set_status("")

    def save_source(self) -> None:
        try:
            hourly_rate_cents = self._scaled_decimal(
                self.source_rate_var.get(), 100
            )
            tax_rate_bps = self._scaled_decimal(self.source_tax_var.get(), 100)
            overtime_after_minutes = self._scaled_decimal(
                self.source_overtime_hours_var.get(), 60
            )
            overtime_multiplier_milli = self._scaled_decimal(
                self.source_overtime_multiplier_var.get(), 1000
            )
            values = {
                "name": self.source_name_var.get(),
                "hourly_rate_cents": hourly_rate_cents,
                "tax_rate_bps": tax_rate_bps,
                "overtime_after_minutes": overtime_after_minutes,
                "overtime_multiplier_milli": overtime_multiplier_milli,
            }
            if self.editing_source_id is None:
                source_id = self.database.add_income_source(**values)
                message = "Income source added."
            else:
                source_id = self.editing_source_id
                self.database.update_income_source(source_id, **values)
                message = "Income source updated."
        except (InvalidOperation, ValueError) as exc:
            message_text = str(exc) or "Enter valid income source values."
            self._set_status(message_text, error=True)
            return

        self.editing_source_id = source_id
        self.refresh_sources(select_id=source_id)
        self.edit_selected_source()
        self._set_status(message)
        self.on_change()

    def toggle_selected_source(self) -> None:
        source = self._selected_source()
        if source is None:
            self._set_status("Select an income source first.", error=True)
            return
        activating = not source.active
        action = "restore" if activating else "archive"
        if not activating and not messagebox.askyesno(
            "Archive income source?",
            f"Archive {source.name}? Existing shifts will remain unchanged.",
            icon="warning",
            parent=self.winfo_toplevel(),
        ):
            return
        try:
            self.database.set_income_source_active(source.id, activating)
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return
        self.refresh_sources(select_id=source.id)
        self._set_status(f"{source.name} {action}d.")
        self.on_change()

    def _selection_changed(self) -> None:
        source = self._selected_source()
        self.archive_button_var.set(
            "Restore selected"
            if source is not None and not source.active
            else "Archive selected"
        )

    def _selected_source(self) -> IncomeSource | None:
        selection = self.source_table.selection()
        if not selection:
            return None
        try:
            return self.sources_by_id.get(int(selection[0]))
        except ValueError:
            return None

    @staticmethod
    def _normalize_time(value: str) -> str:
        total = parse_clock_time(value)
        hours, minutes = divmod(total, 60)
        return f"{hours:02d}:{minutes:02d}"

    @staticmethod
    def _scaled_decimal(value: str, scale: int) -> int:
        try:
            result = (Decimal(value.strip()) * scale).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
            return int(result)
        except (InvalidOperation, OverflowError, ValueError) as exc:
            raise ValueError("Enter valid numeric values.") from exc

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        return format(value.normalize(), "f")

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.configure(foreground=ERROR if error else PRIMARY)
        self.status_var.set(message)

    def _set_data_status(self, message: str, *, error: bool = False) -> None:
        self.data_status_label.configure(foreground=ERROR if error else PRIMARY)
        self.data_status_var.set(message)
