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



from .ui_components import (
    AccountChip,
    BudgetBidList,
    ChartPanel,
    ClubItemDelegate,
    CompactMetric,
    KickbaseLogo,
    LeagueValueSummaryPanel,
    MetricCard,
    RecommendationChipDelegate,
    ResponsiveTableWidget,
    compact_number,
    euro,
    refresh_style
)
from .dialogs import (
    ManagerDetailDialog,
    MarketScannerDialog,
    PlayerDetailTabsWindow,
    open_player_detail_window
)
from .market_mixin import MarketMixin
from .intelligence_mixin import IntelligenceMixin
from .coach_mixin import CoachMixin
from .sync_mixin import SyncMixin
from .dashboard_squad_mixin import DashboardSquadMixin
from .league_mixin import LeagueMixin
from .analysis_mixin import AnalysisMixin

class MainWindow(
    MarketMixin, IntelligenceMixin, CoachMixin, SyncMixin,
    DashboardSquadMixin, LeagueMixin, AnalysisMixin, QMainWindow,
):
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

    def refresh_all(self) -> None:
        league_id = self.league_combo.currentData()
        league_id = str(league_id) if league_id else self.storage.get_setting("league_id")
        self._refresh_dashboard(league_id)
        self._refresh_squad()
        self._refresh_league_page(league_id)
        self._refresh_transfers(league_id)
        self._refresh_analysis()

    def closeEvent(self, event) -> None:
        self.client.close()
        self.storage.close()
        super().closeEvent(event)
