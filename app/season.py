from __future__ import annotations

from datetime import UTC, date, datetime


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
