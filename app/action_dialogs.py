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



class LoginDialog(QDialog):
    def __init__(self, parent, storage: Storage, client: KickbaseClient) -> None:
        super().__init__(parent)
        self.storage = storage
        self.client = client
        self.setWindowTitle("Kickbase Login")
        self.setMinimumWidth(470)

        logo = KickbaseLogo()
        subtitle = QLabel("Verbinde deinen Kickbase-Account")
        subtitle.setObjectName("Subtle")

        self.email = QLineEdit()
        self.email.setPlaceholderText("E-Mail")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Passwort")
        self.password.setEchoMode(QLineEdit.Password)
        self.remember = QCheckBox("Login merken (System-Keyring)")
        self.login_btn = QPushButton("ANMELDEN")
        self.login_btn.setObjectName("Primary")
        self.login_btn.clicked.connect(self.do_login)

        saved_email = self.storage.get_setting("email", "")
        if saved_email:
            self.email.setText(saved_email)
            try:
                saved_password = keyring.get_password(SERVICE, saved_email)
                if saved_password:
                    self.password.setText(saved_password)
                    self.remember.setChecked(True)
            except Exception:
                pass

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 26, 28, 26)
        card_layout.setSpacing(14)
        card_layout.addWidget(logo)
        card_layout.addWidget(subtitle)
        card_layout.addSpacing(6)
        card_layout.addWidget(self.email)
        card_layout.addWidget(self.password)
        card_layout.addWidget(self.remember)
        card_layout.addSpacing(4)
        card_layout.addWidget(self.login_btn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        outer.addWidget(card)

    def do_login(self) -> None:
        email = self.email.text().strip()
        password = self.password.text()
        if not email or not password:
            QMessageBox.warning(self, "Fehlt noch was", "Bitte E-Mail und Passwort eingeben.")
            return

        self.login_btn.setEnabled(False)
        self.login_btn.setText("VERBINDE …")
        self.email.setEnabled(False)
        self.password.setEnabled(False)

        worker = FunctionWorker(lambda: self.client.login(email, password))
        self._login_worker = worker
        worker.signals.succeeded.connect(
            lambda _result: self._login_succeeded(email, password)
        )
        worker.signals.failed.connect(self._login_failed)
        QThreadPool.globalInstance().start(worker)

    def _login_succeeded(self, email: str, password: str) -> None:
        self.storage.set_setting("email", email)
        try:
            if self.remember.isChecked():
                keyring.set_password(SERVICE, email, password)
            else:
                try:
                    keyring.delete_password(SERVICE, email)
                except Exception:
                    pass
        except Exception:
            # A keyring problem should not turn a successful Kickbase login into a failure.
            pass
        self.accept()

    def _login_failed(self, message: str) -> None:
        self.login_btn.setEnabled(True)
        self.login_btn.setText("ANMELDEN")
        self.email.setEnabled(True)
        self.password.setEnabled(True)
        QMessageBox.critical(self, "Login fehlgeschlagen", message)

class SquadScoringInfoDialog(QDialog):
    """Explain the exact own-squad scoring model shown in the KADER tab."""

    def __init__(self, parent=None, *, points_are_current: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle("So funktioniert die Kader-Einschätzung")
        self.resize(780, 720)
        self.setMinimumSize(660, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel("KADER-EINSCHÄTZUNG")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Drei getrennte 0–100-Werte. Jeder Punkt basiert auf messbaren Kader-, Marktwert- und Rolleninformationen.")
        subtitle.setObjectName("Subtle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        squad = QFrame(); squad.setObjectName("Panel")
        sl = QVBoxLayout(squad); sl.setContentsMargins(16, 14, 16, 14); sl.setSpacing(7)
        st = QLabel("ANALYSE-SCORE · 0–100"); st.setObjectName("SectionTitle"); sl.addWidget(st)
        metric = "Ø Punkte gegen den Median deiner Positionskollegen" if points_are_current else "Marktwert gegen den Median deiner Positionskollegen (Preseason)"
        txt = QLabel(
            "• Positionsrelevanz: 25 Punkte – wie dünn die jeweilige Position in deinem Kader besetzt ist. Zielbreite: TW 2 / ABW 4 / MF 4 / ST 3.\n"
            f"• Qualität: 40 Punkte – {metric}. 0,5x Median = 0, 1,0x = 20, 1,5x = 40.\n"
            "• Eigene Rolle: 15 Punkte – STAMM 15 / OFFEN 10 / INVEST 9 / TRANSFERLISTE 2.\n"
            "• Marktwerttrend: 20 Punkte – auf Tagesrate normalisierte 24h-, 3-, 7- und 14-Tage-Entwicklung inklusive Trendbeschleunigung."
        )
        txt.setObjectName("Subtle"); txt.setWordWrap(True); sl.addWidget(txt); layout.addWidget(squad)

        inv = QFrame(); inv.setObjectName("Panel")
        il = QVBoxLayout(inv); il.setContentsMargins(16, 14, 16, 14); il.setSpacing(7)
        it = QLabel("INVESTMENT · 0–100"); it.setObjectName("SectionTitle"); il.addWidget(it)
        itxt = QLabel(
            "• Marktwert-Momentum: 50 Punkte – 24h / 3 / 7 / 14 Tage werden auf eine Tagesrate normalisiert; Beschleunigung wird separat berücksichtigt.\n"
            "• Rendite seit Einstieg: 30 Punkte – -10 % = 0, 0 % = 15, +10 % oder besser = 30.\n"
            "• Momentum-Konsistenz: 20 Punkte – wie viele der verfügbaren Zeitfenster positiv sind.\n\n"
            "Der Investmentwert bewertet bewusst die Marktwert-/Trading-Situation und nicht den Positionsbedarf."
        )
        itxt.setObjectName("Subtle"); itxt.setWordWrap(True); il.addWidget(itxt); layout.addWidget(inv)

        sell = QFrame(); sell.setObjectName("Panel")
        vl = QVBoxLayout(sell); vl.setContentsMargins(16, 14, 16, 14); vl.setSpacing(7)
        vt = QLabel("VERKAUFSBEREITSCHAFT · 0–100"); vt.setObjectName("SectionTitle"); vl.addWidget(vt)
        vtxt = QLabel(
            "• Ersetzbarkeit: 30 Punkte – Positionsbreite plus Qualität relativ zum Positionsmedian.\n"
            "• Kapitalfreisetzung: 20 Punkte – Marktwert relativ zum Medianwert deines gesamten Kaders.\n"
            "• Schwacher Analyse-Score: 25 Punkte – je niedriger der Analyse-Score, desto höher dieser Anteil.\n"
            "• Schwaches Investment: 15 Punkte – fallende/unattraktive Investments werden eher verkaufbar.\n"
            "• Eigene Rolle: 10 Punkte – TRANSFERLISTE 10 / OFFEN 5 / INVEST 2 / STAMM 0."
        )
        vtxt.setObjectName("Subtle"); vtxt.setWordWrap(True); vl.addWidget(vtxt); layout.addWidget(sell)

        decision = QFrame(); decision.setObjectName("Panel")
        dl = QVBoxLayout(decision); dl.setContentsMargins(16, 14, 16, 14); dl.setSpacing(7)
        dt = QLabel("VERKAUFSENTSCHEIDUNG"); dt.setObjectName("SectionTitle"); dl.addWidget(dt)
        dtxt = QLabel(
            "Aus der Verkaufsbereitschaft wird zusätzlich eine konkrete Handlungsempfehlung abgeleitet. "
            "Dafür werden vier Dinge kombiniert:\n"
            "• Basis aus Ersetzbarkeit, Kapitalfreisetzung, Rolle und Investmentlage.\n"
            "• MW-Exit-Signal: mehrere negative 1/3/7/14-Tage-Fenster und abbremsendes Momentum.\n"
            "• Gewinnmitnahme: vorhandener Buchgewinn erhöht den Verkaufsdruck moderat; ein Verlust allein ist ausdrücklich kein Verkaufsgrund.\n"
            "• Aktuelle Markt-Alternative: gibt es einen finanzierbaren Spieler derselben Position, der dein Team messbar verbessert?\n\n"
            "HALTEN < 52 · VERKAUF PRÜFEN ab 52 · EHER VERKAUFEN ab 64 · JETZT VERKAUFEN ab 82. "
            "JETZT VERKAUFEN benötigt zusätzlich einen echten Auslöser wie fallendes Momentum, Transferlisten-Rolle oder eine konkrete Markt-Alternative."
        )
        dtxt.setObjectName("Subtle"); dtxt.setWordWrap(True); dl.addWidget(dtxt); layout.addWidget(decision)

        sig = QFrame(); sig.setObjectName("Panel")
        gl = QVBoxLayout(sig); gl.setContentsMargins(16, 14, 16, 14); gl.setSpacing(6)
        gt = QLabel("SIGNAL"); gt.setObjectName("SectionTitle"); gl.addWidget(gt)
        gtxt = QLabel(
            "KERN-SPIELER: Analyse-Score ≥ 80 und Verkaufsbereitschaft < 40\n"
            "INVESTMENT HALTEN: Investment ≥ 75 und Verkaufsbereitschaft < 55\n"
            "VERKAUFSKANDIDAT: Verkaufsbereitschaft ≥ 75\n"
            "UPGRADE-KANDIDAT: Analyse-Score < 50 und Verkaufsbereitschaft ≥ 60\n"
            "HALTEN: Analyse-Score ≥ 65\n"
            "BEOBACHTEN: übriger Bereich"
        )
        gtxt.setObjectName("Subtle"); gtxt.setWordWrap(True); gl.addWidget(gtxt); layout.addWidget(sig)

        note_text = "Laufende Saison: aktuelle Ø-Punkte fließen in die Qualitätsbewertung ein." if points_are_current else "Preseason: alte Saisonpunkte werden nicht verwendet. Die relative Qualität wird vor Saisonstart über den aktuellen Marktwert gemessen."
        note = QLabel(note_text + " Jede Score-Zelle zeigt per Hover die exakte Punkte-Aufschlüsselung des Spielers.")
        note.setObjectName("Tiny"); note.setWordWrap(True); layout.addWidget(note)
        layout.addStretch()

class MarketScoringInfoDialog(QDialog):
    """Explain the exact market scoring model shown in the MARKT tab."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("So funktioniert die Markt-Einschätzung")
        self.resize(760, 680)
        self.setMinimumSize(650, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel("MARKT-EINSCHÄTZUNG")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Die Scores bleiben intern nachvollziehbar; die eigentliche Entscheidung nutzt zusätzlich Replacement Value, Max-Bid, Investment-Horizont und Datenbasis.")
        subtitle.setObjectName("Subtle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        fit = QFrame(); fit.setObjectName("Panel")
        fit_l = QVBoxLayout(fit); fit_l.setContentsMargins(16,14,16,14); fit_l.setSpacing(7)
        fit_t = QLabel("ANALYSE-SCORE · 0–100"); fit_t.setObjectName("SectionTitle")
        fit_l.addWidget(fit_t)
        fit_text = QLabel(
            "• Spielerqualität: 55 Punkte – rein sportlicher Vergleich mit deinen eigenen Spielern derselben Position; in der Saison über Ø Punkte, in der Preseason nur als Marktwert-Proxy.\n"
            "• Positionsbedarf: 20 Punkte – reine Kaderbreite gegen Zieltiefe TW 2 / ABW 4 / MF 4 / ST 3.\n"
            "• Replacement: 25 Punkte – Kandidat gegen deine schwächste eigene Option derselben Position.\n\n"
            "Preis, Budget und künstliche Marktknappheit beeinflussen diesen Kader-Score bewusst nicht mehr."
        )
        fit_text.setObjectName("Subtle"); fit_text.setWordWrap(True)
        fit_l.addWidget(fit_text)
        layout.addWidget(fit)

        inv = QFrame(); inv.setObjectName("Panel")
        inv_l = QVBoxLayout(inv); inv_l.setContentsMargins(16,14,16,14); inv_l.setSpacing(7)
        inv_t = QLabel("INVESTMENT-CHANCE · 0–100"); inv_t.setObjectName("SectionTitle")
        inv_l.addWidget(inv_t)
        inv_text = QLabel(
            "Preseason: Preis/MW 55 · MW-Momentum 45. Alte Saisonpunkte werden nicht verwendet.\n"
            "Laufende Saison: Performance 35 · Preis/MW 35 · MW-Momentum 30.\n\n"
            "Die drei Blöcke sind bewusst getrennt. Fair Value und Punkte/Mio sind aus der Entscheidungslogik entfernt, damit derselbe Preis nicht mehrfach gewertet wird. MW-Momentum nutzt nicht überlappende Teilfenster (1T, Tage 2–3, 4–7, 8–14) und erkennt Beschleunigung aus den letzten 3 Tagen gegenüber den vorherigen 4 Tagen. Liga-Deals bleiben nur Kontext und verändern den Score nicht."
        )
        inv_text.setObjectName("Subtle"); inv_text.setWordWrap(True)
        inv_l.addWidget(inv_text)
        layout.addWidget(inv)

        signals = QFrame(); signals.setObjectName("Panel")
        sig_l = QVBoxLayout(signals); sig_l.setContentsMargins(16,14,16,14); sig_l.setSpacing(6)
        sig_t = QLabel("SIGNAL"); sig_t.setObjectName("SectionTitle"); sig_l.addWidget(sig_t)
        sig_text = QLabel(
            "KAUFEN: ausführbares Mindestgebot (mindestens aktueller MW) ≤ Max-Bid und beide Kernbewertungen sind mindestens solide.\n"
            "TOP-CHANCE / KADER-UPGRADE / INVEST-CHANCE: starke Einzel- oder Kombinationssignale, solange der Preis nicht klar oberhalb des Max-Bid liegt.\n"
            "KAUFPRÜFUNG: mindestens ein Kernbereich ≥ 60.\n"
            "BEOBACHTEN: neutraler Bereich oder noch zu wenig Evidenz.\n"
            "PASSEN: schwache Kombination, Mindestgebot > Max-Bid oder ausführbarer Preis > 108 % des Max-Bid."
        )
        sig_text.setObjectName("Subtle"); sig_text.setWordWrap(True); sig_l.addWidget(sig_text)
        layout.addWidget(signals)

        decision = QFrame(); decision.setObjectName("Panel")
        dl = QVBoxLayout(decision); dl.setContentsMargins(16,14,16,14); dl.setSpacing(6)
        dt = QLabel("ENTSCHEIDUNGSLAYER"); dt.setObjectName("SectionTitle"); dl.addWidget(dt)
        dtext = QLabel(
            "• Replacement Value – Kandidat gegen deine schwächste realistische Option derselben Position; in der Saison über Ø Punkte, Preseason nur als Marktwert-Proxy.\n"
            "• Mindestgebot – in dieser Liga muss ein Gebot mindestens dem aktuellen Marktwert entsprechen; Listings darunter werden nicht als Schnäppchen gewertet.\n"
            "• Max-Bid – aktueller Marktwert plus klar begründetes Premium: bis +3 % für starkes Trading-Setup, +3 % für klaren Kader-Upgrade und +2 % für starkes MW-Momentum. Gesamtdeckel: +8 %.\n"
            "• Investment-Horizont – FLIP 1–3T, TRADING 1W, HOLD oder kein klares Setup; basiert ausschließlich auf beobachtbarem Preis/MW und MW-Momentum.\n"
            "• Datenbasis – HOCH / MITTEL / GERING anhand vorhandener MW-Historie, Liga-Deals und aktueller Leistungsdaten. Das ist keine Erfolgswahrscheinlichkeit.\n"
            "• Backtesting – BUY- und PASS-Empfehlungen werden nach 7 Tagen getrennt ausgewertet. Entscheidend ist der Rendite-Spread; ein BUY zählt erst ab +1 % als Richtungs-Treffer."
        )
        dtext.setObjectName("Subtle"); dtext.setWordWrap(True); dl.addWidget(dtext); layout.addWidget(decision)

        note = QLabel("Die Empfehlung kann deshalb trotz hoher Einzel-Scores auf PASSEN wechseln, wenn der aktuelle Preis klar über dem berechneten Max-Bid liegt. Werte mit geringer Datenbasis sollten vorsichtiger interpretiert werden.")
        note.setObjectName("Tiny"); note.setWordWrap(True); layout.addWidget(note)
        layout.addStretch()

class PreseasonOptimizerDialog(QDialog):
    def __init__(self, parent, result: dict, budget: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("Startkader-Optimizer")
        self.resize(860, 680)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 18)
        root.setSpacing(10)

        title = QLabel("STARTKADER-OPTIMIZER")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        if not result.get("feasible"):
            info = QLabel(
                "Mit aktuellem Kader, aktuellem Transfermarkt und verfügbarem Budget konnte keine vollständige "
                "11 für eine erlaubte Formation gebaut werden. Der Optimizer erfindet keine nicht gelisteten Spieler."
            )
            info.setObjectName("Subtle")
            info.setWordWrap(True)
            root.addWidget(info)
            close = QPushButton("SCHLIESSEN")
            close.clicked.connect(self.accept)
            root.addWidget(close, 0, Qt.AlignRight)
            return

        summary = QFrame(); summary.setObjectName("Panel")
        grid = QGridLayout(summary); grid.setContentsMargins(14, 12, 14, 12); grid.setSpacing(8)
        values = [
            ("FORMATION", str(result.get("formation") or "–")),
            ("TEAM-SCORE", f"{float(result.get('score') or 0):.1f}/100"),
            ("NEUE KÄUFE", str(int(result.get("market_buys") or 0))),
            ("VERKÄUFE NÖTIG", str(int(result.get("required_sales") or 0))),
            ("AUSGABEN", euro(result.get("spent"))),
            ("RESTBUDGET", euro(result.get("remaining"))),
        ]
        for i, (caption, value) in enumerate(values):
            cap=QLabel(caption); cap.setObjectName("Tiny")
            val=QLabel(value); val.setObjectName("MarketDetailValue")
            grid.addWidget(cap, 0, i)
            grid.addWidget(val, 1, i)
        root.addWidget(summary)

        current_size = int(result.get("current_squad_size") or 0)
        max_size = int(result.get("max_squad_size") or MAX_SQUAD_SIZE)
        note = QLabel(
            "Optimiert nur mit deinem aktuellen Kader + aktuell gelisteten Marktspielern. Eigene Spieler kosten 0 € zusätzlich; "
            "Marktspieler werden mit dem effektiv nötigen Mindestpreis gerechnet. Maximal 6 neue Käufe. "
            f"Kadergrenze: {current_size}/{max_size}; jeder Zugang oberhalb der freien Plätze benötigt einen Abgang."
        )
        note.setObjectName("Tiny"); note.setWordWrap(True)
        root.addWidget(note)

        sales_needed = int(result.get("required_sales") or 0)
        sale_candidates = list(result.get("sale_candidates") or [])
        if sales_needed:
            names = ", ".join(str(p.get("name") or p.get("full_name") or "–") for p in sale_candidates)
            roster_warning = QLabel(
                f"KADERPLÄTZE: Für diese Variante sind {sales_needed} Verkauf/Verkäufe nötig."
                + (f" Naheliegende Abgänge außerhalb der optimierten XI: {names}." if names else "")
            )
            roster_warning.setObjectName("FinanceWarning")
            roster_warning.setWordWrap(True)
            root.addWidget(roster_warning)

        table = QTableWidget()
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels(["SPIELER", "VEREIN", "POS", "QUELLE", "SCORE", "KOSTEN", "ROLLE"])
        table.setRowCount(len(result.get("players") or []))
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        for r, player in enumerate(result.get("players") or []):
            source = str(player.get("optimizer_source") or "")
            role = str(player.get("portfolio_role") or player.get("action") or player.get("player_role") or "–")
            cells = [
                str(player.get("full_name") or player.get("name") or "–"),
                str(player.get("club") or "–"),
                str(player.get("position") or "–"),
                "NEU KAUFEN" if source == "MARKT" else "DEIN KADER",
                f"{float(player.get('optimizer_score') or 0):.1f}",
                euro(player.get("optimizer_cost")) if source == "MARKT" else "–",
                role,
            ]
            for c, value in enumerate(cells):
                item=QTableWidgetItem(value)
                if c == 3:
                    item.setForeground(QColor("#62E49A") if source == "KADER" else QColor("#F3C44E"))
                table.setItem(r,c,item)
        root.addWidget(table, 1)
        close = QPushButton("SCHLIESSEN")
        close.clicked.connect(self.accept)
        root.addWidget(close, 0, Qt.AlignRight)

class MarketBidDialog(QDialog):
    """Compact editor for a real Kickbase market offer."""

    def __init__(self, parent, player: dict, *, squad_value: int, balance_after_bids: int) -> None:
        super().__init__(parent)
        self.player = dict(player or {})
        self.market_value = int(self.player.get("market_value") or 0)
        self.existing_bid = int(self.player.get("own_bid") or 0)
        self.capacity = calculate_bid_capacity(
            squad_value, balance_after_bids, existing_bid=self.existing_bid
        )
        self.amount = 0
        self.setWindowTitle("Gebot abgeben")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        name = QLabel(str(self.player.get("full_name") or self.player.get("name") or "Spieler"))
        name.setObjectName("SectionTitle")
        layout.addWidget(name)

        info = QLabel(
            f"Marktwert: {euro(self.market_value)}   ·   Anbieter: "
            f"{self.player.get('seller_name') or ('Kickbase' if self.player.get('is_kickbase') else 'Manager')}"
        )
        info.setObjectName("Subtle")
        layout.addWidget(info)

        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("Gebot in €")
        default_amount = max(self.market_value, self.existing_bid)
        self.amount_edit.setText(str(default_amount))
        self.amount_edit.textChanged.connect(self._refresh)
        layout.addWidget(self.amount_edit)

        quick = QHBoxLayout()
        for label, factor in (("MW", 1.0), ("+1 %", 1.01), ("+2 %", 1.02), ("+5 %", 1.05)):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, f=factor: self._set_quick(f))
            quick.addWidget(button)
        layout.addLayout(quick)

        self.rule_label = QLabel()
        self.rule_label.setWordWrap(True)
        self.rule_label.setObjectName("Subtle")
        layout.addWidget(self.rule_label)

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)

        actions = QHBoxLayout()
        cancel = QPushButton("ABBRECHEN")
        cancel.clicked.connect(self.reject)
        self.submit = QPushButton("GEBOT PRÜFEN")
        self.submit.clicked.connect(self._accept_if_valid)
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(self.submit)
        layout.addLayout(actions)
        self._refresh()

    def _parsed_amount(self) -> int:
        raw = self.amount_edit.text().strip().replace(".", "").replace(" ", "").replace("€", "")
        try:
            return int(raw)
        except ValueError:
            return 0

    @staticmethod
    def _round_listing_price_up(market_value: int, percent_value: int = 100) -> int:
        """Return a whole-€1k listing price that never undershoots the target."""
        if market_value <= 0 or percent_value <= 0:
            return 0
        target = (int(market_value) * int(percent_value) + 99) // 100
        return ((target + 999) // 1000) * 1000

    def _set_quick(self, percent_value: int) -> None:
        self.amount_edit.setText(str(self._round_listing_price_up(self.market_value, percent_value)))

    def _refresh(self) -> None:
        amount = self._parsed_amount()
        after = self.capacity.effective_balance - amount
        self.rule_label.setText(
            f"Kontostand nach Gebot: {euro(after)}\n"
            f"33%-Grenze: {euro(self.capacity.minimum_balance)}   ·   "
            f"Max. neues Gebot: {euro(self.capacity.maximum_new_bid)}"
        )
        problems = []
        if amount <= 0:
            problems.append("Bitte ein gültiges Gebot eingeben.")
        if self.market_value and amount < self.market_value:
            problems.append(f"Gebot muss mindestens dem aktuellen Marktwert ({euro(self.market_value)}) entsprechen.")
        if amount > self.capacity.maximum_new_bid:
            problems.append("Dieses Gebot würde die lokale 33%-Kreditgrenze überschreiten.")
        self.warning.setText("\n".join(problems) if problems else "✓ Gebot liegt innerhalb der lokalen Prüfregeln.")
        self.warning.setStyleSheet("color: #FF7A80;" if problems else "color: #62E49A;")
        self.submit.setEnabled(not problems)

    def _accept_if_valid(self) -> None:
        self._refresh()
        if not self.submit.isEnabled():
            return
        self.amount = self._parsed_amount()
        self.accept()

class SellPlayerDialog(QDialog):
    """Choose a real Kickbase listing price for an owned player."""

    def __init__(self, parent, player: dict, *, initial_price: int | None = None) -> None:
        super().__init__(parent)
        self.player = dict(player or {})
        self.market_value = int(self.player.get("market_value") or 0)
        self.amount = 0
        self.setWindowTitle("Spieler verkaufen")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        name = QLabel(str(self.player.get("full_name") or self.player.get("name") or "Spieler"))
        name.setObjectName("SectionTitle")
        layout.addWidget(name)
        meta = QLabel(f"Marktwert: {euro(self.market_value)}")
        meta.setObjectName("Subtle")
        layout.addWidget(meta)

        self.amount_edit = QLineEdit(str(int(initial_price or self.market_value or 0)))
        self.amount_edit.setPlaceholderText("Listenpreis in €")
        self.amount_edit.textChanged.connect(self._refresh)
        layout.addWidget(self.amount_edit)

        quick = QHBoxLayout()
        for label, percent_value in (("MW", 100), ("+2 %", 102), ("+5 %", 105), ("+10 %", 110)):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, p=percent_value: self._set_quick(p))
            quick.addWidget(btn)
        layout.addLayout(quick)

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel = QPushButton("ABBRECHEN")
        cancel.clicked.connect(self.reject)
        self.submit = QPushButton("VERKAUF PRÜFEN")
        self.submit.setObjectName("Primary")
        self.submit.clicked.connect(self._accept_if_valid)
        actions.addWidget(cancel)
        actions.addWidget(self.submit)
        layout.addLayout(actions)
        self._refresh()

    def _parsed_amount(self) -> int:
        raw = self.amount_edit.text().strip().replace(".", "").replace(" ", "").replace("€", "")
        try:
            return int(raw)
        except ValueError:
            return 0

    def _set_quick(self, percent_value: int) -> None:
        self.amount_edit.setText(str(listing_price_for_percent(self.market_value, percent_value)))

    def _refresh(self) -> None:
        amount = self._parsed_amount()
        problems = []
        if amount <= 0:
            problems.append("Bitte einen gültigen Verkaufspreis eingeben.")
        if self.market_value and amount < self.market_value:
            problems.append("Der Listenpreis liegt unter dem aktuellen Marktwert.")
        self.warning.setText("\n".join(problems) if problems else f"✓ Listenpreis: {euro(amount)}")
        self.warning.setStyleSheet("color: #FF7A80;" if problems else "color: #62E49A;")
        self.submit.setEnabled(not problems)

    def _accept_if_valid(self) -> None:
        self._refresh()
        if not self.submit.isEnabled():
            return
        self.amount = self._parsed_amount()
        self.accept()

class ListingManagementDialog(QDialog):
    """Manage one own listing. Offer actions stay visible but disabled until verified."""

    def __init__(self, parent, client: KickbaseClient, league_id: str, player: dict, refresh_callback=None) -> None:
        super().__init__(parent)
        self.client = client
        self.league_id = str(league_id)
        self.player = dict(player or {})
        self.player_id = str(self.player.get("player_id") or "")
        self.refresh_callback = refresh_callback
        self.setWindowTitle("Verkauf verwalten")
        self.setMinimumWidth(620)
        self.resize(680, 430)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        title = QLabel(str(self.player.get("full_name") or self.player.get("name") or "Spieler"))
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        self.meta = QLabel(
            f"Marktwert {euro(self.player.get('market_value'))} · Listenpreis {euro(self.player.get('listing_price') or self.player.get('price'))}"
        )
        self.meta.setObjectName("Subtle")
        root.addWidget(self.meta)

        listing_actions = QHBoxLayout()
        change_price = QPushButton("PREIS ÄNDERN")
        change_price.clicked.connect(self._change_price)
        remove = QPushButton("VOM MARKT NEHMEN")
        remove.clicked.connect(self._remove_listing)
        listing_actions.addWidget(change_price)
        listing_actions.addWidget(remove)
        listing_actions.addStretch()
        root.addLayout(listing_actions)

        offers_title = QLabel("ANGEBOTS-CENTER")
        offers_title.setObjectName("SectionTitle")
        root.addWidget(offers_title)

        info = QLabel(
            "Manager-Angebote sind vorbereitet, aber weiterhin deaktiviert, bis deren echte Requests verifiziert sind. "
            "Der separate Verkauf an Kickbase ist inzwischen verifiziert und bewusst davon getrennt."
        )
        info.setObjectName("Subtle")
        info.setWordWrap(True)
        root.addWidget(info)

        offer_box = QFrame()
        offer_box.setObjectName("MarketDetailBox")
        offer_layout = QVBoxLayout(offer_box)
        offer_layout.setContentsMargins(12, 10, 12, 10)
        offer_layout.setSpacing(8)

        status = QLabel("Noch keine verifizierten Angebotsdaten geladen.")
        status.setObjectName("Subtle")
        offer_layout.addWidget(status)

        offer_actions = QHBoxLayout()
        load_offers = QPushButton("ANGEBOTE LADEN")
        accept_offer = QPushButton("AUSGEWÄHLTES ANNEHMEN")
        decline_offer = QPushButton("AUSGEWÄHLTES ABLEHNEN")
        accept_offer.setObjectName("Primary")
        for button in (load_offers, accept_offer, decline_offer):
            button.setEnabled(False)
            button.setToolTip("Noch nicht verifiziert – wird nach dem Mitschnitt der offiziellen Kickbase-App freigeschaltet.")
            offer_actions.addWidget(button)
        offer_actions.addStretch()
        offer_layout.addLayout(offer_actions)
        root.addWidget(offer_box)

        kickbase_box = QFrame()
        kickbase_box.setObjectName("MarketDetailBox")
        kickbase_layout = QVBoxLayout(kickbase_box)
        kickbase_layout.setContentsMargins(12, 10, 12, 10)
        kickbase_layout.setSpacing(8)

        kickbase_title = QLabel("KICKBASE-ANGEBOT")
        kickbase_title.setObjectName("SectionMini")
        kickbase_layout.addWidget(kickbase_title)

        kickbase_hint = QLabel(
            "Verkauft den Spieler direkt an Kickbase über den verifizierten /sell-Request. "
            "Das ist ausdrücklich kein Manager-Gebot und lässt sich nach dem Verkauf nicht über KickTrack rückgängig machen."
        )
        kickbase_hint.setObjectName("Subtle")
        kickbase_hint.setWordWrap(True)
        kickbase_layout.addWidget(kickbase_hint)

        kickbase_actions = QHBoxLayout()
        sell_to_kickbase = QPushButton("AN KICKBASE VERKAUFEN")
        sell_to_kickbase.setObjectName("DangerSecondary")
        sell_to_kickbase.setToolTip("Aktuelles Kickbase-Angebot annehmen und den Spieler direkt an Kickbase verkaufen")
        sell_to_kickbase.clicked.connect(self._sell_to_kickbase)
        kickbase_actions.addWidget(sell_to_kickbase)
        kickbase_actions.addStretch()
        kickbase_layout.addLayout(kickbase_actions)
        root.addWidget(kickbase_box)

        root.addStretch()
        close = QPushButton("SCHLIESSEN")
        close.clicked.connect(self.accept)
        root.addWidget(close, 0, Qt.AlignRight)

    def _after_write(self) -> None:
        if callable(self.refresh_callback):
            self.refresh_callback()

    def _change_price(self) -> None:
        initial = int(self.player.get("listing_price") or self.player.get("price") or self.player.get("market_value") or 0)
        dialog = SellPlayerDialog(self, self.player, initial_price=initial)
        if dialog.exec() != QDialog.Accepted:
            return
        amount = int(dialog.amount or 0)
        if QMessageBox.question(self, "Preis ändern?", f"Listenpreis wirklich auf {euro(amount)} setzen?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.client.set_transfer_price(self.league_id, self.player_id, amount)
        except Exception as exc:
            QMessageBox.warning(self, "Preisänderung fehlgeschlagen", str(exc))
            return
        self.player["listing_price"] = amount
        self.player["price"] = amount
        self.meta.setText(f"Marktwert {euro(self.player.get('market_value'))} · Listenpreis {euro(amount)}")
        self._after_write()

    def _remove_listing(self) -> None:
        if QMessageBox.question(self, "Vom Markt nehmen?", "Spieler wirklich von deiner Transferliste entfernen?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.client.remove_player_from_market(self.league_id, self.player_id)
        except Exception as exc:
            QMessageBox.warning(self, "Entfernen fehlgeschlagen", str(exc))
            return
        self._after_write()
        self.accept()

    def _sell_to_kickbase(self) -> None:
        name = str(self.player.get("full_name") or self.player.get("name") or "Spieler")
        message = (
            f"{name} wirklich direkt an Kickbase verkaufen?\n\n"
            "Dieser Button nimmt ausschließlich das aktuelle Kickbase-Angebot an. "
            "Manager-Gebote werden damit nicht ausgewählt oder angenommen.\n\n"
            "Der Verkauf ist eine echte schreibende Aktion und kann in KickTrack nicht rückgängig gemacht werden."
        )
        if QMessageBox.warning(
            self,
            "An Kickbase verkaufen?",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            self.client.accept_kickbase_sale_offer(self.league_id, self.player_id)
        except Exception as exc:
            QMessageBox.warning(self, "Verkauf an Kickbase fehlgeschlagen", str(exc))
            return
        QMessageBox.information(self, "Verkauft", f"{name} wurde an Kickbase verkauft.")
        self._after_write()
        self.accept()

class FinancingScenarioDialog(QDialog):
    """Explain whether a market player is affordable and how sales could fund it."""

    def __init__(self, parent, target: dict, available_budget: int, squad: list[dict]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Finanzierungsszenario")
        self.resize(760, 620)
        self.setMinimumSize(650, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        title = QLabel(str(target.get("full_name") or target.get("name") or "Spieler"))
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            f"{target.get('club') or '–'} · {target.get('position') or '–'} · Zielpreis {euro(target.get('price'))}"
        )
        subtitle.setObjectName("Subtle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        result = financing_scenarios(int(target.get("price") or 0), int(available_budget or 0), squad)
        capacity = squad_capacity(squad)

        summary = QFrame()
        summary.setObjectName("Panel")
        summary_layout = QGridLayout(summary)
        summary_layout.setContentsMargins(16, 14, 16, 14)
        summary_layout.setHorizontalSpacing(20)
        summary_layout.setVerticalSpacing(6)
        values = [
            ("FREIES BUDGET", euro(available_budget)),
            ("KAUFPREIS", euro(target.get("price"))),
            ("FEHLBETRAG", euro(result.get("gap"))),
        ]
        for idx, (cap, val) in enumerate(values):
            box = QVBoxLayout()
            c = QLabel(cap); c.setObjectName("CardCaption")
            v = QLabel(val); v.setObjectName("CardValue")
            box.addWidget(c); box.addWidget(v)
            summary_layout.addLayout(box, 0, idx)
        layout.addWidget(summary)

        if result["directly_affordable"]:
            state_text = f"Direkt finanzierbar · danach {euro(result.get('remaining_budget'))} Restbudget"
            if capacity.is_full:
                state_text += f" · ABER KADER {capacity.current}/{capacity.maximum}: vor dem Zugang ist ein Verkauf nötig"
            state = QLabel(state_text)
            state.setObjectName("FinanceSuccess")
            state.setWordWrap(True)
            layout.addWidget(state)
        else:
            state = QLabel(
                f"Es fehlen {euro(result.get('gap'))}. Mögliche Verkäufe werden mit dem aktuellen Marktwert gerechnet."
            )
            state.setObjectName("FinanceWarning")
            state.setWordWrap(True)
            layout.addWidget(state)

            scenarios = result.get("scenarios") or []
            if scenarios:
                section = QLabel("MÖGLICHE SZENARIEN")
                section.setObjectName("SectionTitle")
                layout.addWidget(section)
                for idx, scenario in enumerate(scenarios[:5], start=1):
                    card = QFrame()
                    card.setObjectName("FinanceScenarioCard")
                    row = QHBoxLayout(card)
                    row.setContentsMargins(14, 11, 14, 11)
                    row.setSpacing(12)
                    names = " + ".join(p["name"] for p in scenario["players"])
                    left = QVBoxLayout()
                    name = QLabel(f"{idx}. {names}")
                    name.setObjectName("FinanceScenarioName")
                    meta = QLabel(
                        f"Verkaufswert {euro(scenario['sale_value'])} · Rest danach {euro(scenario['remaining_budget'])}"
                    )
                    meta.setObjectName("Tiny")
                    left.addWidget(name)
                    left.addWidget(meta)
                    row.addLayout(left, 1)
                    role_text = ", ".join(p.get("role") or "OFFEN" for p in scenario["players"])
                    roles = QLabel(role_text)
                    roles.setObjectName("FinanceRole")
                    row.addWidget(roles)
                    layout.addWidget(card)
            else:
                no_result = QLabel("Mit maximal drei Verkäufen reicht der aktuelle Kaderwert für dieses Szenario nicht aus.")
                no_result.setObjectName("FinanceWarning")
                no_result.setWordWrap(True)
                layout.addWidget(no_result)

        note = QLabel("Hinweis: Das ist eine Szenariorechnung mit aktuellen Marktwerten, keine Garantie für real erzielbare Verkaufspreise.")
        note.setObjectName("Tiny")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

class LineupOptimizerDialog(QDialog):
    FORMATION_ORDER = ("3-4-3", "3-5-2", "3-6-1", "4-2-4", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1")

    def __init__(self, parent, players: list[dict], fixture_payload: dict, table_payload: dict, lineup_payload: dict | None = None, *, points_are_current: bool, performance_payloads: dict[str, dict] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lineup Optimizer")
        self.resize(760, 680)
        self.setMinimumSize(660, 560)
        self.players = list(players or [])
        self.points_are_current = points_are_current

        self.fixture_by_team: dict[str, list[dict]] = {}
        for player in self.players:
            tid = str(player.get("team_id") or "")
            if tid and tid not in self.fixture_by_team:
                self.fixture_by_team[tid] = fixture_run(tid, fixture_payload, table_payload, 3)
        if not points_are_current:
            for run in self.fixture_by_team.values():
                for fixture in run:
                    fixture["ease"] = 50
                    fixture["adjusted_ease"] = 50
                    fixture["opponent_place"] = None

        performance_payloads = performance_payloads or {}
        self.form_by_player = {
            str(player_id): player_form(payload)
            for player_id, payload in performance_payloads.items()
            if isinstance(payload, dict)
        }
        lineup_items = lineup_payload.get("it", []) if isinstance(lineup_payload, dict) else []
        self.current_ids = {str(item.get("i") or item.get("pi") or "") for item in lineup_items if isinstance(item, dict)}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)
        title = QLabel("EMPFOHLENE XI")
        title.setObjectName("PageTitle")
        sub = QLabel(
            "Read-only Simulation · Form/Saisonleistung, nächste Gegner, Status und Marktwert als Preseason-Tiebreaker"
            if points_are_current else
            "Read-only Simulation · Preseason ohne alte Saisonpunkte; Gegner, Status und Marktwert dienen als Orientierung"
        )
        sub.setObjectName("Subtle")
        sub.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(sub)

        formation_row = QHBoxLayout()
        formation_label = QLabel("FORMATION")
        formation_label.setObjectName("Tiny")
        self.formation_combo = QComboBox()
        self.formation_combo.setMinimumWidth(245)
        self.formation_combo.addItem("AUTO · BESTE XI", None)
        self._populate_formations()
        formation_row.addWidget(formation_label)
        formation_row.addWidget(self.formation_combo)
        formation_row.addStretch(1)
        root.addLayout(formation_row)

        self.meta = QLabel()
        self.meta.setObjectName("SectionTitle")
        root.addWidget(self.meta)

        self.table = ResponsiveTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["POS", "SPIELER", "VEREIN", "MW", "FORM", "NÄCHSTER GEGNER", "OPT-SCORE", "AKTUELL"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.set_responsive_widths([65, 205, 145, 120, 115, 160, 95, 85], [58, 165, 120, 105, 95, 135, 80, 75])
        root.addWidget(self.table, 1)

        self.note = QLabel("Die Aufstellung wird nicht an Kickbase übertragen. Sie ist eine transparente Entscheidungshilfe und kein automatischer Schreibzugriff.")
        self.note.setObjectName("Tiny")
        self.note.setWordWrap(True)
        root.addWidget(self.note)

        self.formation_combo.currentIndexChanged.connect(self._refresh_lineup)
        self._refresh_lineup()

    def _populate_formations(self) -> None:
        counts = {pos: 0 for pos in ("TW", "ABW", "MF", "ST")}
        for player in self.players:
            pos = str(player.get("position") or "")
            if pos in counts:
                counts[pos] += 1

        from .intelligence import VALID_FORMATIONS
        model = self.formation_combo.model()
        for formation in self.FORMATION_ORDER:
            needs = VALID_FORMATIONS[formation]
            missing = {pos: need - counts[pos] for pos, need in needs.items() if counts[pos] < need}
            if missing:
                labels = {"TW": "TW", "ABW": "ABW", "MF": "MF", "ST": "ST"}
                detail = ", ".join(f"{amount}× {labels[pos]}" for pos, amount in missing.items())
                self.formation_combo.addItem(f"{formation} · nicht möglich ({detail} fehlt)", formation)
                item = model.item(self.formation_combo.count() - 1)
                if item is not None:
                    item.setEnabled(False)
            else:
                self.formation_combo.addItem(formation, formation)

    def _refresh_lineup(self, *_args) -> None:
        formation = self.formation_combo.currentData()
        result = optimize_lineup(
            self.players,
            form_by_player=self.form_by_player,
            fixture_by_team=self.fixture_by_team,
            points_are_current=self.points_are_current,
            formation=formation,
        )

        if result.get("feasible"):
            prefix = "AUTO → " if formation is None else ""
            self.meta.setText(f"Formation {prefix}{result['formation']} · Team-Score {result['score']:.1f}")
        else:
            missing = result.get("missing") or {}
            detail = ", ".join(f"{amount}× {pos}" for pos, amount in missing.items())
            if detail:
                self.meta.setText(f"Formation {result['formation']} · nicht möglich · es fehlt {detail}")
            else:
                self.meta.setText(f"Keine vollständige legale XI möglich · Vorschau {result['formation']}")

        rows = result.get("players") or []
        self.table.setRowCount(len(rows))
        for r, player in enumerate(rows):
            fixtures = self.fixture_by_team.get(str(player.get("team_id") or ""), [])
            nxt = fixtures[0] if fixtures else None
            opponent = "–"
            if nxt:
                opponent = ("vs " if nxt.get("home_game") else "@ ") + str(nxt.get("opponent") or "–")
            form = self.form_by_player.get(str(player.get("player_id") or ""), {})
            form_display = "–"
            if self.points_are_current and form.get("last3_avg") is not None:
                form_display = f"{float(form['last3_avg']):.0f} · {form.get('risk_label') or '–'}"
            values = [
                player.get("position") or "–",
                player.get("name") or "–",
                player.get("club") or "–",
                euro(player.get("market_value")),
                form_display,
                opponent,
                f"{float(player.get('optimizer_score') or 0):.1f}",
                "✓" if str(player.get("player_id") or "") in self.current_ids else "NEU",
            ]
            for c, value in enumerate(values):
                item = table_item(value)
                item.setData(Qt.UserRole, player.get("player_id"))
                self.table.setItem(r, c, item)

class MarketScannerDialog(QDialog):
    """League-wide market-value scanner backed by cached 365-day histories."""

    def __init__(self, parent, rows: list[dict]) -> None:
        super().__init__(parent)
        self.rows = list(rows or [])
        self.setWindowTitle("MW-Scanner — Ligaweit")
        self.resize(1320, 760)
        self.setMinimumSize(980, 620)
        self.setModal(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("LIGAWEITER MW-SCANNER")
        title.setObjectName("PageTitle")
        subtitle = QLabel("365-Tage-Historie · manuell geladen · API-Antworten werden 24 h gecacht")
        subtitle.setObjectName("Subtle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        controls = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("Spieler / Verein / Besitzer suchen …")
        position = QComboBox()
        position.addItems(["Alle Positionen", "TW", "ABW", "MF", "ST"])
        status = QLabel(f"{len(self.rows)} Spieler")
        status.setObjectName("Tiny")
        controls.addWidget(search, 1)
        controls.addWidget(position)
        controls.addWidget(status)
        layout.addLayout(controls)

        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "SPIELER", "VEREIN", "POS", "STATUS", "MARKTWERT", "1 TAG", "3 TAGE", "7 TAGE", "30 TAGE", "BESITZER"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        widths = [210, 150, 60, 150, 125, 100, 100, 100, 105, 180]
        for i, width in enumerate(widths):
            self.table.setColumnWidth(i, width)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemDoubleClicked.connect(self._open_player)
        layout.addWidget(self.table, 1)

        self._search = search
        self._position = position
        search.textChanged.connect(self._populate)
        position.currentIndexChanged.connect(self._populate)
        self._populate()

    def _populate(self, *_args) -> None:
        query = self._search.text().strip().casefold()
        pos = self._position.currentText()
        rows = []
        for row in self.rows:
            if pos != "Alle Positionen" and str(row.get("position") or "") != pos:
                continue
            hay = " ".join([
                str(row.get("full_name") or row.get("name") or ""),
                str(row.get("club") or ""),
                str(row.get("owner") or ""),
            ]).casefold()
            if query and query not in hay:
                continue
            rows.append(row)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            specs = [
                (row.get("full_name") or row.get("name") or "–", row.get("full_name") or row.get("name") or ""),
                (row.get("club") or "–", row.get("club") or ""),
                (row.get("position") or "–", POSITION_SORT.get(row.get("position"), 99)),
                (player_status_label(row), player_status_code(row) if player_status_code(row) is not None else -1),
                (euro(row.get("market_value")), int(row.get("market_value") or 0)),
                (delta_text(row.get("d1"), compact=True), row.get("d1") if row.get("d1") is not None else -10**18),
                (delta_text(row.get("d3"), compact=True), row.get("d3") if row.get("d3") is not None else -10**18),
                (delta_text(row.get("d7"), compact=True), row.get("d7") if row.get("d7") is not None else -10**18),
                (delta_text(row.get("d30"), compact=True), row.get("d30") if row.get("d30") is not None else -10**18),
                (row.get("owner") or "–", row.get("owner") or ""),
            ]
            for c, (display, sort_value) in enumerate(specs):
                icon = None
                if c == 0:
                    icon = player_status_icon(row)
                elif c == 1:
                    icon = club_icon(row.get("club"))
                elif c == 3:
                    icon = player_status_icon(row)
                item = table_item(display, sort_value, icon=icon)
                item.setData(Qt.UserRole, str(row.get("player_id") or ""))
                item.setData(Qt.UserRole + 1, row)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if c in (0, 1, 9) else Qt.AlignCenter)
                if c in (0, 3):
                    item.setToolTip(player_status_tooltip(row))
                if c in (5, 6, 7, 8):
                    set_item_delta_color(item, row.get({5:"d1",6:"d3",7:"d7",8:"d30"}[c]))
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)

    def _open_player(self, item: QTableWidgetItem) -> None:
        first = self.table.item(item.row(), 0)
        if not first:
            return
        player_id = first.data(Qt.UserRole)
        player = first.data(Qt.UserRole + 1)
        if player_id and hasattr(self.parent(), "open_player_detail_tab"):
            league_id = self.parent().league_combo.currentData() or self.parent().storage.get_setting("league_id")
            self.parent().open_player_detail_tab(str(player_id), str(league_id) if league_id else None, dict(player or {}))

class PortraitReviewDialog(QDialog):
    def __init__(self, storage: Storage, parent=None) -> None:
        super().__init__(parent)
        self.storage = storage
        self._rows: list[dict] = []
        self._current: dict | None = None
        self._accept_worker: FunctionWorker | None = None
        self.setWindowTitle("Portraits prüfen")
        self.resize(1220, 660)
        self.setMinimumSize(1040, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        title = QLabel("PORTRAITS PRÜFEN")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Hier landen nur FotMob-Treffer, die der automatische Abgleich nicht sicher genug zuordnen konnte. "
            "Übernimm nur Kandidaten, bei denen Spieler und Verein plausibel zusammenpassen."
        )
        subtitle.setObjectName("Subtle")
        subtitle.setWordWrap(True)
        self.counter = QLabel()
        self.counter.setObjectName("Tiny")
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(self.counter)

        split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["SPIELER", "VEREIN", "POS", "MW", "KB-ID", "FOTMOB", "MATCH", "GRUND"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 145)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 55)
        self.table.setColumnWidth(3, 95)
        self.table.setColumnWidth(4, 95)
        self.table.setColumnWidth(5, 185)
        self.table.setColumnWidth(6, 65)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        split.addWidget(self.table)

        detail = QFrame()
        detail.setObjectName("Card")
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(22, 20, 22, 20)
        detail_layout.setSpacing(10)

        self.preview = QLabel("Kein Kandidat ausgewählt")
        self.preview.setObjectName("PlayerDetailPortrait")
        self.preview.setFixedSize(190, 220)
        self.preview.setAlignment(Qt.AlignCenter | Qt.AlignBottom)
        self.preview.setScaledContents(False)
        detail_layout.addWidget(self.preview, 0, Qt.AlignHCenter)

        self.player_label = QLabel("–")
        self.player_label.setObjectName("SectionTitle")
        self.candidate_label = QLabel("–")
        self.candidate_label.setObjectName("BodyStrong")
        self.reason_label = QLabel("–")
        self.reason_label.setObjectName("Subtle")
        self.reason_label.setWordWrap(True)
        detail_layout.addWidget(self.player_label)
        detail_layout.addWidget(self.candidate_label)
        detail_layout.addWidget(self.reason_label)
        detail_layout.addStretch()

        actions = QHBoxLayout()
        self.reject_btn = QPushButton("ABLEHNEN")
        self.reject_btn.setObjectName("DangerSecondary")
        self.reject_btn.clicked.connect(self._reject_current)
        self.accept_btn = QPushButton("PORTRAIT ÜBERNEHMEN")
        self.accept_btn.clicked.connect(self._accept_current)
        actions.addWidget(self.reject_btn)
        actions.addWidget(self.accept_btn)
        detail_layout.addLayout(actions)
        split.addWidget(detail)
        split.setSizes([800, 380])
        root.addWidget(split, 1)

        bottom = QHBoxLayout()
        self.reset_btn = QPushButton("ABGELEHNTE ZURÜCKSETZEN")
        self.reset_btn.clicked.connect(self._reset_rejected)
        close_btn = QPushButton("SCHLIESSEN")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(self.reset_btn)
        bottom.addStretch()
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        self._reload()

    def _reload(self, preferred_player_id: str | None = None) -> None:
        self._rows = self.storage.portrait_review_rows()
        stats = self.storage.player_master_stats()
        self.counter.setText(
            f"{len(self._rows)} offen · {int(stats.get('cached') or 0)} gecacht · "
            f"{int(stats.get('rejected') or 0)} manuell abgelehnt"
        )
        self.reset_btn.setVisible(int(stats.get("rejected") or 0) > 0)
        self.table.setRowCount(len(self._rows))
        selected_row = 0
        for idx, row in enumerate(self._rows):
            player_name = str(row.get("full_name") or row.get("name") or "–")
            club = str(row.get("club") or "–")
            candidate = str(row.get("portrait_candidate_name") or "").strip()
            candidate_team = str(row.get("portrait_candidate_team") or "").strip()
            fotmob_id = str(row.get("fotmob_id") or "–")
            candidate_text = candidate or f"FotMob #{fotmob_id}"
            if candidate_team:
                candidate_text += f" · {candidate_team}"
            market_value = row.get("market_value")
            try:
                market_value_text = f"{int(market_value):,} €".replace(",", ".") if market_value is not None else "–"
            except (TypeError, ValueError):
                market_value_text = "–"
            values = [
                player_name,
                club,
                str(row.get("position") or "–"),
                market_value_text,
                str(row.get("player_id") or "–"),
                candidate_text,
                f"{int(row.get('portrait_confidence') or 0)}%",
                str(row.get("portrait_reason") or "–"),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, str(row.get("player_id") or ""))
                self.table.setItem(idx, col, item)
            if preferred_player_id and str(row.get("player_id")) == str(preferred_player_id):
                selected_row = idx
        if self._rows:
            self.table.selectRow(min(selected_row, len(self._rows) - 1))
        else:
            self._current = None
            self.preview.clear()
            self.preview.setText("Alle unsicheren Portraits geprüft")
            self.player_label.setText("FERTIG")
            self.candidate_label.setText("Keine offenen Kandidaten")
            self.reason_label.setText("")
            self.accept_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)

    def _selection_changed(self) -> None:
        row_idx = self.table.currentRow()
        if row_idx < 0 or row_idx >= len(self._rows):
            return
        self._current = self._rows[row_idx]
        row = self._current
        self.accept_btn.setEnabled(bool(row.get("fotmob_id")))
        self.reject_btn.setEnabled(True)
        player = str(row.get("full_name") or row.get("name") or "–")
        club = str(row.get("club") or "–")
        kb_id = str(row.get("player_id") or "–")
        kb_position = str(row.get("position") or "–")
        try:
            kb_market_value = f"{int(row.get('market_value')):,} €".replace(",", ".") if row.get("market_value") is not None else "–"
        except (TypeError, ValueError):
            kb_market_value = "–"
        candidate = str(row.get("portrait_candidate_name") or "").strip() or f"FotMob #{row.get('fotmob_id') or '–'}"
        candidate_team = str(row.get("portrait_candidate_team") or "").strip()
        candidate_position = str(row.get("portrait_candidate_position") or "").strip()
        candidate_number = str(row.get("portrait_candidate_shirt_number") or "").strip()
        candidate_meta = [value for value in [candidate_team, candidate_position, (f"#{candidate_number}" if candidate_number else "")] if value]
        self.player_label.setText(f"{player} · {club}")
        self.candidate_label.setText(candidate + (f" · {' · '.join(candidate_meta)}" if candidate_meta else ""))
        self.reason_label.setText(
            f"Kickbase: {kb_position} · {kb_market_value} · ID {kb_id}\n"
            f"FotMob-ID: {row.get('fotmob_id') or '–'} · Match-Sicherheit: {int(row.get('portrait_confidence') or 0)}%\n"
            f"{str(row.get('portrait_reason') or 'Keine zusätzliche Begründung')}"
        )
        self._load_preview(str(row.get("portrait_url") or ""))

    def _load_preview(self, url: str) -> None:
        self.preview.clear()
        if not url:
            self.preview.setText("Keine Vorschau verfügbar")
            return
        self.preview.setText("Vorschau lädt …")
        QApplication.processEvents()
        try:
            response = httpx.get(
                url,
                timeout=5.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.fotmob.com/"},
            )
            response.raise_for_status()
            pixmap = QPixmap()
            if not pixmap.loadFromData(response.content):
                raise ValueError("Kein lesbares Bild")
            self.preview.setText("")
            self.preview.setPixmap(pixmap.scaled(190, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            self.preview.setText("Vorschau nicht verfügbar")

    def _accept_current(self) -> None:
        if not self._current or self._accept_worker is not None:
            return
        row = dict(self._current)
        player_id = str(row.get("player_id") or "")
        self.accept_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self.accept_btn.setText("WIRD ÜBERNOMMEN …")
        worker = FunctionWorker(lambda: cache_review_candidate(self.storage, row))
        self._accept_worker = worker
        worker.signals.succeeded.connect(lambda match, pid=player_id: self._accept_succeeded(match, pid))
        worker.signals.failed.connect(self._accept_failed)
        worker.signals.finished.connect(self._accept_finished)
        QThreadPool.globalInstance().start(worker)

    def _accept_succeeded(self, match, player_id: str) -> None:
        self.storage.save_portrait_match(match)
        if getattr(match, "state", "") != "CACHED":
            QMessageBox.warning(self, "Portrait", getattr(match, "reason", "Portrait konnte nicht gespeichert werden."))
        self._notify_parent()
        self._reload()

    def _accept_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Portrait", message)

    def _accept_finished(self) -> None:
        self._accept_worker = None
        self.accept_btn.setText("PORTRAIT ÜBERNEHMEN")
        if self._current:
            self.accept_btn.setEnabled(bool(self._current.get("fotmob_id")))
            self.reject_btn.setEnabled(True)

    def _reject_current(self) -> None:
        if not self._current:
            return
        player_id = str(self._current.get("player_id") or "")
        self.storage.reject_portrait_candidate(player_id)
        self._notify_parent()
        self._reload()

    def _reset_rejected(self) -> None:
        count = self.storage.reset_rejected_portraits()
        if count:
            QMessageBox.information(
                self,
                "Portraits",
                f"{count} abgelehnte Kandidaten wurden wieder auf 'fehlend' gesetzt. "
                "Starte danach erneut den Portrait-Abgleich, um neue Kandidaten zu suchen.",
            )
        self._notify_parent()
        self._reload()

    def _notify_parent(self) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "_refresh_player_master_stats"):
            parent._refresh_player_master_stats()
