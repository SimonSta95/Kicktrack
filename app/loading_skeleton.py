from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation, QEvent, QEasingCurve, QRectF, Qt, QVariantAnimation, QPropertyAnimation
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


class _SkeletonPulseLayer(QWidget):
    """Bright skeleton layer animated by Qt's unified animation driver.

    This intentionally avoids a manually advanced shimmer band. During heavy
    market enrichment the GUI event loop can occasionally miss timer ticks;
    a slow opacity pulse remains visually continuous even then and is the same
    loading pattern used by many web UI skeleton components.
    """

    def __init__(self, owner: "_AnimatedSkeletonOverlay") -> None:
        super().__init__(owner)
        self.owner = owner
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.16)
        self.setGraphicsEffect(self._opacity_effect)
        self._animation = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._animation.setDuration(1450)
        self._animation.setStartValue(0.12)
        self._animation.setKeyValueAt(0.5, 0.58)
        self._animation.setEndValue(0.12)
        self._animation.setLoopCount(-1)
        self._animation.setEasingCurve(QEasingCurve.InOutSine)
        self.hide()

    def start(self) -> None:
        self.setGeometry(self.owner.rect())
        self.show()
        self.raise_()
        if self._animation.state() != QAbstractAnimation.Running:
            self._animation.start()

    def stop(self) -> None:
        self._animation.stop()
        self.hide()
        self._opacity_effect.setOpacity(0.16)

    def paintEvent(self, event) -> None:
        self.owner._ensure_cache()
        pixmap = self.owner._highlight_cache
        if pixmap.isNull():
            return
        painter = QPainter(self)
        exposed = event.rect()
        painter.drawPixmap(exposed, pixmap, exposed)
        painter.end()


class _AnimatedSkeletonOverlay(QWidget):
    """Cached web-style skeleton with a lightweight MUI-like pulse.

    The placeholder geometry is rasterized only when its size/column layout
    changes. Animation is delegated to Qt's unified property-animation driver
    and only changes the opacity of a cached highlight layer. That is much less
    sensitive to timer jitter and CPU-heavy Python workers than manually moving
    a shimmer strip at 50/60 FPS.
    """

    BASE = QColor("#273039")
    BASE_ALT = QColor("#222A31")
    HIGHLIGHT = QColor("#7B8995")

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._fade: QVariantAnimation | None = None
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)
        self._base_cache = QPixmap()
        self._mask_cache = QPixmap()
        self._highlight_cache = QPixmap()
        self._cache_size = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self._pulse_layer = _SkeletonPulseLayer(self)
        self.hide()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() in {QEvent.Resize, QEvent.Show}:
            self.setGeometry(self.parentWidget().rect())
            self._pulse_layer.setGeometry(self.rect())
            self.invalidate_cache()
            self.raise_()
        return super().eventFilter(watched, event)

    def invalidate_cache(self) -> None:
        self._cache_size = None
        self._base_cache = QPixmap()
        self._mask_cache = QPixmap()
        self._highlight_cache = QPixmap()
        if self.isVisible():
            self.update()
            self._pulse_layer.update()

    def start(self) -> None:
        if self._fade is not None:
            self._fade.stop()
            self._fade = None
        self._opacity_effect.setOpacity(1.0)
        self.setGeometry(self.parentWidget().rect())
        self._pulse_layer.setGeometry(self.rect())
        self.invalidate_cache()
        self.show()
        self.raise_()
        self._pulse_layer.start()
        self.update()

    def stop(self, *, animated: bool = True) -> None:
        self._pulse_layer.stop()
        if not self.isVisible():
            return
        if not animated:
            self.hide()
            self._opacity_effect.setOpacity(1.0)
            return

        animation = QVariantAnimation(self)
        animation.setDuration(160)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.valueChanged.connect(lambda value: self._opacity_effect.setOpacity(float(value)))

        def finish() -> None:
            self.hide()
            self._opacity_effect.setOpacity(1.0)
            self._fade = None

        animation.finished.connect(finish)
        self._fade = animation
        animation.start()

    def _ensure_cache(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        size = self.size()
        if (
            self._cache_size == size
            and not self._base_cache.isNull()
            and not self._mask_cache.isNull()
            and not self._highlight_cache.isNull()
        ):
            return

        base = QPixmap(size)
        base.fill(Qt.transparent)
        base_painter = QPainter(base)
        base_painter.setRenderHint(QPainter.Antialiasing)
        self._draw_skeleton(base_painter, mask=False)
        base_painter.end()

        mask = QPixmap(size)
        mask.fill(Qt.transparent)
        mask_painter = QPainter(mask)
        mask_painter.setRenderHint(QPainter.Antialiasing)
        self._draw_skeleton(mask_painter, mask=True)
        mask_painter.end()

        highlight = QPixmap(size)
        highlight.fill(Qt.transparent)
        hp = QPainter(highlight)
        hp.fillRect(highlight.rect(), self.HIGHLIGHT)
        hp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        hp.drawPixmap(0, 0, mask)
        hp.end()

        self._base_cache = base
        self._mask_cache = mask
        self._highlight_cache = highlight
        self._cache_size = size

    @staticmethod
    def _pill(painter: QPainter, rect: QRectF, color: QColor, radius: float = 5.0) -> None:
        if rect.width() <= 0 or rect.height() <= 0:
            return
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(rect, radius, radius)

    @staticmethod
    def _ellipse(painter: QPainter, rect: QRectF, color: QColor) -> None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(rect)

    def _draw_skeleton(self, painter: QPainter, *, mask: bool) -> None:
        raise NotImplementedError

    def paintEvent(self, event) -> None:
        self._ensure_cache()
        if self._base_cache.isNull():
            return
        painter = QPainter(self)
        exposed = event.rect()
        painter.drawPixmap(exposed, self._base_cache, exposed)
        painter.end()


class MarketTableSkeletonOverlay(_AnimatedSkeletonOverlay):
    """Skeleton that follows the real market table column geometry."""

    def __init__(self, table, row_count: int = 9) -> None:
        super().__init__(table.viewport())
        self.table = table
        self.row_count = row_count
        self.table.horizontalHeader().sectionResized.connect(lambda *_: self.invalidate_cache())
        self.table.horizontalHeader().sectionMoved.connect(lambda *_: self.invalidate_cache())
        self.table.verticalHeader().sectionResized.connect(lambda *_: self.invalidate_cache())

    def _draw_skeleton(self, painter: QPainter, *, mask: bool) -> None:
        width = self.width()
        height = self.height()
        shape_color = QColor(255, 255, 255, 255) if mask else self.BASE

        if not mask:
            painter.fillRect(self.rect(), QColor("#0E1215"))

        row_height = max(46, int(self.table.verticalHeader().defaultSectionSize() or 50))
        visible_rows = min(self.row_count, max(1, (height + row_height - 1) // row_height))

        for row in range(visible_rows):
            y = row * row_height
            if not mask:
                row_rect = QRectF(0, y, width, row_height)
                painter.fillRect(row_rect, QColor("#11161A") if row % 2 else QColor("#0E1317"))
                painter.setPen(QPen(QColor("#182027"), 1))
                painter.drawLine(0, y + row_height - 1, width, y + row_height - 1)

            for col in range(self.table.columnCount()):
                x = self.table.columnViewportPosition(col)
                col_width = self.table.columnWidth(col)
                if x + col_width < 0 or x > width:
                    continue

                center_y = y + row_height / 2
                left = x + 12
                available = max(8, col_width - 24)
                bar_h = 12

                if col == 0:
                    avatar = QRectF(left, center_y - 10, 20, 20)
                    self._ellipse(painter, avatar, shape_color)
                    self._pill(
                        painter,
                        QRectF(left + 30, center_y - bar_h / 2, max(28, min(available - 30, 110)), bar_h),
                        shape_color,
                        5,
                    )
                elif col == 1:
                    crest = QRectF(left, center_y - 9, 18, 18)
                    self._ellipse(painter, crest, shape_color)
                    self._pill(
                        painter,
                        QRectF(left + 27, center_y - bar_h / 2, max(20, min(available - 27, 72)), bar_h),
                        shape_color,
                        5,
                    )
                else:
                    ratios = {2: 0.45, 3: 0.70, 4: 0.72, 5: 0.50, 6: 0.52, 7: 0.72, 8: 0.58, 9: 0.44, 10: 0.68}
                    target = int(available * ratios.get(col, 0.62))
                    target = max(18, min(available, target))
                    self._pill(painter, QRectF(left, center_y - bar_h / 2, target, bar_h), shape_color, 5)


class MarketDetailSkeletonOverlay(_AnimatedSkeletonOverlay):
    """Companion skeleton for the persistent market decision panel."""

    def _draw_skeleton(self, painter: QPainter, *, mask: bool) -> None:
        width = self.width()
        x = 18.0
        content_w = max(40.0, width - 36.0)
        shape_color = QColor(255, 255, 255, 255) if mask else self.BASE

        if not mask:
            painter.fillRect(self.rect(), QColor("#0E1317"))

        hero = QRectF(x, 16, content_w, 140)
        if not mask:
            painter.setPen(QPen(QColor("#263039"), 1))
            painter.setBrush(QColor("#11171B"))
            painter.drawRoundedRect(hero, 10, 10)
        portrait = QRectF(width / 2 - 42, 33, 84, 84)
        self._ellipse(painter, portrait, shape_color)
        self._pill(painter, QRectF(width / 2 - 44, 126, 88, 10), shape_color, 5)

        y = 174.0
        self._pill(painter, QRectF(x, y, 80, 10), shape_color, 5)
        y += 24
        self._pill(painter, QRectF(x, y, min(180.0, content_w * 0.68), 17), shape_color, 6)
        y += 28
        self._pill(painter, QRectF(x, y, min(240.0, content_w * 0.84), 10), shape_color, 5)

        y += 28
        card = QRectF(x, y, content_w, 112)
        if not mask:
            painter.setPen(QPen(QColor("#263039"), 1))
            painter.setBrush(QColor("#11171B"))
            painter.drawRoundedRect(card, 10, 10)
        for idx in range(5):
            line_y = y + 14 + idx * 19
            self._pill(painter, QRectF(x + 12, line_y, 72, 9), shape_color, 4)
            self._pill(painter, QRectF(x + content_w - 92, line_y, 78, 9), shape_color, 4)

        y += 130
        for _ in range(3):
            self._pill(painter, QRectF(x, y, 72, 8), shape_color, 4)
            self._pill(painter, QRectF(x, y + 14, content_w, 6), shape_color, 3)
            y += 36

        box = QRectF(x, y + 4, content_w, 70)
        if not mask:
            painter.setPen(QPen(QColor("#263039"), 1))
            painter.setBrush(QColor("#11171B"))
            painter.drawRoundedRect(box, 10, 10)
        self._pill(painter, QRectF(x + 12, y + 18, content_w * 0.72, 9), shape_color, 4)
        self._pill(painter, QRectF(x + 12, y + 37, content_w * 0.52, 9), shape_color, 4)
