"""
MetricCard — Reusable stat card widget.
Shows an icon, title, primary value, subtitle, and a sparkline history.
Color-codes the value ring based on severity thresholds.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from loq_control.dashboard.widgets.icons import SVG_ICONS, get_pixmap
from loq_control.dashboard.widgets.sparkline import SparklineWidget

# Threshold colors
_COLOR_GOOD    = "#22c55e"
_COLOR_WARN    = "#eab308"
_COLOR_DANGER  = "#ef4444"
_COLOR_NEUTRAL = "#71717a"
_COLOR_ACCENT  = "#3b82f6"


def _threshold_color(value: float, warn: float = 60.0, danger: float = 85.0) -> str:
    if value >= danger:
        return _COLOR_DANGER
    if value >= warn:
        return _COLOR_WARN
    return _COLOR_GOOD


class MetricCard(QFrame):
    clicked = Signal()

    def __init__(
        self,
        title: str,
        icon: str = "📊",
        unit: str = "%",
        warn_threshold: float = 60.0,
        danger_threshold: float = 85.0,
        sparkline_color: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._unit = unit
        self._warn = warn_threshold
        self._danger = danger_threshold
        self._sparkline_color = sparkline_color
        self._current_value: float = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._build_ui(icon)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_value(
        self,
        primary: float | str,
        subtitle: str = "",
        push_history: float | None = None,
    ) -> None:
        """
        Update the displayed value.

        primary     : numeric value (float) or pre-formatted string
        subtitle    : secondary line below value (e.g. "12.3 / 32.0 GB")
        push_history: numeric value to push into sparkline (defaults to primary if float)
        """
        if isinstance(primary, float):
            self._current_value = primary
            display = f"{primary:.1f}{self._unit}"
            history_val = push_history if push_history is not None else primary
        else:
            display = str(primary)
            history_val = push_history or 0.0

        color = _threshold_color(self._current_value, self._warn, self._danger)

        self._value_label.setText(display)
        self._value_label.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: 700;")

        if subtitle:
            self._subtitle_label.setText(subtitle)
            self._subtitle_label.show()
        else:
            self._subtitle_label.hide()

        # Update sparkline color to track severity (unless overridden)
        if self._sparkline_color is None:
            self._sparkline.set_color(color)
        self._sparkline.push_value(history_val)

        # Status badge update (P1.3)
        if self._current_value >= self._danger:
            if "°C" in self._unit:
                badge_text = "HOT"
            elif "%" in self._unit:
                badge_text = "SATURATED"
            else:
                badge_text = "MAX"
            self._badge_label.setText(badge_text)
            self._badge_label.setStyleSheet(
                "color: #f87171; background: #450a0a; border-radius: 4px; "
                "font-size: 9px; font-weight: 700; padding: 2px 6px;"
            )
        elif self._current_value >= self._warn:
            if "°C" in self._unit:
                badge_text = "WARM"
            elif "%" in self._unit:
                badge_text = "BUSY"
            else:
                badge_text = "HIGH"
            self._badge_label.setText(badge_text)
            self._badge_label.setStyleSheet(
                "color: #fbbf24; background: #451a03; border-radius: 4px; "
                "font-size: 9px; font-weight: 700; padding: 2px 6px;"
            )
        else:
            self._badge_label.setText("NORMAL")
            self._badge_label.setStyleSheet(
                "color: #34d399; background: #064e3b; border-radius: 4px; "
                "font-size: 9px; font-weight: 700; padding: 2px 6px;"
            )

    def set_spec_details(self, model_name: str = "", meta_text: str = "") -> None:
        has_content = False
        if model_name:
            self._model_lbl.setText(model_name)
            self._model_lbl.show()
            has_content = True
        else:
            self._model_lbl.hide()

        if meta_text:
            self._meta_lbl.setText(meta_text)
            self._meta_lbl.show()
            has_content = True
        else:
            self._meta_lbl.hide()

        self._details_frame.setVisible(has_content)

    def set_history(self, data: list[float]) -> None:
        self._sparkline.set_data(data)

    def set_unavailable(self, reason: str = "Not available") -> None:
        self._value_label.setText("—")
        self._value_label.setStyleSheet(f"color: {_COLOR_NEUTRAL}; font-size: 22px; font-weight: 700;")
        self._subtitle_label.setText(reason)
        self._subtitle_label.show()

    # ------------------------------------------------------------------
    # Internal UI
    # ------------------------------------------------------------------

    def _build_ui(self, icon: str) -> None:
        self.setObjectName("MetricCard")
        self.setStyleSheet("""
            QFrame#MetricCard {
                background: #18181b;
                border: 1px solid #27272a;
                border-radius: 10px;
            }
            QFrame#MetricCard:hover {
                border: 1px solid #3f3f46;
                background: #27272a;
            }
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(6)

        # Header row: icon + title
        header = QHBoxLayout()
        header.setSpacing(8)

        icon_lbl = QLabel()
        spark_color = self._sparkline_color or _COLOR_GOOD
        if icon in SVG_ICONS:
            icon_lbl.setPixmap(get_pixmap(icon, 18, color=spark_color))
        else:
            icon_lbl.setText(icon)
            icon_lbl.setStyleSheet("font-size: 18px;")
        icon_lbl.setFixedWidth(24)
        header.addWidget(icon_lbl)

        title_lbl = QLabel(self._title.upper())
        title_lbl.setStyleSheet(
            "color: #a1a1aa; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;"
        )
        header.addWidget(title_lbl)
        header.addStretch()

        # Status badge
        self._badge_label = QLabel("NORMAL")
        self._badge_label.setStyleSheet(
            "color: #34d399; background: #064e3b; border-radius: 4px; "
            "font-size: 9px; font-weight: 700; padding: 2px 6px;"
        )
        header.addWidget(self._badge_label)
        root.addLayout(header)

        # Primary value
        self._value_label = QLabel("—")
        self._value_label.setStyleSheet(
            "color: #22c55e; font-size: 22px; font-weight: 700;"
        )
        root.addWidget(self._value_label)

        # Subtitle
        self._subtitle_label = QLabel("")
        self._subtitle_label.setStyleSheet("color: #71717a; font-size: 11px;")
        self._subtitle_label.setWordWrap(True)
        self._subtitle_label.hide()
        root.addWidget(self._subtitle_label)

        # Sparkline
        spark_color = self._sparkline_color or _COLOR_GOOD
        self._sparkline = SparklineWidget(color=spark_color, max_value=100.0)
        root.addWidget(self._sparkline)

        # Specs / Metadata Details Frame
        self._details_frame = QFrame()
        self._details_frame.setStyleSheet("""
            QFrame {
                background: #09090b;
                border: 1px solid #27272a;
                border-radius: 6px;
            }
        """)
        self._details_layout = QVBoxLayout(self._details_frame)
        self._details_layout.setContentsMargins(8, 6, 8, 6)
        self._details_layout.setSpacing(2)

        self._model_lbl = QLabel("")
        self._model_lbl.setStyleSheet("color: #3b82f6; font-size: 11px; font-weight: 600;")
        self._model_lbl.hide()
        self._details_layout.addWidget(self._model_lbl)

        self._meta_lbl = QLabel("")
        self._meta_lbl.setStyleSheet("color: #a1a1aa; font-size: 10px;")
        self._meta_lbl.setWordWrap(True)
        self._meta_lbl.hide()
        self._details_layout.addWidget(self._meta_lbl)

        self._details_frame.hide()
        root.addWidget(self._details_frame)
