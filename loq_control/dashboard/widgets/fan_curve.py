"""
FanCurveWidget — Interactive fan curve editor.
Drag-handle graph where users define temperature→fan speed% points.
Uses QPainter for rendering; emits curve_changed when points are moved.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFont, QLinearGradient, QPainter, QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

TEMP_MIN = 30
TEMP_MAX = 100
PWM_MIN = 0
PWM_MAX = 100
HANDLE_RADIUS = 7
SAFE_PWM_MIN = 20
SAFE_TEMP_THRESHOLD = 80


@dataclass
class CurvePoint:
    temp: int
    pwm: int


class FanCurveWidget(QWidget):
    """
    Interactive fan curve editor widget.
    
    Emits:
        curve_changed(list[CurvePoint]) — whenever a point is dragged.
    """

    curve_changed = Signal(list)

    def __init__(self, fan_id: int = 1, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fan_id = fan_id
        self._points: list[CurvePoint] = [
            CurvePoint(40, 20),
            CurvePoint(55, 35),
            CurvePoint(65, 50),
            CurvePoint(75, 70),
            CurvePoint(85, 90),
            CurvePoint(95, 100),
        ]
        self._dragging: int | None = None  # index of dragged point
        self._current_rpm: int = 0
        self._current_temp: float = 0.0

        self.setMinimumSize(300, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_points(self, points: list[CurvePoint]) -> None:
        self._points = sorted(points, key=lambda p: p.temp)
        self.update()

    def get_points(self) -> list[CurvePoint]:
        return sorted(self._points, key=lambda p: p.temp)

    def set_current_stats(self, temp: float, rpm: int) -> None:
        self._current_temp = temp
        self._current_rpm = rpm
        self.update()

    # ------------------------------------------------------------------
    # Coordinate mapping
    # ------------------------------------------------------------------

    def _margins(self) -> tuple[int, int, int, int]:
        return 50, 16, 16, 40  # left, top, right, bottom

    def _plot_rect(self) -> QRectF:
        ml, mt, mr, mb = self._margins()
        return QRectF(ml, mt, self.width() - ml - mr, self.height() - mt - mb)

    def _to_screen(self, temp: float, pwm: float) -> QPointF:
        r = self._plot_rect()
        x = r.left() + (temp - TEMP_MIN) / (TEMP_MAX - TEMP_MIN) * r.width()
        y = r.bottom() - (pwm - PWM_MIN) / (PWM_MAX - PWM_MIN) * r.height()
        return QPointF(x, y)

    def _from_screen(self, sx: float, sy: float) -> tuple[int, int]:
        r = self._plot_rect()
        temp = TEMP_MIN + (sx - r.left()) / r.width() * (TEMP_MAX - TEMP_MIN)
        pwm  = PWM_MIN  + (r.bottom() - sy) / r.height() * (PWM_MAX - PWM_MIN)
        temp = int(max(TEMP_MIN, min(TEMP_MAX, round(temp))))
        pwm  = int(max(PWM_MIN, min(PWM_MAX, round(pwm))))
        return temp, pwm

    def _hit_test(self, px: float, py: float) -> int | None:
        for i, pt in enumerate(self._points):
            sp = self._to_screen(pt.temp, pt.pwm)
            dist = math.hypot(sp.x() - px, sp.y() - py)
            if dist <= HANDLE_RADIUS + 4:
                return i
        return None

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._hit_test(event.position().x(), event.position().y())
            if idx is not None:
                self._dragging = idx
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        elif event.button() == Qt.MouseButton.RightButton:
            # Right-click on handle = delete (if > 2 points)
            idx = self._hit_test(event.position().x(), event.position().y())
            if idx is not None and len(self._points) > 2:
                self._points.pop(idx)
                self.curve_changed.emit(self.get_points())
                self.update()
        elif event.button() == Qt.MouseButton.MiddleButton:
            # Middle-click in empty space = add point
            t, p = self._from_screen(event.position().x(), event.position().y())
            self._points.append(CurvePoint(t, p))
            self._points.sort(key=lambda pt: pt.temp)
            self.curve_changed.emit(self.get_points())
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if self._dragging is not None:
            t, p = self._from_screen(pos.x(), pos.y())
            # Apply safety guard
            if t >= SAFE_TEMP_THRESHOLD and p < SAFE_PWM_MIN:
                p = SAFE_PWM_MIN
            self._points[self._dragging] = CurvePoint(t, p)
            self._points.sort(key=lambda pt: pt.temp)
            # Re-find dragged index after sort
            new_idx = next(
                (i for i, pt in enumerate(self._points)
                 if pt.temp == t and pt.pwm == p), self._dragging
            )
            self._dragging = new_idx
            self.curve_changed.emit(self.get_points())
            self.update()
            # Tooltip
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"Temp: {t}°C  Fan: {p}%",
                self,
            )
        else:
            idx = self._hit_test(pos.x(), pos.y())
            self.setCursor(
                QCursor(Qt.CursorShape.OpenHandCursor if idx is not None
                        else Qt.CursorShape.ArrowCursor)
            )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._dragging = None
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        """Double-click in empty area adds a point."""
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._hit_test(event.position().x(), event.position().y())
            if idx is None:
                t, p = self._from_screen(event.position().x(), event.position().y())
                self._points.append(CurvePoint(t, p))
                self._points.sort(key=lambda pt: pt.temp)
                self.curve_changed.emit(self.get_points())
                self.update()

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        r = self._plot_rect()
        bg_color = QColor("#16161a")
        grid_color = QColor("#2a2a35")
        label_color = QColor("#8888a0")
        safe_zone_color = QColor(239, 68, 68, 20)

        # Background
        painter.fillRect(self.rect(), QColor("#0d0d0f"))
        painter.fillRect(r.toRect(), bg_color)

        # Safety zone overlay (temp > 80°C, pwm < 20%)
        safe_x = self._to_screen(SAFE_TEMP_THRESHOLD, PWM_MAX).x()
        safe_y = self._to_screen(TEMP_MIN, SAFE_PWM_MIN).y()
        danger_rect = QRectF(safe_x, safe_y, r.right() - safe_x, r.bottom() - safe_y)
        painter.fillRect(danger_rect, safe_zone_color)

        # Grid lines
        painter.setPen(QPen(grid_color, 1, Qt.PenStyle.DotLine))
        for temp in range(TEMP_MIN, TEMP_MAX + 1, 10):
            sx = self._to_screen(temp, 0).x()
            painter.drawLine(QPointF(sx, r.top()), QPointF(sx, r.bottom()))
        for pwm in range(0, 101, 20):
            sy = self._to_screen(TEMP_MIN, pwm).y()
            painter.drawLine(QPointF(r.left(), sy), QPointF(r.right(), sy))

        # Axis labels
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(label_color)
        for temp in range(TEMP_MIN, TEMP_MAX + 1, 10):
            sx = self._to_screen(temp, 0).x()
            painter.drawText(QRectF(sx - 15, r.bottom() + 4, 30, 14),
                             Qt.AlignmentFlag.AlignHCenter, f"{temp}°")
        for pwm in range(0, 101, 20):
            sy = self._to_screen(TEMP_MIN, pwm).y()
            painter.drawText(QRectF(2, sy - 8, 42, 16),
                             Qt.AlignmentFlag.AlignRight, f"{pwm}%")

        # Curve line
        if len(self._points) >= 2:
            pts = [self._to_screen(p.temp, p.pwm) for p in self.get_points()]
            path = QPainterPath()
            path.moveTo(pts[0])
            for i in range(1, len(pts)):
                p0, p1 = pts[i - 1], pts[i]
                cp1 = QPointF(p0.x() + (p1.x() - p0.x()) * 0.5, p0.y())
                cp2 = QPointF(p0.x() + (p1.x() - p0.x()) * 0.5, p1.y())
                path.cubicTo(cp1, cp2, p1)

            # Fill under curve
            fill = QPainterPath(path)
            fill.lineTo(QPointF(pts[-1].x(), r.bottom()))
            fill.lineTo(QPointF(pts[0].x(), r.bottom()))
            fill.closeSubpath()
            grad = QLinearGradient(0, r.top(), 0, r.bottom())
            grad.setColorAt(0.0, QColor(232, 24, 44, 60))
            grad.setColorAt(1.0, QColor(232, 24, 44, 0))
            painter.fillPath(fill, grad)

            painter.setPen(QPen(QColor("#e8182c"), 2.0))
            painter.drawPath(path)

        # Current temperature marker
        if self._current_temp > 0:
            cx = self._to_screen(self._current_temp, 0).x()
            if r.left() <= cx <= r.right():
                painter.setPen(QPen(QColor("#f59e0b"), 1, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(cx, r.top()), QPointF(cx, r.bottom()))

        # Handles
        for i, pt in enumerate(self._points):
            sp = self._to_screen(pt.temp, pt.pwm)
            is_unsafe = pt.temp >= SAFE_TEMP_THRESHOLD and pt.pwm < SAFE_PWM_MIN
            c = QColor("#ef4444") if is_unsafe else QColor("#e8182c")
            painter.setPen(QPen(QColor("#ffffff"), 1.5))
            painter.setBrush(c)
            painter.drawEllipse(sp, HANDLE_RADIUS, HANDLE_RADIUS)

        # Axis border
        painter.setPen(QPen(QColor("#3a3a50"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(r)

        # Legend
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor("#8888a0"))
        painter.drawText(
            QRectF(r.left(), r.top() - 14, r.width(), 14),
            Qt.AlignmentFlag.AlignLeft,
            f"Fan {self._fan_id}  |  Drag handles • Double-click to add • Right-click to remove",
        )

        painter.end()
