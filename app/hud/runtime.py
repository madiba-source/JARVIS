"""PySide6 HUD using the approved image as an immutable visual base."""

from __future__ import annotations

import hashlib
import math
import os
import random
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

ASSET_PATH = Path(__file__).resolve().parents[2] / "assets" / "hud" / "approved-ui.png"
ASSET_SHA256 = "10a788cef3a00614a37a7cf88d073fd6799635e0acae9f2fca1a2bfc48515a65"
ASSET_SIZE = (512, 343)


class _HudWidget(QWidget):
    def __init__(self, pixmap: QPixmap) -> None:
        super().__init__()
        self._pixmap = pixmap
        self._started = time.monotonic()
        self._enabled = True
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMinimumSize(*ASSET_SIZE)
        self.setWindowTitle("JARVIS")

    def start(self) -> None:
        self._started = time.monotonic()
        self._enabled = True
        self._timer.start()

    def stop(self) -> None:
        self._enabled = False
        self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        target = QRectF(self.rect())
        source_ratio = ASSET_SIZE[0] / ASSET_SIZE[1]
        target_ratio = target.width() / max(1.0, target.height())
        if target_ratio > source_ratio:
            width = target.height() * source_ratio
            target.setX((self.width() - width) / 2)
            target.setWidth(width)
        else:
            height = target.width() / source_ratio
            target.setY((self.height() - height) / 2)
            target.setHeight(height)
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
        if not self._enabled:
            painter.end()
            return
        elapsed = time.monotonic() - self._started
        center = QPointF(target.center().x(), target.center().y() + target.height() * 0.015)
        scale = min(target.width() / ASSET_SIZE[0], target.height() / ASSET_SIZE[1])
        radius = 106.0 * scale
        core = 1.0 + 0.03 * (0.5 + 0.5 * math.sin(2 * math.pi * elapsed / 2.2))
        glow = 1.0 + 0.12 * (0.5 + 0.5 * math.sin(2 * math.pi * elapsed / 4.0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 180, 50, int(10 * (glow - 1.0) / 0.12)))
        painter.drawEllipse(center, radius * glow, radius * glow)
        self._draw_ring(painter, center, radius * 0.80, elapsed, 25.0, 2.0, 22)
        self._draw_ring(painter, center, radius * 1.04, elapsed, -40.0, 2.0, 20)
        self._draw_ring(painter, center, radius * 1.22, elapsed, 60.0, 2.0, 18)
        self._draw_particles(painter, center, radius, elapsed, scale)
        painter.setBrush(QColor(255, 255, 210, int(20 * (core - 1.0) / 0.03)))
        painter.drawEllipse(center, radius * 0.20 * core, radius * 0.20 * core)
        painter.end()

    @staticmethod
    def _draw_ring(painter: QPainter, center: QPointF, radius: float,
                   elapsed: float, period: float, width: float, alpha: int) -> None:
        painter.save()
        painter.translate(center)
        painter.rotate(360.0 * elapsed / period)
        painter.translate(-center)
        pen = QPen(QColor(255, 196, 80, alpha), width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2), 20 * 16, 105 * 16)
        painter.drawArc(QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2), 190 * 16, 70 * 16)
        painter.restore()

    @staticmethod
    def _draw_particles(painter: QPainter, center: QPointF, radius: float,
                        elapsed: float, scale: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 210, 120, 28))
        randomizer = random.Random(11)
        for _ in range(160):
            distance = radius * (1.10 + randomizer.random() * 0.28)
            angle = randomizer.random() * math.tau + elapsed * 0.035
            painter.drawEllipse(QPointF(center.x() + math.cos(angle) * distance,
                                        center.y() + math.sin(angle) * distance),
                                max(0.5, scale), max(0.5, scale))


class HudRuntime:
    """Bounded, optional HUD lifecycle with no policy or tool authority."""

    def __init__(self, *, asset_path: Path = ASSET_PATH) -> None:
        self.asset_path = Path(asset_path)
        self.application: QApplication | None = None
        self.widget: _HudWidget | None = None
        self.available = False
        self.enabled = False
        self.error: str | None = None

    @staticmethod
    def verify_asset(path: Path = ASSET_PATH) -> bool:
        if not path.is_file():
            return False
        image = QImage(str(path))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return (not image.isNull() and image.width() == ASSET_SIZE[0]
                and image.height() == ASSET_SIZE[1]
                and image.format() in (QImage.Format.Format_RGB888, QImage.Format.Format_RGB32,
                                       QImage.Format.Format_RGBA8888, QImage.Format.Format_ARGB32)
                and digest == ASSET_SHA256)

    def start(self) -> bool:
        try:
            if not self.verify_asset(self.asset_path):
                raise ValueError("approved HUD asset integrity check failed")
            if QApplication.instance() is None:
                if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
                self.application = QApplication([])
            else:
                self.application = QApplication.instance()
            pixmap = QPixmap(str(self.asset_path))
            if pixmap.isNull():
                raise RuntimeError("approved HUD asset could not be rendered")
            self.widget = _HudWidget(pixmap)
            self.widget.start()
            self.available = True
            self.enabled = True
            self.error = None
            return True
        except Exception as error:
            self.close()
            self.error = type(error).__name__
            return False

    def disable(self) -> None:
        self.enabled = False
        if self.widget is not None:
            self.widget.stop()
            self.widget.hide()

    def enable(self) -> None:
        if self.widget is not None:
            self.widget.show()
            self.widget.start()
            self.enabled = True

    def close(self) -> None:
        self.disable()
        if self.widget is not None:
            self.widget.deleteLater()
            self.widget = None
        self.available = False
        self.application = None
