"""
Global application stylesheet and QApplication setup.
"""

from __future__ import annotations

import sys
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

APP_STYLESHEET = """
/* ======================================================
   LOQ Control Center — Global Dark Theme
   Design tokens: see implementation_plan.md
   ====================================================== */

QWidget {
    background-color: #0d0d0f;
    color: #f0f0f2;
    font-family: "Inter", "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: 13px;
}

/* Scrollbars */
QScrollBar:vertical {
    background: #0d0d0f;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #2a2a35;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #3a3a50;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

QScrollBar:horizontal {
    background: #0d0d0f;
    height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #2a2a35;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: #3a3a50;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* QMessageBox */
QMessageBox {
    background: #16161a;
}
QMessageBox QLabel {
    color: #f0f0f2;
}
QMessageBox QPushButton {
    background: #1e1e24;
    color: #f0f0f2;
    border: 1px solid #2a2a35;
    border-radius: 6px;
    padding: 6px 16px;
    min-width: 80px;
}
QMessageBox QPushButton:hover {
    background: #252530;
}
QMessageBox QPushButton:default {
    background: #e8182c;
    border-color: #e8182c;
}
QMessageBox QPushButton:default:hover {
    background: #ff2a3e;
}

/* Tooltips */
QToolTip {
    background: #1e1e24;
    color: #f0f0f2;
    border: 1px solid #3a3a50;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}

/* Dialog */
QDialog {
    background: #0d0d0f;
}

/* CheckBox */
QCheckBox {
    color: #a0a0b8;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #3a3a50;
    border-radius: 4px;
    background: #1e1e24;
}
QCheckBox::indicator:checked {
    background: #e8182c;
    border-color: #e8182c;
    image: none;
}
"""


def create_application(argv: list[str] | None = None) -> QApplication:
    """Create and configure the QApplication."""
    app = QApplication(argv or sys.argv)
    app.setApplicationName("LOQ Control Center")
    app.setApplicationDisplayName("LOQ Control Center")
    app.setOrganizationName("loq-control")
    app.setQuitOnLastWindowClosed(False)

    # Load Inter font if available (downloaded by install.sh)
    # Falls back to system sans-serif
    import importlib.resources
    from pathlib import Path
    assets_dir = Path(__file__).parent / "assets" / "fonts"
    if assets_dir.exists():
        for font_file in assets_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(font_file))

    app.setStyleSheet(APP_STYLESHEET)

    return app
