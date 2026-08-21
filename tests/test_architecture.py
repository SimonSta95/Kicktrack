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
