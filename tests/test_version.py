from pathlib import Path
import tomllib

from app.version import APP_DISPLAY_NAME, APP_NAME, __version__


def test_runtime_and_project_versions_stay_in_sync():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__
    assert APP_NAME in APP_DISPLAY_NAME
    assert f"V{__version__}" in APP_DISPLAY_NAME
