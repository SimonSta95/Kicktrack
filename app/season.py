from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
SEASON_MODE_START = datetime(2026, 8, 21, 22, 0, tzinfo=BERLIN)


def current_season_start(reference: date | datetime | None = None) -> date:
    """Return the start boundary of the current Kickbase/Bundesliga season.

    Kickbase's manager transfer endpoint can retain records from a previous
    season after the league reset. We use July 1 as the stable season boundary:
    preseason activity in July/August belongs to the new season, while records
    from the completed season remain historical data.
    """
    if reference is None:
        reference_date = datetime.now(UTC).date()
    elif isinstance(reference, datetime):
        reference_date = reference.date()
    else:
        reference_date = reference

    start_year = reference_date.year if reference_date.month >= 7 else reference_date.year - 1
    return date(start_year, 7, 1)


def season_label(reference: date | datetime | None = None) -> str:
    start = current_season_start(reference)
    return f"{start.year}/{str(start.year + 1)[-2:]}"


def season_mode(reference: datetime | None = None, override: str | None = None) -> str:
    """Resolve the UI mode independently from the availability of season stats.

    ``AUTO`` switches to SEASON exactly at the configured Berlin kickoff.
    Manual overrides are intentionally supported so the season UI can be tested
    before kickoff without changing the system clock.
    """
    normalized = str(override or "AUTO").strip().upper()
    if normalized in {"PRESEASON", "SEASON"}:
        return normalized

    now = reference or datetime.now(BERLIN)
    if now.tzinfo is None:
        now = now.replace(tzinfo=BERLIN)
    else:
        now = now.astimezone(BERLIN)
    return "SEASON" if now >= SEASON_MODE_START else "PRESEASON"


def season_mode_active(reference: datetime | None = None, override: str | None = None) -> bool:
    return season_mode(reference, override) == "SEASON"


def filter_current_season_transfers(
    events: list[dict], reference: date | datetime | None = None
) -> list[dict]:
    """Keep only transfer events belonging to the current season window."""
    cutoff = current_season_start(reference)
    result: list[dict] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        raw = str(event.get("transferred_at") or "").strip()
        if not raw:
            continue
        try:
            transferred = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        if transferred >= cutoff:
            result.append(event)
    return result
