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
from PySide6.QtCore import QDateTime, QEvent, QMargins, QPoint, QPointF, QRectF, QSize, Qt, QThreadPool, QTimer, Signal, QStringListModel
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
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
    QMenu,
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
        if event.type() == QEvent.ToolTip and self._hover_popovers_enabled:
            # When the richer delayed hover popover is enabled, suppress Qt's
            # native tooltip so both systems do not fight each other. Tables
            # that explicitly disable hover popovers (notably the market) fall
            # back to the normal item tooltip, which is reliable and cheap.
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

_MARKET_TREND_PALETTE = {
    "ACCELERATING_UP": QColor("#38D98A"),
    "STABLE_UP": QColor("#38D98A"),
    "SLOWING_UP": QColor("#F3A847"),
    "TURNING_UP": QColor("#38D98A"),
    "TURNING_DOWN": QColor("#FF5A5F"),
    "SIDEWAYS": QColor("#7C8690"),
    "RECOVERING": QColor("#F3A847"),
    "STABLE_DOWN": QColor("#FF5A5F"),
    "ACCELERATING_DOWN": QColor("#FF5A5F"),
    "UNKNOWN": QColor("#7C8690"),
}

_MARKET_TREND_LABELS = {
    "ACCELERATING_UP": "Beschleunigend steigend",
    "STABLE_UP": "Stabil steigend",
    "SLOWING_UP": "Verlangsamend steigend",
    "TURNING_UP": "Trendwende aufwärts",
    "TURNING_DOWN": "Trendwende abwärts",
    "SIDEWAYS": "Seitwärts",
    "RECOVERING": "Erholung",
    "STABLE_DOWN": "Stabil fallend",
    "ACCELERATING_DOWN": "Beschleunigt fallend",
    "UNKNOWN": "Zu wenig Daten",
}




def _trend_arrow_head(path: QPainterPath, tip_x: float, tip_y: float, dx: float, dy: float, size: float = 3.4) -> None:
    import math
    length = max(0.001, math.hypot(dx, dy))
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    bx, by = tip_x - ux * size, tip_y - uy * size
    path.moveTo(tip_x, tip_y)
    path.lineTo(bx + px * size * 0.58, by + py * size * 0.58)
    path.moveTo(tip_x, tip_y)
    path.lineTo(bx - px * size * 0.58, by - py * size * 0.58)


def paint_market_trend_icon(painter: QPainter, rect: QRectF, code: str) -> None:
    """Paint a clean line-arrow icon set for market trends.

    The requested look is closer to common outline arrow/chevron packs: clean
    strokes, consistent 45° geometry and no decorative custom blobs.
    """
    code = str(code or "UNKNOWN").upper()
    color = _MARKET_TREND_PALETTE.get(code, _MARKET_TREND_PALETTE["UNKNOWN"])
    painter.setRenderHint(QPainter.Antialiasing, True)

    size = max(14.0, min(float(rect.width()), float(rect.height())) - 6.0)
    cx, cy = float(rect.center().x()), float(rect.center().y())
    half = size / 2.0
    left, right = cx - half, cx + half
    top, bottom = cy - half, cy + half
    pen = QPen(color, max(2.0, size * 0.14), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    def draw_polyline(points: list[tuple[float, float]]):
        path = QPainterPath()
        if not points:
            return
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        painter.drawPath(path)

    def draw_head(tip_x: float, tip_y: float, dx: float, dy: float, length: float | None = None) -> None:
        import math
        head = length or max(4.2, size * 0.22)
        norm = max(0.001, math.hypot(dx, dy))
        ux, uy = dx / norm, dy / norm
        px, py = -uy, ux
        bx, by = tip_x - ux * head, tip_y - uy * head
        painter.drawLine(QPointF(tip_x, tip_y), QPointF(bx + px * head * 0.58, by + py * head * 0.58))
        painter.drawLine(QPointF(tip_x, tip_y), QPointF(bx - px * head * 0.58, by - py * head * 0.58))

    def draw_arrow(points: list[tuple[float, float]], dx: float, dy: float):
        draw_polyline(points)
        tip_x, tip_y = points[-1]
        draw_head(tip_x, tip_y, dx, dy)

    def draw_chevron(center_x: float, center_y: float, dx: float, dy: float, spread: float = 0.0):
        import math
        norm = max(0.001, math.hypot(dx, dy))
        ux, uy = dx / norm, dy / norm
        px, py = -uy, ux
        arm = max(4.5, size * 0.26)
        tip_x = center_x + ux * arm
        tip_y = center_y + uy * arm
        back_x = center_x - ux * arm * 0.55
        back_y = center_y - uy * arm * 0.55
        left_x = back_x + px * arm * 0.78
        left_y = back_y + py * arm * 0.78
        right_x = back_x - px * arm * 0.78
        right_y = back_y - py * arm * 0.78
        if spread:
            center_x += px * spread
            center_y += py * spread
        painter.drawLine(QPointF(left_x, left_y), QPointF(tip_x, tip_y))
        painter.drawLine(QPointF(right_x, right_y), QPointF(tip_x, tip_y))

    if code == "ACCELERATING_UP":
        draw_chevron(cx - size * 0.14, cy + size * 0.14, 1, -1)
        draw_chevron(cx + size * 0.18, cy - size * 0.18, 1, -1)
        return
    if code == "STABLE_UP":
        draw_arrow([(left + 2, bottom - 2), (right - 2, top + 2)], 1, -1)
        return
    if code == "SLOWING_UP":
        draw_arrow([(left + 2, bottom - 2), (cx - 1, top + 3), (right - 2, top + 3)], 1, 0)
        return
    if code == "TURNING_UP":
        draw_arrow([(left + 2, top + 3), (cx - 2, bottom - 2), (right - 2, top + 3)], 1, -1)
        return
    if code == "TURNING_DOWN":
        draw_arrow([(left + 2, bottom - 3), (cx - 2, top + 2), (right - 2, bottom - 3)], 1, 1)
        return
    if code == "SIDEWAYS":
        draw_arrow([(left + 2, cy), (right - 2, cy)], 1, 0)
        return
    if code == "RECOVERING":
        draw_arrow([(left + 2, cy + size * 0.18), (cx - 2, bottom - 2), (right - 2, cy - size * 0.08)], 1, -0.55)
        return
    if code == "STABLE_DOWN":
        draw_arrow([(left + 2, top + 2), (right - 2, bottom - 2)], 1, 1)
        return
    if code == "ACCELERATING_DOWN":
        draw_chevron(cx - size * 0.14, cy - size * 0.14, 1, 1)
        draw_chevron(cx + size * 0.18, cy + size * 0.18, 1, 1)
        return

    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    for fraction in (0.25, 0.5, 0.75):
        painter.drawEllipse(QRectF(left + size * fraction - 1.3, cy - 1.3, 2.6, 2.6))


def market_trend_icon_pixmap(code: str, size: int = 26) -> QPixmap:
    code = str(code or "UNKNOWN").upper()
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        paint_market_trend_icon(painter, QRectF(0, 0, size, size), code)
    finally:
        painter.end()
    return pixmap



class MarketTrendLegend(QWidget):
    """Visible legend for the icon-only trend column."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel("DYNAMIK:")
        title.setObjectName("Tiny")
        layout.addWidget(title)

        entries = (
            ("ACCELERATING_UP", "Beschleunigend"),
            ("STABLE_UP", "Stabil steigend"),
            ("SLOWING_UP", "Verlangsamend"),
            ("TURNING_UP", "Wende ↑"),
            ("TURNING_DOWN", "Wende ↓"),
            ("SIDEWAYS", "Seitwärts"),
            ("RECOVERING", "Erholung"),
            ("STABLE_DOWN", "Fallend"),
            ("ACCELERATING_DOWN", "Beschl. fallend"),
        )
        for code, text in entries:
            entry = QWidget(self)
            entry_layout = QHBoxLayout(entry)
            entry_layout.setContentsMargins(0, 0, 0, 0)
            entry_layout.setSpacing(4)
            icon = QLabel(entry)
            icon.setPixmap(market_trend_icon_pixmap(code, 22))
            icon.setFixedSize(22, 22)
            icon.setToolTip(_MARKET_TREND_LABELS[code])
            label = QLabel(text, entry)
            label.setObjectName("Tiny")
            label.setToolTip(_MARKET_TREND_LABELS[code])
            entry_layout.addWidget(icon)
            entry_layout.addWidget(label)
            layout.addWidget(entry)
        layout.addStretch(1)


class MarketTrendIconDelegate(QStyledItemDelegate):
    """Paint compact CI-style vector trend icons without Unicode/ASCII glyphs."""

    def paint(self, painter, option, index) -> None:
        painter.save()
        try:
            selected = bool(option.state & QStyle.State_Selected)
            row_bg = QColor("#211A16") if selected else QColor("#14181B") if index.row() % 2 else QColor("#101316")
            painter.fillRect(option.rect, row_bg)
            code = str(index.data(Qt.UserRole + 2) or "UNKNOWN").upper()
            pixmap = market_trend_icon_pixmap(code, min(24, max(18, option.rect.height() - 12)))
            x = option.rect.center().x() - pixmap.width() // 2
            y = option.rect.center().y() - pixmap.height() // 2
            painter.drawPixmap(x, y, pixmap)
        finally:
            painter.restore()


class SquadRoleDelegate(QStyledItemDelegate):
    """Editable role chip for the squad table.

    The role is stored as a normal QTableWidgetItem.  Unlike a persistent
    QComboBox cell widget, that item moves atomically with the row when Qt sorts
    the table.  A transient combo editor exists only while the role is edited.
    """

    roleChanged = Signal(str, str)

    _ROLES = ("OFFEN", "STAMM", "INVEST", "TRANSFERLISTE")

    @staticmethod
    def _palette(role: str) -> tuple[QColor, QColor, QColor]:
        role = str(role or "OFFEN").upper().strip()
        if role == "STAMM":
            return QColor("#10251A"), QColor("#285B3C"), QColor("#65E89C")
        if role == "INVEST":
            return QColor("#21152C"), QColor("#58376E"), QColor("#C58BFF")
        if role == "TRANSFERLISTE":
            return QColor("#2A180E"), QColor("#71401D"), QColor("#FF6A2A")
        return QColor("#171D22"), QColor("#34414B"), QColor("#B9C5CE")

    def paint(self, painter, option, index) -> None:
        painter.save()
        selected = bool(option.state & QStyle.State_Selected)
        row_bg = QColor("#211A16") if selected else QColor("#14181B") if index.row() % 2 else QColor("#101316")
        painter.fillRect(option.rect, row_bg)
        role = str(index.data(Qt.DisplayRole) or "OFFEN")
        bg, border, fg = self._palette(role)
        rect = QRectF(option.rect.adjusted(8, 7, -8, -7))
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 7, 7)
        painter.setPen(fg)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect.adjusted(10, 0, -20, 0), Qt.AlignLeft | Qt.AlignVCenter, role)
        # Small vector chevron; no font/unicode dependency.
        cx = rect.right() - 11
        cy = rect.center().y()
        painter.setPen(QPen(fg, 1.4))
        painter.drawLine(QPointF(cx - 3, cy - 1.5), QPointF(cx, cy + 1.5))
        painter.drawLine(QPointF(cx, cy + 1.5), QPointF(cx + 3, cy - 1.5))
        painter.restore()

    def open_role_menu(self, table: QTableWidget, index) -> None:
        """Open a compact role picker without replacing the painted chip.

        A QComboBox delegate editor briefly covered the whole cell on Windows,
        which made the role control jump to a large dark rectangle.  A popup
        menu keeps the painted chip untouched and only overlays the choices.
        """
        if not index.isValid():
            return
        current = str(index.data(Qt.DisplayRole) or "OFFEN").upper()
        menu = QMenu(table)
        menu.setObjectName("SquadRoleMenu")
        menu.setStyleSheet(
            "QMenu#SquadRoleMenu { background:#14191D; color:#E8EDF2; "
            "border:1px solid #34414B; border-radius:8px; padding:5px; } "
            "QMenu#SquadRoleMenu::item { padding:7px 18px 7px 12px; border-radius:5px; } "
            "QMenu#SquadRoleMenu::item:selected { background:#232B31; } "
            "QMenu#SquadRoleMenu::indicator { width:0px; height:0px; }"
        )
        for role in self._ROLES:
            action = menu.addAction(ROLE_LABELS.get(role, role))
            action.setCheckable(True)
            action.setChecked(role == current)
            action.triggered.connect(lambda _checked=False, r=role, idx=index: self._apply_role(idx, r))

        rect = table.visualRect(index)
        popup_pos = table.viewport().mapToGlobal(rect.bottomLeft())
        # Keep the menu alive until Qt closes it. exec() is local/nested and
        # avoids ownership/timing glitches from a short-lived popup instance.
        menu.exec(popup_pos)

    def _apply_role(self, index, role: str) -> None:
        role = str(role or "OFFEN").upper()
        model = index.model()
        model.setData(index, role, Qt.DisplayRole)
        model.setData(index, ROLE_SORT.get(role, 99), SORT_ROLE)
        player_id = str(index.data(Qt.UserRole) or "")
        if player_id:
            self.roleChanged.emit(player_id, role)


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
            context = []
            if market_value:
                context.append(f"MW {euro(market_value)}")
            own_bid = int(bid.get("bid") or bid.get("amount") or bid.get("price") or 0)
            if market_value and own_bid:
                premium = (own_bid - market_value) / market_value * 100.0
                context.append(f"Gebot {premium:+.1f}% zum MW")
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
