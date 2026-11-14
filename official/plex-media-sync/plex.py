"""Read-only Plex Media Server client and credential-free normalization.

The host's bounded `network.request` transport accepts only a fixed header allowlist, which
does not include `X-Plex-Token`; Plex's documented alternative is the `X-Plex-Token` query
parameter. The token therefore travels in the request URL to the configured server (and to
plex.tv once, at connect time, to learn the account identity). URLs are built only here and
are never returned, stored outside the private secret record, or included in any message.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlencode

from engine import (
    SyncError,
    checked_json,
    fetch,
    identifier_text,
    integer,
    looks_like_anime,
    optional_int,
    remote_error,
    server_url,
    texts,
)

SOURCE = "plex"
LABEL = "Plex"
PLEX_TV = "https://plex.tv"
PRODUCT = "Unnamed Tracking"
SECTION_KINDS = {"movie": "movie", "show": "show"}
# Plex's numeric metadata types used by /library/sections/{id}/all?type=
TYPE_MOVIE, TYPE_SHOW, TYPE_EPISODE = 1, 2, 4
GUID = re.compile(r"^(imdb|tmdb|tvdb)://([A-Za-z0-9._-]{1,64})$")
TICKS_PER_MS = 10_000


def token_value(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{8,512}", value.strip()):
        raise SyncError("Enter a valid Plex token (letters, digits, '-', '_', '.', '~').")
    return value.strip()


def _url(base: str, path: str, token: str | None = None, **query: Any) -> str:
    if token:
        query["X-Plex-Token"] = token
    return base + path + ("?" + urlencode(query) if query else "")


def _container(data: Any, what: str) -> dict:
    container = data.get("MediaContainer") if isinstance(data, dict) else None
    if not isinstance(container, dict):
        raise remote_error(LABEL, what)
    return container


def connect(values: dict, device: str) -> dict:
    url = server_url(values.get("server_url"), LABEL)
    token = token_value(values.get("token"))
    identity = _container(fetch(LABEL, _url(url, "/identity")), "an invalid server identity")
    server_id = identity.get("machineIdentifier")
    if not isinstance(server_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", server_id):
        raise remote_error(LABEL, "an invalid server identity")
    try:
        root = _container(fetch(LABEL, _url(url, "/", token)), "an invalid server description")
    except SyncError as exc:
        if exc.code == "authentication":
            raise SyncError("Plex refused this token for this server.",
                            code="authentication") from None
        raise
    try:
        account = fetch(
            LABEL,
            _url(PLEX_TV, "/api/v2/user", token,
                 **{"X-Plex-Client-Identifier": device, "X-Plex-Product": PRODUCT}),
        )
    except SyncError as exc:
        if exc.code == "authentication":
            raise SyncError("plex.tv did not accept this token.", code="authentication") from None
        raise SyncError(
            "plex.tv could not confirm which Plex account this token belongs to. "
            "Check the host's internet access and try again.",
            code=exc.code,
        ) from None
    remote_id = account.get("uuid") if isinstance(account, dict) else None
    if not isinstance(remote_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", remote_id):
        raise remote_error("plex.tv", "an invalid account")
    conn = {
        "url": url,
        "server_id": server_id,
        "server_name": str(root.get("friendlyName") or "Plex")[:100],
        "remote_user_id": remote_id,
        "remote_user_name": str(account.get("username") or account.get("title") or "Plex")[:100],
    }
    conn["libraries"] = libraries(conn, token)
    conn["token"] = token
    return conn


def libraries(conn: dict, token: str) -> list[dict]:
    container = _container(fetch(LABEL, _url(conn["url"], "/library/sections", token)),
                           "an invalid library list")
    rows = container.get("Directory", [])
    if not isinstance(rows, list) or len(rows) > 1000:
        raise remote_error(LABEL, "an invalid library list")
    found = []
    for row in rows:
        if not isinstance(row, dict) or row.get("type") not in SECTION_KINDS:
            continue  # music and photo libraries are never read
        found.append({
            "id": identifier_text(row.get("key"), LABEL),
            "name": str(row.get("title") or "Library")[:200],
            "kind": SECTION_KINDS[row["type"]],
        })
    return found


def _page(conn: dict, token: str, library: dict, kind: int, offset: int, limit: int):
    container = _container(
        fetch(
            LABEL,
            _url(
                conn["url"],
                "/library/sections/" + quote(library["id"], safe="") + "/all",
                token,
                type=kind,
                includeGuids=1,
                **{"X-Plex-Container-Start": offset, "X-Plex-Container-Size": limit},
            ),
        ),
        "an invalid library page",
    )
    rows = container.get("Metadata", [])
    total = container.get("totalSize", container.get("size"))
    return rows, total


def roots(conn: dict, token: str, library: dict, offset: int, limit: int):
    kind = TYPE_MOVIE if library["kind"] == "movie" else TYPE_SHOW
    return _page(conn, token, library, kind, offset, limit)


def episodes(conn: dict, token: str, library: dict, offset: int, limit: int):
    return _page(conn, token, library, TYPE_EPISODE, offset, limit)


def item(conn: dict, token: str, external_id: str) -> dict:
    container = _container(
        fetch(LABEL, _url(conn["url"], "/library/metadata/" + quote(external_id, safe=""),
                          token, includeGuids=1)),
        "an invalid item",
    )
    rows = container.get("Metadata")
    if not isinstance(rows, list) or len(rows) != 1:
        raise remote_error(LABEL, "an invalid item")
    return rows[0]


def watch_fields(conn: dict, external_id: str) -> dict:
    """The item's page in the server's own web app; never a token or a file path."""
    key = quote("/library/metadata/" + external_id, safe="")
    return {
        "watch_url": conn["url"] + "/web/index.html#!/server/"
        + quote(conn["server_id"], safe="") + "/details?key=" + key,
        "watch_label": ("Plex · " + conn["server_name"])[:80],
    }


def artwork(conn: dict, item: dict) -> dict:
    """Plex serves artwork only with a token, which must never appear in a stored URL."""
    return {}


def sign_out(conn: dict, token: str) -> None:
    """Plex tokens belong to the Plex account; they are revoked at plex.tv, not here."""


def _tags(row: dict, name: str, limit: int = 50) -> list[str]:
    values = row.get(name, [])
    if not isinstance(values, list):
        return []
    return texts([v.get("tag") for v in values if isinstance(v, dict)], limit=limit)


def _provider_ids(row: dict) -> dict:
    found = {}
    guids = row.get("Guid", [])
    for guid in guids if isinstance(guids, list) else []:
        match = GUID.match(guid.get("id", "")) if isinstance(guid, dict) and isinstance(
            guid.get("id"), str) else None
        if match:
            found.setdefault(match.group(1), match.group(2))
    return found


def playback(row: dict) -> dict:
    offset = integer(row.get("viewOffset"), LABEL, maximum=10**12, default=0)
    duration = optional_int(row.get("duration"), maximum=10**12)
    plays = integer(row.get("viewCount"), LABEL, maximum=10**9, default=0)
    last = optional_int(row.get("lastViewedAt"), maximum=10**12)
    position = offset * TICKS_PER_MS
    runtime = duration * TICKS_PER_MS if duration else None
    return {
        "position_ticks": position,
        "runtime_ticks": runtime,
        "percentage": min(100.0, 100 * position / runtime) if runtime else None,
        "play_count": plays,
        "last_played_at": last,
    }


def normalize(row: Any, kind: str) -> dict:
    """One movie or show from a library page, without artwork (Plex images need a token)."""
    expected = "movie" if kind == "movie" else "show"
    if not isinstance(row, dict) or row.get("type") != expected:
        raise remote_error(LABEL, "an unsupported library item")
    external = identifier_text(row.get("ratingKey"), LABEL)
    title = row.get("title")
    if not isinstance(title, str) or not title.strip():
        raise remote_error(LABEL, "an item without a title")
    year = optional_int(row.get("year"), minimum=1, maximum=9999)
    genres = _tags(row, "Genre")
    labels = _tags(row, "Label")
    date = row.get("originallyAvailableAt")
    date = date if isinstance(date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else None
    people = [
        {"name": tag, "role": "", "type": "Director"} for tag in _tags(row, "Director", 10)
    ] + [
        {"name": tag, "role": "", "type": "Writer"} for tag in _tags(row, "Writer", 10)
    ]
    for role in (row.get("Role") or [])[:20] if isinstance(row.get("Role"), list) else []:
        if isinstance(role, dict) and isinstance(role.get("tag"), str):
            people.append({"name": role["tag"][:256], "role": str(role.get("role") or "")[:256],
                           "type": "Actor"})
    metadata = {
        "description": str(row.get("summary") or "")[:20000],
        "premiere_date": date or (f"{year:04}-01-01" if year else None),
        "date_precision": "day" if date else "year" if year else None,
        "studios": texts([row.get("studio")]),
        "countries": _tags(row, "Country"),
        "tags": labels,
        "age_rating": str(row.get("contentRating") or "")[:20],
        "director": ", ".join(_tags(row, "Director", 10))[:200],
        "writer": ", ".join(_tags(row, "Writer", 10))[:200],
        "people": people,
    }
    rating = row.get("userRating")
    if isinstance(rating, (int, float)) and not isinstance(rating, bool) and 0 <= rating <= 10:
        metadata["rating_overall"] = rating
    metadata = {k: v for k, v in metadata.items() if v not in (None, "", [])}
    if kind == "movie":
        details = playback(row)
        played = details["play_count"] > 0
        in_progress = details["position_ticks"] > 0
    else:
        leaves = integer(row.get("leafCount"), LABEL, maximum=10**6, default=0)
        viewed = integer(row.get("viewedLeafCount"), LABEL, maximum=10**6, default=0)
        details = None
        played = leaves > 0 and viewed >= leaves
        in_progress = 0 < viewed < leaves
    duration = optional_int(row.get("duration"), maximum=10**12)
    result = {
        "external_id": external,
        "title": title.strip()[:500],
        "genres": [g[:128] for g in genres],
        "runtime_minutes": min(100000, duration // 60000) if duration else None,
        "played": played,
        "in_progress": in_progress,
        "provider_ids": _provider_ids(row),
        "release_year": year,
        "metadata": metadata,
        "playback": details,
        "anime": looks_like_anime(genres, labels),
    }
    return checked_json(result, LABEL)


def normalize_episode(row: Any) -> dict:
    if not isinstance(row, dict) or row.get("type") != "episode":
        raise remote_error(LABEL, "an invalid episode page")
    details = playback(row)
    season = optional_int(row.get("parentIndex"), maximum=10000)
    number = optional_int(row.get("index"), maximum=100000)
    return {
        "external_id": identifier_text(row.get("ratingKey"), LABEL),
        "series_id": identifier_text(row.get("grandparentRatingKey"), LABEL),
        "season": season,
        "number": number,
        "title": str(row.get("title") or "")[:500],
        "watched": details["play_count"] > 0,
        "playback": details,
    }
