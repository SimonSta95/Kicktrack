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
    ClubItemDelegate,
    CompactMetric,
    MUTED,
    POSITION_SORT,
    RED,
    RecommendationChipDelegate,
    WHITE,
    change_tooltip,
    club_icon,
    compact_number,
    delta_text,
    euro,
    player_name_cell,
    player_status_code,
    player_status_display,
    player_status_tooltip,
    set_item_delta_color,
    table_item
)
from .dialogs import (
    FinancingScenarioDialog,
    MarketBidDialog,
    MarketScannerDialog,
    MarketScoringInfoDialog,
    PreseasonOptimizerDialog,
    SquadScoringInfoDialog
)


class MarketMixin:
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

    def _mv_prediction_target_date() -> date:
        """Refresh day targeted by a prediction made right now (Europe/Berlin)."""
        now = datetime.now(ZoneInfo("Europe/Berlin"))
        today = now.date()
        # Kickbase refreshes around 22:00 local time. After that point a freshly
        # calculated forecast necessarily targets tomorrow's refresh.
        return today if now.hour < 22 else today + timedelta(days=1)

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

    def _market_expiry_sort(expires_at) -> float:
        if not expires_at:
            return float("inf")
        try:
            return datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return float("inf")

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

    def _score_label(value: int | float | None) -> str:
        score = int(value or 0)
        if score >= 80:
            return "STARK"
        if score >= 65:
            return "GUT"
        if score >= 45:
            return "NEUTRAL"
        return "SCHWACH"

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

    def _format_market_history_empty() -> str:
        return (
            '<div style="line-height:1.4;">'
            '<div style="font-weight:800; color:#DDE6EC; margin-bottom:4px;">HISTORIE</div>'
            '<div>Noch zu wenig vergleichbare Outcomes.</div>'
            '</div>'
        )

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
