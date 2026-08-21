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
    ChartPanel,
    ClubItemDelegate,
    GREEN,
    KickbaseLogo,
    MUTED,
    MetricCard,
    ORANGE,
    POSITION_SORT,
    RED,
    ResponsiveTableWidget,
    SERVICE,
    WHITE,
    chart_hover_popover,
    club_icon,
    delta_text,
    display_date,
    euro,
    percent,
    player_status_code,
    player_status_icon,
    player_status_label,
    player_status_tooltip,
    refresh_style,
    set_delta_label,
    set_item_delta_color,
    table_item
)


from .action_dialogs import ListingManagementDialog, SellPlayerDialog

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
        self._is_owned_player = str(local_player.get("player_status") or "") == "KADER"

        # Selling is intentionally split into two explicit concepts. "Anbieten"
        # only creates a listing. Existing listings are managed separately, where
        # the direct Kickbase sale is clearly labelled as its own write action.
        self.list_player_btn = QPushButton("ANBIETEN")
        self.list_player_btn.setObjectName("Primary")
        self.list_player_btn.setToolTip("Spieler auf den Kickbase-Transfermarkt stellen")
        self.list_player_btn.clicked.connect(self._open_sell_player)
        header.addWidget(self.list_player_btn)

        self.manage_listing_btn = QPushButton("LISTING VERWALTEN")
        self.manage_listing_btn.setToolTip("Listenpreis ändern, vom Markt nehmen oder separat an Kickbase verkaufen")
        self.manage_listing_btn.clicked.connect(self._open_listing_management)
        header.addWidget(self.manage_listing_btn)
        self._refresh_sale_actions()

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

    def _host_main_window(self):
        candidates = [self.window(), self.parent()]
        parent = self.parent()
        if parent is not None and hasattr(parent, "parent"):
            try:
                candidates.append(parent.parent())
            except Exception:
                pass
        for candidate in candidates:
            if candidate is not None and hasattr(candidate, "_own_listings_by_id"):
                return candidate
        return self.window()

    def _current_own_listing(self) -> dict | None:
        if self.player.get("listing_price") is not None:
            return dict(self.player)
        host = self._host_main_window()
        listings = getattr(host, "_own_listings_by_id", {}) if host is not None else {}
        listing = listings.get(str(self.player_id)) if isinstance(listings, dict) else None
        return dict(listing) if isinstance(listing, dict) else None

    def _refresh_sale_actions(self) -> None:
        owned = bool(getattr(self, "_is_owned_player", False))
        listing = self._current_own_listing() if owned else None
        self.list_player_btn.setVisible(owned and listing is None)
        self.manage_listing_btn.setVisible(owned and listing is not None)

    def _open_listing_management(self) -> None:
        if not self.league_id or self.client is None:
            QMessageBox.warning(self, "Verkauf verwalten", "Keine aktive Liga bzw. Kickbase-Verbindung verfügbar.")
            return
        listing = self._current_own_listing()
        if listing is None:
            QMessageBox.information(
                self,
                "Kein aktives Listing",
                "Für diesen Spieler ist aktuell kein eigenes Transfermarkt-Listing bekannt. Bitte Markt/Liga einmal aktualisieren.",
            )
            self._refresh_sale_actions()
            return
        dialog = ListingManagementDialog(
            self, self.client, str(self.league_id), listing, refresh_callback=self._refresh_after_sale_write
        )
        dialog.exec()
        self._refresh_sale_actions()

    def _refresh_after_sale_write(self) -> None:
        host = self._host_main_window()
        if host is not None and hasattr(host, "_load_market_overview"):
            try:
                host._load_market_overview()
            except Exception:
                pass
        if host is not None and hasattr(host, "sync"):
            try:
                host.sync()
            except Exception:
                pass

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
        self.player["listing_price"] = amount
        self.player["price"] = amount
        host = self._host_main_window()
        if host is not None:
            listings = getattr(host, "_own_listings_by_id", None)
            if isinstance(listings, dict):
                listing = dict(self.player)
                listing["listing_price"] = amount
                listing["price"] = amount
                listings[str(self.player_id)] = listing
        self._refresh_sale_actions()

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
