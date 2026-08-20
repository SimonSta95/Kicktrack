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
