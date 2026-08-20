from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QMimeData, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QComboBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


POSITION_LABELS = {
    "TW": "TOR",
    "ABW": "ABWEHR",
    "MF": "MITTELFELD",
    "ST": "STURM",
}


class PlayerAvatar(QLabel):
    """Small reusable portrait component with a deterministic text fallback."""

    def __init__(self, size: int = 44, parent=None) -> None:
        super().__init__(parent)
        self._size = int(size)
        self.setObjectName("PlayerAvatar")
        self.setFixedSize(self._size, self._size)
        self.setAlignment(Qt.AlignCenter | Qt.AlignBottom)
        self.setScaledContents(False)

    def set_player(self, name: str, portrait_path: str | None = None) -> None:
        path = Path(portrait_path) if portrait_path else None
        if path and path.exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self.setPixmap(
                    pixmap.scaled(
                        self._size,
                        self._size,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
                self.setText("")
                return
        self.setPixmap(QPixmap())
        clean = " ".join(str(name or "?").split())
        initials = "".join(part[0] for part in clean.split()[:2] if part)[:2].upper() or "?"
        self.setText(initials)


class PlayerIdentity(QWidget):
    activated = Signal(str)

    def __init__(self, *, avatar_size: int = 42, parent=None) -> None:
        super().__init__(parent)
        self._player_id = ""
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        self.avatar = PlayerAvatar(avatar_size)
        root.addWidget(self.avatar, 0, Qt.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.name = QLabel("–")
        self.name.setObjectName("PlayerIdentityName")
        self.meta = QLabel("–")
        self.meta.setObjectName("PlayerIdentityMeta")
        text.addWidget(self.name)
        text.addWidget(self.meta)
        root.addLayout(text, 1)

    def set_player(
        self,
        *,
        player_id: str,
        name: str,
        meta: str = "",
        portrait_path: str | None = None,
    ) -> None:
        self._player_id = str(player_id or "")
        self.name.setText(str(name or "–"))
        self.meta.setText(str(meta or ""))
        self.avatar.set_player(str(name or ""), portrait_path)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._player_id:
            self.activated.emit(self._player_id)
        super().mouseDoubleClickEvent(event)


class ManagerStatusStrip(QFrame):
    """Persistent manager context: budget, squad slots, bids and deadline."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ManagerStatusStrip")
        root = QHBoxLayout(self)
        root.setContentsMargins(4, 0, 4, 0)
        root.setSpacing(3)
        self._values: dict[str, QLabel] = {}
        self._blocks: dict[str, QFrame] = {}
        for key, caption in (
            ("budget", "BUDGET"),
            ("squad", "KADER"),
            ("bids", "GEBOTE"),
            ("deadline", "DEADLINE"),
        ):
            block = QFrame()
            block.setObjectName("ManagerStatusBlock")
            layout = QVBoxLayout(block)
            layout.setContentsMargins(9, 4, 9, 4)
            layout.setSpacing(0)
            cap = QLabel(caption)
            cap.setObjectName("ManagerStatusCaption")
            value = QLabel("–")
            value.setObjectName("ManagerStatusValue")
            layout.addWidget(cap)
            layout.addWidget(value)
            root.addWidget(block)
            self._values[key] = value
            self._blocks[key] = block

    def update_status(self, *, budget: str, squad: str, bids: str, deadline: str, squad_full: bool = False) -> None:
        self._values["budget"].setText(budget)
        self._values["squad"].setText(squad)
        self._values["bids"].setText(bids)
        self._values["deadline"].setText(deadline)
        self._blocks["squad"].setProperty("full", bool(squad_full))
        self._blocks["squad"].style().unpolish(self._blocks["squad"])
        self._blocks["squad"].style().polish(self._blocks["squad"])


class DashboardFocusPanel(QFrame):
    """Action-first dashboard hero instead of another KPI grid."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DashboardFocusPanel")
        root = QHBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(22)

        left = QVBoxLayout()
        left.setSpacing(4)
        kicker = QLabel("DEIN FOKUS HEUTE")
        kicker.setObjectName("HeroKicker")
        self.title = QLabel("Daten synchronisieren")
        self.title.setObjectName("HeroTitle")
        self.title.setWordWrap(True)
        self.subtitle = QLabel("Danach priorisiert KickTrack die wichtigsten Aktionen für deine Preseason.")
        self.subtitle.setObjectName("HeroSubtitle")
        self.subtitle.setWordWrap(True)
        left.addWidget(kicker)
        left.addWidget(self.title)
        left.addWidget(self.subtitle)
        left.addStretch()
        root.addLayout(left, 3)

        right = QGridLayout()
        right.setHorizontalSpacing(8)
        right.setVerticalSpacing(8)
        self._metrics: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate(
            (
                ("squad", "KADER"),
                ("budget", "NACH GEBOTEN"),
                ("day", "MW 24H"),
                ("actions", "AKTIONEN"),
            )
        ):
            card = QFrame()
            card.setObjectName("HeroMiniMetric")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 9, 12, 9)
            cl.setSpacing(1)
            cap = QLabel(caption)
            cap.setObjectName("HeroMiniCaption")
            value = QLabel("–")
            value.setObjectName("HeroMiniValue")
            cl.addWidget(cap)
            cl.addWidget(value)
            right.addWidget(card, index // 2, index % 2)
            self._metrics[key] = value
        root.addLayout(right, 2)

    def set_content(self, *, title: str, subtitle: str, squad: str, budget: str, day: str, actions: str) -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self._metrics["squad"].setText(squad)
        self._metrics["budget"].setText(budget)
        self._metrics["day"].setText(day)
        self._metrics["actions"].setText(actions)


class ActivityFeed(QFrame):
    """Compact action feed used on the landing page."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ActivityFeed")
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)
        head = QLabel("HEUTE")
        head.setObjectName("SectionMini")
        root.addWidget(head)
        self._container = QVBoxLayout()
        self._container.setSpacing(5)
        root.addLayout(self._container)
        self.set_items([])

    def set_items(self, items: list[tuple[str, str, str]]) -> None:
        while self._container.count():
            item = self._container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not items:
            empty = QLabel("Keine dringenden Aktionen erkannt.")
            empty.setObjectName("Tiny")
            self._container.addWidget(empty)
            return
        for icon, title, meta in items[:5]:
            row = QFrame()
            row.setObjectName("ActivityFeedRow")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(8, 7, 8, 7)
            lay.setSpacing(9)
            ic = QLabel(icon)
            ic.setObjectName("ActivityFeedIcon")
            ic.setFixedWidth(22)
            text = QVBoxLayout()
            text.setSpacing(0)
            t = QLabel(title)
            t.setObjectName("ActivityFeedTitle")
            m = QLabel(meta)
            m.setObjectName("ActivityFeedMeta")
            text.addWidget(t)
            text.addWidget(m)
            lay.addWidget(ic, 0, Qt.AlignTop)
            lay.addLayout(text, 1)
            self._container.addWidget(row)


@dataclass
class PitchSlot:
    position: str
    index: int


class PitchPlayerCard(QPushButton):
    """Small pitch card that can be rearranged inside its positional line."""

    slotDropRequested = Signal(str, int, str, int)

    MIME_TYPE = "application/x-kicktrack-pitch-slot"

    def __init__(self, *, position: str, slot_index: int, player_id: str = "", parent=None) -> None:
        super().__init__(parent)
        self.position = str(position)
        self.slot_index = int(slot_index)
        self.player_id = str(player_id or "")
        self._drag_start = None
        self.setAcceptDrops(True)
        self.setCursor(Qt.OpenHandCursor if self.player_id else Qt.ArrowCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.player_id and event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.setCursor(Qt.OpenHandCursor if self.player_id else Qt.ArrowCursor)
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self.player_id or self._drag_start is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < 8:
            super().mouseMoveEvent(event)
            return

        mime = QMimeData()
        mime.setData(
            self.MIME_TYPE,
            f"{self.position}|{self.slot_index}|{self.player_id}".encode("utf-8"),
        )
        drag = QDrag(self)
        drag.setMimeData(mime)
        if not self.icon().isNull():
            drag.setPixmap(self.icon().pixmap(self.iconSize()))
        drag.exec(Qt.MoveAction)
        self.setCursor(Qt.OpenHandCursor)
        self._drag_start = None

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(self.MIME_TYPE):
            raw = bytes(event.mimeData().data(self.MIME_TYPE)).decode("utf-8", errors="ignore")
            source_pos = raw.split("|", 1)[0]
            # Keep the planning board position-correct: defenders can move inside
            # the defensive line, midfielders inside midfield, etc.
            if source_pos == self.position:
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasFormat(self.MIME_TYPE):
            event.ignore()
            return
        try:
            raw = bytes(event.mimeData().data(self.MIME_TYPE)).decode("utf-8")
            source_pos, source_idx, _player_id = raw.split("|", 2)
            source_idx = int(source_idx)
        except (TypeError, ValueError):
            event.ignore()
            return
        if source_pos != self.position:
            event.ignore()
            return
        self.slotDropRequested.emit(source_pos, source_idx, self.position, self.slot_index)
        event.acceptProposedAction()


class SquadPitchWidget(QFrame):
    """Formation-aware pitch preview for players explicitly marked as STAMM."""

    playerActivated = Signal(str)
    formationChanged = Signal(str)

    FORMATIONS = {
        "3-4-3": {"ABW": 3, "MF": 4, "ST": 3},
        "3-5-2": {"ABW": 3, "MF": 5, "ST": 2},
        "3-6-1": {"ABW": 3, "MF": 6, "ST": 1},
        "4-2-4": {"ABW": 4, "MF": 2, "ST": 4},
        "4-3-3": {"ABW": 4, "MF": 3, "ST": 3},
        "4-4-2": {"ABW": 4, "MF": 4, "ST": 2},
        "4-5-1": {"ABW": 4, "MF": 5, "ST": 1},
        "5-2-3": {"ABW": 5, "MF": 2, "ST": 3},
        "5-3-2": {"ABW": 5, "MF": 3, "ST": 2},
        "5-4-1": {"ABW": 5, "MF": 4, "ST": 1},
    }

    CARD_MAX_WIDTH = {1: 270, 2: 270, 3: 250, 4: 230, 5: 215, 6: 195}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SquadPitch")
        self.setMinimumHeight(330)
        self._players: list[dict] = []
        self._portrait_lookup = None
        self._formation = "AUTO"
        # formation -> position -> visible slot content.  None represents an empty slot.
        self._slot_orders: dict[str, dict[str, list[str | None]]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("STARTELF-VORSCHAU")
        title.setObjectName("SectionMini")
        formation_label = QLabel("FORMATION")
        formation_label.setObjectName("Tiny")
        self.formation_combo = QComboBox()
        self.formation_combo.setObjectName("PitchFormationCombo")
        self.formation_combo.setMinimumWidth(150)
        self.formation_combo.addItem("AUTO", "AUTO")
        for formation in self.FORMATIONS:
            self.formation_combo.addItem(formation, formation)
        self.formation_combo.currentIndexChanged.connect(self._formation_selected)
        self.summary = QLabel("Rolle STAMM")
        self.summary.setObjectName("Tiny")
        head.addWidget(title)
        head.addStretch()
        head.addWidget(formation_label)
        head.addWidget(self.formation_combo)
        head.addSpacing(10)
        head.addWidget(self.summary)
        root.addLayout(head)

        self.pitch_rows = QVBoxLayout()
        # The row margins are deliberately larger than the painted field margin.
        # This keeps the outer cards clear of the frame even in 5/6-player lines.
        self.pitch_rows.setContentsMargins(18, 3, 18, 2)
        self.pitch_rows.setSpacing(8)
        root.addLayout(self.pitch_rows, 1)
        self._render_players()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(255, 255, 255, 24))
        pen.setWidth(1)
        painter.setPen(pen)
        rect = self.rect().adjusted(22, 56, -22, -18)
        if rect.width() <= 0 or rect.height() <= 0:
            return
        painter.drawRect(rect)
        mid_y = rect.center().y()
        painter.drawLine(rect.left(), mid_y, rect.right(), mid_y)
        radius = max(18, min(rect.width(), rect.height()) // 10)
        painter.drawEllipse(rect.center(), radius, radius)
        box_w = int(rect.width() * 0.42)
        box_h = int(rect.height() * 0.16)
        left = rect.center().x() - box_w // 2
        painter.drawRect(left, rect.top(), box_w, box_h)
        painter.drawRect(left, rect.bottom() - box_h, box_w, box_h)

    def set_formation(self, formation: str | None) -> None:
        value = str(formation or "AUTO").upper()
        if value != "AUTO" and value not in self.FORMATIONS:
            value = "AUTO"
        idx = self.formation_combo.findData(value)
        if idx < 0:
            idx = 0
        self.formation_combo.blockSignals(True)
        self.formation_combo.setCurrentIndex(idx)
        self.formation_combo.blockSignals(False)
        self._formation = value
        self._render_players()

    def formation(self) -> str:
        return self._formation

    def _formation_selected(self) -> None:
        value = str(self.formation_combo.currentData() or "AUTO")
        self._formation = value
        self._render_players()
        self.formationChanged.emit(value)

    def _resolved_formation(self, grouped: dict[str, list[dict]]) -> str:
        if self._formation != "AUTO" and self._formation in self.FORMATIONS:
            return self._formation

        counts = {pos: len(grouped.get(pos, [])) for pos in ("ABW", "MF", "ST")}

        def fit_key(item):
            name, req = item
            overflow = sum(max(0, counts[pos] - req[pos]) for pos in ("ABW", "MF", "ST"))
            missing = sum(max(0, req[pos] - counts[pos]) for pos in ("ABW", "MF", "ST"))
            default_penalty = 0 if name == "4-4-2" else 1
            return (overflow, missing, default_penalty)

        return min(self.FORMATIONS.items(), key=fit_key)[0]

    def set_players(self, players: list[dict], portrait_lookup) -> None:
        self._players = list(players or [])
        self._portrait_lookup = portrait_lookup
        self._render_players()

    def _clear_pitch_rows(self) -> None:
        while self.pitch_rows.count():
            item = self.pitch_rows.takeAt(0)
            widget = item.widget()
            layout = item.layout()
            if widget:
                widget.deleteLater()
            elif layout:
                while layout.count():
                    child = layout.takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

    @staticmethod
    def _merge_slot_order(saved: list[str | None] | None, player_ids: list[str], slot_count: int) -> list[str | None]:
        """Keep manual positions while absorbing added/removed starter players."""
        valid_ids = set(player_ids)
        merged: list[str | None] = []
        for pid in saved or []:
            if pid is None:
                merged.append(None)
            elif pid in valid_ids and pid not in merged:
                merged.append(pid)
        # Preserve empty spots created by dragging, but fill untouched/new capacity first.
        for pid in player_ids:
            if pid not in merged:
                try:
                    empty_idx = merged.index(None)
                except ValueError:
                    merged.append(pid)
                else:
                    merged[empty_idx] = pid
        merged = merged[:slot_count]
        while len(merged) < slot_count:
            merged.append(None)
        return merged

    def _row_layout(self, cards: list[PitchPlayerCard], count: int) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        # Stretch at both ends and between cards guarantees a symmetric line and
        # prevents outer cards from touching/clipping the pitch frame.
        row.addStretch(1)
        max_width = self.CARD_MAX_WIDTH.get(count, 195)
        for idx, card in enumerate(cards):
            card.setMinimumWidth(118)
            card.setMaximumWidth(max_width)
            card.setMinimumHeight(54)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            row.addWidget(card, 1)
            if idx < len(cards) - 1:
                row.addSpacing(10)
                row.addStretch(1)
        row.addStretch(1)
        return row

    def _make_card(self, position: str, slot_index: int, player: dict | None) -> PitchPlayerCard:
        pid = str(player.get("player_id") or "") if player else ""
        card = PitchPlayerCard(position=position, slot_index=slot_index, player_id=pid)
        card.slotDropRequested.connect(self._move_slot)
        card.setObjectName("PitchPlayerCard" if player else "PitchEmptySlot")
        if player:
            name = str(player.get("name") or "–")
            mv = int(player.get("market_value") or 0)
            card.setText(f"{name}\n{mv / 1_000_000:.1f} Mio.")
            portrait = self._portrait_lookup(pid) if self._portrait_lookup else None
            if portrait:
                pixmap = QPixmap(str(portrait))
                if not pixmap.isNull():
                    card.setIcon(QIcon(pixmap))
                    card.setIconSize(QSize(38, 38))
            card.clicked.connect(lambda checked=False, player_id=pid: self.playerActivated.emit(player_id))
        else:
            card.setText(POSITION_LABELS.get(position, position))
            # Empty cards intentionally remain enabled so they can be DnD targets.
            card.setFocusPolicy(Qt.NoFocus)
        return card

    def _move_slot(self, source_pos: str, source_idx: int, target_pos: str, target_idx: int) -> None:
        if source_pos != target_pos or source_idx == target_idx:
            return
        grouped = self._grouped_starters()
        formation = self._resolved_formation(grouped)
        order = self._slot_orders.setdefault(formation, {}).get(source_pos)
        if not order:
            return
        if not (0 <= source_idx < len(order) and 0 <= target_idx < len(order)):
            return
        order[source_idx], order[target_idx] = order[target_idx], order[source_idx]
        self._slot_orders[formation][source_pos] = order
        self._render_players()

    def _grouped_starters(self) -> dict[str, list[dict]]:
        starters = [p for p in self._players if str(p.get("player_role") or "").upper() == "STAMM"]
        grouped: dict[str, list[dict]] = {"TW": [], "ABW": [], "MF": [], "ST": []}
        for player in starters:
            pos = str(player.get("position") or "")
            if pos in grouped:
                grouped[pos].append(player)
        for values in grouped.values():
            values.sort(key=lambda p: int(p.get("squad_value_score") or p.get("market_value") or 0), reverse=True)
        return grouped

    def _render_players(self) -> None:
        self._clear_pitch_rows()
        grouped = self._grouped_starters()
        formation = self._resolved_formation(grouped)
        req = {"TW": 1, **self.FORMATIONS[formation]}
        by_id = {
            str(player.get("player_id") or ""): player
            for players in grouped.values()
            for player in players
            if str(player.get("player_id") or "")
        }
        formation_orders = self._slot_orders.setdefault(formation, {})
        used_ids: set[str] = set()
        filled = 0

        # Render top-to-bottom like a real pitch: attack, midfield, defence, goalkeeper.
        for position in ("ST", "MF", "ABW", "TW"):
            slot_count = req[position]
            ids = [str(p.get("player_id") or "") for p in grouped[position] if str(p.get("player_id") or "")]
            order = self._merge_slot_order(formation_orders.get(position), ids, slot_count)
            formation_orders[position] = order
            cards: list[PitchPlayerCard] = []
            for slot_index, pid in enumerate(order):
                player = by_id.get(pid or "") if pid else None
                if player:
                    used_ids.add(str(pid))
                    filled += 1
                cards.append(self._make_card(position, slot_index, player))
            self.pitch_rows.addLayout(self._row_layout(cards, slot_count), 1)

        total_starters = sum(len(values) for values in grouped.values())
        overflow = max(0, total_starters - len(used_ids))
        auto_suffix = f"AUTO → {formation}" if self._formation == "AUTO" else formation
        extra = f" · {overflow} außerhalb Formation" if overflow else ""
        self.summary.setText(f"{filled}/11 STAMM · {auto_suffix}{extra}")


class MarketScoreBar(QWidget):
    def __init__(self, caption: str, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        top = QHBoxLayout()
        cap = QLabel(caption)
        cap.setObjectName("MarketScoreCaption")
        self.value = QLabel("–")
        self.value.setObjectName("MarketScoreValue")
        top.addWidget(cap)
        top.addStretch()
        top.addWidget(self.value)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        self.bar.setObjectName("MarketScoreBar")
        root.addLayout(top)
        root.addWidget(self.bar)

    def set_score(self, score: int | float | None) -> None:
        if score is None:
            self.value.setText("–")
            self.bar.setValue(0)
            return
        value = max(0, min(100, int(round(float(score)))))
        self.value.setText(str(value))
        self.bar.setValue(value)


class FadeController:
    """Tiny reusable opacity animation; animation is intentionally subtle."""

    def __init__(self) -> None:
        self._animations: list[QPropertyAnimation] = []

    def fade_in(self, widget: QWidget, duration: int = 140) -> None:
        effect = widget.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
        effect.setOpacity(0.25)
        animation = QPropertyAnimation(effect, b"opacity", widget)
        animation.setDuration(duration)
        animation.setStartValue(0.25)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animations.append(animation)
        animation.finished.connect(lambda a=animation: self._animations.remove(a) if a in self._animations else None)
        animation.start()

class TradeCycleCard(QFrame):
    playerActivated = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("TradeCard")
        self._player_id = ""
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(11)
        self.avatar = PlayerAvatar(48)
        root.addWidget(self.avatar)
        body = QVBoxLayout()
        body.setSpacing(1)
        self.name = QLabel("–")
        self.name.setObjectName("TradeCardName")
        self.period = QLabel("–")
        self.period.setObjectName("TradeCardPeriod")
        body.addWidget(self.name)
        body.addWidget(self.period)
        root.addLayout(body, 1)
        result = QVBoxLayout()
        result.setSpacing(1)
        self.pnl = QLabel("–")
        self.pnl.setObjectName("TradeCardResult")
        self.verdict = QLabel("–")
        self.verdict.setObjectName("TradeCardVerdict")
        self.pnl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.verdict.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        result.addWidget(self.pnl)
        result.addWidget(self.verdict)
        root.addLayout(result)

    def set_trade(self, trade: dict, portrait_path: str | None = None) -> None:
        self._player_id = str(trade.get("player_id") or "")
        name = str(trade.get("player_name") or "–")
        self.name.setText(name)
        self.avatar.set_player(name, portrait_path)
        cycle_type = str(trade.get("cycle_type") or "")
        buy = str(trade.get("buy_date") or "")[:10] or "?"
        if cycle_type == "OPEN_START_SQUAD":
            buy = "START"
        sell = str(trade.get("sell_date") or "")[:10]
        if not sell:
            sell = "HEUTE" if cycle_type in {"OPEN_TRADE", "OPEN_START_SQUAD"} else "offen"
        days = trade.get("holding_days")
        suffix = f" · {int(days)}T" if days is not None else ""
        self.period.setText(f"{buy} → {sell}{suffix}")
        pnl = trade.get("result_pnl")
        roi = trade.get("roi_pct")
        if pnl is None:
            self.pnl.setText("OFFEN")
        else:
            sign = "+" if int(pnl) > 0 else ""
            self.pnl.setText(f"{sign}{int(pnl):,} €".replace(",", ".") + (f" · {float(roi):+.1f}%" if roi is not None else ""))
        self.verdict.setText(str(trade.get("verdict") or trade.get("financial_verdict") or "–"))

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._player_id:
            self.playerActivated.emit(self._player_id)
        super().mouseDoubleClickEvent(event)

class SquadBenchStrip(QFrame):
    """Compact bench/investment strip below the starting-XI preview."""

    playerActivated = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SquadBenchStrip")
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 11, 14, 11)
        root.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("BANK / INVESTMENTS")
        title.setObjectName("SectionMini")
        self.summary = QLabel("–")
        self.summary.setObjectName("Tiny")
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.summary)
        root.addLayout(head)
        self.row = QHBoxLayout()
        self.row.setSpacing(8)
        root.addLayout(self.row)
        self.set_players([], None)

    def set_players(self, players: list[dict], portrait_lookup) -> None:
        while self.row.count():
            item = self.row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        bench = [p for p in players if str(p.get("player_role") or "OFFEN").upper() != "STAMM"]
        role_order = {"INVEST": 0, "OFFEN": 1, "TRANSFERLISTE": 2}
        bench.sort(
            key=lambda p: (
                role_order.get(str(p.get("player_role") or "OFFEN").upper(), 9),
                -int(p.get("market_value") or 0),
            )
        )
        self.summary.setText(f"{len(bench)} Spieler außerhalb STAMM")
        if not bench:
            empty = QLabel("Alle Kaderspieler sind aktuell als STAMM markiert.")
            empty.setObjectName("Tiny")
            self.row.addWidget(empty)
            self.row.addStretch()
            return
        for player in bench[:7]:
            pid = str(player.get("player_id") or "")
            card = QPushButton()
            card.setObjectName("BenchPlayerCard")
            role = str(player.get("player_role") or "OFFEN").upper()
            mv = int(player.get("market_value") or 0)
            card.setText(f"{player.get('name') or '–'}\n{role} · {mv / 1_000_000:.1f} Mio.")
            portrait = portrait_lookup(pid) if portrait_lookup else None
            if portrait:
                pixmap = QPixmap(str(portrait))
                if not pixmap.isNull():
                    card.setIcon(QIcon(pixmap))
                    card.setIconSize(QSize(34, 34))
            card.clicked.connect(lambda checked=False, player_id=pid: self.playerActivated.emit(player_id))
            self.row.addWidget(card, 1)
        if len(bench) > 7:
            more = QLabel(f"+{len(bench) - 7}")
            more.setObjectName("Tiny")
            self.row.addWidget(more)
