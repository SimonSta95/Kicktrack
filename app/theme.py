APP_STYLESHEET = r"""
* {
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}

QWidget {
    background: #0B0D0F;
    color: #F4F6F8;
}

/* Native Qt labels default to the QWidget background unless explicitly reset.
   Keeping them transparent is essential for card/dialog compositions. */
QLabel { background: transparent; border: none; }
QLabel#MetricCaption { color:#A6B0BA; font-size:11px; font-weight:800; }
QLabel#MetricValue { color:#F7F9FB; font-size:19px; font-weight:800; }

QMainWindow, QFrame#AppShell, QFrame#ContentShell, QStackedWidget#ContentStack {
    background: #0D0F11;
}

/* ---------- Shell ---------- */
QFrame#Sidebar {
    background: #080A0C;
    border: none;
    border-right: 1px solid #202429;
}


QLabel#BrandMark {
    background: transparent;
    color: #FF5A00;
    font-size: 22px;
    font-weight: 900;
}

QLabel#BrandName {
    background: transparent;
    color: #F7F8FA;
    font-size: 19px;
    font-weight: 800;
}
QLabel#SidebarBrandHint {
    background: transparent;
    color: #76818C;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
    padding-left: 3px;
}

QFrame#SidebarDivider {
    background: #202429;
    border: none;
}

QLabel#SidebarSection {
    background: transparent;
    color: #76818C;
    font-size: 11px;
    font-weight: 900;
    letter-spacing: 1px;
    padding: 0 10px 2px 10px;
}

QFrame#SidebarFooter {
    background: #101316;
    border: 1px solid #20252A;
    border-radius: 10px;
}

QLabel#SidebarFooterTitle {
    background: transparent;
    color: #AEB6BE;
    font-size: 11px;
    font-weight: 900;
}

QLabel#SidebarFooterHint {
    background: transparent;
    color: #77828D;
    font-size: 10px;
}

QFrame#TopBar {
    background: #090B0D;
    border: none;
    border-bottom: 1px solid #202429;
}

QLabel#TopContext {
    background: transparent;
    color: #87929D;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: .7px;
}

QLabel#AccountChip {
    background: #12161A;
    color: #A7AFB7;
    border: 1px solid #242A30;
    border-radius: 9px;
    padding: 8px 11px;
    font-size: 12px;
}

QPushButton#NavButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    color: #8A949E;
    padding: 0 12px;
    text-align: left;
    font-size: 13px;
    font-weight: 700;
}

QPushButton#NavButton:hover {
    background: #111519;
    color: #D8DEE4;
    border-color: #171C21;
}

QPushButton#NavButton:checked {
    background: #15191D;
    color: #FF6A18;
    border: 1px solid #1F252A;
    border-left: 3px solid #FF5A00;
    padding-left: 10px;
}

/* ---------- Typography ---------- */
QLabel#PageTitle {
    background: transparent;
    border: none;
    color: #F7F8FA;
    font-size: 24px;
    font-weight: 800;
}

QLabel#SectionTitle {
    background: transparent;
    border: none;
    color: #EEF1F4;
    font-size: 16px;
    font-weight: 800;
}

QLabel#SectionMini {
    background: transparent;
    border: none;
    color: #EDF0F3;
    font-size: 13px;
    font-weight: 800;
}

QLabel#Subtle {
    background: transparent;
    border: none;
    color: #96A1AC;
}

QLabel#Tiny {
    background: transparent;
    border: none;
    color: #89949F;
    font-size: 11px;
}

QLabel#Positive {
    background: transparent;
    color: #38D981;
    font-weight: 800;
}

QLabel#Negative {
    background: transparent;
    color: #FF5B5B;
    font-weight: 800;
}

QLabel#PlayerRoleBadge {
    background: #171B1F;
    color: #C9D0D6;
    border: 1px solid #282E34;
    border-radius: 7px;
    padding: 6px 10px;
    font-size: 11px;
    font-weight: 800;
}

/* ---------- Cards / Panels ---------- */
QFrame#Card {
    background: #111519;
    border: 1px solid #22282E;
    border-radius: 10px;
}

QFrame#Card:hover {
    background: #161B1F;
    border-color: #2C333A;
}

QFrame#CardAccent {
    background: #FF5A00;
    border: none;
    border-radius: 1px;
}

QFrame#Panel {
    background: #101417;
    border: 1px solid #22282E;
    border-radius: 10px;
}

QLabel#CardCaption {
    background: transparent;
    border: none;
    color: #9AA5AF;
    font-size: 11px;
    font-weight: 900;
    letter-spacing: .5px;
}

QLabel#CardValue {
    background: transparent;
    border: none;
    color: #F7F8FA;
    font-size: 22px;
    font-weight: 800;
}

QLabel#CardPositive {
    background: transparent;
    border: none;
    color: #38D981;
    font-size: 22px;
    font-weight: 800;
}

QLabel#CardNegative {
    background: transparent;
    border: none;
    color: #FF5B5B;
    font-size: 22px;
    font-weight: 800;
}

QLabel#CardWarning {
    background: transparent;
    border: none;
    color: #FF7A32;
    font-size: 22px;
    font-weight: 800;
}

QLabel#CardHint {
    background: transparent;
    border: none;
    color: #8B96A0;
    font-size: 11px;
}

/* ---------- Buttons ---------- */
QPushButton {
    background: #1A1F23;
    border: 1px solid #2A3036;
    border-radius: 8px;
    color: #E4E8EB;
    padding: 9px 14px;
    font-weight: 700;
}

QPushButton:hover {
    background: #20262B;
    border-color: #353C43;
}

QPushButton:pressed {
    background: #171B1F;
}

QPushButton#Primary {
    background: #FF5A00;
    border: 1px solid #FF6A18;
    color: #FFFFFF;
    font-weight: 900;
    padding: 9px 16px;
}

QPushButton#Primary:hover {
    background: #FF6918;
    border-color: #FF7A31;
}

QPushButton#Primary:pressed {
    background: #E95100;
}

/* ---------- Inputs ---------- */
QDialog, QMessageBox {
    background: #0D0F11;
}

QLineEdit {
    background: #111519;
    border: 1px solid #282E34;
    border-radius: 9px;
    color: #F4F6F8;
    padding: 10px 12px;
    selection-background-color: #FF5A00;
    selection-color: #FFFFFF;
}

QLineEdit:hover { border-color: #363E46; }
QLineEdit:focus { background: #13181C; border-color: #FF5A00; }

QComboBox {
    background: #12161A;
    border: 1px solid #2A3036;
    border-radius: 9px;
    color: #EEF1F4;
    padding: 8px 11px;
}

QComboBox:hover { border-color: #3A424A; }
QComboBox:focus { border-color: #FF5A00; }
QComboBox::drop-down { border: none; width: 25px; }
QComboBox QAbstractItemView {
    background: #15191D;
    border: 1px solid #30373E;
    color: #EEF1F4;
    outline: 0;
    selection-background-color: #242A30;
    selection-color: #FFFFFF;
    padding: 4px;
}

QComboBox#LeagueCombo {
    min-height: 18px;
}

QCheckBox { background: transparent; color: #9AA3AB; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid #3B434B;
    background: #12161A;
}
QCheckBox::indicator:checked { background: #FF5A00; border-color: #FF5A00; }


/* Chart footers are compositional overlays inside AnalyticsCard.
   Never let the global QWidget background create a black rectangle. */
QWidget#ChartFooter,
QWidget#AllocationLegendItem,
QLabel#ChartLegendText {
    background: transparent;
    border: none;
}
QLabel#ChartLegendText {
    color: #E6EBF0;
    font-size: 12px;
}
QWidget#RoleCell {
    background: transparent;
    border: none;
}

QComboBox#RoleCombo {
    background: #151A1E;
    border: 1px solid #2A3137;
    border-radius: 7px;
    color: #AAB2BA;
    padding: 4px 24px 4px 10px;
    font-size: 12px;
    font-weight: 700;
}
QComboBox#RoleCombo:hover {
    background: #1A2025;
    border-color: #3A434B;
}
QComboBox#RoleCombo:focus {
    background: #1A2025;
    border-color: #47515A;
}
QComboBox#RoleCombo::drop-down {
    width: 22px;
    border: none;
    background: transparent;
}
QComboBox#RoleCombo QAbstractItemView {
    background: #151A1E;
    border: 1px solid #343C43;
    border-radius: 7px;
    padding: 4px;
    selection-background-color: #242B31;
    selection-color: #FFFFFF;
}
QComboBox#RoleCombo[role="OFFEN"] { color: #8D97A0; }
QComboBox#RoleCombo[role="STAMM"] { color: #F0F3F5; }
QComboBox#RoleCombo[role="INVEST"] { color: #50D98A; }
QComboBox#RoleCombo[role="TRANSFERLISTE"] { color: #FF7A32; }

/* ---------- Tables ---------- */
QTableWidget {
    background: #0F1215;
    alternate-background-color: #12161A;
    border: 1px solid #22282E;
    border-radius: 9px;
    gridline-color: transparent;
    color: #E9EDF0;
    selection-background-color: #211A16;
    selection-color: #FFFFFF;
    outline: 0;
}

QHeaderView::section {
    background: #101316;
    color: #7C8690;
    padding: 9px 8px;
    border: none;
    border-bottom: 1px solid #262C32;
    font-size: 11px;
    font-weight: 900;
}

QTableWidget::item {
    padding: 0 11px;
    border: none;
}

QTableWidget::item:hover {
    background: #171B1F;
}

QTableWidget::item:selected,
QTableWidget::item:selected:active,
QTableWidget::item:selected:!active {
    background: #211A16;
    color: #FFFFFF;
    border-top: 1px solid #633318;
    border-bottom: 1px solid #633318;
}

/* ---------- Scrollbars ---------- */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 7px 2px;
}
QScrollBar::handle:vertical {
    background: #30363C;
    min-height: 26px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover { background: #444C54; }
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical,
QScrollBar:horizontal,
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
    border: none;
    height: 0;
    width: 0;
}

/* ---------- Tooltips / status ---------- */
QToolTip {
    background-color: #1A1F23;
    color: #FFFFFF;
    border: 1px solid #343B42;
    border-radius: 7px;
    padding: 7px 9px;
    font-size: 12px;
}

QStatusBar {
    background: #090B0D;
    color: #737D86;
    border-top: 1px solid #202429;
}

QScrollArea#PageScroll {
    background: #0D0F11;
    border: none;
}
QScrollArea#PageScroll > QWidget > QWidget { background: #0D0F11; }
QWidget#KickbaseLogoWrap,
QLabel#KickbaseLogoImage {
    background: transparent;
    border: none;
}
"""

APP_STYLESHEET += r"""
/* ===== UI Redesign v3: custom component layer ===== */
QMainWindow, QFrame#AppShell, QFrame#ContentShell, QStackedWidget#ContentStack { background: #080B0E; }
QFrame#Sidebar { background: #080B0F; border-right: 1px solid #1D242B; }
QFrame#TopBar { background: #090C10; border-bottom: 1px solid #1E252C; }
QLabel#BrandMark { color:#FF6518; font-size:25px; font-weight:900; }
QLabel#BrandName { color:#F7F9FB; font-size:20px; font-weight:800; }
QPushButton#NavButton { min-height: 40px; background: transparent; color:#B6BFC8; border:1px solid transparent; border-radius:8px; padding:0 13px; font-size:13px; font-weight:650; }
QPushButton#NavButton:hover { background:#11161B; color:#F0F3F6; }
QPushButton#NavButton:checked { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #26170F, stop:1 #15171A); border:1px solid #2B211B; border-left:3px solid #FF6518; color:#FF7429; }
QLabel#PageTitle { font-size:23px; font-weight:800; color:#F6F8FA; }
QLabel#Subtle { color:#A0AAB4; font-size:12px; }
QFrame#MetricCard { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #151A1F, stop:1 #11161A); border:1px solid #242C33; border-radius:11px; }
QFrame#MetricCard:hover { border-color:#333C45; background:#171D22; }
QLabel#CardCaption { color:#A5AFB9; font-size:10px; font-weight:800; letter-spacing:.45px; }
QLabel#CardValue, QLabel#CardPositive, QLabel#CardNegative { font-size:21px; font-weight:800; }
QLabel#CardHint { color:#909BA5; font-size:11px; }
QFrame#AnalyticsCard { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #14191E, stop:1 #101519); border:1px solid #242C33; border-radius:11px; }
QFrame#TablePanel { background:#101519; border:1px solid #242C33; border-radius:11px; }
QFrame#TablePanelHeader { background:#12171C; border:none; border-bottom:1px solid #242C33; border-top-left-radius:11px; border-top-right-radius:11px; }
QTableWidget#EmbeddedTable { border:none; border-bottom-left-radius:11px; border-bottom-right-radius:11px; }
QTableWidget { background:#0E1317; alternate-background-color:#11171B; border:1px solid #242C33; border-radius:10px; }
QHeaderView::section { background:#11161A; color:#A6B0BA; padding:9px 10px; border-bottom:1px solid #252D34; font-size:11px; font-weight:850; }
QTableWidget::item { padding:0 10px; }
QTableWidget::item:hover { background:#171E23; }
QTableWidget::item:selected { background:#241A14; color:#FFFFFF; border-top:1px solid #6A351B; border-bottom:1px solid #6A351B; }
QFrame#AccountChipFrame { background:transparent; border:none; }
QLabel#AccountAvatar { background:#6F45D8; color:white; border-radius:13px; font-weight:800; }
QLabel#AccountText { background:transparent; color:#C0C7CE; font-size:11px; }
QComboBox#LeagueCombo { background:#11161B; border:1px solid #2A323A; border-radius:8px; padding:8px 11px; }
QPushButton#Primary { background:#FF6518; border:1px solid #FF7835; border-radius:8px; padding:9px 16px; }
QPushButton#Primary:hover { background:#FF762F; }
QToolTip { background:#171D22; border:1px solid #303942; color:#F7F9FB; padding:6px; }
"""

APP_STYLESHEET += r"""
/* ===== UI polish v4 ===== */
QFrame#MetricCard { border-radius:12px; }
QFrame#AnalyticsCard { border-radius:12px; background:#11161A; }
QFrame#TablePanel, QFrame#Panel { border-radius:12px; }
QFrame#TablePanelHeader { border-top-left-radius:12px; border-top-right-radius:12px; }
QTableWidget#EmbeddedTable { border-bottom-left-radius:12px; border-bottom-right-radius:12px; }
QHeaderView::section { padding:9px 10px; }
"""

APP_STYLESHEET += r"""
QLabel#BudgetStatusBadge {
    background: #151B20;
    color: #C7D0D8;
    border: 1px solid #2A333B;
    border-radius: 10px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 700;
}
QFrame#BudgetBidListPanel {
    background: #0F1418;
    border: 1px solid #222B33;
    border-radius: 12px;
}
QFrame#BudgetBidRow {
    background: #12181D;
    border: 1px solid #232D35;
    border-radius: 10px;
}
QFrame#BudgetBidRow:hover {
    border-color: #33404A;
    background: #141B20;
}
QLabel#BudgetBidClubLogo {
    background: #12181D;
    border: 1px solid #273139;
    border-radius: 12px;
    padding: 1px;
}
QLabel#BudgetBidName {
    color: #F3F6F8;
    font-size: 14px;
    font-weight: 700;
}
QLabel#BudgetBidMeta {
    color: #8C97A2;
    font-size: 11px;
}
QLabel#BudgetBidAmount {
    color: #FF7A32;
    font-size: 15px;
    font-weight: 800;
}
QFrame#BudgetBidFooter {
    background: #12171B;
    border: 1px solid #263038;
    border-radius: 10px;
}
QLabel#BudgetBidFooterLabel {
    color: #A5AFB9;
    font-size: 11px;
    font-weight: 700;
}
QLabel#BudgetBidFooterValue {
    color: #F2F5F7;
    font-size: 14px;
    font-weight: 800;
}
QLabel#BudgetEmptyState {
    background: #12181D;
    color: #8E99A4;
    border: 1px dashed #263139;
    border-radius: 10px;
    padding: 14px 12px;
    font-size: 12px;
}

"""

APP_STYLESHEET += r"""
/* ===== Market intelligence ===== */
QLabel#FinanceSuccess {
    background: #10241A;
    color: #45DF8C;
    border: 1px solid #24583C;
    border-radius: 10px;
    padding: 11px 13px;
    font-size: 13px;
    font-weight: 700;
}
QLabel#FinanceWarning {
    background: #241A12;
    color: #FF9A5B;
    border: 1px solid #5B3922;
    border-radius: 10px;
    padding: 11px 13px;
    font-size: 13px;
    font-weight: 700;
}
QFrame#FinanceScenarioCard {
    background: #12181D;
    border: 1px solid #263039;
    border-radius: 10px;
}
QLabel#FinanceScenarioName {
    color: #F2F5F7;
    font-size: 13px;
    font-weight: 750;
}
QLabel#FinanceRole {
    background: #171D22;
    color: #AEB7C0;
    border: 1px solid #2B343C;
    border-radius: 8px;
    padding: 5px 8px;
    font-size: 10px;
    font-weight: 700;
}
"""

APP_STYLESHEET += r"""
/* ===== Analysis chips ===== */
QWidget#AnalysisChipCell {
    background: transparent;
    border: none;
}
QLabel#AnalysisPrimaryChip,
QLabel#AnalysisScoreChip,
QLabel#AnalysisInsightChip {
    border-radius: 9px;
    padding: 4px 8px;
    font-size: 10px;
    font-weight: 800;
}
QLabel#AnalysisPrimaryChip {
    padding: 5px 10px;
    letter-spacing: .3px;
}
QLabel#AnalysisScoreChip {
    min-width: 34px;
}
QLabel#AnalysisPrimaryChip[tone="positive"],
QLabel#AnalysisScoreChip[tone="positive"],
QLabel#AnalysisInsightChip[tone="positive"] {
    background: #10271D;
    color: #61E69A;
    border: 1px solid #245B3B;
}
QLabel#AnalysisPrimaryChip[tone="warning"],
QLabel#AnalysisScoreChip[tone="warning"],
QLabel#AnalysisInsightChip[tone="warning"] {
    background: #2A1D11;
    color: #FF9B55;
    border: 1px solid #654022;
}
QLabel#AnalysisPrimaryChip[tone="negative"],
QLabel#AnalysisScoreChip[tone="negative"],
QLabel#AnalysisInsightChip[tone="negative"] {
    background: #291516;
    color: #FF7378;
    border: 1px solid #623034;
}
QLabel#AnalysisPrimaryChip[tone="accent"],
QLabel#AnalysisScoreChip[tone="accent"],
QLabel#AnalysisInsightChip[tone="accent"] {
    background: #171F31;
    color: #8FB8FF;
    border: 1px solid #314A70;
}
QLabel#AnalysisPrimaryChip[tone="muted"],
QLabel#AnalysisScoreChip[tone="muted"],
QLabel#AnalysisInsightChip[tone="muted"] {
    background: #161C21;
    color: #AAB4BD;
    border: 1px solid #2B343C;
}
"""

APP_STYLESHEET += r"""
QLabel#PlayerDetailClubLogo {
    background: transparent;
    border: none;
}
"""

APP_STYLESHEET += r"""
QFrame#AnalysisPopover {
    background: #11171C;
    border: 1px solid #34414B;
    border-radius: 10px;
}
QLabel#AnalysisPopoverText {
    color: #E9EEF2;
    background: transparent;
    font-size: 12px;
    line-height: 1.25;
}
"""

APP_STYLESHEET += r"""

QLabel#BidRatingChip {
    min-height: 24px;
    padding: 2px 9px;
    border-radius: 8px;
    border: 1px solid #4A4F55;
    background: #20262B;
    color: #DCE3E8;
    font-size: 10px;
    font-weight: 700;
}
QLabel#BidRatingChip[tone="positive"] {
    background: #10251A;
    border-color: #285B3C;
    color: #65E89C;
}
QLabel#BidRatingChip[tone="warning"] {
    background: #2A1B0E;
    border-color: #6C451F;
    color: #FFAA54;
}
QLabel#BidRatingChip[tone="negative"] {
    background: #2A1515;
    border-color: #6B3030;
    color: #FF7474;
}

"""

APP_STYLESHEET += r"""
QFrame#CompactMetric {
    background: transparent;
    border: none;
}
QTabWidget#AnalysisTabs::pane,
QTabWidget::pane {
    border: 1px solid #273038;
    border-radius: 10px;
    background: #0F1418;
    top: -1px;
}
QTabBar::tab {
    background: #12181D;
    color: #9EABB5;
    border: 1px solid #273038;
    border-bottom: none;
    padding: 8px 16px;
    margin-right: 4px;
    min-width: 96px;
    font-size: 11px;
    font-weight: 700;
}
QTabBar::tab:selected {
    background: #1D1714;
    color: #FF7A2F;
    border-color: #5A3624;
}
QTabBar::tab:hover:!selected {
    background: #182026;
    color: #E7EDF1;
}
"""

APP_STYLESHEET += r"""
QFrame#AnalysisSummaryCard,
QFrame#AnalysisSectionPanel {
    background: #11171B;
    border: 1px solid #252E35;
    border-radius: 10px;
}
QFrame#AnalysisSummaryCard:hover {
    border-color: #343E46;
    background: #141B20;
}
QLabel#AnalysisSummaryTitle {
    color: #F2F5F7;
    font-size: 11px;
    font-weight: 800;
}
QLabel#AnalysisSummaryValue {
    color: #F4F7F9;
    font-size: 15px;
    font-weight: 750;
    margin-top: 2px;
}
QLabel#AnalysisSummaryPreview {
    color: #AAB5BD;
    font-size: 11px;
    line-height: 1.35;
}
QPushButton#CompactActionButton {
    min-height: 24px;
    max-height: 24px;
    padding: 2px 9px;
    border-radius: 7px;
    background: #171E23;
    border: 1px solid #2A343B;
    color: #C7D0D6;
    font-size: 10px;
    font-weight: 800;
}
QPushButton#CompactActionButton:hover {
    background: #1D252B;
    border-color: #3A4650;
    color: #FFFFFF;
}
"""

APP_STYLESHEET += r"""
QPushButton#DangerSecondary {
    min-height: 34px;
    padding: 0 13px;
    border-radius: 8px;
    border: 1px solid #6A3A2A;
    background: #211711;
    color: #FF9A68;
    font-size: 11px;
    font-weight: 800;
}
QPushButton#DangerSecondary:hover { background: #2B1B13; border-color: #8B4B31; }
QPushButton#DangerSecondary:disabled { color:#7D6F68; border-color:#3B302B; background:#171412; }
"""


APP_STYLESHEET += r"""
QFrame#SaleDecisionPanel {
    background: #11171C;
    border: 1px solid #2B343C;
    border-radius: 10px;
}
QLabel#SaleDecisionChip {
    border-radius: 8px;
    padding: 4px 9px;
    font-size: 10px;
    font-weight: 800;
}
QLabel#SaleDecisionChip[tone="positive"] {
    background: #10271D;
    color: #61E69A;
    border: 1px solid #245B3B;
}
QLabel#SaleDecisionChip[tone="warning"] {
    background: #2A1D11;
    color: #FFB15F;
    border: 1px solid #654022;
}
QLabel#SaleDecisionChip[tone="negative"] {
    background: #291516;
    color: #FF7378;
    border: 1px solid #623034;
}
QLabel#SaleDecisionChip[tone="muted"] {
    background: #161C21;
    color: #AAB4BD;
    border: 1px solid #2B343C;
}
"""

APP_STYLESHEET += r"""
QFrame#CoachCard {
    background: #11171B;
    border: 1px solid #273139;
    border-radius: 10px;
}
QLabel#CoachVerdict {
    background: #17211B;
    color: #66E39A;
    border: 1px solid #28583C;
    border-radius: 7px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
}
QLabel#CoachPlayer {
    color: #F4F7F9;
    font-size: 14px;
    font-weight: 700;
}
QLabel#CoachMeta, QLabel#CoachReason {
    color: #93A1AD;
    font-size: 11px;
}
QLabel#CoachAction {
    color: #DCE4EA;
    font-size: 12px;
}
QLabel#CoachPlanability {
    color: #A8B3BC;
    background: #151C21;
    border: 1px solid #2A343B;
    border-radius: 7px;
    padding: 3px 7px;
    font-size: 10px;
    font-weight: 700;
}
QLabel#CoachFallbackIcon {
    color: #FF7A2F;
    background: #26180F;
    border: 1px solid #713210;
    border-radius: 15px;
    font-weight: 700;
}

QLabel#CoachPurposeCaption {
    color: #7F8C98;
    font-size: 10px;
    font-weight: 700;
}
QLabel#CoachPurpose {
    color: #F4F7FA;
    background: #1B242B;
    border: 1px solid #34434E;
    border-radius: 7px;
    padding: 3px 7px;
    font-size: 10px;
    font-weight: 800;
}
QLabel#CoachSecondaryCaption {
    color: #73808A;
    font-size: 10px;
    font-weight: 800;
}
QLabel#CoachSecondaryChip {
    color: #C9D3DA;
    background: #172027;
    border: 1px solid #2B3943;
    border-radius: 7px;
    padding: 2px 7px;
    font-size: 10px;
    font-weight: 700;
}
QLabel#CoachPurposeSecondary {
    color: #B9C4CD;
    background: #151C21;
    border: 1px solid #2A353D;
    border-radius: 7px;
    padding: 3px 7px;
    font-size: 10px;
    font-weight: 700;
}

QLabel#DeadlineChip {
    color: #DCE4EA;
    background: #141B20;
    border: 1px solid #2A353D;
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 11px;
    font-weight: 800;
}
QLabel#DeadlineChip[state="safe"] {
    color: #66E39A;
    border-color: #28583C;
    background: #122019;
}
QLabel#DeadlineChip[state="danger"] {
    color: #FF6B6B;
    border-color: #6B2D2D;
    background: #241515;
}
QFrame#MarketDetailPanel {
    background: #101519;
    border: 1px solid #273139;
    border-radius: 12px;
}
QFrame#MarketDetailBox {
    background: #0C1115;
    border: 1px solid #242E35;
    border-radius: 9px;
}
QLabel#MarketDetailSignal {
    color: #66E39A;
    font-size: 11px;
    font-weight: 900;
}
QLabel#MarketDetailName {
    color: #F4F7F9;
    font-size: 20px;
    font-weight: 900;
}
QLabel#MarketDetailValue {
    color: #F4F7F9;
    font-size: 12px;
    font-weight: 800;
}
QLabel#MarketDetailScores {
    color: #DDE6EC;
    background: #151D23;
    border: 1px solid #2B3740;
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 11px;
    font-weight: 800;
}
QLabel#MarketDetailReason {
    color: #B8C4CC;
    font-size: 11px;
    line-height: 1.35;
}
QLabel#CoachRank {
    color: #FF8A3D;
    background: #24170F;
    border: 1px solid #6B3514;
    border-radius: 13px;
    font-size: 11px;
    font-weight: 900;
}
QSplitter#MarketSplitter::handle {
    background: transparent;
    width: 8px;
}
"""
