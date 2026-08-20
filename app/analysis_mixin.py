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
    GREEN,
    ORANGE,
    RED,
    WHITE,
    chart_hover_popover,
    club_icon,
    delta_text,
    display_date,
    euro,
    set_delta_label,
    short_date,
    table_item
)


class AnalysisMixin:
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
