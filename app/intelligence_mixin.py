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
    MetricCard,
    POSITION_SORT,
    club_icon,
    delta_text,
    display_date,
    euro,
    percent,
    set_item_delta_color,
    table_item
)
from .dialogs import (
    LineupOptimizerDialog
)


class IntelligenceMixin:
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
