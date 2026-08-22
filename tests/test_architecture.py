from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _class_methods(path: str, class_name: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}


def test_main_window_module_stays_composition_focused():
    path = ROOT / "app" / "ui.py"
    assert len(path.read_text(encoding="utf-8").splitlines()) < 1800
    methods = _class_methods("app/ui.py", "MainWindow")
    assert "_build_market_page" not in methods
    assert "_refresh_league_page" not in methods
    assert "_refresh_transfers" not in methods


def test_dialog_facade_has_no_concrete_dialog_implementations():
    tree = ast.parse((ROOT / "app" / "dialogs.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.ClassDef) for node in tree.body)


def test_kickbase_client_transport_is_separated_from_endpoint_domains():
    path = ROOT / "app" / "kickbase.py"
    assert len(path.read_text(encoding="utf-8").splitlines()) < 300
    methods = _class_methods("app/kickbase.py", "KickbaseClient")
    assert "login" in methods
    assert "list_player_for_sale" not in methods
    assert "market_overview" not in methods
    assert "manager_transfers" not in methods


def test_no_wildcard_imports_in_refactored_ui_modules():
    files = [
        "app/ui.py",
        "app/dialogs.py",
        "app/action_dialogs.py",
        "app/player_dialogs.py",
        "app/manager_dialogs.py",
        "app/market_mixin.py",
        "app/intelligence_mixin.py",
        "app/coach_mixin.py",
        "app/sync_mixin.py",
        "app/dashboard_squad_mixin.py",
        "app/league_mixin.py",
        "app/analysis_mixin.py",
    ]
    for rel in files:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert all(alias.name != "*" for alias in node.names), rel


def test_refactored_mixins_do_not_have_unbound_helper_methods():
    files = [
        "app/market_mixin.py",
        "app/intelligence_mixin.py",
        "app/coach_mixin.py",
        "app/sync_mixin.py",
        "app/dashboard_squad_mixin.py",
        "app/league_mixin.py",
        "app/analysis_mixin.py",
    ]
    for rel in files:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            for method in (node for node in cls.body if isinstance(node, ast.FunctionDef)):
                first_arg = method.args.args[0].arg if method.args.args else None
                decorators = {
                    decorator.id
                    for decorator in method.decorator_list
                    if isinstance(decorator, ast.Name)
                }
                assert (
                    first_arg in {"self", "cls"}
                    or "staticmethod" in decorators
                    or "classmethod" in decorators
                    or method.name == "__new__"
                ), f"{rel}:{method.lineno} {cls.name}.{method.name} is missing self/cls or a binding decorator"


def test_refactored_mixins_do_not_reference_mainwindow_directly():
    files = [
        "app/market_mixin.py",
        "app/intelligence_mixin.py",
        "app/coach_mixin.py",
        "app/sync_mixin.py",
        "app/dashboard_squad_mixin.py",
        "app/league_mixin.py",
        "app/analysis_mixin.py",
    ]
    for rel in files:
        source = (ROOT / rel).read_text(encoding="utf-8")
        assert "MainWindow." not in source, rel


def test_market_load_is_progressive_and_uses_background_enrichment():
    source = (ROOT / "app" / "market_mixin.py").read_text(encoding="utf-8")
    assert "def _show_market_skeleton" in source
    assert "def _start_market_enrichment" in source
    assert "def _start_market_status_enrichment" in source
    assert "FunctionWorker(enrich_market_background)" in source
    assert "FunctionWorker(load_statuses)" in source
    fast_block = source.split("def load_market_fast():", 1)[1].split("worker = FunctionWorker(load_market_fast)", 1)[0]
    assert "competition_player_statuses" not in fast_block
    assert "build_predictions" not in fast_block


def test_main_window_tracks_market_background_workers():
    source = (ROOT / "app" / "ui.py").read_text(encoding="utf-8")
    assert "self._market_enrichment_worker" in source
    assert "self._market_status_worker" in source
    assert "self._market_load_generation" in source


def test_facts_first_primary_views_do_not_render_legacy_player_scores():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "app"
    for filename in ("market_mixin.py", "coach_mixin.py", "dashboard_squad_mixin.py"):
        text = (root / filename).read_text(encoding="utf-8")
        assert "MarketScoreBar(" not in text
        assert 'f"PRIO {' not in text
        assert 'Value {int(' not in text


def test_loading_skeleton_avoids_qgraphics_effect_painter_recursion():
    source = (ROOT / "app" / "loading_skeleton.py").read_text(encoding="utf-8")
    assert "QGraphicsOpacityEffect" not in source
    assert "setGraphicsEffect(" not in source


def test_refresh_all_only_refreshes_visible_page():
    source = (ROOT / "app" / "ui.py").read_text(encoding="utf-8")
    block = source.split("def refresh_all(self) -> None:", 1)[1].split("def closeEvent", 1)[0]
    assert "_refresh_visible_page" in block
    assert "_refresh_squad()" not in block
    assert "_refresh_transfers(" not in block
    assert "_refresh_analysis()" not in block


def test_market_missing_daily_changes_are_backfilled_in_background_and_persistently_cached():
    source = (ROOT / "app" / "market_mixin.py").read_text(encoding="utf-8")
    block = source.split("def enrich_market_background():", 1)[1].split("# Persist/merge market-value analytics", 1)[0]
    assert "market_daily_changes" in block
    assert "market:daily_changes:" in block
    assert "cache_get" in block
    assert "cache_set" in block


def test_squad_tab_does_not_scan_complete_market_value_history():
    source = (ROOT / "app" / "dashboard_squad_mixin.py").read_text(encoding="utf-8")
    block = source.split("def _refresh_squad(self) -> None:", 1)[1]
    assert "self.storage.all_market_value_rows()" not in block
    assert "_reversal_reference_cache" in block


def test_navigation_skips_recomputing_an_already_rendered_non_market_tab():
    source = (ROOT / "app" / "ui.py").read_text(encoding="utf-8")
    block = source.split("def _refresh_visible_page(", 1)[1].split("def _page_header", 1)[0]
    assert "_page_loaded_league" in block
    assert "if not force and index != 2" in block


def test_squad_sorting_uses_atomic_items_and_popup_role_menu():
    ui_source = (ROOT / "app" / "ui.py").read_text(encoding="utf-8")
    squad_source = (ROOT / "app" / "dashboard_squad_mixin.py").read_text(encoding="utf-8")
    components_source = (ROOT / "app" / "ui_components.py").read_text(encoding="utf-8")
    assert "SquadRoleDelegate" in ui_source
    assert "self.squad_table.setSortingEnabled(True)" in ui_source
    assert "cellClicked.connect(self._edit_squad_role_cell)" in ui_source
    assert "class SquadRoleDelegate" in components_source
    assert "def open_role_menu(" in components_source
    assert "QMenu(table)" in components_source
    assert "menu.exec(popup_pos)" in components_source
    assert "def createEditor(" not in components_source.split("class SquadRoleDelegate", 1)[1].split("class RecommendationChipDelegate", 1)[0]
    click_block = squad_source.split("def _edit_squad_role_cell", 1)[1].split("def _size_squad_detail_table", 1)[0]
    assert "self.squad_role_delegate.open_role_menu(self.squad_table, index)" in click_block
    assert "editItem(" not in click_block
    render_block = squad_source.split("def _render_squad_detail_rows", 1)[1].split("def _edit_squad_role_cell", 1)[0]
    assert "staged_rows" in render_block
    assert render_block.index("staged_rows.append(items)") < render_block.index("table.setRowCount(0)")
    assert "table.setSortingEnabled(False)" in render_block
    assert "table.setSortingEnabled(True)" in render_block
    assert "table.setRowCount(0)" in render_block
    assert "setCellWidget" not in render_block
    assert "role_item.setFlags(role_item.flags() | Qt.ItemIsEditable)" in render_block
    assert "for col, item in enumerate(items):" in render_block
    assert "MUTED," in squad_source.split("from .ui_components import (", 1)[1].split(")", 1)[0]
    assert 'tooltip = f"Dynamik: {label}' in render_block
    assert 'probability_value = None' in render_block


def test_manager_dialogs_imports_player_detail_window_directly():
    source = (ROOT / "app" / "manager_dialogs.py").read_text(encoding="utf-8")
    assert "from .player_dialogs import open_player_detail_window" in source
    assert source.count("open_player_detail_window(") >= 2


def test_market_trend_icons_use_clean_line_arrows_with_distinct_reversals():
    source = (ROOT / "app" / "ui_components.py").read_text(encoding="utf-8")
    assert 'The requested look is closer to common outline arrow/chevron packs' in source
    assert 'def draw_chevron(' in source
    assert 'if code == "TURNING_UP":' in source
    assert 'if code == "TURNING_DOWN":' in source
    assert '("TURNING_UP", "Wende ↑")' in source
    assert '("TURNING_DOWN", "Wende ↓")' in source
    assert 'qta.icon(icon_name, color=color.name())' not in source


def test_offer_inbox_unifies_kickbase_and_manager_offers_without_duplicate_sale_ui():
    dialogs = (ROOT / "app" / "action_dialogs.py").read_text(encoding="utf-8")
    league = (ROOT / "app" / "league_mixin.py").read_text(encoding="utf-8")
    player = (ROOT / "app" / "player_dialogs.py").read_text(encoding="utf-8")
    theme = (ROOT / "app" / "theme.py").read_text(encoding="utf-8")
    ui = (ROOT / "app" / "ui.py").read_text(encoding="utf-8")
    assert "class OfferInboxDialog" in dialogs
    assert '"user_name": "Kickbase"' in dialogs
    assert "self.client.accept_kickbase_sale_offer" in dialogs
    assert "self.client.accept_manager_offer" in dialogs
    assert 'accept_btn = QPushButton("ANNEHMEN")' in dialogs
    assert 'accept_btn.setObjectName("CompactDangerActionButton")' in dialogs
    listing_block = dialogs.split("class ListingManagementDialog", 1)[1].split("class FinancingScenarioDialog", 1)[0]
    assert 'QPushButton("ANGEBOTE")' not in listing_block
    assert "AN KICKBASE VERKAUFEN" not in listing_block
    assert "_sell_to_kickbase" not in listing_block
    assert 'QPushButton("ANGEBOTE")' in player
    assert 'QPushButton("AUF MARKT")' in player
    assert 'self.manage_listing_btn.setObjectName("CompactDangerActionButton")' in player
    assert 'self.offers_btn.setObjectName("CompactDangerActionButton")' in player
    assert "OfferInboxDialog(" in league
    assert 'offers_btn = QPushButton(f"ANGEBOTE {offer_count}" if offer_count else "ANGEBOTE")' in league
    assert 'listing_btn.setObjectName("CompactDangerActionButton")' in league
    assert 'offers_btn.setObjectName("CompactDangerActionButton")' in league
    assert "QPushButton#CompactDangerActionButton" in theme
    assert 'QLabel("EIGENE LISTINGS")' in ui


def test_market_value_chart_supports_rubberband_zoom_and_ranges():
    source = (ROOT / "app" / "player_dialogs.py").read_text(encoding="utf-8")
    assert "QChartView.RectangleRubberBand" in source
    assert "def _set_history_range(self, days: int | None)" in source
    assert "def _reset_history_zoom(self)" in source
    assert '(("7T", 7), ("30T", 30), ("90T", 90), ("1J", 365))' in source
    assert 'QPushButton("ZOOM RESET")' in source


def test_market_table_has_dedicated_bid_action_button():
    source = (ROOT / "app" / "market_mixin.py").read_text(encoding="utf-8")
    assert '"ABLAUF", "AKTION"' in source
    assert 'bid_btn = QPushButton("BIETEN")' in source
    assert "def _open_market_bid_for_player" in source


def test_market_detail_selection_is_click_authoritative():
    source = (ROOT / "app" / "market_mixin.py").read_text(encoding="utf-8")
    build = source.split("def _build_market_page", 1)[1].split("def _scanner_delta", 1)[0]
    assert "self.market_table.cellClicked.connect(self._market_row_clicked)" in build
    assert "itemSelectionChanged.connect" not in build
    assert "def _market_selection_changed" not in source



def test_listing_action_cell_has_no_container_box():
    league = (ROOT / "app" / "league_mixin.py").read_text(encoding="utf-8")
    theme = (ROOT / "app" / "theme.py").read_text(encoding="utf-8")
    assert 'action_widget.setObjectName("TransparentActionCell")' in league
    assert 'QWidget#TransparentActionCell {' in theme
    transparent_block = theme.split('QWidget#TransparentActionCell {', 1)[1].split('}', 1)[0]
    assert 'background: transparent;' in transparent_block
    assert 'border: none;' in transparent_block


def test_active_bid_premium_uses_actual_bid_before_listing_price():
    source = (ROOT / "app" / "ui_components.py").read_text(encoding="utf-8")
    assert 'own_bid = int(bid.get("bid") or bid.get("amount") or bid.get("price") or 0)' in source
    assert 'own_bid = int(bid.get("price") or bid.get("bid")' not in source

