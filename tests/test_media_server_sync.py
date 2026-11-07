"""Official Plex and Emby media sync: fixture-based provider replies through a fake host.

Each test drives the real plugin handlers. The fake gateway enforces the parts of the host
contract the plugins rely on (storage compare-and-swap, the outbound header allowlist, the
strict `media.sync` enrich field set and episode bound) and replays Plex- and Emby-shaped
JSON. No real server, token or network is used.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from sdk.plugin_protocol import GatewayRequestError

ROOT = Path(__file__).parents[1]
PLEX_DIR = ROOT / "official/plex-media-sync"
EMBY_DIR = ROOT / "official/emby-media-sync"
USER, OTHER = str(uuid4()), str(uuid4())
PLEX_TOKEN = "plexSECRETtoken-123"
EMBY_PASSWORD = "emby-PASSWORD-xyz"
EMBY_TOKEN = "embySESSIONtoken0123456789"
SECRETS = (PLEX_TOKEN, EMBY_PASSWORD, EMBY_TOKEN)
# Header names host outbound.py accepts; X-Plex-Token is deliberately absent there.
HEADER_ALLOWLIST = {
    "accept", "accept-language", "authorization", "x-emby-token", "x-auth-token", "client-id",
    "content-type", "user-agent", "referer", "origin", "cookie",
}
# MediaSyncInput + EnrichmentInput fields (host src/backend/src/plugin_api/media_*.py);
# the host model forbids anything else.
ENRICH_FIELDS = {
    "source", "source_scope", "external_id", "media_type", "title", "genres",
    "runtime_minutes", "poster_url", "played", "in_progress", "episodes",
    "expected_revision", "inventory_complete", "sync_mode", "auto_merge", "merge_title_year",
    "release_year", "provider_ids", "target_id", "force_watch", "available",
    "availability_only", "metadata", "playback", "episode_progress", "history", "watch_url",
    "watch_label",
}
PLAYBACK_FIELDS = {"position_ticks", "runtime_ticks", "percentage", "play_count",
                   "last_played_at"}


def ctx(user=USER, confirmed=True, **values):
    return {"_plugin_context": {"user_id": user, "confirmed": confirmed}, **values}


# --- fake media servers -------------------------------------------------------------------


class FakePlex:
    base = "https://plex.example.test:32400"

    def __init__(self):
        self.sections = [
            {"key": "1", "title": "Films", "type": "movie"},
            {"key": "2", "title": "Series", "type": "show"},
            {"key": "3", "title": "Music", "type": "artist"},
        ]
        self.movies = [self.movie(i) for i in range(3)]
        self.shows = [{
            "ratingKey": "500", "type": "show", "title": "Fixture Show", "year": 2020,
            "leafCount": 3, "viewedLeafCount": 1, "Guid": [{"id": "tvdb://777"}],
            "Genre": [{"tag": "Drama"}],
        }]
        self.episodes = [
            self.episode("501", 1, 1, views=1),
            self.episode("502", 1, 2, offset=60000),
            self.episode("503", 1, 3),
        ]
        self.account = {"uuid": "acct-uuid-1", "username": "fixture-viewer"}
        self.fail: dict[str, dict] = {}

    @staticmethod
    def movie(i, **extra):
        return {
            "ratingKey": str(100 + i), "type": "movie", "title": f"Fixture Film {i}",
            "year": 2001 + i, "duration": 6_000_000, "viewCount": 1 if i == 0 else 0,
            "viewOffset": 1_200_000 if i == 1 else 0, "lastViewedAt": 1_700_000_000,
            "Guid": [{"id": f"imdb://tt00000{i}"}, {"id": f"tmdb://{900 + i}"},
                     {"id": "plex://movie/abc"}],
            "Genre": [{"tag": "Drama"}], "summary": "A fixture.",
            "originallyAvailableAt": f"{2001 + i}-05-04", "thumb": "/library/metadata/x/thumb",
            **extra,
        }

    @staticmethod
    def episode(key, season, number, views=0, offset=0):
        return {
            "ratingKey": key, "type": "episode", "grandparentRatingKey": "500",
            "parentIndex": season, "index": number, "title": f"Episode {number}",
            "viewCount": views, "viewOffset": offset, "duration": 1_500_000,
        }

    def __call__(self, payload):
        url = urlsplit(payload["url"])
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path in self.fail:
            return self.fail[url.path]
        if url.netloc == "plex.tv":
            assert url.path == "/api/v2/user"
            assert query.get("X-Plex-Client-Identifier")
            if query.get("X-Plex-Token") != PLEX_TOKEN:
                return {"status": 401, "error": "rejected"}
            return {"status": 200, "data": dict(self.account)}
        assert f"{url.scheme}://{url.netloc}" == self.base
        if url.path == "/identity":
            assert "X-Plex-Token" not in query
            return {"status": 200, "data": {"MediaContainer": {"machineIdentifier": "machine-1"}}}
        if query.get("X-Plex-Token") != PLEX_TOKEN:
            return {"status": 401, "error": "rejected"}
        if url.path == "/":
            return {"status": 200, "data": {"MediaContainer": {"friendlyName": "Den Server"}}}
        if url.path == "/library/sections":
            return {"status": 200, "data": {"MediaContainer": {"Directory": self.sections}}}
        match = re.fullmatch(r"/library/sections/(\w+)/all", url.path)
        if match:
            rows = {"1": self.movies, "4": self.episodes, "2": self.shows}[query["type"]]
            if query["type"] == "1" and match.group(1) != "1":
                rows = []
            start = int(query["X-Plex-Container-Start"])
            size = int(query["X-Plex-Container-Size"])
            page = rows[start:start + size]
            return {"status": 200, "data": {"MediaContainer": {
                "size": len(page), "totalSize": len(rows), "offset": start, "Metadata": page}}}
        match = re.fullmatch(r"/library/metadata/(\w+)", url.path)
        if match:
            found = [r for r in self.shows + self.movies if r["ratingKey"] == match.group(1)]
            return {"status": 200, "data": {"MediaContainer": {"Metadata": found}}}
        raise AssertionError("unexpected Plex request " + url.path)


class FakeEmby:
    base = "https://emby.example.test/emby"
    user_id = "u1"

    def __init__(self):
        self.movies = [self.movie(i) for i in range(2)]
        self.series = [{
            "Id": "s1", "Type": "Series", "Name": "Fixture Series", "ProductionYear": 2019,
            "ProviderIds": {"Tvdb": "555", "Tmdb": 66}, "Genres": ["Anime"],
            "UserData": {"Played": False, "PlaybackPositionTicks": 0, "PlayCount": 0},
            "ImageTags": {"Primary": "tag"},
        }]
        self.episodes = [
            self.episode("e1", 1, 1, played=True),
            self.episode("e2", 1, None),  # unnumbered: never given invented numbers
        ]
        self.logouts = 0
        self.fail: dict[str, dict] = {}

    @staticmethod
    def movie(i):
        return {
            "Id": f"m{i}", "Type": "Movie", "Name": f"Emby Film {i}", "ProductionYear": 1999,
            "RunTimeTicks": 72_000_000_000, "ProviderIds": {"Imdb": f"tt11{i}"},
            "PremiereDate": "1999-03-31T00:00:00.0000000Z",
            "UserData": {"Played": i == 0, "PlaybackPositionTicks": 0 if i == 0 else 600_000_000,
                         "PlayCount": 2 if i == 0 else 0,
                         "LastPlayedDate": "2024-01-02T03:04:05.1234567Z"},
            "ImageTags": {"Primary": "p"}, "BackdropImageTags": ["b"],
            "People": [{"Name": "Dir", "Type": "Director"}],
        }

    @staticmethod
    def episode(key, season, number, played=False):
        return {
            "Id": key, "Type": "Episode", "SeriesId": "s1", "ParentIndexNumber": season,
            "IndexNumber": number, "Name": key, "RunTimeTicks": 14_000_000_000,
            "UserData": {"Played": played, "PlaybackPositionTicks": 0, "PlayCount": int(played)},
        }

    def __call__(self, payload):
        url = urlsplit(payload["url"])
        assert url.geturl().startswith(self.base)
        path = url.path[len("/emby"):]
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        assert "token" not in url.query.lower()
        if path in self.fail:
            return self.fail[path]
        if path == "/System/Info/Public":
            return {"status": 200, "data": {"Id": "server1", "ServerName": "Attic"}}
        if path == "/Users/AuthenticateByName":
            assert payload["method"] == "POST"
            assert payload["headers"]["Authorization"].startswith('Emby Client="Unnamed Tracking"')
            if payload["body"] != {"Username": "viewer", "Pw": EMBY_PASSWORD}:
                return {"status": 401, "error": "rejected"}
            return {"status": 200, "data": {"User": {"Id": self.user_id, "Name": "viewer"},
                                            "AccessToken": EMBY_TOKEN, "ServerId": "server1"}}
        if payload["headers"].get("X-Emby-Token") != EMBY_TOKEN:
            return {"status": 401, "error": "rejected"}
        if path == "/Sessions/Logout":
            self.logouts += 1
            return {"status": 204, "data": {}}
        if path == f"/Users/{self.user_id}/Views":
            return {"status": 200, "data": {"Items": [
                {"Id": "lib-m", "Name": "Movies", "CollectionType": "movies"},
                {"Id": "lib-t", "Name": "Shows", "CollectionType": "tvshows"},
                {"Id": "lib-x", "Name": "Music", "CollectionType": "music"},
            ]}}
        if path == f"/Users/{self.user_id}/Items":
            rows = {"Movie": self.movies, "Series": self.series,
                    "Episode": self.episodes}[query["IncludeItemTypes"]]
            if query["ParentId"] == "lib-m" and query["IncludeItemTypes"] != "Movie":
                rows = []
            start, limit = int(query["StartIndex"]), int(query["Limit"])
            return {"status": 200, "data": {"Items": rows[start:start + limit],
                                            "TotalRecordCount": len(rows)}}
        match = re.fullmatch(rf"/Users/{self.user_id}/Items/(\w+)", path)
        if match:
            return {"status": 200, "data": next(r for r in self.series if r["Id"] == match.group(1))}
        raise AssertionError("unexpected Emby request " + path)


# --- fake host --------------------------------------------------------------------------------


class Host:
    def __init__(self, server):
        self.server = server
        self.storage: dict[str, str] = {}
        self.syncs: list[dict] = []
        self.network: list[dict] = []
        self.conflicts: dict[str, dict] = {}
        self.denied: set[str] = set()

    def __call__(self, method, capability, payload):
        if capability in self.denied:
            raise GatewayRequestError("SECRET host diagnostics " + PLEX_TOKEN, {"code": "denied"})
        key = payload.get("key")
        if method == "storage.get":
            return {"value": self.storage.get(key)}
        if method == "storage.put":
            assert isinstance(payload["value"], str)
            self.storage[key] = payload["value"]
            return {}
        if method == "storage.delete":
            self.storage.pop(key, None)
            return {}
        if method == "storage.keys":
            return {"keys": [k for k in self.storage if k.startswith(payload["prefix"])]}
        if method == "storage.compare_and_swap":
            if self.storage.get(key) != payload["expected"]:
                return {"swapped": False}
            if payload["value"] is None:
                self.storage.pop(key, None)
            else:
                self.storage[key] = payload["value"]
            return {"swapped": True}
        if method == "network.request":
            assert capability == "network.outbound"
            assert {h.lower() for h in payload.get("headers", {})} <= HEADER_ALLOWLIST
            assert payload.get("method", "GET") in {"GET", "POST"}
            self.network.append(payload)
            return self.server(payload)
        if method == "media.sync":
            assert capability == "media.write"
            self.check_enrich(payload)
            self.syncs.append(payload)
            conflict = self.conflicts.get(payload["external_id"])
            if conflict and not (
                payload.get("target_id") or payload.get("force_watch")
                or payload.get("auto_merge") is False
                or payload.get("availability_only")
            ):
                return dict(conflict)
            return {"id": str(uuid5(NAMESPACE_URL, payload["source_scope"]
                                    + payload["external_id"])), "revision": "0" * 64}
        raise AssertionError("unexpected gateway call " + method)

    @staticmethod
    def check_enrich(payload):
        assert set(payload) <= ENRICH_FIELDS, set(payload) - ENRICH_FIELDS
        assert payload["sync_mode"] == "enrich"
        assert payload["media_type"] in {"movie", "tv_show", "anime"}
        assert re.fullmatch(r"[a-z0-9._-]+", payload["source"])
        assert len(payload.get("episodes", [])) <= 100
        assert len(payload.get("episode_progress", {})) <= 100
        assert len(payload.get("metadata", {})) <= 32
        assert len(json.dumps(payload.get("metadata", {})).encode()) <= 64 * 1024
        for episode in payload.get("episodes", []):
            assert set(episode) <= {"external_id", "season", "number", "title", "watched",
                                    "removed"}
            assert isinstance(episode["season"], int) and episode["number"] >= 1
        for progress in [payload.get("playback"), *payload.get("episode_progress", {}).values()]:
            if progress is not None:
                assert set(progress) <= PLAYBACK_FIELDS
                assert isinstance(progress["position_ticks"], int)
        if payload.get("runtime_minutes") is not None:
            assert isinstance(payload["runtime_minutes"], int)
        url = urlsplit(payload["watch_url"])
        assert url.scheme in {"http", "https"} and not url.username and not url.password
        assert len(payload["watch_label"]) <= 80
        json.dumps(payload, allow_nan=False)

    def stored(self, key):
        value = self.storage.get(key)
        return json.loads(value) if value is not None else None


def load_plugin(monkeypatch, directory, provider):
    monkeypatch.syspath_prepend(str(directory))
    modules = {}
    for name in ("engine", provider, "plugin"):
        spec = importlib.util.spec_from_file_location(name, directory / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules[name] = module
    return modules


def install(monkeypatch, modules, host):
    for module in modules.values():
        if hasattr(module, "request"):
            monkeypatch.setattr(module, "request", host)


@pytest.fixture
def plex(monkeypatch):
    modules = load_plugin(monkeypatch, PLEX_DIR, "plex")
    host = Host(FakePlex())
    install(monkeypatch, modules, host)
    return modules["plugin"], host


@pytest.fixture
def emby(monkeypatch):
    modules = load_plugin(monkeypatch, EMBY_DIR, "emby")
    host = Host(FakeEmby())
    install(monkeypatch, modules, host)
    return modules["plugin"], host


def connect_plex(plugin):
    return plugin.connect(ctx(server_url=FakePlex.base + "/", token=PLEX_TOKEN))


def connect_emby(plugin):
    return plugin.connect(ctx(server_url=FakeEmby.base, username="viewer",
                              password=EMBY_PASSWORD))


def run_to_completion(plugin, limit=50):
    results = []
    for _ in range(limit):
        result = plugin.sync(ctx())
        results.append(result)
        assert result.get("ok") is not False, result
        if result["completed"]:
            return results
        assert result["continue_after_seconds"] == 60
    raise AssertionError("sync did not complete")


def assert_no_secrets(*values):
    text = json.dumps(values, default=str)
    for secret in SECRETS:
        assert secret not in text


def non_secret_storage(host):
    return {k: v for k, v in host.storage.items() if not k.startswith("secrets/")}


# --- packaging and shared-source contracts ----------------------------------------------------


def test_shared_engine_and_page_script_are_identical_copies():
    for name in ("engine.py", "frontend/app.js", "frontend/style.css"):
        assert (PLEX_DIR / name).read_bytes() == (EMBY_DIR / name).read_bytes(), name


@pytest.mark.parametrize("directory", [PLEX_DIR, EMBY_DIR])
def test_manifest_declares_only_what_the_source_uses(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    ui = json.loads((directory / "ui.json").read_text(encoding="utf-8"))
    declared = {c["name"] for c in manifest["capabilities"]}
    assert declared == {p["capability"]["name"] for p in manifest["permissions"]}
    assert all(p["rationale"].strip() for p in manifest["permissions"])
    source = "\n".join(p.read_text(encoding="utf-8") for p in directory.glob("*.py"))
    used = set(re.findall(r'request\(\s*"[a-z_.]+",\s*"([a-z_.]+)"', source))
    used |= {a["capability"]["name"] for a in ui["actions"]}
    # The connection row and the personal schedule need their own grants.
    assert used | {"frontend.connections", "tasks.background"} == declared
    assert manifest["api_contract_version"] == ui["api_contract_version"] == "1.1.20"
    (task,) = manifest["scheduled_tasks"]
    assert task["scope"] == "user" and task["action_id"] == "sync"
    (connection,) = ui["connections"]
    assert connection["sync_action_id"] == "sync" and connection["status_action_id"] == "status"
    assert "from src" not in source and "import src" not in source
    catalogue = json.loads((ROOT / "catalogue.json").read_text(encoding="utf-8"))
    assert manifest["plugin_id"] in catalogue["unreleased_plugins"]


# --- connect ----------------------------------------------------------------------------------


def test_plex_connect_identifies_account_and_binds_the_token(plex):
    plugin, host = plex
    result = connect_plex(plugin)
    assert result["connected"] is True
    assert result["display_name"] == "fixture-viewer · Den Server"
    assert [lib["name"] for lib in result["libraries"]] == ["Films", "Series"]  # no music
    secret = host.stored("secrets/users/" + USER)
    assert secret == {"token": PLEX_TOKEN, "url": FakePlex.base,
                      "scope": "machine-1:acct-uuid-1"}
    # The token goes only to the configured server and plex.tv, as Plex's query parameter.
    for call in host.network:
        assert not any(h.lower() == "x-plex-token" for h in call["headers"])
        assert urlsplit(call["url"]).netloc in {"plex.example.test:32400", "plex.tv"}
    assert_no_secrets(result, non_secret_storage(host))
    assert plugin.status(ctx())["connected"] is True
    assert plugin.status(ctx(OTHER))["connected"] is False


def test_plex_rejected_token_and_invalid_input_never_echo_the_secret(plex):
    plugin, host = plex
    bad = plugin.connect(ctx(server_url=FakePlex.base, token="wrongTOKEN123"))
    assert bad["ok"] is False and bad["code"] == "authentication"
    assert "wrongTOKEN123" not in json.dumps(bad)
    assert plugin.connect(ctx(server_url="ftp://x", token=PLEX_TOKEN))["ok"] is False
    assert plugin.connect(ctx(server_url="https://u:p@x", token=PLEX_TOKEN))["ok"] is False
    assert plugin.connect(ctx(server_url=FakePlex.base, token="no spaces!"))["ok"] is False
    assert "secrets/users/" + USER not in host.storage


def test_emby_connect_uses_a_user_session_and_never_stores_the_password(emby):
    plugin, host = emby
    result = connect_emby(plugin)
    assert result["connected"] is True and result["display_name"] == "viewer · Attic"
    assert [lib["kind"] for lib in result["libraries"]] == ["movie", "show"]
    assert host.stored("secrets/users/" + USER)["token"] == EMBY_TOKEN
    assert EMBY_PASSWORD not in json.dumps(host.storage)
    assert all(EMBY_TOKEN not in call["url"] for call in host.network)
    assert_no_secrets(result, non_secret_storage(host))
    wrong = plugin.connect(ctx(server_url=FakeEmby.base, username="viewer", password="nope"))
    assert wrong["ok"] is False and "username and password" in wrong["error"]


def test_a_second_account_is_refused_until_disconnect(plex):
    plugin, host = plex
    connect_plex(plugin)
    host.server.account = {"uuid": "someone-else", "username": "other"}
    refused = connect_plex(plugin)
    assert refused["ok"] is False and "Disconnect first" in refused["error"]
    assert host.stored("secrets/users/" + USER)["scope"] == "machine-1:acct-uuid-1"
    # Reconnecting the same account (for example a replaced token) is allowed.
    host.server.account = {"uuid": "acct-uuid-1", "username": "fixture-viewer"}
    assert connect_plex(plugin)["connected"] is True


# --- sync ---------------------------------------------------------------------------------------


def test_plex_full_census_writes_watch_state_episodes_and_watch_links(plex):
    plugin, host = plex
    connect_plex(plugin)
    results = run_to_completion(plugin)
    final = results[-1]
    assert final["phase"] == "done" and final["summary"].startswith("Plex sync complete")
    movies = {s["external_id"]: s for s in host.syncs if s["media_type"] == "movie"}
    assert set(movies) == {"100", "101", "102"}
    watched, partial = movies["100"], movies["101"]
    assert watched["played"] is True and watched["inventory_complete"] is True
    assert watched["provider_ids"] == {"imdb": "tt000000", "tmdb": "900"}
    assert watched["playback"]["play_count"] == 1
    assert partial["in_progress"] is True
    assert partial["playback"]["position_ticks"] == 1_200_000 * 10_000
    assert partial["playback"]["percentage"] == pytest.approx(20.0)
    assert "poster_url" not in partial  # Plex artwork needs a token
    assert watched["source"] == "plex" and watched["source_scope"] == "machine-1:acct-uuid-1"
    assert watched["watch_url"] == (
        FakePlex.base + "/web/index.html#!/server/machine-1/details?key=%2Flibrary%2Fmetadata%2F100"
    )
    assert watched["watch_label"] == "Plex · Den Server"
    show = [s for s in host.syncs if s["external_id"] == "500"]
    episodes = [e for s in show for e in s["episodes"]]
    assert [(e["season"], e["number"], e["watched"]) for e in episodes] == [
        (1, 1, True), (1, 2, False), (1, 3, False)]
    progress = {k: v for s in show for k, v in s["episode_progress"].items()}
    assert progress["502"]["position_ticks"] == 60000 * 10_000
    assert show[-1]["inventory_complete"] is True  # finalized only after all episodes
    assert all(not s["inventory_complete"] for s in show[:-1])
    assert_no_secrets(results, host.syncs, non_secret_storage(host))


def test_emby_full_census_with_anime_artwork_and_unnumbered_episode(emby):
    plugin, host = emby
    connect_emby(plugin)
    final = run_to_completion(plugin)[-1]
    assert final["unnumbered"] == 1
    film = next(s for s in host.syncs if s["external_id"] == "m0")
    assert film["played"] is True and film["playback"]["play_count"] == 2
    assert film["playback"]["last_played_at"] == 1704164645
    assert film["poster_url"] == FakeEmby.base + "/Items/m0/Images/Primary"
    assert film["metadata"]["backdrop_url"] == FakeEmby.base + "/Items/m0/Images/Backdrop/0"
    assert film["metadata"]["premiere_date"] == "1999-03-31"
    assert film["watch_url"] == FakeEmby.base + "/web/index.html#!/item?id=m0&serverId=server1"
    assert film["watch_label"] == "Emby · Attic"
    series = [s for s in host.syncs if s["external_id"] == "s1"]
    assert series[0]["media_type"] == "anime"  # detected from genres
    assert series[0]["provider_ids"] == {"tvdb": "555", "tmdb.tv": "66"}
    assert [e["external_id"] for s in series for e in s["episodes"]] == ["e1"]
    assert "e2" in {k for s in series for k in s["episode_progress"]}
    # A series with an unnumbered episode is never finalized as complete.
    assert not any(s["inventory_complete"] for s in series)
    assert_no_secrets(host.syncs, non_secret_storage(host))


def test_pages_are_bounded_and_resume_after_a_transient_failure(plex):
    plugin, host = plex
    host.server.movies = [FakePlex.movie(i) for i in range(120)]
    connect_plex(plugin)
    first = plugin.sync(ctx())
    assert first["completed"] is False and first["processed"] == 50
    host.server.fail["/library/sections/1/all"] = {"status": 503, "error": "down"}
    failed = plugin.sync(ctx())
    assert failed["ok"] is False and failed["code"] == "transient"
    assert "continue_after_seconds" not in failed and "disable_schedule" not in failed
    assert FakePlex.base not in json.dumps(failed)
    assert plugin.status(ctx())["error"] == failed["error"]
    del host.server.fail["/library/sections/1/all"]
    resumed = plugin.sync(ctx())
    assert resumed["processed"] == 100  # the saved offset, not a restart
    run_to_completion(plugin)
    assert len({s["external_id"] for s in host.syncs if s["media_type"] == "movie"}) == 120


def test_a_library_that_changes_mid_scan_restarts_the_census(plex):
    plugin, host = plex
    host.server.movies = [FakePlex.movie(i) for i in range(60)]
    connect_plex(plugin)
    plugin.sync(ctx())
    host.server.movies.append(FakePlex.movie(99))
    changed = plugin.sync(ctx())
    assert changed["code"] == "library_changed" and changed["continue_after_seconds"] == 60
    restarted = plugin.sync(ctx())
    assert restarted["phase"] == "roots" and restarted["processed"] == 50
    run_to_completion(plugin)


def test_an_item_missing_from_two_complete_censuses_becomes_unavailable(plex):
    plugin, host = plex
    connect_plex(plugin)
    run_to_completion(plugin)
    host.server.movies = host.server.movies[1:]  # film 100 removed from Plex
    host.syncs.clear()
    assert run_to_completion(plugin)[-1]["unavailable"] == 0
    assert not any(s.get("availability_only") for s in host.syncs)
    final = run_to_completion(plugin)[-1]
    assert final["unavailable"] == 1
    (retired,) = [s for s in host.syncs if s.get("availability_only")]
    assert retired["external_id"] == "100" and retired["available"] is False
    assert retired["watch_url"].endswith("%2F100")
    host.syncs.clear()
    run_to_completion(plugin)
    assert not any(s.get("availability_only") for s in host.syncs)  # sent once
    # It comes back: the next census offers it as available again.
    host.server.movies.insert(0, FakePlex.movie(0))
    run_to_completion(plugin)
    assert [s["available"] for s in host.syncs if s["external_id"] == "100"][-1] is True


def test_conflicts_wait_for_an_explicit_merge_decision(plex):
    plugin, host = plex
    connect_plex(plugin)
    target = str(uuid4())
    host.conflicts["101"] = {"conflict": "ambiguous_match",
                             "candidates": [{"id": target, "title": "Mine"},
                                            {"id": str(uuid4()), "title": "Also mine"}]}
    status = run_to_completion(plugin)[-1]
    assert status["conflict_total"] == 1
    (review,) = status["conflicts"]
    assert review["external_id"] == "101" and review["decisions"] == ["merge", "new"]
    unconfirmed = plugin.resolve(ctx(confirmed=False, external_id="101", decision="merge",
                                     target_id=target))
    assert unconfirmed["ok"] is False
    stranger = plugin.resolve(ctx(external_id="101", decision="merge", target_id=str(uuid4())))
    assert stranger["ok"] is False
    assert plugin.resolve(ctx(external_id="101", decision="use_remote"))["ok"] is False
    assert plugin.resolve(ctx(external_id="101", decision="merge",
                              target_id=target))["conflict_total"] == 0
    host.syncs.clear()
    run_to_completion(plugin)
    merged = [s for s in host.syncs if s["external_id"] == "101"]
    assert merged[0]["target_id"] == target
    assert plugin.status(ctx())["conflict_total"] == 0
    host.syncs.clear()
    run_to_completion(plugin)
    assert "target_id" not in [s for s in host.syncs if s["external_id"] == "101"][0]


def test_a_local_watch_change_is_overwritten_only_after_use_remote(emby):
    plugin, host = emby
    connect_emby(plugin)
    host.conflicts["m1"] = {"conflict": "local_watch_state_changed", "id": str(uuid4())}
    status = run_to_completion(plugin)[-1]
    assert [c["decisions"] for c in status["conflicts"]] == [["use_remote"]]
    assert not any(s.get("force_watch") for s in host.syncs)
    plugin.resolve(ctx(external_id="m1", decision="use_remote"))
    host.syncs.clear()
    run_to_completion(plugin)
    forced = [s for s in host.syncs if s.get("force_watch")]
    assert [s["external_id"] for s in forced] == ["m1"]
    host.syncs.clear()
    host.conflicts.clear()
    run_to_completion(plugin)
    assert not any(s.get("force_watch") for s in host.syncs)  # one-shot


def test_library_choices_are_validated_and_ignored_libraries_are_not_read(plex):
    plugin, host = plex
    connect_plex(plugin)
    assert plugin.save_libraries(ctx(mappings={"9": "movie"}))["ok"] is False
    assert plugin.save_libraries(ctx(mappings={"1": "tv_show"}))["ok"] is False
    saved = plugin.save_libraries(ctx(mappings={"1": "ignore", "2": "anime"}))
    assert {lib["id"]: lib["category"] for lib in saved["libraries"]} == {"1": "ignore",
                                                                          "2": "anime"}
    run_to_completion(plugin)
    assert {s["media_type"] for s in host.syncs} == {"anime"}
    assert not any("/library/sections/1/" in c["url"] for c in host.network)
    show = next(s for s in host.syncs if s["external_id"] == "500")
    assert show["provider_ids"] == {"tvdb": "777"}
    assert plugin.save_libraries(ctx(mappings={"2": "ignore"}))["ok"] is True
    blocked = plugin.sync(ctx())
    assert blocked["ok"] is False and "at least one" in blocked["error"]


def test_anime_films_become_one_episode_anime(plex):
    plugin, host = plex
    connect_plex(plugin)
    plugin.save_libraries(ctx(mappings={"1": "anime", "2": "ignore"}))
    run_to_completion(plugin)
    film = next(s for s in host.syncs if s["external_id"] == "100")
    assert film["media_type"] == "anime"
    assert film["provider_ids"] == {"imdb": "tt000000", "tmdb.movie": "900"}
    assert film["episodes"] == [{"external_id": "film:100", "season": 1, "number": 1,
                                 "title": "Fixture Film 0", "watched": True}]
    assert film["metadata"]["format"] == "Movie"


# --- scheduling hints, leases and failures -------------------------------------------------------


def test_scheduling_hints_for_disconnected_rejected_and_rate_limited_accounts(plex):
    plugin, host = plex
    missing = plugin.sync(ctx())
    assert missing["disable_schedule"] is True and missing["completed"] is False
    connect_plex(plugin)
    host.server.fail["/library/sections/1/all"] = {"status": 429, "retry_after_seconds": 30}
    limited = plugin.sync(ctx())
    assert limited["retry_after_seconds"] == 300 and "disable_schedule" not in limited
    host.server.fail["/library/sections/1/all"] = {"status": 401, "error": "no"}
    rejected = plugin.sync(ctx())
    assert rejected["disable_schedule"] is True and rejected["code"] == "authentication"
    host.server.fail["/library/sections/1/all"] = {"status": 0, "code": "certificate_untrusted"}
    certificate = plugin.sync(ctx())
    assert certificate["code"] == "certificate" and "bypass" in certificate["error"]
    assert_no_secrets(missing, limited, rejected, certificate)
    assert all(FakePlex.base not in json.dumps(r) for r in (limited, rejected, certificate))


def test_concurrent_steps_share_one_lease(plex):
    plugin, host = plex
    connect_plex(plugin)
    host.storage["leases/" + USER] = json.dumps({"id": "x", "expires_at": 4_102_444_800})
    busy = plugin.sync(ctx())
    assert busy.get("code") == "busy", busy
    assert busy["retry_after_seconds"] == 60
    assert not host.syncs
    host.storage["leases/" + USER] = json.dumps({"id": "x", "expires_at": 1})  # expired
    assert plugin.sync(ctx())["ok"] is not False
    assert "leases/" + USER not in host.storage


def test_gateway_denial_returns_a_generic_message(plex):
    plugin, host = plex
    connect_plex(plugin)
    host.denied.add("media.write")
    denied = plugin.sync(ctx())
    assert denied["ok"] is False and "permissions" in denied["summary"]
    assert_no_secrets(denied)
    assert plugin.status({})["ok"] is False  # no authenticated context


def test_disconnect_needs_confirmation_and_keeps_synced_media(emby):
    plugin, host = emby
    connect_emby(plugin)
    run_to_completion(plugin)
    count = len(host.syncs)
    assert plugin.disconnect(ctx(confirmed=False))["ok"] is False
    result = plugin.disconnect(ctx())
    assert result["connected"] is False
    assert host.server.logouts == 1
    assert "secrets/users/" + USER not in host.storage
    assert len(host.syncs) == count  # nothing in the library was touched
    assert plugin.sync(ctx())["disable_schedule"] is True


def test_reconnecting_the_same_account_reuses_item_links(emby):
    plugin, host = emby
    connect_emby(plugin)
    run_to_completion(plugin)
    plugin.disconnect(ctx())
    connect_emby(plugin)
    host.syncs.clear()
    run_to_completion(plugin)
    scopes = {s["source_scope"] for s in host.syncs}
    assert scopes == {"server1:u1"}  # same host identity: no duplicate records


def test_malformed_remote_pages_are_not_half_applied(emby):
    plugin, host = emby
    connect_emby(plugin)
    host.server.movies[1]["UserData"] = {"Played": "yes"}
    bad = plugin.sync(ctx())
    assert bad["ok"] is False and bad["code"] == "remote_data"
    assert not host.syncs  # the valid first row was not written either


def test_an_emby_sign_in_for_another_server_is_rejected(emby):
    plugin, host = emby
    original = host.server.__call__

    def other_server(payload):
        result = original(payload)
        if payload["url"].endswith("/Users/AuthenticateByName") and result["status"] == 200:
            result["data"]["ServerId"] = "someone-else"
        return result

    host.server = other_server
    refused = connect_emby(plugin)
    assert refused["ok"] is False and "secrets/users/" + USER not in host.storage
    assert unquote(json.dumps(refused)).count(EMBY_TOKEN) == 0
