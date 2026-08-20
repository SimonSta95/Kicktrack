"""KickTrack V4 consolidated Qt stylesheet.

The visual language stays aligned with the Kickbase CI (KB Pitch / KB Volksans,
black/white surfaces and the live-orange accent). V4 interaction components live
in the same stylesheet so selector precedence is deterministic.
"""

APP_STYLESHEET = r"""

* {
    font-family: "KB Volksans", "Source Sans 3", "Source Sans Pro", "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}

QWidget {
    background: #080808;
    color: #F4F4F2;
}

/* Native Qt labels default to the QWidget background unless explicitly reset.
   Keeping them transparent is essential for card/dialog compositions. */
QLabel { background: transparent; border: none; }
QLabel#MetricCaption { color:#A6B0BA; font-size:11px; font-weight:800; }
QLabel#MetricValue { color:#FAFAF7; font-size:19px; font-weight:800; }

QMainWindow, QFrame#AppShell, QFrame#ContentShell, QStackedWidget#ContentStack {
    background: #0A0A0A;
}

/* ---------- Shell ---------- */
QFrame#Sidebar {
    background: #050505;
    border: none;
    border-right: 1px solid #282828;
}


QLabel#BrandMark {
    background: transparent;
    color: #FF3B12;
    font-size: 22px;
    font-weight: 900;
}

QLabel#BrandName {
    font-family: "KB Pitch", "KB Volksans", "Source Sans 3", "Source Sans Pro", "Segoe UI", Arial, sans-serif;
    background: transparent;
    color: #FAFAF7;
    font-size: 19px;
    font-weight: 800;
}
QLabel#SidebarBrandHint {
    background: transparent;
    color: #858580;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
    padding-left: 3px;
}

QFrame#SidebarDivider {
    background: #282828;
    border: none;
}

QLabel#SidebarSection {
    background: transparent;
    color: #858580;
    font-size: 11px;
    font-weight: 900;
    letter-spacing: 1px;
    padding: 0 10px 2px 10px;
}

QFrame#SidebarFooter {
    background: #101316;
    border: 1px solid #292929;
    border-radius: 6px;
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
    background: #070707;
    border: none;
    border-bottom: 1px solid #282828;
}

QLabel#TopContext {
    background: transparent;
    color: #87929D;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: .7px;
}

QLabel#AccountChip {
    background: #131313;
    color: #A7AFB7;
    border: 1px solid #303030;
    border-radius: 9px;
    padding: 8px 11px;
    font-size: 12px;
}

QPushButton#NavButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    color: #999994;
    padding: 0 12px;
    text-align: left;
    font-size: 13px;
    font-weight: 700;
}

QPushButton#NavButton:hover {
    background: #111111;
    color: #D8DEE4;
    border-color: #242424;
}

QPushButton#NavButton:checked {
    background: #171717;
    color: #FF3B12;
    border: 1px solid #1F252A;
    border-left: 3px solid #FF3B12;
    padding-left: 10px;
}

/* ---------- Typography ---------- */
QLabel#PageTitle {
    font-family: "KB Pitch", "KB Volksans", "Source Sans 3", "Source Sans Pro", "Segoe UI", Arial, sans-serif;
    background: transparent;
    border: none;
    color: #FAFAF7;
    font-size: 24px;
    font-weight: 800;
}

QLabel#SectionTitle {
    font-family: "KB Pitch", "KB Volksans", "Source Sans 3", "Source Sans Pro", "Segoe UI", Arial, sans-serif;
    background: transparent;
    border: none;
    color: #F1F1EE;
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
    color: #A5A5A0;
}

QLabel#Tiny {
    background: transparent;
    border: none;
    color: #93938E;
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
    background: #111111;
    border: 1px solid #2A2A2A;
    border-radius: 6px;
}

QFrame#Card:hover {
    background: #181818;
    border-color: #383838;
}

QFrame#CardAccent {
    background: #FF3B12;
    border: none;
    border-radius: 1px;
}

QFrame#Panel {
    background: #101010;
    border: 1px solid #2A2A2A;
    border-radius: 6px;
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
    color: #FAFAF7;
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
    color: #FF5A35;
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
    background: #FF3B12;
    border: 1px solid #FF3B12;
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
    background: #0A0A0A;
}

QLineEdit {
    background: #111111;
    border: 1px solid #282E34;
    border-radius: 9px;
    color: #F4F4F2;
    padding: 10px 12px;
    selection-background-color: #FF3B12;
    selection-color: #FFFFFF;
}

QLineEdit:hover { border-color: #363E46; }
QLineEdit:focus { background: #13181C; border-color: #FF3B12; }

QComboBox {
    background: #131313;
    border: 1px solid #2A3036;
    border-radius: 9px;
    color: #F1F1EE;
    padding: 8px 11px;
}

QComboBox:hover { border-color: #3A424A; }
QComboBox:focus { border-color: #FF3B12; }
QComboBox::drop-down { border: none; width: 25px; }
QComboBox QAbstractItemView {
    background: #171717;
    border: 1px solid #30373E;
    color: #F1F1EE;
    outline: 0;
    selection-background-color: #303030;
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
    background: #131313;
}
QCheckBox::indicator:checked { background: #FF3B12; border-color: #FF3B12; }


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
    padding: 4px 18px 4px 10px;
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
QComboBox#RoleCombo[role="TRANSFERLISTE"] { color: #FF5A35; }

/* ---------- Tables ---------- */
QTableWidget {
    background: #0F1215;
    alternate-background-color: #131313;
    border: 1px solid #2A2A2A;
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
    background: #070707;
    color: #737D86;
    border-top: 1px solid #282828;
}

QScrollArea#PageScroll {
    background: #0A0A0A;
    border: none;
}
QScrollArea#PageScroll > QWidget > QWidget { background: #0A0A0A; }
QWidget#KickbaseLogoWrap,
QLabel#KickbaseLogoImage {
    background: transparent;
    border: none;
}

/* ===== UI Redesign v3: custom component layer ===== */
QMainWindow, QFrame#AppShell, QFrame#ContentShell, QStackedWidget#ContentStack { background: #080B0E; }
QFrame#Sidebar { background: #080B0F; border-right: 1px solid #1D242B; }
QFrame#TopBar { background: #090C10; border-bottom: 1px solid #1E252C; }
QLabel#BrandMark { color:#FF3B12; font-size:25px; font-weight:900; }
QLabel#BrandName { color:#FAFAF7; font-size:20px; font-weight:800; }
QPushButton#NavButton { min-height: 40px; background: transparent; color:#B6BFC8; border:1px solid transparent; border-radius:8px; padding:0 13px; font-size:13px; font-weight:650; }
QPushButton#NavButton:hover { background:#11161B; color:#F0F3F6; }
QPushButton#NavButton:checked { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #26170F, stop:1 #15171A); border:1px solid #2B211B; border-left:3px solid #FF3B12; color:#FF7429; }
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
QPushButton#Primary { background:#FF3B12; border:1px solid #FF7835; border-radius:8px; padding:9px 16px; }
QPushButton#Primary:hover { background:#FF762F; }
QToolTip { background:#171D22; border:1px solid #303942; color:#FAFAF7; padding:6px; }

/* ===== UI polish v4 ===== */
QFrame#MetricCard { border-radius:12px; }
QFrame#AnalyticsCard { border-radius:12px; background:#11161A; }
QFrame#TablePanel, QFrame#Panel { border-radius:12px; }
QFrame#TablePanelHeader { border-top-left-radius:12px; border-top-right-radius:12px; }
QTableWidget#EmbeddedTable { border-bottom-left-radius:12px; border-bottom-right-radius:12px; }
QHeaderView::section { padding:9px 10px; }

QLabel#BudgetStatusBadge {
    background: #151B20;
    color: #C7D0D8;
    border: 1px solid #2A333B;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 700;
}
QFrame#BudgetBidListPanel {
    background: #0F1418;
    border: 1px solid #222B33;
    border-radius: 7px;
}
QFrame#BudgetBidRow {
    background: #12181D;
    border: 1px solid #232D35;
    border-radius: 6px;
}
QFrame#BudgetBidRow:hover {
    border-color: #33404A;
    background: #141B20;
}
QLabel#BudgetBidClubLogo {
    background: #12181D;
    border: 1px solid #273139;
    border-radius: 7px;
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
    color: #FF5A35;
    font-size: 15px;
    font-weight: 800;
}
QFrame#BudgetBidFooter {
    background: #12171B;
    border: 1px solid #263038;
    border-radius: 6px;
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
    border-radius: 6px;
    padding: 14px 12px;
    font-size: 12px;
}


/* ===== Market intelligence ===== */
QLabel#FinanceSuccess {
    background: #10241A;
    color: #45DF8C;
    border: 1px solid #24583C;
    border-radius: 6px;
    padding: 11px 13px;
    font-size: 13px;
    font-weight: 700;
}
QLabel#FinanceWarning {
    background: #241A12;
    color: #FF9A5B;
    border: 1px solid #5B3922;
    border-radius: 6px;
    padding: 11px 13px;
    font-size: 13px;
    font-weight: 700;
}
QFrame#FinanceScenarioCard {
    background: #12181D;
    border: 1px solid #263039;
    border-radius: 6px;
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

QLabel#PlayerDetailClubLogo {
    background: transparent;
    border: none;
}

QFrame#AnalysisPopover {
    background: #11171C;
    border: 1px solid #34414B;
    border-radius: 6px;
}
QLabel#AnalysisPopoverText {
    color: #E9EEF2;
    background: transparent;
    font-size: 12px;
    line-height: 1.25;
}


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


QFrame#CompactMetric {
    background: transparent;
    border: none;
}
QTabWidget#AnalysisTabs::pane,
QTabWidget::pane {
    border: 1px solid #273038;
    border-radius: 6px;
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
    color: #FF5A35;
    border-color: #5A3624;
}
QTabBar::tab:hover:!selected {
    background: #182026;
    color: #E7EDF1;
}

QFrame#AnalysisSummaryCard,
QFrame#AnalysisSectionPanel {
    background: #11171B;
    border: 1px solid #252E35;
    border-radius: 6px;
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

QFrame#SaleDecisionPanel {
    background: #11171C;
    border: 1px solid #2B343C;
    border-radius: 6px;
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

QFrame#CoachCard {
    background: #11171B;
    border: 1px solid #273139;
    border-radius: 6px;
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
    color: #FF5A35;
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
    border-radius: 7px;
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
    color: #D6E0E6;
    background: #10171C;
    border: 1px solid #24303A;
    border-radius: 10px;
    padding: 10px 12px;
    font-size: 12px;
}
QLabel#MarketDetailHistory {
    color: #B9C6CF;
    background: #0F151A;
    border: 1px solid #202A33;
    border-radius: 10px;
    padding: 10px 12px;
    font-size: 12px;
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

QFrame#CoachSummary {
    background: #0D1216;
    border: 1px solid #253039;
    border-radius: 7px;
}
QFrame#CoachStat {
    background: #12191E;
    border: 1px solid #27333C;
    border-radius: 9px;
}
QLabel#CoachStatCaption {
    color: #778793;
    font-size: 9px;
    font-weight: 800;
}
QLabel#CoachStatValue {
    color: #F2F6F8;
    font-size: 16px;
    font-weight: 900;
}
QLabel#CoachStatValue[tone="positive"] { color: #62E49A; }
QLabel#CoachStatValue[tone="warning"] { color: #FFAA55; }
QLabel#CoachStatValue[tone="negative"] { color: #FF6F74; }
QLabel#CoachGroupTitle {
    color: #AEBAC3;
    font-size: 10px;
    font-weight: 900;
    padding: 8px 2px 2px 2px;
}
QFrame#CoachCard[tone="warning"] { border-left: 3px solid #FF8A3D; }
QFrame#CoachCard[tone="buy"] { border-left: 3px solid #4FDC8A; }
QFrame#CoachCard[tone="sell"] { border-left: 3px solid #FF7075; }
QFrame#CoachCard[tone="bid"] { border-left: 3px solid #A97CFF; }
QLabel#CoachPriority {
    color: #8C99A4;
    background: #151C21;
    border: 1px solid #2A343B;
    border-radius: 6px;
    padding: 2px 6px;
    font-size: 9px;
    font-weight: 900;
}
QLabel#CoachPriority[level="high"] {
    color: #FFAA55;
    background: #281A0F;
    border-color: #6B3A16;
}
QLabel#CoachPriority[level="medium"] {
    color: #E5D37A;
}
QLabel#CoachReasonChip {
    color: #AEB9C2;
    background: #151D22;
    border: 1px solid #2A353D;
    border-radius: 6px;
    padding: 2px 7px;
    font-size: 9px;
    font-weight: 700;
}
QLabel#CoachReasonChip[primary="true"] {
    color: #F0F5F7;
    background: #1B252C;
    border-color: #3A4A55;
}

QFrame#CoachHero {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #10171C, stop:0.55 #111B22, stop:1 #0E1418);
    border: 1px solid #26323B;
    border-radius: 8px;
}
QLabel#CoachHeroTitle {
    font-family: "KB Pitch", "KB Volksans", "Source Sans 3", "Source Sans Pro", "Segoe UI", Arial, sans-serif;
    color: #F4F7FA;
    font-size: 18px;
    font-weight: 900;
}
QLabel#CoachHeroMeta {
    color: #AEB9C2;
    font-size: 12px;
    line-height: 1.4;
}
QLabel#CoachInsightChip {
    color: #D9E2E8;
    background: #151E24;
    border: 1px solid #2B3943;
    border-radius: 9px;
    padding: 6px 10px;
    font-size: 11px;
    font-weight: 800;
}
QLabel#CoachInsightChip[tone="positive"] {
    color: #67E49B;
    background: #122018;
    border-color: #28573A;
}
QLabel#CoachInsightChip[tone="negative"] {
    color: #FF7A80;
    background: #241517;
    border-color: #633136;
}
QLabel#CoachInsightChip[tone="warning"] {
    color: #FFB160;
    background: #281A10;
    border-color: #6A3B17;
}
QFrame#CoachCard {
    background: #10161A;
    border: 1px solid #26313A;
    border-radius: 7px;
}
QFrame#CoachCard:hover {
    background: #121A20;
    border-color: #34424D;
}
QLabel#CoachGroupTitle {
    color: #C2CDD5;
    font-size: 11px;
    font-weight: 900;
    padding: 10px 2px 4px 2px;
    letter-spacing: 0.03em;
}
QLabel#CoachKpiChip {
    color: #E3EAF0;
    background: #172027;
    border: 1px solid #2B3943;
    border-radius: 7px;
    padding: 3px 8px;
    font-size: 10px;
    font-weight: 800;
}
QLabel#CoachReasonChip {
    padding: 3px 8px;
    font-size: 10px;
}
QLabel#CoachAction {
    color: #E3EBF0;
    font-size: 12px;
    line-height: 1.45;
}
QLabel#CoachStatValue {
    font-size: 18px;
}

QLabel#PlayerStatusBadge {
    color: #DCE5EA;
    background: #161D22;
    border: 1px solid #2D3942;
    border-radius: 8px;
    padding: 5px 9px;
    font-size: 10px;
    font-weight: 900;
}
QLabel#PlayerStatusBadge[status="0"] {
    color: #66E39A;
    background: #122019;
    border-color: #28583C;
}
QLabel#PlayerStatusBadge[status="1"],
QLabel#PlayerStatusBadge[status="8"],
QLabel#PlayerStatusBadge[status="16"],
QLabel#PlayerStatusBadge[status="128"] {
    color: #FF777C;
    background: #241516;
    border-color: #653034;
}
QLabel#PlayerStatusBadge[status="2"],
QLabel#PlayerStatusBadge[status="4"] {
    color: #FFB05E;
    background: #281A10;
    border-color: #69401E;
}
QLabel#PlayerStatusBadge[status="32"] {
    color: #F1D05C;
    background: #29230F;
    border-color: #66571D;
}
QLabel#PlayerStatusBadge[status="256"] {
    color: #B2BBC2;
    background: #171D21;
    border-color: #333D44;
}

/* ---------- KB font readability pass ----------
   KB Volksans and especially KB Pitch render visually smaller/tighter than the
   previous Segoe/Source Sans fallback at identical pixel sizes. */
* { font-size: 14px; }

QPushButton#NavButton { font-size: 14px; }
QLabel#SidebarSection, QLabel#SidebarFooterTitle, QLabel#TopContext { font-size: 12px; }
QLabel#SidebarFooterHint { font-size: 11px; }
QLabel#AccountText, QLabel#AccountChip { font-size: 12px; }

QLabel#PageTitle { font-size: 26px; }
QLabel#SectionTitle { font-size: 18px; }
QLabel#SectionMini { font-size: 14px; }
QLabel#Subtle { font-size: 13px; }
QLabel#Tiny { font-size: 12px; }

QLabel#MetricCaption, QLabel#CardCaption { font-size: 11px; }
QLabel#MetricValue { font-size: 20px; }
QLabel#CardValue, QLabel#CardPositive, QLabel#CardNegative { font-size: 22px; }
QLabel#CardHint { font-size: 12px; }

QHeaderView::section { font-size: 12px; padding: 10px 10px; }
QTableWidget { font-size: 14px; }
QTableWidget::item { padding: 0 11px; }

QPushButton { font-size: 13px; }
QComboBox, QLineEdit { font-size: 13px; }

QLabel#CoachStatCaption, QLabel#CoachPriority { font-size: 10px; }
QLabel#CoachReasonChip, QLabel#CoachKpiChip, QLabel#CoachSecondaryChip,
QLabel#CoachPurpose, QLabel#CoachPurposeSecondary { font-size: 11px; }
QLabel#CoachAction, QLabel#CoachHeroMeta { font-size: 13px; }
QLabel#CoachGroupTitle { font-size: 12px; }
QLabel#CoachHeroTitle { font-size: 20px; }

/* ===== KickTrack V4 ===== */
QFrame#ManagerStatusStrip {
    background: transparent;
    border: none;
}
QFrame#ManagerStatusBlock {
    background: #12171A;
    border: 1px solid #232B30;
    border-radius: 7px;
}
QFrame#ManagerStatusBlock[full="true"] {
    background: #281A10;
    border-color: #74421E;
}
QLabel#ManagerStatusCaption {
    color: #79838A;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.8px;
}
QLabel#ManagerStatusValue {
    color: #F4F6F7;
    font-size: 12px;
    font-weight: 700;
}
QLineEdit#GlobalPlayerSearch {
    min-width: 210px;
    max-width: 330px;
    height: 34px;
    border-radius: 8px;
    padding-left: 12px;
    background: #111619;
    border: 1px solid #263036;
}
QLineEdit#GlobalPlayerSearch:focus {
    border-color: #F25A24;
    background: #151B1F;
}

QFrame#DashboardFocusPanel {
    background: #111619;
    border: 1px solid #293239;
    border-left: 3px solid #F25A24;
    border-radius: 12px;
}
QLabel#HeroKicker {
    color: #F25A24;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1.1px;
}
QLabel#HeroTitle {
    color: #FAFBFC;
    font-size: 25px;
    font-weight: 800;
}
QLabel#HeroSubtitle {
    color: #99A3AA;
    font-size: 13px;
}
QFrame#HeroMiniMetric {
    background: #171D21;
    border: 1px solid #283137;
    border-radius: 8px;
}
QLabel#HeroMiniCaption {
    color: #778289;
    font-size: 9px;
    font-weight: 800;
}
QLabel#HeroMiniValue {
    color: #F5F7F8;
    font-size: 16px;
    font-weight: 800;
}

QFrame#ActivityFeed {
    background: #111619;
    border: 1px solid #252E34;
    border-radius: 10px;
}
QFrame#ActivityFeedRow {
    background: #151B1F;
    border: 1px solid transparent;
    border-radius: 7px;
}
QFrame#ActivityFeedRow:hover { border-color: #343F46; }
QLabel#ActivityFeedIcon { color: #F25A24; font-size: 16px; font-weight: 800; }
QLabel#ActivityFeedTitle { color: #F1F4F5; font-size: 13px; font-weight: 700; }
QLabel#ActivityFeedMeta { color: #7F8A91; font-size: 11px; }

QLabel#PlayerAvatar {
    background: #1A2125;
    color: #AAB3B8;
    border: 1px solid #303A40;
    border-radius: 8px;
    font-size: 11px;
    font-weight: 800;
}
QLabel#PlayerIdentityName { color: #F6F8F8; font-size: 14px; font-weight: 800; }
QLabel#PlayerIdentityMeta { color: #7F8A91; font-size: 11px; }

QFrame#SquadPitch {
    background: #0D1215;
    border: 1px solid #263038;
    border-radius: 12px;
}
QFrame#SquadPitch QWidget { background: transparent; }
QPushButton#PitchPlayerCard {
    background: #171E22;
    color: #F5F7F8;
    border: 1px solid #334047;
    border-bottom: 2px solid #F25A24;
    border-radius: 9px;
    padding: 6px 8px;
    font-size: 11px;
    font-weight: 700;
}
QPushButton#PitchPlayerCard:hover { background: #1C252A; border-color: #59666E; }
QComboBox#PitchFormationCombo {
    background: #141B1F;
    color: #F1F4F5;
    border: 1px solid #334047;
    border-radius: 7px;
    padding: 5px 28px 5px 10px;
    font-size: 11px;
    font-weight: 800;
}
QComboBox#PitchFormationCombo:hover { border-color: #59666E; }
QComboBox#PitchFormationCombo::drop-down { border: none; width: 24px; }
QComboBox#PitchFormationCombo QAbstractItemView {
    background: #141B1F;
    color: #F1F4F5;
    border: 1px solid #334047;
    selection-background-color: #273238;
    outline: none;
}
QPushButton#PitchEmptySlot {
    background: #11171A;
    color: #4D5960;
    border: 1px dashed #2D373D;
    border-radius: 9px;
    font-size: 10px;
}

QFrame#MarketPortraitHero {
    background: #0E1316;
    border: 1px solid #252F35;
    border-radius: 10px;
}
QLabel#MarketPortrait {
    background: transparent;
    border: none;
}
QLabel#MarketHeroClub { color: #8C979E; font-size: 12px; }
QLabel#MarketScoreCaption { color: #7F8A91; font-size: 10px; font-weight: 700; }
QLabel#MarketScoreValue { color: #F4F6F7; font-size: 12px; font-weight: 800; }
QProgressBar#MarketScoreBar { background: #222B30; border: none; border-radius: 2px; }
QProgressBar#MarketScoreBar::chunk { background: #F25A24; border-radius: 2px; }
QLabel#MarketReasonBullet { color: #C9D0D4; font-size: 12px; }

QTabWidget#V4SegmentTabs::pane { border: none; background: transparent; }
QTabWidget#V4SegmentTabs QTabBar::tab {
    background: transparent;
    color: #7F898F;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 9px 16px;
    font-weight: 700;
}
QTabWidget#V4SegmentTabs QTabBar::tab:selected {
    color: #F4F6F7;
    border-bottom-color: #F25A24;
}

QFrame#TradeCard {
    background: #12181B;
    border: 1px solid #293239;
    border-radius: 10px;
}
QLabel#TradeCardName { color: #F6F8F8; font-size: 15px; font-weight: 800; }
QLabel#TradeCardPeriod { color: #7E8990; font-size: 11px; }
QLabel#TradeCardResult { font-size: 18px; font-weight: 800; }
QLabel#TradeCardVerdict { color: #F25A24; font-size: 11px; font-weight: 800; }

QFrame#CoachCard {
    border-radius: 10px;
    min-height: 74px;
}
QLabel#CoachPortrait {
    background: #192024;
    border: 1px solid #303B41;
    border-radius: 8px;
}

/* V4 tables: a little more breathing room, less spreadsheet feel. */
QTableWidget#EmbeddedTable, QTableWidget#V4Table {
    background: #101518;
    alternate-background-color: #12191C;
    border-radius: 8px;
}
QTableWidget::item:selected { background: #292017; color: #FFFFFF; }

/* Compact sidebar for mid-size windows. */
QFrame#Sidebar[compact="true"] { min-width: 82px; max-width: 82px; }
QFrame#Sidebar[compact="true"] QPushButton#NavButton { text-align: center; padding-left: 4px; padding-right: 4px; }

QFrame#SquadBenchStrip {
    background: #101619;
    border: 1px solid #252E34;
    border-radius: 10px;
}
QPushButton#BenchPlayerCard {
    background: #171D21;
    color: #F2F4F5;
    border: 1px solid #2C373D;
    border-radius: 8px;
    padding: 7px 9px;
    text-align: left;
    font-size: 11px;
    font-weight: 700;
}
QPushButton#BenchPlayerCard:hover {
    background: #1D252A;
    border-color: #4A565D;
}

"""
