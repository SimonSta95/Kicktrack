from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from .fonts import body_font_family


class PerformanceMatchBarsWidget(QWidget):
    """Kickbase-like per-match bar chart with constant bar width and click support."""

    matchActivated = Signal(dict)

    COLUMN_WIDTH = 62
    COLUMN_GAP = 10
    BAR_WIDTH = 26
    HEIGHT = 232
    LEFT_MARGIN = 18
    RIGHT_MARGIN = 18
    TOP_AREA = 46
    BAR_TOP = 54
    BAR_HEIGHT = 118
    BOTTOM_TOP = 178

    def __init__(self, parent=None, *, club_icon_provider=None, display_date_fn=None) -> None:
        super().__init__(parent)
        self._club_icon_provider = club_icon_provider or (lambda _club: QIcon())
        self._display_date_fn = display_date_fn or (lambda value: str(value or ""))
        self._matches: list[dict] = []
        self._enabled = True
        self._message = "Noch keine Spieltags-Punkte"
        self._hover_index = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(self.HEIGHT)
        self.setMaximumHeight(self.HEIGHT)
        self._update_width()

    def sizeHint(self) -> QSize:
        return QSize(self._preferred_width(), self.HEIGHT)

    def set_matches(self, matches: list[dict], *, enabled: bool, message: str = "") -> None:
        self._matches = list(matches or [])
        self._enabled = bool(enabled)
        self._message = message or "Noch keine Spieltags-Punkte"
        self._hover_index = -1
        self._update_width()
        self.update()

    def _preferred_width(self) -> int:
        if not self._matches:
            return 540
        return self.LEFT_MARGIN + self.RIGHT_MARGIN + len(self._matches) * self.COLUMN_WIDTH + max(0, len(self._matches) - 1) * self.COLUMN_GAP

    def _update_width(self) -> None:
        width = self._preferred_width()
        self.setMinimumWidth(width)
        self.resize(width, self.HEIGHT)

    def _column_rect(self, index: int):
        x = self.LEFT_MARGIN + index * (self.COLUMN_WIDTH + self.COLUMN_GAP)
        return QRectF(x, 6, self.COLUMN_WIDTH, self.HEIGHT - 12)

    def _index_at(self, pos) -> int:
        for index in range(len(self._matches)):
            if self._column_rect(index).contains(pos):
                return index
        return -1

    @staticmethod
    def _points_color(points: int) -> QColor:
        if points < 0:
            return QColor("#EF5350")
        if points == 0:
            return QColor("#5E6772")
        if points >= 150:
            return QColor("#8BE26D")
        if points >= 100:
            return QColor("#73D96C")
        if points >= 70:
            return QColor("#B7D957")
        return QColor("#E99A3C")

    @staticmethod
    def _text_pen(color: QColor) -> QColor:
        return color.lighter(110)

    @staticmethod
    def _abbrev(label: str) -> str:
        cleaned = (label or "").strip()
        if not cleaned:
            return "–"
        if len(cleaned) <= 4:
            return cleaned.upper()
        return cleaned[:3].upper()

    def _tooltip_text(self, row: dict) -> str:
        lines = [f"ST {int(row.get('day') or 0)} · {int(row.get('points') or 0)} P"]
        fixture = row.get("fixture_text") or ""
        if fixture:
            lines.append(fixture)
        match_date = row.get("match_date")
        if match_date:
            pretty = self._display_date_fn(str(match_date))
            if pretty and pretty != "–":
                lines.append(pretty)
        minutes = row.get("minutes")
        if minutes is not None:
            try:
                lines.append(f"{int(minutes)} Minuten")
            except (TypeError, ValueError):
                pass
        lines.append("Klick: Punkte-Aufschlüsselung öffnen")
        return "\n".join(lines)

    def leaveEvent(self, event) -> None:
        self._hover_index = -1
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event) -> None:
        index = self._index_at(event.position())
        if index != self._hover_index:
            self._hover_index = index
            self.update()
        if 0 <= index < len(self._matches):
            QToolTip.showText(event.globalPosition().toPoint(), self._tooltip_text(self._matches[index]), self)
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            index = self._index_at(event.position())
            if 0 <= index < len(self._matches):
                self.matchActivated.emit(dict(self._matches[index]))
                event.accept()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        if not self._enabled or not self._matches:
            painter.setPen(QColor("#A2ACB6"))
            painter.setFont(QFont(body_font_family(), 11))
            painter.drawText(self.rect(), Qt.AlignCenter, self._message)
            return

        values = [int(row.get("points") or 0) for row in self._matches]
        max_positive = max(0, max(values))
        min_negative = min(0, min(values))
        bar_top = self.BAR_TOP
        bar_bottom = self.BAR_TOP + self.BAR_HEIGHT
        if max_positive > 0 and min_negative < 0:
            total_span = max_positive + abs(min_negative)
            baseline = bar_top + (max_positive / total_span) * self.BAR_HEIGHT
            positive_room = max(18.0, baseline - bar_top - 4.0)
            negative_room = max(18.0, bar_bottom - baseline - 4.0)
        elif max_positive > 0:
            baseline = float(bar_bottom)
            positive_room = max(18.0, self.BAR_HEIGHT - 6.0)
            negative_room = 0.0
        else:
            baseline = float(bar_top)
            positive_room = 0.0
            negative_room = max(18.0, self.BAR_HEIGHT - 6.0)

        zero_pen = QPen(QColor("#263038"))
        zero_pen.setWidth(1)
        painter.setPen(zero_pen)
        painter.drawLine(self.LEFT_MARGIN - 4, int(round(baseline)), self.width() - self.RIGHT_MARGIN + 4, int(round(baseline)))

        for index, row in enumerate(self._matches):
            rect = self._column_rect(index)
            hovered = index == self._hover_index
            if hovered:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 255, 255, 16))
                painter.drawRoundedRect(rect, 12, 12)

            day = int(row.get("day") or 0)
            painter.setPen(QColor("#A2ACB6"))
            painter.setFont(QFont(body_font_family(), 9, QFont.DemiBold))
            painter.drawText(QRectF(rect.left(), 6, rect.width(), 16), Qt.AlignHCenter | Qt.AlignVCenter, str(day))

            home_name = str(row.get("home_name") or "")
            away_name = str(row.get("away_name") or "")
            home_icon = self._club_icon_provider(home_name)
            away_icon = self._club_icon_provider(away_name)
            y_icons = 24
            icon_size = 14
            score_text = row.get("score_text") or "–"
            score_width = 20 if len(score_text) <= 3 else 28
            total_width = icon_size + 4 + score_width + 4 + icon_size
            start_x = rect.center().x() - total_width / 2
            if not home_icon.isNull():
                painter.drawPixmap(int(start_x), y_icons, home_icon.pixmap(icon_size, icon_size))
            else:
                painter.setPen(QColor("#7F8A94"))
                painter.setFont(QFont(body_font_family(), 7, QFont.DemiBold))
                painter.drawText(QRectF(start_x, y_icons, icon_size, icon_size), Qt.AlignCenter, self._abbrev(home_name))
            painter.setPen(QColor("#DDE6ED"))
            painter.setFont(QFont(body_font_family(), 8, QFont.DemiBold))
            painter.drawText(QRectF(start_x + icon_size + 4, y_icons - 1, score_width, 16), Qt.AlignCenter, score_text)
            if not away_icon.isNull():
                painter.drawPixmap(int(start_x + icon_size + 4 + score_width + 4), y_icons, away_icon.pixmap(icon_size, icon_size))
            else:
                painter.setPen(QColor("#7F8A94"))
                painter.setFont(QFont(body_font_family(), 7, QFont.DemiBold))
                painter.drawText(QRectF(start_x + icon_size + 4 + score_width + 4, y_icons, icon_size, icon_size), Qt.AlignCenter, self._abbrev(away_name))

            points = int(row.get("points") or 0)
            color = self._points_color(points)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 12))
            track_rect = QRectF(rect.center().x() - self.BAR_WIDTH / 2, bar_top, self.BAR_WIDTH, self.BAR_HEIGHT)
            painter.drawRoundedRect(track_rect, 8, 8)

            if points > 0 and max_positive > 0:
                bar_height = max(6.0, (points / max_positive) * positive_room)
                bar_rect = QRectF(rect.center().x() - self.BAR_WIDTH / 2, baseline - bar_height, self.BAR_WIDTH, bar_height)
            elif points < 0 and min_negative < 0:
                bar_height = max(6.0, (abs(points) / abs(min_negative)) * negative_room)
                bar_rect = QRectF(rect.center().x() - self.BAR_WIDTH / 2, baseline, self.BAR_WIDTH, bar_height)
            else:
                bar_rect = QRectF(rect.center().x() - self.BAR_WIDTH / 2, baseline - 3, self.BAR_WIDTH, 6)

            painter.setBrush(color)
            if hovered:
                pen = QPen(color.lighter(125))
                pen.setWidth(1)
                painter.setPen(pen)
            else:
                painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bar_rect, 8, 8)

            painter.setPen(self._text_pen(color))
            painter.setFont(QFont(body_font_family(), 11, QFont.Bold))
            painter.drawText(QRectF(rect.left(), self.BOTTOM_TOP, rect.width(), 18), Qt.AlignHCenter | Qt.AlignVCenter, str(points))

            minutes = row.get("minutes")
            minutes_text = "–"
            if minutes is not None:
                try:
                    minutes_text = f"{int(minutes)}'"
                except (TypeError, ValueError):
                    minutes_text = "–"
            painter.setPen(QColor("#95A0AA"))
            painter.setFont(QFont(body_font_family(), 8))
            painter.drawText(QRectF(rect.left(), self.BOTTOM_TOP + 18, rect.width(), 16), Qt.AlignHCenter | Qt.AlignVCenter, minutes_text)

