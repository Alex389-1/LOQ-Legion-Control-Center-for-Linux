"""
Processes Tab — System Task Manager process table.
Allows searching, sorting, inspecting, and terminating (End Task / Force Kill) running processes.
"""

from __future__ import annotations

import logging
import signal
import os
from typing import TYPE_CHECKING

import psutil
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QMenu
)

from loq_control.dashboard.widgets.icons import get_icon

if TYPE_CHECKING:
    from loq_control.discovery import Capabilities

log = logging.getLogger(__name__)

_ICON_CACHE: dict[str, QIcon] = {}


def get_process_icon(name: str) -> QIcon:
    """Resolve system icon for process name with caching."""
    name_lower = name.lower()
    if name_lower in _ICON_CACHE:
        return _ICON_CACHE[name_lower]

    mapping = {
        "brave": "brave-browser",
        "chrome": "google-chrome",
        "idea": "intellij-idea-ultimate-edition",
        "plasmashell": "plasma",
        "antigravity-ide": "loq-control",
        "python": "python3",
        "python3": "python3",
        "krunner": "krunner",
        "kwin_wayland": "kwin",
        "konsole": "utilities-terminal",
        "bash": "utilities-terminal",
        "zsh": "utilities-terminal",
    }
    icon_name = mapping.get(name_lower, name_lower)
    icon = QIcon.fromTheme(icon_name)

    if icon.isNull() and icon_name != name_lower:
        icon = QIcon.fromTheme(name_lower)

    if icon.isNull():
        icon = QIcon.fromTheme("application-x-executable")

    _ICON_CACHE[name_lower] = icon
    return icon


class ProcessesTab(QWidget):
    """System Task Manager processes tab."""

    def __init__(self, caps: "Capabilities", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._caps = caps
        self._sort_col = 4  # Default sort by Memory (column 4)
        self._sort_order = Qt.SortOrder.DescendingOrder
        self._build_ui()

        # Update process list periodically
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._refresh_processes)
        self._timer.start()

        # Initial populate
        QTimer.singleShot(100, self._refresh_processes)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title = QLabel("Processes & Task Manager")
        title.setStyleSheet("color: #f0f0f2; font-size: 18px; font-weight: 700;")
        header.addWidget(title)

        self._count_badge = QLabel("0 Running")
        self._count_badge.setStyleSheet(
            "color: #a1a1aa; background: #18181b; border: 1px solid #27272a; "
            "border-radius: 6px; font-size: 11px; font-weight: 600; padding: 4px 10px;"
        )
        header.addWidget(self._count_badge)
        header.addStretch()

        # Search bar
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Filter processes by name or PID…")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setFixedWidth(280)
        self._search_input.setStyleSheet("""
            QLineEdit {
                background: #18181b;
                border: 1px solid #27272a;
                border-radius: 8px;
                color: #f4f4f5;
                font-size: 12px;
                padding: 6px 12px;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
        """)
        self._search_input.textChanged.connect(self._filter_table)
        header.addWidget(self._search_input)

        # Action Buttons
        self._end_btn = QPushButton("End Task")
        self._end_btn.setStyleSheet("""
            QPushButton {
                background: #2563eb; color: white; border: none;
                border-radius: 8px; font-weight: 600; padding: 6px 16px; font-size: 12px;
            }
            QPushButton:hover { background: #1d4ed8; }
            QPushButton:disabled { background: #18181b; color: #52525b; border: 1px solid #27272a; }
        """)
        self._end_btn.setDisabled(True)
        self._end_btn.clicked.connect(self._on_end_task)
        header.addWidget(self._end_btn)

        self._kill_btn = QPushButton("Force Kill")
        self._kill_btn.setStyleSheet("""
            QPushButton {
                background: #dc2626; color: white; border: none;
                border-radius: 8px; font-weight: 600; padding: 6px 16px; font-size: 12px;
            }
            QPushButton:hover { background: #b91c1c; }
            QPushButton:disabled { background: #18181b; color: #52525b; border: 1px solid #27272a; }
        """)
        self._kill_btn.setDisabled(True)
        self._kill_btn.clicked.connect(self._on_force_kill)
        header.addWidget(self._kill_btn)

        root.addLayout(header)

        # Table Widget
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["Name", "PID", "User", "CPU %", "Memory"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        from PySide6.QtCore import QSize
        self._table.setIconSize(QSize(20, 20))
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        # Style Table
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #09090b;
                alternate-background-color: #111114;
                color: #f4f4f5;
                gridline-color: #18181b;
                border: 1px solid #27272a;
                border-radius: 10px;
                font-size: 12px;
            }
            QTableWidget::item {
                padding: 6px;
            }
            QTableWidget::item:selected {
                background-color: #1e3a8a;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #18181b;
                color: #a1a1aa;
                font-weight: 600;
                font-size: 11px;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #27272a;
            }
            QHeaderView::section:hover {
                background-color: #27272a;
                color: #f4f4f5;
            }
        """)

        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSortIndicatorShown(True)
        header_view.sectionClicked.connect(self._on_header_clicked)

        root.addWidget(self._table)

    def _refresh_processes(self) -> None:
        """Fetch running processes and update table without losing selection."""
        selected_pid = self._get_selected_pid()

        procs = []
        for p in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_info']):
            try:
                info = p.info
                mem_mb = (info['memory_info'].rss / 1024 / 1024) if info['memory_info'] else 0.0
                procs.append({
                    'pid': info['pid'],
                    'name': info['name'] or f"pid_{info['pid']}",
                    'user': info['username'] or '—',
                    'cpu': info['cpu_percent'] or 0.0,
                    'memory_mb': mem_mb,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        # Sort
        if self._sort_col == 0:
            procs.sort(key=lambda x: x['name'].lower(), reverse=(self._sort_order == Qt.SortOrder.DescendingOrder))
        elif self._sort_col == 1:
            procs.sort(key=lambda x: x['pid'], reverse=(self._sort_order == Qt.SortOrder.DescendingOrder))
        elif self._sort_col == 2:
            procs.sort(key=lambda x: x['user'], reverse=(self._sort_order == Qt.SortOrder.DescendingOrder))
        elif self._sort_col == 3:
            procs.sort(key=lambda x: x['cpu'], reverse=(self._sort_order == Qt.SortOrder.DescendingOrder))
        elif self._sort_col == 4:
            procs.sort(key=lambda x: x['memory_mb'], reverse=(self._sort_order == Qt.SortOrder.DescendingOrder))

        filter_text = self._search_input.text().strip().lower()

        self._table.setRowCount(0)
        row = 0
        target_row = -1

        for proc in procs:
            if filter_text:
                if filter_text not in proc['name'].lower() and filter_text not in str(proc['pid']):
                    continue

            self._table.insertRow(row)

            # Name with application logo / icon
            item_name = QTableWidgetItem(get_process_icon(proc['name']), proc['name'])
            item_name.setData(Qt.ItemDataRole.UserRole, proc['pid'])

            # PID
            item_pid = QTableWidgetItem(str(proc['pid']))
            item_pid.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            # User
            user_str = proc['user'].split('\\')[-1] if '\\' in proc['user'] else proc['user']
            item_user = QTableWidgetItem(user_str)

            # CPU
            item_cpu = QTableWidgetItem(f"{proc['cpu']:.1f}%")
            item_cpu.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if proc['cpu'] > 10.0:
                item_cpu.setForeground(QColor("#f59e0b"))
            if proc['cpu'] > 50.0:
                item_cpu.setForeground(QColor("#ef4444"))

            # Memory
            if proc['memory_mb'] >= 1024:
                mem_str = f"{proc['memory_mb'] / 1024:.2f} GiB"
            else:
                mem_str = f"{proc['memory_mb']:.1f} MiB"
            item_mem = QTableWidgetItem(mem_str)
            item_mem.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self._table.setItem(row, 0, item_name)
            self._table.setItem(row, 1, item_pid)
            self._table.setItem(row, 2, item_user)
            self._table.setItem(row, 3, item_cpu)
            self._table.setItem(row, 4, item_mem)

            if proc['pid'] == selected_pid:
                target_row = row

            row += 1

        self._count_badge.setText(f"{len(procs)} Running")

        if target_row >= 0:
            self._table.selectRow(target_row)

    def _filter_table(self) -> None:
        self._refresh_processes()

    def _on_header_clicked(self, logical_index: int) -> None:
        if self._sort_col == logical_index:
            self._sort_order = (
                Qt.SortOrder.AscendingOrder
                if self._sort_order == Qt.SortOrder.DescendingOrder
                else Qt.SortOrder.DescendingOrder
            )
        else:
            self._sort_col = logical_index
            self._sort_order = Qt.SortOrder.DescendingOrder

        self._table.horizontalHeader().setSortIndicator(self._sort_col, self._sort_order)
        self._refresh_processes()

    def _on_selection_changed(self) -> None:
        has_sel = len(self._table.selectedItems()) > 0
        self._end_btn.setEnabled(has_sel)
        self._kill_btn.setEnabled(has_sel)

    def _get_selected_pid(self) -> int | None:
        sel = self._table.selectedItems()
        if not sel:
            return None
        row = sel[0].row()
        item = self._table.item(row, 0)
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def _get_selected_name(self) -> str:
        sel = self._table.selectedItems()
        if not sel:
            return "process"
        row = sel[0].row()
        item = self._table.item(row, 0)
        return item.text() if item else "process"

    def _on_end_task(self) -> None:
        pid = self._get_selected_pid()
        name = self._get_selected_name()
        if pid is None:
            return

        res = QMessageBox.question(
            self,
            "Confirm End Task",
            f"Are you sure you want to end task '{name}' (PID: {pid})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if res == QMessageBox.StandardButton.Yes:
            self._kill_pid(pid, sig=signal.SIGTERM)

    def _on_force_kill(self) -> None:
        pid = self._get_selected_pid()
        name = self._get_selected_name()
        if pid is None:
            return

        res = QMessageBox.question(
            self,
            "Confirm Force Kill",
            f"Are you sure you want to FORCE KILL '{name}' (PID: {pid})?\nUnsaved work may be lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if res == QMessageBox.StandardButton.Yes:
            self._kill_pid(pid, sig=signal.SIGKILL)

    def _kill_pid(self, pid: int, sig: int = signal.SIGTERM) -> None:
        try:
            p = psutil.Process(pid)
            p.send_signal(sig)
            QTimer.singleShot(300, self._refresh_processes)
        except psutil.NoSuchProcess:
            self._refresh_processes()
        except psutil.AccessDenied:
            # Try pkexec kill
            sig_flag = "-9" if sig == signal.SIGKILL else "-15"
            try:
                import subprocess
                subprocess.run(["pkexec", "kill", sig_flag, str(pid)], capture_output=True)
                QTimer.singleShot(300, self._refresh_processes)
            except Exception as exc:
                QMessageBox.critical(self, "Error", f"Failed to terminate process (Access Denied):\n{exc}")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to terminate process:\n{exc}")

    def _show_context_menu(self, pos) -> None:
        item = self._table.itemAt(pos)
        if not item:
            return
        self._table.selectRow(item.row())
        pid = self._get_selected_pid()
        name = self._get_selected_name()
        if pid is None:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #18181b; color: #f4f4f5; border: 1px solid #27272a;
                border-radius: 8px; padding: 4px;
            }
            QMenu::item {
                padding: 6px 16px; border-radius: 4px; font-size: 12px;
            }
            QMenu::item:selected {
                background: #2563eb; color: white;
            }
        """)

        end_action = menu.addAction(f"End Task ({name})")
        kill_action = menu.addAction(f"Force Kill ({name})")
        menu.addSeparator()
        copy_pid = menu.addAction("Copy PID")

        action = menu.exec_(self._table.viewport().mapToGlobal(pos))
        if action == end_action:
            self._on_end_task()
        elif action == kill_action:
            self._on_force_kill()
        elif action == copy_pid:
            QApplication.clipboard().setText(str(pid))
