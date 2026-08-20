from __future__ import annotations

from collections import defaultdict
import html
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import keyring
import httpx
from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QDateTimeAxis,
    QHorizontalBarSeries,
    QLineSeries,
    QPieSeries,
    QValueAxis,
)
from PySide6.QtCore import QDateTime, QEvent, QMargins, QPoint, QRectF, QSize, Qt, QThreadPool, QTimer, Signal, QStringListModel
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QCompleter,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QScrollArea,
    QSizePolicy,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSplitter,
    QStyledItemDelegate,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QApplication,
)

from .branding import load_logo_pixmap
from .fonts import body_font_family
from .kickbase import KickbaseClient
from .services.league import (
    LeagueAnalysisService,
    LeagueOverviewResult,
    LeagueOwnershipResult,
    ManagerDetailResult,
    ManagerSquadResult,
)
from .services.sync import KickbaseSyncService, SyncResult
from .services.comparison import POSITIONS, summarize_squad
from .services.transfers import analyze_manager_transfers
from .season import SEASON_MODE_START, current_season_start, season_label, season_mode, season_mode_active
from .storage import Storage
from .teams import team_name
from .workers import FunctionWorker
from .version import APP_DISPLAY_NAME
from .ui_v4_components import (
    ActivityFeed,
    DashboardFocusPanel,
    FadeController,
    ManagerStatusStrip,
    MarketScoreBar,
    PlayerAvatar,
    SquadPitchWidget,
    SquadBenchStrip,
    TradeCycleCard,
)
from .mv_prediction import build_predictions
from .performance_chart import PerformanceMatchBarsWidget
from .market_analysis import enrich_market_entries, financing_scenarios
from .bid_analysis import rate_bid
from .bidding import calculate_bid_capacity
from .selling import listing_price_for_percent
from .squad_analysis import enrich_squad_entries
from .coach_analysis import build_coach_recommendations
from .portfolio_analysis import analyze_portfolio
from .transfer_evaluation import evaluate_trade_cycles, transfer_evaluation_summary
from .preseason_tools import add_value_scores, optimize_starting_squad
from .squad_rules import MAX_SQUAD_SIZE, active_bid_count, squad_capacity
from .player_master import sync_player_master, sync_missing_portraits, cache_review_candidate
from .league_learning import (
    build_league_purchase_learning, calibrate_bid_action, estimate_investment_outcome,
    estimate_winning_price, evaluate_active_bid, evaluate_premium_outcome, normalize_market_value_history,
)
from .intelligence import (
    player_form, fixture_run, squad_status, trade_profile, optimize_lineup,
    parse_activity_feed, transfer_price_history, normalize_event_types, normalize_match_events,
)


class KickbaseLogo(QWidget):
    """Displays the exact Kickbase image supplied by the user."""

    def __init__(self, parent=None, width: int = 190, height: int = 48) -> None:
        super().__init__(parent)
        self.setObjectName("KickbaseLogoWrap")
        self.setFixedSize(width, height)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.label = QLabel()
        self.label.setObjectName("KickbaseLogoImage")
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.label)

        pixmap = load_logo_pixmap()
        if pixmap is not None:
            scaled = pixmap.scaled(
                width,
                height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.label.setPixmap(scaled)
        else:
            self.label.setText("KICKBASE")
            self.label.setObjectName("KickbaseBrand")


ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
CLUB_LOGO_DIR = ASSET_DIR / "clubs_png"
CLUB_LOGOS = {
    "Köln": "1-fc-koln-logo-footylogos.png",
    "Leverkusen": "bayer-leverkusen-logo-footylogos.png",
    "Bayern": "bayern-munich-logo-footylogos.png",
    "Dortmund": "borussia-dortmund-logo-footylogos.png",
    "Gladbach": "borussia-monchengladbach-logo-footylogos.png",
    "Frankfurt": "eintracht-frankfurt-logo-footylogos.png",
    "Augsburg": "fc-augsburg-logo-footylogos.png",
    "Hamburg": "hamburger-sv-logo-footylogos.png",
    "Mainz": "mainz-05-logo-footylogos.png",
    "Leipzig": "rb-leipzig-logo-footylogos.png",
    "Freiburg": "sc-freiburg-logo-footylogos.png",
    "Paderborn": "sc-paderborn-07-logo-footylogos.png",
    "Schalke": "schalke-04-logo-footylogos.png",
    "Elversberg": "sv-elversberg-logo-footylogos.png",
    "Hoffenheim": "tsg-hoffenheim-logo-footylogos.png",
    "Union": "union-berlin-logo-footylogos.png",
    "Stuttgart": "vfb-stuttgart-logo-footylogos.png",
    "Bremen": "werder-bremen-logo-footylogos.png",
}
SORT_ROLE = Qt.UserRole + 101
POSITION_SORT = {"TW": 1, "ABW": 2, "MF": 3, "ST": 4}
ROLE_SORT = {"STAMM": 1, "INVEST": 2, "TRANSFERLISTE": 3, "OFFEN": 4}
ROLE_LABELS = {"STAMM": "STAMM", "INVEST": "INVEST", "TRANSFERLISTE": "TRANSFERLISTE", "OFFEN": "OFFEN"}
_CLUB_ICON_CACHE: dict[str, QIcon] = {}


def _smart_popover_position(popover: QWidget, anchor: QPoint, *, gap_x: int = 14, gap_y: int = 16) -> QPoint:
    """Place a tooltip-like window on the visible monitor without clipping.

    Preference order is below/right, below/left, above/right, above/left. If none
    fits completely, the position is clamped into the monitor's available geometry.
    This also behaves correctly on multi-monitor setups because screenAt() uses the
    global anchor position.
    """
    screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
    if screen is None:
        return anchor + QPoint(gap_x, gap_y)

    available = screen.availableGeometry()
    size = popover.sizeHint().expandedTo(popover.size())
    width = max(1, size.width())
    height = max(1, size.height())

    candidates = [
        QPoint(anchor.x() + gap_x, anchor.y() + gap_y),
        QPoint(anchor.x() - width - gap_x, anchor.y() + gap_y),
        QPoint(anchor.x() + gap_x, anchor.y() - height - gap_y),
        QPoint(anchor.x() - width - gap_x, anchor.y() - height - gap_y),
    ]

    for pos in candidates:
        rect = QRectF(pos.x(), pos.y(), width, height)
        if available.contains(rect.toAlignedRect()):
            return pos

    margin = 6
    min_x = available.left() + margin
    max_x = max(min_x, available.right() - width - margin + 1)
    min_y = available.top() + margin
    max_y = max(min_y, available.bottom() - height - margin + 1)
    preferred = candidates[0]
    return QPoint(
        min(max(preferred.x(), min_x), max_x),
        min(max(preferred.y(), min_y), max_y),
    )


class StableHoverPopover(QFrame):
    """Small persistent analytics popover that does not vanish on tiny mouse moves."""

    def __init__(self, owner: QWidget) -> None:
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.owner = owner
        self.setObjectName("AnalysisPopover")
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMaximumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        self.label = QLabel()
        self.label.setObjectName("AnalysisPopoverText")
        self.label.setWordWrap(True)
        # Give the label the real content width before sizeHint()/adjustSize().
        # Otherwise Windows may re-wrap the text after the top-level tooltip
        # has already requested a geometry, producing noisy setGeometry warnings.
        self.label.setMaximumWidth(400)
        self.label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.label)
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._show_pending)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_if_pointer_left)
        self._pending_text = ""
        self._pending_pos = QPoint()

    def schedule(self, text: str, global_pos: QPoint) -> None:
        if not text or text.strip() in ("-", "–"):
            self.schedule_hide()
            return
        self._hide_timer.stop()
        if self.isVisible() and self.label.text() == text:
            return
        self._pending_text = text
        self._pending_pos = global_pos
        self._show_timer.start(420)

    def _show_pending(self) -> None:
        if not self._pending_text:
            return
        self.label.setText(self._pending_text)
        self.adjustSize()
        self.move(_smart_popover_position(self, self._pending_pos, gap_x=16, gap_y=18))
        self.show()
        self.raise_()

    def schedule_hide(self) -> None:
        self._show_timer.stop()
        if self.isVisible():
            # Give the user enough time to move from the table cell into the
            # popover. 180 ms was too short on Windows and made the information
            # flash once and disappear immediately.
            self._hide_timer.start(280)

    def _pointer_inside(self, widget: QWidget) -> bool:
        if widget is None or not widget.isVisible():
            return False
        local = widget.mapFromGlobal(QCursor.pos())
        return widget.rect().contains(local)

    def _hide_if_pointer_left(self) -> None:
        # Keep the popup alive only while the pointer is actually over the popup.
        # The previous V4.1 logic also treated the whole table viewport as "inside",
        # which made tooltips linger while the user had already moved to another row.
        if self._pointer_inside(self):
            self._hide_timer.start(220)
            return
        self.hide()

    def enterEvent(self, event) -> None:
        self._hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hide_timer.start(260)
        super().leaveEvent(event)



class ChartHoverPopover(QFrame):
    """Stable tooltip for charts. QtCharts emits hover enter/leave very eagerly,
    so native QToolTip flickers when the cursor moves a few pixels.
    """

    def __init__(self, owner: QWidget) -> None:
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.owner = owner
        self.setObjectName("AnalysisPopover")
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMaximumWidth(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        self.label = QLabel()
        self.label.setObjectName("AnalysisPopoverText")
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(334)
        self.label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.label)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_if_pointer_left)

    def show_value(self, text: str, global_pos: QPoint | None = None) -> None:
        if not text or text.strip() in ("-", "–"):
            self.hide_later()
            return
        self._hide_timer.stop()
        self.label.setText(text)
        self.adjustSize()
        # Don't chase the mouse on every chart hover event. That movement is one
        # of the main reasons native chart tooltips feel nervous.
        if not self.isVisible():
            pos = global_pos or QCursor.pos()
            self.move(_smart_popover_position(self, pos, gap_x=14, gap_y=18))
        self.show()
        self.raise_()

    def hide_later(self) -> None:
        if self.isVisible():
            self._hide_timer.start(320)

    def _pointer_inside(self, widget: QWidget) -> bool:
        if widget is None or not widget.isVisible():
            return False
        local = widget.mapFromGlobal(QCursor.pos())
        return widget.rect().contains(local)

    def _hide_if_pointer_left(self) -> None:
        # Do not keep chart information visible merely because the cursor is still
        # somewhere inside the chart. Only hovering the popup itself keeps it open.
        if self._pointer_inside(self):
            self._hide_timer.start(240)
            return
        self.hide()

    def enterEvent(self, event) -> None:
        self._hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hide_timer.start(280)
        super().leaveEvent(event)


def chart_hover_popover(view: QChartView) -> ChartHoverPopover:
    popover = getattr(view, "_kicktrack_chart_popover", None)
    if popover is None:
        popover = ChartHoverPopover(view)
        view._kicktrack_chart_popover = popover
    return popover


class ResponsiveTableWidget(QTableWidget):
    """QTableWidget that keeps its columns fitted to the *actual* viewport size.

    The main-window resize event can fire before child layouts have received their
    final geometry. Fitting columns there alone can leave a large unused strip on
    the right. This widget refits after its own resize event, so the calculation
    always uses the final table viewport width.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._kicktrack_base_widths: list[int] = []
        self._kicktrack_min_widths: list[int] = []
        self._fit_pending = False
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._analysis_popover = StableHoverPopover(self)
        self._hover_popovers_enabled = True

    def set_hover_popovers_enabled(self, enabled: bool) -> None:
        self._hover_popovers_enabled = bool(enabled)
        if not self._hover_popovers_enabled:
            self._analysis_popover.hide()

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if not self._hover_popovers_enabled:
            self._analysis_popover.hide()
            return
        item = self.itemAt(event.position().toPoint())
        text = item.toolTip().strip() if item is not None else ""
        if text and text not in ("-", "–"):
            self._analysis_popover.schedule(text, self.viewport().mapToGlobal(event.position().toPoint()))
        else:
            self._analysis_popover.schedule_hide()

    def leaveEvent(self, event) -> None:
        self._analysis_popover.schedule_hide()
        super().leaveEvent(event)

    def viewportEvent(self, event) -> bool:
        if event.type() == QEvent.ToolTip:
            # Suppress Qt's fragile native tooltip; our delayed popover is used instead.
            return True
        return super().viewportEvent(event)

    def set_responsive_widths(self, base_widths: list[int], min_widths: list[int] | None = None) -> None:
        self._kicktrack_base_widths = list(base_widths)
        if min_widths is None:
            # Keep columns readable. Responsiveness should not mean crushing text.
            self._kicktrack_min_widths = [max(64, min(width, int(width * 0.84))) for width in base_widths]
        else:
            self._kicktrack_min_widths = list(min_widths)
        self.fit_columns_to_viewport()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # The viewport geometry is finalized just after the table resize. Queue one
        # refit so we never calculate against the old width.
        if not self._fit_pending:
            self._fit_pending = True
            QTimer.singleShot(0, self._finish_resize_fit)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Tables that live on hidden tabs are often created before they know their
        # final viewport width. Refit once when they become visible.
        if not self._fit_pending:
            self._fit_pending = True
            QTimer.singleShot(0, self._finish_resize_fit)

    def _finish_resize_fit(self) -> None:
        self._fit_pending = False
        self.fit_columns_to_viewport()

    def fit_columns_to_viewport(self) -> None:
        base = self._kicktrack_base_widths
        minimums = self._kicktrack_min_widths
        if not base or not minimums or len(base) != self.columnCount():
            return

        viewport_width = max(1, self.viewport().width() - 2)
        base_total = sum(base)
        min_total = sum(minimums)

        if viewport_width >= base_total:
            # Grow every column proportionally and consume the full table width.
            scale = viewport_width / base_total
            widths = [max(minimums[i], int(base[i] * scale)) for i in range(len(base))]
        elif viewport_width >= min_total:
            # Compress only as much as necessary, preserving the intended ratios.
            available_extra = viewport_width - min_total
            flexible_total = max(1, base_total - min_total)
            widths = [
                minimums[i] + int(available_extra * (base[i] - minimums[i]) / flexible_total)
                for i in range(len(base))
            ]
        else:
            # Below the readable minimum we prefer horizontal scrolling over
            # truncated values and headers.
            widths = list(minimums)

        if viewport_width >= min_total and widths:
            widths[-1] += viewport_width - sum(widths)

        for column, width in enumerate(widths):
            self.setColumnWidth(column, max(48, width))


class ClubItemDelegate(QStyledItemDelegate):
    """Draw club crests at a fixed size instead of relying on Qt's item-icon layout.

    On Windows the default table delegate can shrink tall crests to a tiny strip.
    We paint the rasterized crest ourselves so the visible size is deterministic.
    """

    def paint(self, painter, option, index) -> None:
        painter.save()

        selected = bool(option.state & QStyle.State_Selected)
        painter.fillRect(option.rect, QColor("#211A16") if selected else QColor("#14181B") if index.row() % 2 else QColor("#101316"))

        icon = index.data(Qt.DecorationRole)
        text = str(index.data(Qt.DisplayRole) or "")

        left = option.rect.left() + 10
        icon_size = 36
        if isinstance(icon, QIcon) and not icon.isNull():
            pixmap = icon.pixmap(icon_size, icon_size)
            icon_rect = option.rect.adjusted(left - option.rect.left(), 0, 0, 0)
            x = left
            y = option.rect.top() + (option.rect.height() - icon_size) // 2
            painter.drawPixmap(x, y, icon_size, icon_size, pixmap)
            left += icon_size + 8

        painter.setPen(WHITE)
        text_rect = option.rect.adjusted(left - option.rect.left(), 0, -8, 0)
        metrics = painter.fontMetrics()
        elided = metrics.elidedText(text, Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, elided)
        painter.restore()

class RecommendationChipDelegate(QStyledItemDelegate):
    """Paint one compact recommendation pill directly in the table cell.

    Using a delegate instead of a QLabel cell widget avoids Qt painting the
    backing item text underneath/next to the chip on Windows.
    """

    @staticmethod
    def _palette(signal: str) -> tuple[QColor, QColor, QColor]:
        signal = str(signal or "").upper().strip()

        # Market-role palette: make the table readable at a glance instead of
        # falling back to orange for every new preseason recommendation label.
        if signal in {"KADERZIEL", "KADER-UPGRADE", "KERN-SPIELER"}:
            return QColor("#10202A"), QColor("#28566D"), QColor("#69C9F2")
        if signal in {"INVEST", "KAUFEN", "TOP-CHANCE", "INVEST-CHANCE", "INVESTMENT HALTEN", "HALTEN"}:
            return QColor("#10251A"), QColor("#285B3C"), QColor("#65E89C")
        if signal in {"PASS", "PASSEN", "VERKAUFSKANDIDAT", "JETZT VERKAUFEN", "EHER VERKAUFEN", "VERKAUFEN"}:
            return QColor("#2A1515"), QColor("#6B3030"), QColor("#FF7474")
        if signal in {"BEOBACHTEN", "KAUF PRÜFEN", "KAUFPRÜFUNG", "VERKAUF WARTEN"}:
            return QColor("#2A1B0E"), QColor("#6C451F"), QColor("#FFAA54")

        return QColor("#171D22"), QColor("#34414B"), QColor("#B9C5CE")

    def paint(self, painter, option, index) -> None:
        painter.save()
        selected = bool(option.state & QStyle.State_Selected)
        row_bg = QColor("#211A16") if selected else QColor("#14181B") if index.row() % 2 else QColor("#101316")
        painter.fillRect(option.rect, row_bg)

        signal = str(index.data(Qt.DisplayRole) or "")
        if signal:
            bg, border, fg = self._palette(signal)
            metrics = painter.fontMetrics()
            width = min(option.rect.width() - 16, metrics.horizontalAdvance(signal) + 22)
            height = min(26, max(20, option.rect.height() - 14))
            rect = QRectF(option.rect.left() + 8, option.rect.center().y() - height / 2, max(1, width), height)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(border, 1))
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, 8, 8)
            painter.setPen(fg)
            font = painter.font()
            font.setBold(True)
            # QSS defines the app font in px, which makes QFont.pointSizeF() == -1.
            # Never feed that sentinel back into a point-size setter.
            if font.pointSizeF() > 0:
                font.setPointSizeF(max(8.0, font.pointSizeF() - 1.0))
            else:
                px = font.pixelSize()
                font.setPixelSize(max(10, (px if px > 0 else 13) - 1))
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, metrics.elidedText(signal, Qt.ElideRight, int(rect.width() - 12)))
        painter.restore()


class SortableTableItem(QTableWidgetItem):
    def __lt__(self, other) -> bool:
        left = self.data(SORT_ROLE)
        right = other.data(SORT_ROLE) if isinstance(other, QTableWidgetItem) else None
        if left is not None and right is not None:
            try:
                return left < right
            except TypeError:
                return str(left).casefold() < str(right).casefold()
        return super().__lt__(other)


def club_icon(club: str | None) -> QIcon:
    """Load a pre-rendered PNG crest.

    The SVGs are converted once at build time to 48x48 transparent PNGs.
    This avoids Qt/QIcon SVG rendering quirks in table cells on Windows.
    """
    if not club:
        return QIcon()
    if club in _CLUB_ICON_CACHE:
        return _CLUB_ICON_CACHE[club]

    filename = CLUB_LOGOS.get(club)
    if not filename:
        return QIcon()

    path = CLUB_LOGO_DIR / filename
    if not path.exists():
        return QIcon()

    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return QIcon()

    # Keep a large raster source in the icon; the table decides the final size.
    icon = QIcon(pixmap)
    _CLUB_ICON_CACHE[club] = icon
    return icon


def table_item(text, sort_value=None, *, icon: QIcon | None = None) -> SortableTableItem:
    item = SortableTableItem(str(text))
    item.setData(SORT_ROLE, sort_value if sort_value is not None else str(text).casefold())
    if icon is not None and not icon.isNull():
        item.setIcon(icon)
    return item

SERVICE = "KickTrack"
GREEN = QColor("#38D981")
RED = QColor("#FF5B5B")
ORANGE = QColor("#FF5A00")
WHITE = QColor("#E9EDF0")
MUTED = QColor("#7C8690")
LINE = QColor("#252B31")
CARD = QColor("#14181B")
PANEL = QColor("#121619")

STATUS_LABELS = {
    0: "FIT",
    1: "VERLETZT",
    2: "ANGESCHLAGEN",
    4: "AUFBAUTRAINING",
    8: "ROTE KARTE",
    16: "GELB-ROTE KARTE",
    32: "5. GELBE KARTE",
    128: "RAUS AUS DER LIGA",
    256: "ABWESEND",
}


def player_status_code(player: dict | None) -> int | None:
    """Return a verified Kickbase ``st`` status, or None when unknown.

    Missing status must not silently become 0/FIT.  This matters for rows coming
    from generic competition catalogues where a different field named
    ``status`` exists with unrelated values.
    """
    player = player or {}
    raw_list = player.get("status_list") or player.get("stl") or []
    if isinstance(raw_list, (list, tuple)):
        for value in raw_list:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue

    for key in ("kickbase_status", "st", "status"):
        if key not in player or player.get(key) is None:
            continue
        try:
            return int(player.get(key))
        except (TypeError, ValueError):
            continue
    return None


def player_status_label(player: dict | None) -> str:
    code = player_status_code(player)
    if code is None:
        return "–"
    return STATUS_LABELS.get(code, f"STATUS {code}")

def player_status_tooltip(player: dict | None) -> str:
    player = player or {}
    label = player_status_label(player)
    detail = str(player.get("status_text") or player.get("stxt") or "").strip()
    return f"{label}\n{detail}" if detail else label


def player_status_mark(player: dict | None) -> str:
    code = player_status_code(player)
    return {
        0: "✓",
        1: "✕",
        2: "!",
        4: "↻",
        8: "■",
        16: "■",
        32: "!",
        128: "⊘",
        256: "○",
    }.get(code, "?")


def player_status_display(player: dict | None) -> str:
    label = player_status_label(player)
    mark = player_status_mark(player)
    return f"{mark} {label}" if label != "–" else "? UNBEKANNT"


def player_status_icon(player: dict | None, size: int = 18) -> QIcon:
    """Small native vector status icon inspired by Kickbase's status language."""
    code = player_status_code(player)
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)

    colors = {
        0: QColor("#46B450"),
        1: QColor("#EF4D43"),
        2: QColor("#D88435"),
        4: QColor("#B86A32"),
        8: QColor("#E53935"),
        16: QColor("#E53935"),
        32: QColor("#E4B62F"),
        128: QColor("#D94A4A"),
        256: QColor("#858E96"),
    }
    color = colors.get(code, QColor("#7C8690"))
    pen = QPen(QColor("#FFFFFF"))
    pen.setWidthF(max(1.5, size / 10.0))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)

    m = max(1, size // 8)
    if code in {8, 16, 32}:
        rect = QRectF(m + 2, m, size - 2 * m - 3, size - 2 * m)
        painter.fillRect(rect, color)
        if code == 16:
            half = QRectF(rect.left(), rect.top(), rect.width() / 2, rect.height())
            painter.fillRect(half, QColor("#E4B62F"))
    else:
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(m, m, size - 2 * m, size - 2 * m))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(pen)
        if code == 0:
            painter.drawLine(QPoint(m + 3, size // 2), QPoint(size // 2 - 1, size - m - 4))
            painter.drawLine(QPoint(size // 2 - 1, size - m - 4), QPoint(size - m - 3, m + 4))
        elif code == 1:
            painter.drawLine(QPoint(m + 4, m + 4), QPoint(size - m - 4, size - m - 4))
            painter.drawLine(QPoint(size - m - 4, m + 4), QPoint(m + 4, size - m - 4))
        elif code == 2:
            painter.drawLine(QPoint(m + 4, size - m - 4), QPoint(size - m - 4, m + 4))
            painter.drawLine(QPoint(size // 2 - 3, size // 2 - 1), QPoint(size // 2 + 3, size // 2 + 1))
        elif code == 4:
            painter.drawLine(QPoint(m + 4, size - m - 4), QPoint(size - m - 4, m + 4))
            painter.drawLine(QPoint(m + 5, m + 4), QPoint(size - m - 5, size - m - 4))
        elif code == 128:
            painter.drawLine(QPoint(m + 4, size // 2), QPoint(size - m - 4, size // 2))
            painter.drawLine(QPoint(size - m - 7, size // 2 - 3), QPoint(size - m - 4, size // 2))
            painter.drawLine(QPoint(size - m - 7, size // 2 + 3), QPoint(size - m - 4, size // 2))
        elif code == 256:
            painter.drawLine(QPoint(size // 2, m + 4), QPoint(size // 2, size // 2))
            painter.drawLine(QPoint(size // 2, size // 2), QPoint(size // 2 + 4, size // 2 + 2))
        else:
            painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "?")
    painter.end()
    return QIcon(pix)


def player_name_cell(player: dict | None, portrait_path: str | None, name: str, *, avatar_size: int = 24, status_size: int = 12) -> QWidget:
    """Compact player cell: portrait, name, then a separate status icon at the edge.

    The underlying QTableWidgetItem stays responsible for sorting/data only and
    is rendered textless whenever this widget is installed. This prevents the
    native item text from showing through the transparent custom widget.
    """
    cell = QWidget()
    cell.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    cell.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(cell)
    layout.setContentsMargins(4, 0, 4, 0)
    layout.setSpacing(5)

    avatar = QLabel()
    avatar.setFixedSize(avatar_size, avatar_size)
    avatar.setAlignment(Qt.AlignCenter)
    avatar.setStyleSheet("background: transparent; border: none;")
    if portrait_path:
        portrait = QPixmap(str(portrait_path))
        if not portrait.isNull():
            portrait = portrait.scaled(avatar_size, avatar_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = max(0, (portrait.width() - avatar_size) // 2)
            y = max(0, (portrait.height() - avatar_size) // 2)
            avatar.setPixmap(portrait.copy(x, y, avatar_size, avatar_size))
    layout.addWidget(avatar, 0, Qt.AlignVCenter)

    name_label = QLabel(str(name or "–"))
    name_label.setStyleSheet("background: transparent; border: none; color: #F4F7F9;")
    name_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    name_label.setMinimumWidth(0)
    layout.addWidget(name_label, 1)

    status = QLabel()
    status.setFixedSize(status_size, status_size)
    status.setAlignment(Qt.AlignCenter)
    status.setStyleSheet("background: transparent; border: none;")
    status.setPixmap(player_status_icon(player, size=status_size).pixmap(status_size, status_size))
    status.setToolTip(player_status_tooltip(player))
    layout.addWidget(status, 0, Qt.AlignVCenter | Qt.AlignRight)
    return cell


def euro(value) -> str:
    if value is None:
        return "–"
    return f"{int(value):,} €".replace(",", ".")


def compact_number(value) -> str:
    if value is None:
        return "–"
    value = int(value)
    absolute = abs(value)
    if absolute >= 1_000_000:
        text = f"{absolute / 1_000_000:.2f} M"
    elif absolute >= 1_000:
        text = f"{absolute / 1_000:.0f} K"
    else:
        text = str(absolute)
    prefix = "-" if value < 0 else "+" if value > 0 else ""
    return prefix + text


def delta_text(value, *, compact: bool = False) -> str:
    if value is None:
        return "–"
    return compact_number(value) if compact else (("+" if value > 0 else "") + f"{int(value):,} €").replace(",", ".")


def percent(value) -> str:
    if value is None:
        return "–"
    return f"{value:+.1f} %".replace(".", ",")

def precise_percent(value) -> str:
    if value is None:
        return "–"
    return f"{value:+.3f} %".replace(".", ",")

def change_tooltip(label: str, market_value: int, delta, *, exact: bool) -> str:
    if delta is None:
        return f"{label}: noch keine Daten"
    previous = market_value - int(delta)
    pct = (int(delta) / previous * 100.0) if previous else None
    source = "Kickbase 24h-Wert" if exact else "aus lokalen Tages-Snapshots"
    return (
        f"Aktueller Marktwert: {euro(market_value)}\n"
        f"{label}: {delta_text(delta)} ({precise_percent(pct)})\n"
        f"Vergleichswert: {euro(previous)}\n\n"
        f"Quelle: {source}"
    )

def market_value_tooltip(player: dict) -> str:
    market_value = int(player.get("market_value") or 0)
    entry = player.get("entry_value")
    pnl = player.get("pnl")
    roi = player.get("roi")
    lines = [f"Aktueller Marktwert: {euro(market_value)}"]
    if entry is not None:
        lines += [
            f"Kaufpreis / Startwert: {euro(entry)}",
            f"Differenz: {delta_text(pnl)} ({precise_percent(roi)})",
        ]
    d1 = player.get("d1")
    if d1 is not None:
        previous = market_value - int(d1)
        pct = (int(d1) / previous * 100.0) if previous else None
        lines += ["", f"24h: {delta_text(d1)} ({precise_percent(pct)})"]
    return "\n".join(lines)


def display_date(value: str | None) -> str:
    if not value:
        return "–"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%y %H:%M")
    except ValueError:
        return value


def short_date(value: str | None) -> str:
    if not value:
        return "–"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%d.%m")
    except ValueError:
        return value[:10]


def refresh_style(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def set_delta_label(label: QLabel, value, *, base_name: str = "CardValue") -> None:
    if value is None or value == 0:
        label.setObjectName(base_name)
    elif value > 0:
        label.setObjectName("CardPositive")
    else:
        label.setObjectName("CardNegative")
    refresh_style(label)


def set_item_delta_color(item: QTableWidgetItem, value) -> None:
    if value is None:
        item.setForeground(MUTED)
    elif value > 0:
        item.setForeground(GREEN)
    elif value < 0:
        item.setForeground(RED)
    else:
        item.setForeground(MUTED)


class SparklineWidget(QWidget):
    """Tiny dependency-free sparkline used inside KPI cards.

    Keeping this as a painted Qt widget avoids embedding another chart object for
    every metric card and gives the dashboard the compact web-app feel we want.
    """

    def __init__(self, color: QColor = None, parent=None) -> None:
        super().__init__(parent)
        self._values: list[float] = []
        self._color = QColor(color or ORANGE)
        self.setMinimumSize(62, 24)
        self.setMaximumSize(92, 32)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def set_values(self, values) -> None:
        self._values = [float(v) for v in values if v is not None]
        self.update()

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        if len(self._values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(2, 3, max(1, self.width() - 4), max(1, self.height() - 6))
        low, high = min(self._values), max(self._values)
        span = high - low or 1.0
        points = []
        for index, value in enumerate(self._values):
            x = rect.left() + (rect.width() * index / max(1, len(self._values) - 1))
            y = rect.bottom() - ((value - low) / span) * rect.height()
            points.append(QPoint(int(x), int(y)))
        pen = QPen(self._color)
        pen.setWidthF(1.8)
        painter.setPen(pen)
        for a, b in zip(points, points[1:]):
            painter.drawLine(a, b)


class MetricCard(QFrame):
    """Mantine-like KPI card implemented with lightweight native Qt widgets."""

    _ACCENTS = {
        "orange": (QColor("#FF6518"), "#2A1710"),
        "green": (QColor("#3DDC84"), "#10251A"),
        "purple": (QColor("#A970FF"), "#211631"),
        "gold": (QColor("#F3C44E"), "#2A2210"),
        "blue": (QColor("#6F8CFF"), "#151C32"),
    }

    def __init__(
        self,
        caption: str,
        value: str = "–",
        hint: str = "",
        *,
        icon: str = "",
        accent: str = "orange",
        compact: bool = False,
    ) -> None:
        super().__init__()
        self.setObjectName("MetricCard")
        self._compact = compact
        self.setMinimumHeight(70 if compact else 92)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        accent_color, badge_bg = self._ACCENTS.get(accent, self._ACCENTS["orange"])
        self._accent_color = accent_color

        layout = QHBoxLayout(self)
        layout.setContentsMargins(11 if compact else 13, 8 if compact else 11, 11 if compact else 13, 8 if compact else 11)
        layout.setSpacing(8 if compact else 10)

        self.icon_label = QLabel(icon or "•")
        self.icon_label.setObjectName("MetricIcon")
        self.icon_label.setAlignment(Qt.AlignCenter)
        # Keep every KPI badge visually identical.  Different badge sizes in
        # compact vs. primary cards made the icon row look inconsistent.
        icon_size = 36
        self.icon_label.setFixedSize(icon_size, icon_size)
        self.icon_label.setStyleSheet(
            f"background:{badge_bg}; color:{accent_color.name()}; border:1px solid {accent_color.darker(185).name()}; "
            "border-radius:10px; font-size:16px; font-weight:800;"
        )
        layout.addWidget(self.icon_label, 0, Qt.AlignTop)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(3)
        caption_label = QLabel(caption)
        caption_label.setObjectName("CardCaption")
        # KPI captions may be longer than one line (e.g. VERKAUFSGEWINN/-VERLUST).
        # Let Qt wrap them instead of clipping when the dashboard reflows.
        caption_label.setWordWrap(True)
        caption_label.setMinimumWidth(0)
        caption_label.setMinimumHeight(22 if compact else 18)
        caption_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("CardValue")
        self.value_label.setMinimumWidth(0)
        self.value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.value_label.setMinimumHeight(23 if compact else 28)
        self.value_label.setToolTip(value)
        if compact:
            self.value_label.setStyleSheet("font-size:17px; font-weight:800; background:transparent;")
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("CardHint")
        self.hint_label.setMinimumWidth(0)
        self.hint_label.setWordWrap(True)
        self.hint_label.setMinimumHeight(16)
        body.addWidget(caption_label)
        body.addWidget(self.value_label)
        body.addWidget(self.hint_label)
        body.addStretch()
        layout.addLayout(body, 1)

        self.sparkline = SparklineWidget(accent_color)
        layout.addWidget(self.sparkline, 0, Qt.AlignRight | Qt.AlignBottom)

    def set_sparkline(self, values) -> None:
        values = list(values or [])
        self.sparkline.set_values(values)
        self.sparkline.setVisible(len(values) >= 2)


class CompactMetric(QFrame):
    """Small inline KPI used where a full dashboard card wastes vertical space."""

    def __init__(self, caption: str, value: str = "–", hint: str = "", *, accent: str = "orange") -> None:
        super().__init__()
        self.setObjectName("CompactMetric")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(66)
        color = MetricCard._ACCENTS.get(accent, MetricCard._ACCENTS["orange"])[0].name()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 9, 14, 9)
        outer.setSpacing(10)
        accent_bar = QFrame()
        accent_bar.setFixedWidth(3)
        accent_bar.setStyleSheet(f"background:{color}; border:none; border-radius:1px;")
        outer.addWidget(accent_bar)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(1)
        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("CardCaption")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("CardValue")
        self.value_label.setStyleSheet("font-size:16px; font-weight:800; background:transparent;")
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("CardHint")
        self.hint_label.setWordWrap(False)
        body.addWidget(self.caption_label)
        body.addWidget(self.value_label)
        body.addWidget(self.hint_label)
        outer.addLayout(body, 1)


class AccountChip(QFrame):
    """Compact account chip with an avatar bubble instead of a boxed e-mail label."""

    def __init__(self, text: str = "Nicht verbunden", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AccountChipFrame")
        row = QHBoxLayout(self)
        row.setContentsMargins(7, 5, 9, 5)
        row.setSpacing(7)
        self.avatar = QLabel("?")
        self.avatar.setObjectName("AccountAvatar")
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setFixedSize(26, 26)
        self.label = QLabel(text)
        self.label.setObjectName("AccountText")
        self.label.setMinimumWidth(0)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.label.setToolTip(text)
        row.addWidget(self.avatar)
        row.addWidget(self.label)

    def setText(self, text: str) -> None:
        self.label.setText(text)
        self.label.setToolTip(text)
        value = (text or "?").strip()
        self.avatar.setText(value[0].upper() if value else "?")




class AnalysisChipCell(QWidget):
    """Quiet recommendation chip for analytics tables.

    The table shows only the actionable verdict. Numeric ratings and the full
    rationale stay available through the tooltip so the row remains easy to scan.
    ``scores`` and ``insights`` remain accepted for backwards compatibility with
    the scoring call sites, but are intentionally not rendered.
    """

    def __init__(self, primary: str, scores=None, insights=None, tooltip: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AnalysisChipCell")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(0)

        primary_chip = QLabel(primary)
        primary_chip.setObjectName("AnalysisPrimaryChip")
        primary_chip.setProperty("tone", self._signal_tone(primary))
        primary_chip.setAlignment(Qt.AlignCenter)
        primary_chip.setToolTip(tooltip)
        row.addWidget(primary_chip, 0, Qt.AlignVCenter)
        row.addStretch(1)

    @staticmethod
    def _signal_tone(signal: str) -> str:
        signal = str(signal or "").upper().strip()
        if signal in {"KADERZIEL", "KADER-UPGRADE", "KERN-SPIELER"}:
            return "info"
        if signal in {"INVEST", "KAUFEN", "TOP-CHANCE", "INVEST-CHANCE", "INVESTMENT HALTEN", "HALTEN"}:
            return "positive"
        if signal in {"PASS", "PASSEN", "VERKAUFSKANDIDAT", "JETZT VERKAUFEN", "EHER VERKAUFEN", "VERKAUFEN"}:
            return "negative"
        if signal in {"BEOBACHTEN", "KAUF PRÜFEN", "KAUFPRÜFUNG", "VERKAUF WARTEN"}:
            return "warning"
        return "neutral"


def market_analysis_insights(player: dict) -> list[tuple[str, str]]:
    insights: list[tuple[str, str]] = []
    delta_pct = player.get("price_delta_pct")
    if delta_pct is not None:
        if float(delta_pct) <= -3:
            insights.append((f"↓ {abs(float(delta_pct)):.0f}% unter MW", "positive"))
        elif float(delta_pct) >= 3:
            insights.append((f"↑ {float(delta_pct):.0f}% über MW", "negative"))
    if player.get("affordable"):
        insights.append(("Budget-fit", "positive"))
    if player.get("market_trend") == 1:
        insights.append(("Trend ↑", "positive"))
    elif player.get("market_trend") == 2:
        insights.append(("Trend ↓", "negative"))
    if int((player.get("fit_breakdown") or {}).get("positionsbedarf") or 0) >= 22:
        insights.append(("Positionsbedarf", "accent"))
    if player.get("own_bid"):
        insights.append(("Eigenes Gebot", "accent"))
    return insights or [("neutral", "muted")]


def squad_analysis_insights(player: dict) -> list[tuple[str, str]]:
    insights: list[tuple[str, str]] = []
    role = str(player.get("player_role") or "OFFEN").upper()
    if role == "STAMM":
        insights.append(("Stamm", "accent"))
    elif role == "INVEST":
        insights.append(("Invest", "accent"))
    elif role == "TRANSFERLISTE":
        insights.append(("Transferliste", "warning"))
    pnl = player.get("pnl")
    if pnl is not None and int(pnl) > 250_000:
        insights.append(("Gewinn +", "positive"))
    elif pnl is not None and int(pnl) < -250_000:
        insights.append(("P/L −", "negative"))
    if int(player.get("investment_score") or 0) >= 75:
        insights.append(("Invest stark", "positive"))
    if int(player.get("sell_score") or 0) >= 75:
        insights.append(("Verkauf sinnvoll", "warning"))
    trend = player.get("d3") if player.get("d3") is not None else player.get("d1")
    if trend is not None and int(trend) > 0:
        insights.append(("Trend ↑", "positive"))
    elif trend is not None and int(trend) < 0:
        insights.append(("Trend ↓", "negative"))
    return insights or [("neutral", "muted")]


class ChartPanel(QFrame):
    def __init__(self, title: str, subtitle: str = "", *, height: int = 220) -> None:
        super().__init__()
        self.setObjectName("AnalyticsCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 14, 15, 13)
        layout.setSpacing(7)

        self.title = QLabel(title)
        self.title.setObjectName("SectionMini")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("Tiny")
        self.subtitle.setWordWrap(True)
        self.subtitle.setMinimumHeight(18)

        self.chart_view = QChartView()
        self.chart_view.setRenderHint(QPainter.Antialiasing)
        self.chart_view.setMinimumHeight(max(135, height - 62))
        self.chart_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(height + 10)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.chart_view.setStyleSheet("background: transparent; border: none;")

        # Optional native footer for chart-specific legends / context.
        # Using Qt widgets here is more reliable than QChart's own legend on
        # narrow cards, because QLegend may elide labels without giving us
        # control over the resulting text.
        self.footer = QWidget()
        self.footer.setObjectName("ChartFooter")
        # QWidget inherits the application's opaque background by default.
        # The chart footer is part of the card composition and must not paint
        # its own rectangular surface.
        self.footer.setAttribute(Qt.WA_StyledBackground, True)
        self.footer.setStyleSheet("background: transparent; border: none;")
        self.footer_grid = QGridLayout(self.footer)
        self.footer_grid.setContentsMargins(0, 0, 0, 0)
        self.footer_grid.setHorizontalSpacing(14)
        self.footer_grid.setVerticalSpacing(5)
        self.footer.hide()

        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.chart_view, 1)
        layout.addWidget(self.footer)


class BudgetBidList(QFrame):
    """Compact active-bids list that scales down cleanly for just a few rows."""

    playerActivated = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("BudgetBidListPanel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._analysis_popover = StableHoverPopover(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self.rows_layout = QVBoxLayout()
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        outer.addLayout(self.rows_layout)

        self.footer = QFrame()
        self.footer.setObjectName("BudgetBidFooter")
        footer_row = QHBoxLayout(self.footer)
        footer_row.setContentsMargins(12, 10, 12, 10)
        footer_row.setSpacing(10)
        footer_label = QLabel("Gebundene Summe")
        footer_label.setObjectName("BudgetBidFooterLabel")
        self.footer_value = QLabel("0 €")
        self.footer_value.setObjectName("BudgetBidFooterValue")
        footer_row.addWidget(footer_label)
        footer_row.addStretch()
        footer_row.addWidget(self.footer_value)
        outer.addWidget(self.footer)
        self.footer.hide()

    def _clear_rows(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            nested = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif nested is not None:
                while nested.count():
                    child = nested.takeAt(0)
                    if child.widget() is not None:
                        child.widget().deleteLater()

    def set_bids(self, bids: list[dict]) -> None:
        self._clear_rows()
        bids = list(bids or [])
        total = sum(int(bid.get("bid") or 0) for bid in bids)

        if not bids:
            empty = QLabel("Keine aktiven Gebote erkannt")
            empty.setObjectName("BudgetEmptyState")
            empty.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.rows_layout.addWidget(empty)
            self.footer.hide()
            return

        for bid in bids:
            row = QFrame()
            row.setObjectName("BudgetBidRow")
            row.setCursor(Qt.PointingHandCursor)
            row.setToolTip("Doppelklick für Spielerdetails")
            row.mouseDoubleClickEvent = lambda event, data=dict(bid): self._activate_bid(event, data)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 9, 12, 9)
            row_layout.setSpacing(12)

            crest = QLabel()
            crest.setObjectName("BudgetBidClubLogo")
            crest.setFixedSize(28, 28)
            crest.setAlignment(Qt.AlignCenter)
            icon = club_icon(bid.get("club"))
            if not icon.isNull():
                crest.setPixmap(icon.pixmap(24, 24))
            row_layout.addWidget(crest, 0, Qt.AlignTop)

            body = QVBoxLayout()
            body.setContentsMargins(0, 0, 0, 0)
            body.setSpacing(3)

            head = QHBoxLayout()
            head.setSpacing(8)
            display_name = str(bid.get("full_name") or bid.get("name") or "Unbekannter Spieler")
            name = QLabel(display_name)
            name.setObjectName("BudgetBidName")
            head.addWidget(name)
            club = str(bid.get("club") or "").strip()
            if club:
                meta = QLabel(club)
                meta.setObjectName("BudgetBidMeta")
                head.addWidget(meta)
            head.addStretch()

            # One dominant action chip. The secondary price rating is context,
            # not a competing verdict.
            action = str(bid.get("bid_action") or "").strip()
            signal = str(bid.get("bid_signal") or "").strip()
            dominant = action or signal
            if dominant:
                chip = QLabel(dominant)
                chip.setObjectName("BidRatingChip")
                tone = str(bid.get("bid_action_tone") or self._rating_tone(signal)) if action else self._rating_tone(signal)
                chip.setProperty("tone", tone)
                chip.setAlignment(Qt.AlignCenter)
                chip.setCursor(Qt.PointingHandCursor)
                chip.setProperty("analysis_text", str(bid.get("bid_analysis_text") or ""))
                chip.installEventFilter(self)
                head.addWidget(chip)
            body.addLayout(head)

            market_value = int(bid.get("market_value") or 0)
            max_bid = int(bid.get("max_bid") or 0)
            winning_price = int(bid.get("league_winning_price") or 0)
            context = []
            if market_value:
                context.append(f"MW {euro(market_value)}")
            if max_bid:
                context.append(f"Max-Bid {euro(max_bid)}")
            if winning_price:
                context.append(f"Liga ~{euro(winning_price)}")
            if context:
                context_label = QLabel("  ·  ".join(context))
                context_label.setObjectName("BudgetBidMeta")
                context_label.setToolTip(str(bid.get("bid_analysis_text") or ""))
                body.addWidget(context_label)

            # Historical calibration is shown only when it carries an actual
            # warning or positive signal; raw samples remain in the tooltip.
            hist_profile = dict(bid.get("historical_investment") or {})
            hist_premium = dict(bid.get("historical_premium") or {})
            hist_parts = []
            if hist_profile.get("median_return_7d_pct") is not None:
                hist_parts.append(f"Historie {hist_profile['median_return_7d_pct']:+.1f}% / 7T")
            hist_label = str(hist_premium.get("label") or "").strip()
            if hist_label not in ("", "KEINE DATEN", "ZU WENIG DATEN"):
                hist_parts.append(hist_label)
            if hist_parts:
                hist = QLabel("  ·  ".join(hist_parts))
                hist.setObjectName("BudgetBidMeta")
                hist.setToolTip(str(bid.get("bid_analysis_text") or ""))
                body.addWidget(hist)

            row_layout.addLayout(body, 1)

            amount_box = QVBoxLayout()
            amount_box.setContentsMargins(0, 0, 0, 0)
            amount_box.setSpacing(1)
            amount_caption = QLabel("DEIN GEBOT")
            amount_caption.setObjectName("BudgetBidMeta")
            amount_caption.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            amount = QLabel(euro(bid.get("bid")))
            amount.setObjectName("BudgetBidAmount")
            amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            amount.setMinimumWidth(130)
            amount_box.addWidget(amount_caption)
            amount_box.addWidget(amount)
            if signal and action:
                signal_label = QLabel(signal)
                signal_label.setObjectName("BudgetBidMeta")
                signal_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                amount_box.addWidget(signal_label)
            row_layout.addLayout(amount_box, 0)
            self.rows_layout.addWidget(row)

        self.footer_value.setText(euro(total))
        self.footer.setVisible(len(bids) > 1)

    @staticmethod
    def _rating_tone(signal: str) -> str:
        if signal in {"SCHNÄPPCHEN", "GUTES GEBOT"}:
            return "positive"
        if signal in {"ZU TEUER", "NICHT SINNVOLL"}:
            return "negative"
        return "warning"

    def eventFilter(self, watched, event) -> bool:
        if isinstance(watched, QLabel) and watched.objectName() == "BidRatingChip":
            text = str(watched.property("analysis_text") or "")
            if event.type() == QEvent.Enter:
                self._analysis_popover.schedule(text, watched.mapToGlobal(QPoint(0, watched.height())))
            elif event.type() == QEvent.Leave:
                self._analysis_popover.schedule_hide()
        return super().eventFilter(watched, event)

    def _activate_bid(self, event, bid: dict) -> None:
        if bid.get("player_id"):
            self.playerActivated.emit(dict(bid))
        event.accept()


class LeagueValueSummaryPanel(QFrame):
    """Compact league-value context without competing with the league table."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self.setMinimumHeight(118)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        title = QLabel("KADERWERT-CHECK")
        title.setObjectName("SectionMini")
        subtitle = QLabel("Spitze, dein Kader und direkter Abstand")
        subtitle.setObjectName("Tiny")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        metrics = QHBoxLayout()
        metrics.setSpacing(28)
        self.leader = self._metric("SPITZE")
        self.own = self._metric("DEIN KADER")
        self.gap = self._metric("ABSTAND ZUR SPITZE")
        metrics.addLayout(self.leader[0], 1)
        metrics.addLayout(self.own[0], 1)
        metrics.addLayout(self.gap[0], 1)
        layout.addLayout(metrics)

    @staticmethod
    def _metric(caption: str):
        box = QVBoxLayout()
        box.setSpacing(1)
        caption_label = QLabel(caption)
        caption_label.setObjectName("CardCaption")
        value_label = QLabel("–")
        value_label.setObjectName("SectionMini")
        hint_label = QLabel("")
        hint_label.setObjectName("Tiny")
        box.addWidget(caption_label)
        box.addWidget(value_label)
        box.addWidget(hint_label)
        return box, value_label, hint_label


class MatchEventBreakdownDialog(QDialog):
    """Read-only breakdown of the Kickbase points awarded in one match."""

    def __init__(self, parent, summary: dict, chart_row: dict | None = None) -> None:
        super().__init__(parent)
        self.summary = summary or {}
        self.chart_row = chart_row or {}
        player_name = self.summary.get("player_name") or "Spieler"
        self.setWindowTitle(f"{player_name} — Punkte im Spiel")
        self.resize(700, 650)
        self.setMinimumSize(620, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)

        title = QLabel(f"{player_name.upper()} · PUNKTE-AUFSCHLÜSSELUNG")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        home = PlayerDetailDialog._performance_team_label(self.summary.get("home_team"))
        away = PlayerDetailDialog._performance_team_label(self.summary.get("away_team"))
        goals_home = self.summary.get("home_goals")
        goals_away = self.summary.get("away_goals")
        fixture_bits = []
        if home and away:
            if goals_home is not None and goals_away is not None:
                fixture_bits.append(f"{home} {goals_home}:{goals_away} {away}")
            else:
                fixture_bits.append(f"{home} – {away}")
        match_date = self.summary.get("match_date") or self.chart_row.get("match_date")
        if match_date:
            pretty = display_date(str(match_date))
            if pretty and pretty != "–":
                fixture_bits.append(pretty)
        if self.chart_row.get("day"):
            fixture_bits.append(f"ST {int(self.chart_row['day'])}")
        subtitle = QLabel(" · ".join(fixture_bits) if fixture_bits else "Kickbase Playercenter")
        subtitle.setObjectName("Subtle")
        root.addWidget(subtitle)

        cards = QHBoxLayout()
        total_card = MetricCard("GESAMTPUNKTE", str(self.summary.get("total_points") if self.summary.get("total_points") is not None else "–"), "laut Kickbase")
        event_card = MetricCard("EVENTPUNKTE", str(self.summary.get("event_points") or 0), "Summe der gelisteten Punkte-Events")
        diff = self.summary.get("unmapped_points")
        diff_text = "–" if diff is None else f"{int(diff):+d}"
        diff_card = MetricCard("DIFFERENZ", diff_text, "nicht als Punkte-Event ausgewiesen")
        cards.addWidget(total_card)
        cards.addWidget(event_card)
        cards.addWidget(diff_card)
        root.addLayout(cards)

        hint = QLabel(
            "Die Liste zeigt ausschließlich Events mit einem Punktewert ≠ 0. "
            "Eventnamen kommen dynamisch aus Kickbases /v4/live/eventtypes. "
            "Eine Differenz zur Gesamtpunktzahl wird bewusst separat ausgewiesen statt rekonstruiert."
        )
        hint.setObjectName("Subtle")
        hint.setWordWrap(True)
        root.addWidget(hint)

        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["MIN.", "PUNKTE", "EVENT"] )
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.setAlternatingRowColors(False)

        point_events = self.summary.get("point_events") or []
        table.setRowCount(len(point_events))
        for row_index, event in enumerate(point_events):
            minute = int(event.get("minute") or 0)
            points = int(event.get("points") or 0)
            minute_item = QTableWidgetItem(f"{minute}'")
            points_item = QTableWidgetItem(f"{points:+d}")
            label = str(event.get("label") or "Event")
            event_type_id = str(event.get("event_type_id") or "")
            label_item = QTableWidgetItem(label)
            if label.startswith("Event ") and event_type_id:
                label_item.setToolTip(f"Unbekannte Event-Type-ID: {event_type_id}")
            if points > 0:
                points_item.setForeground(GREEN)
            elif points < 0:
                points_item.setForeground(RED)
            else:
                points_item.setForeground(MUTED)
            table.setItem(row_index, 0, minute_item)
            table.setItem(row_index, 1, points_item)
            table.setItem(row_index, 2, label_item)

        root.addWidget(table, 1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("SCHLIESSEN")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)


class PlayerDetailDialog(QDialog):
    """Focused, read-only player analytics view.

    The dialog intentionally uses only data we actually persist or receive from
    Kickbase. It therefore remains useful offline after a successful sync and
    does not pretend to provide forecasts we cannot substantiate yet.
    """

    def __init__(
        self,
        parent,
        storage: Storage,
        player_id: str,
        league_id: str | None = None,
        player_data: dict | None = None,
        embedded: bool = False,
    ) -> None:
        super().__init__(parent)
        self.embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.Widget)
        self.storage = storage
        self.player_id = player_id
        self.league_id = league_id
        self._history_worker = None
        self._match_event_worker = None
        self.client = self._resolve_client(parent)
        self.player = self._resolve_player_data(player_data)
        self.history = storage.history(player_id, 90)
        self.analytics = storage.analytics(player_id)
        if self.analytics.get("d1") is None and self.player.get("daily_change") is not None:
            self.analytics["d1"] = self.player.get("daily_change")

        name = self.player.get("full_name") or self.player.get("name") or "Spieler"
        self.setWindowTitle(f"{name} — Spieleranalyse")
        self.resize(980, 760)
        self.setMinimumSize(820, 650)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(14)

        portrait_path = self.storage.portrait_path(self.player_id)
        if portrait_path:
            portrait = QLabel()
            portrait.setObjectName("PlayerDetailPortrait")
            portrait.setFixedSize(82, 92)
            portrait.setAlignment(Qt.AlignCenter | Qt.AlignBottom)
            portrait_pixmap = QPixmap(portrait_path)
            if not portrait_pixmap.isNull():
                portrait.setPixmap(
                    portrait_pixmap.scaled(82, 92, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                header.addWidget(portrait, 0, Qt.AlignBottom)

        crest = QLabel()
        crest.setObjectName("PlayerDetailClubLogo")
        crest.setFixedSize(42, 42)
        crest.setAlignment(Qt.AlignCenter)
        crest_icon = club_icon(self.player.get("club"))
        if not crest_icon.isNull():
            crest.setPixmap(crest_icon.pixmap(34, 34))
        header.addWidget(crest, 0, Qt.AlignVCenter)

        identity = QVBoxLayout()
        identity.setSpacing(2)
        self.title_label = QLabel(name)
        self.title_label.setObjectName("PageTitle")
        self.meta_label = QLabel(self._meta_text())
        self.meta_label.setObjectName("Subtle")
        self.crest_label = crest
        identity.addWidget(self.title_label)
        identity.addWidget(self.meta_label)
        header.addLayout(identity)
        header.addStretch()

        self.watchlist_btn = QPushButton()
        self.watchlist_btn.setToolTip("Spieler auf deiner Watchlist speichern oder entfernen")
        self.watchlist_btn.clicked.connect(self._toggle_watchlist)
        self._refresh_watchlist_button()
        header.addWidget(self.watchlist_btn)

        self.compare_btn = QPushButton("⚖ VERGLEICHEN")
        self.compare_btn.setToolTip("Diesen Spieler mit einem anderen Spieler vergleichen")
        self.compare_btn.clicked.connect(self._open_player_comparison)
        header.addWidget(self.compare_btn)

        local_player = self.storage.get_player(self.player_id) or {}
        self.sell_btn = QPushButton("VERKAUFEN")
        self.sell_btn.setObjectName("Primary")
        self.sell_btn.setToolTip("Spieler in Kickbase auf den Transfermarkt setzen oder Preis ändern")
        self.sell_btn.clicked.connect(self._open_sell_player)
        self.sell_btn.setVisible(str(local_player.get("player_status") or "") == "KADER")
        header.addWidget(self.sell_btn)

        self.status_badge = QLabel(player_status_label(self.player))
        self.status_badge.setObjectName("PlayerStatusBadge")
        self.status_badge.setPixmap(QPixmap())
        self.status_badge.setToolTip(player_status_tooltip(self.player))
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setProperty("status", str(player_status_code(self.player)))
        self.status_badge.setText(f"  {player_status_label(self.player)}  ")
        header.addWidget(self.status_badge)

        role = QLabel((self.player.get("player_role") or "OFFEN").replace("_", " "))
        role.setObjectName("PlayerRoleBadge")
        role.setAlignment(Qt.AlignCenter)
        header.addWidget(role)
        root.addLayout(header)

        self.player_hub_tabs = QTabWidget()
        self.player_hub_tabs.setObjectName("V4SegmentTabs")
        overview_tab = QWidget()
        market_tab = QWidget()
        transfers_tab = QWidget()
        performance_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)
        market_layout = QVBoxLayout(market_tab)
        transfers_layout = QVBoxLayout(transfers_tab)
        performance_layout = QVBoxLayout(performance_tab)
        for tab_layout in (overview_layout, market_layout, transfers_layout, performance_layout):
            tab_layout.setContentsMargins(0, 10, 0, 0)
            tab_layout.setSpacing(12)
        self.player_hub_tabs.addTab(overview_tab, "ÜBERSICHT")
        self.player_hub_tabs.addTab(market_tab, "MARKTWERT")
        self.player_hub_tabs.addTab(transfers_tab, "TRANSFERS")
        self.player_hub_tabs.addTab(performance_tab, "PERFORMANCE")

        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        performance_cards_grid = QGridLayout()
        performance_cards_grid.setHorizontalSpacing(10)
        performance_cards_grid.setVerticalSpacing(10)

        market_value = int(self.player.get("market_value") or 0)
        entry = self.player.get("entry_value")
        entry = int(entry) if entry is not None else None
        pnl = market_value - entry if entry is not None else None
        roi = (pnl / entry * 100.0) if pnl is not None and entry else None
        season_started = bool(
            self.league_id
            and self.storage.get_league_setting(str(self.league_id), "season_started", "0") == "1"
        )
        average = self.player.get("average_points") if season_started else None
        average = int(average) if average is not None else None
        total = self.player.get("points_total") if season_started else None
        total = int(total) if total is not None else None
        points_per_million = (average / (market_value / 1_000_000)) if average is not None and market_value else None

        self.market_card = MetricCard("MARKTWERT", euro(market_value), self._trend_hint())
        self.entry_card = MetricCard(
            "EINSTIEG",
            euro(entry),
            "Kaufpreis" if self.player.get("origin") == "TRANSFER" else "Startkaderwert",
        )
        self.pnl_card = MetricCard("OFFENES P/L", delta_text(pnl), f"ROI {percent(roi)}")
        set_delta_label(self.pnl_card.value_label, pnl)
        stats_hint = (
            f"Gesamt {total if total is not None else '–'}"
            if season_started
            else "Preseason · aktuelle Saisonstats noch nicht verfügbar"
        )
        self.avg_card = MetricCard("Ø PUNKTE", str(average) if average is not None else "–", stats_hint)
        self.efficiency_card = MetricCard(
            "PUNKTE / MIO.",
            f"{points_per_million:.1f}" if points_per_million is not None else "–",
            "Ø Punkte je Mio. Marktwert",
        )
        self.change_card = MetricCard(
            "7-TAGE TREND",
            delta_text(self.analytics.get("d7"), compact=True),
            f"24h {delta_text(self.analytics.get('d1'), compact=True)}",
        )
        set_delta_label(self.change_card.value_label, self.analytics.get("d7"))

        owner_value, owner_hint = self._ownership_text()
        self.owner_card = MetricCard("BESITZER", owner_value, owner_hint)
        league_deals = transfer_price_history(
            self.storage.league_all_manager_transfer_rows(str(self.league_id), since=current_season_start().isoformat()) if self.league_id else [],
            self.player_id,
        )
        deal_avg = league_deals.get("average_price")
        deal_count = int(league_deals.get("count") or 0)
        deal_hint = (
            f"{deal_count} Liga-Deals · zuletzt {euro(league_deals.get('last_price'))}"
            if deal_count else "noch keine Liga-Deals erfasst"
        )
        self.deals_card = MetricCard("LIGA-KAUFPREIS Ø", euro(deal_avg) if deal_avg is not None else "–", deal_hint)
        self.form_card = MetricCard("FORM · LETZTE 3", "–", "wird live geladen")
        self.risk_card = MetricCard("KONSTANZ", "–", "letzte 5 Spiele")

        overview_cards = [
            self.market_card, self.entry_card, self.pnl_card, self.owner_card,
            self.change_card, self.deals_card,
        ]
        for index, card in enumerate(overview_cards):
            cards.addWidget(card, index // 3, index % 3)
            cards.setColumnStretch(index % 3, 1)
        overview_layout.addLayout(cards)

        performance_cards = [self.avg_card, self.efficiency_card, self.form_card, self.risk_card]
        for index, card in enumerate(performance_cards):
            performance_cards_grid.addWidget(card, index // 2, index % 2)
            performance_cards_grid.setColumnStretch(index % 2, 1)
        performance_layout.addLayout(performance_cards_grid)

        points_panel = ChartPanel(
            "PUNKTE PRO SPIELTAG",
            "Konstante Balkenbreite wie in der Kickbase-App · Höhe und Farbe richten sich nach der Punktezahl",
            height=320,
        )
        points_panel.setMinimumHeight(315)
        points_panel.setMaximumHeight(390)
        points_panel.chart_view.hide()
        self.performance_chart_panel = points_panel
        self.performance_bars = PerformanceMatchBarsWidget(
            club_icon_provider=club_icon,
            display_date_fn=display_date,
        )
        self.performance_bars.matchActivated.connect(self._open_performance_match)
        self.performance_chart_scroll = QScrollArea()
        self.performance_chart_scroll.setObjectName("PerformanceChartScroll")
        self.performance_chart_scroll.setWidget(self.performance_bars)
        self.performance_chart_scroll.setWidgetResizable(False)
        self.performance_chart_scroll.setFrameShape(QFrame.NoFrame)
        self.performance_chart_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.performance_chart_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.performance_chart_scroll.setStyleSheet("background: transparent; border: none;")
        points_panel.layout().insertWidget(2, self.performance_chart_scroll, 1)
        self._set_performance_chart(self.performance_bars, [], enabled=season_started)
        performance_layout.addWidget(points_panel, 1)

        performance_note = QLabel(
            "Klick auf einen Balken öffnet die originale Kickbase-Punkte-Aufschlüsselung des Spiels. "
            "Die Match-ID kommt aus /players/{id}/performance, die Events aus dem Playercenter und die "
            "Eventnamen dynamisch aus /v4/live/eventtypes. Nicht als Event ausgewiesene Restpunkte werden "
            "separat gezeigt und nicht geraten."
        )
        performance_note.setObjectName("Subtle")
        performance_note.setWordWrap(True)
        performance_layout.addWidget(performance_note)
        performance_layout.addStretch()

        # Compact, action-oriented sale decision. It stays separate from the metric
        # grid so the detail view does not grow another full card row.
        self.sale_decision_panel = QFrame()
        self.sale_decision_panel.setObjectName("SaleDecisionPanel")
        sale_layout = QHBoxLayout(self.sale_decision_panel)
        sale_layout.setContentsMargins(14, 10, 14, 10)
        sale_layout.setSpacing(12)
        sale_title = QLabel("VERKAUFSENTSCHEIDUNG")
        sale_title.setObjectName("SectionMini")
        self.sale_verdict_label = QLabel("–")
        self.sale_verdict_label.setObjectName("SaleDecisionChip")
        self.sale_verdict_label.setProperty("tone", "muted")
        self.sale_reason_label = QLabel("Wird aus Kader, Marktwerttrend und verfügbaren Alternativen abgeleitet")
        self.sale_reason_label.setObjectName("Tiny")
        self.sale_reason_label.setWordWrap(False)
        sale_layout.addWidget(sale_title)
        sale_layout.addWidget(self.sale_verdict_label)
        sale_layout.addWidget(self.sale_reason_label, 1)
        overview_layout.addWidget(self.sale_decision_panel)
        self._refresh_sale_decision()

        chart_panel = ChartPanel(
            "MARKTWERTVERLAUF",
            "Tägliche Snapshots seit der ersten Erfassung in KickTrack",
        )
        chart_panel.setMinimumHeight(250)
        chart_panel.setMaximumHeight(340)
        chart_panel.chart_view.setMinimumHeight(180)
        self.history_chart_view = chart_panel.chart_view
        self._set_history_chart(self.history_chart_view)
        market_layout.addWidget(chart_panel, 1)
        market_hint = QLabel("Der Verlauf verwendet echte gespeicherte Kickbase-Marktwerte; keine interpolierten Fantasiewerte.")
        market_hint.setObjectName("Tiny")
        market_hint.setWordWrap(True)
        market_layout.addWidget(market_hint)

        footer = QHBoxLayout()
        purchased = QLabel(self._purchase_text())
        purchased.setObjectName("Tiny")
        purchased.setWordWrap(True)
        footer.addWidget(purchased, 1)
        overview_layout.addLayout(footer)
        overview_layout.addStretch()

        transfer_panel = QFrame()
        transfer_panel.setObjectName("Panel")
        transfer_panel_layout = QVBoxLayout(transfer_panel)
        transfer_panel_layout.setContentsMargins(16, 14, 16, 14)
        transfer_panel_layout.setSpacing(6)
        transfer_title = QLabel("LIGA-TRANSFERKONTEXT")
        transfer_title.setObjectName("SectionMini")
        transfer_value = QLabel(euro(deal_avg) if deal_avg is not None else "Noch keine Liga-Deals erfasst")
        transfer_value.setObjectName("CardValue")
        transfer_meta = QLabel(deal_hint)
        transfer_meta.setObjectName("Tiny")
        transfer_meta.setWordWrap(True)
        transfer_panel_layout.addWidget(transfer_title)
        transfer_panel_layout.addWidget(transfer_value)
        transfer_panel_layout.addWidget(transfer_meta)
        transfers_layout.addWidget(transfer_panel)
        purchase_context = QLabel(self._purchase_text())
        purchase_context.setObjectName("Subtle")
        purchase_context.setWordWrap(True)
        transfers_layout.addWidget(purchase_context)
        transfers_layout.addStretch()

        root.addWidget(self.player_hub_tabs, 1)

        # Local snapshots are deliberately only a fallback. For any player opened
        # while online, Kickbase's own history endpoint can provide the actual
        # league market-value history even if KickTrack never owned the player.
        self._load_remote_history()

    def _refresh_sale_decision(self) -> None:
        # Build the same transparent decision used by the Kader table. For a
        # non-owned player there is no meaningful sell decision, so hide it.
        current = self.storage.get_player(self.player_id)
        if not current or str(current.get("player_status") or "") != "KADER":
            self.sale_decision_panel.hide()
            return
        squad = []
        for row in self.storage.current_players():
            item = dict(row)
            analytics = self.storage.analytics(str(item.get("player_id") or ""))
            item.update({
                "d1": analytics.get("d1"),
                "d3": analytics.get("d3"),
                "d7": analytics.get("d7"),
                "d14": analytics.get("d14"),
                "trend_acceleration": analytics.get("trend_acceleration"),
            })
            entry = item.get("entry_value")
            mv = int(item.get("market_value") or 0)
            if entry:
                item["roi"] = (mv - int(entry)) / int(entry) * 100.0
            squad.append(item)

        market_rows = []
        widget = self.parentWidget()
        while widget is not None:
            rows = getattr(widget, "_market_rows", None)
            if rows is not None:
                market_rows = rows or []
                break
            widget = widget.parentWidget()
        budget = self.storage.dashboard_metrics(self.league_id).get("budget") if self.league_id else None
        season_started = bool(
            self.league_id
            and self.storage.get_league_setting(str(self.league_id), "season_started", "0") == "1"
        )
        enriched = enrich_squad_entries(
            squad, points_are_current=season_started, market_rows=market_rows, available_budget=budget
        )
        decision = next((row for row in enriched if str(row.get("player_id")) == str(self.player_id)), None)
        if not decision:
            self.sale_decision_panel.hide()
            return
        verdict = str(decision.get("sell_verdict") or "HALTEN")
        tone = "negative" if verdict in {"JETZT VERKAUFEN", "EHER VERKAUFEN"} else "warning" if verdict == "VERKAUF PRÜFEN" else "positive"
        self.sale_verdict_label.setText(verdict)
        self.sale_verdict_label.setProperty("tone", tone)
        refresh_style(self.sale_verdict_label)
        replacement = decision.get("sell_replacement_player") or {}
        if replacement:
            name = replacement.get("full_name") or replacement.get("name") or "Alternative"
            self.sale_reason_label.setText(f"Finanzierbare Alternative: {name}")
        elif verdict == "HALTEN":
            self.sale_reason_label.setText("Aktuell kein starkes Verkaufssignal")
        else:
            self.sale_reason_label.setText("Trend, Ersetzbarkeit und Kapitalwirkung sprechen für Prüfung")
        tip = decision.get("sell_decision_text") or ""
        self.sale_verdict_label.setToolTip(tip)
        self.sale_reason_label.setToolTip(tip)
        self.sale_decision_panel.show()

    def _update_club_crest(self) -> None:
        icon = club_icon(self.player.get("club"))
        self.crest_label.clear()
        if not icon.isNull():
            self.crest_label.setPixmap(icon.pixmap(34, 34))

    def _resolve_client(self, parent):
        widget = parent
        while widget is not None:
            client = getattr(widget, "client", None)
            if client is not None:
                return client
            try:
                widget = widget.parent()
            except Exception:
                break
        return None

    @staticmethod
    def _merge_non_empty(target: dict, source: dict | None) -> None:
        if not isinstance(source, dict):
            return
        for key, value in source.items():
            if value is not None and value != "":
                target[key] = value

    def _resolve_player_data(self, player_data: dict | None) -> dict:
        """Merge local, league-wide and view-specific data instead of discarding richer rows.

        Previously ``storage.get_player() or player_data`` meant that any sparse
        historical row in ``players`` completely hid the richer market/manager
        payload. That was especially visible for players the user does not own.
        """
        merged: dict = {}
        self._merge_non_empty(merged, self.storage.get_player(self.player_id))
        if self.league_id:
            self._merge_non_empty(merged, self.storage.league_player(str(self.league_id), self.player_id))
        self._merge_non_empty(merged, player_data)
        merged.setdefault("player_id", self.player_id)
        return merged

    def _watchlist_league_id(self) -> str:
        return str(self.league_id or self.storage.get_setting("league_id") or "")

    def _refresh_watchlist_button(self) -> None:
        league_id = self._watchlist_league_id()
        active = bool(league_id and self.storage.is_watchlisted(league_id, self.player_id))
        self.watchlist_btn.setText("★ WATCHLIST" if active else "☆ WATCHLIST")
        self.watchlist_btn.setProperty("active", active)
        self.watchlist_btn.style().unpolish(self.watchlist_btn)
        self.watchlist_btn.style().polish(self.watchlist_btn)

    def _open_sell_player(self) -> None:
        if not self.league_id or self.client is None:
            QMessageBox.warning(self, "Verkaufen", "Keine aktive Liga bzw. Kickbase-Verbindung verfügbar.")
            return
        market_value = int(self.player.get("market_value") or 0)
        dialog = SellPlayerDialog(self, self.player, initial_price=market_value)
        if dialog.exec() != QDialog.Accepted:
            return
        amount = int(dialog.amount or 0)
        name = str(self.player.get("full_name") or self.player.get("name") or "Spieler")
        answer = QMessageBox.question(
            self,
            "Spieler wirklich anbieten?",
            f"{name} wird jetzt in Kickbase auf den Transfermarkt gesetzt.\n\n"
            f"Listenpreis: {euro(amount)}\n"
            f"Aktueller Marktwert: {euro(market_value)}\n\n"
            "Diese Aktion schreibt direkt in deine Kickbase-Liga. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            result = self.client.list_player_for_sale(str(self.league_id), self.player_id, amount)
        except Exception as exc:
            QMessageBox.warning(self, "Verkauf fehlgeschlagen", str(exc))
            return
        if result.get("price_set"):
            QMessageBox.information(self, "Spieler angeboten", f"{name} wurde für {euro(amount)} angeboten.")
        else:
            QMessageBox.warning(
                self,
                "Spieler angeboten · Preis prüfen",
                str(result.get("warning") or (
                    f"{name} wurde angeboten, der gewünschte Listenpreis {euro(amount)} konnte "
                    "aber noch nicht bestätigt werden. Bitte Markt aktualisieren und den Preis prüfen."
                )),
            )
        host = self.window()
        parent = self.parent()
        for candidate in (host, parent, getattr(parent, "parent", lambda: None)() if parent else None):
            if candidate is not None and hasattr(candidate, "_load_market_overview"):
                candidate._load_market_overview()
                break

    def _toggle_watchlist(self) -> None:
        league_id = self._watchlist_league_id()
        if not league_id:
            QMessageBox.information(self, "Watchlist", "Bitte zuerst eine Liga auswählen.")
            return
        active = self.storage.is_watchlisted(league_id, self.player_id)
        self.storage.set_watchlisted(league_id, self.player_id, not active)
        self._refresh_watchlist_button()

    def _open_player_comparison(self) -> None:
        dialog = PlayerComparisonDialog(
            self, self.storage, self.player_id, self._watchlist_league_id(), self.player
        )
        dialog.exec()

    def _load_remote_history(self) -> None:
        if not self.client or not self.league_id or self._history_worker is not None:
            return
        def load_remote_player_payload():
            details = self.client.player_details(str(self.league_id), self.player_id)
            performance = {}
            try:
                performance = self.client.player_performance(str(self.league_id), self.player_id)
            except Exception:
                performance = {}
            return {
                "details": details,
                "history": self.client.market_value_history(str(self.league_id), self.player_id, 365),
                "performance": performance,
            }

        worker = FunctionWorker(load_remote_player_payload)
        self._history_worker = worker
        worker.signals.succeeded.connect(self._remote_history_loaded)
        worker.signals.finished.connect(self._remote_history_finished)
        QThreadPool.globalInstance().start(worker)

    @staticmethod
    def _normalize_remote_history(payload) -> list[dict]:
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = []
            for key in ("it", "items", "values", "history", "marketValues", "marketValueHistory"):
                candidate = payload.get(key)
                if isinstance(candidate, list):
                    items = candidate
                    break
            if not items and isinstance(payload.get("data"), dict):
                return PlayerDetailDialog._normalize_remote_history(payload["data"])
        else:
            return []

        normalized: list[dict] = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            raw_value = None
            for key in ("mv", "v", "value", "marketValue", "market_value"):
                if entry.get(key) is not None:
                    raw_value = entry.get(key)
                    break
            try:
                value = int(float(raw_value))
            except (TypeError, ValueError):
                continue

            raw_date_value = None
            for key in ("d", "date", "dt", "timestamp", "createdAt", "created_at"):
                if entry.get(key) is not None:
                    raw_date_value = entry.get(key)
                    break
            if raw_date_value is None:
                continue

            raw_date = str(raw_date_value)
            date_part = raw_date[:10]
            if len(date_part) != 10 or date_part[4:5] != "-":
                # Some API variants expose Unix seconds / milliseconds.
                try:
                    numeric_date = float(raw_date_value)
                    if 1_000 <= numeric_date < 1_000_000:
                        # Kickbase market-value history currently returns an
                        # epoch-day integer (e.g. 20418), not a Unix timestamp.
                        date_part = (datetime(1970, 1, 1) + timedelta(days=int(numeric_date))).date().isoformat()
                    else:
                        timestamp = numeric_date
                        if timestamp > 10_000_000_000:
                            timestamp /= 1000.0
                        date_part = datetime.fromtimestamp(timestamp).date().isoformat()
                except (TypeError, ValueError, OSError, OverflowError):
                    continue
            normalized.append({"value": value, "snapshot_date": date_part, "recorded_at": raw_date})

        by_date = {entry["snapshot_date"]: entry for entry in normalized}
        return [by_date[key] for key in sorted(by_date)]

    def _remote_history_loaded(self, payload) -> None:
        if isinstance(payload, dict):
            performance_payload = payload.get("performance") or {}
            form = player_form(performance_payload)
            season_started_for_performance = bool(
                self.league_id
                and self.storage.get_league_setting(str(self.league_id), "season_started", "0") == "1"
            )
            self._set_performance_chart(
                self.performance_bars,
                form.get("matches") or [],
                enabled=season_started_for_performance,
            )
            if form.get("avg3") is not None:
                self.form_card.value_label.setText(f"{form['avg3']:.0f}")
                season_avg = form.get("avg")
                trend = form.get("trend")
                hint = f"Saison Ø {season_avg:.0f}" if season_avg is not None else "letzte 3 Spiele"
                if trend is not None:
                    hint += f" · Trend {trend:+.0f}"
                self.form_card.hint_label.setText(hint)
            else:
                self.form_card.value_label.setText("–")
                self.form_card.hint_label.setText("noch keine aktuellen Spiele")
            self.risk_card.value_label.setText(str(form.get("risk") or "–"))
            vol = form.get("volatility")
            floor, ceiling = form.get("robust_floor", form.get("floor")), form.get("robust_ceiling", form.get("ceiling"))
            if vol is not None:
                floor_text = f"{floor:.0f}" if floor is not None else "–"
                ceiling_text = f"{ceiling:.0f}" if ceiling is not None else "–"
                hit100 = form.get("hit100")
                hint = f"robuster Bereich {floor_text}–{ceiling_text} P"
                if hit100 is not None:
                    hint += f" · ≥100 in {hit100:.0f}%"
                self.risk_card.hint_label.setText(hint)
            else:
                self.risk_card.hint_label.setText("zu wenige Spiele")
        details = payload.get("details") if isinstance(payload, dict) else None
        history_payload = payload.get("history") if isinstance(payload, dict) else payload
        if isinstance(details, dict) and details:
            self._merge_non_empty(self.player, details)
            display_name = self.player.get("full_name") or self.player.get("name") or "Spieler"
            self.title_label.setText(str(display_name))
            self.setWindowTitle(f"{display_name} — Spieleranalyse")
            self.meta_label.setText(self._meta_text())
            self._update_club_crest()
            self.status_badge.setText(f"  {player_status_label(self.player)}  ")
            self.status_badge.setToolTip(player_status_tooltip(self.player))
            self.status_badge.setProperty("status", str(player_status_code(self.player)))
            self.status_badge.style().unpolish(self.status_badge)
            self.status_badge.style().polish(self.status_badge)
            if self.embedded and isinstance(self.parent(), QTabWidget):
                idx = self.parent().indexOf(self)
                if idx >= 0:
                    self.parent().setTabText(idx, str(display_name))
                    icon = club_icon(self.player.get("club"))
                    if not icon.isNull():
                        self.parent().setTabIcon(idx, icon)

            live_market = self.player.get("market_value")
            if live_market is not None:
                self.market_card.value_label.setText(euro(live_market))
            self.analytics["d1"] = self.player.get("daily_change")

            season_started = bool(
                self.league_id
                and self.storage.get_league_setting(str(self.league_id), "season_started", "0") == "1"
            )
            if season_started:
                avg = self.player.get("average_points")
                total = self.player.get("points_total")
                self.avg_card.value_label.setText(str(avg) if avg is not None else "–")
                self.avg_card.hint_label.setText(f"Gesamt {total if total is not None else '–'}")
                market_value = int(self.player.get("market_value") or 0)
                ppm = (float(avg) / (market_value / 1_000_000)) if avg is not None and market_value else None
                self.efficiency_card.value_label.setText(f"{ppm:.1f}" if ppm is not None else "–")

        remote = self._normalize_remote_history(history_payload)
        if not remote:
            # Even without history, the player-detail endpoint above may have
            # refreshed the current 24h movement and stats.
            d1 = self.player.get("daily_change")
            self.market_card.hint_label.setText(
                f"24h {delta_text(d1, compact=True)}" if d1 is not None else "Noch keine 24h-Dynamik"
            )
            return
        self.history = remote
        self._set_history_chart(self.history_chart_view)

        latest = int(remote[-1].get("value") or 0)
        if latest:
            self.market_card.value_label.setText(euro(latest))

        def delta_days(days: int) -> int | None:
            if not remote:
                return None
            latest_date = datetime.fromisoformat(remote[-1]["snapshot_date"]).date()
            target = latest_date.toordinal() - days
            comparison = None
            for entry in remote:
                entry_date = datetime.fromisoformat(entry["snapshot_date"]).date()
                if entry_date.toordinal() <= target:
                    comparison = entry
            if comparison is None:
                return None
            return latest - int(comparison.get("value") or 0)

        d1 = delta_days(1)
        d7 = delta_days(7)
        self.analytics["d1"] = d1
        self.analytics["d7"] = d7
        self.market_card.hint_label.setText(
            f"24h {delta_text(d1, compact=True)}" if d1 is not None else "Noch keine 24h-Dynamik"
        )
        self.change_card.value_label.setText(delta_text(d7, compact=True))
        self.change_card.hint_label.setText(f"24h {delta_text(d1, compact=True)}")
        set_delta_label(self.change_card.value_label, d7)

    def _remote_history_finished(self) -> None:
        self._history_worker = None

    def _meta_text(self) -> str:
        pieces = [self.player.get("club") or "Unbekannter Verein", self.player.get("position") or "–"]
        return "  ·  ".join(pieces)

    def _ownership_text(self) -> tuple[str, str]:
        if not self.league_id:
            return "–", "Keine Liga ausgewählt"

        owner = self.storage.player_owner(str(self.league_id), self.player_id)
        if owner:
            if bool(owner.get("is_user")):
                return "DU", "Aktuell in deinem Kader"
            place = owner.get("place")
            hint = f"Liga-Platz {place}" if place is not None else "Manager der aktuellen Liga"
            return str(owner.get("manager_name") or "Manager"), hint

        # A player opened from the user's current squad is known to be owned by
        # the user even before the background league-wide ownership index has
        # finished its first sync.
        if self.player.get("player_status") == "KADER":
            own_manager_id = self.storage.get_league_setting(str(self.league_id), "manager_id")
            if own_manager_id:
                return "DU", "Aktuell in deinem Kader"

        complete = self.storage.league_ownership_is_fresh(
            str(self.league_id), LeagueAnalysisService.SQUAD_TTL
        )
        if complete:
            return "FREI", "Keinem Manager der Liga zugeordnet"

        covered, total = self.storage.ownership_coverage(str(self.league_id))
        if total:
            return "NOCH UNBEKANNT", f"Besitzdaten {covered}/{total} Manager synchronisiert"
        return "NOCH UNBEKANNT", "Liga-Besitz noch nicht synchronisiert"

    def _purchase_text(self) -> str:
        origin = self.player.get("origin") or "UNKNOWN"
        date_value = self.player.get("purchase_date")
        if origin == "TRANSFER":
            return f"Transfer · {display_date(date_value) if date_value else 'Datum unbekannt'}"
        if origin == "STARTKADER":
            return "Seit Ligastart im Kader"
        return "Einstiegsart noch nicht eindeutig ermittelt"

    def _trend_hint(self) -> str:
        d1 = self.analytics.get("d1")
        if d1 is None:
            return "Noch keine 24h-Dynamik"
        return f"24h {delta_text(d1, compact=True)}"

    @staticmethod
    def _style_chart_axis(axis, *, grid: bool = True) -> None:
        """Apply the shared chart-axis styling inside the player dialog.

        The dashboard owns a similarly named helper, but PlayerDetailDialog is a
        separate class and must not depend on MainWindow implementation details.
        Keeping this tiny helper local prevents the detail dialog from crashing
        after chart styling refactors.
        """
        axis.setLabelsColor(QColor("#A2ACB6"))
        axis.setLabelsFont(QFont(body_font_family(), 9))
        axis.setLineVisible(False)
        axis.setGridLineVisible(grid)
        if grid:
            axis.setGridLineColor(QColor("#20272D"))
        try:
            axis.setMinorGridLineVisible(False)
        except AttributeError:
            pass

    @staticmethod
    def _performance_team_label(value) -> str:
        if value is None:
            return ""
        if isinstance(value, dict):
            for key in ("name", "n", "teamName", "team_name", "shortName", "short_name"):
                if value.get(key):
                    return str(value.get(key))
            for key in ("id", "i", "teamId", "team_id"):
                if value.get(key) is not None:
                    return team_name(value.get(key))
            return ""
        raw = str(value).strip()
        if not raw:
            return ""
        return team_name(raw) if raw.isdigit() else raw

    def _set_performance_chart(self, widget: PerformanceMatchBarsWidget, matches: list[dict], *, enabled: bool) -> None:
        prepared = []
        for row in matches or []:
            try:
                day = int(row.get("day") or 0)
            except (TypeError, ValueError):
                day = 0
            if day <= 0 or row.get("points") is None:
                continue
            home_name = self._performance_team_label(row.get("opponent_home"))
            away_name = self._performance_team_label(row.get("opponent_away"))
            home_goals = row.get("home_goals")
            away_goals = row.get("away_goals")
            score_text = "–"
            if home_goals is not None and away_goals is not None:
                score_text = f"{home_goals}:{away_goals}"
            fixture_text = ""
            if home_name and away_name:
                fixture_text = f"{home_name} {score_text if score_text != '–' else '–'} {away_name}"
            prepared_row = dict(row)
            prepared_row.update({
                "day": day,
                "home_name": home_name,
                "away_name": away_name,
                "score_text": score_text,
                "fixture_text": fixture_text,
            })
            prepared.append(prepared_row)

        prepared.sort(key=lambda row: int(row.get("day") or 0))
        season_title = next((str(row.get("season_title") or "").strip() for row in prepared if str(row.get("season_title") or "").strip()), "")
        if hasattr(self, "performance_chart_panel"):
            subtitle = "Konstante Balkenbreite wie in der Kickbase-App · Höhe und Farbe richten sich nach der Punktezahl"
            if season_title:
                subtitle += f" · Saison {season_title}"
            self.performance_chart_panel.subtitle.setText(subtitle)

        if prepared:
            widget.set_matches(prepared, enabled=True, message="")
            return

        if enabled:
            widget.set_matches([], enabled=False, message="Noch keine Spieltags-Punkte")
        else:
            widget.set_matches([], enabled=False, message="Noch keine Performance-Historie verfügbar")

    def _open_performance_match(self, row: dict) -> None:
        if not self.client or not self.league_id:
            QMessageBox.information(self, "Punkte-Aufschlüsselung", "Keine aktive Kickbase-Verbindung verfügbar.")
            return
        match_id = str(row.get("match_id") or "")
        if not match_id:
            QMessageBox.information(self, "Punkte-Aufschlüsselung", "Für dieses Spiel wurde keine Match-ID geliefert.")
            return
        if self._match_event_worker is not None:
            return

        league_id = str(self.league_id)
        player_id = str(self.player_id)
        match_cache_key = f"playercenter:{league_id}:{player_id}:{match_id}"
        event_type_cache_key = "live_event_types:v1"

        def load_match_breakdown():
            match_payload = self.storage.cache_get(match_cache_key, 30 * 24 * 3600)
            if match_payload is None:
                match_payload = self.client.player_match_center(league_id, player_id, match_id)
                self.storage.cache_set(match_cache_key, match_payload)

            event_type_payload = self.storage.cache_get(event_type_cache_key, 7 * 24 * 3600)
            if event_type_payload is None:
                event_type_payload = self.client.live_event_types()
                self.storage.cache_set(event_type_cache_key, event_type_payload)

            event_types = normalize_event_types(event_type_payload)
            return normalize_match_events(match_payload, event_types)

        worker = FunctionWorker(load_match_breakdown)
        self._match_event_worker = worker
        worker.signals.succeeded.connect(lambda summary: self._show_match_breakdown(summary, row))
        worker.signals.failed.connect(
            lambda message: QMessageBox.warning(
                self,
                "Punkte-Aufschlüsselung fehlgeschlagen",
                f"Kickbase konnte die Spielereignisse nicht laden.\n\n{message}",
            )
        )
        worker.signals.finished.connect(self._match_event_finished)
        QThreadPool.globalInstance().start(worker)

    def _show_match_breakdown(self, summary: dict, row: dict) -> None:
        dialog = MatchEventBreakdownDialog(self, summary, row)
        dialog.exec()

    def _match_event_finished(self) -> None:
        self._match_event_worker = None

    def _set_history_chart(self, view: QChartView) -> None:
        if not self.history:
            chart = QChart()
            chart.setBackgroundVisible(False)
            chart.setTitle("Noch keine Marktwert-Historie")
            chart.setTitleBrush(WHITE)
            chart.legend().setVisible(False)
            view.setChart(chart)
            return

        series = QLineSeries()
        series.setName("Marktwert")
        pen = QPen(ORANGE)
        pen.setWidth(2)
        series.setPen(pen)

        values: list[int] = []
        timestamps: list[int] = []
        for entry in self.history:
            raw_date = entry.get("snapshot_date") or (entry.get("recorded_at") or "")[:10]
            dt = QDateTime.fromString(raw_date, "yyyy-MM-dd")
            if not dt.isValid():
                continue
            timestamp = dt.toMSecsSinceEpoch()
            value = int(entry.get("value") or 0)
            series.append(timestamp, value / 1_000_000)
            timestamps.append(timestamp)
            values.append(value)

        if not timestamps:
            chart = QChart()
            chart.setBackgroundVisible(False)
            chart.setTitle("Noch keine verwertbare Marktwert-Historie")
            chart.setTitleBrush(WHITE)
            chart.legend().setVisible(False)
            view.setChart(chart)
            return

        # A single daily snapshot used to look like an empty chart. Always show
        # markers for short histories so the first datapoint is immediately visible.
        series.setPointsVisible(len(timestamps) <= 10)
        series.setMarkerSize(8.0)

        chart = QChart()
        chart.setBackgroundVisible(False)
        chart.setPlotAreaBackgroundVisible(False)
        chart.setMargins(QMargins(4, 4, 4, 4))
        chart.legend().setLabelColor(WHITE)
        chart.legend().setVisible(False)
        chart.addSeries(series)

        entry_value = self.player.get("entry_value")
        if entry_value is not None and timestamps:
            entry_series = QLineSeries()
            entry_series.setName("Einstieg")
            entry_pen = QPen(MUTED)
            entry_pen.setWidth(1)
            entry_pen.setStyle(Qt.DashLine)
            entry_series.setPen(entry_pen)
            first_x = min(timestamps)
            last_x = max(timestamps)
            if first_x == last_x:
                first_x -= 12 * 60 * 60 * 1000
                last_x += 12 * 60 * 60 * 1000
            entry_m = int(entry_value) / 1_000_000
            entry_series.append(first_x, entry_m)
            entry_series.append(last_x, entry_m)
            chart.addSeries(entry_series)
            chart.legend().setVisible(True)

        axis_x = QDateTimeAxis()
        axis_x.setFormat("dd.MM")
        axis_x.setTickCount(min(6, max(2, len(timestamps))))
        self._style_chart_axis(axis_x, grid=False)
        first_x = min(timestamps)
        last_x = max(timestamps)
        if first_x == last_x:
            first_x -= 12 * 60 * 60 * 1000
            last_x += 12 * 60 * 60 * 1000
        axis_x.setRange(QDateTime.fromMSecsSinceEpoch(first_x), QDateTime.fromMSecsSinceEpoch(last_x))

        axis_y = QValueAxis()
        self._style_chart_axis(axis_y, grid=True)
        low = min(values + ([int(entry_value)] if entry_value is not None else [])) / 1_000_000
        high = max(values + ([int(entry_value)] if entry_value is not None else [])) / 1_000_000
        span = high - low
        padding = max(0.05, span * 0.18, high * 0.0025)
        axis_y.setRange(max(0, low - padding), high + padding)
        if span < 0.10:
            axis_y.setLabelFormat("%.3f M")
        elif span < 1.0:
            axis_y.setLabelFormat("%.2f M")
        else:
            axis_y.setLabelFormat("%.1f M")
        axis_y.setTickCount(4)

        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        if entry_value is not None:
            entry_series.attachAxis(axis_x)
            entry_series.attachAxis(axis_y)

        history_popover = chart_hover_popover(view)

        def show_history_tooltip(point, state: bool) -> None:
            if not state:
                history_popover.hide_later()
                return
            dt = QDateTime.fromMSecsSinceEpoch(int(point.x()))
            history_popover.show_value(
                f"{dt.toString('dd.MM.yyyy')}\n{euro(int(round(point.y() * 1_000_000)))}",
                QCursor.pos(),
            )

        series.hovered.connect(show_history_tooltip)
        view.setChart(chart)



class PlayerComparisonDialog(QDialog):
    """Side-by-side factual player comparison without an aggregate winner score."""

    def __init__(self, parent, storage: Storage, player_id: str, league_id: str, player_data: dict | None = None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.league_id = str(league_id or "")
        self.left_id = str(player_id)
        self.left = self._player_row(self.left_id, player_data)
        self.setWindowTitle("Spieler vergleichen")
        self.resize(800, 610)
        self.setMinimumSize(680, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        title = QLabel("SPIELER-VERGLEICH")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Harte Daten nebeneinander · kein künstlicher Gesamtscore")
        subtitle.setObjectName("Subtle")
        root.addWidget(title)
        root.addWidget(subtitle)

        chooser_row = QHBoxLayout()
        left_name = QLabel(str(self.left.get("full_name") or self.left.get("name") or "Spieler"))
        left_name.setObjectName("SectionTitle")
        chooser_row.addWidget(left_name, 1)
        versus = QLabel("VS")
        versus.setObjectName("Tiny")
        chooser_row.addWidget(versus)
        self.target_combo = QComboBox()
        self.target_combo.setEditable(True)
        self.target_combo.setInsertPolicy(QComboBox.NoInsert)
        self._targets = []
        for row in storage.player_master_rows(state="ACTIVE"):
            pid = str(row.get("player_id") or "")
            if not pid or pid == self.left_id:
                continue
            self._targets.append(row)
            name = str(row.get("full_name") or row.get("name") or pid)
            suffix = " · ".join(x for x in [str(row.get("club") or ""), str(row.get("position") or "")] if x)
            self.target_combo.addItem(f"{name} — {suffix}" if suffix else name, pid)
        completer = self.target_combo.completer()
        if completer is not None:
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
        self.target_combo.currentIndexChanged.connect(self._refresh)
        chooser_row.addWidget(self.target_combo, 1)
        root.addLayout(chooser_row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["KENNZAHL", "SPIELER A", "SPIELER B"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        close_btn = QPushButton("SCHLIESSEN")
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, 0, Qt.AlignRight)
        self._refresh()

    def _player_row(self, player_id: str, preferred: dict | None = None) -> dict:
        merged = {}
        for source in (
            self.storage.player_master_row(player_id),
            self.storage.get_player(player_id),
            self.storage.league_player(self.league_id, player_id) if self.league_id else None,
            preferred,
        ):
            if isinstance(source, dict):
                for key, value in source.items():
                    if value is not None and value != "":
                        merged[key] = value
        merged.setdefault("player_id", player_id)
        return merged

    @staticmethod
    def _plain(value) -> str:
        return "–" if value is None or value == "" else str(value)

    def _facts(self, row: dict) -> dict[str, str]:
        pid = str(row.get("player_id") or "")
        analytics = self.storage.analytics(pid)
        owner = self.storage.player_owner(self.league_id, pid) if self.league_id else None
        season_started = bool(
            self.league_id and self.storage.get_league_setting(self.league_id, "season_started", "0") == "1"
        )
        facts = {
            "Spieler": str(row.get("full_name") or row.get("name") or "–"),
            "Verein": self._plain(row.get("club")),
            "Position": self._plain(row.get("position")),
            "Marktwert": euro(row.get("market_value")),
            "24H": delta_text(analytics.get("d1"), compact=True),
            "3 Tage": delta_text(analytics.get("d3"), compact=True),
            "7 Tage": delta_text(analytics.get("d7"), compact=True),
            "30 Tage": delta_text(analytics.get("d30"), compact=True),
            "Besitzer": str(owner.get("manager_name") or "FREI") if owner else "–",
            "Status": player_status_label(row),
        }
        if season_started:
            facts["Ø Punkte"] = self._plain(row.get("average_points"))
            facts["Gesamtpunkte"] = self._plain(row.get("points_total"))
        return facts

    def _refresh(self, *_args) -> None:
        target_id = str(self.target_combo.currentData() or "")
        if not target_id:
            self.table.setRowCount(0)
            return
        right = self._player_row(target_id)
        left_facts = self._facts(self.left)
        right_facts = self._facts(right)
        keys = list(left_facts.keys())
        for key in right_facts:
            if key not in keys:
                keys.append(key)
        self.table.setRowCount(len(keys))
        for r, key in enumerate(keys):
            self.table.setItem(r, 0, QTableWidgetItem(key))
            self.table.setItem(r, 1, QTableWidgetItem(left_facts.get(key, "–")))
            self.table.setItem(r, 2, QTableWidgetItem(right_facts.get(key, "–")))


class PlayerDetailTabsWindow(QMainWindow):
    """Non-modal detail workspace: one tab per player, reusable across all views."""

    def __init__(self, parent, storage: Storage) -> None:
        super().__init__(parent)
        self.storage = storage
        # Keep the player workspace as a normal independent top-level window.
        # This avoids native window stacking quirks when it is opened from the
        # also non-modal manager detail window.
        self.setWindowModality(Qt.NonModal)
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
        )
        self.setWindowTitle("KickTrack — Spielerdetails")
        self.resize(1080, 860)
        self.setMinimumSize(900, 700)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.setCentralWidget(self.tabs)
        self._player_tabs: dict[str, QWidget] = {}

    def open_player(self, player_id: str, league_id: str | None = None, player_data: dict | None = None) -> None:
        key = f"{league_id or ''}:{player_id}"
        existing = self._player_tabs.get(key)
        if existing is not None:
            idx = self.tabs.indexOf(existing)
            if idx >= 0:
                self.tabs.setCurrentIndex(idx)
        else:
            detail = PlayerDetailDialog(
                self.tabs, self.storage, str(player_id), league_id, player_data=player_data, embedded=True
            )
            name = detail.player.get("full_name") or detail.player.get("name") or "Spieler"
            icon = club_icon(detail.player.get("club"))
            idx = self.tabs.addTab(detail, icon, str(name)) if not icon.isNull() else self.tabs.addTab(detail, str(name))
            self.tabs.setCurrentIndex(idx)
            self._player_tabs[key] = detail
            detail.destroyed.connect(lambda *_args, k=key: self._player_tabs.pop(k, None))
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        # On Windows the originating double-click can return activation to the
        # manager window after this slot finishes. Re-raise on the next event
        # loop iteration so the player workspace reliably becomes visible.
        QTimer.singleShot(0, self._bring_to_front)

    def _bring_to_front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _close_tab(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is None:
            return
        self.tabs.removeTab(index)
        for key, value in list(self._player_tabs.items()):
            if value is widget:
                self._player_tabs.pop(key, None)
                break
        widget.deleteLater()
        if self.tabs.count() == 0:
            self.hide()


def open_player_detail_window(parent, storage: Storage, player_id: str, league_id: str | None = None, player_data: dict | None = None) -> None:
    widget = parent
    while widget is not None:
        opener = getattr(widget, "open_player_detail_tab", None)
        if callable(opener):
            opener(player_id, league_id, player_data)
            return
        try:
            widget = widget.parent()
        except Exception:
            widget = None
    # Defensive fallback for isolated dialogs/tests.
    dialog = PlayerDetailDialog(parent, storage, player_id, league_id, player_data=player_data)
    dialog.show()
    dialog.setAttribute(Qt.WA_DeleteOnClose, True)


class LoginDialog(QDialog):
    def __init__(self, parent, storage: Storage, client: KickbaseClient) -> None:
        super().__init__(parent)
        self.storage = storage
        self.client = client
        self.setWindowTitle("Kickbase Login")
        self.setMinimumWidth(470)

        logo = KickbaseLogo()
        subtitle = QLabel("Verbinde deinen Kickbase-Account")
        subtitle.setObjectName("Subtle")

        self.email = QLineEdit()
        self.email.setPlaceholderText("E-Mail")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Passwort")
        self.password.setEchoMode(QLineEdit.Password)
        self.remember = QCheckBox("Login merken (System-Keyring)")
        self.login_btn = QPushButton("ANMELDEN")
        self.login_btn.setObjectName("Primary")
        self.login_btn.clicked.connect(self.do_login)

        saved_email = self.storage.get_setting("email", "")
        if saved_email:
            self.email.setText(saved_email)
            try:
                saved_password = keyring.get_password(SERVICE, saved_email)
                if saved_password:
                    self.password.setText(saved_password)
                    self.remember.setChecked(True)
            except Exception:
                pass

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 26, 28, 26)
        card_layout.setSpacing(14)
        card_layout.addWidget(logo)
        card_layout.addWidget(subtitle)
        card_layout.addSpacing(6)
        card_layout.addWidget(self.email)
        card_layout.addWidget(self.password)
        card_layout.addWidget(self.remember)
        card_layout.addSpacing(4)
        card_layout.addWidget(self.login_btn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        outer.addWidget(card)

    def do_login(self) -> None:
        email = self.email.text().strip()
        password = self.password.text()
        if not email or not password:
            QMessageBox.warning(self, "Fehlt noch was", "Bitte E-Mail und Passwort eingeben.")
            return

        self.login_btn.setEnabled(False)
        self.login_btn.setText("VERBINDE …")
        self.email.setEnabled(False)
        self.password.setEnabled(False)

        worker = FunctionWorker(lambda: self.client.login(email, password))
        self._login_worker = worker
        worker.signals.succeeded.connect(
            lambda _result: self._login_succeeded(email, password)
        )
        worker.signals.failed.connect(self._login_failed)
        QThreadPool.globalInstance().start(worker)

    def _login_succeeded(self, email: str, password: str) -> None:
        self.storage.set_setting("email", email)
        try:
            if self.remember.isChecked():
                keyring.set_password(SERVICE, email, password)
            else:
                try:
                    keyring.delete_password(SERVICE, email)
                except Exception:
                    pass
        except Exception:
            # A keyring problem should not turn a successful Kickbase login into a failure.
            pass
        self.accept()

    def _login_failed(self, message: str) -> None:
        self.login_btn.setEnabled(True)
        self.login_btn.setText("ANMELDEN")
        self.email.setEnabled(True)
        self.password.setEnabled(True)
        QMessageBox.critical(self, "Login fehlgeschlagen", message)


class ManagerComparisonDialog(QDialog):
    """Side-by-side squad comparison without synthetic strength scores."""

    POSITION_LABELS = {"TW": "Tor", "ABW": "Abwehr", "MF": "Mittelfeld", "ST": "Sturm"}

    def __init__(
        self,
        parent,
        storage: Storage,
        league_id: str,
        own_manager: dict,
        opponent_manager: dict,
        own_players: list[dict],
        opponent_players: list[dict],
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.league_id = league_id
        self.own_manager = own_manager
        self.opponent_manager = opponent_manager
        self.own_players = own_players
        self.opponent_players = opponent_players
        self.own = summarize_squad(own_players)
        self.opponent = summarize_squad(opponent_players)
        self.season_started = str(self.storage.get_league_setting(self.league_id, "season_started", "0")) == "1"

        own_name = str(own_manager.get("name") or "Du")
        opponent_name = str(opponent_manager.get("name") or "Manager")
        self.setWindowTitle(f"{own_name} vs. {opponent_name} — Kadervergleich")
        self.resize(1120, 780)
        self.setMinimumSize(900, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        header = QHBoxLayout()
        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(2)
        title = QLabel(f"{own_name}  VS.  {opponent_name}")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Direkter Kadervergleich · aktuelle gecachte Ligadaten")
        subtitle.setObjectName("Subtle")
        title_wrap.addWidget(title)
        title_wrap.addWidget(subtitle)
        header.addLayout(title_wrap)
        header.addStretch()
        root.addLayout(header)

        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        metrics = [
            ("KADERWERT", self.own.market_value, self.opponent.market_value, euro),
            ("SPIELER", self.own.player_count, self.opponent.player_count, lambda value: str(value)),
            ("Ø PUNKTE", self.own.average_points if self.season_started else None, self.opponent.average_points if self.season_started else None, self._number_text),
            ("GESAMTPUNKTE", self.own.total_points if self.season_started else None, self.opponent.total_points if self.season_started else None, self._number_text),
        ]
        for column, (caption, left, right, formatter) in enumerate(metrics):
            cards.addWidget(self._comparison_card(caption, own_name, opponent_name, left, right, formatter), 0, column)
        root.addLayout(cards)

        section = QLabel("POSITIONSVERGLEICH")
        section.setObjectName("SectionTitle")
        root.addWidget(section)

        position_table = ResponsiveTableWidget()
        headers = ["POSITION", f"{own_name} SPIELER", f"{opponent_name} SPIELER", f"{own_name} WERT", f"{opponent_name} WERT", f"{own_name} Ø P", f"{opponent_name} Ø P"]
        widths = [140, 130, 150, 150, 170, 120, 140]
        position_table.setColumnCount(len(headers))
        position_table.setHorizontalHeaderLabels(headers)
        position_table.setRowCount(len(POSITIONS))
        position_table.setShowGrid(False)
        position_table.setAlternatingRowColors(True)
        position_table.verticalHeader().setVisible(False)
        position_table.verticalHeader().setDefaultSectionSize(44)
        position_table.setEditTriggers(QTableWidget.NoEditTriggers)
        position_table.setSelectionMode(QTableWidget.NoSelection)
        position_table.setFocusPolicy(Qt.NoFocus)
        position_table.set_responsive_widths(widths, [120, 110, 120, 130, 140, 100, 110])
        for row, position in enumerate(POSITIONS):
            own = self.own.positions[position]
            other = self.opponent.positions[position]
            values = [
                self.POSITION_LABELS[position],
                str(own.player_count),
                str(other.player_count),
                euro(own.market_value),
                euro(other.market_value),
                self._number_text(own.average_points) if self.season_started else "–",
                self._number_text(other.average_points) if self.season_started else "–",
            ]
            for col, text in enumerate(values):
                item = table_item(text, text)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col == 0 else Qt.AlignCenter)
                position_table.setItem(row, col, item)
        position_table.setMinimumHeight(48 * len(POSITIONS) + 58)
        root.addWidget(position_table)

        lists = QHBoxLayout()
        lists.setSpacing(12)
        lists.addWidget(self._top_players_panel("TOP NACH Ø PUNKTEN", own_name, opponent_name, "average_points"), 1)
        lists.addWidget(self._top_players_panel("TEUERSTE SPIELER", own_name, opponent_name, "market_value"), 1)
        root.addLayout(lists, 1)

    @staticmethod
    def _number_text(value) -> str:
        if value is None:
            return "–"
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "–"
        return f"{numeric:.1f}" if not numeric.is_integer() else str(int(numeric))

    def _comparison_card(self, caption, own_name, opponent_name, left, right, formatter) -> QFrame:
        frame = QFrame()
        frame.setObjectName("MetricCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(5)
        label = QLabel(caption)
        label.setObjectName("MetricCaption")
        layout.addWidget(label)
        left_label = QLabel(f"{own_name}:  {formatter(left) if left is not None else '–'}")
        left_label.setObjectName("MetricValue")
        left_label.setStyleSheet("font-size: 18px;")
        layout.addWidget(left_label)
        right_label = QLabel(f"{opponent_name}:  {formatter(right) if right is not None else '–'}")
        right_label.setObjectName("Subtle")
        layout.addWidget(right_label)
        return frame

    def _top_players_panel(self, caption: str, own_name: str, opponent_name: str, metric: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        title = QLabel(caption)
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        if metric == "average_points" and not self.season_started:
            note = QLabel("Noch keine aktuellen Saisonpunkte verfügbar.")
            note.setObjectName("Subtle")
            note.setAlignment(Qt.AlignCenter)
            layout.addWidget(note, 1)
            return frame

        table = ResponsiveTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["MANAGER", "SPIELER", "WERT"])
        rows: list[tuple[str, dict]] = []
        own_players = self.own.top_by_average_points if metric == "average_points" else self.own.top_by_market_value
        other_players = self.opponent.top_by_average_points if metric == "average_points" else self.opponent.top_by_market_value
        rows.extend((own_name, player) for player in own_players)
        rows.extend((opponent_name, player) for player in other_players)
        table.setRowCount(len(rows))
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(48)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.set_responsive_widths([145, 240, 130], [110, 165, 100])
        for row, (manager_name, player) in enumerate(rows):
            value = player.get(metric)
            value_text = euro(value) if metric == "market_value" else self._number_text(value)
            for col, text in enumerate((manager_name, str(player.get("name") or "–"), value_text)):
                item = table_item(text, text)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col < 2 else Qt.AlignCenter)
                table.setItem(row, col, item)
        layout.addWidget(table, 1)
        return frame


class ManagerTransferDialog(QDialog):
    """Observed transfer history and transparent trading KPIs for one manager."""

    def __init__(self, parent, storage: Storage, league_id: str, manager_id: str) -> None:
        super().__init__(parent)
        self.storage = storage
        self.league_id = league_id
        self.manager_id = manager_id
        self.manager = storage.get_league_manager(league_id, manager_id) or {}
        self.events = storage.league_manager_transfer_rows(
            league_id, manager_id, since=current_season_start().isoformat()
        )
        self.behavior = analyze_manager_transfers(self.events)

        name = str(self.manager.get("name") or "Manager")
        self.setWindowTitle(f"{name} — Transferhistorie")
        self.resize(980, 720)
        self.setMinimumSize(800, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        header = QHBoxLayout()
        identity = QVBoxLayout()
        identity.setSpacing(2)
        title = QLabel(f"{name} · TRANSFERS")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            f"Saison {season_label()} · beobachtete Käufe und Verkäufe · 15 Minuten SQLite-Cache"
        )
        subtitle.setObjectName("Subtle")
        identity.addWidget(title)
        identity.addWidget(subtitle)
        header.addLayout(identity)
        header.addStretch()
        root.addLayout(header)

        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        buy = MetricCard("KÄUFE", str(self.behavior.buy_count), f"Volumen {euro(self.behavior.buy_volume)}")
        sell = MetricCard("VERKÄUFE", str(self.behavior.sell_count), f"Volumen {euro(self.behavior.sell_volume)}")
        pnl = MetricCard("REALISIERTES TRADING P/L", delta_text(self.behavior.realized_pnl), f"{self.behavior.completed_trade_count} abgeschlossene Trades")
        set_delta_label(pnl.value_label, self.behavior.realized_pnl)
        holding_text = (f"{self.behavior.average_holding_days:.1f} Tage" if self.behavior.average_holding_days is not None else "–")
        holding = MetricCard("Ø HALTEDAUER", holding_text, "nur gepaarte Kauf/Verkauf-Trades")
        for col, card in enumerate((buy, sell, pnl, holding)):
            cards.addWidget(card, 0, col)
        root.addLayout(cards)

        insight = QFrame()
        insight.setObjectName("Card")
        insight_layout = QHBoxLayout(insight)
        insight_layout.setContentsMargins(18, 14, 18, 14)
        insight_layout.setSpacing(24)
        best = self.behavior.best_trade
        worst = self.behavior.worst_trade
        best_text = f"Bester Trade: {best.player_name} · {delta_text(best.pnl)}" if best else "Bester Trade: –"
        worst_text = f"Schwächster Trade: {worst.player_name} · {delta_text(worst.pnl)}" if worst else "Schwächster Trade: –"
        insight_layout.addWidget(QLabel(best_text))
        insight_layout.addWidget(QLabel(worst_text))
        insight_layout.addStretch()
        root.addWidget(insight)

        section = QLabel("TRANSFERHISTORIE")
        section.setObjectName("SectionTitle")
        root.addWidget(section)

        table = ResponsiveTableWidget()
        self.table = table
        headers = ["DATUM", "SPIELER", "VEREIN", "TYP", "PREIS", "TRADE P/L"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(44)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.set_responsive_widths([145, 220, 160, 100, 145, 145], [125, 170, 135, 85, 125, 125])

        pnl_by_sale = {
            (trade.player_id, trade.sold_at, trade.sell_price): trade.pnl
            for trade in self.behavior.completed_trades
        }
        table.setRowCount(len(self.events))
        for row, event in enumerate(self.events):
            transfer_type = str(event.get("transfer_type") or "")
            sale_key = (str(event.get("player_id") or ""), str(event.get("transferred_at") or ""), int(event.get("price") or 0))
            trade_pnl = pnl_by_sale.get(sale_key) if transfer_type == "SELL" else None
            values = [
                display_date(event.get("transferred_at")),
                str(event.get("player_name") or "–"),
                str(event.get("club") or "–"),
                "KAUF" if transfer_type == "BUY" else "VERKAUF",
                euro(event.get("price")),
                delta_text(trade_pnl) if trade_pnl is not None else "–",
            ]
            for col, text in enumerate(values):
                item = table_item(text, text, icon=club_icon(event.get("club")) if col == 2 else None)
                item.setData(Qt.UserRole, str(event.get("player_id") or ""))
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col in (0, 1, 2) else Qt.AlignCenter)
                if col == 3:
                    item.setForeground(ORANGE if transfer_type == "BUY" else WHITE)
                if col == 5 and trade_pnl is not None:
                    item.setForeground(GREEN if trade_pnl >= 0 else RED)
                table.setItem(row, col, item)
        table.itemDoubleClicked.connect(self._open_player_detail)
        root.addWidget(table, 1)

        if not self.events:
            empty = QLabel("Noch keine Transferereignisse für diesen Manager beobachtet.")
            empty.setObjectName("Subtle")
            empty.setAlignment(Qt.AlignCenter)
            root.addWidget(empty)

    def _open_player_detail(self, item: QTableWidgetItem) -> None:
        player_id = str(item.data(Qt.UserRole) or "")
        if not player_id:
            return
        event = next(
            (entry for entry in self.events if str(entry.get("player_id") or "") == player_id),
            None,
        )
        player_data = None
        if event:
            player_data = {
                "player_id": player_id,
                "name": event.get("player_name") or "Spieler",
                "club": event.get("club") or "",
                "team_id": event.get("team_id"),
            }
        open_player_detail_window(self, self.storage, player_id, self.league_id, player_data)


class ManagerDetailDialog(QDialog):
    """Read-only competitor overview backed by the local league cache."""

    def __init__(self, parent, storage: Storage, league_id: str, manager_id: str) -> None:
        super().__init__(parent)
        self.storage = storage
        self.league_id = league_id
        self.manager_id = manager_id
        self.manager = storage.get_league_manager(league_id, manager_id) or {}
        self.players = storage.manager_squad(league_id, manager_id)

        name = self.manager.get("name") or "Manager"
        self.setWindowTitle(f"{name} — Liga-Manager")
        # Do not make this a modal/dialog-stacked child of the main window.
        # A normal top-level window can freely move behind/in front of the
        # separate player-detail workspace.
        self.setWindowModality(Qt.NonModal)
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
        )
        self.resize(980, 700)
        self.setMinimumSize(780, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        header = QHBoxLayout()
        identity = QVBoxLayout()
        identity.setSpacing(2)
        title = QLabel(name)
        title.setObjectName("PageTitle")
        place = self.manager.get("place")
        meta = QLabel(f"Liga-Platz {place if place is not None else '–'} · {len(self.players)} Spieler")
        meta.setObjectName("Subtle")
        identity.addWidget(title)
        identity.addWidget(meta)
        header.addLayout(identity)
        header.addStretch()
        own_manager_id = self.storage.get_league_setting(self.league_id, "manager_id")
        if own_manager_id and str(own_manager_id) != str(self.manager_id):
            compare = QPushButton("MIT MIR VERGLEICHEN")
            compare.setObjectName("Primary")
            compare.clicked.connect(self._open_comparison)
            header.addWidget(compare)
        transfers = QPushButton("TRANSFERHISTORIE")
        transfers.clicked.connect(self._open_transfers)
        header.addWidget(transfers)
        root.addLayout(header)

        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        has_current_season_points = self.manager.get("points") is not None
        trade_rows = self.storage.league_manager_transfer_rows(
            self.league_id, self.manager_id, since=current_season_start().isoformat()
        )
        profile = trade_profile(trade_rows)
        card_data = [
            ("PUNKTE", self.manager.get("points"), "Gesamtpunkte"),
            ("KADERWERT", euro(self.manager.get("team_value")), "Kickbase Team Value"),
            (
                "Ø PUNKTE",
                self.manager.get("average_points") if has_current_season_points else None,
                "Kickbase Durchschnitt",
            ),
            (
                "SPIELTAGSSIEGE",
                self.manager.get("matchday_wins") if has_current_season_points else None,
                "Saison",
            ),
            ("HANDELSPROFIL", profile["label"], (
                f"{profile['count']} Transfers · P/L {delta_text(profile.get('realized_pnl'))}"
                + (f" · Ø {profile['avg_hold_days']:.1f} T gehalten" if profile.get('avg_hold_days') is not None else "")
            )),
        ]
        for index, (caption, value, hint) in enumerate(card_data):
            text = str(value) if value is not None else "–"
            cards.addWidget(MetricCard(caption, text, hint), 0, index)
        root.addLayout(cards)

        section = QLabel("KADER")
        section.setObjectName("SectionTitle")
        root.addWidget(section)

        table = ResponsiveTableWidget()
        self.table = table
        headers = ["SPIELER", "VEREIN", "POS", "MARKTWERT", "Ø PUNKTE", "PUNKTE"]
        widths = [240, 190, 75, 150, 120, 110]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(46)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.setSortingEnabled(False)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.set_responsive_widths(widths, [180, 150, 65, 125, 105, 95])
        table.setRowCount(len(self.players))

        for row, player in enumerate(self.players):
            specs = [
                (player.get("name") or "–", player.get("name") or ""),
                (player.get("club") or "–", player.get("club") or ""),
                (player.get("position") or "–", POSITION_SORT.get(player.get("position"), 99)),
                (euro(player.get("market_value")), player.get("market_value") or -1),
                (str(player.get("average_points")) if player.get("average_points") is not None else "–", player.get("average_points") if player.get("average_points") is not None else -1),
                (str(player.get("points_total")) if player.get("points_total") is not None else "–", player.get("points_total") if player.get("points_total") is not None else -1),
            ]
            for col, (text, sort_value) in enumerate(specs):
                item = table_item(text, sort_value, icon=club_icon(player.get("club")) if col == 1 else None)
                item.setData(Qt.UserRole, str(player.get("player_id") or ""))
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col in (0, 1) else Qt.AlignCenter)
                table.setItem(row, col, item)
        table.setItemDelegateForColumn(1, ClubItemDelegate(table))
        table.setSortingEnabled(True)
        table.itemDoubleClicked.connect(self._open_player_detail)
        root.addWidget(table, 1)

    def _open_transfers(self) -> None:
        ManagerTransferDialog(
            self, self.storage, self.league_id, self.manager_id
        ).exec()

    def _open_comparison(self) -> None:
        own_manager_id = self.storage.get_league_setting(self.league_id, "manager_id")
        if not own_manager_id:
            QMessageBox.information(self, "Vergleich nicht verfügbar", "Dein Manager konnte in dieser Liga nicht bestimmt werden.")
            return

        own_manager_id = str(own_manager_id)
        own_manager = self.storage.get_league_manager(self.league_id, own_manager_id) or {"manager_id": own_manager_id, "name": "Du", "is_user": 1}
        own_players = self.storage.manager_squad(self.league_id, own_manager_id)
        if not own_players:
            # The local squad is always available after the normal KickTrack sync,
            # even if the league-wide ownership cache has not covered our own
            # manager yet. Normalize it to the manager-squad shape.
            own_players = [
                {
                    "player_id": player.get("player_id"),
                    "name": player.get("name"),
                    "club": player.get("club"),
                    "team_id": player.get("team_id"),
                    "position": player.get("position"),
                    "market_value": player.get("market_value"),
                    "points_total": player.get("points_total"),
                    "average_points": player.get("average_points"),
                    "team_image": player.get("team_image"),
                }
                for player in self.storage.current_players()
            ]

        if not own_players:
            QMessageBox.information(self, "Vergleich nicht verfügbar", "Dein Kader ist noch nicht synchronisiert.")
            return
        if not self.players:
            QMessageBox.information(self, "Vergleich nicht verfügbar", "Der Kader dieses Managers ist noch nicht synchronisiert.")
            return

        ManagerComparisonDialog(
            self,
            self.storage,
            self.league_id,
            own_manager,
            self.manager,
            own_players,
            self.players,
        ).exec()

    def _open_player_detail(self, item: QTableWidgetItem) -> None:
        player_id = str(item.data(Qt.UserRole) or "")
        if not player_id:
            return
        player = next(
            (entry for entry in self.players if str(entry.get("player_id")) == player_id),
            None,
        )
        open_player_detail_window(self, self.storage, player_id, self.league_id, player)
        # Do not lower or otherwise manipulate the manager window here. On
        # Windows, lowering a top-level window can cause an unrelated window to
        # be promoted by the OS. The player workspace itself handles activation.



class SquadScoringInfoDialog(QDialog):
    """Explain the exact own-squad scoring model shown in the KADER tab."""

    def __init__(self, parent=None, *, points_are_current: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle("So funktioniert die Kader-Einschätzung")
        self.resize(780, 720)
        self.setMinimumSize(660, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel("KADER-EINSCHÄTZUNG")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Drei getrennte 0–100-Werte. Jeder Punkt basiert auf messbaren Kader-, Marktwert- und Rolleninformationen.")
        subtitle.setObjectName("Subtle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        squad = QFrame(); squad.setObjectName("Panel")
        sl = QVBoxLayout(squad); sl.setContentsMargins(16, 14, 16, 14); sl.setSpacing(7)
        st = QLabel("ANALYSE-SCORE · 0–100"); st.setObjectName("SectionTitle"); sl.addWidget(st)
        metric = "Ø Punkte gegen den Median deiner Positionskollegen" if points_are_current else "Marktwert gegen den Median deiner Positionskollegen (Preseason)"
        txt = QLabel(
            "• Positionsrelevanz: 25 Punkte – wie dünn die jeweilige Position in deinem Kader besetzt ist. Zielbreite: TW 2 / ABW 4 / MF 4 / ST 3.\n"
            f"• Qualität: 40 Punkte – {metric}. 0,5x Median = 0, 1,0x = 20, 1,5x = 40.\n"
            "• Eigene Rolle: 15 Punkte – STAMM 15 / OFFEN 10 / INVEST 9 / TRANSFERLISTE 2.\n"
            "• Marktwerttrend: 20 Punkte – auf Tagesrate normalisierte 24h-, 3-, 7- und 14-Tage-Entwicklung inklusive Trendbeschleunigung."
        )
        txt.setObjectName("Subtle"); txt.setWordWrap(True); sl.addWidget(txt); layout.addWidget(squad)

        inv = QFrame(); inv.setObjectName("Panel")
        il = QVBoxLayout(inv); il.setContentsMargins(16, 14, 16, 14); il.setSpacing(7)
        it = QLabel("INVESTMENT · 0–100"); it.setObjectName("SectionTitle"); il.addWidget(it)
        itxt = QLabel(
            "• Marktwert-Momentum: 50 Punkte – 24h / 3 / 7 / 14 Tage werden auf eine Tagesrate normalisiert; Beschleunigung wird separat berücksichtigt.\n"
            "• Rendite seit Einstieg: 30 Punkte – -10 % = 0, 0 % = 15, +10 % oder besser = 30.\n"
            "• Momentum-Konsistenz: 20 Punkte – wie viele der verfügbaren Zeitfenster positiv sind.\n\n"
            "Der Investmentwert bewertet bewusst die Marktwert-/Trading-Situation und nicht den Positionsbedarf."
        )
        itxt.setObjectName("Subtle"); itxt.setWordWrap(True); il.addWidget(itxt); layout.addWidget(inv)

        sell = QFrame(); sell.setObjectName("Panel")
        vl = QVBoxLayout(sell); vl.setContentsMargins(16, 14, 16, 14); vl.setSpacing(7)
        vt = QLabel("VERKAUFSBEREITSCHAFT · 0–100"); vt.setObjectName("SectionTitle"); vl.addWidget(vt)
        vtxt = QLabel(
            "• Ersetzbarkeit: 30 Punkte – Positionsbreite plus Qualität relativ zum Positionsmedian.\n"
            "• Kapitalfreisetzung: 20 Punkte – Marktwert relativ zum Medianwert deines gesamten Kaders.\n"
            "• Schwacher Analyse-Score: 25 Punkte – je niedriger der Analyse-Score, desto höher dieser Anteil.\n"
            "• Schwaches Investment: 15 Punkte – fallende/unattraktive Investments werden eher verkaufbar.\n"
            "• Eigene Rolle: 10 Punkte – TRANSFERLISTE 10 / OFFEN 5 / INVEST 2 / STAMM 0."
        )
        vtxt.setObjectName("Subtle"); vtxt.setWordWrap(True); vl.addWidget(vtxt); layout.addWidget(sell)

        decision = QFrame(); decision.setObjectName("Panel")
        dl = QVBoxLayout(decision); dl.setContentsMargins(16, 14, 16, 14); dl.setSpacing(7)
        dt = QLabel("VERKAUFSENTSCHEIDUNG"); dt.setObjectName("SectionTitle"); dl.addWidget(dt)
        dtxt = QLabel(
            "Aus der Verkaufsbereitschaft wird zusätzlich eine konkrete Handlungsempfehlung abgeleitet. "
            "Dafür werden vier Dinge kombiniert:\n"
            "• Basis aus Ersetzbarkeit, Kapitalfreisetzung, Rolle und Investmentlage.\n"
            "• MW-Exit-Signal: mehrere negative 1/3/7/14-Tage-Fenster und abbremsendes Momentum.\n"
            "• Gewinnmitnahme: vorhandener Buchgewinn erhöht den Verkaufsdruck moderat; ein Verlust allein ist ausdrücklich kein Verkaufsgrund.\n"
            "• Aktuelle Markt-Alternative: gibt es einen finanzierbaren Spieler derselben Position, der dein Team messbar verbessert?\n\n"
            "HALTEN < 52 · VERKAUF PRÜFEN ab 52 · EHER VERKAUFEN ab 64 · JETZT VERKAUFEN ab 82. "
            "JETZT VERKAUFEN benötigt zusätzlich einen echten Auslöser wie fallendes Momentum, Transferlisten-Rolle oder eine konkrete Markt-Alternative."
        )
        dtxt.setObjectName("Subtle"); dtxt.setWordWrap(True); dl.addWidget(dtxt); layout.addWidget(decision)

        sig = QFrame(); sig.setObjectName("Panel")
        gl = QVBoxLayout(sig); gl.setContentsMargins(16, 14, 16, 14); gl.setSpacing(6)
        gt = QLabel("SIGNAL"); gt.setObjectName("SectionTitle"); gl.addWidget(gt)
        gtxt = QLabel(
            "KERN-SPIELER: Analyse-Score ≥ 80 und Verkaufsbereitschaft < 40\n"
            "INVESTMENT HALTEN: Investment ≥ 75 und Verkaufsbereitschaft < 55\n"
            "VERKAUFSKANDIDAT: Verkaufsbereitschaft ≥ 75\n"
            "UPGRADE-KANDIDAT: Analyse-Score < 50 und Verkaufsbereitschaft ≥ 60\n"
            "HALTEN: Analyse-Score ≥ 65\n"
            "BEOBACHTEN: übriger Bereich"
        )
        gtxt.setObjectName("Subtle"); gtxt.setWordWrap(True); gl.addWidget(gtxt); layout.addWidget(sig)

        note_text = "Laufende Saison: aktuelle Ø-Punkte fließen in die Qualitätsbewertung ein." if points_are_current else "Preseason: alte Saisonpunkte werden nicht verwendet. Die relative Qualität wird vor Saisonstart über den aktuellen Marktwert gemessen."
        note = QLabel(note_text + " Jede Score-Zelle zeigt per Hover die exakte Punkte-Aufschlüsselung des Spielers.")
        note.setObjectName("Tiny"); note.setWordWrap(True); layout.addWidget(note)
        layout.addStretch()


class MarketScoringInfoDialog(QDialog):
    """Explain the exact market scoring model shown in the MARKT tab."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("So funktioniert die Markt-Einschätzung")
        self.resize(760, 680)
        self.setMinimumSize(650, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel("MARKT-EINSCHÄTZUNG")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Die Scores bleiben intern nachvollziehbar; die eigentliche Entscheidung nutzt zusätzlich Replacement Value, Max-Bid, Investment-Horizont und Datenbasis.")
        subtitle.setObjectName("Subtle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        fit = QFrame(); fit.setObjectName("Panel")
        fit_l = QVBoxLayout(fit); fit_l.setContentsMargins(16,14,16,14); fit_l.setSpacing(7)
        fit_t = QLabel("ANALYSE-SCORE · 0–100"); fit_t.setObjectName("SectionTitle")
        fit_l.addWidget(fit_t)
        fit_text = QLabel(
            "• Spielerqualität: 55 Punkte – rein sportlicher Vergleich mit deinen eigenen Spielern derselben Position; in der Saison über Ø Punkte, in der Preseason nur als Marktwert-Proxy.\n"
            "• Positionsbedarf: 20 Punkte – reine Kaderbreite gegen Zieltiefe TW 2 / ABW 4 / MF 4 / ST 3.\n"
            "• Replacement: 25 Punkte – Kandidat gegen deine schwächste eigene Option derselben Position.\n\n"
            "Preis, Budget und künstliche Marktknappheit beeinflussen diesen Kader-Score bewusst nicht mehr."
        )
        fit_text.setObjectName("Subtle"); fit_text.setWordWrap(True)
        fit_l.addWidget(fit_text)
        layout.addWidget(fit)

        inv = QFrame(); inv.setObjectName("Panel")
        inv_l = QVBoxLayout(inv); inv_l.setContentsMargins(16,14,16,14); inv_l.setSpacing(7)
        inv_t = QLabel("INVESTMENT-CHANCE · 0–100"); inv_t.setObjectName("SectionTitle")
        inv_l.addWidget(inv_t)
        inv_text = QLabel(
            "Preseason: Preis/MW 55 · MW-Momentum 45. Alte Saisonpunkte werden nicht verwendet.\n"
            "Laufende Saison: Performance 35 · Preis/MW 35 · MW-Momentum 30.\n\n"
            "Die drei Blöcke sind bewusst getrennt. Fair Value und Punkte/Mio sind aus der Entscheidungslogik entfernt, damit derselbe Preis nicht mehrfach gewertet wird. MW-Momentum nutzt nicht überlappende Teilfenster (1T, Tage 2–3, 4–7, 8–14) und erkennt Beschleunigung aus den letzten 3 Tagen gegenüber den vorherigen 4 Tagen. Liga-Deals bleiben nur Kontext und verändern den Score nicht."
        )
        inv_text.setObjectName("Subtle"); inv_text.setWordWrap(True)
        inv_l.addWidget(inv_text)
        layout.addWidget(inv)

        signals = QFrame(); signals.setObjectName("Panel")
        sig_l = QVBoxLayout(signals); sig_l.setContentsMargins(16,14,16,14); sig_l.setSpacing(6)
        sig_t = QLabel("SIGNAL"); sig_t.setObjectName("SectionTitle"); sig_l.addWidget(sig_t)
        sig_text = QLabel(
            "KAUFEN: ausführbares Mindestgebot (mindestens aktueller MW) ≤ Max-Bid und beide Kernbewertungen sind mindestens solide.\n"
            "TOP-CHANCE / KADER-UPGRADE / INVEST-CHANCE: starke Einzel- oder Kombinationssignale, solange der Preis nicht klar oberhalb des Max-Bid liegt.\n"
            "KAUFPRÜFUNG: mindestens ein Kernbereich ≥ 60.\n"
            "BEOBACHTEN: neutraler Bereich oder noch zu wenig Evidenz.\n"
            "PASSEN: schwache Kombination, Mindestgebot > Max-Bid oder ausführbarer Preis > 108 % des Max-Bid."
        )
        sig_text.setObjectName("Subtle"); sig_text.setWordWrap(True); sig_l.addWidget(sig_text)
        layout.addWidget(signals)

        decision = QFrame(); decision.setObjectName("Panel")
        dl = QVBoxLayout(decision); dl.setContentsMargins(16,14,16,14); dl.setSpacing(6)
        dt = QLabel("ENTSCHEIDUNGSLAYER"); dt.setObjectName("SectionTitle"); dl.addWidget(dt)
        dtext = QLabel(
            "• Replacement Value – Kandidat gegen deine schwächste realistische Option derselben Position; in der Saison über Ø Punkte, Preseason nur als Marktwert-Proxy.\n"
            "• Mindestgebot – in dieser Liga muss ein Gebot mindestens dem aktuellen Marktwert entsprechen; Listings darunter werden nicht als Schnäppchen gewertet.\n"
            "• Max-Bid – aktueller Marktwert plus klar begründetes Premium: bis +3 % für starkes Trading-Setup, +3 % für klaren Kader-Upgrade und +2 % für starkes MW-Momentum. Gesamtdeckel: +8 %.\n"
            "• Investment-Horizont – FLIP 1–3T, TRADING 1W, HOLD oder kein klares Setup; basiert ausschließlich auf beobachtbarem Preis/MW und MW-Momentum.\n"
            "• Datenbasis – HOCH / MITTEL / GERING anhand vorhandener MW-Historie, Liga-Deals und aktueller Leistungsdaten. Das ist keine Erfolgswahrscheinlichkeit.\n"
            "• Backtesting – BUY- und PASS-Empfehlungen werden nach 7 Tagen getrennt ausgewertet. Entscheidend ist der Rendite-Spread; ein BUY zählt erst ab +1 % als Richtungs-Treffer."
        )
        dtext.setObjectName("Subtle"); dtext.setWordWrap(True); dl.addWidget(dtext); layout.addWidget(decision)

        note = QLabel("Die Empfehlung kann deshalb trotz hoher Einzel-Scores auf PASSEN wechseln, wenn der aktuelle Preis klar über dem berechneten Max-Bid liegt. Werte mit geringer Datenbasis sollten vorsichtiger interpretiert werden.")
        note.setObjectName("Tiny"); note.setWordWrap(True); layout.addWidget(note)
        layout.addStretch()


class PreseasonOptimizerDialog(QDialog):
    def __init__(self, parent, result: dict, budget: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("Startkader-Optimizer")
        self.resize(860, 680)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 18)
        root.setSpacing(10)

        title = QLabel("STARTKADER-OPTIMIZER")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        if not result.get("feasible"):
            info = QLabel(
                "Mit aktuellem Kader, aktuellem Transfermarkt und verfügbarem Budget konnte keine vollständige "
                "11 für eine erlaubte Formation gebaut werden. Der Optimizer erfindet keine nicht gelisteten Spieler."
            )
            info.setObjectName("Subtle")
            info.setWordWrap(True)
            root.addWidget(info)
            close = QPushButton("SCHLIESSEN")
            close.clicked.connect(self.accept)
            root.addWidget(close, 0, Qt.AlignRight)
            return

        summary = QFrame(); summary.setObjectName("Panel")
        grid = QGridLayout(summary); grid.setContentsMargins(14, 12, 14, 12); grid.setSpacing(8)
        values = [
            ("FORMATION", str(result.get("formation") or "–")),
            ("TEAM-SCORE", f"{float(result.get('score') or 0):.1f}/100"),
            ("NEUE KÄUFE", str(int(result.get("market_buys") or 0))),
            ("VERKÄUFE NÖTIG", str(int(result.get("required_sales") or 0))),
            ("AUSGABEN", euro(result.get("spent"))),
            ("RESTBUDGET", euro(result.get("remaining"))),
        ]
        for i, (caption, value) in enumerate(values):
            cap=QLabel(caption); cap.setObjectName("Tiny")
            val=QLabel(value); val.setObjectName("MarketDetailValue")
            grid.addWidget(cap, 0, i)
            grid.addWidget(val, 1, i)
        root.addWidget(summary)

        current_size = int(result.get("current_squad_size") or 0)
        max_size = int(result.get("max_squad_size") or MAX_SQUAD_SIZE)
        note = QLabel(
            "Optimiert nur mit deinem aktuellen Kader + aktuell gelisteten Marktspielern. Eigene Spieler kosten 0 € zusätzlich; "
            "Marktspieler werden mit dem effektiv nötigen Mindestpreis gerechnet. Maximal 6 neue Käufe. "
            f"Kadergrenze: {current_size}/{max_size}; jeder Zugang oberhalb der freien Plätze benötigt einen Abgang."
        )
        note.setObjectName("Tiny"); note.setWordWrap(True)
        root.addWidget(note)

        sales_needed = int(result.get("required_sales") or 0)
        sale_candidates = list(result.get("sale_candidates") or [])
        if sales_needed:
            names = ", ".join(str(p.get("name") or p.get("full_name") or "–") for p in sale_candidates)
            roster_warning = QLabel(
                f"KADERPLÄTZE: Für diese Variante sind {sales_needed} Verkauf/Verkäufe nötig."
                + (f" Naheliegende Abgänge außerhalb der optimierten XI: {names}." if names else "")
            )
            roster_warning.setObjectName("FinanceWarning")
            roster_warning.setWordWrap(True)
            root.addWidget(roster_warning)

        table = QTableWidget()
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels(["SPIELER", "VEREIN", "POS", "QUELLE", "SCORE", "KOSTEN", "ROLLE"])
        table.setRowCount(len(result.get("players") or []))
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        for r, player in enumerate(result.get("players") or []):
            source = str(player.get("optimizer_source") or "")
            role = str(player.get("portfolio_role") or player.get("action") or player.get("player_role") or "–")
            cells = [
                str(player.get("full_name") or player.get("name") or "–"),
                str(player.get("club") or "–"),
                str(player.get("position") or "–"),
                "NEU KAUFEN" if source == "MARKT" else "DEIN KADER",
                f"{float(player.get('optimizer_score') or 0):.1f}",
                euro(player.get("optimizer_cost")) if source == "MARKT" else "–",
                role,
            ]
            for c, value in enumerate(cells):
                item=QTableWidgetItem(value)
                if c == 3:
                    item.setForeground(QColor("#62E49A") if source == "KADER" else QColor("#F3C44E"))
                table.setItem(r,c,item)
        root.addWidget(table, 1)
        close = QPushButton("SCHLIESSEN")
        close.clicked.connect(self.accept)
        root.addWidget(close, 0, Qt.AlignRight)


class MarketBidDialog(QDialog):
    """Compact editor for a real Kickbase market offer."""

    def __init__(self, parent, player: dict, *, squad_value: int, balance_after_bids: int) -> None:
        super().__init__(parent)
        self.player = dict(player or {})
        self.market_value = int(self.player.get("market_value") or 0)
        self.existing_bid = int(self.player.get("own_bid") or 0)
        self.capacity = calculate_bid_capacity(
            squad_value, balance_after_bids, existing_bid=self.existing_bid
        )
        self.amount = 0
        self.setWindowTitle("Gebot abgeben")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        name = QLabel(str(self.player.get("full_name") or self.player.get("name") or "Spieler"))
        name.setObjectName("SectionTitle")
        layout.addWidget(name)

        info = QLabel(
            f"Marktwert: {euro(self.market_value)}   ·   Anbieter: "
            f"{self.player.get('seller_name') or ('Kickbase' if self.player.get('is_kickbase') else 'Manager')}"
        )
        info.setObjectName("Subtle")
        layout.addWidget(info)

        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("Gebot in €")
        default_amount = max(self.market_value, self.existing_bid)
        self.amount_edit.setText(str(default_amount))
        self.amount_edit.textChanged.connect(self._refresh)
        layout.addWidget(self.amount_edit)

        quick = QHBoxLayout()
        for label, factor in (("MW", 1.0), ("+1 %", 1.01), ("+2 %", 1.02), ("+5 %", 1.05)):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, f=factor: self._set_quick(f))
            quick.addWidget(button)
        layout.addLayout(quick)

        self.rule_label = QLabel()
        self.rule_label.setWordWrap(True)
        self.rule_label.setObjectName("Subtle")
        layout.addWidget(self.rule_label)

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)

        actions = QHBoxLayout()
        cancel = QPushButton("ABBRECHEN")
        cancel.clicked.connect(self.reject)
        self.submit = QPushButton("GEBOT PRÜFEN")
        self.submit.clicked.connect(self._accept_if_valid)
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(self.submit)
        layout.addLayout(actions)
        self._refresh()

    def _parsed_amount(self) -> int:
        raw = self.amount_edit.text().strip().replace(".", "").replace(" ", "").replace("€", "")
        try:
            return int(raw)
        except ValueError:
            return 0

    @staticmethod
    def _round_listing_price_up(market_value: int, percent_value: int = 100) -> int:
        """Return a whole-€1k listing price that never undershoots the target."""
        if market_value <= 0 or percent_value <= 0:
            return 0
        target = (int(market_value) * int(percent_value) + 99) // 100
        return ((target + 999) // 1000) * 1000

    def _set_quick(self, percent_value: int) -> None:
        self.amount_edit.setText(str(self._round_listing_price_up(self.market_value, percent_value)))

    def _refresh(self) -> None:
        amount = self._parsed_amount()
        after = self.capacity.effective_balance - amount
        self.rule_label.setText(
            f"Kontostand nach Gebot: {euro(after)}\n"
            f"33%-Grenze: {euro(self.capacity.minimum_balance)}   ·   "
            f"Max. neues Gebot: {euro(self.capacity.maximum_new_bid)}"
        )
        problems = []
        if amount <= 0:
            problems.append("Bitte ein gültiges Gebot eingeben.")
        if self.market_value and amount < self.market_value:
            problems.append(f"Gebot muss mindestens dem aktuellen Marktwert ({euro(self.market_value)}) entsprechen.")
        if amount > self.capacity.maximum_new_bid:
            problems.append("Dieses Gebot würde die lokale 33%-Kreditgrenze überschreiten.")
        self.warning.setText("\n".join(problems) if problems else "✓ Gebot liegt innerhalb der lokalen Prüfregeln.")
        self.warning.setStyleSheet("color: #FF7A80;" if problems else "color: #62E49A;")
        self.submit.setEnabled(not problems)

    def _accept_if_valid(self) -> None:
        self._refresh()
        if not self.submit.isEnabled():
            return
        self.amount = self._parsed_amount()
        self.accept()


class SellPlayerDialog(QDialog):
    """Choose a real Kickbase listing price for an owned player."""

    def __init__(self, parent, player: dict, *, initial_price: int | None = None) -> None:
        super().__init__(parent)
        self.player = dict(player or {})
        self.market_value = int(self.player.get("market_value") or 0)
        self.amount = 0
        self.setWindowTitle("Spieler verkaufen")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        name = QLabel(str(self.player.get("full_name") or self.player.get("name") or "Spieler"))
        name.setObjectName("SectionTitle")
        layout.addWidget(name)
        meta = QLabel(f"Marktwert: {euro(self.market_value)}")
        meta.setObjectName("Subtle")
        layout.addWidget(meta)

        self.amount_edit = QLineEdit(str(int(initial_price or self.market_value or 0)))
        self.amount_edit.setPlaceholderText("Listenpreis in €")
        self.amount_edit.textChanged.connect(self._refresh)
        layout.addWidget(self.amount_edit)

        quick = QHBoxLayout()
        for label, percent_value in (("MW", 100), ("+2 %", 102), ("+5 %", 105), ("+10 %", 110)):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, p=percent_value: self._set_quick(p))
            quick.addWidget(btn)
        layout.addLayout(quick)

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel = QPushButton("ABBRECHEN")
        cancel.clicked.connect(self.reject)
        self.submit = QPushButton("VERKAUF PRÜFEN")
        self.submit.setObjectName("Primary")
        self.submit.clicked.connect(self._accept_if_valid)
        actions.addWidget(cancel)
        actions.addWidget(self.submit)
        layout.addLayout(actions)
        self._refresh()

    def _parsed_amount(self) -> int:
        raw = self.amount_edit.text().strip().replace(".", "").replace(" ", "").replace("€", "")
        try:
            return int(raw)
        except ValueError:
            return 0

    def _set_quick(self, percent_value: int) -> None:
        self.amount_edit.setText(str(listing_price_for_percent(self.market_value, percent_value)))

    def _refresh(self) -> None:
        amount = self._parsed_amount()
        problems = []
        if amount <= 0:
            problems.append("Bitte einen gültigen Verkaufspreis eingeben.")
        if self.market_value and amount < self.market_value:
            problems.append("Der Listenpreis liegt unter dem aktuellen Marktwert.")
        self.warning.setText("\n".join(problems) if problems else f"✓ Listenpreis: {euro(amount)}")
        self.warning.setStyleSheet("color: #FF7A80;" if problems else "color: #62E49A;")
        self.submit.setEnabled(not problems)

    def _accept_if_valid(self) -> None:
        self._refresh()
        if not self.submit.isEnabled():
            return
        self.amount = self._parsed_amount()
        self.accept()


class ListingManagementDialog(QDialog):
    """Manage one own listing. Offer actions stay visible but disabled until verified."""

    def __init__(self, parent, client: KickbaseClient, league_id: str, player: dict, refresh_callback=None) -> None:
        super().__init__(parent)
        self.client = client
        self.league_id = str(league_id)
        self.player = dict(player or {})
        self.player_id = str(self.player.get("player_id") or "")
        self.refresh_callback = refresh_callback
        self.setWindowTitle("Verkauf verwalten")
        self.setMinimumWidth(620)
        self.resize(680, 430)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        title = QLabel(str(self.player.get("full_name") or self.player.get("name") or "Spieler"))
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        self.meta = QLabel(
            f"Marktwert {euro(self.player.get('market_value'))} · Listenpreis {euro(self.player.get('listing_price') or self.player.get('price'))}"
        )
        self.meta.setObjectName("Subtle")
        root.addWidget(self.meta)

        listing_actions = QHBoxLayout()
        change_price = QPushButton("PREIS ÄNDERN")
        change_price.clicked.connect(self._change_price)
        remove = QPushButton("VOM MARKT NEHMEN")
        remove.clicked.connect(self._remove_listing)
        listing_actions.addWidget(change_price)
        listing_actions.addWidget(remove)
        listing_actions.addStretch()
        root.addLayout(listing_actions)

        offers_title = QLabel("ANGEBOTS-CENTER")
        offers_title.setObjectName("SectionTitle")
        root.addWidget(offers_title)

        info = QLabel(
            "Manager-Angebote sind vorbereitet, aber weiterhin deaktiviert, bis deren echte Requests verifiziert sind. "
            "Der separate Verkauf an Kickbase ist inzwischen verifiziert und bewusst davon getrennt."
        )
        info.setObjectName("Subtle")
        info.setWordWrap(True)
        root.addWidget(info)

        offer_box = QFrame()
        offer_box.setObjectName("MarketDetailBox")
        offer_layout = QVBoxLayout(offer_box)
        offer_layout.setContentsMargins(12, 10, 12, 10)
        offer_layout.setSpacing(8)

        status = QLabel("Noch keine verifizierten Angebotsdaten geladen.")
        status.setObjectName("Subtle")
        offer_layout.addWidget(status)

        offer_actions = QHBoxLayout()
        load_offers = QPushButton("ANGEBOTE LADEN")
        accept_offer = QPushButton("AUSGEWÄHLTES ANNEHMEN")
        decline_offer = QPushButton("AUSGEWÄHLTES ABLEHNEN")
        accept_offer.setObjectName("Primary")
        for button in (load_offers, accept_offer, decline_offer):
            button.setEnabled(False)
            button.setToolTip("Noch nicht verifiziert – wird nach dem Mitschnitt der offiziellen Kickbase-App freigeschaltet.")
            offer_actions.addWidget(button)
        offer_actions.addStretch()
        offer_layout.addLayout(offer_actions)
        root.addWidget(offer_box)

        kickbase_box = QFrame()
        kickbase_box.setObjectName("MarketDetailBox")
        kickbase_layout = QVBoxLayout(kickbase_box)
        kickbase_layout.setContentsMargins(12, 10, 12, 10)
        kickbase_layout.setSpacing(8)

        kickbase_title = QLabel("KICKBASE-ANGEBOT")
        kickbase_title.setObjectName("SectionMini")
        kickbase_layout.addWidget(kickbase_title)

        kickbase_hint = QLabel(
            "Verkauft den Spieler direkt an Kickbase über den verifizierten /sell-Request. "
            "Das ist ausdrücklich kein Manager-Gebot und lässt sich nach dem Verkauf nicht über KickTrack rückgängig machen."
        )
        kickbase_hint.setObjectName("Subtle")
        kickbase_hint.setWordWrap(True)
        kickbase_layout.addWidget(kickbase_hint)

        kickbase_actions = QHBoxLayout()
        sell_to_kickbase = QPushButton("AN KICKBASE VERKAUFEN")
        sell_to_kickbase.setObjectName("DangerSecondary")
        sell_to_kickbase.setToolTip("Aktuelles Kickbase-Angebot annehmen und den Spieler direkt an Kickbase verkaufen")
        sell_to_kickbase.clicked.connect(self._sell_to_kickbase)
        kickbase_actions.addWidget(sell_to_kickbase)
        kickbase_actions.addStretch()
        kickbase_layout.addLayout(kickbase_actions)
        root.addWidget(kickbase_box)

        root.addStretch()
        close = QPushButton("SCHLIESSEN")
        close.clicked.connect(self.accept)
        root.addWidget(close, 0, Qt.AlignRight)

    def _after_write(self) -> None:
        if callable(self.refresh_callback):
            self.refresh_callback()

    def _change_price(self) -> None:
        initial = int(self.player.get("listing_price") or self.player.get("price") or self.player.get("market_value") or 0)
        dialog = SellPlayerDialog(self, self.player, initial_price=initial)
        if dialog.exec() != QDialog.Accepted:
            return
        amount = int(dialog.amount or 0)
        if QMessageBox.question(self, "Preis ändern?", f"Listenpreis wirklich auf {euro(amount)} setzen?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.client.set_transfer_price(self.league_id, self.player_id, amount)
        except Exception as exc:
            QMessageBox.warning(self, "Preisänderung fehlgeschlagen", str(exc))
            return
        self.player["listing_price"] = amount
        self.player["price"] = amount
        self.meta.setText(f"Marktwert {euro(self.player.get('market_value'))} · Listenpreis {euro(amount)}")
        self._after_write()

    def _remove_listing(self) -> None:
        if QMessageBox.question(self, "Vom Markt nehmen?", "Spieler wirklich von deiner Transferliste entfernen?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.client.remove_player_from_market(self.league_id, self.player_id)
        except Exception as exc:
            QMessageBox.warning(self, "Entfernen fehlgeschlagen", str(exc))
            return
        self._after_write()
        self.accept()

    def _sell_to_kickbase(self) -> None:
        name = str(self.player.get("full_name") or self.player.get("name") or "Spieler")
        message = (
            f"{name} wirklich direkt an Kickbase verkaufen?\n\n"
            "Dieser Button nimmt ausschließlich das aktuelle Kickbase-Angebot an. "
            "Manager-Gebote werden damit nicht ausgewählt oder angenommen.\n\n"
            "Der Verkauf ist eine echte schreibende Aktion und kann in KickTrack nicht rückgängig gemacht werden."
        )
        if QMessageBox.warning(
            self,
            "An Kickbase verkaufen?",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            self.client.accept_kickbase_sale_offer(self.league_id, self.player_id)
        except Exception as exc:
            QMessageBox.warning(self, "Verkauf an Kickbase fehlgeschlagen", str(exc))
            return
        QMessageBox.information(self, "Verkauft", f"{name} wurde an Kickbase verkauft.")
        self._after_write()
        self.accept()


class FinancingScenarioDialog(QDialog):
    """Explain whether a market player is affordable and how sales could fund it."""

    def __init__(self, parent, target: dict, available_budget: int, squad: list[dict]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Finanzierungsszenario")
        self.resize(760, 620)
        self.setMinimumSize(650, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        title = QLabel(str(target.get("full_name") or target.get("name") or "Spieler"))
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            f"{target.get('club') or '–'} · {target.get('position') or '–'} · Zielpreis {euro(target.get('price'))}"
        )
        subtitle.setObjectName("Subtle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        result = financing_scenarios(int(target.get("price") or 0), int(available_budget or 0), squad)
        capacity = squad_capacity(squad)

        summary = QFrame()
        summary.setObjectName("Panel")
        summary_layout = QGridLayout(summary)
        summary_layout.setContentsMargins(16, 14, 16, 14)
        summary_layout.setHorizontalSpacing(20)
        summary_layout.setVerticalSpacing(6)
        values = [
            ("FREIES BUDGET", euro(available_budget)),
            ("KAUFPREIS", euro(target.get("price"))),
            ("FEHLBETRAG", euro(result.get("gap"))),
        ]
        for idx, (cap, val) in enumerate(values):
            box = QVBoxLayout()
            c = QLabel(cap); c.setObjectName("CardCaption")
            v = QLabel(val); v.setObjectName("CardValue")
            box.addWidget(c); box.addWidget(v)
            summary_layout.addLayout(box, 0, idx)
        layout.addWidget(summary)

        if result["directly_affordable"]:
            state_text = f"Direkt finanzierbar · danach {euro(result.get('remaining_budget'))} Restbudget"
            if capacity.is_full:
                state_text += f" · ABER KADER {capacity.current}/{capacity.maximum}: vor dem Zugang ist ein Verkauf nötig"
            state = QLabel(state_text)
            state.setObjectName("FinanceSuccess")
            state.setWordWrap(True)
            layout.addWidget(state)
        else:
            state = QLabel(
                f"Es fehlen {euro(result.get('gap'))}. Mögliche Verkäufe werden mit dem aktuellen Marktwert gerechnet."
            )
            state.setObjectName("FinanceWarning")
            state.setWordWrap(True)
            layout.addWidget(state)

            scenarios = result.get("scenarios") or []
            if scenarios:
                section = QLabel("MÖGLICHE SZENARIEN")
                section.setObjectName("SectionTitle")
                layout.addWidget(section)
                for idx, scenario in enumerate(scenarios[:5], start=1):
                    card = QFrame()
                    card.setObjectName("FinanceScenarioCard")
                    row = QHBoxLayout(card)
                    row.setContentsMargins(14, 11, 14, 11)
                    row.setSpacing(12)
                    names = " + ".join(p["name"] for p in scenario["players"])
                    left = QVBoxLayout()
                    name = QLabel(f"{idx}. {names}")
                    name.setObjectName("FinanceScenarioName")
                    meta = QLabel(
                        f"Verkaufswert {euro(scenario['sale_value'])} · Rest danach {euro(scenario['remaining_budget'])}"
                    )
                    meta.setObjectName("Tiny")
                    left.addWidget(name)
                    left.addWidget(meta)
                    row.addLayout(left, 1)
                    role_text = ", ".join(p.get("role") or "OFFEN" for p in scenario["players"])
                    roles = QLabel(role_text)
                    roles.setObjectName("FinanceRole")
                    row.addWidget(roles)
                    layout.addWidget(card)
            else:
                no_result = QLabel("Mit maximal drei Verkäufen reicht der aktuelle Kaderwert für dieses Szenario nicht aus.")
                no_result.setObjectName("FinanceWarning")
                no_result.setWordWrap(True)
                layout.addWidget(no_result)

        note = QLabel("Hinweis: Das ist eine Szenariorechnung mit aktuellen Marktwerten, keine Garantie für real erzielbare Verkaufspreise.")
        note.setObjectName("Tiny")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()




class LineupOptimizerDialog(QDialog):
    FORMATION_ORDER = ("3-4-3", "3-5-2", "3-6-1", "4-2-4", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1")

    def __init__(self, parent, players: list[dict], fixture_payload: dict, table_payload: dict, lineup_payload: dict | None = None, *, points_are_current: bool, performance_payloads: dict[str, dict] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lineup Optimizer")
        self.resize(760, 680)
        self.setMinimumSize(660, 560)
        self.players = list(players or [])
        self.points_are_current = points_are_current

        self.fixture_by_team: dict[str, list[dict]] = {}
        for player in self.players:
            tid = str(player.get("team_id") or "")
            if tid and tid not in self.fixture_by_team:
                self.fixture_by_team[tid] = fixture_run(tid, fixture_payload, table_payload, 3)
        if not points_are_current:
            for run in self.fixture_by_team.values():
                for fixture in run:
                    fixture["ease"] = 50
                    fixture["adjusted_ease"] = 50
                    fixture["opponent_place"] = None

        performance_payloads = performance_payloads or {}
        self.form_by_player = {
            str(player_id): player_form(payload)
            for player_id, payload in performance_payloads.items()
            if isinstance(payload, dict)
        }
        lineup_items = lineup_payload.get("it", []) if isinstance(lineup_payload, dict) else []
        self.current_ids = {str(item.get("i") or item.get("pi") or "") for item in lineup_items if isinstance(item, dict)}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)
        title = QLabel("EMPFOHLENE XI")
        title.setObjectName("PageTitle")
        sub = QLabel(
            "Read-only Simulation · Form/Saisonleistung, nächste Gegner, Status und Marktwert als Preseason-Tiebreaker"
            if points_are_current else
            "Read-only Simulation · Preseason ohne alte Saisonpunkte; Gegner, Status und Marktwert dienen als Orientierung"
        )
        sub.setObjectName("Subtle")
        sub.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(sub)

        formation_row = QHBoxLayout()
        formation_label = QLabel("FORMATION")
        formation_label.setObjectName("Tiny")
        self.formation_combo = QComboBox()
        self.formation_combo.setMinimumWidth(245)
        self.formation_combo.addItem("AUTO · BESTE XI", None)
        self._populate_formations()
        formation_row.addWidget(formation_label)
        formation_row.addWidget(self.formation_combo)
        formation_row.addStretch(1)
        root.addLayout(formation_row)

        self.meta = QLabel()
        self.meta.setObjectName("SectionTitle")
        root.addWidget(self.meta)

        self.table = ResponsiveTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["POS", "SPIELER", "VEREIN", "MW", "FORM", "NÄCHSTER GEGNER", "OPT-SCORE", "AKTUELL"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.set_responsive_widths([65, 205, 145, 120, 115, 160, 95, 85], [58, 165, 120, 105, 95, 135, 80, 75])
        root.addWidget(self.table, 1)

        self.note = QLabel("Die Aufstellung wird nicht an Kickbase übertragen. Sie ist eine transparente Entscheidungshilfe und kein automatischer Schreibzugriff.")
        self.note.setObjectName("Tiny")
        self.note.setWordWrap(True)
        root.addWidget(self.note)

        self.formation_combo.currentIndexChanged.connect(self._refresh_lineup)
        self._refresh_lineup()

    def _populate_formations(self) -> None:
        counts = {pos: 0 for pos in ("TW", "ABW", "MF", "ST")}
        for player in self.players:
            pos = str(player.get("position") or "")
            if pos in counts:
                counts[pos] += 1

        from .intelligence import VALID_FORMATIONS
        model = self.formation_combo.model()
        for formation in self.FORMATION_ORDER:
            needs = VALID_FORMATIONS[formation]
            missing = {pos: need - counts[pos] for pos, need in needs.items() if counts[pos] < need}
            if missing:
                labels = {"TW": "TW", "ABW": "ABW", "MF": "MF", "ST": "ST"}
                detail = ", ".join(f"{amount}× {labels[pos]}" for pos, amount in missing.items())
                self.formation_combo.addItem(f"{formation} · nicht möglich ({detail} fehlt)", formation)
                item = model.item(self.formation_combo.count() - 1)
                if item is not None:
                    item.setEnabled(False)
            else:
                self.formation_combo.addItem(formation, formation)

    def _refresh_lineup(self, *_args) -> None:
        formation = self.formation_combo.currentData()
        result = optimize_lineup(
            self.players,
            form_by_player=self.form_by_player,
            fixture_by_team=self.fixture_by_team,
            points_are_current=self.points_are_current,
            formation=formation,
        )

        if result.get("feasible"):
            prefix = "AUTO → " if formation is None else ""
            self.meta.setText(f"Formation {prefix}{result['formation']} · Team-Score {result['score']:.1f}")
        else:
            missing = result.get("missing") or {}
            detail = ", ".join(f"{amount}× {pos}" for pos, amount in missing.items())
            if detail:
                self.meta.setText(f"Formation {result['formation']} · nicht möglich · es fehlt {detail}")
            else:
                self.meta.setText(f"Keine vollständige legale XI möglich · Vorschau {result['formation']}")

        rows = result.get("players") or []
        self.table.setRowCount(len(rows))
        for r, player in enumerate(rows):
            fixtures = self.fixture_by_team.get(str(player.get("team_id") or ""), [])
            nxt = fixtures[0] if fixtures else None
            opponent = "–"
            if nxt:
                opponent = ("vs " if nxt.get("home_game") else "@ ") + str(nxt.get("opponent") or "–")
            form = self.form_by_player.get(str(player.get("player_id") or ""), {})
            form_display = "–"
            if self.points_are_current and form.get("last3_avg") is not None:
                form_display = f"{float(form['last3_avg']):.0f} · {form.get('risk_label') or '–'}"
            values = [
                player.get("position") or "–",
                player.get("name") or "–",
                player.get("club") or "–",
                euro(player.get("market_value")),
                form_display,
                opponent,
                f"{float(player.get('optimizer_score') or 0):.1f}",
                "✓" if str(player.get("player_id") or "") in self.current_ids else "NEU",
            ]
            for c, value in enumerate(values):
                item = table_item(value)
                item.setData(Qt.UserRole, player.get("player_id"))
                self.table.setItem(r, c, item)


class MarketScannerDialog(QDialog):
    """League-wide market-value scanner backed by cached 365-day histories."""

    def __init__(self, parent, rows: list[dict]) -> None:
        super().__init__(parent)
        self.rows = list(rows or [])
        self.setWindowTitle("MW-Scanner — Ligaweit")
        self.resize(1320, 760)
        self.setMinimumSize(980, 620)
        self.setModal(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("LIGAWEITER MW-SCANNER")
        title.setObjectName("PageTitle")
        subtitle = QLabel("365-Tage-Historie · manuell geladen · API-Antworten werden 24 h gecacht")
        subtitle.setObjectName("Subtle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        controls = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("Spieler / Verein / Besitzer suchen …")
        position = QComboBox()
        position.addItems(["Alle Positionen", "TW", "ABW", "MF", "ST"])
        status = QLabel(f"{len(self.rows)} Spieler")
        status.setObjectName("Tiny")
        controls.addWidget(search, 1)
        controls.addWidget(position)
        controls.addWidget(status)
        layout.addLayout(controls)

        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "SPIELER", "VEREIN", "POS", "STATUS", "MARKTWERT", "1 TAG", "3 TAGE", "7 TAGE", "30 TAGE", "BESITZER"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        widths = [210, 150, 60, 150, 125, 100, 100, 100, 105, 180]
        for i, width in enumerate(widths):
            self.table.setColumnWidth(i, width)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemDoubleClicked.connect(self._open_player)
        layout.addWidget(self.table, 1)

        self._search = search
        self._position = position
        search.textChanged.connect(self._populate)
        position.currentIndexChanged.connect(self._populate)
        self._populate()

    def _populate(self, *_args) -> None:
        query = self._search.text().strip().casefold()
        pos = self._position.currentText()
        rows = []
        for row in self.rows:
            if pos != "Alle Positionen" and str(row.get("position") or "") != pos:
                continue
            hay = " ".join([
                str(row.get("full_name") or row.get("name") or ""),
                str(row.get("club") or ""),
                str(row.get("owner") or ""),
            ]).casefold()
            if query and query not in hay:
                continue
            rows.append(row)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            specs = [
                (row.get("full_name") or row.get("name") or "–", row.get("full_name") or row.get("name") or ""),
                (row.get("club") or "–", row.get("club") or ""),
                (row.get("position") or "–", POSITION_SORT.get(row.get("position"), 99)),
                (player_status_label(row), player_status_code(row) if player_status_code(row) is not None else -1),
                (euro(row.get("market_value")), int(row.get("market_value") or 0)),
                (delta_text(row.get("d1"), compact=True), row.get("d1") if row.get("d1") is not None else -10**18),
                (delta_text(row.get("d3"), compact=True), row.get("d3") if row.get("d3") is not None else -10**18),
                (delta_text(row.get("d7"), compact=True), row.get("d7") if row.get("d7") is not None else -10**18),
                (delta_text(row.get("d30"), compact=True), row.get("d30") if row.get("d30") is not None else -10**18),
                (row.get("owner") or "–", row.get("owner") or ""),
            ]
            for c, (display, sort_value) in enumerate(specs):
                icon = None
                if c == 0:
                    icon = player_status_icon(row)
                elif c == 1:
                    icon = club_icon(row.get("club"))
                elif c == 3:
                    icon = player_status_icon(row)
                item = table_item(display, sort_value, icon=icon)
                item.setData(Qt.UserRole, str(row.get("player_id") or ""))
                item.setData(Qt.UserRole + 1, row)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if c in (0, 1, 9) else Qt.AlignCenter)
                if c in (0, 3):
                    item.setToolTip(player_status_tooltip(row))
                if c in (5, 6, 7, 8):
                    set_item_delta_color(item, row.get({5:"d1",6:"d3",7:"d7",8:"d30"}[c]))
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)

    def _open_player(self, item: QTableWidgetItem) -> None:
        first = self.table.item(item.row(), 0)
        if not first:
            return
        player_id = first.data(Qt.UserRole)
        player = first.data(Qt.UserRole + 1)
        if player_id and hasattr(self.parent(), "open_player_detail_tab"):
            league_id = self.parent().league_combo.currentData() or self.parent().storage.get_setting("league_id")
            self.parent().open_player_detail_tab(str(player_id), str(league_id) if league_id else None, dict(player or {}))




class PortraitReviewDialog(QDialog):
    def __init__(self, storage: Storage, parent=None) -> None:
        super().__init__(parent)
        self.storage = storage
        self._rows: list[dict] = []
        self._current: dict | None = None
        self._accept_worker: FunctionWorker | None = None
        self.setWindowTitle("Portraits prüfen")
        self.resize(1220, 660)
        self.setMinimumSize(1040, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        title = QLabel("PORTRAITS PRÜFEN")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Hier landen nur FotMob-Treffer, die der automatische Abgleich nicht sicher genug zuordnen konnte. "
            "Übernimm nur Kandidaten, bei denen Spieler und Verein plausibel zusammenpassen."
        )
        subtitle.setObjectName("Subtle")
        subtitle.setWordWrap(True)
        self.counter = QLabel()
        self.counter.setObjectName("Tiny")
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(self.counter)

        split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["SPIELER", "VEREIN", "POS", "MW", "KB-ID", "FOTMOB", "MATCH", "GRUND"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 145)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 55)
        self.table.setColumnWidth(3, 95)
        self.table.setColumnWidth(4, 95)
        self.table.setColumnWidth(5, 185)
        self.table.setColumnWidth(6, 65)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        split.addWidget(self.table)

        detail = QFrame()
        detail.setObjectName("Card")
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(22, 20, 22, 20)
        detail_layout.setSpacing(10)

        self.preview = QLabel("Kein Kandidat ausgewählt")
        self.preview.setObjectName("PlayerDetailPortrait")
        self.preview.setFixedSize(190, 220)
        self.preview.setAlignment(Qt.AlignCenter | Qt.AlignBottom)
        self.preview.setScaledContents(False)
        detail_layout.addWidget(self.preview, 0, Qt.AlignHCenter)

        self.player_label = QLabel("–")
        self.player_label.setObjectName("SectionTitle")
        self.candidate_label = QLabel("–")
        self.candidate_label.setObjectName("BodyStrong")
        self.reason_label = QLabel("–")
        self.reason_label.setObjectName("Subtle")
        self.reason_label.setWordWrap(True)
        detail_layout.addWidget(self.player_label)
        detail_layout.addWidget(self.candidate_label)
        detail_layout.addWidget(self.reason_label)
        detail_layout.addStretch()

        actions = QHBoxLayout()
        self.reject_btn = QPushButton("ABLEHNEN")
        self.reject_btn.setObjectName("DangerSecondary")
        self.reject_btn.clicked.connect(self._reject_current)
        self.accept_btn = QPushButton("PORTRAIT ÜBERNEHMEN")
        self.accept_btn.clicked.connect(self._accept_current)
        actions.addWidget(self.reject_btn)
        actions.addWidget(self.accept_btn)
        detail_layout.addLayout(actions)
        split.addWidget(detail)
        split.setSizes([800, 380])
        root.addWidget(split, 1)

        bottom = QHBoxLayout()
        self.reset_btn = QPushButton("ABGELEHNTE ZURÜCKSETZEN")
        self.reset_btn.clicked.connect(self._reset_rejected)
        close_btn = QPushButton("SCHLIESSEN")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(self.reset_btn)
        bottom.addStretch()
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        self._reload()

    def _reload(self, preferred_player_id: str | None = None) -> None:
        self._rows = self.storage.portrait_review_rows()
        stats = self.storage.player_master_stats()
        self.counter.setText(
            f"{len(self._rows)} offen · {int(stats.get('cached') or 0)} gecacht · "
            f"{int(stats.get('rejected') or 0)} manuell abgelehnt"
        )
        self.reset_btn.setVisible(int(stats.get("rejected") or 0) > 0)
        self.table.setRowCount(len(self._rows))
        selected_row = 0
        for idx, row in enumerate(self._rows):
            player_name = str(row.get("full_name") or row.get("name") or "–")
            club = str(row.get("club") or "–")
            candidate = str(row.get("portrait_candidate_name") or "").strip()
            candidate_team = str(row.get("portrait_candidate_team") or "").strip()
            fotmob_id = str(row.get("fotmob_id") or "–")
            candidate_text = candidate or f"FotMob #{fotmob_id}"
            if candidate_team:
                candidate_text += f" · {candidate_team}"
            market_value = row.get("market_value")
            try:
                market_value_text = f"{int(market_value):,} €".replace(",", ".") if market_value is not None else "–"
            except (TypeError, ValueError):
                market_value_text = "–"
            values = [
                player_name,
                club,
                str(row.get("position") or "–"),
                market_value_text,
                str(row.get("player_id") or "–"),
                candidate_text,
                f"{int(row.get('portrait_confidence') or 0)}%",
                str(row.get("portrait_reason") or "–"),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, str(row.get("player_id") or ""))
                self.table.setItem(idx, col, item)
            if preferred_player_id and str(row.get("player_id")) == str(preferred_player_id):
                selected_row = idx
        if self._rows:
            self.table.selectRow(min(selected_row, len(self._rows) - 1))
        else:
            self._current = None
            self.preview.clear()
            self.preview.setText("Alle unsicheren Portraits geprüft")
            self.player_label.setText("FERTIG")
            self.candidate_label.setText("Keine offenen Kandidaten")
            self.reason_label.setText("")
            self.accept_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)

    def _selection_changed(self) -> None:
        row_idx = self.table.currentRow()
        if row_idx < 0 or row_idx >= len(self._rows):
            return
        self._current = self._rows[row_idx]
        row = self._current
        self.accept_btn.setEnabled(bool(row.get("fotmob_id")))
        self.reject_btn.setEnabled(True)
        player = str(row.get("full_name") or row.get("name") or "–")
        club = str(row.get("club") or "–")
        kb_id = str(row.get("player_id") or "–")
        kb_position = str(row.get("position") or "–")
        try:
            kb_market_value = f"{int(row.get('market_value')):,} €".replace(",", ".") if row.get("market_value") is not None else "–"
        except (TypeError, ValueError):
            kb_market_value = "–"
        candidate = str(row.get("portrait_candidate_name") or "").strip() or f"FotMob #{row.get('fotmob_id') or '–'}"
        candidate_team = str(row.get("portrait_candidate_team") or "").strip()
        candidate_position = str(row.get("portrait_candidate_position") or "").strip()
        candidate_number = str(row.get("portrait_candidate_shirt_number") or "").strip()
        candidate_meta = [value for value in [candidate_team, candidate_position, (f"#{candidate_number}" if candidate_number else "")] if value]
        self.player_label.setText(f"{player} · {club}")
        self.candidate_label.setText(candidate + (f" · {' · '.join(candidate_meta)}" if candidate_meta else ""))
        self.reason_label.setText(
            f"Kickbase: {kb_position} · {kb_market_value} · ID {kb_id}\n"
            f"FotMob-ID: {row.get('fotmob_id') or '–'} · Match-Sicherheit: {int(row.get('portrait_confidence') or 0)}%\n"
            f"{str(row.get('portrait_reason') or 'Keine zusätzliche Begründung')}"
        )
        self._load_preview(str(row.get("portrait_url") or ""))

    def _load_preview(self, url: str) -> None:
        self.preview.clear()
        if not url:
            self.preview.setText("Keine Vorschau verfügbar")
            return
        self.preview.setText("Vorschau lädt …")
        QApplication.processEvents()
        try:
            response = httpx.get(
                url,
                timeout=5.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.fotmob.com/"},
            )
            response.raise_for_status()
            pixmap = QPixmap()
            if not pixmap.loadFromData(response.content):
                raise ValueError("Kein lesbares Bild")
            self.preview.setText("")
            self.preview.setPixmap(pixmap.scaled(190, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            self.preview.setText("Vorschau nicht verfügbar")

    def _accept_current(self) -> None:
        if not self._current or self._accept_worker is not None:
            return
        row = dict(self._current)
        player_id = str(row.get("player_id") or "")
        self.accept_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self.accept_btn.setText("WIRD ÜBERNOMMEN …")
        worker = FunctionWorker(lambda: cache_review_candidate(self.storage, row))
        self._accept_worker = worker
        worker.signals.succeeded.connect(lambda match, pid=player_id: self._accept_succeeded(match, pid))
        worker.signals.failed.connect(self._accept_failed)
        worker.signals.finished.connect(self._accept_finished)
        QThreadPool.globalInstance().start(worker)

    def _accept_succeeded(self, match, player_id: str) -> None:
        self.storage.save_portrait_match(match)
        if getattr(match, "state", "") != "CACHED":
            QMessageBox.warning(self, "Portrait", getattr(match, "reason", "Portrait konnte nicht gespeichert werden."))
        self._notify_parent()
        self._reload()

    def _accept_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Portrait", message)

    def _accept_finished(self) -> None:
        self._accept_worker = None
        self.accept_btn.setText("PORTRAIT ÜBERNEHMEN")
        if self._current:
            self.accept_btn.setEnabled(bool(self._current.get("fotmob_id")))
            self.reject_btn.setEnabled(True)

    def _reject_current(self) -> None:
        if not self._current:
            return
        player_id = str(self._current.get("player_id") or "")
        self.storage.reject_portrait_candidate(player_id)
        self._notify_parent()
        self._reload()

    def _reset_rejected(self) -> None:
        count = self.storage.reset_rejected_portraits()
        if count:
            QMessageBox.information(
                self,
                "Portraits",
                f"{count} abgelehnte Kandidaten wurden wieder auf 'fehlend' gesetzt. "
                "Starte danach erneut den Portrait-Abgleich, um neue Kandidaten zu suchen.",
            )
        self._notify_parent()
        self._reload()

    def _notify_parent(self) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "_refresh_player_master_stats"):
            parent._refresh_player_master_stats()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.storage = Storage()
        self.client = KickbaseClient()
        self.sync_service = KickbaseSyncService(self.client)
        self.league_service = LeagueAnalysisService(self.client, self.storage)
        self._sync_worker: FunctionWorker | None = None
        self._league_worker: FunctionWorker | None = None
        self._league_analysis_worker: FunctionWorker | None = None
        self._manager_squad_worker: FunctionWorker | None = None
        self._league_ownership_worker: FunctionWorker | None = None
        self._budget_worker: FunctionWorker | None = None
        self._league_learning_worker: FunctionWorker | None = None
        self._league_learning: dict = {}
        self._market_worker: FunctionWorker | None = None
        self._bid_worker: FunctionWorker | None = None
        self._market_scanner_worker: FunctionWorker | None = None
        self._market_scanner_dialog: MarketScannerDialog | None = None
        self._player_master_worker: FunctionWorker | None = None
        self._portrait_worker: FunctionWorker | None = None
        self._market_rows: list[dict] = []
        self._market_budget: int = 0
        self._cash_balance: int = 0
        self._active_bid_committed: int = 0
        self._pending_manager_detail: tuple[str, str] | None = None
        # Manager details are intentionally non-modal. Keep strong references so
        # Qt/Python does not destroy a shown window as soon as the local variable
        # in the async callback goes out of scope.
        self._manager_detail_windows: set[ManagerDetailDialog] = set()
        self._player_details_window: PlayerDetailTabsWindow | None = None
        self._intelligence_worker: FunctionWorker | None = None
        self._intelligence_data: dict = {}
        self._force_update_active = False
        self._force_ownership_pending = False
        self.setWindowTitle(APP_DISPLAY_NAME)
        self._fade = FadeController()
        self._global_search_lookup: dict[str, str] = {}
        self.resize(1580, 940)
        self.setMinimumSize(980, 640)

        self.stack = QStackedWidget()
        self.stack.setObjectName("ContentStack")

        shell = QFrame()
        shell.setObjectName("AppShell")
        root = QHBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = self._build_sidebar()
        root.addWidget(self.sidebar, 0)

        content = QFrame()
        content.setObjectName("ContentShell")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._build_topbar())
        content_layout.addWidget(self.stack, 1)
        root.addWidget(content, 1)
        self.setCentralWidget(shell)

        self._build_dashboard_page()
        self._build_squad_page()
        self._build_market_page()
        self._build_league_page()
        self._build_transfers_page()
        self._build_analysis_page()
        self._build_coach_page()
        self._build_settings_page()

        self._season_mode_timer = QTimer(self)
        self._season_mode_timer.setInterval(30_000)
        self._season_mode_timer.timeout.connect(self._check_season_mode_transition)
        self._season_mode_timer.start()
        self._last_season_mode = None
        self._apply_season_mode(force=True)

        self._switch_page(0, self.nav_dashboard)
        self.statusBar().showMessage("Bereit")
        self._login()

    def open_player_detail_tab(self, player_id: str, league_id: str | None = None, player_data: dict | None = None) -> None:
        if self._player_details_window is None:
            self._player_details_window = PlayerDetailTabsWindow(self, self.storage)
        self._player_details_window.open_player(str(player_id), str(league_id) if league_id else None, player_data)

    def _season_override(self) -> str:
        return str(self.storage.get_setting("season_mode_override", "AUTO") or "AUTO").upper()

    def _season_mode(self) -> str:
        return season_mode(override=self._season_override())

    def _season_mode_active(self) -> bool:
        return season_mode_active(override=self._season_override())

    def _season_stats_current(self, league_id: str | None = None) -> bool:
        league_id = str(league_id or (self.league_combo.currentData() if hasattr(self, "league_combo") else "") or self.storage.get_setting("league_id") or "")
        return bool(league_id and self.storage.get_league_setting(league_id, "season_started", "0") == "1")

    def _season_mode_override_changed(self, *_args) -> None:
        if not hasattr(self, "season_mode_combo"):
            return
        value = str(self.season_mode_combo.currentData() or "AUTO")
        self.storage.set_setting("season_mode_override", value)
        self._apply_season_mode(force=True)
        self.refresh_all()

    def _check_season_mode_transition(self) -> None:
        self._apply_season_mode(force=False)

    def _apply_season_mode(self, *, force: bool = False) -> None:
        mode = self._season_mode()
        if not force and mode == getattr(self, "_last_season_mode", None):
            return
        previous = getattr(self, "_last_season_mode", None)
        self._last_season_mode = mode
        active = mode == "SEASON"

        if hasattr(self, "nav_analysis"):
            self.nav_analysis.setVisible(active)
            self.nav_analysis.setText("⚽   Spieltag" if active else "▥   Analyse")
            self._nav_full_texts[self.nav_analysis] = self.nav_analysis.text()
        if hasattr(self, "sidebar_footer_title"):
            self.sidebar_footer_title.setText(f"KICKTRACK V5 · {'SAISON' if active else 'PRESEASON'} · {season_label()}")
        if hasattr(self, "dashboard_page_title"):
            self.dashboard_page_title.setText("SAISON COMMAND CENTER" if active else "PRESEASON COMMAND CENTER")
            self.dashboard_page_subtitle.setText(
                "Spieltag, Aufstellung, Performance und die nächsten Entscheidungen"
                if active else "Was heute wichtig ist – Kaderplätze, Kapital und die nächsten Aktionen"
            )
        if hasattr(self, "squad_page_subtitle"):
            self.squad_page_subtitle.setText(
                "Startelf optimieren, Verfügbarkeit prüfen und sportliche Leistung bewerten"
                if active else "Startkader planen, Investments halten und Verkäufe timen"
            )
        if hasattr(self, "coach_page_title"):
            self.coach_page_title.setText("SAISON COACH" if active else "PRESEASON COACH")
            self.coach_page_subtitle.setText(
                "Aufstellung, Kader-Upgrades, Verkäufe und Marktchancen priorisiert"
                if active else "Nur die nächsten Schritte für Trading, Startkader und Liquidität"
            )
        if hasattr(self, "analysis_page_title"):
            self.analysis_page_title.setText("SPIELTAG & ANALYSE")
            self.analysis_page_subtitle.setText("Aufstellung, nächste Gegner und aktuelle Saisonleistung")
        if hasattr(self, "season_mode_status"):
            override = self._season_override()
            auto_text = SEASON_MODE_START.strftime("%d.%m.%Y · %H:%M") + " Uhr"
            if override == "AUTO":
                self.season_mode_status.setText(
                    f"Aktiv: {'SAISON' if active else 'PRESEASON'} · automatischer Wechsel am {auto_text} (Europe/Berlin)."
                )
            else:
                self.season_mode_status.setText(
                    f"Aktiv: {'SAISON' if active else 'PRESEASON'} · manueller Test-Override. AUTO wechselt am {auto_text}."
                )
        if previous is not None and previous != mode:
            self.statusBar().showMessage(
                "KickTrack ist automatisch in den Saisonmodus gewechselt." if active else "KickTrack läuft wieder im Preseason-Modus.",
                9000,
            )
            # Re-evaluate the visible app immediately at the boundary. This is
            # deliberately scheduled instead of called inline from the timer.
            QTimer.singleShot(0, self.refresh_all)

    def _coach_access_allowed(self, league_id: str | None = None) -> bool:
        """Coach is a normal league feature for every authenticated manager."""
        league_id = str(league_id or self.league_combo.currentData() or self.storage.get_setting("league_id") or "")
        return bool(league_id)

    def _apply_coach_access(self, league_id: str | None = None) -> None:
        allowed = self._coach_access_allowed(league_id)
        self.nav_coach.setVisible(True)
        self.nav_coach.setEnabled(allowed)

    # ------------------------------------------------------------------
    # Shell
    # ------------------------------------------------------------------

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setMinimumWidth(214)
        sidebar.setMaximumWidth(214)
        sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 16, 12, 14)
        layout.setSpacing(6)

        # Use the real Kickbase wordmark again instead of a Unicode placeholder.
        # KickbaseLogo loads the cached/bundled branding and falls back gracefully
        # if the remote asset is not available yet.
        self.sidebar_logo = KickbaseLogo(sidebar, width=180, height=42)
        layout.addWidget(self.sidebar_logo, 0, Qt.AlignLeft | Qt.AlignVCenter)

        divider = QFrame()
        divider.setObjectName("SidebarDivider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        layout.addSpacing(6)

        self.nav_dashboard = QPushButton("⌂   Übersicht")
        self.nav_squad = QPushButton("♙   Kader")
        self.nav_market = QPushButton("◈   Markt")
        self.nav_league = QPushButton("♜   Liga")
        self.nav_league.setVisible(True)
        self.nav_transfers = QPushButton("⇄   Transfers")
        self.nav_analysis = QPushButton("▥   Analyse")
        self.nav_analysis.setVisible(False)
        self.nav_coach = QPushButton("★   Coach")
        self.nav_settings = QPushButton("⚙   Einstellungen")
        self.nav_buttons = [
            self.nav_dashboard,
            self.nav_squad,
            self.nav_market,
            self.nav_league,
            self.nav_transfers,
            self.nav_analysis,
            self.nav_coach,
            self.nav_settings,
        ]
        self._nav_full_texts = {button: button.text() for button in self.nav_buttons}
        self._nav_compact_texts = {
            self.nav_dashboard: "⌂", self.nav_squad: "♙", self.nav_market: "◈",
            self.nav_league: "♜", self.nav_transfers: "⇄", self.nav_analysis: "▥",
            self.nav_coach: "★", self.nav_settings: "⚙",
        }

        top_buttons = self.nav_buttons[:-1]
        for index, button in enumerate(top_buttons):
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(40)
            button.clicked.connect(lambda checked=False, i=index, b=button: self._switch_page(i, b))
            layout.addWidget(button)

        self.nav_market.clicked.connect(lambda checked=False: self._ensure_market_overview())
        self.nav_league.clicked.connect(lambda checked=False: self._ensure_league_data())
        self.nav_analysis.clicked.connect(lambda checked=False: self._load_intelligence())
        self.nav_coach.clicked.connect(lambda checked=False: self._refresh_coach())
        layout.addStretch()

        lower_label = QLabel("SYSTEM")
        lower_label.setObjectName("SidebarSection")
        layout.addWidget(lower_label)

        self.nav_settings.setObjectName("NavButton")
        self.nav_settings.setCheckable(True)
        self.nav_settings.setCursor(Qt.PointingHandCursor)
        self.nav_settings.setFixedHeight(40)
        self.nav_settings.clicked.connect(
            lambda checked=False, b=self.nav_settings: self._switch_page(7, b)
        )
        layout.addWidget(self.nav_settings)

        self.sidebar_footer = QFrame()
        self.sidebar_footer.setObjectName("SidebarFooter")
        footer_layout = QVBoxLayout(self.sidebar_footer)
        footer_layout.setContentsMargins(12, 10, 12, 10)
        footer_layout.setSpacing(2)
        self.sidebar_footer_title = QLabel(f"KICKTRACK V5 · PRESEASON · {season_label()}")
        self.sidebar_footer_title.setObjectName("SidebarFooterTitle")
        footer_hint = QLabel("SQLite Cache aktiv")
        footer_hint.setObjectName("SidebarFooterHint")
        footer_layout.addWidget(self.sidebar_footer_title)
        footer_layout.addWidget(footer_hint)
        layout.addWidget(self.sidebar_footer)
        return sidebar

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(68)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 0, 16, 0)
        layout.setSpacing(10)

        self.league_combo = QComboBox()
        self.league_combo.setObjectName("LeagueCombo")
        self.league_combo.setMinimumWidth(165)
        self.league_combo.setMaximumWidth(210)
        self.league_combo.currentIndexChanged.connect(self._league_changed)
        layout.addWidget(self.league_combo)

        self.global_player_search = QLineEdit()
        self.global_player_search.setObjectName("GlobalPlayerSearch")
        self.global_player_search.setPlaceholderText("⌕ Spieler suchen …")
        self.global_player_search.returnPressed.connect(self._open_global_search_result)
        self._global_search_model = QStringListModel(self)
        self._global_search_completer = QCompleter(self._global_search_model, self)
        self._global_search_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._global_search_completer.setFilterMode(Qt.MatchContains)
        self._global_search_completer.setCompletionMode(QCompleter.PopupCompletion)
        self._global_search_completer.activated[str].connect(self._global_search_selected)
        self.global_player_search.setCompleter(self._global_search_completer)
        layout.addWidget(self.global_player_search, 1)

        self.manager_status_strip = ManagerStatusStrip()
        layout.addWidget(self.manager_status_strip)

        self.sync_btn = QPushButton("↻  AKTUALISIEREN")
        self.sync_btn.setObjectName("Primary")
        self.sync_btn.setCursor(Qt.PointingHandCursor)
        self.sync_btn.clicked.connect(self.sync)

        self.account = AccountChip("Nicht verbunden")
        # Kept for compatibility with the existing deadline calculation. V4 shows
        # the same value inside the persistent manager strip instead.
        self.deadline_chip = QLabel("FR 20:00 · –")
        self.deadline_chip.setObjectName("DeadlineChip")
        self.deadline_chip.setVisible(False)
        self.deadline_chip.setToolTip("Echter Cash-Saldo nach allen aktuell offenen Geboten zur nächsten Freitag-20:00-Deadline.")

        layout.addWidget(self.sync_btn)
        layout.addSpacing(2)
        layout.addWidget(self.account)
        QTimer.singleShot(0, self._refresh_global_player_search)
        QTimer.singleShot(0, self._update_manager_status_strip)
        return bar

    def _refresh_global_player_search(self) -> None:
        if not hasattr(self, "_global_search_model"):
            return
        lookup: dict[str, str] = {}
        labels: list[str] = []
        try:
            rows = self.storage.player_master_rows(state="ACTIVE")
        except Exception:
            rows = []
        for row in rows:
            pid = str(row.get("player_id") or "")
            name = str(row.get("full_name") or row.get("name") or "").strip()
            club = str(row.get("club") or "").strip()
            if not pid or not name:
                continue
            label = f"{name}  ·  {club}" if club else name
            # Duplicate labels are rare; appending the player id makes collisions
            # deterministic without exposing it in the normal UI.
            if label in lookup and lookup[label] != pid:
                label = f"{label}  ·  #{pid}"
            lookup[label] = pid
            labels.append(label)
        labels.sort(key=str.casefold)
        self._global_search_lookup = lookup
        self._global_search_model.setStringList(labels)

    def _global_search_selected(self, text: str) -> None:
        pid = self._global_search_lookup.get(str(text))
        if pid:
            self.global_player_search.clear()
            self.open_player_detail_tab(pid, str(self.league_combo.currentData() or self.storage.get_setting("league_id") or ""))

    def _open_global_search_result(self) -> None:
        query = self.global_player_search.text().strip().casefold()
        if not query:
            return
        exact = self._global_search_lookup.get(self.global_player_search.text().strip())
        if exact:
            self._global_search_selected(self.global_player_search.text().strip())
            return
        for label, pid in self._global_search_lookup.items():
            if query in label.casefold():
                self.global_player_search.clear()
                self.open_player_detail_tab(pid, str(self.league_combo.currentData() or self.storage.get_setting("league_id") or ""))
                return

    def _update_manager_status_strip(self) -> None:
        if not hasattr(self, "manager_status_strip"):
            return
        league_id = str(self.league_combo.currentData() or self.storage.get_setting("league_id") or "") if hasattr(self, "league_combo") else str(self.storage.get_setting("league_id") or "")
        try:
            metrics = self.storage.dashboard_metrics(league_id or None)
        except Exception:
            metrics = {}
        players = self.storage.current_players()
        capacity = squad_capacity(players)
        budget = int(getattr(self, "_cash_balance", 0) or metrics.get("budget") or 0)
        committed = int(getattr(self, "_active_bid_committed", 0) or 0)
        bids = active_bid_count(getattr(self, "_market_rows", []) or [])
        bids_text = str(bids)
        if committed > 0:
            bids_text += f" · {compact_number(committed).lstrip('+')} €"
        deadline_raw = self.deadline_chip.text() if hasattr(self, "deadline_chip") else "–"
        deadline = deadline_raw.split(" · ", 1)[0] if deadline_raw else "–"
        self.manager_status_strip.update_status(
            budget=euro(budget),
            squad=capacity.label,
            bids=bids_text,
            deadline=deadline or "–",
            squad_full=capacity.is_full,
        )

    def _switch_page(self, index: int, active_button: QPushButton) -> None:
        if self.stack.currentIndex() != index:
            self.stack.setCurrentIndex(index)
            self._fade.fade_in(self.stack.currentWidget(), 135)
        for button in self.nav_buttons:
            button.setChecked(button is active_button)
        # Some tables sit on tabs that were hidden during initial layout. Refit their
        # columns after the new page becomes visible so they use the full width.
        QTimer.singleShot(0, self._apply_responsive_layout)
        QTimer.singleShot(0, self._update_manager_status_strip)
        if index == 0:
            league_id = self.league_combo.currentData() if hasattr(self, "league_combo") else None
            QTimer.singleShot(0, lambda lid=str(league_id) if league_id else None: self._refresh_dashboard(lid))

    def _page_header(self, title_text: str, subtitle_text: str) -> tuple[QLabel, QLabel]:
        title = QLabel(title_text)
        title.setObjectName("PageTitle")
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("Subtle")
        return title, subtitle

    def _add_scroll_page(self, page: QWidget) -> None:
        scroll = QScrollArea()
        scroll.setObjectName("PageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        self.stack.addWidget(scroll)

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def _build_dashboard_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(12)

        self.dashboard_page_title, self.dashboard_page_subtitle = self._page_header(
            "PRESEASON COMMAND CENTER",
            "Was heute wichtig ist – Kaderplätze, Kapital und die nächsten Aktionen",
        )
        layout.addWidget(self.dashboard_page_title)
        layout.addWidget(self.dashboard_page_subtitle)

        self.dashboard_focus = DashboardFocusPanel()
        layout.addWidget(self.dashboard_focus)

        cards_grid = QGridLayout()
        cards_grid.setHorizontalSpacing(10)
        self.dashboard_cards_grid = cards_grid
        self.dash_team_value = MetricCard("TEAMWERT", "–", "aktueller Kaderwert", icon="◎", accent="orange")
        self.dash_profit = MetricCard("GEWINN / VERLUST", "–", "seit Ligastart", icon="↗", accent="green")
        self.dash_budget = MetricCard("BUDGET", "–", "Kickbase Kontostand", icon="€", accent="gold")
        self.dash_day = MetricCard("MARKTWERT 24H", "–", "aktueller Kader", icon="Δ", accent="purple")
        self.dashboard_cards = [self.dash_team_value, self.dash_profit, self.dash_budget]
        for index, card in enumerate(self.dashboard_cards):
            cards_grid.addWidget(card, 0, index)
            cards_grid.setColumnStretch(index, 1)
        layout.addLayout(cards_grid)

        # Existing metric objects remain alive as data sources/tooltips, but V4 no
        # longer puts nine equally loud KPI cards on the landing page.
        self.dash_open = MetricCard("AKTUELLER KADER +/-", "–", "Marktwert vs. Kaufpreis", icon="±", accent="purple", compact=True)
        self.dash_realized = MetricCard("VERKAUFSGEWINN/-VERLUST", "–", "abgeschlossene Verkäufe", icon="↕", accent="green", compact=True)
        self.dash_assets = MetricCard("GESAMTVERMÖGEN", "–", "Kaderwert + Budget", icon="Σ", accent="gold", compact=True)
        self.dash_transfer_count = MetricCard("TRANSFERS", "–", "Käufe + Verkäufe", icon="⇄", accent="orange", compact=True)
        self.dash_status = MetricCard("KADERSTATUS", "–", "Verfügbarkeit", icon="!", accent="purple", compact=True)
        self.dashboard_secondary_cards = [self.dash_open, self.dash_realized, self.dash_assets, self.dash_transfer_count, self.dash_status]
        self.dashboard_secondary_grid = None

        working = QGridLayout()
        working.setHorizontalSpacing(10)
        working.setVerticalSpacing(10)
        self.dashboard_activity_feed = ActivityFeed()
        self.dashboard_value_chart = ChartPanel(
            "KADERWERT-VERLAUF", "Tägliche Snapshots seit der ersten Erfassung", height=220
        )
        working.addWidget(self.dashboard_activity_feed, 0, 0)
        working.addWidget(self.dashboard_value_chart, 0, 1, 1, 2)
        working.setColumnStretch(0, 1)
        working.setColumnStretch(1, 1)
        working.setColumnStretch(2, 1)
        layout.addLayout(working)

        # Detailed allocation/transfer charts moved to their specialised pages in
        # V4. Do not keep invisible QChart instances alive on the command center.
        self.dashboard_positions_chart = None
        self.dashboard_transfers_chart = None
        self.dashboard_movers_chart = None
        self.dashboard_charts_grid = None
        self.dashboard_charts = [self.dashboard_value_chart]

        movers_panel = QFrame()
        movers_panel.setObjectName("TablePanel")
        movers_layout = QVBoxLayout(movers_panel)
        movers_layout.setContentsMargins(0, 0, 0, 0)
        movers_layout.setSpacing(0)
        movers_header = QFrame()
        movers_header.setObjectName("TablePanelHeader")
        section_row = QHBoxLayout(movers_header)
        section_row.setContentsMargins(14, 11, 14, 10)
        section = QLabel("DEINE SPIELER · BEWEGUNG")
        section.setObjectName("SectionMini")
        hint = QLabel("Portrait + Doppelklick öffnet den Player Hub")
        hint.setObjectName("Tiny")
        section_row.addWidget(section)
        section_row.addStretch()
        section_row.addWidget(hint)
        movers_layout.addWidget(movers_header)

        self.dashboard_table = self._make_table(
            ["SPIELER", "POS", "MARKTWERT", "24H", "P/L", "ROI"],
            [250, 70, 140, 100, 115, 90],
        )
        self.dashboard_table.setObjectName("EmbeddedTable")
        self.dashboard_table.verticalHeader().setDefaultSectionSize(52)
        self.dashboard_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.dashboard_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.dashboard_table.setMinimumHeight(220)
        self.dashboard_table.itemDoubleClicked.connect(self._open_dashboard_player_detail)
        movers_layout.addWidget(self.dashboard_table, 1)
        layout.addWidget(movers_panel, 1)
        self._add_scroll_page(page)

    # ------------------------------------------------------------------
    # Squad
    # ------------------------------------------------------------------

    def _build_squad_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(12)

        self.squad_page_title, self.squad_page_subtitle = self._page_header(
            "MEIN KADER",
            "Startkader planen, Investments halten und Verkäufe timen",
        )
        layout.addWidget(self.squad_page_title)
        layout.addWidget(self.squad_page_subtitle)

        summary = QGridLayout()
        self.squad_analysis_cards_grid = summary
        summary.setHorizontalSpacing(10)
        summary.setVerticalSpacing(10)
        self.squad_quality_card = MetricCard("STARTER", "–", "deine Rolle STAMM", icon="◆", accent="green", compact=True)
        self.squad_core_card = MetricCard("INVESTS", "–", "deine Rolle INVEST", icon="↗", accent="purple", compact=True)
        self.squad_invest_card = MetricCard("TRANSFERLISTE", "–", "explizit zum Verkauf", icon="€", accent="gold", compact=True)
        self.squad_sell_card = MetricCard("AKTION NÖTIG", "–", "Verkaufen / Verkauf prüfen", icon="!", accent="orange", compact=True)
        self.squad_analysis_cards = [self.squad_quality_card, self.squad_core_card, self.squad_invest_card, self.squad_sell_card]
        for i, card in enumerate(self.squad_analysis_cards):
            summary.addWidget(card, 0, i)
            summary.setColumnStretch(i, 1)
        layout.addLayout(summary)

        self.squad_pitch = SquadPitchWidget()
        self.squad_pitch.set_formation(self.storage.get_setting("squad_pitch_formation", "AUTO"))
        self.squad_pitch.formationChanged.connect(
            lambda formation: self.storage.set_setting("squad_pitch_formation", formation)
        )
        self.squad_pitch.playerActivated.connect(
            lambda player_id: self.open_player_detail_tab(
                str(player_id),
                str(self.league_combo.currentData() or self.storage.get_setting("league_id") or ""),
                self.storage.get_player(str(player_id)) or {},
            )
        )
        layout.addWidget(self.squad_pitch)
        self.squad_bench = SquadBenchStrip()
        self.squad_bench.playerActivated.connect(
            lambda player_id: self.open_player_detail_tab(
                str(player_id),
                str(self.league_combo.currentData() or self.storage.get_setting("league_id") or ""),
                self.storage.get_player(str(player_id)) or {},
            )
        )
        layout.addWidget(self.squad_bench)

        status_panel = QFrame()
        status_panel.setObjectName("Panel")
        status_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(16, 14, 16, 14)
        status_layout.setSpacing(8)
        status_head = QHBoxLayout()
        status_title = QLabel("KADERSTATUS")
        status_title.setObjectName("SectionMini")
        self.squad_status_summary = QLabel("–")
        self.squad_status_summary.setObjectName("Tiny")
        status_head.addWidget(status_title)
        status_head.addStretch()
        status_head.addWidget(self.squad_status_summary)
        status_layout.addLayout(status_head)
        self.squad_status_table = self._make_table(
            ["SPIELER", "VEREIN", "STATUS"],
            [240, 210, 360],
        )
        self.squad_status_table.setItemDelegateForColumn(1, ClubItemDelegate(self.squad_status_table))
        self.squad_status_table.set_responsive_widths([240, 210, 360], [180, 150, 240])
        self.squad_status_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.squad_status_table.horizontalHeader().setVisible(False)
        self.squad_status_table.setObjectName("EmbeddedTable")
        self.squad_status_table.setMinimumHeight(0)
        self.squad_status_table.setMaximumHeight(190)
        self.squad_status_table.itemDoubleClicked.connect(self._open_status_player_detail)
        status_layout.addWidget(self.squad_status_table)
        self.squad_status_empty = QLabel("Alles verfügbar")
        self.squad_status_empty.setObjectName("Tiny")
        self.squad_status_empty.setAlignment(Qt.AlignCenter)
        self.squad_status_empty.setVisible(False)
        status_layout.addWidget(self.squad_status_empty)
        layout.addWidget(status_panel)

        section_row = QHBoxLayout()
        section = QLabel("KADER · DETAILANSICHT")
        section.setObjectName("SectionTitle")
        self.squad_info_btn = QPushButton("ⓘ BEWERTUNG")
        self.squad_info_btn.setVisible(False)
        self.squad_info_btn.clicked.connect(self._open_squad_scoring_info)
        section_row.addWidget(section)
        section_row.addStretch()
        section_row.addWidget(self.squad_info_btn)
        layout.addLayout(section_row)

        self.squad_table = self._make_table(
            ["SPIELER", "VEREIN", "POS", "ROLLE", "MARKTWERT", "24H", "22U", "P/L", "STARTKADER", "TRADE", "AKTION"],
            [180, 140, 56, 170, 122, 80, 80, 96, 86, 86, 155],
        )
        self.squad_table.set_responsive_widths(
            [180, 140, 56, 170, 122, 80, 80, 96, 86, 86, 155],
            [142, 115, 52, 158, 106, 70, 70, 84, 76, 76, 136],
        )
        self.squad_table.setItemDelegateForColumn(1, ClubItemDelegate(self.squad_table))
        self.squad_table.setItemDelegateForColumn(10, RecommendationChipDelegate(self.squad_table))
        # The Kader table never owns vertical scrolling. A squad is capped at
        # 18 players, so showing all rows at once is both feasible and much nicer
        # to navigate. The surrounding page scroll area now owns the vertical
        # scroll for pitch, bench, status and detail table as one continuous page.
        self.squad_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.squad_table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self.squad_table.verticalHeader().setDefaultSectionSize(48)
        self.squad_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.squad_table.setMinimumHeight(0)
        self.squad_table.itemDoubleClicked.connect(self._open_player_detail)
        layout.addWidget(self.squad_table)
        self._add_scroll_page(page)

    def _open_status_player_detail(self, item: QTableWidgetItem) -> None:
        player_id = item.data(Qt.UserRole)
        if not player_id:
            first = self.squad_status_table.item(item.row(), 0)
            player_id = first.data(Qt.UserRole) if first else None
        if player_id:
            league_id = self.league_combo.currentData() or self.storage.get_setting("league_id")
            open_player_detail_window(self, self.storage, str(player_id), str(league_id) if league_id else None)

    # ------------------------------------------------------------------
    # Market intelligence
    # ------------------------------------------------------------------

    def _build_market_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(12)

        title, subtitle = self._page_header(
            "MARKT",
            "Trading-Chancen und Spieler für deinen Startkader",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)

        controls = QFrame()
        controls.setObjectName("Panel")
        controls_row = QHBoxLayout(controls)
        controls_row.setContentsMargins(14, 10, 14, 10)
        controls_row.setSpacing(10)
        self.market_search = QLineEdit()
        self.market_search.setPlaceholderText("Spieler suchen …")
        self.market_search.textChanged.connect(self._apply_market_filters)
        self.market_position = QComboBox()
        self.market_position.addItems(["Alle Positionen", "TW", "ABW", "MF", "ST"])
        self.market_position.currentIndexChanged.connect(self._apply_market_filters)
        self.market_verdict = QComboBox()
        self.market_verdict.addItems(["Alle Aktionen", "KADERZIEL", "INVEST", "BEOBACHTEN", "PASS"])
        self.market_verdict.currentIndexChanged.connect(self._apply_market_filters)
        self.market_affordable = QCheckBox("Nur bezahlbar")
        self.market_affordable.stateChanged.connect(self._apply_market_filters)
        self.market_under_mv = QCheckBox("Nur unter MW")
        self.market_under_mv.stateChanged.connect(self._apply_market_filters)
        self.market_own_bid = QCheckBox("Eigenes Gebot")
        self.market_own_bid.stateChanged.connect(self._apply_market_filters)
        self.market_kickbase_only = QCheckBox("Nur Kickbase")
        self.market_kickbase_only.stateChanged.connect(self._apply_market_filters)
        self.market_watchlist_only = QCheckBox("★ Watchlist")
        self.market_watchlist_only.setToolTip("Nur Spieler anzeigen, die du in dieser Liga beobachtest")
        self.market_watchlist_only.stateChanged.connect(self._apply_market_filters)
        self.market_refresh_btn = QPushButton("MARKT AKTUALISIEREN")
        self.market_refresh_btn.clicked.connect(self._load_market_overview)
        controls_row.addWidget(self.market_search, 1)
        controls_row.addWidget(self.market_position)
        controls_row.addWidget(self.market_verdict)
        controls_row.addWidget(self.market_affordable)
        controls_row.addWidget(self.market_under_mv)
        controls_row.addWidget(self.market_own_bid)
        controls_row.addWidget(self.market_kickbase_only)
        controls_row.addWidget(self.market_watchlist_only)
        controls_row.addWidget(self.market_refresh_btn)
        layout.addWidget(controls)

        # Market overview is an information strip, not four dashboard hero cards.
        summary_panel = QFrame()
        summary_panel.setObjectName("Panel")
        summary = QHBoxLayout(summary_panel)
        summary.setContentsMargins(6, 4, 6, 4)
        summary.setSpacing(4)
        self.market_count_card = CompactMetric("SPIELER", "–", "aktuell sichtbar", accent="orange")
        self.market_under_card = CompactMetric("UNTER MW", "–", "Preis < Marktwert", accent="green")
        self.market_interest_card = CompactMetric("CHANCEN", "–", "Kaderziele + Investments", accent="purple")
        self.market_budget_card = CompactMetric("FREIES BUDGET", "–", "nach aktiven Geboten", accent="gold")
        self.market_model_card = CompactMetric("22U MODELL", "–", "noch keine Auswertung", accent="blue")
        self.market_cards = [self.market_count_card, self.market_under_card, self.market_interest_card, self.market_budget_card, self.market_model_card]
        for card in self.market_cards:
            summary.addWidget(card, 1)
        layout.addWidget(summary_panel)

        header = QHBoxLayout()
        section = QLabel("TRANSFERMARKT")
        section.setObjectName("SectionTitle")
        self.market_status = QLabel("Noch nicht geladen")
        self.market_status.setObjectName("Tiny")
        self.market_info_btn = QPushButton("ⓘ BEWERTUNG")
        self.market_info_btn.setVisible(False)
        self.market_info_btn.clicked.connect(self._open_market_scoring_info)
        self.market_scanner_btn = QPushButton("MW-SCANNER")
        self.market_scanner_btn.setToolTip("Ligaweiten Marktwert-Scanner aus 365-Tage-Historien laden. Daten werden 24 h gecacht.")
        self.market_scanner_btn.clicked.connect(self._load_market_scanner)
        self.market_model_btn = QPushButton("MODELLGÜTE")
        self.market_model_btn.setToolTip("Zeigt, wie gut die gespeicherten 22-Uhr-Prognosen gegen echte Marktwert-Refreshes waren.")
        self.market_model_btn.clicked.connect(self._open_mv_model_quality)
        self.market_optimizer_btn = QPushButton("STARTKADER-OPTIMIZER")
        self.market_optimizer_btn.setToolTip("Baut aus deinem Kader und aktuellen Marktspielern die stärkste finanzierbare Startelf.")
        self.market_optimizer_btn.clicked.connect(self._open_preseason_optimizer)
        self.market_finance_btn = QPushButton("FINANZIERUNG")
        self.market_finance_btn.setEnabled(False)
        self.market_finance_btn.clicked.connect(self._open_market_financing)
        header.addWidget(section)
        header.addStretch()
        header.addWidget(self.market_status)
        header.addWidget(self.market_info_btn)
        header.addWidget(self.market_scanner_btn)
        header.addWidget(self.market_model_btn)
        header.addWidget(self.market_optimizer_btn)
        header.addWidget(self.market_finance_btn)
        layout.addLayout(header)

        # Master/detail layout: the table is for scanning; the right panel
        # explains the selected player without hiding decision-critical data
        # in tooltips or modal dialogs.
        self.market_table = self._make_table(
            ["SPIELER", "VEREIN", "POS", "ANBIETER", "MARKTWERT", "24H", "22U", "PREIS", "DEIN GEBOT", "VALUE", "ABLAUF", "EMPFEHLUNG"],
            [210, 108, 50, 112, 96, 68, 72, 92, 102, 66, 86, 126],
        )
        self.market_table.setItemDelegateForColumn(1, ClubItemDelegate(self.market_table))
        self.market_table.setItemDelegateForColumn(11, RecommendationChipDelegate(self.market_table))
        self.market_table.set_responsive_widths(
            [210, 108, 50, 112, 96, 68, 72, 92, 102, 66, 86, 126],
            [180, 90, 46, 92, 84, 58, 60, 82, 88, 58, 74, 106],
        )
        self.market_table.verticalHeader().setDefaultSectionSize(50)
        self.market_countdown_timer = QTimer(self)
        self.market_countdown_timer.setInterval(1000)
        self.market_countdown_timer.timeout.connect(self._refresh_market_expiry_cells)
        self.market_countdown_timer.start()
        self.market_table.setMinimumHeight(500)
        # V4.3: the market is true master/detail. Hover only highlights a row;
        # all analysis belongs to the explicitly clicked player on the right.
        self.market_table.set_hover_popovers_enabled(False)
        self._market_selected_player_id = None
        self._market_selected_player_data = None
        self._market_rows_by_id: dict[str, dict] = {}
        self.market_table.cellClicked.connect(self._market_row_clicked)
        self.market_table.itemSelectionChanged.connect(self._market_selection_changed)
        self.market_table.itemDoubleClicked.connect(self._open_market_player_detail)

        self.market_detail_panel = QFrame()
        self.market_detail_panel.setObjectName("MarketDetailPanel")
        self.market_detail_panel.setMinimumWidth(320)
        self.market_detail_panel.setMaximumWidth(430)
        detail = QVBoxLayout(self.market_detail_panel)
        detail.setContentsMargins(18, 16, 18, 16)
        detail.setSpacing(9)

        portrait_hero = QFrame()
        portrait_hero.setObjectName("MarketPortraitHero")
        portrait_layout = QVBoxLayout(portrait_hero)
        portrait_layout.setContentsMargins(12, 10, 12, 0)
        portrait_layout.setSpacing(2)
        self.market_detail_portrait = PlayerAvatar(112)
        self.market_detail_portrait.setObjectName("MarketPortrait")
        portrait_layout.addWidget(self.market_detail_portrait, 0, Qt.AlignHCenter | Qt.AlignBottom)
        self.market_detail_clubline = QLabel("")
        self.market_detail_clubline.setObjectName("MarketHeroClub")
        self.market_detail_clubline.setAlignment(Qt.AlignCenter)
        portrait_layout.addWidget(self.market_detail_clubline)
        detail.addWidget(portrait_hero)

        self.market_detail_signal = QLabel("SPIELER AUSWÄHLEN")
        self.market_detail_signal.setObjectName("MarketDetailSignal")
        self.market_detail_name = QLabel("Transfermarkt")
        self.market_detail_name.setObjectName("MarketDetailName")
        self.market_detail_meta = QLabel("Wähle links einen Spieler für die Entscheidungsansicht.")
        self.market_detail_meta.setObjectName("Subtle")
        self.market_detail_meta.setWordWrap(True)
        detail.addWidget(self.market_detail_signal)
        detail.addWidget(self.market_detail_name)
        detail.addWidget(self.market_detail_meta)

        money = QFrame()
        money.setObjectName("MarketDetailBox")
        money_layout = QGridLayout(money)
        money_layout.setContentsMargins(12, 10, 12, 10)
        money_layout.setHorizontalSpacing(12)
        money_layout.setVerticalSpacing(5)
        self.market_detail_mv = QLabel("–")
        self.market_detail_price = QLabel("–")
        self.market_detail_own_bid = QLabel("–")
        self.market_detail_max = QLabel("–")
        self.market_detail_liga = QLabel("–")
        for label in (
            self.market_detail_mv, self.market_detail_price, self.market_detail_own_bid,
            self.market_detail_max, self.market_detail_liga,
        ):
            label.setObjectName("MarketDetailValue")
        for row, (title_text, value_label) in enumerate([
            ("MARKTWERT", self.market_detail_mv),
            ("PREIS", self.market_detail_price),
            ("DEIN GEBOT", self.market_detail_own_bid),
            ("MAX-BID", self.market_detail_max),
            ("LIGA-TYPISCH", self.market_detail_liga),
        ]):
            key = QLabel(title_text)
            key.setObjectName("Tiny")
            money_layout.addWidget(key, row, 0)
            money_layout.addWidget(value_label, row, 1, Qt.AlignRight)
        detail.addWidget(money)

        self.market_detail_scores = QLabel("STARTKADER –   ·   TRADE –")
        self.market_detail_scores.setObjectName("MarketDetailScores")
        self.market_detail_scores.setVisible(False)
        detail.addWidget(self.market_detail_scores)
        self.market_score_fit = MarketScoreBar("STARTKADER")
        self.market_score_trade = MarketScoreBar("TRADE")
        self.market_score_value = MarketScoreBar("VALUE")
        detail.addWidget(self.market_score_fit)
        detail.addWidget(self.market_score_trade)
        detail.addWidget(self.market_score_value)
        self.market_detail_trend = QLabel("24H –   ·   22U –   ·   3T –   ·   7T –")
        self.market_detail_trend.setObjectName("Subtle")
        detail.addWidget(self.market_detail_trend)

        self.market_detail_reason = QLabel("Die wichtigsten Gründe erscheinen hier.")
        self.market_detail_reason.setObjectName("MarketDetailReason")
        self.market_detail_reason.setWordWrap(True)
        detail.addWidget(self.market_detail_reason)

        self.market_detail_history = QLabel("")
        self.market_detail_history.setObjectName("MarketDetailHistory")
        self.market_detail_history.setWordWrap(True)
        detail.addWidget(self.market_detail_history)
        detail.addStretch()

        detail_actions = QGridLayout()
        detail_actions.setContentsMargins(0, 6, 0, 0)
        detail_actions.setHorizontalSpacing(10)
        detail_actions.setVerticalSpacing(10)

        self.market_detail_open_btn = QPushButton("DETAILS")
        self.market_detail_open_btn.setEnabled(False)
        self.market_detail_open_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.market_detail_open_btn.setMinimumHeight(38)
        self.market_detail_open_btn.setToolTip("Vollständige Spieler-Detailansicht öffnen")
        self.market_detail_open_btn.clicked.connect(self._open_market_player_detail)

        self.market_detail_bid_btn = QPushButton("BIETEN")
        self.market_detail_bid_btn.setObjectName("Primary")
        self.market_detail_bid_btn.setEnabled(False)
        self.market_detail_bid_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.market_detail_bid_btn.setMinimumHeight(38)
        self.market_detail_bid_btn.setToolTip("Echtes Gebot in Kickbase abgeben")
        self.market_detail_bid_btn.clicked.connect(self._open_market_bid)

        self.market_detail_finance_btn = QPushButton("FINANZIERUNG")
        self.market_detail_finance_btn.setEnabled(False)
        self.market_detail_finance_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.market_detail_finance_btn.setMinimumHeight(38)
        self.market_detail_finance_btn.clicked.connect(self._open_market_financing)

        detail_actions.addWidget(self.market_detail_open_btn, 0, 0)
        detail_actions.addWidget(self.market_detail_bid_btn, 0, 1)
        detail_actions.addWidget(self.market_detail_finance_btn, 1, 0, 1, 2)
        detail_actions.setColumnStretch(0, 1)
        detail_actions.setColumnStretch(1, 1)
        detail.addLayout(detail_actions)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("MarketSplitter")
        splitter.addWidget(self.market_table)
        splitter.addWidget(self.market_detail_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1040, 360])
        layout.addWidget(splitter, 1)
        self._add_scroll_page(page)

    @staticmethod
    def _scanner_delta(history: list[dict], days: int) -> int | None:
        if not history:
            return None
        latest = history[-1]
        latest_value = int(latest.get("value") or 0)
        try:
            latest_date = datetime.fromisoformat(str(latest.get("snapshot_date"))[:10]).date()
        except (TypeError, ValueError):
            return None
        target = latest_date.toordinal() - int(days)
        comparison = None
        for entry in history:
            try:
                entry_date = datetime.fromisoformat(str(entry.get("snapshot_date"))[:10]).date()
            except (TypeError, ValueError):
                continue
            if entry_date.toordinal() <= target:
                comparison = entry
        if comparison is None:
            return None
        return latest_value - int(comparison.get("value") or 0)

    def _load_market_scanner(self, *_args) -> None:
        league_id = self.league_combo.currentData() if hasattr(self, "league_combo") else None
        league_id = str(league_id) if league_id else self.storage.get_setting("league_id")
        if not league_id or self._market_scanner_worker is not None:
            return
        self.market_scanner_btn.setEnabled(False)
        self.market_scanner_btn.setText("SCANNER LÄDT …")
        self.market_status.setText("Ligaweiter MW-Scanner lädt 365-Tage-Historien …")

        def load_scanner():
            players = self.client.competition_players()

            # Canonical availability comes from teamprofile ``st``/``stl``.
            # The generic competition player catalogue has another field called
            # ``status`` with different values (e.g. 3/5), so never use that as
            # injury/availability state.
            status_map = self.storage.cache_get("competition:1:player_statuses", 6 * 3600)
            if not isinstance(status_map, dict):
                status_map = self.client.competition_player_statuses()
                if status_map:
                    self.storage.cache_set("competition:1:player_statuses", status_map)

            histories: dict[str, list[dict]] = {}
            missing: list[dict] = []
            for player in players:
                pid = str(player.get("player_id") or "")
                if not pid:
                    continue
                cache_key = f"mv_scanner:365:{pid}"
                payload = self.storage.cache_get(cache_key, 24 * 3600)
                if isinstance(payload, dict):
                    histories[pid] = normalize_market_value_history(payload)
                else:
                    missing.append(player)

            # Same basic strategy as Kickbase-Insights: parallel read-only history
            # requests. Keep the pool modest and persist/cache sequentially below.
            fetched: dict[str, dict] = {}
            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = {
                    executor.submit(self.client.market_value_history, league_id, str(player["player_id"]), 365): str(player["player_id"])
                    for player in missing
                }
                for future in as_completed(futures):
                    pid = futures[future]
                    try:
                        payload = future.result()
                    except Exception:
                        continue
                    if isinstance(payload, dict):
                        fetched[pid] = payload

            for pid, payload in fetched.items():
                self.storage.cache_set(f"mv_scanner:365:{pid}", payload)
                normalized = normalize_market_value_history(payload)
                histories[pid] = normalized
                if normalized:
                    self.storage.upsert_market_value_history(pid, normalized)

            covered, total = self.storage.ownership_coverage(league_id)
            ownership_complete = bool(total and covered >= total)
            result = []
            for player in players:
                pid = str(player.get("player_id") or "")
                history = histories.get(pid) or self.storage.all_history(pid)
                if history:
                    current = int(player.get("market_value") or 0) or int(history[-1].get("value") or 0)
                else:
                    current = int(player.get("market_value") or 0)
                owner = self.storage.player_owner(league_id, pid)
                owner_name = str(owner.get("manager_name") or "") if owner else ("FREI" if ownership_complete else "–")
                verified_status = status_map.get(pid) if isinstance(status_map, dict) else None
                status_fields = verified_status if isinstance(verified_status, dict) else {}
                result.append({
                    **player,
                    **status_fields,
                    "market_value": current,
                    "d1": self._scanner_delta(history, 1),
                    "d3": self._scanner_delta(history, 3),
                    "d7": self._scanner_delta(history, 7),
                    "d30": self._scanner_delta(history, 30),
                    "history_days": len(history),
                    "owner": owner_name,
                })
            return result

        worker = FunctionWorker(load_scanner)
        self._market_scanner_worker = worker
        worker.signals.succeeded.connect(self._market_scanner_loaded)
        worker.signals.failed.connect(self._market_scanner_failed)
        worker.signals.finished.connect(self._market_scanner_finished)
        QThreadPool.globalInstance().start(worker)

    def _market_scanner_loaded(self, rows: list[dict]) -> None:
        self._market_scanner_dialog = MarketScannerDialog(self, rows)
        self._market_scanner_dialog.show()
        self._market_scanner_dialog.raise_()
        self._market_scanner_dialog.activateWindow()
        complete_30 = sum(1 for row in rows if row.get("d30") is not None)
        self.market_status.setText(f"MW-Scanner: {len(rows)} Spieler · {complete_30} mit ≥30 Tagen Historie")

    def _market_scanner_failed(self, message: str) -> None:
        self.market_status.setText("MW-Scanner konnte nicht geladen werden")
        self.statusBar().showMessage("MW-Scanner: " + str(message).splitlines()[0], 8000)

    def _market_scanner_finished(self) -> None:
        self._market_scanner_worker = None
        if hasattr(self, "market_scanner_btn"):
            self.market_scanner_btn.setEnabled(True)
            self.market_scanner_btn.setText("MW-SCANNER")

    def _toggle_market_details(self, enabled: bool) -> None:
        # Kept for compatibility with older UI state; master/detail no longer
        # needs a second table-column mode.
        return

    def _ensure_market_overview(self, *_args) -> None:
        """Show already loaded market data without refreshing it on every tab click."""
        if getattr(self, "_market_rows", None):
            self._apply_market_filters()
            return
        self._load_market_overview()

    def _load_market_overview(self, *_args) -> None:
        league_id = self.league_combo.currentData()
        league_id = str(league_id) if league_id else self.storage.get_setting("league_id")
        if not league_id or self._market_worker is not None:
            return
        manager_id = self.storage.get_league_setting(league_id, "manager_id") or self.storage.get_setting("manager_id")
        owned_player_ids = {str(p.get("player_id")) for p in self.storage.current_players() if p.get("player_id") is not None}
        self.market_refresh_btn.setEnabled(False)
        self.market_refresh_btn.setText("◌  MARKT LÄDT …")
        self.market_status.setText("Transfermarkt wird geladen …")
        def load_market_with_statuses():
            data = self.client.market_overview(league_id, manager_id, owned_player_ids)

            # The normal transfer-market payload does not reliably include `st`
            # / `stl` for every player. Reuse the same canonical teamprofile map
            # as the MW scanner so Market, Kader and Player Detail all speak the
            # same status language. Six-hour caching keeps this to ~18 requests
            # only when the cache is cold, not on every market refresh.
            status_map = self.storage.cache_get("competition:1:player_statuses", 6 * 3600)
            if not isinstance(status_map, dict):
                status_map = self.client.competition_player_statuses()
                if status_map:
                    self.storage.cache_set("competition:1:player_statuses", status_map)

            if isinstance(status_map, dict):
                for collection in ("market_entries", "own_listings"):
                    for row in data.get(collection, []) if isinstance(data, dict) else []:
                        if not isinstance(row, dict):
                            continue
                        pid = str(row.get("player_id") or "")
                        canonical = status_map.get(pid)
                        if not isinstance(canonical, dict):
                            continue
                        # Prefer canonical teamprofile status over a missing market
                        # value. If the market explicitly supplies st/stl they should
                        # agree, but teamprofile is our single source of truth.
                        row["status"] = canonical.get("status")
                        row["status_list"] = canonical.get("status_list") or []
            return data

        worker = FunctionWorker(load_market_with_statuses)
        self._market_worker = worker
        worker.signals.succeeded.connect(lambda data, lid=league_id: self._market_overview_loaded(lid, data))
        worker.signals.failed.connect(self._market_overview_failed)
        worker.signals.finished.connect(self._market_overview_finished)
        QThreadPool.globalInstance().start(worker)

    @staticmethod
    def _mv_prediction_target_date() -> date:
        """Refresh day targeted by a prediction made right now (Europe/Berlin)."""
        now = datetime.now(ZoneInfo("Europe/Berlin"))
        today = now.date()
        # Kickbase refreshes around 22:00 local time. After that point a freshly
        # calculated forecast necessarily targets tomorrow's refresh.
        return today if now.hour < 22 else today + timedelta(days=1)

    @staticmethod
    def _mv_prediction_evaluation_through() -> date:
        """Latest day that can safely be treated as a completed 22:00 refresh."""
        now = datetime.now(ZoneInfo("Europe/Berlin"))
        return now.date() if now.hour >= 22 else now.date() - timedelta(days=1)

    def _refresh_mv_model_quality(self, league_id: str | None = None) -> None:
        if not hasattr(self, "market_model_card"):
            return
        lid = str(league_id or self.league_combo.currentData() or self.storage.get_setting("league_id") or "")
        if not lid:
            return
        summary = self.storage.mv_prediction_summary(lid)
        n = int(summary.get("evaluated") or 0)
        if n <= 0:
            self.market_model_card.value_label.setText("–")
            self.market_model_card.hint_label.setText("noch keine Auswertung")
            self.market_model_card.setToolTip("Nach dem nächsten abgeschlossenen 22-Uhr-Refresh kann KickTrack die erste Prognose bewerten.")
            return
        hit = float(summary.get("direction_hit_rate") or 0.0)
        mae = int(round(float(summary.get("mae") or 0.0)))
        self.market_model_card.value_label.setText(f"{hit:.0f}%")
        self.market_model_card.hint_label.setText(f"Richtung · MAE {compact_number(mae).lstrip('+')} € · n={n}")
        median_error = int(summary.get("median_abs_error") or 0)
        within = float(summary.get("within_100k_rate") or 0.0)
        bias = int(round(float(summary.get("bias") or 0.0)))
        high_hit = summary.get("high_confidence_hit_rate")
        high_count = int(summary.get("high_confidence_count") or 0)
        lines = [
            f"Bewertete Prognosen: {n}",
            f"Richtungs-Trefferquote: {hit:.1f}%",
            f"Mittlerer absoluter Fehler (MAE): {euro(mae)}",
            f"Median absoluter Fehler: {euro(median_error)}",
            f"Innerhalb ±100.000 €: {within:.1f}%",
            f"Durchschnittlicher Bias: {euro(bias)}",
        ]
        if high_hit is not None:
            lines.append(f"HOCH-Confidence Richtung: {float(high_hit):.1f}% (n={high_count})")
        self.market_model_card.setToolTip("\n".join(lines))

    def _open_mv_model_quality(self) -> None:
        league_id = self.league_combo.currentData() if hasattr(self, "league_combo") else None
        league_id = str(league_id) if league_id else str(self.storage.get_setting("league_id") or "")
        if not league_id:
            return
        summary = self.storage.mv_prediction_summary(league_id)
        rows = self.storage.mv_prediction_rows(league_id, limit=12)
        n = int(summary.get("evaluated") or 0)
        if n <= 0:
            QMessageBox.information(
                self, "22U Modellgüte",
                "Noch keine Prognose konnte gegen einen abgeschlossenen 22-Uhr-Refresh ausgewertet werden.\n\n"
                "KickTrack speichert ab jetzt die Prognose, die zuletzt vor dem jeweiligen Refresh berechnet wurde."
            )
            return
        hit = float(summary.get("direction_hit_rate") or 0.0)
        mae = int(round(float(summary.get("mae") or 0.0)))
        med = int(summary.get("median_abs_error") or 0)
        within = float(summary.get("within_100k_rate") or 0.0)
        bias = int(round(float(summary.get("bias") or 0.0)))
        text = [
            f"Letzte 30 Tage · {n} ausgewertete Prognosen",
            "",
            f"Richtung korrekt: {hit:.1f}%",
            f"MAE: {euro(mae)}",
            f"Median-Fehler: {euro(med)}",
            f"≤ 100.000 € Fehler: {within:.1f}%",
            f"Bias: {euro(bias)}",
        ]
        evaluated_rows = [r for r in rows if r.get("evaluated_at")][:6]
        if evaluated_rows:
            text.extend(["", "LETZTE AUSWERTUNGEN"] )
            for row in evaluated_rows:
                name = next((str(p.get("name") or p.get("full_name") or row.get("player_id")) for p in getattr(self, "_market_rows", []) if str(p.get("player_id")) == str(row.get("player_id"))), str(row.get("player_id")))
                hit_mark = "✓" if int(row.get("direction_hit") or 0) else "✕"
                observed = str(row.get("actual_recorded_at") or "")
                observed_hint = ""
                if observed:
                    try:
                        observed_dt = datetime.fromisoformat(observed.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Berlin"))
                        observed_hint = f" · Ist {observed_dt.strftime('%d.%m. %H:%M')}"
                    except ValueError:
                        observed_hint = ""
                text.append(
                    f"{hit_mark} {name}: progn. {delta_text(row.get('predicted_delta'), compact=True)} · "
                    f"real {delta_text(row.get('actual_delta'), compact=True)} · Fehler {euro(row.get('absolute_error'))}{observed_hint}"
                )
        QMessageBox.information(self, "22U Modellgüte", "\n".join(text))

    def _open_preseason_optimizer(self) -> None:
        rows = [dict(r) for r in getattr(self, "_market_rows", [])]
        if not rows:
            QMessageBox.information(self, "Startkader-Optimizer", "Bitte zuerst den Transfermarkt aktualisieren.")
            return
        league_id = str(self.league_combo.currentData() or self.storage.get_setting("league_id") or "")
        squad = enrich_squad_entries(
            self._player_metrics(), points_are_current=self._season_stats_current(league_id),
            market_rows=rows, available_budget=int(getattr(self, "_market_budget", 0) or 0),
        )
        budget = int(getattr(self, "_market_budget", 0) or 0)
        result = optimize_starting_squad(squad, rows, budget)
        PreseasonOptimizerDialog(self, result, budget).exec()

    def _market_overview_loaded(self, league_id: str, data: dict) -> None:
        available = int(data.get("rest_without_sales") or 0)
        committed = int(data.get("committed") or 0)
        cash_balance = int(data.get("balance") if data.get("balance") is not None else (available + committed))
        self._cash_balance = cash_balance
        self._active_bid_committed = committed
        market_entries = [dict(row) for row in (data.get("market_entries") or [])]
        # Persist one daily snapshot for every player we actually see on the market.
        # This lets KickTrack build its own 3/7/14-day momentum without extra API calls.
        for row in market_entries:
            player_id = row.get("player_id")
            market_value = row.get("market_value")
            if player_id and market_value:
                try:
                    self.storage.snapshot_market_value(str(player_id), int(market_value))
                    api_d1 = row.get("d1") if row.get("d1") is not None else row.get("daily_change")
                    analytics = self.storage.analytics(str(player_id))
                    row.update(analytics)
                    if row.get("d1") is None and api_d1 is not None:
                        row["d1"] = int(api_d1)
                        row["daily_change"] = int(api_d1)
                except Exception:
                    pass
        # Score forecasts only against refresh days that are definitely complete.
        try:
            self.storage.evaluate_mv_predictions(
                str(league_id), through_date=self._mv_prediction_evaluation_through()
            )
        except Exception:
            pass

        # Predict the next 22:00 market-value refresh from the daily history.
        # The predictor is intentionally conservative: latest 24h movement is
        # calibrated against comparable historical observations and accompanied
        # by an empirical uncertainty range.
        try:
            history_rows = self.storage.all_market_value_rows()
            current_values: dict[str, int] = {}
            current_deltas: dict[str, int] = {}
            prediction_sources: dict[str, str] = {}

            for row in market_entries:
                pid = str(row.get("player_id") or "")
                mv = row.get("market_value")
                if not pid or mv is None:
                    continue
                current_values[pid] = int(mv or 0)
                prediction_sources[pid] = "MARKET"
                if row.get("d1") is not None:
                    current_deltas[pid] = int(row.get("d1") or 0)

            for row in self.storage.current_players():
                pid = str(row.get("player_id") or "")
                mv = row.get("market_value")
                if not pid or mv is None or pid in current_values:
                    continue
                current_values[pid] = int(mv or 0)
                prediction_sources[pid] = "OWN_SQUAD"
                if row.get("daily_change") is not None:
                    current_deltas[pid] = int(row.get("daily_change") or 0)
                else:
                    analytics = self.storage.analytics(pid)
                    if analytics.get("d1") is not None:
                        current_deltas[pid] = int(analytics.get("d1") or 0)

            for row in self.storage.league_prediction_pool(str(league_id)):
                pid = str(row.get("player_id") or "")
                mv = row.get("market_value")
                if not pid or mv is None or pid in current_values:
                    continue
                current_values[pid] = int(mv or 0)
                prediction_sources[pid] = "MANAGER_SQUAD"
                analytics = self.storage.analytics(pid)
                if analytics.get("d1") is not None:
                    current_deltas[pid] = int(analytics.get("d1") or 0)

            prediction_target = self._mv_prediction_target_date()
            predictions = build_predictions(
                history_rows,
                current_values=current_values,
                current_deltas=current_deltas,
                target_date=prediction_target,
            )
            for row in market_entries:
                pred = predictions.get(str(row.get("player_id")))
                if pred:
                    row["next_refresh_prediction"] = pred
                    row["next_refresh_delta"] = pred.get("delta")
            self.storage.record_mv_predictions(
                str(league_id), predictions,
                current_values=current_values, current_deltas=current_deltas,
                target_date=prediction_target,
                sources=prediction_sources,
            )
            self._refresh_mv_model_quality(str(league_id))
        except Exception:
            predictions = {}

        league_transfers = self.storage.league_all_manager_transfer_rows(
            str(league_id), since=current_season_start().isoformat()
        )
        rows = enrich_market_entries(
            market_entries,
            available,
            self.storage.current_players(),
            points_are_current=self._season_stats_current(str(league_id)),
            league_transfers=league_transfers,
        )
        # Apply the same portfolio/deadline classification here that the Coach
        # uses, so Market, Coach and Budget speak one decision language.
        try:
            squad_rows = enrich_squad_entries(
                self._player_metrics(),
                points_are_current=self._season_stats_current(str(league_id)),
                market_rows=rows,
                available_budget=available,
            )
            rows, _portfolio_squad, portfolio_summary = analyze_portfolio(
                rows, squad_rows, available_budget=cash_balance,
                season_started=self._season_mode_active(),
                committed_budget=committed,
            )
            self._portfolio_summary = portfolio_summary
        except Exception:
            self._portfolio_summary = {}

        # Transparent position-relative price/performance score.
        # We deliberately do not estimate or infer other managers' budgets.
        rows = add_value_scores(rows)

        self._market_rows = rows
        self._market_budget = available
        try:
            self.storage.record_market_decisions(str(league_id), rows)
            self._market_backtest = self.storage.decision_backtest_summary(str(league_id))
        except Exception:
            self._market_backtest = {"evaluated": 0, "hit_rate": None}
        self.market_count_card.value_label.setText(str(len(rows)))
        self.market_under_card.value_label.setText(str(sum(1 for r in rows if (r.get("price_delta") or 0) < 0)))
        self.market_interest_card.value_label.setText(str(sum(1 for r in rows if r.get("action") in {"KADERZIEL", "INVEST", "BEOBACHTEN"})))
        backtest = getattr(self, "_market_backtest", {}) or {}
        hit_rate = backtest.get("hit_rate")
        spread = backtest.get("return_spread_7d")
        evaluated = int(backtest.get("evaluated") or 0)
        if spread is not None and evaluated >= 5:
            self.market_interest_card.hint_label.setText(f"7T BUY-vs-PASS Spread {spread:+.1f} pp · n={evaluated}")
        elif hit_rate is not None and evaluated >= 5:
            self.market_interest_card.hint_label.setText(f"7T-Modellcheck {hit_rate:.0f}% · n={evaluated}")
        elif data.get("points_are_current") is False:
            self.market_interest_card.hint_label.setText("Preseason · Modell lernt mit Historie")
        else:
            self.market_interest_card.hint_label.setText("Entscheidungen werden für Backtests gespeichert")
        self.market_budget_card.value_label.setText(euro(available))
        capacity = squad_capacity(self._player_metrics())
        self.market_budget_card.hint_label.setText(f"nach Geboten · Kader {capacity.current}/{capacity.maximum}")
        self._apply_market_filters()
        self._update_deadline_chip()
        if self._coach_access_allowed() and self.stack.currentIndex() == 6:
            QTimer.singleShot(0, self._refresh_coach)

    def _update_deadline_chip(self) -> None:
        if not hasattr(self, "deadline_chip"):
            return
        summary = dict(getattr(self, "_portfolio_summary", {}) or {})
        deadline = summary.get("deadline")
        projected = summary.get("balance_after_commitments", summary.get("projected_balance_before_new_buys"))
        if deadline is None or projected is None:
            self.deadline_chip.setText("FR 20:00 · –")
            self.deadline_chip.setProperty("state", "neutral")
        else:
            try:
                deadline_text = deadline.strftime("%d.%m. %H:%M")
            except Exception:
                deadline_text = "FR 20:00"
            projected = int(projected or 0)
            self.deadline_chip.setText(f"{deadline_text} · {euro(projected)}")
            self.deadline_chip.setProperty("state", "safe" if projected >= 0 else "danger")
            self.deadline_chip.setToolTip(
                f"Nächste Spieltags-Solvency-Deadline: {deadline_text}\n"
                f"Prognostizierter Saldo vor neuen Käufen: {euro(projected)}"
            )
        self.deadline_chip.style().unpolish(self.deadline_chip)
        self.deadline_chip.style().polish(self.deadline_chip)
        self._update_manager_status_strip()

    def _market_overview_failed(self, message: str) -> None:
        self.market_status.setText("Transfermarkt konnte nicht geladen werden")
        self.statusBar().showMessage("Markt: " + message.splitlines()[0], 7000)

    def _market_overview_finished(self) -> None:
        self._market_worker = None
        self.market_refresh_btn.setEnabled(True)
        self.market_refresh_btn.setText("MARKT AKTUALISIEREN")

    def _apply_market_filters(self, *_args) -> None:
        if not hasattr(self, "market_table"):
            return
        needle = self.market_search.text().strip().casefold()
        position = self.market_position.currentText()
        verdict = self.market_verdict.currentText()
        filtered = []
        watchlist_ids = set()
        if self.market_watchlist_only.isChecked():
            league_id = str(self.league_combo.currentData() or self.storage.get_setting("league_id") or "")
            watchlist_ids = self.storage.watchlist_ids(league_id)
        for row in self._market_rows:
            haystack = f"{row.get('full_name') or row.get('name') or ''} {row.get('club') or ''}".casefold()
            if needle and needle not in haystack:
                continue
            if position != "Alle Positionen" and row.get("position") != position:
                continue
            decision = str(row.get("action") or row.get("portfolio_role") or row.get("signal") or "")
            if verdict not in {"Alle Signale", "Alle Aktionen"} and decision != verdict:
                continue
            if self.market_affordable.isChecked() and not row.get("affordable"):
                continue
            if self.market_under_mv.isChecked() and not ((row.get("price_delta") or 0) < 0):
                continue
            if self.market_own_bid.isChecked() and not row.get("own_bid"):
                continue
            if self.market_kickbase_only.isChecked() and not row.get("is_kickbase"):
                continue
            if self.market_watchlist_only.isChecked() and str(row.get("player_id") or "") not in watchlist_ids:
                continue
            filtered.append(row)
        self._populate_market_table(filtered)
        capacity = squad_capacity(self._player_metrics())
        roster_text = "KADER VOLL" if capacity.is_full else f"{capacity.free} Plätze frei"
        self.market_status.setText(f"{len(filtered)} von {len(self._market_rows)} Spielern · Kader {capacity.current}/{capacity.maximum} · {roster_text}")

    @staticmethod
    def _market_expiry_sort(expires_at) -> float:
        if not expires_at:
            return float("inf")
        try:
            return datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return float("inf")

    @staticmethod
    def _format_market_expiry(expires_at) -> tuple[str, str]:
        if not expires_at:
            return "–", "Für Manager-Angebote liefert Kickbase keine vergleichbare Restlaufzeit."
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            seconds = max(0, int((expiry.astimezone(timezone.utc) - now).total_seconds()))
            local = expiry.astimezone()
            if seconds <= 0:
                display = "ABGELAUFEN"
            else:
                hours, remainder = divmod(seconds, 3600)
                minutes, secs = divmod(remainder, 60)
                if hours >= 24:
                    days, hours = divmod(hours, 24)
                    display = f"{days}T {hours:02d}:{minutes:02d}"
                else:
                    display = f"{hours:02d}:{minutes:02d}:{secs:02d}"
            return display, f"Kickbase-Angebot endet voraussichtlich am {local:%d.%m.%Y um %H:%M:%S}.\nRestzeit wird aus dem API-Feld exs berechnet."
        except (TypeError, ValueError):
            return "–", "Ablaufzeit konnte nicht gelesen werden."

    @staticmethod
    def _market_expiry_seconds(expires_at) -> int | None:
        if not expires_at:
            return None
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            return max(0, int((expiry.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _style_expiry_item(item: QTableWidgetItem, expires_at) -> None:
        seconds = MainWindow._market_expiry_seconds(expires_at)
        if seconds is None:
            item.setForeground(MUTED)
        elif seconds <= 3600:
            item.setForeground(RED)
        elif seconds <= 6 * 3600:
            item.setForeground(QColor("#F3C44E"))
        else:
            item.setForeground(WHITE)

    def _refresh_market_expiry_cells(self) -> None:
        if not hasattr(self, "market_table"):
            return
        for row in range(self.market_table.rowCount()):
            item = self.market_table.item(row, 10)
            source = self.market_table.item(row, 0)
            player = source.data(Qt.UserRole + 1) if source else None
            if not item or not isinstance(player, dict):
                continue
            display, tip = self._format_market_expiry(player.get("expires_at"))
            if item.text() != display:
                item.setText(display)
            item.setToolTip(tip)
            self._style_expiry_item(item, player.get("expires_at"))

    def _populate_market_table(self, rows: list[dict]) -> None:
        table = self.market_table
        # Keep a stable data source for the master/detail pane. The detail pane
        # must never depend on the visual row index because sorting changes it.
        self._market_rows_by_id = {
            str(player.get("player_id")): player
            for player in rows
            if player.get("player_id") is not None
        }
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for r, player in enumerate(rows):
            full_name = str(player.get("full_name") or player.get("name") or "–")
            seller_name = str(player.get("seller_name") or ("Kickbase" if player.get("is_kickbase") else "Manager"))
            values = [
                (full_name, full_name, None),
                (player.get("club") or "–", player.get("club") or "", club_icon(player.get("club"))),
                (player.get("position") or "–", POSITION_SORT.get(player.get("position"), 99), None),
                (seller_name, seller_name.casefold(), None),
                (euro(player.get("market_value")), int(player.get("market_value") or 0), None),
                (delta_text(player.get("d1"), compact=True), int(player.get("d1") or 0), None),
                (delta_text(player.get("next_refresh_delta"), compact=True), int(player.get("next_refresh_delta") or 0), None),
                (euro(player.get("price")), int(player.get("price") or 0), None),
                (euro(player.get("own_bid")) if player.get("own_bid") else "–", int(player.get("own_bid") or 0), None),
                (str(player.get("value_score")) if player.get("value_score") is not None else "–", int(player.get("value_score") or -1), None),
                (self._format_market_expiry(player.get("expires_at"))[0], self._market_expiry_sort(player.get("expires_at")), None),
                (player.get("action") or player.get("portfolio_role") or "BEOBACHTEN", max(int(player.get("squad_fit_score") or 0), int(player.get("investment_score") or 0)), None),
            ]
            for c, (display, sort_value, icon) in enumerate(values):
                item = table_item("" if c == 0 else display, sort_value, icon=icon)
                item.setData(Qt.UserRole, player.get("player_id"))
                item.setData(Qt.UserRole + 1, player)
                if c == 0:
                    status_tip = player_status_tooltip(player)
                    analysis_tip = str(player.get("analysis_text") or "").strip()
                    item.setToolTip(status_tip + ("\n\n" + analysis_tip if analysis_tip else ""))
                if c == 3:
                    item.setToolTip("Kickbase" if player.get("is_kickbase") else f"Angeboten von {seller_name}")
                elif c == 5:
                    set_item_delta_color(item, player.get("d1"))
                    item.setToolTip(change_tooltip("24h Änderung", player.get("market_value"), player.get("d1"), exact=True))
                elif c == 6:
                    pred = player.get("next_refresh_prediction") or {}
                    set_item_delta_color(item, pred.get("delta"))
                    if pred.get("delta") is not None:
                        item.setToolTip(
                            f"Nächster MW-Refresh (22 Uhr)\n"
                            f"Prognose: {delta_text(pred.get('delta'))} → ca. {euro(pred.get('expected_value'))}\n"
                            f"80%-Erfahrungsbereich: {delta_text(pred.get('low_delta'))} bis {delta_text(pred.get('high_delta'))}\n"
                            f"Basis: {pred.get('confidence', 'UNSICHER')} · n={pred.get('sample_count', 0)} ähnliche historische Fälle"
                        )
                    else:
                        item.setToolTip("Noch zu wenig tägliche MW-Historie für eine belastbare 22-Uhr-Prognose.")
                if c == 8:
                    own_bid = int(player.get("own_bid") or 0)
                    market_value = int(player.get("market_value") or 0)
                    if own_bid > 0:
                        item.setForeground(QColor("#F3C44E"))
                        delta = own_bid - market_value if market_value else None
                        premium = (delta / market_value * 100.0) if delta is not None and market_value else None
                        details = [f"Dein aktuell erkanntes Gebot: {euro(own_bid)}"]
                        if delta is not None:
                            details.append(f"Zum aktuellen MW: {delta_text(delta)} ({premium:+.1f} %)" if premium is not None else f"Zum aktuellen MW: {delta_text(delta)}")
                        max_bid = int(player.get("max_bid") or 0)
                        if max_bid:
                            details.append(f"Modell-Max-Bid: {euro(max_bid)}")
                        item.setToolTip("\n".join(details))
                    else:
                        item.setForeground(MUTED)
                        item.setToolTip("Auf diesem Spieler wurde kein eigenes aktives Gebot erkannt.")
                elif c == 9:
                    score = player.get("value_score")
                    if score is not None:
                        item.setToolTip(str(player.get("value_reason") or "Relative Preis-Leistung im Positionsvergleich."))
                        if int(score) >= 80:
                            item.setForeground(QColor("#62E49A"))
                        elif int(score) < 45:
                            item.setForeground(QColor("#FF7A80"))
                elif c == 10:
                    _display, expiry_tip = self._format_market_expiry(player.get("expires_at"))
                    item.setToolTip(expiry_tip)
                    self._style_expiry_item(item, player.get("expires_at"))
                elif c in (7, 11):
                    item.setToolTip(player.get("analysis_text") or "")
                table.setItem(r, c, item)
                if c == 0:
                    portrait_path = self.storage.portrait_path(str(player.get("player_id") or ""))
                    table.setCellWidget(r, c, player_name_cell(player, portrait_path, full_name))
        table.setSortingEnabled(True)
        table.fit_columns_to_viewport()

        # Restore the explicitly clicked player after refresh/sorting. If there has
        # not been a click yet, use the first visible row as the initial selection.
        restored_row = -1
        wanted_id = str(getattr(self, "_market_selected_player_id", "") or "")
        if wanted_id:
            for row_idx in range(table.rowCount()):
                source = table.item(row_idx, 0)
                if source is not None and str(source.data(Qt.UserRole) or "") == wanted_id:
                    restored_row = row_idx
                    break
        if restored_row < 0 and rows:
            restored_row = 0
        if restored_row >= 0:
            table.selectRow(restored_row)
            source = table.item(restored_row, 0)
            if source is not None:
                self._market_selected_player_id = str(source.data(Qt.UserRole) or "") or None
                self._market_selected_player_data = self._market_rows_by_id.get(
                    str(self._market_selected_player_id or "")
                )
        else:
            self._market_selected_player_id = None
            self._market_selected_player_data = None

        self.market_finance_btn.setEnabled(self._selected_market_player() is not None)
        self._update_market_detail()

    def _market_row_clicked(self, row: int, _column: int) -> None:
        """Render the clicked row directly in the detail pane.

        A click is the authoritative selection. No hover state, animation or
        secondary table lookup is allowed to overwrite the right-hand panel.
        """
        if row < 0:
            return
        source = self.market_table.item(row, 0)
        if source is None:
            return
        player = source.data(Qt.UserRole + 1)
        if not isinstance(player, dict):
            return
        player_id = str(player.get("player_id") or source.data(Qt.UserRole) or "")
        self._market_selected_player_id = player_id or None
        self._market_selected_player_data = player
        if self.market_table.currentRow() != row:
            self.market_table.selectRow(row)
        self._render_market_detail(player)

    def _selected_market_player(self) -> dict | None:
        player = getattr(self, "_market_selected_player_data", None)
        wanted_id = str(getattr(self, "_market_selected_player_id", "") or "")
        if isinstance(player, dict):
            player_id = str(player.get("player_id") or "")
            if not wanted_id or player_id == wanted_id:
                return player
        if wanted_id:
            mapped = getattr(self, "_market_rows_by_id", {}).get(wanted_id)
            if isinstance(mapped, dict):
                self._market_selected_player_data = mapped
                return mapped
        return None

    def _market_selection_changed(self) -> None:
        """Support keyboard selection without competing with mouse clicks."""
        row = self.market_table.currentRow()
        if row < 0:
            return
        source = self.market_table.item(row, 0)
        if source is None:
            return
        player = source.data(Qt.UserRole + 1)
        if not isinstance(player, dict):
            return
        player_id = str(player.get("player_id") or source.data(Qt.UserRole) or "")
        self._market_selected_player_id = player_id or None
        self._market_selected_player_data = player
        self._render_market_detail(player)

    def _render_market_detail(self, player: dict | None) -> None:
        selected = player if isinstance(player, dict) else None
        self.market_finance_btn.setEnabled(selected is not None)
        if hasattr(self, "market_detail_open_btn"):
            self.market_detail_open_btn.setEnabled(selected is not None)
            self.market_detail_finance_btn.setEnabled(selected is not None)
            self.market_detail_bid_btn.setEnabled(
                selected is not None and bool(selected.get("player_id"))
            )
            self.market_detail_bid_btn.setText(
                "GEBOT ÄNDERN" if selected is not None and int(selected.get("own_bid") or 0) > 0 else "BIETEN"
            )
        # V4.4 deliberately avoids an opacity effect here. On some Windows/Qt
        # combinations a QGraphicsOpacityEffect on the splitter child could
        # leave the panel visually blank after rapid selection changes.
        if hasattr(self, "market_detail_panel") and self.market_detail_panel.graphicsEffect() is not None:
            self.market_detail_panel.setGraphicsEffect(None)
        self._update_market_detail(selected)

    @staticmethod
    def _score_label(value: int | float | None) -> str:
        score = int(value or 0)
        if score >= 80:
            return "STARK"
        if score >= 65:
            return "GUT"
        if score >= 45:
            return "NEUTRAL"
        return "SCHWACH"

    @staticmethod
    def _format_market_reason_text(lines: list[str]) -> str:
        title = '<div style="font-weight:800; color:#F1F1EE; margin-bottom:4px;">EINSCHÄTZUNG</div>'
        if not lines:
            body = '<div>Keine zusätzlichen Warnsignale.</div>'
        else:
            items = ''.join(
                f'<div style="margin-top:4px;">• {html.escape(str(line))}</div>' for line in lines if str(line).strip()
            )
            body = items or '<div>Keine zusätzlichen Warnsignale.</div>'
        return f'<div style="line-height:1.45;">{title}{body}</div>'

    @staticmethod
    def _format_market_history_empty() -> str:
        return (
            '<div style="line-height:1.4;">'
            '<div style="font-weight:800; color:#DDE6EC; margin-bottom:4px;">HISTORIE</div>'
            '<div>Noch zu wenig vergleichbare Outcomes.</div>'
            '</div>'
        )

    @staticmethod
    def _format_market_history_text(hist: dict) -> str:
        title = '<div style="font-weight:800; color:#DDE6EC; margin-bottom:4px;">HISTORIE</div>'
        if hist.get("median_return_7d_pct") is None:
            return (
                '<div style="line-height:1.4;">'
                f'{title}<div>Noch zu wenig vergleichbare Outcomes.</div>'
                '</div>'
            )
        median = float(hist.get("median_return_7d_pct") or 0.0)
        profitable = float(hist.get("profitable_rate_7d") or 0.0) * 100.0
        n = int(hist.get("sample_count") or 0)
        lines = [
            f'Ähnliche Momentum-Profile: <b>{median:+.1f}%</b> in 7 Tagen',
            f'Trefferquote profitabel: <b>{profitable:.0f}%</b>',
            f'Vergleichbare Fälle: <b>n={n}</b>',
        ]
        body = ''.join(f'<div style="margin-top:4px;">{line}</div>' for line in lines)
        return f'<div style="line-height:1.4;">{title}{body}</div>'

    def _update_market_detail(self, player: dict | None = None) -> None:
        if not hasattr(self, "market_detail_panel"):
            return
        if player is None:
            player = self._selected_market_player()
        if not player:
            self.market_detail_signal.setText("SPIELER AUSWÄHLEN")
            self.market_detail_name.setText("Transfermarkt")
            self.market_detail_meta.setText("Wähle links einen Spieler für die Entscheidungsansicht.")
            self.market_detail_portrait.set_player("?")
            self.market_detail_clubline.setText("")
            self.market_score_fit.set_score(None)
            self.market_score_trade.set_score(None)
            self.market_score_value.set_score(None)
            self.market_detail_mv.setText("–")
            self.market_detail_price.setText("–")
            self.market_detail_own_bid.setText("–")
            self.market_detail_own_bid.setToolTip("")
            self.market_detail_max.setText("–")
            self.market_detail_liga.setText("–")
            self.market_detail_scores.setText("STARTKADER –   ·   TRADE –")
            self.market_detail_trend.setText("24H –   ·   22U –   ·   3T –   ·   7T –")
            self.market_detail_reason.setText(self._format_market_reason_text([]))
            self.market_detail_history.setText(self._format_market_history_empty())
            return

        signal = str(player.get("portfolio_role") or player.get("signal") or "BEOBACHTEN")
        self.market_detail_signal.setText(signal)
        display_name = str(player.get("full_name") or player.get("name") or "Spieler")
        self.market_detail_name.setText(display_name)
        status_meta = player_status_display(player) if player_status_code(player) is not None else ""
        meta_text = " · ".join(x for x in [status_meta, str(player.get("club") or ""), str(player.get("position") or ""), "Kickbase" if player.get("is_kickbase") else str(player.get("seller_name") or "Manager")] if x)
        self.market_detail_meta.setText(meta_text)
        pid = str(player.get("player_id") or "")
        self.market_detail_portrait.set_player(display_name, self.storage.portrait_path(pid))
        self.market_detail_clubline.setText(" · ".join(x for x in [str(player.get("club") or ""), str(player.get("position") or "")] if x))
        self.market_detail_mv.setText(euro(player.get("market_value")))
        self.market_detail_price.setText(euro(player.get("price")))
        own_bid = int(player.get("own_bid") or 0)
        if own_bid > 0:
            self.market_detail_own_bid.setText(euro(own_bid))
            market_value = int(player.get("market_value") or 0)
            if market_value > 0:
                bid_delta = own_bid - market_value
                bid_premium = bid_delta / market_value * 100.0
                self.market_detail_own_bid.setToolTip(
                    f"{delta_text(bid_delta)} zum aktuellen Marktwert · {bid_premium:+.1f} %"
                )
            else:
                self.market_detail_own_bid.setToolTip("Aktuell erkanntes eigenes Gebot")
        else:
            self.market_detail_own_bid.setText("–")
            self.market_detail_own_bid.setToolTip("Kein eigenes aktives Gebot erkannt")
        self.market_detail_max.setText(euro(player.get("max_bid")) if player.get("max_bid") else "–")

        winning = estimate_winning_price(player.get("market_value"), getattr(self, "_league_learning", {}) or {})
        self.market_detail_liga.setText(euro(winning.get("price")) if winning.get("price") else "–")
        if winning.get("price"):
            self.market_detail_liga.setToolTip(f"{winning.get('source')} · {winning.get('premium_pct'):+.1f}% · n={winning.get('sample_count', 0)}")
        else:
            self.market_detail_liga.setToolTip("Noch zu wenig historische Liga-Daten")

        trading = int(player.get("investment_score") or 0)
        fit = int(player.get("squad_fit_score") or 0)
        value_score = player.get("value_score")
        value_text = str(int(value_score)) if value_score is not None else "–"
        self.market_detail_scores.setText(
            f"STARTKADER {self._score_label(fit)}   ·   TRADE {self._score_label(trading)}   ·   VALUE {value_text}"
        )
        self.market_score_fit.set_score(fit)
        self.market_score_trade.set_score(trading)
        self.market_score_value.set_score(value_score)
        self.market_detail_scores.setToolTip(
            f"Startkader {fit}/100 · Trade {trading}/100 · Value {value_text}/100\n"
            f"{player.get('value_reason') or 'Value ist eine relative Preis-Leistungs-Einordnung innerhalb der Position.'}"
        )
        pred = player.get("next_refresh_prediction") or {}
        pred_text = delta_text(pred.get("delta"), compact=True) if pred.get("delta") is not None else "–"
        self.market_detail_trend.setText(
            f"24H {delta_text(player.get('d1'), compact=True)}   ·   22U {pred_text}   ·   3T {delta_text(player.get('d3'), compact=True)}   ·   7T {delta_text(player.get('d7'), compact=True)}"
        )
        if pred.get("delta") is not None:
            self.market_detail_trend.setToolTip(
                f"22-Uhr-Prognose: {delta_text(pred.get('delta'))} → ca. {euro(pred.get('expected_value'))}\n"
                f"80%-Erfahrungsbereich: {delta_text(pred.get('low_delta'))} bis {delta_text(pred.get('high_delta'))}\n"
                f"Verlässlichkeit: {pred.get('confidence', 'UNSICHER')} · n={pred.get('sample_count', 0)}"
            )
        else:
            self.market_detail_trend.setToolTip("Noch zu wenig tägliche Historie für 22U.")
        reasons = [str(x).strip() for x in (player.get("analysis_reasons") or []) if str(x).strip()]
        max_reasons = [str(x).strip() for x in (player.get("max_bid_reasons") or []) if str(x).strip()]
        block = str(player.get("portfolio_block_reason") or "").strip()
        visible = []
        capacity = squad_capacity(self._player_metrics())
        if capacity.is_full:
            visible.append(f"⚠ Kader {capacity.current}/{capacity.maximum}: Kauf nur mit gleichzeitigem Abgang möglich")
        elif capacity.free == 1:
            visible.append(f"Kader {capacity.current}/{capacity.maximum}: nur noch 1 freier Platz")
        if block:
            visible.append("⚠ " + block)
        for text in reasons + max_reasons:
            if text and text not in visible:
                visible.append(text)
            if len(visible) >= 3:
                break
        self.market_detail_reason.setText("\n".join("• " + x for x in visible) if visible else "Keine zusätzlichen Warnsignale.")

        hist = estimate_investment_outcome(
            market_value=player.get("market_value"), d3=player.get("d3"), d7=player.get("d7"),
            learning=getattr(self, "_league_learning", {}) or {}, min_samples=3,
        )
        if hist.get("median_return_7d_pct") is not None:
            self.market_detail_history.setText(
                f"Historisch ähnliche Momentum-Profile: {hist['median_return_7d_pct']:+.1f}% / 7T · "
                f"Treffer {float(hist.get('profitable_rate_7d') or 0)*100:.0f}% · n={hist.get('sample_count', 0)}"
            )
        else:
            self.market_detail_history.setText("Historie: noch zu wenig vergleichbare Outcomes")

    def _open_squad_scoring_info(self) -> None:
        league_id = self.league_combo.currentData() if hasattr(self, "league_combo") else None
        league_id = str(league_id) if league_id else self.storage.get_setting("league_id")
        points_are_current = bool(league_id and self.storage.get_league_setting(str(league_id), "season_started", "0") == "1")
        SquadScoringInfoDialog(self, points_are_current=points_are_current).exec()

    def _open_market_scoring_info(self) -> None:
        MarketScoringInfoDialog(self).exec()

    def _open_market_bid(self) -> None:
        player = self._selected_market_player()
        if not player or not player.get("player_id"):
            return
        league_id = str(self.league_combo.currentData() or self.storage.get_setting("league_id") or "")
        if not league_id:
            QMessageBox.warning(self, "Gebot", "Keine aktive Liga ausgewählt.")
            return

        squad_value = sum(int(row.get("market_value") or 0) for row in self.storage.current_players())
        balance_after_bids = int(getattr(self, "_market_budget", 0) or 0)
        dialog = MarketBidDialog(
            self, player, squad_value=squad_value, balance_after_bids=balance_after_bids
        )
        if dialog.exec() != QDialog.Accepted:
            return
        amount = int(dialog.amount or 0)
        name = str(player.get("full_name") or player.get("name") or "Spieler")
        capacity = dialog.capacity
        balance_after = capacity.effective_balance - amount
        answer = QMessageBox.question(
            self,
            "Gebot wirklich absenden?",
            f"Du gibst jetzt ein echtes Kickbase-Gebot ab.\n\n"
            f"{name}\n"
            f"Gebot: {euro(amount)}\n"
            f"Kontostand danach: {euro(balance_after)}\n"
            f"Lokale 33%-Grenze: {euro(capacity.minimum_balance)}\n\n"
            "Kickbase prüft das Gebot serverseitig nochmals verbindlich.\n\n"
            "Gebot jetzt absenden?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.market_detail_bid_btn.setEnabled(False)
        self.market_detail_bid_btn.setText("SENDET …")

        worker = FunctionWorker(lambda: self.client.place_market_offer(league_id, str(player["player_id"]), amount))
        self._bid_worker = worker

        def succeeded(_payload) -> None:
            QMessageBox.information(self, "Gebot abgegeben", f"Gebot über {euro(amount)} für {name} wurde an Kickbase gesendet.")
            # Refresh is explicit here because the write changed budget/own-bid state.
            self._load_market_overview()

        def failed(message: str) -> None:
            QMessageBox.warning(self, "Gebot fehlgeschlagen", message)

        def finished() -> None:
            self._bid_worker = None
            self.market_detail_bid_btn.setEnabled(self._selected_market_player() is not None)
            current = self._selected_market_player() or {}
            self.market_detail_bid_btn.setText("GEBOT ÄNDERN" if int(current.get("own_bid") or 0) > 0 else "BIETEN")

        worker.signals.succeeded.connect(succeeded)
        worker.signals.failed.connect(failed)
        worker.signals.finished.connect(finished)
        QThreadPool.globalInstance().start(worker)

    def _open_market_financing(self) -> None:
        player = self._selected_market_player()
        if not player:
            return
        FinancingScenarioDialog(self, player, self._market_budget, self.storage.current_players()).exec()

    def _open_market_player_detail(self, *_args) -> None:
        player = self._selected_market_player()
        if not player or not player.get("player_id"):
            return
        league_id = self.league_combo.currentData() or self.storage.get_setting("league_id")
        self.open_player_detail_tab(str(player["player_id"]), str(league_id) if league_id else None, player)

    # ------------------------------------------------------------------
    # League / competitors
    # ------------------------------------------------------------------

    def _build_league_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        identity = QVBoxLayout()
        identity.setSpacing(3)
        title, subtitle = self._page_header(
            "LIGA",
            "Manager und Kader deiner Konkurrenz · Spieler per Doppelklick prüfen",
        )
        identity.addWidget(title)
        identity.addWidget(subtitle)
        header.addLayout(identity)
        header.addStretch()
        self.league_updated = QLabel("Noch nicht geladen")
        self.league_updated.setObjectName("Tiny")
        self.league_refresh_btn = QPushButton("LIGA AKTUALISIEREN")
        self.league_refresh_btn.setObjectName("Primary")
        self.league_refresh_btn.clicked.connect(lambda: self._refresh_league_overview_async(force=True))
        header.addWidget(self.league_updated)
        header.addWidget(self.league_refresh_btn)
        layout.addLayout(header)

        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        self.league_cards_grid = cards
        self.league_managers_card = MetricCard("MANAGER", "–", "Liga", icon="♙", accent="purple")
        self.league_rank_card = MetricCard("DEIN PLATZ", "–", "Liga-Ranking", icon="#", accent="orange")
        self.league_value_card = MetricCard("Ø KADERWERT", "–", "alle Manager", icon="€", accent="green")
        self.league_leader_card = MetricCard("TABELLENFÜHRER", "–", "nach Punkten", icon="♜", accent="gold")
        self.league_cards = [
            self.league_managers_card, self.league_rank_card,
            self.league_value_card, self.league_leader_card,
        ]
        for index, card in enumerate(self.league_cards):
            cards.addWidget(card, 0, index)
        layout.addLayout(cards)

        self.league_value_summary = LeagueValueSummaryPanel()
        layout.addWidget(self.league_value_summary, 0)

        section = QLabel("LIGATABELLE")
        section.setObjectName("SectionTitle")
        layout.addWidget(section)
        tiny = QLabel("Doppelklick auf einen Manager lädt dessen aktuellen Kader.")
        tiny.setObjectName("Tiny")
        layout.addWidget(tiny)
        self.league_ownership_status = QLabel("Spielerbesitz: noch nicht synchronisiert")
        self.league_ownership_status.setObjectName("Tiny")
        layout.addWidget(self.league_ownership_status)

        self.league_table = self._make_table(
            ["PLATZ", "MANAGER", "PUNKTE", "KADERWERT", "GEWINN", "Ø PUNKTE", "ST-SIEGE"],
            [80, 245, 120, 155, 145, 120, 105],
        )
        self.league_table.set_responsive_widths(
            [80, 245, 120, 155, 145, 120, 105],
            [70, 180, 105, 135, 125, 105, 90],
        )
        self.league_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.league_table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self.league_table.verticalHeader().setDefaultSectionSize(48)
        self.league_table.setMinimumHeight(260)
        self.league_table.itemDoubleClicked.connect(self._open_manager_detail)
        layout.addWidget(self.league_table, 1)
        self.stack.addWidget(page)

    # ------------------------------------------------------------------
    # Transfers
    # ------------------------------------------------------------------

    def _build_transfers_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(12)

        title, subtitle = self._page_header(
            "TRANSFERS",
            "Deine Käufe und Verkäufe in der aktuellen Liga",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.transfer_tabs = QTabWidget()
        self.transfer_tabs.setObjectName("V4SegmentTabs")
        overview_tab = QWidget()
        trades_tab = QWidget()
        learning_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)
        trades_layout = QVBoxLayout(trades_tab)
        learning_tab_layout = QVBoxLayout(learning_tab)
        for tab_layout in (overview_layout, trades_layout, learning_tab_layout):
            tab_layout.setContentsMargins(0, 8, 0, 0)
            tab_layout.setSpacing(12)
        self.transfer_tabs.addTab(overview_tab, "ÜBERSICHT")
        self.transfer_tabs.addTab(trades_tab, "MEINE TRADES")
        self.transfer_tabs.addTab(learning_tab, "LIGA-MODELL")
        layout.addWidget(self.transfer_tabs)

        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        self.transfer_cards_grid = cards
        self.transfer_realized = MetricCard("REALISIERT P/L", "–", "Kickbase Gesamt P/L minus offen")
        self.transfer_buys = MetricCard("KÄUFE", "–", "Volumen –")
        self.transfer_sells = MetricCard("VERKÄUFE", "–", "Volumen –")
        self.transfer_total = MetricCard("VORGÄNGE", "–", "aktuelle Liga")
        self.transfer_cards = [self.transfer_realized, self.transfer_buys, self.transfer_sells, self.transfer_total]
        for index, card in enumerate(self.transfer_cards):
            cards.addWidget(card, 0, index)
        overview_layout.addLayout(cards)

        # Live budget planner. Data comes from Kickbase's own budget + market
        # endpoints and is refreshed asynchronously so the UI stays responsive.
        budget_panel = QFrame()
        budget_panel.setObjectName("Panel")
        budget_layout = QVBoxLayout(budget_panel)
        budget_layout.setContentsMargins(20, 18, 20, 18)
        budget_layout.setSpacing(14)

        budget_header = QHBoxLayout()
        budget_title_box = QVBoxLayout()
        budget_title = QLabel("BUDGETPLANER")
        budget_title.setObjectName("SectionTitle")
        budget_subtitle = QLabel("Kontostand, Transferliste und laufende Gebote auf einen Blick")
        budget_subtitle.setObjectName("Tiny")
        budget_title_box.addWidget(budget_title)
        budget_title_box.addWidget(budget_subtitle)
        budget_header.addLayout(budget_title_box)
        budget_header.addStretch()
        self.budget_refresh_btn = QPushButton("BUDGET AKTUALISIEREN")
        self.budget_refresh_btn.clicked.connect(self._load_budget_overview)
        budget_header.addWidget(self.budget_refresh_btn)
        budget_layout.addLayout(budget_header)

        self.budget_value_labels = {}
        self.budget_metric_cards = {}

        def budget_metric(key: str, caption: str) -> QFrame:
            card = QFrame()
            card.setObjectName("MetricCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 11, 14, 11)
            card_layout.setSpacing(4)
            cap = QLabel(caption)
            cap.setObjectName("CardCaption")
            value = QLabel("–")
            value.setObjectName("CardValue")
            value.setMinimumHeight(24)
            card_layout.addWidget(cap)
            card_layout.addWidget(value)
            self.budget_value_labels[key] = value
            self.budget_metric_cards[key] = card
            return card

        # Primary row answers only: what do I have, what is bound, where do I land?
        summary = QGridLayout()
        summary.setHorizontalSpacing(12)
        summary.setVerticalSpacing(10)
        for index, (key, caption) in enumerate([
            ("balance", "KONTOSTAND"),
            ("committed", "AKTIVE GEBOTE"),
            ("rest_without_sales", "NACH ALLEN ZUSCHLÄGEN"),
        ]):
            summary.addWidget(budget_metric(key, caption), 0, index)
            summary.setColumnStretch(index, 1)
        budget_layout.addLayout(summary)

        # Secondary budget context stays visible, but in a quieter strip below
        # the three decision KPIs. This avoids both hiding useful information and
        # presenting six values as equally important.
        self.budget_details_frame = QFrame()
        self.budget_details_frame.setObjectName("BudgetSecondaryStrip")
        details = QGridLayout(self.budget_details_frame)
        details.setContentsMargins(4, 2, 4, 2)
        details.setHorizontalSpacing(8)
        for index, (key, caption) in enumerate([
            ("transfer_list_value", "AUF TRANSFERLISTE"),
            ("rest_budget", "NACH ZUSCHLÄGEN + VERKÄUFEN"),
        ]):
            metric = budget_metric(key, caption)
            metric.setObjectName("CompactBudgetMetric")
            metric.setMaximumHeight(72)
            details.addWidget(metric, 0, index)
            details.setColumnStretch(index, 1)
        budget_layout.addWidget(self.budget_details_frame)

        bids_header = QHBoxLayout()
        bids_title = QLabel("AKTIVE GEBOTE")
        bids_title.setObjectName("SectionTitle")
        bids_header.addWidget(bids_title)
        bids_header.addStretch()
        self.budget_status = QLabel("Automatisch aus Kickbase geladen")
        self.budget_status.setObjectName("BudgetStatusBadge")
        bids_header.addWidget(self.budget_status)
        budget_layout.addLayout(bids_header)

        self.budget_bid_list = BudgetBidList()
        self.budget_bid_list.playerActivated.connect(self._open_budget_bid_player_detail)
        budget_layout.addWidget(self.budget_bid_list)
        overview_layout.addWidget(budget_panel)

        # Own transfer-list players: real current sale value, not a model estimate.
        listings_panel = QFrame()
        listings_panel.setObjectName("Panel")
        listings_layout = QVBoxLayout(listings_panel)
        listings_layout.setContentsMargins(18, 16, 18, 16)
        listings_layout.setSpacing(10)
        listings_head = QHBoxLayout()
        listings_title_box = QVBoxLayout()
        listings_title = QLabel("EIGENE ANGEBOTE")
        listings_title.setObjectName("SectionTitle")
        listings_sub = QLabel("Spieler auf deiner Transferliste · Erlös nach aktueller Kickbase-Mindestpreisregel")
        listings_sub.setObjectName("Tiny")
        listings_title_box.addWidget(listings_title)
        listings_title_box.addWidget(listings_sub)
        listings_head.addLayout(listings_title_box)
        listings_head.addStretch()
        self.own_listings_summary = QLabel("Keine Spieler angeboten")
        self.own_listings_summary.setObjectName("BudgetStatusBadge")
        listings_head.addWidget(self.own_listings_summary)
        listings_layout.addLayout(listings_head)

        self.own_listings_table = self._make_table(
            ["SPIELER", "VEREIN", "POS", "STATUS", "MARKTWERT", "24H", "LISTENPREIS", "AKTUELLER ERLÖS", "Δ ZUM MW", "ROLLE", "AKTION"],
            [190, 135, 56, 150, 120, 80, 120, 135, 105, 110, 115],
        )
        self.own_listings_table.set_responsive_widths(
            [190, 135, 56, 150, 120, 80, 120, 135, 105, 110, 115],
            [155, 115, 50, 125, 105, 70, 105, 115, 90, 95, 100],
        )
        self.own_listings_table.setItemDelegateForColumn(1, ClubItemDelegate(self.own_listings_table))
        self.own_listings_table.verticalHeader().setDefaultSectionSize(48)
        self.own_listings_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.own_listings_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.own_listings_table.itemDoubleClicked.connect(self._open_own_listing_player_detail)
        listings_layout.addWidget(self.own_listings_table)
        self.own_listings_empty = QLabel("Aktuell steht kein Spieler auf deiner Transferliste.")
        self.own_listings_empty.setObjectName("Tiny")
        self.own_listings_empty.setAlignment(Qt.AlignCenter)
        self.own_listings_empty.setVisible(False)
        listings_layout.addWidget(self.own_listings_empty)
        overview_layout.addWidget(listings_panel)

        learning_panel = QFrame()
        learning_panel.setObjectName("Panel")
        learning_layout = QVBoxLayout(learning_panel)
        learning_layout.setContentsMargins(20, 18, 20, 18)
        learning_layout.setSpacing(12)

        learning_header = QHBoxLayout()
        learning_title_box = QVBoxLayout()
        learning_title = QLabel("LIGA-LERNMODELL")
        learning_title.setObjectName("SectionTitle")
        learning_subtitle = QLabel("Rückwirkend aus echten Zuschlägen · Winning Price bleibt Kontext, nicht Max-Bid")
        learning_subtitle.setObjectName("Tiny")
        learning_title_box.addWidget(learning_title)
        learning_title_box.addWidget(learning_subtitle)
        learning_header.addLayout(learning_title_box)
        learning_header.addStretch()
        self.league_learning_status = QLabel("Noch nicht ausgewertet")
        self.league_learning_status.setObjectName("BudgetStatusBadge")
        learning_header.addWidget(self.league_learning_status)
        self.league_learning_refresh_btn = QPushButton("RÜCKWIRKEND LERNEN")
        self.league_learning_refresh_btn.clicked.connect(lambda: self._load_league_learning(force=True))
        learning_header.addWidget(self.league_learning_refresh_btn)
        learning_layout.addLayout(learning_header)

        learning_cards = QGridLayout()
        learning_cards.setHorizontalSpacing(10)
        self.league_learning_cards = {
            "buys": CompactMetric("DEALS", "–", "historische Fremdkäufe", accent="orange"),
            "premium": CompactMetric("TYPISCHES PREMIUM", "–", "Median Liga", accent="gold"),
            "outcome3": CompactMetric("7T RETURN", "–", "nach Kaufpreis", accent="green"),
            "sample": CompactMetric("PREMIUM-LIMIT", "–", "historisch profitabel", accent="purple"),
        }
        for idx, card in enumerate(self.league_learning_cards.values()):
            learning_cards.addWidget(card, 0, idx)
        learning_layout.addLayout(learning_cards)

        self.league_learning_table = self._make_table(
            ["DATUM", "SPIELER", "KÄUFER", "PREIS", "MW @ DEAL", "PREMIUM", "+3T"],
            [135, 220, 180, 140, 140, 110, 110],
        )
        self.league_learning_table.set_responsive_widths(
            [135, 220, 180, 140, 140, 110, 110],
            [120, 170, 145, 125, 125, 95, 95],
        )
        self.league_learning_table.setMinimumHeight(220)
        # Keep a compact sample visible by default. The user can collapse raw
        # deals, but the history is no longer hidden behind an extra click.
        self.league_learning_details_btn = QPushButton("HISTORISCHE DEALS AUSBLENDEN")
        self.league_learning_details_btn.setCheckable(True)
        self.league_learning_details_btn.setChecked(True)
        self.league_learning_details_btn.toggled.connect(self.league_learning_table.setVisible)
        self.league_learning_details_btn.toggled.connect(
            lambda on: self.league_learning_details_btn.setText("HISTORISCHE DEALS AUSBLENDEN" if on else "HISTORISCHE DEALS ANZEIGEN")
        )
        learning_layout.addWidget(self.league_learning_details_btn, 0, Qt.AlignRight)
        learning_layout.addWidget(self.league_learning_table)
        learning_tab_layout.addWidget(learning_panel)
        learning_tab_layout.addStretch()

        self.transfers_chart = ChartPanel(
            "TRANSFER-TIMELINE", "Verteilung der Transferpreise über die Zeit", height=270
        )
        overview_layout.addWidget(self.transfers_chart)
        overview_layout.addStretch()

        evaluation_strip = QGridLayout()
        evaluation_strip.setHorizontalSpacing(10)
        self.transfer_eval_cards = {
            "evaluated": CompactMetric("BEWERTETE TRADES", "–", "Kauf → Verkauf", accent="orange"),
            "roi": CompactMetric("Ø REALISIERTER ROI", "–", "nur gepaarte Trades", accent="green"),
            "good_exits": CompactMetric("GUTE EXITS", "–", "MW fiel nach Verkauf", accent="green"),
            "early_exits": CompactMetric("ZU FRÜH", "–", "MW stieg nach Verkauf", accent="red"),
        }
        for idx, card in enumerate(self.transfer_eval_cards.values()):
            evaluation_strip.addWidget(card, 0, idx)
        trades_layout.addLayout(evaluation_strip)

        section = QLabel("LIVE-BEWERTETE TRADES")
        section.setObjectName("SectionTitle")
        trades_layout.addWidget(section)
        evaluation_hint = QLabel(
            "Kauf und zugehöriger Verkauf werden als ein Trade-Zyklus gezeigt. "
            "Finanzielles Ergebnis, Sport während des Besitzes und MW-Timing +3/+7 Tage nach dem Verkauf werden getrennt bewertet. "
            "In der Preseason bleibt die Sportwertung offen."
        )
        evaluation_hint.setObjectName("Tiny")
        evaluation_hint.setWordWrap(True)
        trades_layout.addWidget(evaluation_hint)

        self.transfer_cards_visual = QFrame()
        self.transfer_cards_visual.setObjectName("Panel")
        self.transfer_cards_visual_layout = QVBoxLayout(self.transfer_cards_visual)
        self.transfer_cards_visual_layout.setContentsMargins(10, 10, 10, 10)
        self.transfer_cards_visual_layout.setSpacing(7)
        transfer_cards_placeholder = QLabel("Trades werden nach der nächsten Datenaktualisierung als Zyklen zusammengefasst.")
        transfer_cards_placeholder.setObjectName("Tiny")
        self.transfer_cards_visual_layout.addWidget(transfer_cards_placeholder)
        trades_layout.addWidget(self.transfer_cards_visual)

        self.transfer_table = self._make_table(
            ["ZEITRAUM", "SPIELER", "VEREIN", "KAUF", "VERKAUF / HEUTE", "ERGEBNIS", "ROI", "SPORT", "+3T", "+7T", "EXIT", "BEWERTUNG"],
            [150, 185, 140, 120, 130, 110, 76, 118, 100, 100, 132, 112],
        )
        self.transfer_table.set_responsive_widths(
            [150, 185, 140, 120, 130, 110, 76, 118, 100, 100, 132, 112],
            [128, 148, 118, 100, 108, 94, 66, 100, 84, 84, 112, 96],
        )
        self.transfer_table.verticalHeader().setDefaultSectionSize(34)
        self.transfer_table.setMinimumHeight(340)
        self.transfer_table.itemDoubleClicked.connect(self._open_transfer_player_detail)
        trades_layout.addWidget(self.transfer_table)
        self._add_scroll_page(page)

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def _build_analysis_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 24)
        layout.setSpacing(12)

        self.analysis_page_title, self.analysis_page_subtitle = self._page_header(
            "SPIELTAG",
            "Aufstellung, nächste Gegner und aktuelle Saisonleistung",
        )
        layout.addWidget(self.analysis_page_title)
        layout.addWidget(self.analysis_page_subtitle)

        cards = QGridLayout()
        cards.setHorizontalSpacing(8)
        cards.setVerticalSpacing(8)
        self.analysis_cards_grid = cards
        self.analysis_invest = MetricCard("INVESTS", "–", "–", compact=True)
        self.analysis_transfer = MetricCard("TRANSFERLISTE", "–", "–", compact=True)
        self.analysis_stamm = MetricCard("STAMMSPIELER", "–", "–", compact=True)
        self.analysis_open = MetricCard("NOCH OFFEN", "–", "ohne Rolle", compact=True)
        self.analysis_cards = [self.analysis_invest, self.analysis_transfer, self.analysis_stamm, self.analysis_open]
        for index, card in enumerate(self.analysis_cards):
            cards.addWidget(card, 0, index)
        layout.addLayout(cards)

        # Kaderentwicklung stays visible as the analytical anchor instead of being
        # hidden behind another navigation layer.
        self.analysis_chart = ChartPanel(
            "KADER P/L", "Aktueller Gewinn / Verlust nach Spieler", height=235
        )
        layout.addWidget(self.analysis_chart)

        # Compact role summaries. Full data remains available on demand, but the
        # main analysis page is not dominated by three nearly identical tables.
        role_header = QHBoxLayout()
        role_title = QLabel("ROLLEN IM KADER")
        role_title.setObjectName("SectionTitle")
        role_header.addWidget(role_title)
        role_header.addStretch()
        role_hint = QLabel("Wichtigste Spieler je Rolle · vollständige Tabelle über Details")
        role_hint.setObjectName("Tiny")
        role_header.addWidget(role_hint)
        layout.addLayout(role_header)

        role_grid = QGridLayout()
        role_grid.setHorizontalSpacing(8)
        role_grid.setVerticalSpacing(8)
        self.analysis_role_tables = {}
        self.analysis_role_summary_labels = {}
        self.analysis_role_preview_labels = {}
        role_specs = [
            ("INVEST", "INVESTMENTS", "Marktwert-Chancen und Rendite"),
            ("TRANSFERLISTE", "TRANSFERLISTE", "Kapital, das du freigeben willst"),
            ("STAMM", "STAMMSPIELER", "Gebundener Kern deines Kaders"),
        ]
        for column, (role, heading, hint) in enumerate(role_specs):
            panel = QFrame()
            panel.setObjectName("AnalysisSummaryCard")
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(14, 12, 14, 12)
            panel_layout.setSpacing(5)

            head = QHBoxLayout()
            label = QLabel(heading)
            label.setObjectName("AnalysisSummaryTitle")
            head.addWidget(label)
            head.addStretch()
            button = QPushButton("DETAILS")
            button.setObjectName("CompactActionButton")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, r=role: self._open_analysis_role_dialog(r))
            head.addWidget(button)
            panel_layout.addLayout(head)

            sub = QLabel(hint)
            sub.setObjectName("Tiny")
            panel_layout.addWidget(sub)

            summary = QLabel("–")
            summary.setObjectName("AnalysisSummaryValue")
            panel_layout.addWidget(summary)
            self.analysis_role_summary_labels[role] = summary

            preview = QLabel("Noch keine Daten")
            preview.setObjectName("AnalysisSummaryPreview")
            preview.setWordWrap(True)
            preview.setMinimumHeight(42)
            panel_layout.addWidget(preview)
            self.analysis_role_preview_labels[role] = preview

            role_grid.addWidget(panel, 0, column)
            role_grid.setColumnStretch(column, 1)
        layout.addLayout(role_grid)

        # League intelligence is a sequence of compact sections instead of nested
        # tabs. Each table keeps its own scrollbar for deeper inspection.
        intel_header = QHBoxLayout()
        intel_title = QLabel("SPIELTAG & LIGA-INTELLIGENCE")
        intel_title.setObjectName("SectionTitle")
        intel_header.addWidget(intel_title)
        intel_header.addStretch()
        self.intelligence_status = QLabel("Noch nicht geladen")
        self.intelligence_status.setObjectName("Tiny")
        self.intelligence_refresh_btn = QPushButton("LIVE-DATEN LADEN")
        self.intelligence_refresh_btn.clicked.connect(self._load_intelligence)
        self.lineup_btn = QPushButton("LINEUP OPTIMIEREN")
        self.lineup_btn.setEnabled(False)
        self.lineup_btn.clicked.connect(self._open_lineup_optimizer)
        intel_header.addWidget(self.intelligence_status)
        intel_header.addWidget(self.intelligence_refresh_btn)
        intel_header.addWidget(self.lineup_btn)
        layout.addLayout(intel_header)

        fixture_panel = QFrame()
        fixture_panel.setObjectName("AnalysisSectionPanel")
        fixture_layout = QVBoxLayout(fixture_panel)
        fixture_layout.setContentsMargins(12, 10, 12, 10)
        fixture_layout.setSpacing(6)
        fixture_title = QLabel("NÄCHSTE SPIELE")
        fixture_title.setObjectName("AnalysisSummaryTitle")
        fixture_layout.addWidget(fixture_title)
        self.fixtures_table = self._make_table(
            ["SPIELER", "VEREIN", "TAG", "MATCHUP", "FIXTURE"],
            [210, 170, 65, 230, 100],
        )
        self.fixtures_table.setItemDelegateForColumn(1, ClubItemDelegate(self.fixtures_table))
        self.fixtures_table.setItemDelegateForColumn(3, ClubItemDelegate(self.fixtures_table))
        self.fixtures_table.set_responsive_widths([210, 170, 65, 230, 100], [165, 140, 60, 190, 90])
        self.fixtures_table.setMinimumHeight(170)
        fixture_layout.addWidget(self.fixtures_table)
        layout.addWidget(fixture_panel)

        manager_panel = QFrame()
        manager_panel.setObjectName("AnalysisSectionPanel")
        manager_layout = QVBoxLayout(manager_panel)
        manager_layout.setContentsMargins(12, 10, 12, 10)
        manager_layout.setSpacing(6)
        manager_title = QLabel("MANAGER-HANDELSPROFILE")
        manager_title.setObjectName("AnalysisSummaryTitle")
        manager_layout.addWidget(manager_title)
        self.manager_profile_table = self._make_table(
            ["MANAGER", "PROFIL", "TRANSFERS", "KÄUFE", "VERKÄUFE", "VOLUMEN", "REAL. P/L", "Ø HALTEDAUER"],
            [190, 145, 85, 75, 85, 120, 115, 115],
        )
        self.manager_profile_table.set_responsive_widths(
            [190, 145, 85, 75, 85, 120, 115, 115],
            [155, 125, 75, 68, 76, 105, 100, 100],
        )
        self.manager_profile_table.setMinimumHeight(170)
        manager_layout.addWidget(self.manager_profile_table)
        layout.addWidget(manager_panel)

        activity_panel = QFrame()
        activity_panel.setObjectName("AnalysisSectionPanel")
        activity_layout = QVBoxLayout(activity_panel)
        activity_layout.setContentsMargins(12, 10, 12, 10)
        activity_layout.setSpacing(6)
        activity_header = QHBoxLayout()
        activity_title = QLabel("LIGA-AKTIVITÄT")
        activity_title.setObjectName("AnalysisSummaryTitle")
        activity_header.addWidget(activity_title)
        activity_header.addStretch()
        self.activity_search = QLineEdit()
        self.activity_search.setPlaceholderText("Aktivität suchen …")
        self.activity_search.setMaximumWidth(250)
        self.activity_filter = QComboBox()
        self.activity_filter.addItems(["Nur Transfers", "Alle Spieler-Aktivitäten", "Sonstiges", "Alles"])
        self.activity_search.textChanged.connect(self._apply_activity_filters)
        self.activity_filter.currentIndexChanged.connect(self._apply_activity_filters)
        activity_header.addWidget(self.activity_search)
        activity_header.addWidget(self.activity_filter)
        activity_layout.addLayout(activity_header)
        self.activity_table = self._make_table(
            ["ZEIT", "SPIELER", "AKTION / MANAGER", "PREIS", "TYP"],
            [170, 220, 230, 135, 90],
        )
        self.activity_table.setMinimumHeight(180)
        self.activity_table.itemDoubleClicked.connect(self._open_activity_player_detail)
        activity_layout.addWidget(self.activity_table)
        layout.addWidget(activity_panel)

        self._add_scroll_page(page)

    def _open_analysis_role_dialog(self, role: str) -> None:
        role = str(role or "").upper()
        titles = {
            "INVEST": "Investments",
            "TRANSFERLISTE": "Transferliste",
            "STAMM": "Stammspieler",
        }
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{titles.get(role, role)} — Analyse")
        dialog.resize(1180, 570)
        dialog.setModal(False)
        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        heading = QLabel(titles.get(role, role).upper())
        heading.setObjectName("SectionTitle")
        outer.addWidget(heading)

        table = self._make_table(
            ["SPIELER", "VEREIN", "POS", "KAUFPREIS", "MARKTWERT", "P/L", "ROI", "24H", "3 TAGE", "7 TAGE"],
            [210, 170, 70, 125, 125, 105, 85, 90, 90, 90],
        )
        table.setItemDelegateForColumn(1, ClubItemDelegate(table))
        table.set_responsive_widths(
            [210, 170, 70, 125, 125, 105, 85, 90, 90, 90],
            [160, 140, 60, 112, 112, 90, 75, 78, 78, 78],
        )
        players = [p for p in self._player_metrics() if (p.get("player_role") or "OFFEN") == role]
        players.sort(key=lambda p: (p.get("pnl") is not None, p.get("pnl") or -10**18), reverse=True)
        table.setRowCount(len(players))
        for row, player in enumerate(players):
            specs = [
                (player.get("name") or "–", player.get("name") or ""),
                (player.get("club") or "–", player.get("club") or ""),
                (player.get("position") or "–", POSITION_SORT.get(player.get("position"), 99)),
                (euro(player.get("entry_value")), player.get("entry_value") if player.get("entry_value") is not None else -10**18),
                (euro(player.get("market_value")), player.get("market_value") or 0),
                (delta_text(player.get("pnl"), compact=True), player.get("pnl") if player.get("pnl") is not None else -10**18),
                (percent(player.get("roi")), player.get("roi") if player.get("roi") is not None else -10**18),
                (delta_text(player.get("d1"), compact=True), player.get("d1") if player.get("d1") is not None else -10**18),
                (delta_text(player.get("d3"), compact=True), player.get("d3") if player.get("d3") is not None else -10**18),
                (delta_text(player.get("d7"), compact=True), player.get("d7") if player.get("d7") is not None else -10**18),
            ]
            for col, (label, sort_value) in enumerate(specs):
                item = table_item(label, sort_value, icon=club_icon(player.get("club")) if col == 1 else None)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col in (0, 1) else Qt.AlignCenter)
                if col in (5, 6):
                    set_item_delta_color(item, player.get("pnl"))
                elif col in (7, 8, 9):
                    set_item_delta_color(item, {7: player.get("d1"), 8: player.get("d3"), 9: player.get("d7")}[col])
                table.setItem(row, col, item)
        outer.addWidget(table, 1)
        dialog.show()
        if not hasattr(self, "_analysis_role_dialogs"):
            self._analysis_role_dialogs = []
        self._analysis_role_dialogs = [d for d in self._analysis_role_dialogs if d.isVisible()]
        self._analysis_role_dialogs.append(dialog)

    def _load_intelligence(self, *_args, force: bool = False) -> None:
        league_id = self.league_combo.currentData() or self.storage.get_setting("league_id")
        if not league_id or self._intelligence_worker is not None:
            return
        league_id = str(league_id)
        self.intelligence_refresh_btn.setEnabled(False)
        self.intelligence_status.setText("Live-Daten werden geladen …")
        managers = self.storage.league_managers(league_id)
        cached_ids = set() if force else {
            str(m.get("manager_id"))
            for m in managers
            if self.storage.league_manager_transfers_are_fresh(league_id, str(m.get("manager_id")), 3600)
        }
        players = self.storage.current_players()
        cached_performance: dict[str, dict] = {}
        missing_performance: list[str] = []
        for player in players:
            player_id = str(player.get("player_id") or "")
            if not player_id:
                continue
            cached = None if force else self.storage.cache_get(f"player_performance:{league_id}:{player_id}", 3600)
            if isinstance(cached, dict):
                cached_performance[player_id] = cached
            else:
                missing_performance.append(player_id)

        def load():
            data = {
                "fixtures": self.client.competition_fixtures(1),
                "table": self.client.competition_table(1),
                "activity": self.client.activity_feed(league_id, 0, 50),
                "lineup": self.client.my_lineup(league_id),
                "manager_transfers": {},
                "performance": dict(cached_performance),
                "performance_fetched": {},
            }
            # Player form is cached on disk for one hour. Only stale/missing
            # players trigger network calls, keeping the intelligence refresh light.
            for player_id in missing_performance:
                try:
                    payload = self.client.player_performance(league_id, player_id)
                    data["performance"][player_id] = payload
                    data["performance_fetched"][player_id] = payload
                except Exception:
                    continue
            # Build missing trade profiles once. Existing SQLite history is reused.
            for manager in managers:
                mid = str(manager.get("manager_id") or "")
                if not mid or mid in cached_ids:
                    continue
                try:
                    raw = self.client.manager_transfers(league_id, mid)
                    data["manager_transfers"][mid] = self.client.parse_manager_transfers(raw)
                except Exception:
                    continue
            return data

        worker = FunctionWorker(load)
        self._intelligence_worker = worker
        worker.signals.succeeded.connect(lambda data, lid=league_id: self._intelligence_loaded(lid, data))
        worker.signals.failed.connect(self._intelligence_failed)
        worker.signals.finished.connect(self._intelligence_finished)
        QThreadPool.globalInstance().start(worker)

    def _intelligence_loaded(self, league_id: str, data: dict) -> None:
        for player_id, payload in (data.get("performance_fetched") or {}).items():
            self.storage.cache_set(f"player_performance:{league_id}:{player_id}", payload)
        cutoff = current_season_start().isoformat()
        for manager_id, transfers in (data.get("manager_transfers") or {}).items():
            current = []
            for transfer in transfers or []:
                raw = str(transfer.get("transferred_at") or "")
                if raw[:10] >= cutoff:
                    current.append(transfer)
            self.storage.upsert_league_manager_transfers(league_id, str(manager_id), current)
        self._intelligence_data = data
        self.lineup_btn.setEnabled(True)
        self.intelligence_status.setText("Live · Fixtures + Ligaaktivität")

        # Fixtures: one row per current squad player, using the next known match.
        points_current = self.storage.get_league_setting(league_id, "season_started", "0") == "1"
        players = self.storage.current_players()
        fixture_rows = []
        for player in players:
            run = fixture_run(str(player.get("team_id") or ""), data.get("fixtures") or {}, data.get("table") or {}, 3)
            if not run:
                continue
            nxt = run[0]
            fixture_rows.append((player, nxt))
        self.fixtures_table.setSortingEnabled(False)
        self.fixtures_table.setRowCount(len(fixture_rows))
        for r, (player, nxt) in enumerate(fixture_rows):
            ease = int(nxt.get("adjusted_ease", nxt.get("ease", 50)) or 50) if points_current else 50
            difficulty = ("LEICHT" if ease >= 67 else "SCHWER" if ease <= 33 else "MITTEL") if points_current else "PRESEASON"
            opponent_club = team_name(nxt.get("opponent_id")) if nxt.get("opponent_id") else str(nxt.get("opponent") or "")
            opponent_name = opponent_club or str(nxt.get("opponent") or "–")
            matchup = f"vs {opponent_name}" if nxt.get("home_game") else f"@ {opponent_name}"
            specs = [
                (player.get("name") or "–", player.get("name") or "", None),
                (player.get("club") or "–", player.get("club") or "", club_icon(player.get("club"))),
                (str(nxt.get("day") or "–"), int(nxt.get("day") or 0), None),
                (matchup, opponent_name, club_icon(opponent_club)),
                (difficulty, ease, None),
            ]
            for c, (display, sort_value, icon) in enumerate(specs):
                item = table_item(display, sort_value, icon=icon)
                item.setData(Qt.UserRole, player.get("player_id"))
                if c == 3:
                    item.setToolTip(
                        f"{player.get('club') or 'Team'} {'zu Hause gegen' if nxt.get('home_game') else 'auswärts bei'} {opponent_name}."
                    )
                elif c == 4:
                    if points_current:
                        item.setToolTip(
                            f"Fixture-Wert {ease}/100\nGegner: {opponent_name} · Tabellenplatz {nxt.get('opponent_place')} · {'Heim' if nxt.get('home_game') else 'Auswärts'}\n"
                            "100 = leichter, 0 = schwerer. Grundlage: aktuelle Competition-Tabelle plus kleiner Heim/Auswärts-Faktor."
                        )
                    else:
                        item.setToolTip("Preseason: Gegner wird angezeigt, aber die alte Abschlusstabelle wird bewusst nicht als Fixture-Schwierigkeit bewertet.")
                self.fixtures_table.setItem(r, c, item)
        self.fixtures_table.setSortingEnabled(True)
        self._fit_table_height(self.fixtures_table, len(fixture_rows), min_rows=3, max_rows=5)

        # Manager trade profiles are deterministic summaries of captured current-season transfers.
        managers = self.storage.league_managers(league_id)
        self.manager_profile_table.setSortingEnabled(False)
        self.manager_profile_table.setRowCount(len(managers))
        for r, manager in enumerate(managers):
            mid = str(manager.get("manager_id") or "")
            rows = self.storage.league_manager_transfer_rows(league_id, mid, since=current_season_start().isoformat())
            profile = trade_profile(rows)
            hold_days = profile.get("avg_hold_days")
            specs = [
                (manager.get("name") or "–", manager.get("name") or ""),
                (profile["label"], profile["label"]),
                (str(profile["count"]), profile["count"]),
                (str(profile["buy_count"]), profile["buy_count"]),
                (str(profile["sell_count"]), profile["sell_count"]),
                (euro(profile["volume"]), profile["volume"]),
                (delta_text(profile.get("realized_pnl")), profile.get("realized_pnl") or 0),
                (f"{hold_days:.1f} T" if hold_days is not None else "–", hold_days if hold_days is not None else 9999),
            ]
            for c, (display, sort_value) in enumerate(specs):
                item = table_item(display, sort_value)
                item.setData(Qt.UserRole, mid)
                if c == 1:
                    item.setToolTip(
                        f"{profile['label']}\n{profile['count']} erfasste Transfers · "
                        f"{profile['buy_count']} Käufe · {profile['sell_count']} Verkäufe\n"
                        "Profil basiert nur auf tatsächlich in KickTrack erfassten Liga-Transfers."
                    )
                self.manager_profile_table.setItem(r, c, item)
        self.manager_profile_table.setSortingEnabled(True)
        self._fit_table_height(self.manager_profile_table, len(managers), min_rows=3, max_rows=5)

        self._activity_rows = parse_activity_feed(data.get("activity") or {})
        self._apply_activity_filters()

    def _apply_activity_filters(self, *_args) -> None:
        if not hasattr(self, "activity_table"):
            return
        rows = list(getattr(self, "_activity_rows", []) or [])
        needle = self.activity_search.text().strip().casefold() if hasattr(self, "activity_search") else ""
        mode = self.activity_filter.currentText() if hasattr(self, "activity_filter") else "Nur Transfers"
        filtered = []
        for activity in rows:
            is_transfer = bool(activity.get("player_id") and int(activity.get("price") or 0) > 0)
            is_player = bool(activity.get("player_id"))
            if mode == "Nur Transfers" and not is_transfer:
                continue
            if mode == "Alle Spieler-Aktivitäten" and not is_player:
                continue
            if mode == "Sonstiges" and is_player:
                continue
            haystack = f"{activity.get('player_name') or ''} {activity.get('buyer') or ''} {activity.get('type') or ''}".casefold()
            if needle and needle not in haystack:
                continue
            filtered.append(activity)

        self.activity_table.setSortingEnabled(False)
        self.activity_table.setRowCount(len(filtered))
        for r, activity in enumerate(filtered):
            action = activity.get("buyer") or "Ligaaktivität"
            category = "TRANSFER" if activity.get("player_id") and int(activity.get("price") or 0) > 0 else ("SPIELER" if activity.get("player_id") else "SONSTIGES")
            specs = [
                (display_date(activity.get("date")), activity.get("date") or ""),
                (activity.get("player_name") or "–", activity.get("player_name") or ""),
                (action, action),
                (euro(activity.get("price")) if activity.get("price") else "–", int(activity.get("price") or 0)),
                (category, category),
            ]
            for c, (display, sort_value) in enumerate(specs):
                item = table_item(display, sort_value)
                item.setData(Qt.UserRole, activity.get("player_id"))
                item.setData(Qt.UserRole + 1, activity)
                self.activity_table.setItem(r, c, item)
        self.activity_table.setSortingEnabled(True)
        self._fit_table_height(self.activity_table, len(filtered), min_rows=3, max_rows=5)

    def _intelligence_failed(self, message: str) -> None:
        self.intelligence_status.setText("Live-Daten konnten nicht geladen werden")
        self.statusBar().showMessage("Intelligence: " + message.splitlines()[0], 7000)

    def _intelligence_finished(self) -> None:
        self._intelligence_worker = None
        self.intelligence_refresh_btn.setEnabled(True)

    def _open_lineup_optimizer(self) -> None:
        if not self._intelligence_data:
            self._load_intelligence()
            return
        league_id = self.league_combo.currentData() or self.storage.get_setting("league_id")
        points_current = bool(
            league_id and self.storage.get_league_setting(str(league_id), "season_started", "0") == "1"
        )
        LineupOptimizerDialog(
            self,
            self.storage.current_players(),
            self._intelligence_data.get("fixtures") or {},
            self._intelligence_data.get("table") or {},
            self._intelligence_data.get("lineup") or {},
            points_are_current=points_current,
            performance_payloads=self._intelligence_data.get("performance") or {},
        ).exec()

    def _open_activity_player_detail(self, item: QTableWidgetItem) -> None:
        player_id = item.data(Qt.UserRole)
        if not player_id:
            row_item = self.activity_table.item(item.row(), 0)
            player_id = row_item.data(Qt.UserRole) if row_item else None
        if not player_id:
            return
        league_id = self.league_combo.currentData() or self.storage.get_setting("league_id")
        activity = item.data(Qt.UserRole + 1) or {}
        player_data = {
            "player_id": str(player_id),
            "name": activity.get("player_name") or "Spieler",
            "team_id": activity.get("team_id"),
        }
        self.open_player_detail_tab(str(player_id), str(league_id) if league_id else None, player_data)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _build_coach_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(12)

        self.coach_page_title, self.coach_page_subtitle = self._page_header(
            "PRESEASON COACH",
            "Nur die nächsten Schritte für Trading, Startkader und Liquidität",
        )
        layout.addWidget(self.coach_page_title)
        layout.addWidget(self.coach_page_subtitle)

        hero = QFrame()
        hero.setObjectName("CoachHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(8)

        self.coach_hero_title = QLabel("Noch keine Analyse berechnet")
        self.coach_hero_title.setObjectName("CoachHeroTitle")
        self.coach_hero_meta = QLabel("Öffne den Markt oder aktualisiere die Daten, um konkrete Prioritäten zu sehen.")
        self.coach_hero_meta.setObjectName("CoachHeroMeta")
        self.coach_hero_meta.setWordWrap(True)
        hero_layout.addWidget(self.coach_hero_title)
        hero_layout.addWidget(self.coach_hero_meta)

        insights = QHBoxLayout()
        insights.setSpacing(8)

        def add_insight(default_text: str, attr: str) -> None:
            chip = QLabel(default_text)
            chip.setObjectName("CoachInsightChip")
            setattr(self, attr, chip)
            insights.addWidget(chip)

        add_insight("DEADLINE · –", "coach_deadline_chip")
        add_insight("NACH GEBOTEN · –", "coach_budget_chip")
        add_insight("KADER · –/18", "coach_slots_chip")
        add_insight("AKTIONEN · –", "coach_actions_chip")
        add_insight("MIX · –", "coach_mix_chip")
        insights.addStretch()
        hero_layout.addLayout(insights)
        layout.addWidget(hero)

        top = QHBoxLayout()
        self.coach_status = QLabel("Öffne den Markt oder aktualisiere die Daten, um Vorschläge zu berechnen.")
        self.coach_status.setObjectName("Subtle")
        refresh = QPushButton("VORSCHLÄGE NEU BERECHNEN")
        refresh.clicked.connect(self._refresh_coach)
        top.addWidget(self.coach_status, 1)
        top.addWidget(refresh)
        layout.addLayout(top)

        summary = QFrame()
        summary.setObjectName("CoachSummary")
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(10)

        def add_stat(caption: str, attr: str) -> None:
            box = QFrame()
            box.setObjectName("CoachStat")
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(12, 8, 12, 8)
            box_layout.setSpacing(2)
            cap = QLabel(caption)
            cap.setObjectName("CoachStatCaption")
            value = QLabel("–")
            value.setObjectName("CoachStatValue")
            setattr(self, attr, value)
            box_layout.addWidget(cap)
            box_layout.addWidget(value)
            summary_layout.addWidget(box, 1)

        add_stat("FOKUS JETZT", "coach_focus_value")
        add_stat("NACH GEBOTEN", "coach_liquidity_value")
        add_stat("MARKTCHANCEN", "coach_market_value")
        add_stat("KADERAKTIONEN", "coach_squad_value")
        layout.addWidget(summary)

        self.coach_container = QWidget()
        self.coach_layout = QVBoxLayout(self.coach_container)
        self.coach_layout.setContentsMargins(0, 0, 0, 0)
        self.coach_layout.setSpacing(8)
        layout.addWidget(self.coach_container)
        layout.addStretch()
        self._add_scroll_page(page)

    def _clear_coach_cards(self) -> None:
        if not hasattr(self, "coach_layout"):
            return
        while self.coach_layout.count():
            item = self.coach_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _coach_card(self, rec: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("CoachCard")
        label_upper = str(rec.get("label") or "").upper()
        kind = str(rec.get("kind") or "")
        tone = "neutral"
        if kind == "warning" or "ANPASSEN" in label_upper or "PRÜFEN" in label_upper:
            tone = "warning"
        elif kind == "sell" or "VERKAUF" in label_upper:
            tone = "sell"
        elif kind in {"kickbase_buy", "manager_buy"} or label_upper in {"INVEST", "KAUFEN", "KADERZIEL", "TOP-CHANCE"}:
            tone = "buy"
        elif kind == "bid":
            tone = "bid"
        card.setProperty("tone", tone)
        root = QHBoxLayout(card)
        root.setContentsMargins(14, 11, 14, 11)
        root.setSpacing(12)

        rank_value = rec.get("_queue_rank")
        if rank_value:
            rank = QLabel(str(rank_value))
            rank.setObjectName("CoachRank")
            rank.setFixedSize(26, 26)
            rank.setAlignment(Qt.AlignCenter)
            root.addWidget(rank, 0, Qt.AlignTop)

        pid_for_portrait = str(rec.get("player_id") or "")
        portrait = PlayerAvatar(46)
        portrait.setObjectName("CoachPortrait")
        portrait.set_player(str(rec.get("name") or "?"), self.storage.portrait_path(pid_for_portrait) if pid_for_portrait else None)
        root.addWidget(portrait, 0, Qt.AlignTop)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        verdict = QLabel(str(rec.get("label") or "HINWEIS"))
        verdict.setObjectName("CoachVerdict")
        name = QLabel(str(rec.get("name") or "–"))
        name.setObjectName("CoachPlayer")
        status_source = dict(rec.get("raw") or {})
        for key in ("status", "kickbase_status", "st", "status_list", "stl", "status_text", "stxt"):
            if rec.get(key) is not None:
                status_source[key] = rec.get(key)
        status_meta = player_status_display(status_source) if player_status_code(status_source) is not None else ""
        meta = QLabel(" · ".join(part for part in [status_meta, str(rec.get("club") or ""), str(rec.get("position") or ""), str(rec.get("source") or "")] if part))
        meta.setObjectName("CoachMeta")
        if status_meta:
            meta.setToolTip(player_status_tooltip(status_source))
        head.addWidget(verdict)
        head.addWidget(name)
        head.addStretch()
        priority = int(rec.get("priority") or 0)
        if priority:
            prio = QLabel(f"PRIO {priority}")
            prio.setObjectName("CoachPriority")
            prio.setProperty("level", "high" if priority >= 90 else "medium" if priority >= 75 else "low")
            head.addWidget(prio)
        body.addLayout(head)
        body.addWidget(meta)

        purpose_row = QHBoxLayout()
        purpose_row.setSpacing(6)
        primary_reason = str(rec.get("primary_reason") or "").strip()
        secondary_reason = str(rec.get("secondary_reason") or "").strip()
        if primary_reason:
            purpose = QLabel(primary_reason)
            purpose.setObjectName("CoachPurpose")
            purpose_row.addWidget(purpose)
        if secondary_reason:
            secondary = QLabel(secondary_reason)
            secondary.setObjectName("CoachPurposeSecondary")
            purpose_row.addWidget(secondary)
        planability = str(rec.get("planability") or "").strip()
        if planability:
            plan = QLabel(f"PLANBAR {planability}")
            plan.setObjectName("CoachPlanability")
            purpose_row.addWidget(plan)
        confidence = str(rec.get("confidence") or "").strip()
        if confidence:
            conf = QLabel(f"CONF {confidence}")
            conf.setObjectName("CoachSecondaryChip")
            purpose_row.addWidget(conf)
        horizon = str(rec.get("horizon") or "").strip()
        if horizon:
            hz = QLabel(horizon)
            hz.setObjectName("CoachSecondaryChip")
            purpose_row.addWidget(hz)
        purpose_row.addStretch()
        body.addLayout(purpose_row)

        action = QLabel(str(rec.get("action") or ""))
        action.setObjectName("CoachAction")
        action.setWordWrap(True)
        body.addWidget(action)

        def money_chip(label: str, value) -> str | None:
            if value is None:
                return None
            try:
                value = int(value)
            except (TypeError, ValueError):
                return None
            if value <= 0:
                return None
            compact = compact_number(value).lstrip("+")
            return f"{label} {compact} €"

        facts = []
        facts.append(money_chip("MW", rec.get("market_value")))
        price_value = rec.get("price")
        mv_value = rec.get("market_value")
        if price_value and int(price_value or 0) != int(mv_value or 0):
            facts.append(money_chip("Preis", price_value))
        facts.append(money_chip("Max-Bid", rec.get("max_bid")))
        facts.append(money_chip("Gebot", rec.get("own_bid")))
        raw = dict(rec.get("raw") or {})
        if raw.get("value_score") is not None:
            facts.append(f"Value {int(raw.get('value_score') or 0)}/100")
        expires = str(raw.get("expires") or raw.get("expiry") or rec.get("expires") or "").strip()
        if expires and expires != "–":
            facts.append(f"Ablauf {expires}")
        facts = [value for value in facts if value]
        if facts:
            chip_row = QHBoxLayout()
            chip_row.setSpacing(6)
            for value in facts[:6]:
                chip = QLabel(value)
                chip.setObjectName("CoachKpiChip")
                chip_row.addWidget(chip)
            chip_row.addStretch()
            body.addLayout(chip_row)

        reasons = [str(x).strip() for x in (rec.get("reasons") or []) if str(x).strip()]
        secondary_tags = [str(x).strip() for x in (rec.get("secondary_tags") or []) if str(x).strip()]
        visible_reasons = []
        for value in [*secondary_tags, *reasons]:
            if value and value not in visible_reasons:
                visible_reasons.append(value)
            if len(visible_reasons) >= 4:
                break
        if visible_reasons:
            chips = QHBoxLayout()
            chips.setSpacing(6)
            for index, value in enumerate(visible_reasons):
                chip = QLabel(value)
                chip.setObjectName("CoachReasonChip")
                chip.setProperty("primary", index == 0)
                chips.addWidget(chip)
            chips.addStretch()
            body.addLayout(chips)
        detail_parts = []
        if primary_reason:
            detail_parts.append("Primär: " + primary_reason)
        if secondary_reason:
            detail_parts.append("Sekundär: " + secondary_reason)
        if secondary_tags:
            detail_parts.append("Signale: " + " · ".join(secondary_tags))
        if reasons:
            detail_parts.append("Gründe: " + " · ".join(reasons))
        if detail_parts:
            card.setToolTip("\n".join(detail_parts))
        root.addLayout(body, 1)

        pid = rec.get("player_id")
        if pid:
            btn = QPushButton("SPIELER ÖFFNEN")
            btn.clicked.connect(lambda checked=False, player_id=str(pid), data=dict(rec.get("raw") or {}): self.open_player_detail_tab(player_id, str(self.league_combo.currentData() or self.storage.get_setting("league_id") or ""), data))
            root.addWidget(btn, 0, Qt.AlignVCenter)
        return card

    def _refresh_coach(self, *_args) -> None:
        if not hasattr(self, "coach_layout"):
            return
        league_id = self.league_combo.currentData() if hasattr(self, "league_combo") else None
        league_id = str(league_id) if league_id else self.storage.get_setting("league_id")
        if not league_id:
            return
        if not getattr(self, "_market_rows", None):
            self.coach_status.setText("Transfermarkt noch nicht geladen – Markt wird jetzt aktualisiert …")
            self._load_market_overview()
            return

        points_are_current = self._season_stats_current(league_id)
        free_budget = int(getattr(self, "_market_budget", 0) or 0)
        cash_balance = int(getattr(self, "_cash_balance", 0) or free_budget)
        committed = int(getattr(self, "_active_bid_committed", 0) or 0)
        squad = enrich_squad_entries(
            self._player_metrics(),
            points_are_current=points_are_current,
            market_rows=self._market_rows,
            available_budget=free_budget,
        )
        capacity = squad_capacity(squad)
        portfolio_market, portfolio_squad, portfolio_summary = analyze_portfolio(
            self._market_rows,
            squad,
            available_budget=cash_balance,
            season_started=self._season_mode_active(),
            committed_budget=committed,
        )
        manager_id = self.storage.get_league_setting(str(league_id), "manager_id") or self.storage.get_setting("manager_id")
        recs = build_coach_recommendations(
            portfolio_market,
            portfolio_squad,
            managers=self.storage.league_managers(str(league_id)),
            own_manager_id=str(manager_id) if manager_id else None,
            available_budget=free_budget,
            portfolio_summary=portfolio_summary,
            limit=16,
        )
        self._clear_coach_cards()
        if not recs:
            empty = QLabel("Aktuell ergibt sich aus Markt, Budget und Kader kein klarer Handlungsbedarf. Budget halten und Markt beobachten.")
            empty.setObjectName("Subtle")
            empty.setWordWrap(True)
            self.coach_layout.addWidget(empty)
            self.coach_status.setText("Keine klare Aktion notwendig")
            self.coach_hero_title.setText("Coach aktuell entspannt")
            self.coach_hero_meta.setText("Markt, Budget und Kader liefern momentan keinen priorisierten Handlungsdruck.")
            return

        queue = sorted(recs, key=lambda row: int(row.get("priority") or 0), reverse=True)[:14]
        groups = [
            ("JETZT ENTSCHEIDEN", lambda r: r.get("kind") == "warning" or (r.get("kind") == "sell" and int(r.get("priority") or 0) >= 88)),
            ("AKTIVE GEBOTE", lambda r: r.get("kind") == "bid"),
            ("MARKTCHANCEN", lambda r: r.get("kind") in {"kickbase_buy", "manager_buy"}),
            ("KADER / LIQUIDITÄT", lambda r: r.get("kind") in {"sell", "squad_hold"}),
        ]
        rendered: set[int] = set()
        rank = 1
        for heading, predicate in groups:
            group_rows = [(idx, rec) for idx, rec in enumerate(queue) if idx not in rendered and predicate(rec)]
            if not group_rows:
                continue
            group_title = QLabel(f"{heading} · {len(group_rows)}")
            group_title.setObjectName("CoachGroupTitle")
            self.coach_layout.addWidget(group_title)
            for idx, rec in group_rows:
                rendered.add(idx)
                rec = dict(rec)
                rec["_queue_rank"] = rank
                rank += 1
                self.coach_layout.addWidget(self._coach_card(rec))

        leftovers = [(idx, rec) for idx, rec in enumerate(queue) if idx not in rendered]
        if leftovers:
            group_title = QLabel(f"WEITERE CHANCEN · {len(leftovers)}")
            group_title.setObjectName("CoachGroupTitle")
            self.coach_layout.addWidget(group_title)
            for idx, rec in leftovers:
                rec = dict(rec)
                rec["_queue_rank"] = rank
                rank += 1
                self.coach_layout.addWidget(self._coach_card(rec))

        remaining = max(0, len(recs) - len(queue))
        if remaining:
            more = QLabel(f"+ {remaining} weitere valide Hinweise werden aktuell niedriger priorisiert")
            more.setObjectName("Tiny")
            self.coach_layout.addWidget(more)

        deadline = portfolio_summary.get("deadline")
        deadline_text = deadline.strftime("%d.%m. %H:%M") if deadline else "Freitag 20:00"
        after_bids = int(portfolio_summary.get("balance_after_commitments") or 0)
        high_priority = sum(1 for row in recs if int(row.get("priority") or 0) >= 90)
        market_count = sum(1 for row in recs if row.get("kind") in {"kickbase_buy", "manager_buy"})
        squad_count = sum(1 for row in recs if row.get("kind") in {"sell", "squad_hold"})
        bid_count = sum(1 for row in recs if row.get("kind") == "bid")
        top = queue[0]
        top_name = str(top.get("name") or "Nächste Aktion")
        top_label = str(top.get("label") or "COACH")
        top_action = str(top.get("action") or "").strip()

        self.coach_focus_value.setText(f"{high_priority} DRINGEND" if high_priority else "STABIL")
        self.coach_focus_value.setProperty("tone", "warning" if high_priority else "positive")
        self.coach_liquidity_value.setText(euro(after_bids))
        self.coach_liquidity_value.setProperty("tone", "negative" if after_bids < 0 else "positive")
        self.coach_market_value.setText(str(market_count))
        self.coach_squad_value.setText(str(squad_count))
        for label in (self.coach_focus_value, self.coach_liquidity_value, self.coach_market_value, self.coach_squad_value):
            label.style().unpolish(label)
            label.style().polish(label)

        self.coach_hero_title.setText(f"Top-Fokus: {top_label} · {top_name}")
        self.coach_hero_meta.setText(top_action or "Coach hat aktuell die stärksten Handlungsimpulse für dich priorisiert.")

        def _refresh_chip(widget: QLabel, text_value: str, tone: str | None = None) -> None:
            widget.setText(text_value)
            if tone is None:
                widget.setProperty("tone", None)
            else:
                widget.setProperty("tone", tone)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        _refresh_chip(self.coach_deadline_chip, f"DEADLINE · {deadline_text}", "warning" if after_bids < 0 else "neutral")
        _refresh_chip(self.coach_budget_chip, f"NACH GEBOTEN · {euro(after_bids)}", "negative" if after_bids < 0 else "positive")
        slot_tone = "negative" if capacity.is_full else "warning" if capacity.free == 1 else "positive"
        _refresh_chip(self.coach_slots_chip, f"KADER · {capacity.current}/{capacity.maximum} · {capacity.free} FREI", slot_tone)
        _refresh_chip(self.coach_actions_chip, f"AKTIONEN · {len(queue)} / {len(recs)}", "neutral")
        _refresh_chip(self.coach_mix_chip, f"MIX · {market_count} Markt · {bid_count} Gebote · {squad_count} Kader", "neutral")

        self.coach_status.setText(
            f"{deadline_text} · {len(queue)} sichtbare Aktionen · {len(recs)} valide Signale insgesamt"
        )

    def _build_settings_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(12)

        title, subtitle = self._page_header("EINSTELLUNGEN", "Account und lokale Daten")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("Card")
        form = QFormLayout(card)
        form.setContentsMargins(22, 22, 22, 22)
        form.setHorizontalSpacing(25)
        form.setVerticalSpacing(14)

        self.settings_email = QLabel(self.storage.get_setting("email", "–"))
        self.settings_manager = QLabel(self.storage.get_setting("manager_id", "–"))
        db_label = QLabel(str(self.storage.conn.execute("PRAGMA database_list").fetchone()[2]))
        db_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        relog = QPushButton("KICKBASE-LOGIN ÄNDERN")
        relog.clicked.connect(self._login)

        form.addRow("Account", self.settings_email)
        form.addRow("Manager-ID", self.settings_manager)
        form.addRow("Datenbank", db_label)
        form.addRow("", relog)
        layout.addWidget(card)

        season_card = QFrame()
        season_card.setObjectName("Card")
        season_layout = QVBoxLayout(season_card)
        season_layout.setContentsMargins(22, 18, 22, 18)
        season_layout.setSpacing(9)
        season_title = QLabel("APP-MODUS")
        season_title.setObjectName("SectionTitle")
        self.season_mode_status = QLabel("")
        self.season_mode_status.setObjectName("Subtle")
        self.season_mode_status.setWordWrap(True)
        season_row = QHBoxLayout()
        season_label_widget = QLabel("Modus")
        self.season_mode_combo = QComboBox()
        self.season_mode_combo.addItem("AUTOMATISCH", "AUTO")
        self.season_mode_combo.addItem("PRESEASON · TEST", "PRESEASON")
        self.season_mode_combo.addItem("SAISON · TEST", "SEASON")
        saved_override = str(self.storage.get_setting("season_mode_override", "AUTO") or "AUTO").upper()
        index = self.season_mode_combo.findData(saved_override)
        self.season_mode_combo.setCurrentIndex(index if index >= 0 else 0)
        self.season_mode_combo.currentIndexChanged.connect(self._season_mode_override_changed)
        season_row.addWidget(season_label_widget)
        season_row.addWidget(self.season_mode_combo)
        season_row.addStretch()
        season_layout.addWidget(season_title)
        season_layout.addWidget(self.season_mode_status)
        season_layout.addLayout(season_row)
        layout.addWidget(season_card)

        advanced = QFrame()
        advanced.setObjectName("Card")
        advanced_layout = QVBoxLayout(advanced)
        advanced_layout.setContentsMargins(22, 18, 22, 18)
        advanced_layout.setSpacing(9)
        advanced_title = QLabel("ERWEITERTE DATENAKTUALISIERUNG")
        advanced_title.setObjectName("SectionTitle")
        advanced_text = QLabel(
            "Erzwingt einen vollständigen Live-Abruf für Kader, Budget, Markt, Liga/Manager-Kader, "
            "Transfers, Fixtures, Activity Feed und Performance-Daten. TTL-Caches werden dabei umgangen. "
            "Nur verwenden, wenn du wirklich alle Daten sofort neu ziehen möchtest."
        )
        advanced_text.setObjectName("Subtle")
        advanced_text.setWordWrap(True)
        self.force_update_btn = QPushButton("FORCE UPDATE · ALLE LIVE-DATEN")
        self.force_update_btn.setObjectName("DangerSecondary")
        self.force_update_btn.clicked.connect(self._force_update_all)
        advanced_layout.addWidget(advanced_title)
        advanced_layout.addWidget(advanced_text)
        advanced_layout.addWidget(self.force_update_btn, 0, Qt.AlignLeft)
        layout.addWidget(advanced)

        portraits = QFrame()
        portraits.setObjectName("Card")
        portraits_layout = QVBoxLayout(portraits)
        portraits_layout.setContentsMargins(22, 18, 22, 18)
        portraits_layout.setSpacing(10)
        portraits_title = QLabel("SPIELER-MASTER & PORTRAITS")
        portraits_title.setObjectName("SectionTitle")
        portraits_text = QLabel(
            "Kickbase liefert den aktuellen Bundesliga-Spielerpool. Spieler, die fehlen, werden nicht gelöscht, "
            "sondern zunächst als UNKNOWN und nach drei vollständigen Syncs als LEFT_LEAGUE markiert. "
            "Portraits werden lokal gecacht und bleiben dadurch auch nach einem Ligaabgang erhalten."
        )
        portraits_text.setObjectName("Subtle")
        portraits_text.setWordWrap(True)
        self.player_master_stats_label = QLabel("Noch kein Spielerpool synchronisiert")
        self.player_master_stats_label.setObjectName("Tiny")
        portrait_actions = QHBoxLayout()
        self.player_master_sync_btn = QPushButton("SPIELERPOOL SYNCHRONISIEREN")
        self.player_master_sync_btn.clicked.connect(lambda: self._sync_player_master_async(auto_portraits=True, manual=True))
        self.portrait_sync_btn = QPushButton("FEHLENDE PORTRAITS LADEN")
        self.portrait_sync_btn.clicked.connect(lambda: self._sync_portraits_async(limit=None, retry_failed=True))
        self.portrait_review_btn = QPushButton("PORTRAITS PRÜFEN")
        self.portrait_review_btn.clicked.connect(self._open_portrait_review)
        portrait_actions.addWidget(self.player_master_sync_btn)
        portrait_actions.addWidget(self.portrait_sync_btn)
        portrait_actions.addWidget(self.portrait_review_btn)
        portrait_actions.addStretch()
        portraits_layout.addWidget(portraits_title)
        portraits_layout.addWidget(portraits_text)
        portraits_layout.addWidget(self.player_master_stats_label)
        portraits_layout.addLayout(portrait_actions)
        layout.addWidget(portraits)
        self._refresh_player_master_stats()

        layout.addStretch()
        self._add_scroll_page(page)

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------

    def _make_table(self, headers: list[str], widths: list[int]) -> QTableWidget:
        table = ResponsiveTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(44)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.setWordWrap(False)
        table.setCornerButtonEnabled(False)
        table.setSortingEnabled(True)
        table.setIconSize(QSize(34, 34))
        table.setMouseTracking(True)
        table.viewport().setMouseTracking(True)
        table.setAttribute(Qt.WA_Hover, True)
        table.viewport().setAttribute(Qt.WA_Hover, True)
        table.horizontalHeader().setSortIndicatorShown(True)

        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(56)
        table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        for column, width in enumerate(widths):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            table.setColumnWidth(column, width)
        table.set_responsive_widths(widths)
        return table

    def _show_table_tooltip(self, table: QTableWidget, row: int, column: int) -> None:
        item = table.item(row, column)
        text = item.toolTip() if item is not None else ""
        if not text:
            QToolTip.hideText()
            return

        # Offset slightly so the tooltip never sits directly underneath the cursor.
        QToolTip.showText(QCursor.pos() + QPoint(14, 18), text, table.viewport(), msecDisplayTime=2200)

    def _fit_table_height(self, table: QTableWidget, row_count: int, *, min_rows: int = 1, max_rows: int | None = None) -> None:
        """Let page scrolling handle long tables instead of clipping them."""
        visible_rows = max(row_count, min_rows)
        if max_rows is not None:
            visible_rows = min(visible_rows, max_rows)
        header_height = table.horizontalHeader().height() or 38
        row_height = table.verticalHeader().defaultSectionSize() or 46
        target_height = header_height + visible_rows * row_height + 8
        table.setMinimumHeight(target_height)
        table.setMaximumHeight(16777215)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    # ------------------------------------------------------------------
    # Responsive layout
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _reflow_cards(self, grid: QGridLayout, widgets: list[QWidget], columns: int) -> None:
        columns = max(1, columns)
        for widget in widgets:
            grid.removeWidget(widget)
        for index, widget in enumerate(widgets):
            grid.addWidget(widget, index // columns, index % columns)
        for column in range(4):
            grid.setColumnStretch(column, 1 if column < columns else 0)

    def _resize_table_columns(self, table: QTableWidget) -> None:
        if isinstance(table, ResponsiveTableWidget):
            table.fit_columns_to_viewport()

    def _responsive_content_width(self) -> int:
        """Return the actually visible page width, not the QStackedWidget size hint.

        Every page is hosted in a QScrollArea. Using the stack width can be wrong
        while the scroll area's viewport is much narrower, which previously made
        grids keep a multi-column layout and clip their contents.
        """
        if hasattr(self, "stack"):
            current = self.stack.currentWidget()
            if isinstance(current, QScrollArea):
                viewport_width = current.viewport().width()
                if viewport_width > 0:
                    return viewport_width
            stack_width = self.stack.width()
            if stack_width > 0:
                return stack_width
        return self.width()

    def _apply_responsive_layout(self) -> None:
        width = self._responsive_content_width()

        # Real desktop breakpoints: never squeeze four/two KPI cards until their
        # text gets clipped. At small widths every card receives the full row.
        if width >= 1180:
            card_columns = 4
        elif width >= 720:
            card_columns = 2
        else:
            card_columns = 1
        if hasattr(self, "dashboard_cards_grid"):
            self._reflow_cards(self.dashboard_cards_grid, self.dashboard_cards, card_columns)
        if getattr(self, "dashboard_secondary_grid", None) is not None:
            secondary_columns = 3 if width >= 1180 else card_columns
            self._reflow_cards(self.dashboard_secondary_grid, self.dashboard_secondary_cards, secondary_columns)
        if hasattr(self, "transfer_cards_grid"):
            self._reflow_cards(self.transfer_cards_grid, self.transfer_cards, card_columns)
        if hasattr(self, "analysis_cards_grid"):
            self._reflow_cards(self.analysis_cards_grid, self.analysis_cards, card_columns)
        if hasattr(self, "market_cards_grid"):
            self._reflow_cards(self.market_cards_grid, self.market_cards, card_columns)
        if hasattr(self, "squad_analysis_cards_grid"):
            self._reflow_cards(self.squad_analysis_cards_grid, self.squad_analysis_cards, card_columns)
        if hasattr(self, "league_cards_grid"):
            self._reflow_cards(self.league_cards_grid, self.league_cards, card_columns)

        # Dashboard uses a dense editorial grid on wide desktop windows and
        # gracefully falls back to two / one columns when space gets tight.
        if hasattr(self, "dashboard_charts_grid") and self.dashboard_charts_grid is not None and len(self.dashboard_charts) > 1:
            for widget in self.dashboard_charts:
                self.dashboard_charts_grid.removeWidget(widget)

            # QGridLayout keeps old column stretch values. Reset every column on
            # every reflow; otherwise hidden columns continue consuming space and
            # produce the narrow-left-column / huge-empty-right-area bug.
            for column in range(4):
                self.dashboard_charts_grid.setColumnStretch(column, 0)
                self.dashboard_charts_grid.setColumnMinimumWidth(column, 0)

            if width >= 1260:
                self.dashboard_charts_grid.addWidget(self.dashboard_value_chart, 0, 0, 1, 2)
                self.dashboard_charts_grid.addWidget(self.dashboard_positions_chart, 0, 2)
                self.dashboard_charts_grid.addWidget(self.dashboard_transfers_chart, 0, 3)
                for column in range(4):
                    self.dashboard_charts_grid.setColumnStretch(column, 1)
            elif width >= 760:
                # The history chart gets a full row; the two compact charts share
                # the second row. This keeps every chart readable at medium widths.
                self.dashboard_charts_grid.addWidget(self.dashboard_value_chart, 0, 0, 1, 2)
                self.dashboard_charts_grid.addWidget(self.dashboard_positions_chart, 1, 0)
                self.dashboard_charts_grid.addWidget(self.dashboard_transfers_chart, 1, 1)
                self.dashboard_charts_grid.setColumnStretch(0, 1)
                self.dashboard_charts_grid.setColumnStretch(1, 1)
            else:
                # Small desktop/window mode: full-width stacked cards, never a
                # 180px-wide chart strip next to unused whitespace.
                for index, widget in enumerate(self.dashboard_charts):
                    self.dashboard_charts_grid.addWidget(widget, index, 0)
                self.dashboard_charts_grid.setColumnStretch(0, 1)

        # Account text is useful but expendable when horizontal room gets tight.
        if hasattr(self, "account"):
            self.account.setVisible(width >= 960)
        if hasattr(self, "league_combo"):
            self.league_combo.setMinimumWidth(145 if width < 1080 else 165)

        if hasattr(self, "sidebar"):
            compact_sidebar = self.width() < 1180
            target_width = 82 if compact_sidebar else 214
            self.sidebar.setMinimumWidth(target_width)
            self.sidebar.setMaximumWidth(target_width)
            self.sidebar.setProperty("compact", compact_sidebar)
            refresh_style(self.sidebar)
            if hasattr(self, "sidebar_logo"):
                self.sidebar_logo.setVisible(not compact_sidebar)
            if hasattr(self, "sidebar_footer"):
                self.sidebar_footer.setVisible(not compact_sidebar)
            for button in getattr(self, "nav_buttons", []):
                button.setText(
                    self._nav_compact_texts.get(button, button.text())
                    if compact_sidebar
                    else self._nav_full_texts.get(button, button.text())
                )
                button.setToolTip(self._nav_full_texts.get(button, "") if compact_sidebar else "")

        if hasattr(self, "manager_status_strip"):
            self.manager_status_strip.setVisible(width >= 760)
        if hasattr(self, "global_player_search"):
            self.global_player_search.setVisible(width >= 620)

        for name in (
            "dashboard_table",
            "squad_table",
            "league_table",
            "transfer_table",
        ):
            table = getattr(self, name, None)
            if table is not None:
                self._resize_table_columns(table)
        for table in getattr(self, "analysis_role_tables", {}).values():
            self._resize_table_columns(table)

    # ------------------------------------------------------------------
    # Login / league selection
    # ------------------------------------------------------------------

    def _login(self) -> None:
        dialog = LoginDialog(self, self.storage, self.client)
        if dialog.exec() != QDialog.Accepted:
            return

        email = self.storage.get_setting("email", "")
        self.account.setText(email)
        self.settings_email.setText(email)
        self._load_leagues_async()

    def _load_leagues_async(self) -> None:
        self.league_combo.setEnabled(False)
        self.sync_btn.setEnabled(False)
        self.statusBar().showMessage("Ligen werden geladen …")

        worker = FunctionWorker(self.client.leagues)
        self._league_worker = worker
        worker.signals.succeeded.connect(self._leagues_loaded)
        worker.signals.failed.connect(self._leagues_failed)
        QThreadPool.globalInstance().start(worker)

    def _leagues_loaded(self, leagues: list[dict]) -> None:
        self.league_combo.blockSignals(True)
        self.league_combo.clear()
        for league in leagues:
            self.league_combo.addItem(league["name"], league["id"])

        saved_league = self.storage.get_setting("league_id")
        index = self.league_combo.findData(saved_league) if saved_league else -1
        if index >= 0:
            self.league_combo.setCurrentIndex(index)
        self.league_combo.blockSignals(False)
        self.league_combo.setEnabled(True)
        self.sync_btn.setEnabled(True)
        self._apply_coach_access()
        self.refresh_all()
        self.statusBar().showMessage(f"Kickbase verbunden · {len(leagues)} Liga(en)", 6000)
        QTimer.singleShot(250, lambda: self._sync_player_master_async(auto_portraits=True, manual=False))

    def _leagues_failed(self, message: str) -> None:
        self.league_combo.setEnabled(True)
        self.sync_btn.setEnabled(True)
        self.statusBar().showMessage("Ligen konnten nicht geladen werden", 6000)
        QMessageBox.warning(self, "Initialisierung fehlgeschlagen", message)

    def _league_changed(self) -> None:
        league_id = self.league_combo.currentData()
        if league_id:
            self.storage.set_setting("league_id", league_id)
            self._apply_coach_access(str(league_id))
            self.refresh_all()

    # ------------------------------------------------------------------
    # Competition player master / portraits
    # ------------------------------------------------------------------

    def _refresh_player_master_stats(self) -> None:
        if not hasattr(self, "player_master_stats_label"):
            return
        stats = self.storage.player_master_stats()
        total = int(stats.get("total") or 0)
        if not total:
            self.player_master_stats_label.setText("Noch kein Spielerpool synchronisiert")
            return
        self.player_master_stats_label.setText(
            f"{stats.get('active', 0)} aktiv · {stats.get('unknown', 0)} unklar · "
            f"{stats.get('left', 0)} Liga verlassen · {stats.get('cached', 0)}/{stats.get('active', 0)} Portraits gecacht · "
            f"{stats.get('review', 0)} prüfen · {stats.get('failed', 0)} fehlgeschlagen · "
            f"{stats.get('rejected', 0)} abgelehnt"
        )
        if hasattr(self, "portrait_review_btn"):
            review_count = int(stats.get("review") or 0)
            self.portrait_review_btn.setEnabled(review_count > 0)
            self.portrait_review_btn.setText(
                f"PORTRAITS PRÜFEN · {review_count}" if review_count else "PORTRAITS PRÜFEN"
            )

    def _open_portrait_review(self) -> None:
        rows = self.storage.portrait_review_rows()
        if not rows:
            QMessageBox.information(self, "Portraits", "Aktuell gibt es keine unsicheren Portrait-Treffer zu prüfen.")
            return
        dialog = PortraitReviewDialog(self.storage, self)
        dialog.exec()
        self._refresh_player_master_stats()

    def _sync_player_master_async(self, *, auto_portraits: bool, manual: bool = False) -> None:
        if self._player_master_worker is not None:
            return
        previous_total = int(self.storage.player_master_stats().get("total") or 0)
        if hasattr(self, "player_master_sync_btn"):
            self.player_master_sync_btn.setEnabled(False)
            self.player_master_sync_btn.setText("SPIELERPOOL LÄDT …")
        if manual:
            self.statusBar().showMessage("Bundesliga-Spielerpool wird über Kickbase synchronisiert …")

        def load_master():
            players = self.client.competition_players()
            result = sync_player_master(self.storage, players, missing_threshold=3)
            result["previous_total"] = previous_total
            return result

        worker = FunctionWorker(load_master)
        self._player_master_worker = worker
        worker.signals.succeeded.connect(
            lambda result: self._player_master_sync_succeeded(result, auto_portraits=auto_portraits, manual=manual)
        )
        worker.signals.failed.connect(lambda message: self._player_master_sync_failed(message, manual=manual))
        worker.signals.finished.connect(self._player_master_sync_finished)
        QThreadPool.globalInstance().start(worker)

    def _player_master_sync_succeeded(self, result: dict, *, auto_portraits: bool, manual: bool) -> None:
        self._refresh_player_master_stats()
        self._refresh_global_player_search()
        new_count = int(result.get("new") or 0)
        active = int(result.get("active") or 0)
        if manual or new_count:
            self.statusBar().showMessage(
                f"Spielerpool: {active} aktiv · {new_count} neu · "
                f"{int(result.get('unknown') or 0)} unklar · {int(result.get('left') or 0)} Liga verlassen",
                8000,
            )

        # First installation deliberately does not hammer through the complete
        # portrait backfill automatically. The settings button starts that once.
        # Afterwards newly appearing Kickbase IDs are matched automatically.
        if auto_portraits and int(result.get("previous_total") or 0) > 0 and new_count > 0:
            new_ids = [str(value) for value in result.get("new_ids") or []]
            QTimer.singleShot(200, lambda ids=new_ids: self._sync_portraits_async(player_ids=ids))

    def _player_master_sync_failed(self, message: str, *, manual: bool) -> None:
        if manual:
            self.statusBar().showMessage("Spielerpool konnte nicht synchronisiert werden", 7000)
            QMessageBox.warning(self, "Spielerpool", message)

    def _player_master_sync_finished(self) -> None:
        self._player_master_worker = None
        if hasattr(self, "player_master_sync_btn"):
            self.player_master_sync_btn.setEnabled(True)
            self.player_master_sync_btn.setText("SPIELERPOOL SYNCHRONISIEREN")
        self._refresh_player_master_stats()

    def _sync_portraits_async(
        self, *, limit: int | None = None, retry_failed: bool = False, player_ids: list[str] | None = None
    ) -> None:
        if self._portrait_worker is not None:
            return
        if not self.storage.player_master_stats().get("active"):
            QMessageBox.information(self, "Portraits", "Bitte zuerst den Spielerpool synchronisieren.")
            return
        if hasattr(self, "portrait_sync_btn"):
            self.portrait_sync_btn.setEnabled(False)
            self.portrait_sync_btn.setText("PORTRAITS WERDEN GELADEN …")
        self.statusBar().showMessage("Fehlende Spielerportraits werden abgeglichen und lokal gecacht …")

        league_id = self.league_combo.currentData() or self.storage.get_setting("league_id")
        worker = FunctionWorker(
            lambda: sync_missing_portraits(
                self.storage,
                limit=limit,
                retry_failed=retry_failed,
                player_ids=player_ids,
                kickbase_client=self.client,
                league_id=str(league_id) if league_id else None,
            )
        )
        self._portrait_worker = worker
        worker.signals.succeeded.connect(self._portrait_sync_succeeded)
        worker.signals.failed.connect(self._portrait_sync_failed)
        worker.signals.finished.connect(self._portrait_sync_finished)
        QThreadPool.globalInstance().start(worker)

    def _portrait_sync_succeeded(self, result: dict) -> None:
        self._refresh_player_master_stats()
        self._refresh_global_player_search()
        requested = int(result.get("requested") or 0)
        cached = int(result.get("cached") or 0)
        review = int(result.get("review") or 0)
        failed = int(result.get("failed") or 0)
        if requested:
            self.statusBar().showMessage(
                f"Portraits: {cached}/{requested} gecacht · {review} prüfen · {failed} fehlgeschlagen",
                9000,
            )
        else:
            self.statusBar().showMessage("Portraits: keine neuen Spieler offen", 6000)

    def _portrait_sync_failed(self, message: str) -> None:
        self.statusBar().showMessage("Portrait-Abgleich fehlgeschlagen", 7000)
        QMessageBox.warning(self, "Portrait-Abgleich", message)

    def _portrait_sync_finished(self) -> None:
        self._portrait_worker = None
        if hasattr(self, "portrait_sync_btn"):
            self.portrait_sync_btn.setEnabled(True)
            self.portrait_sync_btn.setText("FEHLENDE PORTRAITS LADEN")
        self._refresh_player_master_stats()

    # ------------------------------------------------------------------
    # Force refresh
    # ------------------------------------------------------------------

    def _force_update_all(self) -> None:
        league_id = self.league_combo.currentData() or self.storage.get_setting("league_id")
        if not league_id:
            QMessageBox.warning(self, "Keine Liga", "Bitte zuerst eine Liga auswählen.")
            return
        if self._force_update_active:
            return
        busy = any((
            self._sync_worker, self._league_analysis_worker, self._league_ownership_worker,
            self._market_worker, self._budget_worker, self._intelligence_worker, self._league_learning_worker,
        ))
        if busy:
            self.statusBar().showMessage("Force Update wartet: Es läuft bereits eine Aktualisierung.", 6000)
            return

        self._force_update_active = True
        self._force_ownership_pending = True
        self.force_update_btn.setEnabled(False)
        self.force_update_btn.setText("FORCE UPDATE LÄUFT …")
        self.statusBar().showMessage("Force Update: vollständiger Live-Abruf wird gestartet …")
        # Start with the coherent own-team sync. Its success handler starts the
        # additional live areas so the freshly detected manager id is available.
        self.sync()
        QTimer.singleShot(250, self._poll_force_update_finished)

    def _start_force_update_dependents(self) -> None:
        self._refresh_league_overview_async(force=True)
        self._load_market_overview()
        self._load_budget_overview()
        self._load_intelligence(force=True)

    def _poll_force_update_finished(self) -> None:
        if not self._force_update_active:
            return
        busy = any((
            self._sync_worker, self._league_analysis_worker, self._league_ownership_worker,
            self._market_worker, self._budget_worker, self._intelligence_worker, self._league_learning_worker,
        ))
        if busy or self._force_ownership_pending:
            QTimer.singleShot(300, self._poll_force_update_finished)
            return
        self._force_update_active = False
        self.force_update_btn.setEnabled(True)
        self.force_update_btn.setText("FORCE UPDATE · ALLE LIVE-DATEN")
        self.refresh_all()
        self.statusBar().showMessage("Force Update abgeschlossen · alle Live-Bereiche wurden neu geladen", 9000)

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    def sync(self) -> None:
        league_id = self.league_combo.currentData()
        if not league_id:
            QMessageBox.warning(self, "Keine Liga", "Bitte zuerst eine Liga auswählen.")
            return
        if self._sync_worker is not None:
            return

        league_id = str(league_id)
        known_manager_id = self.storage.get_league_setting(league_id, "manager_id")
        self._set_sync_busy(True)

        worker = FunctionWorker(
            lambda: self.sync_service.fetch(league_id, known_manager_id)
        )
        self._sync_worker = worker
        worker.signals.succeeded.connect(self._sync_succeeded)
        worker.signals.failed.connect(self._sync_failed)
        worker.signals.finished.connect(self._sync_finished)
        QThreadPool.globalInstance().start(worker)

    def _set_sync_busy(self, busy: bool) -> None:
        self.sync_btn.setEnabled(not busy)
        self.league_combo.setEnabled(not busy)
        self.sync_btn.setText("◌  SYNCHRONISIERE …" if busy else "↻  AKTUALISIEREN")
        if busy:
            self.statusBar().showMessage("Kickbase-Daten werden synchronisiert …")

    def _sync_succeeded(self, result: SyncResult) -> None:
        try:
            self.storage.apply_sync_result(result)
            if result.manager_id:
                self.settings_manager.setText(result.manager_id)
            self._apply_coach_access(result.league_id)
            self.refresh_all()

            metrics = self.storage.dashboard_metrics(result.league_id)
            details = [f"{len(result.players)} Spieler", f"{metrics['total_count']} Transfers"]
            if result.dashboard_loaded:
                details.append("Kickbase P/L geladen")
            self.statusBar().showMessage("Aktualisiert · " + " · ".join(details), 9000)
            if self._force_update_active:
                QTimer.singleShot(0, self._start_force_update_dependents)
        except Exception as exc:
            self._sync_failed(f"Daten konnten nicht gespeichert werden: {exc}")

    def _sync_failed(self, message: str) -> None:
        self.statusBar().showMessage("Synchronisierung fehlgeschlagen", 7000)
        if self._force_update_active:
            self._force_update_active = False
            self._force_ownership_pending = False
            if hasattr(self, "force_update_btn"):
                self.force_update_btn.setEnabled(True)
                self.force_update_btn.setText("FORCE UPDATE · ALLE LIVE-DATEN")
        QMessageBox.critical(self, "Sync fehlgeschlagen", message)

    def _sync_finished(self) -> None:
        self._sync_worker = None
        self._set_sync_busy(False)

    # ------------------------------------------------------------------
    # Refresh all pages
    # ------------------------------------------------------------------

    def refresh_all(self) -> None:
        league_id = self.league_combo.currentData()
        league_id = str(league_id) if league_id else self.storage.get_setting("league_id")
        self._refresh_dashboard(league_id)
        self._refresh_squad()
        self._refresh_league_page(league_id)
        self._refresh_transfers(league_id)
        self._refresh_analysis()

    def _refresh_dashboard(self, league_id: str | None) -> None:
        metrics = self.storage.dashboard_metrics(league_id)
        self.dash_profit.value_label.setText(delta_text(metrics["total_pnl"]))
        self.dash_profit.hint_label.setText(
            "seit Ligastart · Kickbase-Wert" if metrics["total_pnl"] is not None else "noch nicht synchronisiert"
        )
        set_delta_label(self.dash_profit.value_label, metrics["total_pnl"])

        self.dash_team_value.value_label.setText(euro(metrics["team_value"]))
        self.dash_budget.value_label.setText(euro(metrics["budget"]))
        self.dash_day.value_label.setText(delta_text(metrics["daily_change"]))
        set_delta_label(self.dash_day.value_label, metrics["daily_change"])

        history_rows = self.storage.team_value_history(str(league_id), 30) if league_id else []
        self.dash_team_value.set_sparkline([row.get("team_value") for row in history_rows])
        # Profit/budget do not have trustworthy historical snapshots yet. Keep the
        # sparkline hidden instead of drawing decorative/fake data.
        self.dash_profit.set_sparkline([])
        self.dash_budget.set_sparkline([])
        self.dash_day.set_sparkline([])

        self.dash_open.value_label.setText(delta_text(metrics["open_pnl"]))
        set_delta_label(self.dash_open.value_label, metrics["open_pnl"])
        self.dash_realized.value_label.setText(delta_text(metrics["realized_pnl"]))
        set_delta_label(self.dash_realized.value_label, metrics["realized_pnl"])
        self.dash_assets.value_label.setText(euro(metrics["total_assets"]))
        self.dash_transfer_count.value_label.setText(str(metrics["total_count"]))
        self.dash_transfer_count.hint_label.setText(
            f"{metrics['buy_count']} Käufe · {metrics['sell_count']} Verkäufe"
        )
        status = squad_status(self.storage.current_players())
        self.dash_status.value_label.setText(str(status["available"]))
        self.dash_status.hint_label.setText(
            f"{status['questionable']} fraglich · {status['unavailable']} nicht verfügbar"
        )
        if status["affected"]:
            self.dash_status.setToolTip("\n".join(
                f"{p.get('name', 'Spieler')}: {p.get('availability_label', 'STATUS')}" for p in status["affected"]
            ))
        else:
            self.dash_status.setToolTip("Keine erkannten Verfügbarkeitswarnungen im aktuellen Kader.")

        # Explanatory hover details for the compact dashboard cards.
        self.dash_profit.setToolTip(
            "Gesamter Gewinn/Verlust laut Kickbase seit Ligastart.\n"
            "Enthält bereits realisierte Verkäufe und die aktuelle Kaderentwicklung."
        )
        self.dash_team_value.setToolTip(
            f"Aktueller Marktwert des gesamten Kaders: {euro(metrics['team_value'])}"
        )
        self.dash_budget.setToolTip(
            f"Aktuell verfügbares Transferbudget: {euro(metrics['budget'])}"
        )
        self.dash_day.setToolTip(
            f"Exakte aufsummierte 24h-Marktwertänderung des aktuellen Kaders: "
            f"{delta_text(metrics['daily_change'])}\nQuelle: Kickbase 24h-Werte der Spieler"
        )
        self.dash_open.setToolTip(
            f"Aktueller Kader +/-: {delta_text(metrics['open_pnl'])}\n"
            "Berechnung: aktueller Marktwert minus Kaufpreis/Startwert aller Kaderspieler."
        )
        self.dash_realized.setToolTip(
            f"Verkaufsgewinn/-verlust: {delta_text(metrics['realized_pnl'])}\n"
            "Berechnung: Kickbase Gesamtgewinn minus aktueller Kader +/- ."
        )
        self.dash_assets.setToolTip(
            f"Gesamtvermögen: {euro(metrics['total_assets'])}\nBerechnung: Kaderwert + Budget."
        )
        self.dash_transfer_count.setToolTip(
            f"Erfasste Transfers: {metrics['total_count']}\n"
            f"{metrics['buy_count']} Käufe · {metrics['sell_count']} Verkäufe"
        )

        players = self._player_metrics()

        capacity = squad_capacity(players)
        free_budget = int(getattr(self, "_cash_balance", 0) or metrics.get("budget") or 0) - int(getattr(self, "_active_bid_committed", 0) or 0)
        action_items: list[tuple[str, str, str]] = []
        season_active = self._season_mode_active()
        if season_active:
            focus_title = "Nächsten Spieltag vorbereiten"
            focus_subtitle = "Prüfe Verfügbarkeit, Aufstellung und Gegner. Trading bleibt sekundär im Blick."
            action_items.append(("⚽", "Spieltag-Modus aktiv", "Aufstellung, Fixtures und Saisonleistung sind jetzt freigeschaltet"))
        else:
            focus_title = "Kaderaufbau weiter optimieren"
            focus_subtitle = "Aktuell gibt es keine dringende Einzelaktion. Nutze Markt und Coach für den nächsten Schritt."
        if capacity.is_full:
            focus_title = "Kader voll – jeder Zugang braucht einen Abgang"
            focus_subtitle = "18/18 Plätze belegt. Neue Marktchancen werden deshalb nur noch als Upgrade + Verkauf bewertet."
            action_items.append(("!", "Kaderlimit erreicht", "18/18 · vor dem nächsten Zugang einen Platz freimachen"))
        elif capacity.free == 1:
            action_items.append(("!", "Nur noch ein Kaderplatz frei", "17/18 · Investments jetzt strenger priorisieren"))
        else:
            action_items.append(("◆", f"{capacity.free} Kaderplätze frei", f"{capacity.label} · genug Flexibilität für gezielte Investments"))

        bid_count = active_bid_count(getattr(self, "_market_rows", []) or [])
        if bid_count:
            action_items.append(("⚡", f"{bid_count} aktive Gebote", f"Nach Geboten: {euro(free_budget)}"))
        if status["affected"]:
            action_items.append(("!", f"{len(status['affected'])} Statushinweise im Kader", "Verfügbarkeit vor der Aufstellung prüfen" if season_active else "Verfügbarkeit vor Startkader-Entscheidungen prüfen"))
            if season_active or not capacity.is_full:
                focus_title = "Statusrisiken vor dem Spieltag prüfen" if season_active else "Statusrisiken im Startkader prüfen"
                focus_subtitle = "Mindestens ein Kaderspieler ist aktuell nicht vollständig verfügbar."
        if metrics.get("daily_change"):
            action_items.append(("↗" if metrics["daily_change"] > 0 else "↘", f"{delta_text(metrics['daily_change'], compact=True)} Marktwert heute", "Summe des aktuellen Kaders"))

        market_candidates = [
            row for row in (getattr(self, "_market_rows", []) or [])
            if str(row.get("verdict") or row.get("action") or "").upper() in {"KADERZIEL", "INVEST"}
        ]
        if market_candidates and not capacity.is_full and not season_active:
            market_candidates.sort(key=lambda r: int(r.get("value_score") or r.get("trading_score") or 0), reverse=True)
            best = market_candidates[0]
            name = str(best.get("name") or "Marktchance")
            verdict = str(best.get("verdict") or best.get("action") or "CHANCE").upper()
            focus_title = f"{name}: {verdict}"
            focus_subtitle = str(best.get("primary_reason") or best.get("analysis_text") or "Aktuell die stärkste priorisierte Marktchance.")

        self.dashboard_focus.set_content(
            title=focus_title,
            subtitle=focus_subtitle,
            squad=capacity.label,
            budget=euro(free_budget),
            day=delta_text(metrics.get("daily_change"), compact=True),
            actions=str(len(action_items)),
        )
        self.dashboard_activity_feed.set_items(action_items)

        self._set_team_value_history_chart(
            self.dashboard_value_chart.chart_view,
            self.storage.team_value_history(league_id, 90),
        )
        if self.dashboard_positions_chart is not None:
            self._set_position_allocation_chart(self.dashboard_positions_chart.chart_view, players)

        movers = sorted(players, key=lambda p: abs(p["d1"] or 0), reverse=True)[:6]
        self.dashboard_table.setSortingEnabled(False)
        self.dashboard_table.setRowCount(len(movers))
        self._fit_table_height(self.dashboard_table, len(movers), min_rows=6, max_rows=6)
        for row, player in enumerate(movers):
            specs = [
                (player["name"], player["name"]),
                (player["position"], POSITION_SORT.get(player["position"], 99)),
                (euro(player["market_value"]), player["market_value"]),
                (delta_text(player["d1"], compact=True), player["d1"] if player["d1"] is not None else -10**18),
                (delta_text(player["pnl"], compact=True), player["pnl"] if player["pnl"] is not None else -10**18),
                (percent(player["roi"]), player["roi"] if player["roi"] is not None else -10**18),
            ]
            for col, (text, sort_value) in enumerate(specs):
                item = table_item("" if col == 0 else text, sort_value)
                item.setData(Qt.UserRole, str(player["player_id"]))
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col == 0 else Qt.AlignCenter)
                if col == 0:
                    status_tip = player_status_tooltip(player)
                    item.setToolTip(status_tip)
                if col == 2:
                    item.setToolTip(market_value_tooltip(player))
                elif col == 3:
                    set_item_delta_color(item, player["d1"])
                    item.setToolTip(change_tooltip("24h Änderung", player["market_value"], player["d1"], exact=True))
                elif col in (4, 5):
                    set_item_delta_color(item, player["pnl"])
                    item.setToolTip(market_value_tooltip(player))
                self.dashboard_table.setItem(row, col, item)
                if col == 0:
                    portrait_path = self.storage.portrait_path(str(player.get("player_id") or ""))
                    self.dashboard_table.setCellWidget(row, col, player_name_cell(player, portrait_path, player.get("name") or "–"))
        self.dashboard_table.setSortingEnabled(True)

        mover_labels = [p["name"] for p in movers]
        mover_values = [p["d1"] or 0 for p in movers]
        if self.dashboard_movers_chart is not None:
            self._set_positive_negative_bar_chart(
                self.dashboard_movers_chart.chart_view,
                mover_labels,
                mover_values,
                positive_name="Positiv",
                negative_name="Negativ",
                subtitle="Werte in Tausend €",
            )
            self.dashboard_movers_chart.subtitle.setText("Werte in Mio. € · positiv grün / negativ rot")

        transfer_rows = self.storage.transfer_rows(league_id)
        if not transfer_rows and league_id:
            transfer_rows = self.storage.transfer_rows(None)
        if self.dashboard_transfers_chart is not None:
            self._set_transfer_volume_chart(self.dashboard_transfers_chart.chart_view, transfer_rows[-12:])
        self._update_manager_status_strip()

    def _refresh_squad(self) -> None:
        players = self._player_metrics()
        league_id = self.league_combo.currentData() if hasattr(self, "league_combo") else None
        league_id = str(league_id) if league_id else self.storage.get_setting("league_id")
        points_are_current = self._season_stats_current(league_id)
        market_context = getattr(self, "_market_rows", []) or []
        current_budget = self.storage.dashboard_metrics(league_id).get("budget") if league_id else None
        # Rendering the squad must stay cheap. Reuse the forecasts already
        # produced by an explicit market refresh instead of rebuilding the full
        # model from all MW history every time the Kader tab is opened.
        try:
            stored_predictions = (
                self.storage.mv_predictions_for_target(str(league_id), self._mv_prediction_target_date())
                if league_id else {}
            )
            for p in players:
                raw = stored_predictions.get(str(p.get("player_id") or ""))
                if not raw:
                    continue
                pred = {
                    "delta": raw.get("predicted_delta"),
                    "expected_value": raw.get("expected_value"),
                    "low_delta": raw.get("low_delta"),
                    "high_delta": raw.get("high_delta"),
                    "confidence": raw.get("confidence"),
                    "sample_count": raw.get("sample_count"),
                    "history_days": raw.get("history_days"),
                    "method": raw.get("method"),
                }
                p["next_refresh_prediction"] = pred
                p["next_refresh_delta"] = pred.get("delta")
        except Exception:
            pass
        players = enrich_squad_entries(
            players,
            points_are_current=points_are_current,
            market_rows=market_context,
            available_budget=current_budget,
        )
        # The Kader page uses the same preseason action language as the Coach.
        # Legacy sell/squad scores remain internal inputs, not competing UI outputs.
        try:
            _unused_market, players, _unused_summary = analyze_portfolio(
                [],
                players,
                available_budget=int(getattr(self, "_cash_balance", current_budget or 0) or 0),
                season_started=self._season_mode_active(),
                committed_budget=int(getattr(self, "_active_bid_committed", 0) or 0),
            )
        except Exception:
            pass

        if hasattr(self, "squad_quality_card"):
            roles = [str(p.get("player_role") or "OFFEN").upper() for p in players]
            self.squad_quality_card.value_label.setText(str(sum(1 for r in roles if r == "STAMM")))
            self.squad_core_card.value_label.setText(str(sum(1 for r in roles if r == "INVEST")))
            self.squad_invest_card.value_label.setText(str(sum(1 for r in roles if r == "TRANSFERLISTE")))
            self.squad_sell_card.value_label.setText(str(sum(1 for p in players if p.get("action") in {"VERKAUFEN", "VERKAUF WARTEN"})))

        if hasattr(self, "squad_pitch"):
            self.squad_pitch.set_players(players, self.storage.portrait_path)
        if hasattr(self, "squad_bench"):
            self.squad_bench.set_players(players, self.storage.portrait_path)

        status = squad_status(players)
        if hasattr(self, "squad_status_table"):
            capacity = squad_capacity(players)
            self.squad_status_summary.setText(
                f"Kader {capacity.label} · {status['available']} verfügbar · {status['questionable']} fraglich · {status['unavailable']} nicht verfügbar"
            )
            affected = status["affected"]
            self.squad_status_table.setSortingEnabled(False)
            self.squad_status_table.setRowCount(len(affected))
            row_h = max(40, self.squad_status_table.verticalHeader().defaultSectionSize())
            visible_rows = min(3, len(affected))
            self.squad_status_table.setVisible(bool(affected))
            self.squad_status_empty.setVisible(not affected)
            if affected:
                self.squad_status_table.setFixedHeight(visible_rows * row_h + 4)
                for r, player in enumerate(affected):
                    status_text = player.get("status_detail") or player.get("availability_label") or "STATUS"
                    specs = [
                        (player.get("name") or "–", player.get("name") or ""),
                        (player.get("club") or "–", player.get("club") or "", club_icon(player.get("club"))),
                        (status_text, status_text),
                    ]
                    for c, spec in enumerate(specs):
                        display, sort_value, *icon = spec
                        item = table_item(display, sort_value, icon=icon[0] if icon else None)
                        item.setData(Qt.UserRole, str(player.get("player_id") or ""))
                        if c == 0:
                            item.setIcon(player_status_icon(player))
                            item.setToolTip(player_status_tooltip(player))
                        if c == 2:
                            item.setIcon(player_status_icon(player))
                            item.setToolTip(player_status_tooltip(player))
                            if player.get("availability_label") == "FRAGLICH":
                                item.setForeground(QColor("#F3C44E"))
                            else:
                                item.setForeground(QColor("#FF6B6B"))
                        self.squad_status_table.setItem(r, c, item)
            self.squad_status_table.setSortingEnabled(True)

        self.squad_table.setSortingEnabled(False)
        self.squad_table.setRowCount(len(players))
        for row, player in enumerate(players):
            trend_source = player["d3"] if player["d3"] is not None else player["d1"]
            trend = "→" if not trend_source else ("↗" if trend_source > 0 else "↘")
            role = (player.get("player_role") or "OFFEN").upper()
            specs = [
                (player["name"], player["name"]),
                (player["club"] or "–", player["club"] or "", club_icon(player["club"])),
                (player["position"], POSITION_SORT.get(player["position"], 99)),
                (ROLE_LABELS.get(role, role), ROLE_SORT.get(role, 99)),
                (euro(player["market_value"]), player["market_value"]),
                (delta_text(player["d1"], compact=True), player["d1"] if player["d1"] is not None else -10**18),
                (delta_text(player.get("next_refresh_delta"), compact=True), player.get("next_refresh_delta") if player.get("next_refresh_delta") is not None else -10**18),
                (delta_text(player["pnl"], compact=True), player["pnl"] if player["pnl"] is not None else -10**18),
                (player.get("kader_label") or self._score_label(player.get("squad_value_score")), int(player.get("squad_value_score") or 0)),
                (player.get("trade_label") or self._score_label(player.get("trading_score")), int(player.get("trading_score") or 0)),
                (player.get("action") or "HALTEN", int(player.get("squad_value_score") or 0)),
            ]
            for col, spec in enumerate(specs):
                text, sort_value = spec[0], spec[1]
                icon = spec[2] if len(spec) > 2 else None
                item = table_item(text, sort_value, icon=icon)
                item.setData(Qt.UserRole, player["player_id"])
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col in (0, 1) else Qt.AlignCenter)
                if col == 0:
                    item.setToolTip(player_status_tooltip(player))
                if col == 1 and icon is not None and not icon.isNull():
                    item.setToolTip(player["club"] or "")
                if col == 4:
                    item.setToolTip(market_value_tooltip(player))
                elif col == 5:
                    set_item_delta_color(item, player["d1"])
                    item.setToolTip(change_tooltip("24h Änderung", player["market_value"], player["d1"], exact=True))
                elif col == 6:
                    pred = player.get("next_refresh_prediction") or {}
                    set_item_delta_color(item, pred.get("delta"))
                    if pred.get("delta") is not None:
                        item.setToolTip(
                            f"Nächster MW-Refresh (22 Uhr)\n"
                            f"Prognose: {delta_text(pred.get('delta'))} → ca. {euro(pred.get('expected_value'))}\n"
                            f"80%-Erfahrungsbereich: {delta_text(pred.get('low_delta'))} bis {delta_text(pred.get('high_delta'))}\n"
                            f"Basis: {pred.get('confidence', 'UNSICHER')} · n={pred.get('sample_count', 0)}"
                        )
                elif col == 7:
                    set_item_delta_color(item, player["pnl"])
                    item.setToolTip(market_value_tooltip(player))
                elif col in (8, 9, 10):
                    item.setToolTip(player.get("squad_analysis_text") or "")
                self.squad_table.setItem(row, col, item)

            # Keep the role selector visually compact inside the table cell.
            # QTableWidget stretches a cell widget to the full column width; using
            # a transparent wrapper prevents the combo box from looking like a
            # full-width input field.
            role_cell = QWidget()
            role_cell.setObjectName("RoleCell")
            role_layout = QHBoxLayout(role_cell)
            role_layout.setContentsMargins(8, 7, 8, 7)
            role_layout.setSpacing(0)

            combo = QComboBox()
            combo.setObjectName("RoleCombo")
            combo.addItems(["OFFEN", "STAMM", "INVEST", "TRANSFERLISTE"])
            combo.setMinimumWidth(154)
            combo.setMaximumWidth(166)
            combo.setFixedHeight(30)
            combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(14)
            combo.setCurrentText(role if role in ROLE_LABELS else "OFFEN")
            combo.setProperty("role", combo.currentText())
            combo.setToolTip("Eigene Rolle für diesen Spieler. Wird lokal gespeichert.")
            combo.currentTextChanged.connect(
                lambda new_role, pid=player["player_id"], c=combo: self._role_changed(c, pid, new_role)
            )

            role_layout.addWidget(combo, 0, Qt.AlignVCenter | Qt.AlignLeft)
            role_layout.addStretch(1)
            self.squad_table.setCellWidget(row, 3, role_cell)
        self.squad_table.setSortingEnabled(True)
        # Keep every squad row visible and let PageScroll handle the page.
        # Include header + frame padding; with the Kickbase limit this tops out
        # at roughly 18 * 48 px and remains perfectly manageable.
        row_height = max(40, self.squad_table.verticalHeader().defaultSectionSize())
        header_height = self.squad_table.horizontalHeader().height() if self.squad_table.horizontalHeader().isVisible() else 0
        self.squad_table.setFixedHeight(header_height + len(players) * row_height + 6)

    def _open_dashboard_player_detail(self, item: QTableWidgetItem) -> None:
        player_id = item.data(Qt.UserRole)
        if not player_id:
            row_item = self.dashboard_table.item(item.row(), 0)
            player_id = row_item.data(Qt.UserRole) if row_item else None
        if not player_id:
            return
        league_id = self.league_combo.currentData()
        self.open_player_detail_tab(str(player_id), str(league_id) if league_id else None)

    def _open_player_detail(self, item: QTableWidgetItem) -> None:
        player_id = item.data(Qt.UserRole)
        if not player_id:
            row_item = self.squad_table.item(item.row(), 0)
            player_id = row_item.data(Qt.UserRole) if row_item else None
        if not player_id:
            return
        league_id = self.league_combo.currentData()
        self.open_player_detail_tab(str(player_id), str(league_id) if league_id else None)

    def _role_changed(self, combo: QComboBox, player_id: str, role: str) -> None:
        combo.setProperty("role", role)
        combo.style().unpolish(combo)
        combo.style().polish(combo)
        combo.update()
        self._set_player_role(player_id, role)

    def _set_player_role(self, player_id: str, role: str) -> None:
        self.storage.set_player_role(player_id, role)
        self._refresh_analysis()
        # Role is an explicit input to the Kader-/Verkaufsbewertung. Rebuild on
        # the next event-loop tick so the active ComboBox signal can finish first.
        QTimer.singleShot(0, self._refresh_squad)

    def _ensure_league_data(self) -> None:
        league_id = self.league_combo.currentData()
        if not league_id:
            return
        league_id = str(league_id)
        if not self.storage.league_managers_are_fresh(
            league_id, self.league_service.MANAGERS_TTL
        ):
            self._refresh_league_overview_async()
        else:
            self._ensure_league_ownership(league_id)

    def _refresh_league_overview_async(self, force: bool = False) -> None:
        league_id = self.league_combo.currentData()
        if not league_id or self._league_analysis_worker is not None:
            return
        league_id = str(league_id)
        self.league_refresh_btn.setEnabled(False)
        self.league_refresh_btn.setText("LÄDT …")
        self.statusBar().showMessage("Liga-Manager werden geladen …")

        worker = FunctionWorker(lambda: self.league_service.fetch_overview(league_id, force=force))
        self._league_analysis_worker = worker
        worker.signals.succeeded.connect(self._league_overview_succeeded)
        worker.signals.failed.connect(self._league_overview_failed)
        worker.signals.finished.connect(self._league_overview_finished)
        QThreadPool.globalInstance().start(worker)

    def _league_overview_succeeded(self, result: LeagueOverviewResult) -> None:
        try:
            self.storage.replace_league_managers(result)
            current = self.league_combo.currentData()
            if current and str(current) == result.league_id:
                self._refresh_league_page(result.league_id)
                force_ownership = bool(self._force_ownership_pending)
                self._force_ownership_pending = False
                self._ensure_league_ownership(result.league_id, force=force_ownership)
            self.statusBar().showMessage(f"Liga aktualisiert · {len(result.managers)} Manager", 7000)
        except Exception as exc:
            self._league_overview_failed(f"Liga-Daten konnten nicht gespeichert werden: {exc}")

    def _league_overview_failed(self, message: str) -> None:
        self.statusBar().showMessage("Liga-Daten konnten nicht geladen werden", 7000)
        if self._force_update_active:
            # Do not leave the force-update completion poll waiting forever when
            # the league overview itself fails before ownership can be started.
            self._force_ownership_pending = False
        QMessageBox.warning(self, "Liga konnte nicht geladen werden", message)

    def _league_overview_finished(self) -> None:
        self._league_analysis_worker = None
        self.league_refresh_btn.setEnabled(True)
        self.league_refresh_btn.setText("LIGA AKTUALISIEREN")

    def _refresh_league_page(self, league_id: str | None) -> None:
        if not league_id:
            self.league_table.setRowCount(0)
            return
        managers = self.storage.league_managers(str(league_id))
        self.league_managers_card.value_label.setText(str(len(managers)) if managers else "–")
        self._set_league_value_summary(managers)

        # Explicitly persisted by LeagueAnalysisService. Do not infer season
        # state from 0/None values: Kickbase can expose stale previous-season
        # aggregates in manager dashboards during preseason.
        season_started = (
            self.storage.get_league_setting(str(league_id), "season_started", "0") == "1"
        )

        own_id = self.storage.get_league_setting(str(league_id), "manager_id")
        own = next((manager for manager in managers if str(manager["manager_id"]) == str(own_id)), None)
        self.league_rank_card.value_label.setText(str(own.get("place")) if own and own.get("place") is not None else "–")
        self.league_rank_card.hint_label.setText(f"von {len(managers)}" if managers else "Liga-Ranking")

        values = [int(m["team_value"]) for m in managers if m.get("team_value") is not None]
        average_value = int(sum(values) / len(values)) if values else None
        self.league_value_card.value_label.setText(euro(average_value))

        leader = None
        ranked = [m for m in managers if m.get("place") is not None]
        if ranked:
            leader = min(ranked, key=lambda m: int(m["place"]))
        elif managers:
            scored = [m for m in managers if m.get("points") is not None]
            leader = max(scored, key=lambda m: int(m["points"])) if scored else None
        self.league_leader_card.value_label.setText(leader.get("name") if leader else "–")
        self.league_leader_card.hint_label.setText(
            f"{leader.get('points')} Punkte" if leader and leader.get("points") is not None else "nach Punkten"
        )

        updated = max((m.get("updated_at") or "" for m in managers), default="")
        self.league_updated.setText(f"Stand {display_date(updated)}" if updated else "Noch nicht geladen")

        covered, total = self.storage.ownership_coverage(str(league_id))
        ownership_fresh = self.storage.league_ownership_is_fresh(
            str(league_id), self.league_service.SQUAD_TTL
        )
        if ownership_fresh and total:
            self.league_ownership_status.setText(f"Spielerbesitz: {total}/{total} Manager aktuell")
        elif self._league_ownership_worker is not None:
            self.league_ownership_status.setText(f"Spielerbesitz: synchronisiert … ({covered}/{total})")
        elif total:
            self.league_ownership_status.setText(f"Spielerbesitz: {covered}/{total} Manager erfasst")
        else:
            self.league_ownership_status.setText("Spielerbesitz: noch nicht synchronisiert")

        self.league_table.setSortingEnabled(False)
        self.league_table.setRowCount(len(managers))
        for row, manager in enumerate(managers):
            is_own = own_id is not None and str(manager["manager_id"]) == str(own_id)
            manager_name = manager["name"] + ("  ·  DU" if is_own else "")
            specs = [
                (str(manager.get("place")) if manager.get("place") is not None else "–", manager.get("place") if manager.get("place") is not None else 10**9),
                (manager_name, manager["name"]),
                (str(manager.get("points")) if manager.get("points") is not None else "–", manager.get("points") if manager.get("points") is not None else -1),
                (euro(manager.get("team_value")), manager.get("team_value") if manager.get("team_value") is not None else -1),
                (delta_text(manager.get("profit"), compact=True), manager.get("profit") if manager.get("profit") is not None else -10**18),
                (
                    str(manager.get("average_points"))
                    if season_started and manager.get("average_points") is not None
                    else "–",
                    manager.get("average_points")
                    if season_started and manager.get("average_points") is not None
                    else -1,
                ),
                (
                    str(manager.get("matchday_wins"))
                    if season_started and manager.get("matchday_wins") is not None
                    else "–",
                    manager.get("matchday_wins")
                    if season_started and manager.get("matchday_wins") is not None
                    else -1,
                ),
            ]
            for col, (text, sort_value) in enumerate(specs):
                item = table_item(text, sort_value)
                item.setData(Qt.UserRole, str(manager["manager_id"]))
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col == 1 else Qt.AlignCenter)
                if is_own and col == 1:
                    item.setForeground(ORANGE)
                if col == 4:
                    set_item_delta_color(item, manager.get("profit"))
                self.league_table.setItem(row, col, item)
        self.league_table.setSortingEnabled(True)

    def _ensure_league_ownership(self, league_id: str, *, force: bool = False) -> None:
        league_id = str(league_id)
        if not force and self.storage.league_ownership_is_fresh(league_id, self.league_service.SQUAD_TTL):
            self._refresh_league_page(league_id)
            return
        if self._league_ownership_worker is not None:
            return

        managers = self.storage.league_managers(league_id)
        manager_ids = [str(manager["manager_id"]) for manager in managers]
        if not manager_ids:
            return

        self.league_ownership_status.setText("Spielerbesitz: wird im Hintergrund synchronisiert …")
        worker = FunctionWorker(lambda: self.league_service.fetch_ownership(league_id, manager_ids, force=force))
        self._league_ownership_worker = worker
        worker.signals.succeeded.connect(self._league_ownership_succeeded)
        worker.signals.failed.connect(self._league_ownership_failed)
        worker.signals.finished.connect(self._league_ownership_finished)
        QThreadPool.globalInstance().start(worker)

    def _league_ownership_succeeded(self, result: LeagueOwnershipResult) -> None:
        try:
            self.storage.replace_league_ownership(result)
            current = self.league_combo.currentData()
            if current and str(current) == result.league_id:
                self._refresh_league_page(result.league_id)
            if result.failed_manager_ids:
                self.statusBar().showMessage(
                    f"Spielerbesitz teilweise geladen · {len(result.failed_manager_ids)} Manager fehlgeschlagen",
                    7000,
                )
            else:
                self.statusBar().showMessage("Spielerbesitz der Liga aktualisiert", 5000)
        except Exception as exc:
            self._league_ownership_failed(str(exc))

    def _league_ownership_failed(self, message: str) -> None:
        current = self.league_combo.currentData()
        if current:
            covered, total = self.storage.ownership_coverage(str(current))
            self.league_ownership_status.setText(f"Spielerbesitz: {covered}/{total} Manager erfasst")
        self.statusBar().showMessage(f"Spielerbesitz konnte nicht vollständig geladen werden · {message}", 7000)

    def _league_ownership_finished(self) -> None:
        self._league_ownership_worker = None
        current = self.league_combo.currentData()
        if current:
            self._refresh_league_page(str(current))

    def _open_manager_detail(self, item: QTableWidgetItem) -> None:
        manager_id = item.data(Qt.UserRole)
        league_id = self.league_combo.currentData()
        if not manager_id or not league_id or self._manager_squad_worker is not None:
            return
        league_id = str(league_id)
        manager_id = str(manager_id)

        self._pending_manager_detail = (league_id, manager_id)
        manager = self.storage.get_league_manager(league_id, manager_id) or {}
        self.statusBar().showMessage(
            f"{manager.get('name', 'Manager')}: Kader und Transferhistorie werden geladen …"
        )
        worker = FunctionWorker(
            lambda: self.league_service.fetch_manager_detail(league_id, manager_id)
        )
        self._manager_squad_worker = worker
        worker.signals.succeeded.connect(self._manager_squad_succeeded)
        worker.signals.failed.connect(self._manager_squad_failed)
        worker.signals.finished.connect(self._manager_squad_finished)
        QThreadPool.globalInstance().start(worker)

    def _manager_squad_succeeded(self, result: ManagerDetailResult) -> None:
        try:
            squad_result = ManagerSquadResult(
                league_id=result.league_id,
                manager_id=result.manager_id,
                players=result.players,
            )
            self.storage.replace_manager_squad(squad_result)
            current = self._pending_manager_detail
            if current == (result.league_id, result.manager_id):
                dialog = ManagerDetailDialog(
                    self, self.storage, result.league_id, result.manager_id
                )
                dialog.setAttribute(Qt.WA_DeleteOnClose, True)
                self._manager_detail_windows.add(dialog)
                dialog.destroyed.connect(
                    lambda *_args, window=dialog: self._manager_detail_windows.discard(window)
                )
                dialog.show()
                dialog.raise_()
                dialog.activateWindow()
            message = f"Managerdaten geladen · {len(result.players)} Spieler · {len(result.transfers)} Transfers"
            if result.transfer_error:
                message += " · Transferhistorie nicht verfügbar"
            self.statusBar().showMessage(message, 7000)
        except Exception as exc:
            self._manager_squad_failed(str(exc))

    def _manager_squad_failed(self, message: str) -> None:
        self.statusBar().showMessage("Manager-Kader konnte nicht geladen werden", 7000)
        QMessageBox.warning(
            self,
            "Kader nicht verfügbar",
            "Kickbase hat für diesen Manager keinen lesbaren Kader geliefert.\n\n" + message,
        )

    def _manager_squad_finished(self) -> None:
        self._manager_squad_worker = None
        self._pending_manager_detail = None

    def _load_budget_overview(self, *_args) -> None:
        league_id = self.league_combo.currentData()
        league_id = str(league_id) if league_id else self.storage.get_setting("league_id")
        if not league_id or self._budget_worker is not None:
            return

        manager_id = self.storage.get_league_setting(league_id, "manager_id") or self.storage.get_setting("manager_id")
        owned_player_ids = {
            str(player.get("player_id"))
            for player in self.storage.current_players()
            if player.get("player_id") is not None
        }
        self.budget_refresh_btn.setEnabled(False)
        self.budget_status.setText("Budgetdaten werden geladen …")
        # market_overview() wraps the same budget + market API calls as
        # budget_overview(), but also normalizes every live market entry. Using
        # that full population here keeps active-bid analytics identical to the
        # Transfermarkt page instead of scoring only the handful of players we
        # currently bid on.
        worker = FunctionWorker(
            lambda: self.client.market_overview(league_id, manager_id, owned_player_ids)
        )
        self._budget_worker = worker
        worker.signals.succeeded.connect(lambda data, lid=league_id: self._budget_overview_loaded(lid, data))
        worker.signals.failed.connect(self._budget_overview_failed)
        worker.signals.finished.connect(self._budget_overview_finished)
        QThreadPool.globalInstance().start(worker)

    def _budget_overview_loaded(self, league_id: str, data: dict) -> None:
        # `/me/budget` should be authoritative. If a particular API response uses
        # an undocumented shape, fall back to the already-synced local budget.
        balance = data.get("balance")
        if balance is None:
            balance = self.storage.dashboard_metrics(league_id).get("budget")
            data["balance"] = balance
            if balance is not None:
                data["total_budget"] = balance + int(data.get("transfer_list_value") or 0)
                data["rest_budget"] = data["total_budget"] - int(data.get("committed") or 0)
                data["rest_without_sales"] = balance - int(data.get("committed") or 0)

        transfer_list_value = int(data.get("transfer_list_value") or 0)
        self.budget_details_frame.setVisible(transfer_list_value > 0)

        for key, label in self.budget_value_labels.items():
            value = data.get(key)
            label.setText(euro(value) if value is not None else "–")
            label.setStyleSheet("")
            if key in ("rest_budget", "rest_without_sales"):
                set_delta_label(label, value)
            elif key == "committed" and value is not None:
                label.setObjectName("CardWarning")
                refresh_style(label)
            else:
                label.setObjectName("CardValue")
                refresh_style(label)

        bids = [dict(bid) for bid in (data.get("active_bids") or [])]
        self._active_bid_committed = int(data.get("committed") or 0)
        if balance is not None:
            self._cash_balance = int(balance or 0)
        if getattr(self, "_portfolio_summary", None):
            self._portfolio_summary["available_budget"] = self._cash_balance
            self._portfolio_summary["committed_budget"] = self._active_bid_committed
            self._portfolio_summary["balance_after_commitments"] = self._cash_balance - self._active_bid_committed
        self._update_deadline_chip()
        if bids:
            points_are_current = data.get("points_are_current") is not False

            # Use the complete normalized live market as the scoring population.
            # This is the same basis used by the Transfermarkt page, so a player's
            # Investment-, Squad- and Max-Bid values cannot drift just because we
            # are viewing the Budgetplaner. The own bid remains a separate input
            # and is evaluated only by rate_bid() below.
            score_inputs = [dict(row) for row in (data.get("market_entries") or [])]
            if not score_inputs:
                # Defensive fallback for older/mocked client responses. Crucially,
                # never overwrite the listing price with our own bid.
                for bid in bids:
                    candidate = dict(bid)
                    candidate["price"] = int(bid.get("price") or bid.get("market_value") or 0)
                    candidate["own_bid"] = int(bid.get("bid") or 0)
                    score_inputs.append(candidate)

            for candidate in score_inputs:
                player_id = candidate.get("player_id")
                if player_id:
                    candidate.update(self.storage.analytics(str(player_id)))
            scored = enrich_market_entries(
                score_inputs,
                int(data.get("rest_without_sales") if data.get("rest_without_sales") is not None else (balance or 0)),
                self.storage.current_players(),
                points_are_current=points_are_current,
                league_transfers=self.storage.league_all_manager_transfer_rows(
                    str(league_id), since=current_season_start().isoformat()
                ),
            )
            scored_by_id = {str(row.get("player_id")): row for row in scored if row.get("player_id") is not None}
            for bid in bids:
                scored_row = scored_by_id.get(str(bid.get("player_id"))) or {}
                bid.update({
                    "squad_fit_score": scored_row.get("squad_fit_score"),
                    "investment_score": scored_row.get("investment_score"),
                    "max_bid": scored_row.get("max_bid"),
                    "minimum_bid": scored_row.get("minimum_bid") or bid.get("market_value"),
                    "confidence_label": scored_row.get("confidence_label"),
                    "investment_horizon": scored_row.get("investment_horizon"),
                })
                bid.update(rate_bid(
                    bid=int(bid.get("bid") or 0),
                    market_value=bid.get("market_value"),
                    investment_score=bid.get("investment_score"),
                    squad_fit_score=bid.get("squad_fit_score"),
                    balance=int(balance or 0) if balance is not None else None,
                    max_bid=bid.get("max_bid"),
                    minimum_bid=bid.get("minimum_bid"),
                    confidence_label=bid.get("confidence_label"),
                    investment_horizon=bid.get("investment_horizon"),
                ))
                winning = estimate_winning_price(bid.get("market_value"), getattr(self, "_league_learning", {}) or {})
                bid["league_winning_price"] = winning.get("price")
                bid["league_winning_premium_pct"] = winning.get("premium_pct")
                bid["league_winning_source"] = winning.get("source")
                bid["league_winning_sample_count"] = winning.get("sample_count")
                league_bid = evaluate_active_bid(
                    bid=bid.get("bid"),
                    max_bid=bid.get("max_bid"),
                    winning=winning,
                )
                investment_history = estimate_investment_outcome(
                    market_value=bid.get("market_value"),
                    d3=scored_row.get("d3"),
                    d7=scored_row.get("d7"),
                    learning=getattr(self, "_league_learning", {}) or {},
                )
                premium_history = evaluate_premium_outcome(
                    bid=bid.get("bid"),
                    market_value=bid.get("market_value"),
                    learning=getattr(self, "_league_learning", {}) or {},
                )
                league_bid = calibrate_bid_action(
                    league_bid, investment_outcome=investment_history, premium_outcome=premium_history
                )
                bid.update(league_bid)
                bid["historical_investment"] = investment_history
                bid["historical_premium"] = premium_history
                if winning.get("price"):
                    gap = league_bid.get("league_gap")
                    gap_text = f"{euro(abs(gap))} {'über' if gap is not None and gap >= 0 else 'unter'} Liga-Niveau" if gap is not None else ""
                    extra = (
                        f"\n\nLIGA-HISTORIE\nTypischer Zuschlag: {euro(winning['price'])} "
                        f"({winning['premium_pct']:+.1f}% · {winning['source']} · n={winning['sample_count']})\n"
                        f"Dein Gebot: {league_bid['league_chance']}"
                        + (f" · {gap_text}" if gap_text else "")
                        + f"\nAktion: {league_bid['bid_action']}"
                        + "\nHistorischer Zuschlagspreis ist Kontext und erhöht den Max-Bid nicht."
                    )
                    profile_return = investment_history.get("median_return_7d_pct")
                    premium_return = premium_history.get("median_return_7d_pct")
                    if profile_return is not None:
                        extra += (
                            f"\nMomentum-Profil {investment_history.get('profile')}: "
                            f"{profile_return:+.1f}% Median nach 7T · "
                            f"{investment_history.get('profitable_rate_7d', 0)*100:.0f}% profitabel · n={investment_history.get('sample_count', 0)}"
                        )
                    if premium_return is not None:
                        extra += (
                            f"\nPremium {premium_history.get('band')}: {premium_history.get('label')} · "
                            f"{premium_return:+.1f}% Median nach 7T · n={premium_history.get('sample_count', 0)}"
                        )
                    if league_bid.get("historical_veto_reason"):
                        extra += f"\nHistorischer Stop: {league_bid['historical_veto_reason']}"
                    bid["bid_analysis_text"] = str(bid.get("bid_analysis_text") or "") + extra
                else:
                    extra = f"\n\nLIGA-HISTORIE\n{league_bid['league_chance']} · Aktion: {league_bid['bid_action']}"
                    if investment_history.get("median_return_7d_pct") is not None:
                        extra += (f"\nMomentum-Profil {investment_history.get('profile')}: "
                                  f"{investment_history['median_return_7d_pct']:+.1f}% / 7T · n={investment_history.get('sample_count', 0)}")
                    if premium_history.get("median_return_7d_pct") is not None:
                        extra += (f"\nPremium {premium_history.get('band')}: {premium_history.get('label')} · "
                                  f"{premium_history['median_return_7d_pct']:+.1f}% / 7T · n={premium_history.get('sample_count', 0)}")
                    bid["bid_analysis_text"] = str(bid.get("bid_analysis_text") or "") + extra
        self.budget_bid_list.set_bids(bids)
        if bids:
            self.budget_status.setText(f"{len(bids)} aktiv")
        else:
            self.budget_status.setText("Keine aktiven Gebote")

        self._populate_own_listings(data.get("own_listings") or [])

    def _populate_own_listings(self, listings: list[dict]) -> None:
        if not hasattr(self, "own_listings_table"):
            return
        current_by_id = {
            str(row.get("player_id")): dict(row)
            for row in self.storage.current_players()
            if row.get("player_id") is not None
        }
        rows = []
        for source in listings:
            row = dict(source or {})
            pid = str(row.get("player_id") or "")
            local = current_by_id.get(pid) or {}
            # Keep API listing values authoritative, but enrich the display with
            # locally synced status, role and market history.
            for key in ("status", "kickbase_status", "st", "status_list", "stl", "status_text", "stxt", "player_role", "role"):
                if row.get(key) is None and local.get(key) is not None:
                    row[key] = local.get(key)
            analytics = self.storage.analytics(pid) if pid else {}
            if row.get("d1") is None:
                row["d1"] = analytics.get("d1")
            if not row.get("full_name"):
                row["full_name"] = local.get("full_name") or local.get("name") or row.get("name")
            if not row.get("club"):
                row["club"] = local.get("club") or ""
            if not row.get("position"):
                row["position"] = local.get("position") or ""
            rows.append(row)

        table = self.own_listings_table
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        total_sale = 0
        for r, player in enumerate(rows):
            pid = str(player.get("player_id") or "")
            mv = int(player.get("market_value") or 0)
            listing_price = int(player.get("listing_price") or player.get("price") or 0)
            effective = int(player.get("effective_sale_value") or max(mv, listing_price))
            total_sale += effective
            delta = effective - mv if mv else None
            role = str(player.get("player_role") or player.get("role") or "OFFEN").upper()
            full_name = str(player.get("full_name") or player.get("name") or "–")
            status_text = player_status_display(player)
            values = [
                (full_name, full_name, None),
                (player.get("club") or "–", player.get("club") or "", club_icon(player.get("club"))),
                (player.get("position") or "–", POSITION_SORT.get(player.get("position"), 99), None),
                (status_text, player_status_code(player) if player_status_code(player) is not None else -1, player_status_icon(player)),
                (euro(mv), mv, None),
                (delta_text(player.get("d1"), compact=True), int(player.get("d1") or 0), None),
                (euro(listing_price), listing_price, None),
                (euro(effective), effective, None),
                (delta_text(delta, compact=True) if delta is not None else "–", delta if delta is not None else -10**18, None),
                (ROLE_LABELS.get(role, role), ROLE_SORT.get(role, 99), None),
                ("", 0, None),
            ]
            for c, (display, sort_value, icon) in enumerate(values):
                item = table_item(display, sort_value, icon=icon)
                item.setData(Qt.UserRole, pid)
                item.setData(Qt.UserRole + 1, player)
                if c == 0:
                    item.setToolTip(player_status_tooltip(player))
                elif c == 3:
                    item.setToolTip(player_status_tooltip(player))
                elif c == 4:
                    item.setToolTip(market_value_tooltip(player))
                elif c == 5:
                    set_item_delta_color(item, player.get("d1"))
                    item.setToolTip(change_tooltip("24h Änderung", mv, player.get("d1"), exact=True))
                elif c == 6:
                    item.setToolTip("Dein aktuell gesetzter Listenpreis.")
                elif c == 7:
                    item.setForeground(QColor("#62E49A"))
                    item.setToolTip(
                        "Aktuell mindestens erzielbar, wenn der Spieler verkauft wird.\n"
                        "Kickbase verlangt mindestens den aktuellen Marktwert; liegt dein Listenpreis höher, gilt dieser."
                    )
                elif c == 8 and delta is not None:
                    set_item_delta_color(item, delta)
                    item.setToolTip(f"Aktueller Erlös minus Marktwert: {delta_text(delta)}")
                table.setItem(r, c, item)
            manage = QPushButton("VERWALTEN")
            manage.setObjectName("CompactActionButton")
            manage.setToolTip("Listenpreis ändern, vom Markt nehmen oder eingehende Angebote verwalten")
            manage.clicked.connect(lambda _checked=False, p=dict(player): self._manage_own_listing(p))
            table.setCellWidget(r, 10, manage)
        table.setSortingEnabled(True)
        table.setVisible(bool(rows))
        self.own_listings_empty.setVisible(not rows)
        if rows:
            self.own_listings_summary.setText(f"{len(rows)} SPIELER · {euro(total_sale)} ERLÖS")
            row_h = max(40, table.verticalHeader().defaultSectionSize())
            header_h = table.horizontalHeader().height() if table.horizontalHeader().isVisible() else 0
            table.setFixedHeight(header_h + len(rows) * row_h + 6)
        else:
            self.own_listings_summary.setText("KEINE ANGEBOTE")
            table.setFixedHeight(0)

    def _manage_own_listing(self, player: dict) -> None:
        league_id = str(self.league_combo.currentData() or self.storage.get_setting("league_id") or "")
        if not league_id:
            QMessageBox.warning(self, "Verkauf verwalten", "Keine aktive Liga ausgewählt.")
            return
        ListingManagementDialog(
            self, self.client, league_id, player, refresh_callback=self._refresh_after_sale_write
        ).exec()

    def _refresh_after_sale_write(self) -> None:
        # A sale write changes squad, budget and market state; refresh those explicit
        # data sources once instead of making tab navigation trigger hidden requests.
        try:
            self._load_market_overview()
        except Exception:
            pass
        try:
            self.sync()
        except Exception:
            pass

    def _open_own_listing_player_detail(self, item: QTableWidgetItem) -> None:
        player_id = item.data(Qt.UserRole)
        if not player_id:
            source = self.own_listings_table.item(item.row(), 0)
            player_id = source.data(Qt.UserRole) if source else None
        if not player_id:
            return
        league_id = self.league_combo.currentData() or self.storage.get_setting("league_id")
        self.open_player_detail_tab(str(player_id), str(league_id) if league_id else None)


    def _load_league_learning(self, *_args, force: bool = False) -> None:
        league_id = self.league_combo.currentData() or self.storage.get_setting("league_id")
        if not league_id or self._league_learning_worker is not None:
            return
        league_id = str(league_id)
        managers = self.storage.league_managers(league_id)
        if not managers:
            self.league_learning_status.setText("Managerdaten fehlen")
            return
        own_manager_id = str(self.storage.get_league_setting(league_id, "manager_id") or self.storage.get_setting("manager_id") or "")
        self.league_learning_refresh_btn.setEnabled(False)
        self.league_learning_status.setText("Historie wird rekonstruiert …")

        def load_learning():
            cutoff = current_season_start().isoformat()
            # 1) Backfill every manager's current-season transfer history. This is
            # retrospective: no need to have observed the transfer live.
            for manager in managers:
                mid = str(manager.get("manager_id") or "")
                if not mid:
                    continue
                fresh = self.storage.league_manager_transfers_are_fresh(league_id, mid, 6 * 3600)
                if force or not fresh:
                    try:
                        raw = self.client.manager_transfers(league_id, mid)
                        transfers = self.client.parse_manager_transfers(raw)
                        current = [row for row in transfers if str(row.get("transferred_at") or "")[:10] >= cutoff]
                        self.storage.upsert_league_manager_transfers(league_id, mid, current)
                    except Exception:
                        continue

            rows = self.storage.league_all_manager_transfer_rows(league_id, since=cutoff)
            external_buys = [
                row for row in rows
                if str(row.get("transfer_type") or "").upper() == "BUY"
                and str(row.get("manager_id") or "") != own_manager_id
            ]
            # 2) Pull historical MV series for every externally bought player.
            # Cache responses for 12h; SQLite then keeps the points permanently.
            for player_id in sorted({str(row.get("player_id") or "") for row in external_buys if row.get("player_id")}):
                cache_key = f"league_learning:mv365:{league_id}:{player_id}"
                payload = None if force else self.storage.cache_get(cache_key, 12 * 3600)
                if not isinstance(payload, dict):
                    try:
                        payload = self.client.market_value_history(league_id, player_id, 365)
                        self.storage.cache_set(cache_key, payload)
                    except Exception:
                        payload = None
                if isinstance(payload, dict):
                    self.storage.upsert_market_value_history(player_id, normalize_market_value_history(payload))

            histories = {
                pid: self.storage.all_history(pid)
                for pid in {str(row.get("player_id") or "") for row in external_buys if row.get("player_id")}
            }
            names = {str(m.get("manager_id") or ""): str(m.get("name") or "Manager") for m in managers}
            return build_league_purchase_learning(
                rows, own_manager_id=own_manager_id, manager_names=names, histories=histories
            )

        worker = FunctionWorker(load_learning)
        self._league_learning_worker = worker
        worker.signals.succeeded.connect(self._league_learning_loaded)
        worker.signals.failed.connect(self._league_learning_failed)
        worker.signals.finished.connect(self._league_learning_finished)
        QThreadPool.globalInstance().start(worker)

    def _league_learning_loaded(self, learning: dict) -> None:
        self._league_learning = dict(learning or {})
        buys = list(self._league_learning.get("buys") or [])
        premium = self._league_learning.get("median_premium_pct")
        outcome3 = self._league_learning.get("median_buyer_return_7d_pct")
        premium_n = int(self._league_learning.get("premium_sample_count") or 0)
        outcome_n = int(self._league_learning.get("outcome_7d_count") or 0)
        profitable_band = self._league_learning.get("profitable_premium_band")

        self.league_learning_cards["buys"].value_label.setText(str(int(self._league_learning.get("external_buy_count") or 0)))
        self.league_learning_cards["premium"].value_label.setText(f"{premium:+.1f}%" if premium is not None else "–")
        self.league_learning_cards["premium"].hint_label.setText(f"historischer MW verfügbar · n={premium_n}")
        self.league_learning_cards["outcome3"].value_label.setText(f"{outcome3:+.1f}%" if outcome3 is not None else "–")
        self.league_learning_cards["outcome3"].hint_label.setText(f"Kaufpreis → MW nach 7T · n={outcome_n}")
        self.league_learning_cards["sample"].value_label.setText(str(profitable_band or "–"))
        self.league_learning_cards["sample"].hint_label.setText(f"7T Outcome · Datenbasis {premium_n}/{len(buys)}")

        self.league_learning_table.setSortingEnabled(False)
        visible = buys[:12]
        self.league_learning_table.setRowCount(len(visible))
        for r, row in enumerate(visible):
            premium_value = row.get("premium_pct")
            return3 = row.get("buyer_return_3d_pct")
            specs = [
                (display_date(row.get("transferred_at")), str(row.get("transferred_at") or "")),
                (str(row.get("player_name") or "–"), str(row.get("player_name") or "")),
                (str(row.get("manager_name") or "–"), str(row.get("manager_name") or "")),
                (euro(row.get("price")), int(row.get("price") or 0)),
                (euro(row.get("market_value_at_transfer")) if row.get("market_value_at_transfer") else "–", int(row.get("market_value_at_transfer") or 0)),
                (f"{premium_value:+.1f}%" if premium_value is not None else "–", premium_value if premium_value is not None else -999),
                (f"{return3:+.1f}%" if return3 is not None else "–", return3 if return3 is not None else -999),
            ]
            for c, (text, sort_value) in enumerate(specs):
                item = table_item(text, sort_value)
                if c in (5, 6):
                    value = premium_value if c == 5 else return3
                    if value is not None:
                        item.setForeground(GREEN if (value <= 0 if c == 5 else value >= 0) else RED)
                self.league_learning_table.setItem(r, c, item)
        self.league_learning_table.setSortingEnabled(True)
        self._fit_table_height(self.league_learning_table, len(visible), min_rows=4, max_rows=8)
        self.league_learning_status.setText(f"{len(buys)} fremde Käufe gelernt")
        self._update_market_detail()
        # Re-evaluate active-bid tooltip context immediately with the new league model.
        if getattr(self, "_budget_worker", None) is None:
            QTimer.singleShot(0, self._load_budget_overview)

    def _league_learning_failed(self, message: str) -> None:
        self.league_learning_status.setText("Lernmodell nicht verfügbar")
        self.statusBar().showMessage("Liga-Lernmodell: " + message.splitlines()[0], 7000)

    def _league_learning_finished(self) -> None:
        self._league_learning_worker = None
        self.league_learning_refresh_btn.setEnabled(True)

    def _open_budget_bid_player_detail(self, player: dict) -> None:
        if not player or not player.get("player_id"):
            return
        league_id = self.league_combo.currentData() or self.storage.get_setting("league_id")
        self.open_player_detail_tab(str(player["player_id"]), str(league_id) if league_id else None, player)

    def _open_transfer_player_detail(self, item: QTableWidgetItem) -> None:
        player_id = str(item.data(Qt.UserRole) or "")
        if not player_id:
            return
        league_id = self.league_combo.currentData() or self.storage.get_setting("league_id")
        rows = self.storage.transfer_rows(str(league_id)) if league_id else self.storage.transfer_rows(None)
        transfer = next((row for row in rows if str(row.get("player_id") or "") == player_id), None)
        player_data = None
        if transfer:
            player_data = {
                "player_id": player_id,
                "name": transfer.get("player_name") or "Spieler",
                "club": transfer.get("club") or "",
                "team_id": transfer.get("team_id"),
            }
        self.open_player_detail_tab(player_id, str(league_id) if league_id else None, player_data)

    def _budget_overview_failed(self, message: str) -> None:
        self.budget_status.setText("Budgetdaten konnten nicht automatisch geladen werden")
        self.statusBar().showMessage("Budgetplaner: " + message.splitlines()[0], 7000)

    def _budget_overview_finished(self) -> None:
        self._budget_worker = None
        self.budget_refresh_btn.setEnabled(True)

    def _schedule_own_transfer_history_backfill(self, league_id: str | None, rows: list[dict]) -> None:
        """Backfill MV histories for own sold players without blocking the UI."""
        if not league_id or not rows or getattr(self, "_own_trade_history_backfill_running", False):
            return

        sold_ids = sorted({
            str(row.get("player_id") or "")
            for row in rows
            if str(row.get("transfer_type") or "").upper() == "SELL" and row.get("player_id")
        })
        if not sold_ids:
            return

        pending: list[str] = []
        # Cached payloads may stem from an earlier run/version. Persist them now
        # immediately; only truly missing/stale payloads need a network request.
        for player_id in sold_ids:
            cache_key = f"own_trade:mv365:{league_id}:{player_id}"
            cached = self.storage.cache_get(cache_key, 12 * 3600)
            if isinstance(cached, dict):
                if not cached.get("_failed"):
                    normalized = normalize_market_value_history(cached)
                    if normalized:
                        self.storage.upsert_market_value_history(player_id, normalized)
                continue
            pending.append(player_id)

        if not pending:
            return

        self._own_trade_history_backfill_running = True

        def load_histories():
            written = 0
            for player_id in pending:
                cache_key = f"own_trade:mv365:{league_id}:{player_id}"
                try:
                    payload = self.client.market_value_history(str(league_id), player_id, 365)
                    normalized = normalize_market_value_history(payload)
                    if normalized:
                        written += self.storage.upsert_market_value_history(player_id, normalized)
                    self.storage.cache_set(cache_key, payload if isinstance(payload, dict) else {"it": payload})
                except Exception as exc:
                    # Avoid hammering a permanently unavailable player on every
                    # page refresh. A failed marker expires through cache_get after 12h.
                    self.storage.cache_set(cache_key, {"_failed": True, "error": str(exc)})
            return written

        worker = FunctionWorker(load_histories)
        self._own_trade_history_backfill_worker = worker

        def finished():
            self._own_trade_history_backfill_running = False
            # Re-render from the newly persisted history. At this point cache keys
            # are fresh, so this cannot recursively start another backfill loop.
            QTimer.singleShot(0, lambda: self._refresh_transfers(str(league_id)))

        worker.signals.finished.connect(finished)
        QThreadPool.globalInstance().start(worker)

    def _refresh_transfers(self, league_id: str | None) -> None:
        metrics = self.storage.dashboard_metrics(league_id)
        self.transfer_realized.value_label.setText(delta_text(metrics["realized_pnl"]))
        set_delta_label(self.transfer_realized.value_label, metrics["realized_pnl"])
        self.transfer_buys.value_label.setText(str(metrics["buy_count"]))
        self.transfer_buys.hint_label.setText(f"Volumen {euro(metrics['buy_volume'])}")
        self.transfer_sells.value_label.setText(str(metrics["sell_count"]))
        self.transfer_sells.hint_label.setText(f"Volumen {euro(metrics['sell_volume'])}")
        self.transfer_total.value_label.setText(str(metrics["total_count"]))
        self.transfer_total.hint_label.setText("gespeicherte Vorgänge")

        rows = self.storage.transfer_rows(league_id)
        if not rows and league_id:
            rows = self.storage.transfer_rows(None)

        # Sold players often leave the current squad before we have accumulated
        # enough daily snapshots for a +3T/+7T exit grade. Backfill their official
        # 365-day Kickbase MW history in the background and refresh this page once
        # it is persisted. Cached histories prevent repeated API traffic.
        self._schedule_own_transfer_history_backfill(league_id, rows)

        history_by_player: dict[str, list[dict]] = defaultdict(list)
        for mv in self.storage.all_market_value_rows():
            history_by_player[str(mv.get("player_id") or "")].append(mv)

        # Use already persisted/cached performance data when available. We do
        # not fire dozens of extra API calls just to grade old trades. During
        # preseason this intentionally remains "noch keine Daten".
        performance_by_player: dict[str, dict] = {}
        if league_id:
            for player_id in {str(row.get("player_id") or "") for row in rows if row.get("player_id")}:
                cached = self.storage.cache_get(f"player_performance:{league_id}:{player_id}")
                if isinstance(cached, dict):
                    performance_by_player[player_id] = cached

        acquisition_by_player: dict[str, dict] = {}
        # Current squad players are required as well: start-squad holdings may
        # never have a BUY event, but are still live positions that should be
        # evaluated from their start MW to today's MW.
        current_squad = self.storage.current_players()
        for stored_player in current_squad:
            player_id = str(stored_player.get("player_id") or "")
            if player_id:
                acquisition_by_player[player_id] = stored_player
        for player_id in {str(row.get("player_id") or "") for row in rows if row.get("player_id")}:
            if player_id in acquisition_by_player:
                continue
            stored_player = self.storage.get_player(player_id)
            if isinstance(stored_player, dict):
                acquisition_by_player[player_id] = stored_player

        # Reuse cached performance for live current holdings, too.
        if league_id:
            for player_id in acquisition_by_player:
                if player_id in performance_by_player:
                    continue
                cached = self.storage.cache_get(f"player_performance:{league_id}:{player_id}")
                if isinstance(cached, dict):
                    performance_by_player[player_id] = cached

        trade_rows = evaluate_trade_cycles(rows, history_by_player, performance_by_player, acquisition_by_player)
        summary = transfer_evaluation_summary(trade_rows)

        if hasattr(self, "transfer_cards_visual_layout"):
            while self.transfer_cards_visual_layout.count():
                item = self.transfer_cards_visual_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            if not trade_rows:
                empty = QLabel("Noch keine Trade-Zyklen vorhanden.")
                empty.setObjectName("Tiny")
                self.transfer_cards_visual_layout.addWidget(empty)
            else:
                for trade in trade_rows[:5]:
                    card = TradeCycleCard()
                    pid = str(trade.get("player_id") or "")
                    card.set_trade(trade, self.storage.portrait_path(pid))
                    card.playerActivated.connect(
                        lambda player_id: self.open_player_detail_tab(
                            str(player_id),
                            str(self.league_combo.currentData() or self.storage.get_setting("league_id") or ""),
                        )
                    )
                    self.transfer_cards_visual_layout.addWidget(card)

        if hasattr(self, "transfer_eval_cards"):
            self.transfer_eval_cards["evaluated"].value_label.setText(str(summary["evaluated_trades"]))
            avg_roi = summary.get("avg_realized_roi_pct")
            self.transfer_eval_cards["roi"].value_label.setText(f"{avg_roi:+.1f} %" if avg_roi is not None else "–")
            if avg_roi is not None:
                set_delta_label(self.transfer_eval_cards["roi"].value_label, avg_roi)
            self.transfer_eval_cards["good_exits"].value_label.setText(str(summary["good_exits"]))
            self.transfer_eval_cards["early_exits"].value_label.setText(str(summary["early_exits"]))
            self.transfer_eval_cards["evaluated"].hint_label.setText(
                f"{summary['open_trades']} offen · {summary['timed_sales']} mit Exit-Timing"
            )

        self.transfer_table.setSortingEnabled(False)
        self.transfer_table.setRowCount(len(trade_rows))
        self._fit_table_height(self.transfer_table, len(trade_rows), min_rows=4)

        def verdict_color(verdict: str):
            verdict = str(verdict or "").upper()
            if any(token in verdict for token in ("TOP", "STARK", "GUTER", "GUTES")):
                return GREEN
            if any(token in verdict for token in ("FEHL", "VERLUST", "ZU FRÜH")):
                return RED
            if any(token in verdict for token in ("SCHWACH", "OFFEN")):
                return ORANGE
            return WHITE

        def compact_trade_verdict(verdict: str) -> str:
            """Short table label; the complete verdict remains available via tooltip."""
            value = str(verdict or "NICHT BEWERTBAR").upper().strip()
            labels = {
                "LIVE · STAMM": "STAMM",
                "LIVE · INVEST": "INVEST",
                "LIVE · VERKAUF GEPLANT": "VERKAUF",
                "OFFENER TRADE": "OFFEN",
                "TOP-TRADE": "TOP",
                "STARKER TRADE": "TRADE+",
                "GUTER TRADE": "GUT",
                "SOLIDER TRADE": "SOLIDE",
                "VERLUST-TRADE": "VERLUST",
                "SCHWACHER TRADE": "SCHWACH",
                "FEHLKAUF": "FEHLKAUF",
                "SPORTLICH GUTER TRADE": "SPORT+",
                "NICHT BEWERTBAR": "–",
            }
            if value in labels:
                return labels[value]
            if value.startswith("LIVE · "):
                value = value.removeprefix("LIVE · ")
            return value[:12] + ("…" if len(value) > 12 else "")

        def short_date(value) -> str:
            text = display_date(value) if value else "–"
            # The table needs only the date; exact timestamps remain in tooltip.
            return text.split(" ")[0] if text else "–"

        def post_text(value, delta, pct) -> str:
            if value is None:
                return "–"
            if delta is None or pct is None:
                return euro(value)
            return f"{delta_text(delta, compact=True)} · {float(pct):+.1f}%"

        for row_index, trade in enumerate(trade_rows):
            cycle_type = str(trade.get("cycle_type") or "")
            buy_date = trade.get("buy_date")
            sell_date = trade.get("sell_date")
            holding_days = trade.get("holding_days")
            if cycle_type == "OPEN_TRADE":
                period_text = f"{short_date(buy_date)} → HEUTE"
            elif cycle_type == "OPEN_START_SQUAD":
                period_text = "START → HEUTE"
            elif buy_date and sell_date:
                if cycle_type == "CLOSED_START_SQUAD_TRADE":
                    period_text = f"START → {short_date(sell_date)}"
                else:
                    period_text = f"{short_date(buy_date)} → {short_date(sell_date)}"
            else:
                period_text = f"? → {short_date(sell_date)}"
            if holding_days is not None and buy_date:
                period_text += f" · {int(holding_days)}T"

            result_pnl = trade.get("result_pnl")
            roi = trade.get("roi_pct")
            result_text = delta_text(result_pnl, compact=True) if result_pnl is not None else "–"
            roi_text = f"{float(roi):+.1f} %" if roi is not None else "–"

            if cycle_type in {"OPEN_TRADE", "OPEN_START_SQUAD"}:
                end_value = trade.get("current_market_value")
                end_text = euro(end_value) if end_value else "–"
            else:
                end_value = trade.get("sell_price")
                end_text = euro(end_value) if end_value else "–"

            sport_points = trade.get("sport_points")
            sport_games = int(trade.get("sport_games") or 0)
            sport_avg = trade.get("sport_avg")
            if sport_points is None:
                sport_text = "Noch keine Sportdaten" if self._season_mode_active() else "Preseason / –"
            elif sport_games:
                sport_text = f"{int(sport_points)} P · Ø {float(sport_avg):.0f}"
            else:
                sport_text = f"{int(sport_points)} P"

            p3_text = post_text(trade.get("post_3d_value"), trade.get("post_3d_delta"), trade.get("post_3d_pct"))
            p7_text = post_text(trade.get("post_7d_value"), trade.get("post_7d_delta"), trade.get("post_7d_pct"))
            exit_verdict = str(trade.get("exit_verdict") or "–")
            verdict = str(trade.get("verdict") or "NICHT BEWERTBAR")

            specs = [
                (period_text, trade.get("sort_date") or ""),
                (trade.get("player_name") or "–", trade.get("player_name") or ""),
                (trade.get("club") or "–", trade.get("club") or "", club_icon(trade.get("club"))),
                (("Start-MW " + euro(trade.get("buy_price"))) if cycle_type in {"CLOSED_START_SQUAD_TRADE", "OPEN_START_SQUAD"} and trade.get("buy_price") else (euro(trade.get("buy_price")) if trade.get("buy_price") else "–"), trade.get("buy_price") or -1),
                (end_text, end_value or -1),
                (result_text, result_pnl if result_pnl is not None else -10**18),
                (roi_text, float(roi) if roi is not None else -10**18),
                (sport_text, float(sport_avg) if sport_avg is not None else -10**18),
                (p3_text, float(trade.get("post_3d_pct")) if trade.get("post_3d_pct") is not None else -10**18),
                (p7_text, float(trade.get("post_7d_pct")) if trade.get("post_7d_pct") is not None else -10**18),
                (exit_verdict, exit_verdict),
                (compact_trade_verdict(verdict), verdict),
            ]
            for col, spec in enumerate(specs):
                text_value, sort_value = spec[0], spec[1]
                icon = spec[2] if len(spec) > 2 else None
                item = table_item(text_value, sort_value, icon=icon)
                item.setData(Qt.UserRole, str(trade.get("player_id") or ""))
                if col == 1:
                    portrait_path = self.storage.portrait_path(str(trade.get("player_id") or ""))
                    item.setIcon(QIcon(portrait_path))
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col in (0, 1, 2) else Qt.AlignCenter)
                if col == 5 and result_pnl is not None:
                    item.setForeground(GREEN if result_pnl > 0 else RED if result_pnl < 0 else WHITE)
                elif col == 6 and roi is not None:
                    item.setForeground(GREEN if roi > 0 else RED if roi < 0 else WHITE)
                elif col in (8, 9):
                    timing_pct = trade.get("post_3d_pct") if col == 8 else trade.get("post_7d_pct")
                    if timing_pct is not None:
                        # Falling after our sale means the exit timing was good.
                        item.setForeground(GREEN if float(timing_pct) < 0 else RED if float(timing_pct) > 0 else WHITE)
                elif col == 10:
                    item.setForeground(verdict_color(exit_verdict))
                elif col == 11:
                    item.setForeground(verdict_color(verdict))

                if col == 11:
                    details = [f"Bewertung: {verdict}"]
                    if trade.get("buy_date"):
                        details.append(f"Kauf: {display_date(trade.get('buy_date'))} · {euro(trade.get('buy_price'))}")
                    if trade.get("sell_date"):
                        details.append(f"Verkauf: {display_date(trade.get('sell_date'))} · {euro(trade.get('sell_price'))}")
                    elif trade.get("current_market_value"):
                        details.append(f"Aktueller MW: {euro(trade.get('current_market_value'))}")
                    if result_pnl is not None:
                        details.append(f"Finanziell: {delta_text(result_pnl)} ({roi_text}) · {trade.get('financial_verdict')}")
                    details.append(f"Sport: {trade.get('sport_verdict') or 'NOCH KEINE DATEN'}")
                    if trade.get("post_3d_value") is not None:
                        details.append(f"MW +3T: {euro(trade.get('post_3d_value'))} · {float(trade.get('post_3d_pct')):+.1f}%")
                    if trade.get("post_7d_value") is not None:
                        details.append(f"MW +7T: {euro(trade.get('post_7d_value'))} · {float(trade.get('post_7d_pct')):+.1f}%")
                    if cycle_type == "UNPAIRED_SALE":
                        details.append("Kein eigener Kauf beobachtet: Kaufpreis/ROI werden bewusst nicht erfunden.")
                    item.setToolTip("\n".join(details))
                self.transfer_table.setItem(row_index, col, item)
        self.transfer_table.setSortingEnabled(True)

        self._set_transfer_volume_chart(self.transfers_chart.chart_view, rows[:12])

        if league_id:
            self._load_budget_overview()
            self._load_league_learning(force=False)

    def _refresh_analysis(self) -> None:
        players = self._player_metrics()
        assigned = [p for p in players if (p.get("player_role") or "OFFEN") != "OFFEN"]
        ranked = sorted(
            [player for player in players if player["pnl"] is not None],
            key=lambda p: p["pnl"],
            reverse=True,
        )

        def role_summary(role: str):
            group = [p for p in players if (p.get("player_role") or "OFFEN") == role]
            pnl = sum((p.get("pnl") or 0) for p in group)
            d1 = sum((p.get("d1") or 0) for p in group)
            return group, pnl, d1

        invest, invest_pnl, invest_d1 = role_summary("INVEST")
        transfer, transfer_pnl, transfer_d1 = role_summary("TRANSFERLISTE")
        stamm, stamm_pnl, stamm_d1 = role_summary("STAMM")
        offen, _, _ = role_summary("OFFEN")

        for card, group, pnl, d1 in (
            (self.analysis_invest, invest, invest_pnl, invest_d1),
            (self.analysis_transfer, transfer, transfer_pnl, transfer_d1),
            (self.analysis_stamm, stamm, stamm_pnl, stamm_d1),
        ):
            card.value_label.setText(str(len(group)))
            card.hint_label.setText(f"P/L {delta_text(pnl, compact=True)} · 24h {delta_text(d1, compact=True)}")
        self.analysis_open.value_label.setText(str(len(offen)))
        self.analysis_open.hint_label.setText("Rolle im Kader auswählen")

        role_groups = {
            "INVEST": invest,
            "TRANSFERLISTE": transfer,
            "STAMM": stamm,
        }
        for role, group in role_groups.items():
            ordered = sorted(
                group,
                key=lambda p: (p.get("pnl") is not None, p.get("pnl") or -10**18),
                reverse=True,
            )
            pnl_total = sum((p.get("pnl") or 0) for p in group)
            d1_total = sum((p.get("d1") or 0) for p in group)
            summary = self.analysis_role_summary_labels.get(role)
            if summary is not None:
                summary.setText(
                    f"{len(group)} Spieler · P/L {delta_text(pnl_total, compact=True)} · 24h {delta_text(d1_total, compact=True)}"
                )
            preview = self.analysis_role_preview_labels.get(role)
            if preview is not None:
                if ordered:
                    lines = []
                    for player in ordered[:3]:
                        pnl_text = delta_text(player.get("pnl"), compact=True) if player.get("pnl") is not None else "–"
                        lines.append(f"{player.get('name') or '–'}  ·  {pnl_text}")
                    if len(ordered) > 3:
                        lines.append(f"+ {len(ordered) - 3} weitere")
                    preview.setText("\n".join(lines))
                else:
                    preview.setText("Keine Spieler in dieser Rolle")

        analysis_labels = [p["name"] for p in ranked[:8]]
        analysis_values = [p["pnl"] or 0 for p in ranked[:8]]
        self._set_positive_negative_bar_chart(
            self.analysis_chart.chart_view,
            analysis_labels,
            analysis_values,
            positive_name="Plus",
            negative_name="Minus",
            subtitle="Aktueller Kader P/L in Mio. €",
        )

    def _player_metrics(self) -> list[dict]:
        result: list[dict] = []
        for player in self.storage.current_players():
            analytics = self.storage.analytics(player["player_id"])
            market_value = int(player.get("market_value") or 0)
            entry = player.get("entry_value")
            pnl = market_value - int(entry) if entry is not None else None
            roi = (pnl / int(entry) * 100.0) if pnl is not None and entry else None
            result.append(
                {
                    **player,
                    "market_value": market_value,
                    "entry_value": entry,
                    "pnl": pnl,
                    "roi": roi,
                    "d1": analytics.get("d1"),
                    "d3": analytics.get("d3"),
                    "d7": analytics.get("d7"),
                    "d14": analytics.get("d14"),
                    "trend_velocity_3d": analytics.get("trend_velocity_3d"),
                    "trend_velocity_7d": analytics.get("trend_velocity_7d"),
                    "trend_acceleration": analytics.get("trend_acceleration"),
                }
            )
        return result

    # ------------------------------------------------------------------
    # Chart helpers
    # ------------------------------------------------------------------

    def _base_chart(self, empty_text: str | None = None) -> QChart:
        chart = QChart()
        chart.setBackgroundVisible(False)
        chart.setPlotAreaBackgroundVisible(False)
        chart.setDropShadowEnabled(False)
        chart.legend().setVisible(True)
        chart.legend().setLabelColor(QColor("#C4CBD2"))
        chart.legend().setFont(QFont(body_font_family(), 10))
        chart.legend().setAlignment(Qt.AlignTop)
        chart.setMargins(QMargins(2, 2, 2, 0))
        if empty_text:
            chart.setTitle(empty_text)
            chart.setTitleBrush(QColor("#C1C8CF"))
            chart.setTitleFont(QFont(body_font_family(), 11, QFont.DemiBold))
        return chart

    @staticmethod
    def _style_chart_axis(axis, *, grid: bool = True) -> None:
        axis.setLabelsColor(QColor("#A2ACB6"))
        axis.setLabelsFont(QFont(body_font_family(), 9))
        axis.setLineVisible(False)
        axis.setGridLineVisible(grid)
        if grid:
            axis.setGridLineColor(QColor("#20272D"))
        try:
            axis.setMinorGridLineVisible(False)
        except AttributeError:
            pass

    def _set_empty_chart(self, view: QChartView, message: str) -> None:
        chart = self._base_chart(message)
        view.setChart(chart)

    def _set_team_value_history_chart(self, view: QChartView, rows: list[dict]) -> None:
        if not rows:
            self._set_empty_chart(view, "Noch keine Kaderwert-Historie")
            return

        series = QLineSeries()
        series.setName("Kaderwert")
        pen = QPen(ORANGE)
        pen.setWidth(2)
        series.setPen(pen)
        timestamps: list[int] = []
        values: list[int] = []
        for row in rows:
            dt = QDateTime.fromString(str(row.get("snapshot_date") or ""), "yyyy-MM-dd")
            if not dt.isValid():
                continue
            value = int(row.get("team_value") or 0)
            stamp = dt.toMSecsSinceEpoch()
            timestamps.append(stamp)
            values.append(value)
            series.append(stamp, value / 1_000_000)
        if not timestamps:
            self._set_empty_chart(view, "Noch keine Kaderwert-Historie")
            return
        series.setPointsVisible(len(timestamps) <= 10)
        series.setMarkerSize(10)

        chart = self._base_chart()
        chart.legend().setVisible(False)
        chart.addSeries(series)
        axis_x = QDateTimeAxis()
        axis_x.setFormat("dd.MM")
        self._style_chart_axis(axis_x, grid=False)
        axis_x.setTickCount(min(6, max(2, len(timestamps))))
        first_x, last_x = min(timestamps), max(timestamps)
        if first_x == last_x:
            first_x -= 12 * 60 * 60 * 1000
            last_x += 12 * 60 * 60 * 1000
        axis_x.setRange(QDateTime.fromMSecsSinceEpoch(first_x), QDateTime.fromMSecsSinceEpoch(last_x))
        axis_y = QValueAxis()
        low, high = min(values) / 1_000_000, max(values) / 1_000_000
        span = high - low
        padding = max(0.1, span * 0.2, high * 0.003)
        axis_y.setRange(max(0, low - padding), high + padding)
        axis_y.setLabelFormat("%.2f M" if span < 1 else "%.1f M")
        axis_y.setTickCount(4)
        self._style_chart_axis(axis_y, grid=True)
        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)

        history_popover = chart_hover_popover(view)

        def tooltip(point, state: bool) -> None:
            if state:
                dt = QDateTime.fromMSecsSinceEpoch(int(point.x()))
                history_popover.show_value(
                    f"{dt.toString('dd.MM.yyyy')}\n{euro(int(point.y() * 1_000_000))}",
                    QCursor.pos(),
                )
            else:
                history_popover.hide_later()
        series.hovered.connect(tooltip)
        view.setChart(chart)

    def _set_position_allocation_chart(self, view: QChartView, players: list[dict]) -> None:
        totals = {position: 0 for position in ("TW", "ABW", "MF", "ST")}
        for player in players:
            position = str(player.get("position") or "")
            if position in totals:
                totals[position] += int(player.get("market_value") or 0)

        panel = view.parentWidget()
        footer = getattr(panel, "footer", None)
        footer_grid = getattr(panel, "footer_grid", None)

        def clear_footer() -> None:
            if footer_grid is None:
                return
            while footer_grid.count():
                item = footer_grid.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            if footer is not None:
                footer.hide()

        clear_footer()

        if not any(totals.values()):
            self._set_empty_chart(view, "Noch keine Kaderdaten")
            return

        chart = self._base_chart()
        chart.setMargins(QMargins(8, 2, 8, 2))
        pie = QPieSeries()
        labels = {"TW": "Tor", "ABW": "Abwehr", "MF": "Mittelfeld", "ST": "Sturm"}
        colors = {
            "TW": QColor("#7C8CFF"),
            "ABW": QColor("#25B8A6"),
            "MF": ORANGE,
            "ST": QColor("#E7B64A"),
        }

        for position in ("TW", "ABW", "MF", "ST"):
            value = totals[position]
            if value <= 0:
                continue
            slice_ = pie.append(labels[position], value / 1_000_000)
            slice_.setColor(colors[position])
            slice_.setLabelVisible(False)
            slice_.hovered.connect(
                lambda state, pos=position, amount=value: QToolTip.showText(
                    QCursor.pos(), f"{labels[pos]}\n{euro(amount)}", view
                ) if state else QToolTip.hideText()
            )

        # Keep the donut itself deliberately simple. The legend below is made
        # from normal Qt widgets so values never get shortened to an ellipsis.
        pie.setHoleSize(0.54)
        pie.setPieSize(0.66)
        pie.setHorizontalPosition(0.50)
        pie.setVerticalPosition(0.50)
        chart.addSeries(pie)
        chart.legend().setVisible(False)
        view.setChart(chart)

        if footer_grid is not None and footer is not None:
            active = [(pos, totals[pos]) for pos in ("TW", "ABW", "MF", "ST") if totals[pos] > 0]
            for index, (position, value) in enumerate(active):
                item = QWidget()
                item.setObjectName("AllocationLegendItem")
                item.setAttribute(Qt.WA_StyledBackground, True)
                item.setStyleSheet("background: transparent; border: none;")
                row = QHBoxLayout(item)
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(7)

                marker = QFrame()
                marker.setFixedSize(9, 9)
                marker.setStyleSheet(
                    f"background-color: {colors[position].name()}; "
                    "border: 1px solid rgba(255,255,255,55); border-radius: 2px;"
                )
                text = QLabel(f"{labels[position]} · {value / 1_000_000:.1f} M")
                text.setObjectName("ChartLegendText")
                text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                text.setMinimumWidth(0)
                text.setToolTip(f"{labels[position]}: {euro(value)}")

                row.addWidget(marker, 0, Qt.AlignVCenter)
                row.addWidget(text, 1)

                footer_grid.addWidget(item, index // 2, index % 2)

            footer_grid.setColumnStretch(0, 1)
            footer_grid.setColumnStretch(1, 1)
            footer.show()

    def _set_league_value_summary(self, managers: list[dict]) -> None:
        panel = self.league_value_summary
        ranked = [m for m in managers if int(m.get("team_value") or 0) > 0]
        ranked.sort(key=lambda m: int(m.get("team_value") or 0), reverse=True)

        if not ranked:
            for metric in (panel.leader, panel.own, panel.gap):
                metric[1].setText("–")
                metric[2].setText("")
            return

        leader = ranked[0]
        leader_value = int(leader.get("team_value") or 0)
        panel.leader[1].setText(euro(leader_value))
        panel.leader[2].setText(str(leader.get("name") or "Manager"))

        league_id = self.league_combo.currentData()
        own_id = self.storage.get_league_setting(str(league_id), "manager_id") if league_id else None
        own = next((m for m in ranked if str(m.get("manager_id")) == str(own_id)), None)
        if own is None:
            panel.own[1].setText("–")
            panel.own[2].setText("nicht ermittelt")
            panel.gap[1].setText("–")
            panel.gap[2].setText("")
            return

        own_value = int(own.get("team_value") or 0)
        own_rank = ranked.index(own) + 1
        panel.own[1].setText(euro(own_value))
        panel.own[2].setText(f"Platz {own_rank} von {len(ranked)} nach Kaderwert")

        gap = max(0, leader_value - own_value)
        if gap == 0:
            panel.gap[1].setText("0 €")
            panel.gap[2].setText("Du hast den höchsten Kaderwert")
        else:
            panel.gap[1].setText(euro(gap))
            panel.gap[2].setText(f"bis {leader.get('name') or 'zur Spitze'}")

    def _set_positive_negative_bar_chart(
        self,
        view: QChartView,
        labels: list[str],
        values: list[int],
        *,
        positive_name: str,
        negative_name: str,
        subtitle: str = "",
    ) -> None:
        if not labels:
            self._set_empty_chart(view, "Noch keine Daten")
            return

        chart = self._base_chart()
        pos = QBarSet(positive_name)
        neg = QBarSet(negative_name)
        pos.setColor(GREEN)
        neg.setColor(RED)
        pos.setBorderColor(GREEN)
        neg.setBorderColor(RED)

        scaled_max = 0.0
        for value in values:
            million = value / 1_000_000
            pos_val = max(million, 0)
            neg_val = min(million, 0)
            pos.append(pos_val)
            neg.append(neg_val)
            scaled_max = max(scaled_max, abs(million))

        series = QBarSeries()
        series.setBarWidth(0.48)
        series.append(pos)
        series.append(neg)

        bar_popover = chart_hover_popover(view)

        def bar_tooltip(state: bool, index: int, *, kind: str) -> None:
            if not state or index < 0 or index >= len(labels):
                bar_popover.hide_later()
                return
            raw_value = int(values[index])
            if kind == "positive" and raw_value <= 0:
                bar_popover.hide_later()
                return
            if kind == "negative" and raw_value >= 0:
                bar_popover.hide_later()
                return
            bar_popover.show_value(
                f"{labels[index]}\n{euro(raw_value)}",
                QCursor.pos(),
            )

        pos.hovered.connect(lambda state, index: bar_tooltip(state, index, kind="positive"))
        neg.hovered.connect(lambda state, index: bar_tooltip(state, index, kind="negative"))
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(labels)
        self._style_chart_axis(axis_x, grid=False)
        chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        self._style_chart_axis(axis_y, grid=True)
        axis_y.setLabelFormat("%.1f")
        axis_y.setRange(-max(0.5, scaled_max * 1.2), max(0.5, scaled_max * 1.2))
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)

        view.setChart(chart)

    def _set_transfer_volume_chart(self, view: QChartView, rows: list[dict]) -> None:
        if not rows:
            self._set_empty_chart(view, "Noch keine Transferdaten")
            return

        rows = sorted(rows, key=lambda x: x.get("transferred_at") or "")
        grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"BUY": 0, "SELL": 0})
        for row in rows:
            label = short_date(row.get("transferred_at"))
            grouped[label][row.get("transfer_type") or "BUY"] += int(row.get("price") or 0)

        labels = list(grouped.keys())[-8:]
        buy_set = QBarSet("Käufe")
        sell_set = QBarSet("Verkäufe")
        buy_set.setColor(ORANGE)
        sell_color = QColor("#7D8790")
        sell_set.setColor(sell_color)
        buy_set.setBorderColor(ORANGE)
        sell_set.setBorderColor(sell_color)
        max_value = 0.0
        for label in labels:
            buy_value = grouped[label]["BUY"] / 1_000_000
            sell_value = grouped[label]["SELL"] / 1_000_000
            buy_set.append(buy_value)
            sell_set.append(sell_value)
            max_value = max(max_value, buy_value, sell_value)

        chart = self._base_chart()
        series = QBarSeries()
        series.setBarWidth(0.48)
        series.append(buy_set)
        series.append(sell_set)

        transfer_popover = chart_hover_popover(view)

        def transfer_tooltip(state: bool, index: int, *, transfer_type: str) -> None:
            if not state or index < 0 or index >= len(labels):
                transfer_popover.hide_later()
                return
            label = labels[index]
            raw_value = int(grouped[label][transfer_type])
            if raw_value <= 0:
                transfer_popover.hide_later()
                return
            caption = "Käufe" if transfer_type == "BUY" else "Verkäufe"
            transfer_popover.show_value(
                f"{label} · {caption}\n{euro(raw_value)}",
                QCursor.pos(),
            )

        buy_set.hovered.connect(lambda state, index: transfer_tooltip(state, index, transfer_type="BUY"))
        sell_set.hovered.connect(lambda state, index: transfer_tooltip(state, index, transfer_type="SELL"))
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(labels)
        self._style_chart_axis(axis_x, grid=False)
        chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        self._style_chart_axis(axis_y, grid=True)
        axis_y.setLabelFormat("%.1f")
        axis_y.setRange(0, max(0.5, max_value * 1.2))
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)
        view.setChart(chart)

    def closeEvent(self, event) -> None:
        self.client.close()
        self.storage.close()
        super().closeEvent(event)
