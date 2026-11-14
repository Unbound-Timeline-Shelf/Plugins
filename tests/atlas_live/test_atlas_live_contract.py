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
import re
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
    # the second read fetches the relations block, which only GET /games/{id} carries (C6.3)
    assert gateway.paths() == ["/resolve", "/games/" + seeded.ids["starlight"]]
    assert [call.method for call in gateway.calls] == ["POST", "GET"]


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


def test_atlas_96_resolve_reports_the_conflict_it_found(atlas_api, seeded):
    """Atlas #96 (contract C4.1): two ids that point at different records are reported as a ``conflict`` with no
    canonical id, not as an unknown game. Needs an Atlas from the A6 change; an older Atlas answers ``none``."""
    status, body = atlas_api.request("POST", "/resolve", seeded.read_token, {"items": [{
        "title": "Twin Signal", "release_date": "2018-01-01", "media_type": "game",
        "provider_ids": {"steam": "5101", "gog": "5102"}}], "include_view": False})
    assert status == 200
    result = body["results"][0]
    assert (result["reason"], result["tier"], result["canonical_id"], result["method"]) == ("conflict", "id", None, "none")
    assert sorted(result["conflict"]["canonical_ids"]) == sorted([seeded.ids["twin_a"], seeded.ids["twin_b"]])


def test_resolve_with_conflicting_provider_ids_logs_the_conflict_and_adopts_nothing(plugin, gateway, seeded, capsys):
    cand = selected(plugin, title="Twin Signal", year=2018, provider_ids={"steam": "5101", "gog": "5102"})
    assert plugin.metadata({"request": {}, "candidate": cand}) == {}  # not a failure, and no marker in `custom`
    assert plugin.media({"request": {}, "candidate": cand}) == {"assets": []}
    logged = capsys.readouterr().err
    assert seeded.ids["twin_a"] in logged and seeded.ids["twin_b"] in logged
    assert gateway.paths() == ["/resolve", "/resolve"]


# --- the shared /resolve fixture (contract C4.5), replayed through the plugin ----------------------------------------

FIXTURE = ROOT / "tests" / "fixtures" / "atlas" / "resolve-contract-v1.json"
SPEC = json.loads(FIXTURE.read_text(encoding="utf-8"))
SAFE_REASONS = {"id", "redirect", "crosswalk", "exact"}


def substitute(value, ids):
    if isinstance(value, str) and value.startswith("$"):
        return ids[value[1:]]
    if isinstance(value, dict):
        return {k: substitute(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, ids) for v in value]
    return value


@pytest.fixture(scope="module")
def contract_ids(atlas_api, seeded):
    """Build the fixture's records in the live node (ingest, then merges), exactly as the fixture describes."""
    ids = {}
    for seed in SPEC["seeds"]:
        fields = {key: seed[key] for key in ("provider_ids",) if key in seed}
        if "developer" in seed:
            fields["facts"] = {"developer": seed["developer"]}
        ids[seed["name"]] = atlas_api.observe(seeded.admin_token, seed["source"], seed["external_id"], seed["title"],
                                              seed.get("release_date"), **fields)
    for source, target in SPEC["merges"]:
        atlas_api.ok("POST", f"/games/{substitute(source, ids)}/merge", seeded.admin_token,
                     {"into": substitute(target, ids)})
    return ids


def host_candidate(plugin, request):
    """The candidate a host would pass for one fixture request: its own ids, its title and its year."""
    provider_ids = dict(request.get("provider_ids") or {})
    if request.get("namespace") and request.get("external_id"):
        provider_ids[request["namespace"]] = request["external_id"]
    extra = {"title": request.get("title"), "media_type": request.get("media_type", "game")}
    if request.get("release_date"):
        extra["year"] = int(request["release_date"][:4])
    if "atlas" in provider_ids:
        return selected(plugin, provider_ids["atlas"], **extra)
    return selected(plugin, provider_ids=provider_ids, **extra)


@pytest.mark.parametrize("case", SPEC["cases"], ids=lambda c: c["name"])
def test_fixture_case_through_the_plugin(plugin, gateway, atlas_api, seeded, contract_ids, capsys, case):
    """A client adopts an identity exactly when the fixture says it may: id, redirect, crosswalk and exact."""
    want = substitute(case["expect"], contract_ids)
    candidate = host_candidate(plugin, substitute(case["request"], contract_ids))
    result = plugin.metadata({"request": {}, "candidate": candidate})
    assert "failure" not in result, result
    held = candidate.get("provider_ids", {}).get("atlas")
    if held and not plugin.ATLAS_ID.match(held):
        assert result == {} and gateway.calls == []  # a malformed Atlas id never reaches the network
        return
    if held:
        # An Atlas id the host already holds is looked up directly (C4.2): the live record under its live id, or
        # nothing for an id Atlas does not have. It does not go through /resolve.
        status, record = atlas_api.request("GET", "/games/" + held, seeded.read_token)
        assert gateway.paths() == ["/games/" + held]
        if status == 404:
            assert result == {}
        else:
            assert result["metadata"]["provider_ids"]["atlas"] == record["id"]
            if want["reason"] in ("id", "redirect"):
                assert record["id"] == want["canonical_id"]
        return
    # an adopted record is read once more for its relations block (C6.3), which /resolve does not include
    assert gateway.paths() == ["/resolve"] + (["/games/" + want["canonical_id"]] if result else [])
    assert bool(result) is (want["reason"] in SAFE_REASONS), (case["name"], result)
    if result:
        assert result["metadata"]["provider_ids"]["atlas"] == want["canonical_id"]
        if "game_title" in want:
            assert result["metadata"]["title"] == want["game_title"]
    if want["reason"] == "conflict":
        logged = capsys.readouterr().err
        assert all(cid in logged for cid in want["conflict_ids"])


# --- merge, rename and conflict as the host meets them -------------------------------------------------------------

def test_a_merged_atlas_id_is_followed_to_the_live_record_for_metadata_artwork_and_achievements(
        plugin, gateway, atlas_api, seeded):
    admin = seeded.admin_token
    old = atlas_api.observe(admin, "steamlike", "MG-1", "Merge Source Field", "2016-04-01", provider_ids={"steam": "5401"})
    live = atlas_api.observe(admin, "gogish", "MG-2", "Merge Target Field", "2016-04-02", provider_ids={"gog": "5402"})
    atlas_api.ok("PUT", f"/games/{live}/achievements", admin, {"items": [
        {"name": "Merged One", "description": "d", "external_id": "m-1"},
        {"name": "Merged Two", "description": "d", "external_id": "m-2"}]})
    atlas_api.ok("PUT", f"/games/{live}/artwork", admin, {"items": [
        {"kind": "logo", "url": f"{seeded.public}/media/{seeded.digest_logo}", "priority": 1}]})
    atlas_api.ok("POST", f"/games/{old}/merge", admin, {"into": live})
    assert old != live
    cand = selected(plugin, old, title="Merge Source Field", year=2016)
    meta = plugin.metadata({"request": {}, "candidate": cand})["metadata"]
    assert meta["provider_ids"]["atlas"] == live and meta["provider_ids"]["steam"] == "5401"
    assert meta["links"][0]["url"] == f"{seeded.public}/game/{live}"
    # the merged-away id travels only as the id the host should follow (C4.4 rule 2)
    assert meta.pop("identity") == {"match": "redirect", "previous_ids": {"atlas": old}}
    assert old not in json.dumps(meta)
    assets = plugin.media({"request": {}, "candidate": cand})["assets"]
    assert [a["kind"] for a in assets] == ["logo"]
    items, _ = catalogue(plugin, old)
    assert sorted(i["name"] for i in items) == ["Merged One", "Merged Two"]
    # every request after the first lookup of each operation used the live id, never the merged one
    assert not any(p.startswith(f"/games/{old}/") for p in gateway.paths()), gateway.paths()


def test_a_provider_id_of_a_merged_record_resolves_to_the_live_id(plugin, gateway, atlas_api, seeded):
    admin = seeded.admin_token
    a = atlas_api.observe(admin, "steamlike", "MG-3", "Chain Alpha Field", "2015-01-01", provider_ids={"steam": "5411"})
    b = atlas_api.observe(admin, "gogish", "MG-4", "Chain Beta Field", "2015-02-02", provider_ids={"gog": "5412"})
    c = atlas_api.observe(admin, "steamlike", "MG-5", "Chain Gamma Field", "2015-03-03", provider_ids={"steam": "5413"})
    atlas_api.ok("POST", f"/games/{a}/merge", admin, {"into": b})
    atlas_api.ok("POST", f"/games/{b}/merge", admin, {"into": c})
    cand = selected(plugin, title="Chain Alpha Field", year=2015, provider_ids={"steam": "5411"})
    assert plugin.metadata({"request": {}, "candidate": cand})["metadata"]["provider_ids"]["atlas"] == c
    by_old_id = plugin.metadata({"request": {}, "candidate": selected(plugin, a)})["metadata"]
    assert by_old_id["provider_ids"]["atlas"] == c
    assert by_old_id["identity"] == {"match": "redirect", "previous_ids": {"atlas": a}}


def test_a_renamed_record_is_found_by_its_provider_id_and_not_by_its_old_title(plugin, gateway, atlas_api, seeded):
    admin = seeded.admin_token
    cid = atlas_api.observe(admin, "steamlike", "RN-1", "Placeholder Working Name", "2014-05-05",
                            provider_ids={"steam": "5421"})
    atlas_api.observe(admin, "steamlike", "RN-1", "Final Shipping Name", "2014-05-05")
    by_id = selected(plugin, title="Placeholder Working Name", year=2014, provider_ids={"steam": "5421"})
    meta = plugin.metadata({"request": {}, "candidate": by_id})["metadata"]
    assert meta["provider_ids"]["atlas"] == cid and meta["title"] == "Final Shipping Name"
    by_title = selected(plugin, title="Placeholder Working Name", year=2014)
    assert plugin.metadata({"request": {}, "candidate": by_title}) == {}


def test_a_title_twin_is_not_adopted_when_the_client_holds_a_different_id(plugin, gateway, atlas_api, seeded):
    atlas_api.observe(seeded.admin_token, "steamlike", "DM-1", "Dusk Marsh", "2012-02-02", provider_ids={"steam": "5431"})
    cand = selected(plugin, title="Dusk Marsh", year=2012, provider_ids={"steam": "5439"})
    assert plugin.metadata({"request": {}, "candidate": cand}) == {}


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


def relate(atlas_api, seeded, child, parent, kind="dlc_of"):
    """Give `child` the relation `kind` to `parent` through Atlas's curate API (C6.3). False when the Atlas under test
    predates relations (A15): it has no such route, and its records carry no relations block."""
    status, payload = atlas_api.request("PUT", f"/games/{child}/relations", seeded.admin_token,
                                        {"relations": [{"to": parent, "type": kind}]})
    if status in (404, 405):
        assert "relations" not in atlas_view(atlas_api, seeded, child)
        return False
    assert status == 200, (status, payload)
    assert [(p["id"], p["type"]) for p in payload["relations"]["parents"]] == [(parent, kind)]
    return True


def test_a_dlc_names_its_parent_game_as_a_relation(plugin, gateway, atlas_api, seeded, monkeypatch):
    """Atlas #86 / C6.4: the 'Night Expansion' of 'Orbit Garden' reaches the host as a `dlc_of` relation whose target
    is the base game's Atlas id, found by Atlas id and by its Steam id (through /resolve) alike. The base game itself
    only has an incoming relation, which travels with the DLC's refresh."""
    dlc, base = seeded.ids["orbit_dlc"], seeded.ids["orbit"]
    if not relate(atlas_api, seeded, dlc, base):
        assert "relations" not in details(plugin, dlc)
        return
    title = atlas_view(atlas_api, seeded, base)["title"]  # the base record's merged title, as Atlas lists it
    expected = [{"candidate": {"provider": plugin.PROVIDER_ID, "external_id": base, "title": title,
                               "media_type": "game", "provider_ids": {"atlas": base}},
                 "relation": "dlc_of", "group": "related"}]
    assert details(plugin, dlc)["relations"] == expected
    by_steam = selected(plugin, title="Orbit Garden - Night Expansion", year=2021, provider_ids={"steam": "5004"},
                        media_type="game")
    result = plugin.metadata({"request": {}, "candidate": by_steam})
    jsonschema.validate(result, RESPONSE_SCHEMA)
    assert result["metadata"]["provider_ids"]["atlas"] == dlc and result["metadata"]["relations"] == expected
    assert "relations" not in details(plugin, base), "children are the other record's edges"
    monkeypatch.setattr(plugin, "API_CONTRACT", (1, 1, 19))
    assert "relations" not in details(plugin, dlc)


def test_relations_follow_a_merge_of_the_parent(plugin, gateway, atlas_api, seeded):
    """C6.3 merges move edges: when the parent is merged into another record, the relation names the survivor."""
    admin = seeded.admin_token
    child = atlas_api.observe(admin, "steamlike", "RM-1", "Tidal Rooms - Deep Wing", "2024-04-04")
    parent = atlas_api.observe(admin, "steamlike", "RM-2", "Tidal Rooms", "2023-03-03")
    survivor = atlas_api.observe(admin, "gogish", "RM-3", "Rooms of the Tide", "2023-03-04")
    assert len({child, parent, survivor}) == 3
    if not relate(atlas_api, seeded, child, parent):
        return
    atlas_api.ok("POST", f"/games/{parent}/merge", admin, {"into": survivor})
    [sent] = details(plugin, child)["relations"]
    assert (sent["relation"], sent["candidate"]["external_id"]) == ("dlc_of", survivor)


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
    assert first["source_ids"].pop("atlas.row") and first["source_ids"] == {"curator": "src-0"}
    hidden = [i for i in items if i["hidden"]]
    assert len(hidden) == 1 and hidden[0]["name"] == "Hidden achievement"
    assert "description" not in hidden[0], "a read token never sees the real text"
    assert list(hidden[0]["source_ids"]) == ["atlas.row"], "only the bridge: no provider id leaks from a hidden entry"


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
    # Cut by bytes: the stable key and the atlas.row bridge make an entry larger, so the page ends at or before 200.
    assert 0 < len(first["metadata"]["achievements"]) <= 200 and first["next_cursor"] == str(len(first["metadata"]["achievements"]))
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


def atlas_rows(atlas_api, token, cid):
    """Atlas's own view of a game's achievements: ``[(id, key or None), ...]`` in API order."""
    status, page = atlas_api.request("GET", f"/games/{cid}/achievements?limit=200", token)
    assert status == 200, page
    return [(entry["id"], entry.get("key")) for entry in page["results"]]


def atlas_serves_keys(atlas_api, seeded):
    """True for an Atlas that carries the contract C2 ``key`` (A4 and later); False for an older one."""
    return all(key for _, key in atlas_rows(atlas_api, seeded.read_token, seeded.ids["starlight"])[:5])


def test_atlas_78_achievement_external_ids_survive_an_atlas_edit(plugin, gateway, atlas_api, seeded):
    """Atlas #78 (defect 1) / plugins #70, contract C2: the plugin forwards Atlas's stable ``ak1`` key as the host
    ``external_id`` (the row id only against an Atlas that predates keys), so an unchanged re-import or an edit of
    one source's list leaves every external_id alone and the host keeps its catalogue and manual progress."""
    cid = atlas_api.observe(seeded.admin_token, "steamlike", "CH-1", "Churn Subject", "2020-01-01")
    items = support.achievements(5, prefix="Churn")
    atlas_api.ok("PUT", f"/games/{cid}/achievements", seeded.admin_token, {"items": items})
    before, _ = catalogue(plugin, cid)
    atlas_api.ok("PUT", f"/games/{cid}/achievements", seeded.admin_token, {"items": items})  # an unchanged re-import
    after, _ = catalogue(plugin, cid)
    ids = lambda rows: {i["name"]: i["external_id"] for i in rows}  # noqa: E731
    assert ids(before).keys() == ids(after).keys() and len(before) == 5
    assert ids(before) == ids(after), "every external_id changed"
    assert [i["source_ids"]["atlas.row"] for i in before] == [i["source_ids"]["atlas.row"] for i in after]


def test_atlas_78_the_key_is_the_external_id_and_the_row_id_is_the_bridge(plugin, gateway, atlas_api, seeded):
    """Compat matrix, both cells against the real Atlas under test: with keys the key is the identity and the row id
    rides as ``atlas.row``; against an older Atlas the plugin falls back to the row id (today's behaviour)."""
    cid = atlas_api.observe(seeded.admin_token, "steamlike", "CH-3", "Bridge Subject", "2020-01-01")
    atlas_api.ok("PUT", f"/games/{cid}/achievements", seeded.admin_token,
                 {"items": support.achievements(6, prefix="Bridge", hidden=(2,))})
    rows = atlas_rows(atlas_api, seeded.read_token, cid)
    items, _ = catalogue(plugin, cid)
    assert len(items) == len(rows) == 6
    for (row_id, key), item in zip(rows, items):
        assert item["source_ids"]["atlas.row"] == row_id
        if key is None:  # an Atlas that predates keys
            assert item["external_id"] == row_id
        else:
            assert re.fullmatch(r"ak1:[a-z2-7]{26}", key) and item["external_id"] == key != row_id
    assert len({i["external_id"] for i in items}) == 6
    assert any(i["hidden"] for i in items), "the hidden entry is forwarded too, with its key and no real text"


def test_atlas_78_an_edit_of_one_entry_keeps_the_identity_of_every_other(plugin, gateway, atlas_api, seeded):
    """Changing one entry's text and dropping another must not move the survivors (in-place reconcile, C2.2)."""
    cid = atlas_api.observe(seeded.admin_token, "steamlike", "CH-4", "Edit Subject", "2020-01-01")
    items = support.achievements(5, prefix="Edit")
    atlas_api.ok("PUT", f"/games/{cid}/achievements", seeded.admin_token, {"items": items})
    before = {i["name"]: i["external_id"] for i in catalogue(plugin, cid)[0]}
    edited = [dict(i, description="Changed text") for i in items[:4]]  # entry 4 is dropped, the rest are edited
    atlas_api.ok("PUT", f"/games/{cid}/achievements", seeded.admin_token, {"items": edited})
    after_items, _ = catalogue(plugin, cid)
    after = {i["name"]: i["external_id"] for i in after_items}
    assert set(after) == set(before) - {"Edit 0004"}
    if atlas_serves_keys(atlas_api, seeded):
        assert all(after[name] == before[name] for name in after), "a survivor's external_id moved"
        assert all(i["description"] == "Changed text" for i in after_items)
    else:
        assert all(after[name] != before[name] for name in after), "an older Atlas churns row ids"


# --- Plugin API 1.1.20: partial and regional dates, platinum, aliases (contracts C5.3, C2.6, C7) -----------------

NEW_PATCH_FIELDS = {"first_release", "releases", "identity"}


def details(plugin, atlas_id):
    result = plugin.metadata({"request": {}, "candidate": selected(plugin, atlas_id)})
    assert "failure" not in result, result
    jsonschema.validate(result, RESPONSE_SCHEMA)
    return result["metadata"]


def atlas_view(atlas_api, seeded, cid):
    return atlas_api.ok("GET", f"/games/{cid}", seeded.read_token)


def atlas_dates(atlas_api, seeded):
    """Whether the Atlas under test serves partial dates (Atlas contract C5, programme/a14 and later)."""
    return "first_release" in atlas_view(atlas_api, seeded, seeded.ids["starlight"])


def observe_dated(atlas_api, seeded, external_id, title, release, **fields):
    """An observation carrying `ext.release`, or None when the Atlas under test predates it and refuses it."""
    status, payload = atlas_api.request("POST", "/observations", seeded.admin_token, {
        "connection": {"source_kind": "plugin", "source": "steamlike", "source_scope": "live-contract"},
        "media_type": "game",
        "observations": [{"external_id": external_id, "title": title, "ext": {"release": release}, **fields}]})
    if not atlas_dates(atlas_api, seeded):
        assert status == 422 or (200 <= status < 300 and payload["results"][0].get("error")), (status, payload)
        return None
    assert 200 <= status < 300, (status, payload)
    return payload["results"][0]["atlas"]["canonical_id"]


def test_partial_and_regional_release_dates_reach_the_host_at_their_precision(plugin, gateway, atlas_api, seeded):
    """C5.3: a month stays a month and a year a year; the regional entries are forwarded as Atlas serves them."""
    release = {"first": {"date": "2015-03", "precision": "month"},
               "entries": [{"date": "2015-09", "precision": "month", "platform": "ps4", "region": "eu",
                            "category": "full"},
                           {"date": "2016", "precision": "year", "platform": "switch", "region": "jp",
                            "edition": "Complete Edition", "category": "full"},
                           {"date": "2014-11-20", "precision": "day", "platform": "pc", "region": "ww",
                            "category": "beta"}]}
    cid = observe_dated(atlas_api, seeded, "D-1", "Dated Lantern", release, edition="Complete Edition")
    if cid is None:  # an Atlas before contract C5 refuses the dated observation; nothing partial reaches the host
        return
    view = atlas_view(atlas_api, seeded, cid)
    assert view["first_release"] == {"date": "2015-03", "precision": "month"} and view.get("release_date") is None
    meta = details(plugin, cid)
    assert meta["first_release"] == {"date": "2015-03", "precision": "month"}
    assert "release_date" not in meta, "a month is never sent as a day"
    assert meta["year"] == 2015
    assert meta["releases"] == [{key: value for key, value in entry.items() if value is not None}
                                for entry in view["releases"]]
    assert {(e["date"], e["precision"], e.get("region")) for e in meta["releases"]} == {
        ("2015-09", "month", "eu"), ("2016", "year", "jp"), ("2014-11-20", "day", "ww")}
    [hit] = [c for c in plugin.search(work(query="dated lantern"))["candidates"] if c["external_id"] == cid]
    assert hit["year"] == 2015


def test_a_day_first_release_also_travels_as_the_legacy_day(plugin, gateway, atlas_api, seeded):
    meta = details(plugin, seeded.ids["starlight"])
    assert meta["release_date"] == "2021-03-12" and meta["year"] == 2021
    if atlas_dates(atlas_api, seeded):
        assert meta["first_release"] == {"date": "2021-03-12", "precision": "day"}


def test_a_curator_year_lock_is_sent_as_a_year_not_as_1_january(plugin, gateway, atlas_api, seeded):
    """Both cells: from contract C5 Atlas serves the lock as `first_release`; an older Atlas serves "2011" in the
    day-only key, which the plugin reads as a year instead of sending it as a date the host would refuse."""
    cid = atlas_api.observe(seeded.admin_token, "steamlike", "D-2", "Locked Year", "2011-04-19")
    atlas_api.ok("PUT", f"/games/{cid}/locks/release_date", seeded.admin_token, {"value": "2011"})
    meta = details(plugin, cid)
    assert meta["first_release"] == {"date": "2011", "precision": "year"} and meta["year"] == 2011
    assert "release_date" not in meta


def test_a_releases_lock_is_forwarded_as_the_release_list(plugin, gateway, atlas_api, seeded):
    cid = atlas_api.observe(seeded.admin_token, "steamlike", "D-3", "Locked Releases", "2018-06-01")
    entries = [{"date": "2018-06-01", "precision": "day", "platform": "pc", "region": "ww", "category": "full"},
               {"date": "2019", "precision": "year", "platform": "ps4", "region": "na", "category": "port"}]
    if not atlas_dates(atlas_api, seeded):  # an older Atlas has no `releases` view key; nothing extra is sent
        meta = details(plugin, cid)
        assert "releases" not in meta and "first_release" not in meta and meta["release_date"] == "2018-06-01"
        return
    atlas_api.ok("PUT", f"/games/{cid}/locks/releases", seeded.admin_token, {"value": entries})
    meta = details(plugin, cid)
    assert meta["releases"] == entries
    assert meta["release_date"] == "2018-06-01" and meta["first_release"] == {"date": "2018-06-01", "precision": "day"}


def test_a_free_text_date_lock_sends_no_date_and_does_not_break_the_response(plugin, gateway, atlas_api, seeded):
    """An older Atlas keeps a non-date `release_date` lock ("TBA") in its legacy key, which the previous plugin
    forwarded as a date (the host refused the response) and parsed as a year (the action crashed). From contract
    C5 Atlas refuses such a lock, so the record keeps its observed day."""
    cid = atlas_api.observe(seeded.admin_token, "steamlike", "D-4", "Locked Soon", "2030-01-01")
    status, _ = atlas_api.request("PUT", f"/games/{cid}/locks/release_date", seeded.admin_token, {"value": "TBA"})
    if atlas_dates(atlas_api, seeded):
        assert status == 400
        assert details(plugin, cid)["release_date"] == "2030-01-01"
        return
    assert status == 200 and atlas_view(atlas_api, seeded, cid).get("release_date") == "TBA"
    meta = details(plugin, cid)
    assert not {"release_date", "first_release", "year"} & set(meta) and meta["title"] == "Locked Soon"
    [hit] = [c for c in plugin.search(work(query="locked soon"))["candidates"] if c["external_id"] == cid]
    assert hit["year"] is None


def test_under_an_older_declared_contract_the_same_records_send_no_1_1_20_field(plugin, gateway, atlas_api, seeded,
                                                                               monkeypatch):
    """The feature switch, against the real Atlas: a 1.1.19 declaration gets only fields a 1.1.19 host knows."""
    monkeypatch.setattr(plugin, "API_CONTRACT", (1, 1, 19))
    cid = observe_dated(atlas_api, seeded, "D-5", "Older Contract",
                        {"first": {"date": "2012-07", "precision": "month"},
                         "entries": [{"date": "2012-07", "precision": "month", "region": "ww", "category": "full"}]})
    for atlas_id in filter(None, (cid, seeded.ids["starlight"])):
        meta = details(plugin, atlas_id)
        assert not NEW_PATCH_FIELDS & set(meta), sorted(meta)
    if cid is not None:
        assert details(plugin, cid)["year"] == 2012 and "release_date" not in details(plugin, cid)


def test_platinum_is_passed_through_only_under_plugin_api_1_1_20(plugin, gateway, atlas_api, seeded, monkeypatch):
    cid = atlas_api.observe(seeded.admin_token, "steamlike", "P-1", "Platinum Peak", "2022-02-02")
    items = [{"name": "Every Summit", "tier": "platinum", "external_id": "plat"},
             {"name": "Base Camp", "tier": "bronze", "external_id": "base"}]
    status, _ = atlas_api.request("PUT", f"/games/{cid}/achievements", seeded.admin_token, {"items": items})
    if status != 200:  # an Atlas before contract C7 (so also before C5) has no platinum tier and refuses the list
        assert status in (400, 422) and not atlas_dates(atlas_api, seeded), status
        return
    served = {e["name"]: e["tier"] for e in atlas_api.ok("GET", f"/games/{cid}/achievements", seeded.read_token)["results"]}
    assert served == {"Every Summit": "platinum", "Base Camp": "bronze"}
    got, _ = catalogue(plugin, cid)
    assert {i["name"]: i.get("tier") for i in got} == {"Every Summit": "platinum", "Base Camp": "bronze"}
    monkeypatch.setattr(plugin, "API_CONTRACT", (1, 1, 19))
    older, _ = catalogue(plugin, cid)
    assert {i["name"]: i.get("tier") for i in older} == {"Every Summit": None, "Base Camp": "bronze"}
    assert [i["external_id"] for i in older] == [i["external_id"] for i in got], "the identity does not depend on it"


def test_a_merged_achievement_sends_its_other_keys_as_aliases(plugin, gateway, atlas_api, seeded, monkeypatch):
    """C2.4/C2.6: two sources list the same achievement; Atlas merges them into one entry with both keys. The
    anchor (min of the keys) is the external_id and the other key rides as an alias, so the host keeps the stored
    definition when the anchor moves."""
    cid = atlas_api.observe(seeded.admin_token, "steamlike", "AL-1", "Alias Harbor", "2023-03-03")
    atlas_api.ok("PUT", f"/games/{cid}/achievements", seeded.admin_token,
                 {"items": [{"name": "Shared Goal", "tier": "gold"}, {"name": "Curator Only"}]})
    assert atlas_api.provider_achievements(cid, "gogish", [{"name": "Shared Goal", "external_id": "G-1"}]) == 1
    rows = {e["name"]: e for e in atlas_api.ok("GET", f"/games/{cid}/achievements", seeded.read_token)["results"]}
    shared = rows["Shared Goal"]
    assert len(shared["keys"]) == 2 and shared["key"] == min(shared["keys"])
    got = {i["name"]: i for i in catalogue(plugin, cid)[0]}
    assert got["Shared Goal"]["external_id"] == shared["key"]
    assert got["Shared Goal"]["aliases"] == [k for k in shared["keys"] if k != shared["key"]]
    assert "aliases" not in got["Curator Only"]
    monkeypatch.setattr(plugin, "API_CONTRACT", (1, 1, 19))
    assert all("aliases" not in item for item in catalogue(plugin, cid)[0])


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
    # The page is cut by bytes (the stable key and the atlas.row bridge add to each entry), so it ends at or before 200.
    cursor = first["next_cursor"]
    assert cursor == str(len(first["metadata"]["achievements"])) and 0 < int(cursor) <= 200
    expected = plugin.metadata({"request": {"resource": "achievements", "cursor": cursor}, "candidate": selected(plugin, gid)})
    assert expected["metadata"]["achievements"]
    gateway.timeout = 1.5
    support.pause(live_env["container"])
    try:
        second = plugin.metadata({"request": {"resource": "achievements", "cursor": cursor},
                                  "candidate": selected(plugin, gid)})
    finally:
        support.unpause(live_env["container"])
    assert second == {"failure": {"code": "unavailable"}}
    resumed = plugin.metadata({"request": {"resource": "achievements", "cursor": cursor}, "candidate": selected(plugin, gid)})
    assert resumed == expected, "the same cursor works again once Atlas is back, with the same page"


def test_nothing_secret_is_left_in_results_or_urls(plugin, gateway, seeded):
    plugin.search(work())
    plugin.metadata({"request": {}, "candidate": selected(plugin, seeded.ids["starlight"])})
    result = plugin.media({"request": {}, "candidate": selected(plugin, seeded.ids["starlight"])})
    assert seeded.read_token not in json.dumps(result)
    assert all(seeded.read_token not in call.url for call in gateway.calls)
    assert {call.headers.get("authorization") for call in gateway.calls} == {"Bearer " + seeded.read_token}
