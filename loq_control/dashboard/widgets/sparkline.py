"""
SparklineWidget — Lightweight QPainter-based mini history graph.
No external charting library. Draws a smooth bezier line with gradient fill.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget


class SparklineWidget(QWidget):
    """
    Displays a scrolling line chart of historical values.
    
    Parameters
    ----------
    color : str
        CSS hex color for the line.
    max_value : float
        Y-axis maximum (values are clamped to [0, max_value]).
    """

    def __init__(
        self,
        color: str = "#e8182c",
        max_value: float = 100.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._max_value = max_value
        self._data: list[float] = []
        self._show_grid = True
        self._show_axis_labels = True

        self.setMinimumHeight(64)
        self.setMinimumWidth(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def set_max_value(self, val: float) -> None:
        self._max_value = max(1.0, val)
        self.update()

    def push_value(self, value: float) -> None:
        self._data.append(value)
        if len(self._data) > 120:
            self._data.pop(0)
        self.update()

    def set_data(self, data: list[float]) -> None:
        self._data = list(data)
        self.update()

    # -------------------------------------------------------------------
    # Paint
    # -------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        pad_top = 10
        pad_bot = 10
        pad_left = 6
        pad_right = 34 if self._show_axis_labels else 6

        graph_w = w - pad_left - pad_right
        graph_h = h - pad_top - pad_bot

        # Draw gridlines
        if self._show_grid:
            grid_pen = QPen(QColor("#27272a"), 1, Qt.PenStyle.DashLine)
            painter.setPen(grid_pen)
            for r in (0.25, 0.5, 0.75):
                gy = pad_top + graph_h * (1.0 - r)
                painter.drawLine(QPointF(pad_left, gy), QPointF(w - pad_right, gy))

        # Draw Y-axis labels
        if self._show_axis_labels:
            painter.setPen(QColor("#71717a"))
            font = painter.font()
            font.setPixelSize(9)
            font.setBold(True)
            painter.setFont(font)
            unit_str = "%" if self._max_value == 100.0 else ""
            max_lbl = f"{int(self._max_value)}{unit_str}"
            min_lbl = f"0{unit_str}"
            painter.drawText(QRectF(w - pad_right + 4, pad_top - 4, pad_right - 4, 12), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, max_lbl)
            painter.drawText(QRectF(w - pad_right + 4, h - pad_bot - 8, pad_right - 4, 12), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, min_lbl)

        if len(self._data) < 2:
            painter.end()
            return

        data = self._data
        n = len(data)
        step = graph_w / max(n - 1, 1)

        def _x(i: int) -> float:
            return pad_left + i * step

        def _y(v: float) -> float:
            ratio = max(0.0, min(1.0, v / self._max_value))
            return pad_top + graph_h * (1.0 - ratio)

        # Build smooth path via cubic bezier
        path = QPainterPath()
        points = [QPointF(_x(i), _y(v)) for i, v in enumerate(data)]
        path.moveTo(points[0])

        for i in range(1, len(points)):
            p0 = points[i - 1]
            p1 = points[i]
            cp1 = QPointF(p0.x() + (p1.x() - p0.x()) * 0.5, p0.y())
            cp2 = QPointF(p0.x() + (p1.x() - p0.x()) * 0.5, p1.y())
            path.cubicTo(cp1, cp2, p1)

        # Filled area under curve
        fill_path = QPainterPath(path)
        fill_path.lineTo(QPointF(points[-1].x(), h - pad_bot))
        fill_path.lineTo(QPointF(points[0].x(), h - pad_bot))
        fill_path.closeSubpath()

        grad = QLinearGradient(0, pad_top, 0, h - pad_bot)
        fill_color = QColor(self._color)
        fill_color.setAlpha(60)
        transparent = QColor(self._color)
        transparent.setAlpha(0)
        grad.setColorAt(0.0, fill_color)
        grad.setColorAt(1.0, transparent)

        painter.fillPath(fill_path, grad)

        # Line
        pen = QPen(self._color, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)

        painter.end()
