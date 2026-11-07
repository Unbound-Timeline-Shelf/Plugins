"""Provider-neutral media-server sync engine for personal account connections.

The Plex and Emby official plugins ship byte-identical copies of this module, because every
package is self-contained; tests/test_media_server_sync.py fails if the copies drift.

A provider module supplies only remote reads (connect, libraries, pages, one item, the watch
link). This module owns the per-user lease, bounded census checkpoints, `media.sync` enrich
writes, conflict review and availability. Every remote failure is reported with a fixed,
sanitized message: no URL, credential, header or remote response text ever reaches a status,
summary, log or exception message.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from sdk.plugin_protocol import GatewayRequestError, request

PAGE_SIZE = 50
EPISODE_PAGE_SIZE = 100  # the host accepts at most 100 episodes per media.sync request
FINALIZE_BATCH = 25
STALE_SECONDS = 6 * 3600
LEASE_SECONDS = 75
MISSING_CENSUSES = 2
MAX_LIBRARIES = 200
MAX_CONFLICTS_SHOWN = 25
MAX_SCAN_RESTARTS = 5
CONTINUE_SECONDS = 60
RATE_LIMIT_RETRY_SECONDS = 300
CATEGORIES = {"auto", "movie", "tv_show", "anime", "ignore"}
ALLOWED_CATEGORIES = {
    "movie": {"auto", "movie", "anime", "ignore"},
    "show": {"auto", "tv_show", "anime", "ignore"},
}
# Which decisions make sense for which host conflict; anything else is informational only.
DECISIONS = {
    "ambiguous_match": {"new", "merge"},
    "incomplete_match": {"new", "merge"},
    "provider_id_mismatch": {"new", "merge"},
    "local_watch_state_changed": {"use_remote"},
    "category_changed": {"keep_category"},
}
ITEM_FIELDS = (
    "external_id", "media_type", "title", "genres", "runtime_minutes", "poster_url",
    "played", "in_progress", "provider_ids", "release_year", "metadata", "playback",
)


class SyncError(ValueError):
    """A public, sanitized failure; ``code`` drives retries and scheduling hints."""

    def __init__(self, message: str, *, code: str = "configuration", retry_after: int = 0):
        super().__init__(message)
        self.code, self.retry_after = code, retry_after


class NotConnected(SyncError):
    def __init__(self, label: str):
        super().__init__(f"Connect your {label} account first.", code="not_connected")


# --- storage ------------------------------------------------------------------------------


def load(key: str, default: Any = None) -> Any:
    raw = request("storage.get", "plugin.storage", {"key": key}).get("value")
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        raise SyncError("Saved plugin state is damaged. Disconnect and connect again.") from None


def store(key: str, value: Any) -> None:
    request("storage.put", "plugin.storage", {"key": key, "value": json.dumps(value)})


def delete(key: str) -> None:
    request("storage.delete", "plugin.storage", {"key": key})


def keys(prefix: str) -> list[str]:
    return sorted(request("storage.keys", "plugin.storage", {"prefix": prefix}).get("keys", []))


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def actor(values: dict) -> str:
    context = values.get("_plugin_context") if isinstance(values, dict) else None
    try:
        return str(UUID(context["user_id"]))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SyncError("An authenticated action context is required.") from None


@contextmanager
def lease(user: str, label: str):
    """Serialize page, Connections and personal-schedule steps for one account."""
    key = "leases/" + user
    original = request("storage.get", "plugin.storage", {"key": key}).get("value")
    busy = SyncError(
        f"Another {label} sync step is running. Wait a minute, then try again.", code="busy"
    )
    if original:
        try:
            expires_at = float(json.loads(original)["expires_at"])
        except (TypeError, ValueError, KeyError):
            expires_at = 0.0  # a damaged lease must not lock the account forever
        if expires_at > time.time():
            raise busy
    value = json.dumps({"id": uuid4().hex, "expires_at": time.time() + LEASE_SECONDS})
    swapped = request(
        "storage.compare_and_swap",
        "plugin.storage",
        {"key": key, "expected": original, "value": value},
    ).get("swapped")
    if not swapped:
        raise busy
    try:
        yield
    finally:
        request(
            "storage.compare_and_swap",
            "plugin.storage",
            {"key": key, "expected": value, "value": None},
        )


# --- remote HTTP --------------------------------------------------------------------------


def server_url(value: Any, label: str) -> str:
    """A plain HTTP(S) base URL; an optional reverse-proxy path is kept, nothing else."""
    if not isinstance(value, str) or not value.strip():
        raise SyncError(f"Enter your {label} server URL.")
    value = value.strip()
    try:
        parts = urlsplit(value)
        _ = parts.port
    except ValueError:
        raise SyncError("The server URL or port is invalid.") from None
    if (
        parts.scheme not in {"https", "http"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or len(value) > 2048
        or any(c.isspace() or ord(c) < 32 or c in '\\"<>' for c in value)
    ):
        raise SyncError("Use an HTTP(S) server URL without credentials, query or fragment.")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def fetch(
    label: str,
    url: str,
    *,
    headers: dict | None = None,
    method: str = "GET",
    body: dict | None = None,
) -> Any:
    """One bounded JSON request through the host; failures never echo the URL or reply."""
    payload: dict[str, Any] = {
        "url": url,
        "headers": {"Accept": "application/json", **(headers or {})},
        "method": method,
    }
    if body is not None:
        payload["body"] = body
    result = request("network.request", "network.outbound", payload)
    status = result.get("status", 0)
    if isinstance(status, int) and 200 <= status < 300:
        return result.get("data")
    if status in {401, 403}:
        raise SyncError(
            f"{label} no longer accepts the saved sign-in. Reconnect to continue; "
            "synced media and progress are kept.",
            code="authentication",
        )
    if result.get("code") == "certificate_untrusted":
        raise SyncError(
            f"The {label} server's certificate is not trusted. Ask your administrator to "
            "trust its certificate authority on the host; there is no verification bypass.",
            code="certificate",
        )
    retry = result.get("retry_after_seconds", 0)
    retry = retry if isinstance(retry, int) and not isinstance(retry, bool) else 0
    if status == 429:
        raise SyncError(
            f"{label} is limiting requests. The sync resumes from its checkpoint later.",
            code="rate_limited",
            retry_after=max(retry, RATE_LIMIT_RETRY_SECONDS),
        )
    if status in {0, 408} or (isinstance(status, int) and status >= 500):
        raise SyncError(
            f"{label} is unavailable. The sync resumes from its checkpoint later.",
            code="transient",
            retry_after=retry,
        )
    raise SyncError(
        f"{label} rejected a request (HTTP {int(status) if isinstance(status, int) else 0}). "
        "Check the server URL and library access.",
        code="configuration",
    )


# --- remote value validation helpers shared by providers ----------------------------------


def remote_error(label: str, what: str) -> SyncError:
    return SyncError(f"{label} returned {what}; this page was not saved.", code="remote_data")


def integer(value: Any, label: str, *, maximum: int = 10**16, default: int | None = None) -> int:
    if value is None and default is not None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise remote_error(label, "an invalid number")
    return value


def optional_int(value: Any, *, minimum: int = 0, maximum: int = 10**16) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        return None
    return value


def percentage(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or not 0 <= value <= 100:
        return None
    return float(value)


def texts(value: Any, *, limit: int = 50, length: int = 256) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v.strip()[:length] for v in value[:limit] if isinstance(v, str) and v.strip()]


def identifier_text(value: Any, label: str) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or any(ord(c) < 32 for c in value):
        raise remote_error(label, "an item without a valid identity")
    return value


ANIME_PATTERN = re.compile(r"\banime\b|\banimation japonaise\b", re.I)


def looks_like_anime(*values: list[str]) -> bool:
    return any(ANIME_PATTERN.search(v) for group in values for v in group)


def checked_json(item: dict, label: str) -> dict:
    """Only finite JSON may reach the host; invalid third-party values fail this page."""
    try:
        json.dumps(item, allow_nan=False)
    except (TypeError, ValueError):
        raise remote_error(label, "malformed metadata") from None
    return item


# --- connection state ---------------------------------------------------------------------


def connection_key(user: str) -> str:
    return "connections/" + user


def secret_key(user: str) -> str:
    return "secrets/users/" + user


def scope_of(conn: dict) -> str:
    return conn["server_id"] + ":" + conn["remote_user_id"]


def scope_hash(conn: dict) -> str:
    return hashlib.sha256(scope_of(conn).encode()).hexdigest()[:32]


def item_key(user: str, conn: dict, external_id: str) -> str:
    return (
        "items/" + user + "/" + scope_hash(conn) + "/"
        + hashlib.sha256(external_id.encode()).hexdigest()
    )


def conflict_key(user: str, conn: dict, external_id: str) -> str:
    return "conflicts/" + user + "/" + item_key(user, conn, external_id).rsplit("/", 2)[-1]


def credential(user: str, conn: dict, label: str) -> str:
    secret = load(secret_key(user), {})
    if (
        not isinstance(secret, dict)
        or secret.get("url") != conn["url"]
        or secret.get("scope") != scope_of(conn)
        or not isinstance(secret.get("token"), str)
    ):
        raise SyncError(
            f"Reconnect your {label} account. Library choices and progress are kept.",
            code="authentication",
        )
    return secret["token"]


def category(conn: dict, library: dict) -> str:
    value = conn.get("mappings", {}).get(library["id"], "auto")
    return value if value in ALLOWED_CATEGORIES[library["kind"]] else "ignore"


def selected_libraries(conn: dict) -> list[dict]:
    return [lib for lib in conn.get("libraries", []) if category(conn, lib) != "ignore"]


def public_status(user: str, provider: Any) -> dict:
    conn = load(connection_key(user))
    connected = bool(conn) and bool(load(secret_key(user)))
    state = load("sync/" + user, {}) if conn else {}
    conflicts = []
    conflict_keys = keys("conflicts/" + user + "/") if conn else []
    for key in conflict_keys[:MAX_CONFLICTS_SHOWN]:
        record = load(key, {})
        conflicts.append(
            {
                "external_id": record.get("external_id"),
                "title": record.get("title"),
                "reason": record.get("reason"),
                "decisions": sorted(DECISIONS.get(record.get("reason"), set())),
                "candidates": record.get("candidates", [])[:20],
                "media_type": record.get("media_type"),
            }
        )
    return {
        "ok": True,
        "connected": connected,
        "display_name": (
            f"{conn['remote_user_name']} · {conn['server_name']}"[:80] if conn else None
        ),
        "provider": provider.LABEL,
        "server_name": conn.get("server_name") if conn else None,
        "server_url": conn.get("url") if conn else None,
        "account_name": conn.get("remote_user_name") if conn else None,
        "libraries": [
            {"id": lib["id"], "name": lib["name"], "kind": lib["kind"],
             "category": category(conn, lib)}
            for lib in (conn or {}).get("libraries", [])
        ],
        "phase": state.get("phase", "idle"),
        "library_index": state.get("library", 0),
        "library_total": len(state.get("libraries", [])),
        "processed": state.get("processed", 0),
        "unnumbered": state.get("unnumbered", 0),
        "unavailable": state.get("unavailable", 0),
        "conflict_total": len(conflict_keys),
        "conflicts": conflicts,
        "warning": state.get("warning"),
        "error": state.get("error"),
        "updated_at": state.get("updated_at"),
        "completed_at": state.get("completed_at"),
    }


# --- actions ------------------------------------------------------------------------------


def guarded(handler):
    """Return expected failures as results; the host discards a raised action's message."""

    def run(values: dict, provider: Any) -> dict:
        try:
            return handler(values, provider)
        except GatewayRequestError:
            return {
                "ok": False,
                "error": "The host denied or could not complete this action. "
                "Check this plugin's permissions, then try again.",
            }
        except SyncError as exc:
            return {"ok": False, "error": str(exc), "code": exc.code}

    run.__name__ = handler.__name__
    return run


@guarded
def status_action(values: dict, provider: Any) -> dict:
    return public_status(actor(values), provider)


@guarded
def connect_action(values: dict, provider: Any) -> dict:
    """Validate the sign-in against the server before anything is saved."""
    user = actor(values)
    with lease(user, provider.LABEL):
        old = load(connection_key(user))
        device = hashlib.sha256(("utp-" + provider.SOURCE + ":" + user).encode()).hexdigest()[:32]
        remote = provider.connect(values, device)
        conn = {
            "url": remote["url"],
            "server_id": remote["server_id"][:200],
            "server_name": str(remote.get("server_name") or provider.LABEL)[:100],
            "remote_user_id": remote["remote_user_id"][:200],
            "remote_user_name": str(remote.get("remote_user_name") or provider.LABEL)[:100],
            "libraries": remote["libraries"][:MAX_LIBRARIES],
        }
        if old and scope_of(old) != scope_of(conn):
            raise SyncError(
                f"This sign-in is for a different {provider.LABEL} server or account. "
                "Disconnect first; media already synced stays in your library."
            )
        known = {lib["id"] for lib in conn["libraries"]}
        conn["mappings"] = {
            k: v for k, v in (old or {}).get("mappings", {}).items() if k in known
        }
        conn["connected_at"] = int(time.time())
        # The credential is bound to this URL and account scope, never sent anywhere else.
        store(
            secret_key(user),
            {"token": remote["token"], "url": conn["url"], "scope": scope_of(conn)},
        )
        store(connection_key(user), conn)
        if not old or old.get("url") != conn["url"]:
            delete("sync/" + user)
        return public_status(user, provider)


@guarded
def save_libraries_action(values: dict, provider: Any) -> dict:
    user = actor(values)
    mappings = values.get("mappings")
    with lease(user, provider.LABEL):
        conn = load(connection_key(user))
        if not conn:
            raise NotConnected(provider.LABEL)
        libraries = {lib["id"]: lib for lib in conn.get("libraries", [])}
        if not isinstance(mappings, dict) or any(
            key not in libraries or value not in ALLOWED_CATEGORIES[libraries[key]["kind"]]
            for key, value in mappings.items()
        ):
            raise SyncError("Choose a supported category for each listed library.")
        conn["mappings"] = {**conn.get("mappings", {}), **mappings}
        store(connection_key(user), conn)
        # The next step starts a fresh census over the new selection; item links are kept.
        delete("sync/" + user)
        return public_status(user, provider)


@guarded
def disconnect_action(values: dict, provider: Any) -> dict:
    user = actor(values)
    if values.get("_plugin_context", {}).get("confirmed") is not True:
        raise SyncError(f"Confirm disconnecting this {provider.LABEL} account.")
    with lease(user, provider.LABEL):
        conn = load(connection_key(user))
        secret = load(secret_key(user), {})
        if conn and isinstance(secret, dict) and secret.get("token"):
            try:
                provider.sign_out(conn, secret["token"])
            except (SyncError, GatewayRequestError):
                pass  # the local credential is removed regardless
        for key in (secret_key(user), connection_key(user), "sync/" + user):
            delete(key)
        for key in keys("conflicts/" + user + "/"):
            delete(key)
        return public_status(user, provider)


@guarded
def resolve_action(values: dict, provider: Any) -> dict:
    """Record one explicit review decision; the next visit to that item applies it."""
    user = actor(values)
    if values.get("_plugin_context", {}).get("confirmed") is not True:
        raise SyncError("Confirm the review decision in the host dialog.")
    with lease(user, provider.LABEL):
        conn = load(connection_key(user))
        if not conn:
            raise NotConnected(provider.LABEL)
        external = values.get("external_id")
        if not isinstance(external, str) or not 1 <= len(external) <= 256:
            raise SyncError("Choose an item that needs review.")
        record = load(conflict_key(user, conn, external))
        state = load(item_key(user, conn, external))
        if not record or not state:
            raise SyncError("This item no longer needs review.")
        decision = values.get("decision")
        if decision not in DECISIONS.get(record.get("reason"), set()):
            raise SyncError("Choose one of the offered review decisions.")
        state["decision"] = decision
        if decision == "merge":
            target = values.get("target_id")
            if target not in {c.get("id") for c in record.get("candidates", [])}:
                raise SyncError("Choose one of the listed library items.")
            state["target_id"] = target
        if decision == "keep_category":
            kept = record.get("media_type")
            if kept not in {"movie", "tv_show", "anime"}:
                raise SyncError("This review has no retained category.")
            state["category_override"] = kept
            state["item"]["media_type"] = kept
        store(item_key(user, conn, external), state)
        delete(conflict_key(user, conn, external))
        return public_status(user, provider)


def sync_action(values: dict, provider: Any) -> dict:
    """One bounded checkpoint for the page, Connections → Sync now or a personal schedule.

    Failures return a public summary plus the host's optional scheduling hints:
    ``retry_after_seconds`` when the server is rate limiting or another step holds the lease,
    ``disable_schedule`` when the account is disconnected or the sign-in is rejected."""
    label = provider.LABEL
    try:
        user = actor(values)
        with lease(user, label):
            result = _step(user, provider)
        completed = result["phase"] == "done"
        summary = (
            f"{label} sync complete: {result['processed']} items checked, "
            f"{result['conflict_total']} need review."
            if completed
            else f"{label} sync saved its checkpoint. The next step resumes automatically."
        )
        return {
            **result,
            "completed": completed,
            "summary": summary,
            **({} if completed else {"continue_after_seconds": CONTINUE_SECONDS}),
        }
    except GatewayRequestError:
        message = (
            "The host denied or could not complete this action. Check this plugin's "
            "permissions, then try again."
        )
        return {"ok": False, "error": message, "completed": False, "summary": message}
    except SyncError as exc:
        hints: dict[str, Any] = {}
        if exc.code in {"rate_limited", "busy"}:
            hints["retry_after_seconds"] = max(exc.retry_after, CONTINUE_SECONDS)
        elif exc.code in {"not_connected", "authentication"}:
            hints["disable_schedule"] = True
        elif exc.code == "library_changed":
            hints["continue_after_seconds"] = CONTINUE_SECONDS
        message = str(exc)
        return {"ok": False, "error": message, "code": exc.code, "completed": False,
                "summary": message, **hints}


# --- the census -----------------------------------------------------------------------------


def _step(user: str, provider: Any) -> dict:
    label = provider.LABEL
    conn = load(connection_key(user))
    if not conn:
        raise NotConnected(label)
    token = credential(user, conn, label)
    libraries = selected_libraries(conn)
    if not libraries:
        raise SyncError(f"Choose at least one {label} library to sync.")
    selection = [[lib["id"], lib["kind"], category(conn, lib)] for lib in libraries]
    cursor = load("sync/" + user, {})
    now = int(time.time())
    if (
        not cursor
        or cursor.get("phase") in {None, "idle", "done"}
        or cursor.get("scope") != scope_of(conn)
        or cursor.get("libraries") != selection
        or now - cursor.get("updated_at", 0) > STALE_SECONDS
    ):
        cursor = {
            "generation": uuid4().hex,
            "scope": scope_of(conn),
            "libraries": selection,
            "phase": "roots",
            "library": 0,
            "offset": 0,
            "total": None,
            "processed": 0,
            "unnumbered": 0,
            "unavailable": 0,
            "restarts": cursor.get("restarts", 0) if cursor.get("phase") == "restart" else 0,
            "started_at": now,
            "completed_at": cursor.get("completed_at"),
        }
    try:
        phase = cursor["phase"]
        if phase == "roots":
            _roots(user, conn, token, cursor, provider)
        elif phase == "episodes":
            _episodes(user, conn, token, cursor, provider)
        elif phase == "finalize":
            _finalize(user, conn, cursor, provider)
    except SyncError as exc:
        if exc.code == "library_changed":
            restarts = cursor.get("restarts", 0) + 1
            if restarts > MAX_SCAN_RESTARTS:
                exc = SyncError(
                    f"The {label} library kept changing during the scan. Try again later.",
                    code="transient",
                )
                store("sync/" + user, {**cursor, "phase": "idle", "error": str(exc),
                                       "updated_at": now, "restarts": 0})
            else:
                # Saved offsets describe a library that no longer exists: begin a new census.
                store("sync/" + user, {"phase": "restart", "restarts": restarts,
                                       "updated_at": now, "error": None,
                                       "completed_at": cursor.get("completed_at")})
        else:
            cursor.update(error=str(exc), updated_at=now)
            store("sync/" + user, cursor)
        raise exc from None
    cursor.update(updated_at=now, error=None)
    if cursor["phase"] == "done":
        cursor.update(completed_at=now, restarts=0)
    store("sync/" + user, cursor)
    return public_status(user, provider)


def _library(cursor: dict) -> dict:
    lib_id, kind, chosen = cursor["libraries"][cursor["library"]]
    return {"id": lib_id, "kind": kind, "category": chosen}


def _check_page(label: str, rows: Any, total: Any, cursor: dict, limit: int) -> tuple[list, int]:
    if not isinstance(rows, list):
        raise remote_error(label, "an invalid library page")
    total = integer(total, label, maximum=10**7)
    if (
        len(rows) > limit
        or (not rows and cursor["offset"] < total)
        or cursor["offset"] + len(rows) > total
        or cursor.get("total") not in {None, total}
    ):
        raise SyncError(
            f"The {label} library changed during the scan; it restarts.", code="library_changed"
        )
    cursor["total"] = total
    return rows, total


def _media_type(item: dict, library: dict) -> str:
    chosen = library["category"]
    if chosen != "auto":
        return chosen
    if item.get("anime"):
        return "anime"
    return "movie" if library["kind"] == "movie" else "tv_show"


def _stage(
    user: str, conn: dict, item: dict, library: dict, cursor: dict, provider: Any
) -> dict:
    """Record the item as present in this census and return its saved state."""
    key = item_key(user, conn, item["external_id"])
    state = load(key, {})
    media_type = state.get("category_override") or _media_type(item, library)
    ids = dict(item.get("provider_ids", {}))
    if media_type == "anime" and ids.get("tmdb"):
        # TMDB films and series share numbers but not namespaces.
        ids["tmdb.movie" if library["kind"] == "movie" else "tmdb.tv"] = ids.pop("tmdb")
    staged = {k: item[k] for k in ITEM_FIELDS if item.get(k) is not None}
    staged.update(media_type=media_type, provider_ids=ids)
    pictures = provider.artwork(conn, item)
    if pictures.get("poster_url"):
        staged["poster_url"] = pictures["poster_url"]
    if pictures.get("backdrop_url"):
        staged["metadata"] = {**staged.get("metadata", {}), "backdrop_url": pictures["backdrop_url"]}
    if media_type == "anime" and library["kind"] == "movie":
        staged["metadata"] = {**staged.get("metadata", {}), "format": "Movie"}
    state.update(
        item=staged,
        kind=library["kind"],
        library=library["id"],
        generation=cursor["generation"],
        available=True,
        missing=0,
    )
    store(key, state)
    return state


def _apply(
    user: str,
    conn: dict,
    state: dict,
    provider: Any,
    *,
    episodes: list | None = None,
    progress: dict | None = None,
    complete: bool = False,
    availability_only: bool = False,
) -> bool:
    item = state["item"]
    payload = {
        **item,
        "source": provider.SOURCE,
        "source_scope": scope_of(conn),
        "sync_mode": "enrich",
        "auto_merge": state.get("decision") != "new",
        "merge_title_year": True,
        "available": state.get("available", True),
        **provider.watch_fields(conn, item["external_id"]),
    }
    if availability_only:
        payload["availability_only"] = True
    else:
        payload.update(
            episodes=episodes or [],
            episode_progress=progress or {},
            inventory_complete=complete,
        )
        if state.get("target_id"):
            payload["target_id"] = state["target_id"]
        if state.get("decision") == "use_remote":
            payload["force_watch"] = True
    result = request("media.sync", "media.write", payload)
    key = item_key(user, conn, item["external_id"])
    if result.get("conflict"):
        if availability_only:
            return False
        state["conflict"] = result["conflict"]
        store(key, state)
        store(
            conflict_key(user, conn, item["external_id"]),
            {
                "external_id": item["external_id"],
                "title": item["title"],
                "reason": result["conflict"],
                "candidates": [
                    {"id": str(c.get("id")), "title": str(c.get("title", ""))[:200]}
                    for c in result.get("candidates", [])[:20]
                    if isinstance(c, dict)
                ],
                "media_type": result.get("media_type"),
            },
        )
        return False
    host_id = result.get("id")
    if not isinstance(host_id, str):
        raise SyncError("The host did not confirm this item. The sync resumes later.",
                        code="transient")
    had_review = bool(state.get("conflict") or state.get("decision"))
    state.update(host_id=host_id, conflict=None)
    # Review decisions are one-shot: once the link exists the host resolves it by itself.
    for one_shot in ("decision", "target_id"):
        state.pop(one_shot, None)
    store(key, state)
    if had_review:
        delete(conflict_key(user, conn, item["external_id"]))
    return True


def _film_episode(item: dict) -> list:
    """An anime film is tracked as a one-episode anime, as the Jellyfin plugin does."""
    return [{
        "external_id": "film:" + item["external_id"],
        "season": 1,
        "number": 1,
        "title": item["title"][:500],
        "watched": bool(item.get("played")),
    }]


def _roots(user: str, conn: dict, token: str, cursor: dict, provider: Any) -> None:
    library = _library(cursor)
    rows, total = provider.roots(conn, token, library, cursor["offset"], PAGE_SIZE)
    rows, total = _check_page(provider.LABEL, rows, total, cursor, PAGE_SIZE)
    # Validate the whole page before any write, so a bad row cannot half-apply a page.
    items = [provider.normalize(row, library["kind"]) for row in rows]
    for item in items:
        # An item under review is offered again: the host answers with the same conflict
        # and changes nothing until the user decides, and a conflict that went away clears.
        state = _stage(user, conn, item, library, cursor, provider)
        movie = library["kind"] == "movie"
        anime_film = movie and state["item"]["media_type"] == "anime"
        _apply(user, conn, state, provider,
               episodes=_film_episode(state["item"]) if anime_film else None,
               complete=movie)
        cursor["processed"] += 1
    cursor["offset"] += len(rows)
    if cursor["offset"] >= total:
        if library["kind"] == "show":
            cursor.update(phase="episodes", offset=0, total=None)
        else:
            _next_library(cursor)


def _next_library(cursor: dict) -> None:
    cursor["library"] += 1
    cursor.update(offset=0, total=None)
    cursor["phase"] = "roots" if cursor["library"] < len(cursor["libraries"]) else "finalize"


def _episodes(user: str, conn: dict, token: str, cursor: dict, provider: Any) -> None:
    library = _library(cursor)
    rows, total = provider.episodes(conn, token, library, cursor["offset"], EPISODE_PAGE_SIZE)
    rows, total = _check_page(provider.LABEL, rows, total, cursor, EPISODE_PAGE_SIZE)
    parsed = [provider.normalize_episode(row) for row in rows]
    groups: dict[str, list] = {}
    for episode in parsed:
        groups.setdefault(episode["series_id"], []).append(episode)
    for series_id, group in groups.items():
        key = item_key(user, conn, series_id)
        state = load(key, {})
        if state.get("generation") != cursor["generation"]:
            # A series can be missing from the root listing while its episodes are visible;
            # read just that parent through the same account.
            parent = provider.normalize(provider.item(conn, token, series_id), "show")
            if parent["external_id"] != series_id:
                raise remote_error(provider.LABEL, "a different series than requested")
            state = _stage(user, conn, parent, library, cursor, provider)
        numbered, progress = [], {}
        for episode in group:
            progress[episode["external_id"]] = episode["playback"]
            if episode["season"] is None or not episode["number"]:
                # Never invent numbers; the series is simply not finalized this census.
                state["unnumbered_generation"] = cursor["generation"]
                cursor["unnumbered"] += 1
                continue
            numbered.append({
                "external_id": episode["external_id"],
                "season": episode["season"],
                "number": episode["number"],
                "title": episode["title"],
                "watched": episode["watched"],
            })
        store(key, state)
        _apply(user, conn, state, provider, episodes=numbered, progress=progress)
        cursor["processed"] += len(group)
    cursor["offset"] += len(rows)
    if cursor["offset"] >= total:
        _next_library(cursor)


def _finalize(user: str, conn: dict, cursor: dict, provider: Any) -> None:
    """Finalize present series, and retire items absent from two complete censuses."""
    prefix = "items/" + user + "/" + scope_hash(conn) + "/"
    candidates = keys(prefix)
    selected = {lib_id for lib_id, _, _ in cursor["libraries"]}
    batch = candidates[cursor["offset"]: cursor["offset"] + FINALIZE_BATCH]
    for key in batch:
        state = load(key, {})
        if not state.get("item") or state.get("library") not in selected:
            continue
        if state.get("generation") == cursor["generation"]:
            if state.get("kind") == "show" and state.get(
                "unnumbered_generation"
            ) != cursor["generation"]:
                _apply(user, conn, state, provider, complete=True)
            continue
        if state.get("missing_generation") != cursor["generation"]:
            state["missing"] = state.get("missing", 0) + 1
            state["missing_generation"] = cursor["generation"]
        if state["missing"] >= MISSING_CENSUSES and state.get("available", True):
            state["available"] = False
            store(key, state)
            if state.get("host_id"):
                _apply(user, conn, state, provider, availability_only=True)
            cursor["unavailable"] += 1
        else:
            store(key, state)
    cursor["offset"] += len(batch)
    if cursor["offset"] >= len(candidates):
        cursor.update(phase="done", offset=0, total=None)
