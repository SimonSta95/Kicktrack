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
    POSITION_SORT,
    RED,
    ROLE_LABELS,
    ROLE_SORT,
    change_tooltip,
    club_icon,
    delta_text,
    display_date,
    euro,
    market_value_tooltip,
    player_status_code,
    player_status_display,
    player_status_icon,
    player_status_tooltip,
    refresh_style,
    set_delta_label,
    set_item_delta_color,
    table_item
)
from .dialogs import (
    ListingManagementDialog,
    ManagerDetailDialog
)


class LeagueMixin:
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
        # Keep a lightweight live index so player detail dialogs can distinguish
        # "auf den Markt stellen" from "bestehendes Listing verwalten" without
        # issuing another hidden API request.
        self._own_listings_by_id = {
            str(player.get("player_id")): dict(player)
            for player in (listings or [])
            if isinstance(player, dict) and player.get("player_id") is not None
        }
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
