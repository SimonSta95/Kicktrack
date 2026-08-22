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
from .market_value_insights import TREND_LABELS, analyze_market_value_trend, build_reversal_reference, predict_trend_reversal, facts_first_squad_action, trend_display, trend_tone
from .performance_chart import PerformanceMatchBarsWidget
from .market_analysis import enrich_market_entries, financing_scenarios
from .bid_analysis import rate_bid
from .bidding import calculate_bid_capacity
from .selling import listing_price_for_percent
from .squad_analysis import enrich_squad_entries
from .coach_analysis import build_coach_recommendations
from .transfer_evaluation import evaluate_trade_cycles, transfer_evaluation_summary
from .preseason_tools import optimize_starting_squad
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
    MarketTrendIconDelegate,
    MUTED,
    POSITION_SORT,
    ROLE_LABELS,
    ROLE_SORT,
    change_tooltip,
    club_icon,
    delta_text,
    euro,
    market_value_tooltip,
    percent,
    player_name_cell,
    player_status_icon,
    player_status_tooltip,
    set_delta_label,
    set_item_delta_color,
    table_item
)


class DashboardSquadMixin:
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
            if str(row.get("facts_signal") or row.get("verdict") or row.get("action") or "").upper() == "INTERESSANT"
        ]
        if market_candidates and not capacity.is_full and not season_active:
            # No synthetic market score: prefer the smallest premium to MW, then
            # a stable/accelerating real MW trend.
            trend_rank = {"ACCELERATING_UP": 0, "STABLE_UP": 1, "SLOWING_UP": 2}
            market_candidates.sort(key=lambda r: (
                float(r.get("price_delta_pct") if r.get("price_delta_pct") is not None else 999.0),
                trend_rank.get(str((r.get("mv_trend") or {}).get("code") or ""), 9),
                str(r.get("name") or "").casefold(),
            ))
            best = market_candidates[0]
            name = str(best.get("name") or "Marktchance")
            verdict = str(best.get("facts_signal") or "INTERESSANT").upper()
            focus_title = f"{name}: {verdict}"
            reasons = [str(x) for x in (best.get("analysis_reasons") or []) if str(x).strip()]
            focus_subtitle = reasons[0] if reasons else "Positiver MW-Trend bei nachvollziehbarem Preis-vs.-MW-Verhältnis."

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
        except Exception as exc:
            print(f"[WARN] squad prediction cache load failed: {exc}")
        players = enrich_squad_entries(
            players,
            points_are_current=points_are_current,
            market_rows=market_context,
            available_budget=current_budget,
        )
        # Facts First: squad actions use the real MW timeline, the user's role,
        # open P/L and a separately labelled reversal prediction. No aggregate
        # squad/trading score is used for the visible recommendation.
        try:
            # Do not scan the complete market-value table on every Kader click.
            # The expensive historical reference is built once by the market worker
            # and reused here. Without it the current trend remains available and
            # the reversal forecast degrades explicitly to UNSICHER.
            reversal_reference = list(getattr(self, "_reversal_reference_cache", []) or [])
            for player in players:
                pid = str(player.get("player_id") or "")
                history = self.storage.all_history(pid) if pid else []
                trend = analyze_market_value_trend(
                    history,
                    market_value=int(player.get("market_value") or 0),
                    current_delta=player.get("d1"),
                )
                reversal = predict_trend_reversal(
                    (),
                    history,
                    market_value=int(player.get("market_value") or 0),
                    current_delta=player.get("d1"),
                    reference_samples=reversal_reference,
                )
                action, reasons = facts_first_squad_action(player, trend, reversal)
                player["mv_trend"] = trend
                player["trend_reversal_prediction"] = reversal
                player["facts_action"] = action
                player["action"] = action
                player["analysis_reasons"] = reasons
        except Exception as exc:
            print(f"[WARN] squad facts-first enrichment failed: {exc}")

        if hasattr(self, "squad_quality_card"):
            roles = [str(p.get("player_role") or "OFFEN").upper() for p in players]
            self.squad_quality_card.value_label.setText(str(sum(1 for r in roles if r == "STAMM")))
            self.squad_core_card.value_label.setText(str(sum(1 for r in roles if r == "INVEST")))
            self.squad_invest_card.value_label.setText(str(sum(1 for r in roles if r == "TRANSFERLISTE")))
            self.squad_sell_card.value_label.setText(str(sum(1 for p in players if p.get("action") in {"VERKAUF PRÜFEN", "GEWINN ABSICHERN", "VERKAUF BEOBACHTEN", "EXIT BEOBACHTEN"})))

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
            # Do not spend a full panel on the common "Alles verfügbar" case.
            # The compact summary remains available in the surrounding squad UI
            # only when there is something that actually needs attention.
            if hasattr(self, "squad_status_panel"):
                self.squad_status_panel.setVisible(bool(affected))
            self.squad_status_table.setVisible(bool(affected))
            self.squad_status_empty.setVisible(False)
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

        self._render_squad_detail_rows(players)

    def _render_squad_detail_rows(self, players: list[dict]) -> None:
        table = self.squad_table
        header = table.horizontalHeader()
        sort_column = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        sorting_was_enabled = table.isSortingEnabled()

        # Build the complete replacement off-table first. If one optional value is
        # malformed, the currently visible table remains intact instead of being
        # cleared and left half-populated.
        staged_rows: list[list[QTableWidgetItem]] = []
        for player in players:
            role = str(player.get("player_role") or "OFFEN").upper()
            trend_info = player.get("mv_trend") if isinstance(player.get("mv_trend"), dict) else {}
            reversal = player.get("trend_reversal_prediction") if isinstance(player.get("trend_reversal_prediction"), dict) else {}
            action = str(player.get("facts_action") or player.get("action") or "KEINE KLARE EMPFEHLUNG")
            probability = reversal.get("probability")
            try:
                probability_value = float(probability) if probability is not None else None
            except (TypeError, ValueError):
                probability_value = None

            specs = [
                (str(player.get("name") or "–"), str(player.get("name") or "")),
                (str(player.get("club") or "–"), str(player.get("club") or ""), club_icon(player.get("club"))),
                (str(player.get("position") or "–"), POSITION_SORT.get(player.get("position"), 99)),
                (ROLE_LABELS.get(role, role), ROLE_SORT.get(role, 99)),
                (euro(player.get("market_value")), player.get("market_value") if player.get("market_value") is not None else -10**18),
                (delta_text(player.get("d1"), compact=True), player.get("d1") if player.get("d1") is not None else -10**18),
                (delta_text(player.get("next_refresh_delta"), compact=True), player.get("next_refresh_delta") if player.get("next_refresh_delta") is not None else -10**18),
                (delta_text(player.get("pnl"), compact=True), player.get("pnl") if player.get("pnl") is not None else -10**18),
                ("", str(trend_info.get("code") or "UNKNOWN")),
                (
                    f"{str(reversal.get('risk') or 'UNSICHER')} {probability_value * 100:.0f}%"
                    if probability_value is not None else "UNSICHER",
                    probability_value if probability_value is not None else -1.0,
                ),
                (action, action.casefold()),
            ]

            items: list[QTableWidgetItem] = []
            for col, spec in enumerate(specs):
                text, sort_value = spec[0], spec[1]
                icon = spec[2] if len(spec) > 2 else None
                item = table_item(text, sort_value, icon=icon)
                item.setData(Qt.UserRole, str(player.get("player_id") or ""))
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col in (0, 1) else Qt.AlignCenter)
                if col == 0:
                    item.setToolTip(player_status_tooltip(player))
                if col == 1 and icon is not None and not icon.isNull():
                    item.setToolTip(str(player.get("club") or ""))
                if col == 4:
                    item.setToolTip(market_value_tooltip(player))
                elif col == 5:
                    set_item_delta_color(item, player.get("d1"))
                    item.setToolTip(change_tooltip("24h Änderung", player.get("market_value"), player.get("d1"), exact=True))
                elif col == 6:
                    pred = player.get("next_refresh_prediction") if isinstance(player.get("next_refresh_prediction"), dict) else {}
                    set_item_delta_color(item, pred.get("delta"))
                    if pred.get("delta") is not None:
                        item.setToolTip(
                            f"Nächster MW-Refresh (22 Uhr)\n"
                            f"Prognose: {delta_text(pred.get('delta'))} → ca. {euro(pred.get('expected_value'))}\n"
                            f"80%-Erfahrungsbereich: {delta_text(pred.get('low_delta'))} bis {delta_text(pred.get('high_delta'))}\n"
                            f"Basis: {pred.get('confidence', 'UNSICHER')} · n={pred.get('sample_count', 0)}"
                        )
                elif col == 7:
                    set_item_delta_color(item, player.get("pnl"))
                    item.setToolTip(market_value_tooltip(player))
                elif col == 8:
                    code = str(trend_info.get("code") or "UNKNOWN")
                    item.setData(Qt.UserRole + 2, code)
                    tone = trend_tone(code)
                    if tone == "positive":
                        item.setForeground(QColor("#38D98A"))
                    elif tone == "warning":
                        item.setForeground(QColor("#F3A847"))
                    elif tone == "negative":
                        item.setForeground(QColor("#FF5A5F"))
                    else:
                        item.setForeground(MUTED)
                    label = str(trend_info.get("label") or TREND_LABELS.get(code) or TREND_LABELS["UNKNOWN"])
                    tooltip = f"Dynamik: {label}\n{str(trend_info.get('reason') or 'Noch zu wenig MW-Historie.')}"
                    if trend_info.get("steps_text"):
                        tooltip += f"\nLetzte Schritte: {trend_info.get('steps_text')}"
                    item.setToolTip(tooltip)
                elif col == 9:
                    item.setToolTip(str(reversal.get("reason") or "Noch zu wenig historische Vergleichsfälle."))
                elif col == 10:
                    reasons = player.get("analysis_reasons")
                    if isinstance(reasons, (list, tuple)):
                        item.setToolTip("\n".join(str(x) for x in reasons if str(x).strip()))
                items.append(item)

            role_item = items[3]
            role_item.setFlags(role_item.flags() | Qt.ItemIsEditable)
            role_item.setToolTip("Eigene Rolle für diesen Spieler. Anklicken zum Ändern; wird lokal gespeichert.")
            staged_rows.append(items)

        table.setSortingEnabled(False)
        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(0)
            table.setRowCount(len(staged_rows))
            self._size_squad_detail_table(len(staged_rows))
            for row, items in enumerate(staged_rows):
                for col, item in enumerate(items):
                    table.setItem(row, col, item)
        finally:
            table.setUpdatesEnabled(True)
            if sorting_was_enabled:
                table.setSortingEnabled(True)
                if 0 <= int(sort_column) < table.columnCount():
                    table.sortItems(int(sort_column), sort_order)
            table.viewport().update()
            self._size_squad_detail_table(len(staged_rows))

    def _edit_squad_role_cell(self, row: int, column: int) -> None:
        if int(column) != 3:
            return
        index = self.squad_table.model().index(int(row), 3)
        if not index.isValid():
            return
        self.squad_role_delegate.open_role_menu(self.squad_table, index)

    def _size_squad_detail_table(self, row_count: int) -> None:
        """Show the complete squad in the page scroll area, never in a tiny table."""
        if not hasattr(self, "squad_table"):
            return
        table = self.squad_table
        row_height = max(48, int(table.verticalHeader().defaultSectionSize() or 48))
        header_height = int(table.horizontalHeader().height() or 42) if table.horizontalHeader().isVisible() else 0
        # At least eight rows remain visible while loading/empty; with real data
        # the exact full squad height (max 18) is used. The outer PageScroll is
        # the only vertical scrollbar.
        visible_rows = max(8, int(row_count or 0))
        frame = int(table.frameWidth() or 1) * 2
        target_height = header_height + visible_rows * row_height + frame + 4
        table.setMinimumHeight(target_height)
        table.setMaximumHeight(target_height)
        table.resizeRowsToContents()
        # Cell widgets can report smaller content heights; restore the intended
        # consistent row rhythm after resizeRowsToContents().
        for row in range(table.rowCount()):
            table.setRowHeight(row, row_height)
        table.updateGeometry()

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
