from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


FOTMOB_SEARCH_URL = "https://apigw.fotmob.com/searchapi/suggest"
FOTMOB_PLAYER_IMAGE = "https://images.fotmob.com/image_resources/playerimages/{player_id}.png"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("ß", "ss")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _name_tokens(value: Any) -> set[str]:
    return {token for token in _normalize_text(value).split() if token}


def _extract_candidates(payload: Any) -> list[dict]:
    """Best-effort parser for FotMob's search suggestion payload.

    FotMob's endpoint is not a public API contract, so keep this intentionally
    defensive and only accept objects that look like player results.
    """
    found: list[dict] = []

    # Current FotMob search gateway (2026) returns player suggestions in
    # squadMemberSuggest[0].options.  Keep this explicit path first and retain
    # the recursive fallback below for older payload shapes.
    if isinstance(payload, dict):
        groups = payload.get("squadMemberSuggest")
        if isinstance(groups, list):
            for group in groups:
                if not isinstance(group, dict):
                    continue
                options = group.get("options")
                if not isinstance(options, list):
                    continue
                for option in options:
                    if not isinstance(option, dict):
                        continue
                    option_payload = option.get("payload")
                    if not isinstance(option_payload, dict):
                        continue
                    candidate_id = option_payload.get("id")
                    if candidate_id is None:
                        continue
                    text = str(option.get("text") or "").strip()
                    name = text.split("|", 1)[0].strip() or str(option_payload.get("name") or "").strip()
                    if not name:
                        continue
                    found.append({
                        "fotmob_id": str(candidate_id),
                        "name": name,
                        "team": str(option_payload.get("teamName") or ""),
                        "position": str(option_payload.get("position") or option_payload.get("positionName") or option_payload.get("role") or ""),
                        "shirt_number": str(option_payload.get("shirtNumber") or option_payload.get("jerseyNumber") or option_payload.get("number") or ""),
                        "raw": option,
                    })

    def walk(node: Any, inherited_type: str = "") -> None:
        if isinstance(node, list):
            for item in node:
                walk(item, inherited_type)
            return
        if not isinstance(node, dict):
            return

        result_type = str(
            node.get("type")
            or node.get("resultType")
            or node.get("category")
            or inherited_type
            or ""
        ).lower()
        candidate_id = (
            node.get("id")
            or node.get("playerId")
            or node.get("player_id")
            or node.get("entityId")
        )
        name = node.get("name") or node.get("title") or node.get("playerName")
        team = (
            node.get("teamName")
            or node.get("team")
            or node.get("subtitle")
            or node.get("secondaryText")
        )
        if isinstance(team, dict):
            team = team.get("name") or team.get("title")

        looks_like_player = "player" in result_type
        if not looks_like_player:
            # Some payload versions omit an explicit type but include playerId.
            looks_like_player = node.get("playerId") is not None or node.get("player_id") is not None

        if looks_like_player and candidate_id is not None and name:
            found.append(
                {
                    "fotmob_id": str(candidate_id),
                    "name": str(name),
                    "team": str(team or ""),
                    "position": str(node.get("position") or node.get("positionName") or node.get("role") or ""),
                    "shirt_number": str(node.get("shirtNumber") or node.get("jerseyNumber") or node.get("number") or ""),
                    "raw": node,
                }
            )

        for key, value in node.items():
            child_type = result_type
            if isinstance(key, str) and "player" in key.lower():
                child_type = "player"
            if isinstance(value, (dict, list)):
                walk(value, child_type)

    walk(payload)

    unique: dict[str, dict] = {}
    for item in found:
        unique.setdefault(item["fotmob_id"], item)
    return list(unique.values())


def _candidate_score(player: dict, candidate: dict) -> tuple[int, str]:
    full_name = player.get("full_name") or player.get("name") or ""
    short_name = player.get("name") or full_name
    club = player.get("club") or ""

    expected_full = _normalize_text(full_name)
    expected_short = _normalize_text(short_name)
    candidate_name = _normalize_text(candidate.get("name"))
    candidate_team = _normalize_text(candidate.get("team"))

    score = 0
    reasons: list[str] = []

    if candidate_name and expected_full and candidate_name == expected_full:
        score += 80
        reasons.append("Name exakt")
    elif candidate_name and expected_short and candidate_name == expected_short:
        score += 72
        reasons.append("Kurzname exakt")
    else:
        expected_tokens = _name_tokens(full_name) | _name_tokens(short_name)
        short_tokens = _name_tokens(short_name)
        candidate_tokens = _name_tokens(candidate.get("name"))

        # Kickbase team-profile payloads often expose only the shirt/short name
        # (e.g. "Porath"), while FotMob returns "Finn Porath".  Treat an
        # exact short-name token/suffix match as a strong name signal.  The club
        # score below still has to lift it over the automatic-match threshold,
        # so common surnames without a matching club remain review cases.
        short_is_candidate_token = (
            len(short_tokens) == 1
            and next(iter(short_tokens), "") in candidate_tokens
        )
        short_is_suffix = bool(
            expected_short
            and candidate_name
            and (candidate_name == expected_short or candidate_name.endswith(" " + expected_short))
        )
        if short_is_candidate_token or short_is_suffix:
            score += 68
            reasons.append("Nachname/Kurzname exakt")
        elif expected_tokens and candidate_tokens:
            overlap = len(expected_tokens & candidate_tokens) / max(len(expected_tokens), len(candidate_tokens))
            if overlap >= 0.99:
                score += 68
                reasons.append("Name vollständig")
            elif overlap >= 0.66:
                score += 50
                reasons.append("Name sehr ähnlich")
            elif overlap >= 0.5:
                score += 35
                reasons.append("Name ähnlich")

    if club and candidate_team:
        club_norm = _normalize_text(club)
        if club_norm == candidate_team:
            score += 22
            reasons.append("Verein exakt")
        else:
            club_tokens = _name_tokens(club)
            team_tokens = _name_tokens(candidate.get("team"))
            if club_tokens and team_tokens and (club_tokens & team_tokens):
                score += 12
                reasons.append("Verein ähnlich")

    return min(score, 100), " · ".join(reasons) or "kein sicherer Match"


@dataclass(frozen=True)
class PortraitMatch:
    kickbase_player_id: str
    fotmob_id: str | None
    confidence: int
    state: str
    reason: str
    portrait_url: str | None = None
    portrait_path: str | None = None
    candidate_name: str | None = None
    candidate_team: str | None = None
    candidate_position: str | None = None
    candidate_shirt_number: str | None = None


class FotMobPortraitResolver:
    """Resolve/caches portraits for Kickbase player master rows.

    This intentionally keeps FotMob isolated behind one class. If the source or
    endpoint changes later, the rest of the app keeps using the local player
    master and cached files unchanged.
    """

    def __init__(self, cache_dir: str | Path, timeout: float = 15.0) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                "Referer": "https://www.fotmob.com/",
            },
        )

    def close(self) -> None:
        self.client.close()

    def search(self, player: dict) -> PortraitMatch:
        player_id = str(player.get("player_id") or "")
        full_name = str(player.get("full_name") or player.get("name") or "").strip()
        if not player_id or not full_name:
            return PortraitMatch(player_id, None, 0, "FAILED", "Kickbase-Spielerdaten unvollständig")

        response = self.client.get(FOTMOB_SEARCH_URL, params={"term": full_name, "lang": "en"})
        response.raise_for_status()
        payload = response.json()
        candidates = _extract_candidates(payload)
        if not candidates:
            return PortraitMatch(player_id, None, 0, "FAILED", "Kein FotMob-Spielertreffer")

        ranked = []
        for candidate in candidates:
            score, reason = _candidate_score(player, candidate)
            ranked.append((score, reason, candidate))
        ranked.sort(key=lambda row: row[0], reverse=True)
        score, reason, best = ranked[0]
        runner_up_score = ranked[1][0] if len(ranked) > 1 else -1

        if score < 55:
            fotmob_id = str(best["fotmob_id"])
            return PortraitMatch(
                player_id, fotmob_id, score, "NEEDS_REVIEW", reason,
                FOTMOB_PLAYER_IMAGE.format(player_id=quote(fotmob_id, safe="")), None,
                str(best.get("name") or "").strip() or None,
                str(best.get("team") or "").strip() or None,
                str(best.get("position") or "").strip() or None,
                str(best.get("shirt_number") or "").strip() or None,
            )

        # Auto-accept only a strong AND clearly best candidate. This lets
        # "Porath" -> "Finn Porath" + matching club through, while still
        # protecting us from same-surname collisions in the search results.
        unambiguous = len(ranked) == 1 or (score - runner_up_score) >= 8

        # A surname-only Kickbase name is not enough when FotMob returns more
        # than one player with that surname for the same club. This is exactly
        # the kind of case where an automatic portrait can silently become the
        # wrong person (e.g. two "Becker" at Schalke).
        short_tokens = _name_tokens(player.get("name") or player.get("full_name") or "")
        best_team = _normalize_text(best.get("team"))
        surname_club_collision = False
        if len(short_tokens) == 1 and best_team:
            short_token = next(iter(short_tokens))
            same_identity_candidates = 0
            for candidate_score, _candidate_reason, candidate in ranked:
                candidate_tokens = _name_tokens(candidate.get("name"))
                if short_token not in candidate_tokens:
                    continue
                candidate_team = _normalize_text(candidate.get("team"))
                if candidate_team == best_team or (
                    _name_tokens(candidate.get("team")) & _name_tokens(best.get("team"))
                ):
                    same_identity_candidates += 1
            surname_club_collision = same_identity_candidates >= 2

        fotmob_id = str(best["fotmob_id"])
        state = "MATCHED" if score >= 78 and unambiguous and not surname_club_collision else "NEEDS_REVIEW"
        if surname_club_collision:
            reason = f"{reason} · gleicher Nachname mehrfach im selben Verein"
        elif score >= 78 and not unambiguous:
            reason = f"{reason} · mehrere ähnlich starke Treffer"
        return PortraitMatch(
            player_id,
            fotmob_id,
            score,
            state,
            reason,
            FOTMOB_PLAYER_IMAGE.format(player_id=quote(fotmob_id, safe="")),
            None,
            str(best.get("name") or "").strip() or None,
            str(best.get("team") or "").strip() or None,
            str(best.get("position") or "").strip() or None,
            str(best.get("shirt_number") or "").strip() or None,
        )

    def download(self, match: PortraitMatch) -> PortraitMatch:
        if not match.fotmob_id or not match.portrait_url:
            return match
        destination = self.cache_dir / f"{match.kickbase_player_id}.png"
        response = self.client.get(match.portrait_url)
        if response.status_code == 404:
            return PortraitMatch(
                match.kickbase_player_id,
                match.fotmob_id,
                match.confidence,
                "FAILED",
                "FotMob-Portrait nicht vorhanden",
                match.portrait_url,
                None,
                match.candidate_name,
                match.candidate_team,
                match.candidate_position,
                match.candidate_shirt_number,
            )
        response.raise_for_status()
        content_type = str(response.headers.get("content-type") or "").lower()
        if "image" not in content_type and not response.content.startswith(b"\x89PNG"):
            return PortraitMatch(
                match.kickbase_player_id,
                match.fotmob_id,
                match.confidence,
                "FAILED",
                "Antwort war kein Bild",
                match.portrait_url,
                None,
                match.candidate_name,
                match.candidate_team,
                match.candidate_position,
                match.candidate_shirt_number,
            )
        destination.write_bytes(response.content)
        return PortraitMatch(
            match.kickbase_player_id,
            match.fotmob_id,
            match.confidence,
            "CACHED",
            match.reason,
            match.portrait_url,
            str(destination),
            match.candidate_name,
            match.candidate_team,
            match.candidate_position,
            match.candidate_shirt_number,
        )

    def resolve_and_download(self, player: dict) -> PortraitMatch:
        match = self.search(player)
        if match.state != "MATCHED":
            return match
        return self.download(match)



def cache_review_candidate(storage, player: dict) -> PortraitMatch:
    """Download the already selected FotMob candidate after explicit user approval."""
    player_id = str(player.get("player_id") or "")
    fotmob_id = str(player.get("fotmob_id") or "").strip()
    if not player_id or not fotmob_id:
        return PortraitMatch(player_id, None, 0, "FAILED", "Kein prüfbarer FotMob-Kandidat gespeichert")
    match = PortraitMatch(
        player_id,
        fotmob_id,
        int(player.get("portrait_confidence") or 0),
        "MATCHED",
        str(player.get("portrait_reason") or "Manuell bestätigt"),
        str(player.get("portrait_url") or FOTMOB_PLAYER_IMAGE.format(player_id=quote(fotmob_id, safe=""))),
        None,
        str(player.get("portrait_candidate_name") or "").strip() or None,
        str(player.get("portrait_candidate_team") or "").strip() or None,
        str(player.get("portrait_candidate_position") or "").strip() or None,
        str(player.get("portrait_candidate_shirt_number") or "").strip() or None,
    )
    resolver = FotMobPortraitResolver(storage.portrait_cache_dir())
    try:
        return resolver.download(match)
    finally:
        resolver.close()

def sync_player_master(storage, players: list[dict], *, missing_threshold: int = 3) -> dict:
    """Persist one complete Kickbase competition snapshot into the master table."""
    return storage.sync_player_master(players, missing_threshold=missing_threshold)


def sync_missing_portraits(
    storage,
    *,
    limit: int | None = None,
    retry_failed: bool = False,
    player_ids: list[str] | None = None,
    kickbase_client=None,
    league_id: str | None = None,
) -> dict:
    """Resolve missing portraits sequentially and persist every result.

    We deliberately keep this low-concurrency. It is a one-time/backfill helper,
    while subsequent runs normally contain only newly arrived players.
    """
    rows = storage.players_needing_portrait(
        limit=limit, retry_failed=retry_failed, player_ids=player_ids
    )
    resolver = FotMobPortraitResolver(storage.portrait_cache_dir())
    result = {
        "requested": len(rows),
        "cached": 0,
        "review": 0,
        "failed": 0,
        "matches": [],
    }
    try:
        for row in rows:
            try:
                # The complete team-profile pool often contains only Kickbase's
                # short display name (usually the surname). For unresolved
                # portraits, enrich that one player through the richer Kickbase
                # player-detail endpoint before asking FotMob. This keeps the
                # extra API traffic limited to genuinely ambiguous/missing cases.
                full_name = str(row.get("full_name") or row.get("name") or "").strip()
                short_name = str(row.get("name") or "").strip()
                needs_identity_enrichment = bool(full_name) and (
                    full_name.casefold() == short_name.casefold() or len(_name_tokens(full_name)) <= 1
                )
                if needs_identity_enrichment and kickbase_client is not None and league_id:
                    try:
                        details = kickbase_client.player_details(str(league_id), str(row.get("player_id") or ""))
                        richer_name = str(details.get("full_name") or "").strip() if isinstance(details, dict) else ""
                        if richer_name and richer_name.casefold() != full_name.casefold():
                            refreshed = storage.enrich_player_master_identity(str(row.get("player_id") or ""), details)
                            if refreshed:
                                row = refreshed
                    except Exception:
                        # Name enrichment is opportunistic. A failed Kickbase
                        # detail request must not block the normal FotMob review.
                        pass

                match = resolver.resolve_and_download(row)
            except Exception as exc:
                match = PortraitMatch(
                    str(row.get("player_id") or ""),
                    None,
                    0,
                    "FAILED",
                    str(exc).splitlines()[0][:240],
                )
            storage.save_portrait_match(match)
            result["matches"].append(match)
            if match.state == "CACHED":
                result["cached"] += 1
            elif match.state == "NEEDS_REVIEW":
                result["review"] += 1
            else:
                result["failed"] += 1
    finally:
        resolver.close()
    return result
