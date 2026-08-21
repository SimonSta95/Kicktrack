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



from .dialogs import (
    LoginDialog,
    PortraitReviewDialog
)


class SyncMixin:
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

    def _force_update_all(self) -> None:
        league_id = self.league_combo.currentData() or self.storage.get_setting("league_id")
        if not league_id:
            QMessageBox.warning(self, "Keine Liga", "Bitte zuerst eine Liga auswählen.")
            return
        if self._force_update_active:
            return
        busy = any((
            self._sync_worker, self._league_analysis_worker, self._league_ownership_worker,
            self._market_worker, self._market_enrichment_worker, self._market_status_worker, self._budget_worker, self._intelligence_worker, self._league_learning_worker,
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
            self._market_worker, self._market_enrichment_worker, self._market_status_worker, self._budget_worker, self._intelligence_worker, self._league_learning_worker,
        ))
        if busy or self._force_ownership_pending:
            QTimer.singleShot(300, self._poll_force_update_finished)
            return
        self._force_update_active = False
        self.force_update_btn.setEnabled(True)
        self.force_update_btn.setText("FORCE UPDATE · ALLE LIVE-DATEN")
        self.refresh_all()
        self.statusBar().showMessage("Force Update abgeschlossen · alle Live-Bereiche wurden neu geladen", 9000)

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
