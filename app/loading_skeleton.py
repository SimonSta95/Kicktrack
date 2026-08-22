from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation, QEvent, QEasingCurve, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class _AnimatedSkeletonOverlay(QWidget):
    """Cached web-style skeleton without QGraphicsEffect recursion.

    Qt's graphics effects render their source widget through an internal painter.
    Animating an opacity effect on a child that is itself painting cached pixmaps
    can therefore cause overlapping QPainters on Windows.  The loading log showed
    exactly that failure mode.  This overlay keeps one widget and one painter: the
    base skeleton and cached highlight are composited directly in paintEvent.
    """

    BASE = QColor("#273039")
    BASE_ALT = QColor("#222A31")
    HIGHLIGHT = QColor("#7B8995")

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._pulse: QVariantAnimation | None = None
        self._fade: QVariantAnimation | None = None
        self._pulse_alpha = 0.16
        self._overlay_alpha = 1.0
        self._base_cache = QPixmap()
        self._mask_cache = QPixmap()
        self._highlight_cache = QPixmap()
        self._cache_size = None
        # While the skeleton is visible it should also block hover/click
        # interactions, otherwise stale row widgets can still emit tooltips or
        # receive clicks during a force refresh.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.hide()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() in {QEvent.Resize, QEvent.Show}:
            self.setGeometry(self.parentWidget().rect())
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

    def start(self) -> None:
        if self._fade is not None:
            self._fade.stop()
            self._fade = None
        if self._pulse is not None:
            self._pulse.stop()
        self._overlay_alpha = 1.0
        self._pulse_alpha = 0.14
        self.setGeometry(self.parentWidget().rect())
        self.invalidate_cache()
        self.show()
        self.raise_()

        pulse = QVariantAnimation(self)
        pulse.setDuration(1450)
        pulse.setStartValue(0.12)
        pulse.setKeyValueAt(0.5, 0.50)
        pulse.setEndValue(0.12)
        pulse.setLoopCount(-1)
        pulse.setEasingCurve(QEasingCurve.InOutSine)
        pulse.valueChanged.connect(self._set_pulse_alpha)
        self._pulse = pulse
        pulse.start()
        self.update()

    def _set_pulse_alpha(self, value) -> None:
        self._pulse_alpha = float(value)
        if self.isVisible():
            self.update()

    def stop(self, *, animated: bool = True) -> None:
        if self._pulse is not None:
            self._pulse.stop()
            self._pulse = None
        if not self.isVisible():
            return
        if not animated:
            self.hide()
            self._overlay_alpha = 1.0
            return

        if self._fade is not None:
            self._fade.stop()
        animation = QVariantAnimation(self)
        animation.setDuration(140)
        animation.setStartValue(self._overlay_alpha)
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.valueChanged.connect(self._set_overlay_alpha)

        def finish() -> None:
            self.hide()
            self._overlay_alpha = 1.0
            self._fade = None

        animation.finished.connect(finish)
        self._fade = animation
        animation.start()

    def _set_overlay_alpha(self, value) -> None:
        self._overlay_alpha = float(value)
        if self.isVisible():
            self.update()

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
        if base_painter.isActive():
            base_painter.setRenderHint(QPainter.Antialiasing)
            self._draw_skeleton(base_painter, mask=False)
            base_painter.end()

        mask = QPixmap(size)
        mask.fill(Qt.transparent)
        mask_painter = QPainter(mask)
        if mask_painter.isActive():
            mask_painter.setRenderHint(QPainter.Antialiasing)
            self._draw_skeleton(mask_painter, mask=True)
            mask_painter.end()

        highlight = QPixmap(size)
        highlight.fill(Qt.transparent)
        hp = QPainter(highlight)
        if hp.isActive():
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
        if not painter.isActive():
            return
        exposed = event.rect()
        painter.setOpacity(max(0.0, min(1.0, self._overlay_alpha)))
        painter.drawPixmap(exposed, self._base_cache, exposed)
        if not self._highlight_cache.isNull():
            painter.setOpacity(max(0.0, min(1.0, self._overlay_alpha * self._pulse_alpha)))
            painter.drawPixmap(exposed, self._highlight_cache, exposed)
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
