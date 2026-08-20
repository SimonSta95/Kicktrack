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
    compact_number,
    euro,
    player_status_code,
    player_status_display,
    player_status_tooltip
)


class CoachMixin:
    def _build_coach_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(12)

        self.coach_page_title, self.coach_page_subtitle = self._page_header(
            "PRESEASON COACH",
            "Nur die nächsten Schritte für Trading, Startkader und Liquidität",
        )
        layout.addWidget(self.coach_page_title)
        layout.addWidget(self.coach_page_subtitle)

        hero = QFrame()
        hero.setObjectName("CoachHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(8)

        self.coach_hero_title = QLabel("Noch keine Analyse berechnet")
        self.coach_hero_title.setObjectName("CoachHeroTitle")
        self.coach_hero_meta = QLabel("Öffne den Markt oder aktualisiere die Daten, um konkrete Prioritäten zu sehen.")
        self.coach_hero_meta.setObjectName("CoachHeroMeta")
        self.coach_hero_meta.setWordWrap(True)
        hero_layout.addWidget(self.coach_hero_title)
        hero_layout.addWidget(self.coach_hero_meta)

        insights = QHBoxLayout()
        insights.setSpacing(8)

        def add_insight(default_text: str, attr: str) -> None:
            chip = QLabel(default_text)
            chip.setObjectName("CoachInsightChip")
            setattr(self, attr, chip)
            insights.addWidget(chip)

        add_insight("DEADLINE · –", "coach_deadline_chip")
        add_insight("NACH GEBOTEN · –", "coach_budget_chip")
        add_insight("KADER · –/18", "coach_slots_chip")
        add_insight("AKTIONEN · –", "coach_actions_chip")
        add_insight("MIX · –", "coach_mix_chip")
        insights.addStretch()
        hero_layout.addLayout(insights)
        layout.addWidget(hero)

        top = QHBoxLayout()
        self.coach_status = QLabel("Öffne den Markt oder aktualisiere die Daten, um Vorschläge zu berechnen.")
        self.coach_status.setObjectName("Subtle")
        refresh = QPushButton("VORSCHLÄGE NEU BERECHNEN")
        refresh.clicked.connect(self._refresh_coach)
        top.addWidget(self.coach_status, 1)
        top.addWidget(refresh)
        layout.addLayout(top)

        summary = QFrame()
        summary.setObjectName("CoachSummary")
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(10)

        def add_stat(caption: str, attr: str) -> None:
            box = QFrame()
            box.setObjectName("CoachStat")
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(12, 8, 12, 8)
            box_layout.setSpacing(2)
            cap = QLabel(caption)
            cap.setObjectName("CoachStatCaption")
            value = QLabel("–")
            value.setObjectName("CoachStatValue")
            setattr(self, attr, value)
            box_layout.addWidget(cap)
            box_layout.addWidget(value)
            summary_layout.addWidget(box, 1)

        add_stat("FOKUS JETZT", "coach_focus_value")
        add_stat("NACH GEBOTEN", "coach_liquidity_value")
        add_stat("MARKTCHANCEN", "coach_market_value")
        add_stat("KADERAKTIONEN", "coach_squad_value")
        layout.addWidget(summary)

        self.coach_container = QWidget()
        self.coach_layout = QVBoxLayout(self.coach_container)
        self.coach_layout.setContentsMargins(0, 0, 0, 0)
        self.coach_layout.setSpacing(8)
        layout.addWidget(self.coach_container)
        layout.addStretch()
        self._add_scroll_page(page)

    def _clear_coach_cards(self) -> None:
        if not hasattr(self, "coach_layout"):
            return
        while self.coach_layout.count():
            item = self.coach_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _coach_card(self, rec: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("CoachCard")
        label_upper = str(rec.get("label") or "").upper()
        kind = str(rec.get("kind") or "")
        tone = "neutral"
        if kind == "warning" or "ANPASSEN" in label_upper or "PRÜFEN" in label_upper:
            tone = "warning"
        elif kind == "sell" or "VERKAUF" in label_upper:
            tone = "sell"
        elif kind in {"kickbase_buy", "manager_buy"} or label_upper in {"INVEST", "KAUFEN", "KADERZIEL", "TOP-CHANCE"}:
            tone = "buy"
        elif kind == "bid":
            tone = "bid"
        card.setProperty("tone", tone)
        root = QHBoxLayout(card)
        root.setContentsMargins(14, 11, 14, 11)
        root.setSpacing(12)

        rank_value = rec.get("_queue_rank")
        if rank_value:
            rank = QLabel(str(rank_value))
            rank.setObjectName("CoachRank")
            rank.setFixedSize(26, 26)
            rank.setAlignment(Qt.AlignCenter)
            root.addWidget(rank, 0, Qt.AlignTop)

        pid_for_portrait = str(rec.get("player_id") or "")
        portrait = PlayerAvatar(46)
        portrait.setObjectName("CoachPortrait")
        portrait.set_player(str(rec.get("name") or "?"), self.storage.portrait_path(pid_for_portrait) if pid_for_portrait else None)
        root.addWidget(portrait, 0, Qt.AlignTop)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        verdict = QLabel(str(rec.get("label") or "HINWEIS"))
        verdict.setObjectName("CoachVerdict")
        name = QLabel(str(rec.get("name") or "–"))
        name.setObjectName("CoachPlayer")
        status_source = dict(rec.get("raw") or {})
        for key in ("status", "kickbase_status", "st", "status_list", "stl", "status_text", "stxt"):
            if rec.get(key) is not None:
                status_source[key] = rec.get(key)
        status_meta = player_status_display(status_source) if player_status_code(status_source) is not None else ""
        meta = QLabel(" · ".join(part for part in [status_meta, str(rec.get("club") or ""), str(rec.get("position") or ""), str(rec.get("source") or "")] if part))
        meta.setObjectName("CoachMeta")
        if status_meta:
            meta.setToolTip(player_status_tooltip(status_source))
        head.addWidget(verdict)
        head.addWidget(name)
        head.addStretch()
        priority = int(rec.get("priority") or 0)
        if priority:
            prio = QLabel(f"PRIO {priority}")
            prio.setObjectName("CoachPriority")
            prio.setProperty("level", "high" if priority >= 90 else "medium" if priority >= 75 else "low")
            head.addWidget(prio)
        body.addLayout(head)
        body.addWidget(meta)

        purpose_row = QHBoxLayout()
        purpose_row.setSpacing(6)
        primary_reason = str(rec.get("primary_reason") or "").strip()
        secondary_reason = str(rec.get("secondary_reason") or "").strip()
        if primary_reason:
            purpose = QLabel(primary_reason)
            purpose.setObjectName("CoachPurpose")
            purpose_row.addWidget(purpose)
        if secondary_reason:
            secondary = QLabel(secondary_reason)
            secondary.setObjectName("CoachPurposeSecondary")
            purpose_row.addWidget(secondary)
        planability = str(rec.get("planability") or "").strip()
        if planability:
            plan = QLabel(f"PLANBAR {planability}")
            plan.setObjectName("CoachPlanability")
            purpose_row.addWidget(plan)
        confidence = str(rec.get("confidence") or "").strip()
        if confidence:
            conf = QLabel(f"CONF {confidence}")
            conf.setObjectName("CoachSecondaryChip")
            purpose_row.addWidget(conf)
        horizon = str(rec.get("horizon") or "").strip()
        if horizon:
            hz = QLabel(horizon)
            hz.setObjectName("CoachSecondaryChip")
            purpose_row.addWidget(hz)
        purpose_row.addStretch()
        body.addLayout(purpose_row)

        action = QLabel(str(rec.get("action") or ""))
        action.setObjectName("CoachAction")
        action.setWordWrap(True)
        body.addWidget(action)

        def money_chip(label: str, value) -> str | None:
            if value is None:
                return None
            try:
                value = int(value)
            except (TypeError, ValueError):
                return None
            if value <= 0:
                return None
            compact = compact_number(value).lstrip("+")
            return f"{label} {compact} €"

        facts = []
        facts.append(money_chip("MW", rec.get("market_value")))
        price_value = rec.get("price")
        mv_value = rec.get("market_value")
        if price_value and int(price_value or 0) != int(mv_value or 0):
            facts.append(money_chip("Preis", price_value))
        facts.append(money_chip("Max-Bid", rec.get("max_bid")))
        facts.append(money_chip("Gebot", rec.get("own_bid")))
        raw = dict(rec.get("raw") or {})
        if raw.get("value_score") is not None:
            facts.append(f"Value {int(raw.get('value_score') or 0)}/100")
        expires = str(raw.get("expires") or raw.get("expiry") or rec.get("expires") or "").strip()
        if expires and expires != "–":
            facts.append(f"Ablauf {expires}")
        facts = [value for value in facts if value]
        if facts:
            chip_row = QHBoxLayout()
            chip_row.setSpacing(6)
            for value in facts[:6]:
                chip = QLabel(value)
                chip.setObjectName("CoachKpiChip")
                chip_row.addWidget(chip)
            chip_row.addStretch()
            body.addLayout(chip_row)

        reasons = [str(x).strip() for x in (rec.get("reasons") or []) if str(x).strip()]
        secondary_tags = [str(x).strip() for x in (rec.get("secondary_tags") or []) if str(x).strip()]
        visible_reasons = []
        for value in [*secondary_tags, *reasons]:
            if value and value not in visible_reasons:
                visible_reasons.append(value)
            if len(visible_reasons) >= 4:
                break
        if visible_reasons:
            chips = QHBoxLayout()
            chips.setSpacing(6)
            for index, value in enumerate(visible_reasons):
                chip = QLabel(value)
                chip.setObjectName("CoachReasonChip")
                chip.setProperty("primary", index == 0)
                chips.addWidget(chip)
            chips.addStretch()
            body.addLayout(chips)
        detail_parts = []
        if primary_reason:
            detail_parts.append("Primär: " + primary_reason)
        if secondary_reason:
            detail_parts.append("Sekundär: " + secondary_reason)
        if secondary_tags:
            detail_parts.append("Signale: " + " · ".join(secondary_tags))
        if reasons:
            detail_parts.append("Gründe: " + " · ".join(reasons))
        if detail_parts:
            card.setToolTip("\n".join(detail_parts))
        root.addLayout(body, 1)

        pid = rec.get("player_id")
        if pid:
            btn = QPushButton("SPIELER ÖFFNEN")
            btn.clicked.connect(lambda checked=False, player_id=str(pid), data=dict(rec.get("raw") or {}): self.open_player_detail_tab(player_id, str(self.league_combo.currentData() or self.storage.get_setting("league_id") or ""), data))
            root.addWidget(btn, 0, Qt.AlignVCenter)
        return card

    def _refresh_coach(self, *_args) -> None:
        if not hasattr(self, "coach_layout"):
            return
        league_id = self.league_combo.currentData() if hasattr(self, "league_combo") else None
        league_id = str(league_id) if league_id else self.storage.get_setting("league_id")
        if not league_id:
            return
        if not getattr(self, "_market_rows", None):
            self.coach_status.setText("Transfermarkt noch nicht geladen – Markt wird jetzt aktualisiert …")
            self._load_market_overview()
            return

        points_are_current = self._season_stats_current(league_id)
        free_budget = int(getattr(self, "_market_budget", 0) or 0)
        cash_balance = int(getattr(self, "_cash_balance", 0) or free_budget)
        committed = int(getattr(self, "_active_bid_committed", 0) or 0)
        squad = enrich_squad_entries(
            self._player_metrics(),
            points_are_current=points_are_current,
            market_rows=self._market_rows,
            available_budget=free_budget,
        )
        capacity = squad_capacity(squad)
        portfolio_market, portfolio_squad, portfolio_summary = analyze_portfolio(
            self._market_rows,
            squad,
            available_budget=cash_balance,
            season_started=self._season_mode_active(),
            committed_budget=committed,
        )
        manager_id = self.storage.get_league_setting(str(league_id), "manager_id") or self.storage.get_setting("manager_id")
        recs = build_coach_recommendations(
            portfolio_market,
            portfolio_squad,
            managers=self.storage.league_managers(str(league_id)),
            own_manager_id=str(manager_id) if manager_id else None,
            available_budget=free_budget,
            portfolio_summary=portfolio_summary,
            limit=16,
        )
        self._clear_coach_cards()
        if not recs:
            empty = QLabel("Aktuell ergibt sich aus Markt, Budget und Kader kein klarer Handlungsbedarf. Budget halten und Markt beobachten.")
            empty.setObjectName("Subtle")
            empty.setWordWrap(True)
            self.coach_layout.addWidget(empty)
            self.coach_status.setText("Keine klare Aktion notwendig")
            self.coach_hero_title.setText("Coach aktuell entspannt")
            self.coach_hero_meta.setText("Markt, Budget und Kader liefern momentan keinen priorisierten Handlungsdruck.")
            return

        queue = sorted(recs, key=lambda row: int(row.get("priority") or 0), reverse=True)[:14]
        groups = [
            ("JETZT ENTSCHEIDEN", lambda r: r.get("kind") == "warning" or (r.get("kind") == "sell" and int(r.get("priority") or 0) >= 88)),
            ("AKTIVE GEBOTE", lambda r: r.get("kind") == "bid"),
            ("MARKTCHANCEN", lambda r: r.get("kind") in {"kickbase_buy", "manager_buy"}),
            ("KADER / LIQUIDITÄT", lambda r: r.get("kind") in {"sell", "squad_hold"}),
        ]
        rendered: set[int] = set()
        rank = 1
        for heading, predicate in groups:
            group_rows = [(idx, rec) for idx, rec in enumerate(queue) if idx not in rendered and predicate(rec)]
            if not group_rows:
                continue
            group_title = QLabel(f"{heading} · {len(group_rows)}")
            group_title.setObjectName("CoachGroupTitle")
            self.coach_layout.addWidget(group_title)
            for idx, rec in group_rows:
                rendered.add(idx)
                rec = dict(rec)
                rec["_queue_rank"] = rank
                rank += 1
                self.coach_layout.addWidget(self._coach_card(rec))

        leftovers = [(idx, rec) for idx, rec in enumerate(queue) if idx not in rendered]
        if leftovers:
            group_title = QLabel(f"WEITERE CHANCEN · {len(leftovers)}")
            group_title.setObjectName("CoachGroupTitle")
            self.coach_layout.addWidget(group_title)
            for idx, rec in leftovers:
                rec = dict(rec)
                rec["_queue_rank"] = rank
                rank += 1
                self.coach_layout.addWidget(self._coach_card(rec))

        remaining = max(0, len(recs) - len(queue))
        if remaining:
            more = QLabel(f"+ {remaining} weitere valide Hinweise werden aktuell niedriger priorisiert")
            more.setObjectName("Tiny")
            self.coach_layout.addWidget(more)

        deadline = portfolio_summary.get("deadline")
        deadline_text = deadline.strftime("%d.%m. %H:%M") if deadline else "Freitag 20:00"
        after_bids = int(portfolio_summary.get("balance_after_commitments") or 0)
        high_priority = sum(1 for row in recs if int(row.get("priority") or 0) >= 90)
        market_count = sum(1 for row in recs if row.get("kind") in {"kickbase_buy", "manager_buy"})
        squad_count = sum(1 for row in recs if row.get("kind") in {"sell", "squad_hold"})
        bid_count = sum(1 for row in recs if row.get("kind") == "bid")
        top = queue[0]
        top_name = str(top.get("name") or "Nächste Aktion")
        top_label = str(top.get("label") or "COACH")
        top_action = str(top.get("action") or "").strip()

        self.coach_focus_value.setText(f"{high_priority} DRINGEND" if high_priority else "STABIL")
        self.coach_focus_value.setProperty("tone", "warning" if high_priority else "positive")
        self.coach_liquidity_value.setText(euro(after_bids))
        self.coach_liquidity_value.setProperty("tone", "negative" if after_bids < 0 else "positive")
        self.coach_market_value.setText(str(market_count))
        self.coach_squad_value.setText(str(squad_count))
        for label in (self.coach_focus_value, self.coach_liquidity_value, self.coach_market_value, self.coach_squad_value):
            label.style().unpolish(label)
            label.style().polish(label)

        self.coach_hero_title.setText(f"Top-Fokus: {top_label} · {top_name}")
        self.coach_hero_meta.setText(top_action or "Coach hat aktuell die stärksten Handlungsimpulse für dich priorisiert.")

        def _refresh_chip(widget: QLabel, text_value: str, tone: str | None = None) -> None:
            widget.setText(text_value)
            if tone is None:
                widget.setProperty("tone", None)
            else:
                widget.setProperty("tone", tone)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        _refresh_chip(self.coach_deadline_chip, f"DEADLINE · {deadline_text}", "warning" if after_bids < 0 else "neutral")
        _refresh_chip(self.coach_budget_chip, f"NACH GEBOTEN · {euro(after_bids)}", "negative" if after_bids < 0 else "positive")
        slot_tone = "negative" if capacity.is_full else "warning" if capacity.free == 1 else "positive"
        _refresh_chip(self.coach_slots_chip, f"KADER · {capacity.current}/{capacity.maximum} · {capacity.free} FREI", slot_tone)
        _refresh_chip(self.coach_actions_chip, f"AKTIONEN · {len(queue)} / {len(recs)}", "neutral")
        _refresh_chip(self.coach_mix_chip, f"MIX · {market_count} Markt · {bid_count} Gebote · {squad_count} Kader", "neutral")

        self.coach_status.setText(
            f"{deadline_text} · {len(queue)} sichtbare Aktionen · {len(recs)} valide Signale insgesamt"
        )
