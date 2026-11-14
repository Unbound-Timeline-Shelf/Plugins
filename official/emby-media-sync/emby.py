"""Read-only Emby client and credential-free normalization.

The person signs in once with their Emby username and password; the password goes only to
the configured server's AuthenticateByName endpoint and is never stored. The resulting
user access token (not an administrator API key) is sent in the `X-Emby-Token` header,
which the host's outbound allowlist permits. All reads use that user's own views.
"""

from __future__ import annotations

import re
from datetime import datetime
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
    percentage,
    remote_error,
    server_url,
    texts,
)

SOURCE = "emby"
LABEL = "Emby"
VERSION = "0.1.0"
CLIENT = 'Emby Client="Unnamed Tracking", Device="Media Sync", DeviceId="{}", Version="{}"'
FIELDS = "ProviderIds,Overview,Genres,Tags,Studios,People,ProductionLocations,PremiereDate"
VIEW_KINDS = {"movies": "movie", "tvshows": "show"}
ID = re.compile(r"[A-Za-z0-9-]{1,128}")


def _id(value: Any, what: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise remote_error(LABEL, what)
    return value


def _get(conn: dict, token: str, path: str, **query: Any) -> Any:
    url = conn["url"] + path + ("?" + urlencode(query) if query else "")
    return fetch(LABEL, url, headers={"X-Emby-Token": token})


def connect(values: dict, device: str) -> dict:
    url = server_url(values.get("server_url"), LABEL)
    username = values.get("username")
    password = values.get("password")
    if not isinstance(username, str) or not username.strip() or len(username) > 256:
        raise SyncError("Enter your Emby username.")
    if not isinstance(password, str) or len(password) > 1024:
        raise SyncError("Enter your Emby password (it is used once and never saved).")
    public = fetch(LABEL, url + "/System/Info/Public")
    if not isinstance(public, dict):
        raise remote_error(LABEL, "an invalid server description")
    server_id = _id(public.get("Id"), "an invalid server identity")
    try:
        session = fetch(
            LABEL,
            url + "/Users/AuthenticateByName",
            method="POST",
            headers={"Authorization": CLIENT.format(device, VERSION)},
            body={"Username": username.strip(), "Pw": password},
        )
    except SyncError as exc:
        if exc.code == "authentication":
            raise SyncError("Emby did not accept this username and password.",
                            code="authentication") from None
        raise
    user = session.get("User") if isinstance(session, dict) else None
    token = session.get("AccessToken") if isinstance(session, dict) else None
    if (
        not isinstance(user, dict)
        or not isinstance(token, str)
        or not re.fullmatch(r"[A-Za-z0-9._-]{8,512}", token)
    ):
        raise remote_error(LABEL, "an invalid sign-in")
    if session.get("ServerId") not in {None, server_id}:
        raise remote_error(LABEL, "a sign-in for a different server")
    conn = {
        "url": url,
        "server_id": server_id,
        "server_name": str(public.get("ServerName") or "Emby")[:100],
        "remote_user_id": _id(user.get("Id"), "an invalid user"),
        "remote_user_name": str(user.get("Name") or username.strip())[:100],
    }
    conn["libraries"] = libraries(conn, token)
    conn["token"] = token
    return conn


def libraries(conn: dict, token: str) -> list[dict]:
    data = _get(conn, token, "/Users/" + conn["remote_user_id"] + "/Views")
    rows = data.get("Items") if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) > 1000:
        raise remote_error(LABEL, "an invalid library list")
    found = []
    for row in rows:
        if not isinstance(row, dict) or row.get("CollectionType") not in VIEW_KINDS:
            continue  # music, books, Live TV and collections are never read
        found.append({
            "id": _id(row.get("Id"), "an invalid library"),
            "name": str(row.get("Name") or "Library")[:200],
            "kind": VIEW_KINDS[row["CollectionType"]],
        })
    return found


def _page(conn: dict, token: str, library: dict, types: str, offset: int, limit: int):
    data = _get(
        conn, token, "/Users/" + conn["remote_user_id"] + "/Items",
        ParentId=library["id"], Recursive="true", IncludeItemTypes=types, Fields=FIELDS,
        EnableUserData="true", SortBy="SortName", SortOrder="Ascending",
        StartIndex=offset, Limit=limit,
    )
    if not isinstance(data, dict):
        raise remote_error(LABEL, "an invalid library page")
    return data.get("Items"), data.get("TotalRecordCount")


def roots(conn: dict, token: str, library: dict, offset: int, limit: int):
    return _page(conn, token, library, "Movie" if library["kind"] == "movie" else "Series",
                 offset, limit)


def episodes(conn: dict, token: str, library: dict, offset: int, limit: int):
    return _page(conn, token, library, "Episode", offset, limit)


def item(conn: dict, token: str, external_id: str) -> dict:
    data = _get(conn, token, "/Users/" + conn["remote_user_id"] + "/Items/"
                + quote(external_id, safe=""), Fields=FIELDS)
    if not isinstance(data, dict):
        raise remote_error(LABEL, "an invalid item")
    return data


def watch_fields(conn: dict, external_id: str) -> dict:
    """The item's page in the server's own web app; never a token or a file path."""
    return {
        "watch_url": conn["url"] + "/web/index.html#!/item?id=" + quote(external_id, safe="")
        + "&serverId=" + quote(conn["server_id"], safe=""),
        "watch_label": ("Emby · " + conn["server_name"])[:80],
    }


def artwork(conn: dict, item: dict) -> dict:
    """Token-free image addresses; Emby serves item images without authentication."""
    base = conn["url"] + "/Items/" + quote(item["external_id"], safe="") + "/Images/"
    images = item.get("images", {})
    return {
        "poster_url": base + "Primary" if images.get("poster") else None,
        "backdrop_url": base + "Backdrop/0" if images.get("backdrop") else None,
    }


def sign_out(conn: dict, token: str) -> None:
    """End the session the plugin opened, so the token stops working on the server too."""
    fetch(LABEL, conn["url"] + "/Sessions/Logout", method="POST",
          headers={"X-Emby-Token": token}, body={})


def _timestamp(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        # Emby sends up to seven fractional digits; Python accepts at most six.
        text = re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00"))
        return int(datetime.fromisoformat(text).timestamp())
    except (ValueError, OverflowError):
        raise remote_error(LABEL, "an invalid playback timestamp") from None


def playback(row: dict) -> dict:
    user = row.get("UserData")
    if not isinstance(user, dict) or not isinstance(user.get("Played"), bool):
        raise remote_error(LABEL, "an item without its user playback data")
    ticks = integer(user.get("PlaybackPositionTicks"), LABEL, default=0)
    runtime = optional_int(row.get("RunTimeTicks"))
    percent = percentage(user.get("PlayedPercentage"))
    if percent is None and runtime:
        percent = min(100.0, 100 * ticks / runtime)
    return {
        "position_ticks": ticks,
        "runtime_ticks": runtime or None,
        "percentage": percent,
        "play_count": integer(user.get("PlayCount"), LABEL, maximum=10**9, default=0),
        "last_played_at": _timestamp(user.get("LastPlayedDate")),
    }


def normalize(row: Any, kind: str) -> dict:
    expected = "Movie" if kind == "movie" else "Series"
    if not isinstance(row, dict) or row.get("Type") != expected:
        raise remote_error(LABEL, "an unsupported library item")
    external = identifier_text(row.get("Id"), LABEL)
    title = row.get("Name")
    if not isinstance(title, str) or not title.strip():
        raise remote_error(LABEL, "an item without a title")
    details = playback(row)
    tags, genres = texts(row.get("Tags")), texts(row.get("Genres"))
    year = optional_int(row.get("ProductionYear"), minimum=1, maximum=9999)
    raw_ids = row.get("ProviderIds")
    ids = {
        k.lower(): str(v)[:256]
        for k, v in (raw_ids.items() if isinstance(raw_ids, dict) else [])
        if isinstance(k, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,50}", k)
        and isinstance(v, (str, int)) and not isinstance(v, bool) and str(v).strip()
    }
    images = row.get("ImageTags") if isinstance(row.get("ImageTags"), dict) else {}
    people = [p for p in (row.get("People") or [])[:40] if isinstance(p, dict)] if isinstance(
        row.get("People"), list) else []
    studios = row.get("Studios") if isinstance(row.get("Studios"), list) else []
    premiere = row.get("PremiereDate")
    premiere = premiere[:10] if isinstance(premiere, str) and re.match(
        r"\d{4}-\d{2}-\d{2}", premiere) else None
    metadata = {
        "description": str(row.get("Overview") or "")[:20000],
        "premiere_date": premiere or (f"{year:04}-01-01" if year else None),
        "date_precision": "day" if premiere else "year" if year else None,
        "studios": texts([s.get("Name") for s in studios if isinstance(s, dict)]),
        "countries": texts(row.get("ProductionLocations")),
        "tags": tags,
        "age_rating": str(row.get("OfficialRating") or "")[:20],
        "director": ", ".join(
            str(p.get("Name", "")) for p in people if p.get("Type") == "Director")[:200],
        "writer": ", ".join(
            str(p.get("Name", "")) for p in people if p.get("Type") == "Writer")[:200],
        "people": [
            {"name": str(p.get("Name", ""))[:256], "role": str(p.get("Role", ""))[:256],
             "type": str(p.get("Type", ""))[:50]}
            for p in people
        ],
        "community_rating": row.get("CommunityRating")
        if isinstance(row.get("CommunityRating"), (int, float))
        and not isinstance(row.get("CommunityRating"), bool) else None,
    }
    rating = row["UserData"].get("Rating")
    if isinstance(rating, (int, float)) and not isinstance(rating, bool) and 0 <= rating <= 10:
        metadata["rating_overall"] = rating
    metadata = {k: v for k, v in metadata.items() if v not in (None, "", [])}
    runtime = details["runtime_ticks"]
    result = {
        "external_id": external,
        "title": title.strip()[:500],
        "genres": [g[:128] for g in genres],
        "runtime_minutes": min(100000, runtime // 600_000_000) if runtime else None,
        "played": row["UserData"]["Played"],
        "in_progress": details["position_ticks"] > 0,
        "provider_ids": ids,
        "release_year": year,
        "metadata": metadata,
        "playback": details if kind == "movie" else None,
        "anime": looks_like_anime(tags, genres),
        "images": {"poster": bool(images.get("Primary")),
                   "backdrop": bool(row.get("BackdropImageTags"))},
    }
    return checked_json(result, LABEL)


def normalize_episode(row: Any) -> dict:
    if not isinstance(row, dict) or row.get("Type") != "Episode":
        raise remote_error(LABEL, "an invalid episode page")
    details = playback(row)
    return {
        "external_id": identifier_text(row.get("Id"), LABEL),
        "series_id": identifier_text(row.get("SeriesId"), LABEL),
        "season": optional_int(row.get("ParentIndexNumber"), maximum=10000),
        "number": optional_int(row.get("IndexNumber"), maximum=100000),
        "title": str(row.get("Name") or "")[:500],
        "watched": row["UserData"]["Played"],
        "playback": details,
    }
