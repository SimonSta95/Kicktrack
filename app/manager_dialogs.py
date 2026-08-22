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
from .player_dialogs import open_player_detail_window
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
