"""official.metadata-atlas against a REAL Atlas container (no mocks of Atlas, only of the host gateway transport).

Run with ``python tools/check_metadata_atlas_live.py ...`` (see tests/atlas_live/README.md). Without the
environment that runner sets, this whole module is skipped: it needs Docker, which a plain ``pytest`` run
does not assume. That is the one documented platform limitation; nothing else here is skipped.

Conventions
-----------
* Ordinary tests pin CURRENT behaviour of the plugin and of the Atlas HTTP API it depends on.
* ``KNOWN ISSUE`` tests state the DESIRED behaviour and are ``xfail(strict=True, raises=AssertionError)``:
  they fail today, and the day a fix lands they turn XPASS (= red) so whoever fixed it must flip the test
  to a normal one. Each names the issue it is waiting for.
"""
import json
import os
import socket
import threading
import time
from pathlib import Path

import jsonschema
import pytest

if not all(os.environ.get(name) for name in ("ATLAS_LIVE_URL", "ATLAS_LIVE_BOOTSTRAP_TOKEN", "ATLAS_LIVE_CONTAINER")):
    pytest.skip("live Atlas lane: run tools/check_metadata_atlas_live.py (needs Docker); see tests/atlas_live/README.md",
                allow_module_level=True)

import atlas_live_support as support  # noqa: E402
from sdk import metadata_provider as sdk  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RESPONSE_SCHEMA = json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text(encoding="utf-8"))
ACTION_OUTPUT_LIMIT = 64 * 1024  # the runtime's action output limit, per the plugin's own comments

KNOWN_ISSUE = pytest.mark.xfail(strict=True, raises=AssertionError)


def work(**extra):
    return {"request": {"query": "starlight", "limit": 5, **extra}}


def selected(plugin, atlas_id=None, **extra):
    """The candidate the host passes back: the Atlas id when it has one, else only other providers' ids."""
    if atlas_id:
        return {"provider": plugin.PROVIDER_ID, "external_id": atlas_id, "provider_ids": {"atlas": atlas_id}, **extra}
    return {"provider": "official.metadata-steam.steam", **extra}


def catalogue(plugin, game_id, *, limit_pages=50):
    """Walk the achievements resource exactly like the host: follow next_cursor until it is absent."""
    items, cursor, pages = [], None, 0
    while True:
        request = {"resource": "achievements", **({"cursor": cursor} if cursor else {})}
        result = plugin.metadata({"request": request, "candidate": selected(plugin, game_id)})
        assert "failure" not in result, result
        assert len(json.dumps(result)) <= ACTION_OUTPUT_LIMIT
        jsonschema.validate(result, RESPONSE_SCHEMA)
        pages += 1
        items += result.get("metadata", {}).get("achievements", [])
        following = result.get("next_cursor")
        if not following:
            return items, pages
        assert following != cursor and pages < limit_pages, "cursor did not advance"
        cursor = following


# --- search ----------------------------------------------------------------------------------------------

def test_search_finds_a_seeded_game_with_the_host_candidate_shape(plugin, gateway, seeded):
    result = plugin.search(work())
    [hit] = result["candidates"]
    assert hit == {"provider": plugin.PROVIDER_ID, "external_id": seeded.ids["starlight"], "title": "Starlight Harbor",
                   "media_type": "game", "year": 2021,
                   "provider_ids": {"atlas": seeded.ids["starlight"], "steam": "5001", "steamlike": "S-1"}}
    [call] = gateway.calls
    assert call.status == 200 and call.path == "/api/v2/games"
    assert call.headers["authorization"] == "Bearer " + seeded.read_token
    assert seeded.read_token not in call.url, "the token must travel only in the Authorization header"


def test_search_is_isolated_by_media_type(plugin, gateway, seeded):
    games = plugin.search(work(query="midnight lanterns", media_type="game"))
    movies = plugin.search(work(query="midnight lanterns", media_type="movie"))
    assert games == {"candidates": []}
    assert [(c["title"], c["media_type"]) for c in movies["candidates"]] == [("Midnight Lanterns", "movie")]
    anime = plugin.search(work(query="clockwork", media_type="anime"))
    assert [c["title"] for c in anime["candidates"]] == ["Clockwork Tide"]


def test_search_with_no_match_is_an_empty_list_not_a_failure(plugin, gateway):
    assert plugin.search(work(query="zzzz no such synthetic title")) == {"candidates": []}


def test_search_clamps_the_limit_to_atlas_maximum(plugin, gateway):
    plugin.search(work(query="orbit", limit=500))
    assert "limit=50" in gateway.calls[0].query


def test_search_returns_the_edition_set_as_one_record_and_the_expansion_as_another(plugin, gateway, seeded):
    """Atlas collapses an observed "Deluxe Edition" into the base record (no edition entity) and keeps the DLC apart."""
    found = plugin.search(work(query="orbit garden"))["candidates"]
    assert {c["external_id"] for c in found} == {seeded.ids["orbit"], seeded.ids["orbit_dlc"]}
    assert len(found) == 2
    base = next(c for c in found if c["external_id"] == seeded.ids["orbit"])
    assert base["provider_ids"].keys() >= {"atlas", "steamlike", "gogish"}, "both sources fed one record"


def test_search_with_a_bad_token_reports_invalid_configuration(plugin, gateway):
    gateway.config["api_token"] = "atl_not_a_real_token"
    assert plugin.search(work()) == {"failure": {"code": "invalid_configuration"}}


def test_search_with_a_revoked_token_reports_invalid_configuration(plugin, gateway, atlas_api, live_env):
    token = atlas_api.token(live_env["bootstrap"], "live-contract-revoked", ["read"])
    gateway.config["api_token"] = token["token"]
    assert plugin.search(work()).get("candidates") is not None
    assert atlas_api.request("DELETE", "/tokens/" + token["id"], live_env["bootstrap"])[0] == 204
    assert plugin.search(work()) == {"failure": {"code": "invalid_configuration"}}


def test_search_works_with_a_read_only_token_and_health_is_healthy(plugin, gateway):
    assert plugin.health({"request": {}}) == {"health": "healthy"}


# --- resolve + details -------------------------------------------------------------------------------------

def test_details_by_atlas_id_maps_the_live_record_and_validates_against_the_host_schema(plugin, gateway, seeded):
    gid = seeded.ids["starlight"]
    result = plugin.metadata({"request": {}, "candidate": selected(plugin, gid)})
    jsonschema.validate(result, RESPONSE_SCHEMA)
    meta = result["metadata"]
    assert meta["title"] == "Starlight Harbor" and meta["release_date"] == "2021-03-12" and meta["year"] == 2021
    assert (meta["developer"], meta["publisher"], meta["series"]) == ("Lantern Forge", "Open Tide", "Harbor")
    assert meta["genres"] == ["adventure"] and set(meta["tags"]) >= {"exploration", "cozy"}
    assert meta["platforms"] == ["PC", "Switch"] and meta["features"] == ["Co-op"]
    assert (meta["players_min"], meta["players_max"], meta["crossplay"]) == (1, 4, "partial")
    assert meta["scores"] == {"critic": 82, "user": 77} and meta["age_rating"] == "E10+"
    assert meta["languages"] == ["English", "French"] and meta["alternate_titles"] == ["Starlight Harbour"]
    assert meta["links"] == [{"label": "Atlas record", "url": f"{seeded.public}/game/{gid}"},
                             {"label": "Website", "url": "https://example.invalid/starlight"}]
    assert meta["provider_ids"]["atlas"] == gid and meta["provider_ids"]["steam"] == "5001"
    assert gateway.paths() == [f"/games/{gid}"]


def test_details_for_a_movie_use_the_movie_mapping(plugin, gateway, seeded):
    cand = selected(plugin, seeded.ids["movie"], media_type="movie")
    meta = plugin.metadata({"request": {}, "candidate": cand})["metadata"]
    assert meta["title"] == "Midnight Lanterns" and meta["director"] == "A. Director"
    assert meta["studios"] == ["Lantern Pictures"] and "developer" not in meta


def test_details_with_the_wrong_media_type_returns_nothing(plugin, gateway, seeded):
    assert plugin.metadata({"request": {}, "candidate": selected(plugin, seeded.ids["movie"], media_type="game")}) == {}


def test_details_for_an_unknown_atlas_id_return_nothing_not_a_failure(plugin, gateway):
    assert plugin.metadata({"request": {}, "candidate": selected(plugin, "atlas:" + "0" * 26)}) == {}
    assert gateway.calls[0].status == 404


def test_resolve_by_steam_id_uses_a_crosswalk_and_returns_the_record(plugin, gateway, seeded):
    cand = selected(plugin, title="Anything the host remembered", year=2021, provider_ids={"steam": "5001"})
    result = plugin.metadata({"request": {}, "candidate": cand})
    assert result["metadata"]["provider_ids"]["atlas"] == seeded.ids["starlight"]
    assert gateway.paths() == ["/resolve"] and gateway.calls[0].method == "POST"


def test_resolve_by_exact_title_and_year_is_accepted_as_certain(plugin, gateway, seeded):
    result = plugin.metadata({"request": {}, "candidate": selected(plugin, title="Cinder Circuit", year=2019)})
    assert result["metadata"]["provider_ids"]["atlas"] == seeded.ids["cinder"]


def test_resolve_with_an_unknown_title_returns_nothing(plugin, gateway):
    assert plugin.metadata({"request": {}, "candidate": selected(plugin, title="Nothing Like It", year=2001)}) == {}


def test_resolve_with_a_fuzzy_title_is_not_trusted(plugin, gateway, seeded):
    """A near-miss title is a 'fuzzy' or 'none' answer from Atlas, never a certain match, so nothing is filled in."""
    result = plugin.metadata({"request": {}, "candidate": selected(plugin, title="Starlight Harbr", year=2021)})
    assert result == {}


def test_resolve_never_follows_an_identity_from_a_different_media_type(plugin, gateway, seeded):
    cand = selected(plugin, title="Midnight Lanterns", year=2019, media_type="game")
    assert plugin.metadata({"request": {}, "candidate": cand}) == {}


def test_resolve_with_conflicting_provider_ids_yields_no_match(plugin, gateway, seeded):
    cand = selected(plugin, title="Twin Signal", year=2018, provider_ids={"steam": "5101", "gog": "5102"})
    assert plugin.metadata({"request": {}, "candidate": cand}) == {}


@KNOWN_ISSUE
def test_KNOWN_ISSUE_atlas_96_resolve_reports_the_conflict_it_found(atlas_api, seeded):
    """Atlas #96: /resolve reports method 'none' for two ids that point at different records and drops the
    internal ``conflict`` list, so a client cannot tell 'unknown' from 'contradictory'. Flip when Atlas returns it."""
    status, body = atlas_api.request("POST", "/resolve", seeded.read_token, {"items": [{
        "title": "Twin Signal", "release_date": "2018-01-01", "media_type": "game",
        "provider_ids": {"steam": "5101", "gog": "5102"}}], "include_view": False})
    assert status == 200
    assert "conflict" in body["results"][0], body["results"][0]


# --- rename + edition children ---------------------------------------------------------------------------------

def test_a_source_rename_keeps_the_atlas_id_and_the_new_title_is_served(plugin, gateway, atlas_api, seeded):
    admin = seeded.admin_token
    cid = atlas_api.observe(admin, "steamlike", "R-1", "Hollow Orchard", "2017-09-29", provider_ids={"steam": "5301"})
    again = atlas_api.observe(admin, "steamlike", "R-1", "Hollow Orchard Reborn", "2017-09-29")
    assert again == cid, "a source renaming its own entry must not mint a new Atlas id"
    meta = plugin.metadata({"request": {}, "candidate": selected(plugin, cid)})["metadata"]
    assert meta["title"] == "Hollow Orchard Reborn"
    assert [c["external_id"] for c in plugin.search(work(query="hollow orchard reborn"))["candidates"]] == [cid]


def test_after_a_rename_the_old_title_is_found_by_the_new_name_not_as_an_alias(plugin, gateway, atlas_api, seeded):
    """Characterises today: the previous title is not kept as an alias, so the host's stored title no longer matches."""
    admin = seeded.admin_token
    cid = atlas_api.observe(admin, "steamlike", "R-2", "Moss and Mortar", "2026-02-02", provider_ids={"steam": "5302"})
    atlas_api.observe(admin, "steamlike", "R-2", "Moss & Mortar Remastered", "2026-02-02")
    meta = plugin.metadata({"request": {}, "candidate": selected(plugin, cid)})["metadata"]
    assert meta["title"] == "Moss & Mortar Remastered"
    assert "Moss and Mortar" not in meta.get("alternate_titles", [])
    # the crosswalk still reaches it from the old identity, so the host keeps working
    cand = selected(plugin, title="Moss and Mortar", year=2026, provider_ids={"steam": "5302"})
    assert plugin.metadata({"request": {}, "candidate": cand})["metadata"]["provider_ids"]["atlas"] == cid


@KNOWN_ISSUE
def test_KNOWN_ISSUE_atlas_86_a_child_edition_or_dlc_names_its_parent(plugin, gateway, seeded):
    """Atlas #86: there are no relationships between records, so the 'Night Expansion' of 'Orbit Garden' reaches the
    host as an unrelated game. The host already accepts ``relations`` on a metadata patch. Flip when it is sent."""
    meta = plugin.metadata({"request": {}, "candidate": selected(plugin, seeded.ids["orbit_dlc"])})["metadata"]
    assert "relations" in meta, sorted(meta)


# --- achievements ------------------------------------------------------------------------------------------------

def test_achievements_page_through_the_whole_catalogue_without_loss_or_duplicates(plugin, gateway, seeded):
    items, pages = catalogue(plugin, seeded.ids["starlight"])
    assert len(items) == seeded.big_count == 450
    assert len({i["external_id"] for i in items}) == 450, "duplicate ids across pages"
    assert pages == 3, "450 entries are three Atlas pages of at most 200"
    names = [i["name"] for i in items]
    assert names[:2] == ["Harbor 0000", "Harbor 0001"]
    assert names[-1] == "Hidden achievement", "hidden entries come last"


def test_achievements_forward_atlas_fields_and_the_hidden_entry_is_redacted(plugin, gateway, seeded):
    items, _ = catalogue(plugin, seeded.ids["starlight"])
    first = items[0]
    assert (first["name"], first["tier"], first["points"], first["kind"]) == ("Harbor 0000", "bronze", 5, "progression")
    assert first["global_percent"] == 90.0 and first["hidden"] is False
    assert first["source_ids"] == {"curator": "src-0"}
    hidden = [i for i in items if i["hidden"]]
    assert len(hidden) == 1 and hidden[0]["name"] == "Hidden achievement"
    assert "description" not in hidden[0] and "source_ids" not in hidden[0], "a read token never sees the real text"


def test_achievement_icons_are_public_media_urls_that_really_serve_the_image(plugin, gateway, atlas_api, seeded):
    items, _ = catalogue(plugin, seeded.ids["starlight"])
    with_icon = [i for i in items if "icon_url" in i]
    assert len(with_icon) > 50
    assert {i["icon_url"] for i in with_icon} == {f"{seeded.public}/media/{seeded.digest}"}
    status, body = atlas_api.request("GET", f"/media/{seeded.digest}", "", root=True, raw=True)
    assert status == 200 and body[:8] == b"\x89PNG\r\n\x1a\n", "the host downloads this URL without credentials"


def test_oversized_pages_split_by_bytes_and_still_deliver_every_entry_once(plugin, gateway, seeded):
    items, pages = catalogue(plugin, seeded.ids["cinder"])
    assert len(items) == seeded.heavy_count and len({i["external_id"] for i in items}) == seeded.heavy_count
    assert pages > 3, "120 entries of ~1.9 KiB each exceed 56 KiB, so one Atlas page must span host pages"
    assert [i["name"] for i in items] == [f"Circuit {k:04d}" for k in range(seeded.heavy_count)]


def test_a_game_without_achievements_returns_nothing(plugin, gateway, seeded):
    result = plugin.metadata({"request": {"resource": "achievements"}, "candidate": selected(plugin, seeded.ids["bare"])})
    assert result == {}, "an empty catalogue is 'nothing', which the host treats as no achievements"


def test_achievements_for_a_movie_are_not_requested(plugin, gateway, seeded):
    cand = selected(plugin, seeded.ids["movie"], media_type="movie")
    assert plugin.metadata({"request": {"resource": "achievements"}, "candidate": cand}) == {}
    assert not any("achievements" in path for path in gateway.paths())


def test_achievements_can_be_resolved_from_a_linked_steam_identity(plugin, gateway, seeded):
    cand = selected(plugin, title="Starlight Harbor", year=2021, provider_ids={"steam": "5001"})
    first = plugin.metadata({"request": {"resource": "achievements"}, "candidate": cand})
    assert len(first["metadata"]["achievements"]) == 200 and first["next_cursor"] == "200"
    assert gateway.paths()[0] == "/resolve"


def test_invalid_and_exhausted_cursors(plugin, gateway, seeded):
    base = {"resource": "achievements"}
    cand = selected(plugin, seeded.ids["starlight"])
    assert plugin.metadata({"request": {**base, "cursor": "abc"}, "candidate": cand}) == {"failure": {"code": "invalid_response"}}
    assert plugin.metadata({"request": {**base, "cursor": "2000"}, "candidate": cand}) == {"metadata": {"achievements": []}}
    assert plugin.metadata({"request": {**base, "cursor": "999"}, "candidate": cand}) == {}  # past Atlas's last entry


def test_atlas_reports_the_unpaged_total_the_plugin_relies_on(atlas_api, seeded):
    status, page = atlas_api.request("GET", f"/games/{seeded.ids['starlight']}/achievements?limit=200&offset=400", seeded.read_token)
    assert status == 200 and (page["total"], page["next_offset"], len(page["results"])) == (450, None, 50)
    status, first = atlas_api.request("GET", f"/games/{seeded.ids['starlight']}/achievements?limit=200", seeded.read_token)
    assert first["next_offset"] == 200 and first["hidden_count"] == 1


@KNOWN_ISSUE
def test_KNOWN_ISSUE_atlas_78_achievement_external_ids_survive_an_atlas_edit(plugin, gateway, atlas_api, seeded):
    """Atlas #78 (defect 1) / plugins #70: the plugin forwards Atlas's achievement ``id`` as the host ``external_id``,
    and Atlas gives every row a fresh id each time a source's list is replaced, so one refresh makes the host delete and
    recreate the whole catalogue (and orphan manual progress). Flip when ids are stable across an edit."""
    cid = atlas_api.observe(seeded.admin_token, "steamlike", "CH-1", "Churn Subject", "2020-01-01")
    items = support.achievements(5, prefix="Churn")
    atlas_api.ok("PUT", f"/games/{cid}/achievements", seeded.admin_token, {"items": items})
    before = {i["name"]: i["external_id"] for i in catalogue(plugin, cid)[0]}
    atlas_api.ok("PUT", f"/games/{cid}/achievements", seeded.admin_token, {"items": items})  # an unchanged re-import
    after = {i["name"]: i["external_id"] for i in catalogue(plugin, cid)[0]}
    assert before.keys() == after.keys() and len(before) == 5
    assert before == after, "every external_id changed"


def test_atlas_78_current_behaviour_the_ids_do_change_but_names_and_order_do_not(plugin, gateway, atlas_api, seeded):
    """Companion to the KNOWN ISSUE above, on a separate game: what stays stable today is the name and the order."""
    cid = atlas_api.observe(seeded.admin_token, "steamlike", "CH-2", "Churn Companion", "2020-01-01")
    items = support.achievements(4, prefix="Stable")
    atlas_api.ok("PUT", f"/games/{cid}/achievements", seeded.admin_token, {"items": items})
    before, _ = catalogue(plugin, cid)
    atlas_api.ok("PUT", f"/games/{cid}/achievements", seeded.admin_token, {"items": items})
    after, _ = catalogue(plugin, cid)
    assert [i["name"] for i in before] == [i["name"] for i in after]
    assert {i["external_id"] for i in before}.isdisjoint({i["external_id"] for i in after})


# --- artwork -------------------------------------------------------------------------------------------------

def test_media_lists_only_cached_artwork_under_the_public_media_path(plugin, gateway, seeded):
    result = plugin.media({"request": {}, "candidate": selected(plugin, seeded.ids["starlight"])})
    assets = result["assets"]
    assert [a["kind"] for a in assets] == ["key_art", "logo"], "the never-downloaded banner has no cached copy"
    assert [a["url"] for a in assets] == [f"{seeded.public}/media/{seeded.digest}",
                                          f"{seeded.public}/media/{seeded.digest_logo}"]
    assert [a["priority"] for a in assets] == [0, 10]
    assert (assets[0]["width"], assets[0]["height"]) == (1, 1)


def test_media_maps_key_art_to_poster_for_non_games(plugin, gateway, seeded):
    result = plugin.media({"request": {}, "candidate": selected(plugin, seeded.ids["movie"], media_type="movie")})
    assert [(a["kind"], a["url"]) for a in result["assets"]] == [("poster", f"{seeded.public}/media/{seeded.digest_movie}")]


def test_media_for_a_game_without_artwork_is_empty(plugin, gateway, seeded):
    assert plugin.media({"request": {}, "candidate": selected(plugin, seeded.ids["bare"])}) == {"assets": []}


def test_media_for_an_unknown_game_is_empty_not_a_failure(plugin, gateway):
    assert plugin.media({"request": {}, "candidate": selected(plugin, "atlas:" + "1" * 26)}) == {"assets": []}


def test_public_base_url_setting_controls_every_link_the_host_will_fetch(plugin, gateway, seeded):
    gateway.config["public_base_url"] = "https://atlas.example.invalid"
    meta = plugin.metadata({"request": {}, "candidate": selected(plugin, seeded.ids["starlight"])})["metadata"]
    assert meta["links"][0]["url"].startswith("https://atlas.example.invalid/game/")
    assets = plugin.media({"request": {}, "candidate": selected(plugin, seeded.ids["starlight"])})["assets"]
    assert all(a["url"].startswith("https://atlas.example.invalid/media/") for a in assets)


# --- request economy (N+1) --------------------------------------------------------------------------------------

def test_request_counts_today(plugin, gateway, seeded):
    """Pins today's number of Atlas requests per host operation, so a change in either direction is visible."""
    gid = seeded.ids["starlight"]
    cand = selected(plugin, gid)
    plugin.metadata({"request": {}, "candidate": cand})
    assert len(gateway.calls) == 1
    gateway.reset()
    plugin.media({"request": {}, "candidate": cand})
    assert gateway.paths() == [f"/games/{gid}", f"/games/{gid}/artwork"]
    gateway.reset()
    catalogue(plugin, gid)
    assert len(gateway.calls) == 2 * 3, "one game lookup plus one page request for each of the 3 host pages"


@KNOWN_ISSUE
def test_KNOWN_ISSUE_n_plus_one_media_needs_one_request_for_a_known_atlas_id(plugin, gateway, seeded):
    """The plugin re-reads /games/<id> before /artwork even though the host already passed the id (an extra request per
    operation, and per achievements page: 2N requests for N pages). Flip when a known id goes straight to the data."""
    gid = seeded.ids["starlight"]
    plugin.media({"request": {}, "candidate": selected(plugin, gid)})
    assert gateway.paths() == [f"/games/{gid}/artwork"], gateway.paths()


@KNOWN_ISSUE
def test_KNOWN_ISSUE_n_plus_one_each_achievement_page_costs_one_request(plugin, gateway, seeded):
    gid = seeded.ids["starlight"]
    catalogue(plugin, gid)
    assert len(gateway.calls) == 3, f"{len(gateway.calls)} requests for 3 pages"


# --- offline, stalled and interrupted ----------------------------------------------------------------------------

def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.parametrize("operation", ["search", "metadata", "media", "health"])
def test_unreachable_atlas_is_reported_as_unavailable_for_every_operation(plugin, gateway, seeded, operation):
    gateway.config["base_url"] = f"http://127.0.0.1:{free_port()}"
    call = {"search": lambda: plugin.search(work()),
            "metadata": lambda: plugin.metadata({"request": {}, "candidate": selected(plugin, seeded.ids["starlight"])}),
            "media": lambda: plugin.media({"request": {}, "candidate": selected(plugin, seeded.ids["starlight"])}),
            "health": lambda: plugin.health({"request": {}})}[operation]
    assert call() == {"failure": {"code": "unavailable"}}
    assert gateway.calls and all(c.status == 0 for c in gateway.calls)


class Stalled:
    """Accepts connections and never answers: what an Atlas behind a hung proxy looks like."""

    def __init__(self):
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(8)
        self.port = self.socket.getsockname()[1]
        self.held = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                self.held.append(self.socket.accept()[0])
            except OSError:
                return

    def close(self):
        self.socket.close()
        for connection in self.held:
            connection.close()


def test_a_stalled_atlas_times_out_within_the_gateway_deadline(plugin, gateway):
    stalled = Stalled()
    try:
        gateway.timeout = 1.0
        gateway.config["base_url"] = f"http://127.0.0.1:{stalled.port}"
        started = time.monotonic()
        assert plugin.search(work()) == {"failure": {"code": "unavailable"}}
        assert time.monotonic() - started < 5, "an interactive request is one attempt and never retries"
        assert len(gateway.calls) == 1 and gateway.calls[0].status == 0
    finally:
        stalled.close()


def test_background_requests_retry_a_stalled_atlas_a_bounded_number_of_times(plugin, gateway):
    stalled = Stalled()
    try:
        gateway.timeout = 0.5
        gateway.config["base_url"] = f"http://127.0.0.1:{stalled.port}"
        started = time.monotonic()
        result = plugin.search({"request": {"query": "x", "limit": 1, "policy": "background"}})
        assert result == {"failure": {"code": "unavailable"}}
        assert len(gateway.calls) == 3, "three attempts, then give up"
        assert time.monotonic() - started < 24
    finally:
        stalled.close()


def test_a_paused_atlas_container_is_reported_then_recovers(plugin, gateway, live_env, seeded):
    gateway.timeout = 1.5
    support.pause(live_env["container"])
    try:
        assert plugin.search(work()) == {"failure": {"code": "unavailable"}}
        assert plugin.health({"request": {}}) == {"failure": {"code": "unavailable"}}
    finally:
        support.unpause(live_env["container"])
    gateway.timeout = support.HOST_TIMEOUT_SECONDS
    assert plugin.health({"request": {}}) == {"health": "healthy"}


def test_losing_atlas_between_achievement_pages_fails_instead_of_truncating(plugin, gateway, live_env, seeded):
    """The host must see a failure for page 2, never a silently shorter catalogue that it would then trust."""
    gid = seeded.ids["starlight"]
    first = plugin.metadata({"request": {"resource": "achievements"}, "candidate": selected(plugin, gid)})
    assert first["next_cursor"] == "200"
    gateway.timeout = 1.5
    support.pause(live_env["container"])
    try:
        second = plugin.metadata({"request": {"resource": "achievements", "cursor": "200"},
                                  "candidate": selected(plugin, gid)})
    finally:
        support.unpause(live_env["container"])
    assert second == {"failure": {"code": "unavailable"}}
    resumed = plugin.metadata({"request": {"resource": "achievements", "cursor": "200"}, "candidate": selected(plugin, gid)})
    assert len(resumed["metadata"]["achievements"]) == 200, "the same cursor works again once Atlas is back"


def test_nothing_secret_is_left_in_results_or_urls(plugin, gateway, seeded):
    plugin.search(work())
    plugin.metadata({"request": {}, "candidate": selected(plugin, seeded.ids["starlight"])})
    result = plugin.media({"request": {}, "candidate": selected(plugin, seeded.ids["starlight"])})
    assert seeded.read_token not in json.dumps(result)
    assert all(seeded.read_token not in call.url for call in gateway.calls)
    assert {call.headers.get("authorization") for call in gateway.calls} == {"Bearer " + seeded.read_token}
