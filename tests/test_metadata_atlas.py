"""Atlas provider: wire shape, URL handling and certainty rules, against a faked gateway."""
import hashlib
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest

from sdk import metadata_provider as sdk

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "atl_secret_token"
GAME = {"id": "atlas:" + "a" * 26, "title": "Portal 2", "release_date": "2011-04-19",
        "description": "Co-op puzzles.", "developer": "Valve", "publisher": "Valve",
        "tags": ["Puzzle"], "features": ["Co-op"], "platforms": ["pc"],
        "provider_ids": {"steam": "620", "igdb": "72"}}


@pytest.fixture
def atlas(monkeypatch):
    directory = ROOT / "official" / "metadata-atlas"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("metadata_test_atlas", directory / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Gateway:
    def __init__(self, monkeypatch, config=None, routes=None):
        self.config = {"base_url": "https://atlas.test/", "api_token": TOKEN} if config is None else config
        self.routes = routes or {}
        self.calls = []
        monkeypatch.setattr(sdk, "request", self)

    def __call__(self, method, capability, payload=None):
        if method == "metadata_providers.configuration":
            return {"values": self.config}
        assert method == "network.request" and capability == "network.outbound"
        self.calls.append(payload)
        url = payload["url"].split("?")[0]
        for suffix, response in self.routes.items():
            if url.endswith(suffix):
                return response
        return {"status": 404, "error": "not found"}


def work(**extra):
    return {"request": {"query": "portal", "limit": 5, **extra}}


def test_registration_declares_url_as_plain_setting_and_token_as_secret(atlas):
    schema = json.loads((ROOT / "tools/schemas/metadata-registration-v1.schema.json").read_text())
    jsonschema.validate(atlas.DECLARATION, schema)
    fields = {item["key"]: item for item in atlas.DECLARATION["configuration"]}
    assert fields["base_url"]["secret"] is False
    assert fields["public_base_url"]["secret"] is False
    assert fields["api_token"].get("secret", True) is True


def test_search_maps_games_and_sends_token_only_in_authorization(atlas, monkeypatch):
    gateway = Gateway(monkeypatch, routes={"/api/v2/games": {"status": 200, "data": {"results": [GAME]}}})
    result = atlas.search(work())
    assert result["candidates"] == [{
        "provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2", "media_type": "game",
        "provider_ids": {"atlas": GAME["id"], "steam": "620", "igdb": "72"}, "year": 2011}]
    call = gateway.calls[0]
    assert call["url"].startswith("https://atlas.test/api/v2/games?q=portal&limit=5")
    assert TOKEN not in call["url"] and call["headers"]["Authorization"] == "Bearer " + TOKEN


@pytest.mark.parametrize("media_type", ["game", "anime", "movie", "tv_show"])
def test_search_sends_and_returns_the_requested_media_type(atlas, monkeypatch, media_type):
    record = {**GAME, "media_type": media_type}
    gateway = Gateway(monkeypatch, routes={"/api/v2/games": {"status": 200, "data": {"results": [record]}}})
    result = atlas.search(work(media_type=media_type))
    assert result["candidates"][0]["media_type"] == media_type
    assert "type=" + media_type in gateway.calls[0]["url"]


def test_metadata_by_atlas_id_matches_response_schema(atlas, monkeypatch):
    Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": GAME}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2"}
    result = atlas.metadata({"request": {}, "candidate": selected})
    schema = json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text())
    jsonschema.validate(result, schema)
    assert result["metadata"]["developer"] == "Valve" and result["metadata"]["year"] == 2011
    assert result["metadata"]["provider_ids"] == {"atlas": GAME["id"], "steam": "620", "igdb": "72"}
    assert result["metadata"]["links"] == [{"label": "Atlas record", "url": "https://atlas.test/game/" + GAME["id"]}]


def test_unknown_or_malformed_id_returns_nothing_not_failure(atlas, monkeypatch):
    gateway = Gateway(monkeypatch)
    missing = {"provider": atlas.PROVIDER_ID, "external_id": "atlas:" + "b" * 26, "title": "x"}
    assert atlas.metadata({"request": {}, "candidate": missing}) == {}
    hostile = {"provider": atlas.PROVIDER_ID, "external_id": "../../admin/tokens", "title": "x"}
    assert atlas.metadata({"request": {}, "candidate": hostile}) == {}
    assert len(gateway.calls) == 1  # the hostile id never reached the network


@pytest.mark.parametrize("method, accepted", [("crosswalk", True), ("exact", True), ("fuzzy", False), ("none", False)])
def test_identity_lookup_only_accepts_certain_matches(atlas, monkeypatch, method, accepted):
    result = {"results": [{"canonical_id": GAME["id"], "method": method, "game": GAME}]}
    gateway = Gateway(monkeypatch, routes={"/resolve": {"status": 200, "data": result}})
    selected = {"provider": "official.metadata-steam.steam", "title": "Portal 2", "year": 2011,
                "provider_ids": {"steam": "620", "Bad Key!": "x"}}
    out = atlas.metadata({"request": {}, "candidate": selected})
    assert bool(out) is accepted
    body = gateway.calls[0]["body"]
    assert gateway.calls[0]["method"] == "POST"
    assert body["items"][0]["provider_ids"] == {"steam": "620"}


@pytest.mark.parametrize("url", ["", "ftp://atlas.test", "https://user:pw@atlas.test", "https://atlas.test/?x=1",
                                 "https://atlas.test/#f", "atlas.test", "https://"])
def test_bad_server_urls_are_rejected_before_any_request(atlas, monkeypatch, url):
    gateway = Gateway(monkeypatch, config={"base_url": url, "api_token": TOKEN})
    assert atlas.search(work()) == {"failure": {"code": "invalid_configuration"}}
    assert gateway.calls == []


def test_path_prefix_and_trailing_slash_are_supported(atlas, monkeypatch):
    gateway = Gateway(monkeypatch, config={"base_url": "http://192.168.1.20:8000/atlas/", "api_token": TOKEN},
                      routes={"/games": {"status": 200, "data": {"results": []}}})
    assert atlas.search(work()) == {"candidates": []}
    assert gateway.calls[0]["url"].startswith("http://192.168.1.20:8000/atlas/api/v2/games?")


def test_public_atlas_url_is_used_for_images_and_record_links(atlas, monkeypatch):
    digest = "a" * 64
    public_url = "http://127.0.0.1:28080"
    routes = {
        "/games/" + GAME["id"]: {"status": 200, "data": GAME},
        "/games/" + GAME["id"] + "/artwork": {"status": 200, "data": {"results": [
            {"kind": "key_art", "media_url": f"/api/v2/media/{digest}"}
        ]}},
        "/games/" + GAME["id"] + "/achievements": {"status": 200, "data": {
            "results": [{"id": "atlas-achievement", "name": "First", "icon_url": f"/api/v2/media/{digest}"}]
        }},
    }
    gateway = Gateway(
        monkeypatch,
        config={
            "base_url": "http://atlas:8000",
            "public_base_url": public_url,
            "api_token": TOKEN,
        },
        routes=routes,
    )
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": GAME["title"]}

    metadata = atlas.metadata({"request": {}, "candidate": selected})["metadata"]
    media = atlas.media({"request": {}, "candidate": selected})["assets"][0]
    achievements = atlas.metadata({"request": {"resource": "achievements"}, "candidate": selected})

    assert metadata["links"][0]["url"].startswith(public_url + "/game/")
    assert media["url"] == f"{public_url}/media/{digest}"
    assert achievements["metadata"]["achievements"][0]["icon_url"] == f"{public_url}/media/{digest}"
    assert all(call["url"].startswith("http://atlas:8000/api/v2/") for call in gateway.calls)


def test_public_atlas_url_defaults_to_api_url(atlas, monkeypatch):
    Gateway(monkeypatch, config={"base_url": "https://atlas.test/", "api_token": TOKEN})
    assert atlas.public_base_url() == "https://atlas.test"


def test_missing_configuration_and_rejected_token_are_typed(atlas, monkeypatch):
    Gateway(monkeypatch, config={})
    assert atlas.search(work())["failure"]["code"] == "not_configured"
    Gateway(monkeypatch, routes={"/games": {"status": 401, "error": "unauthorized"}})
    assert atlas.search(work())["failure"]["code"] == "invalid_configuration"
    Gateway(monkeypatch, routes={"/games": {"status": 429, "retry_after_seconds": 30}})
    assert atlas.search(work())["failure"] == {"code": "rate_limited", "retry_after_seconds": 30}
    Gateway(monkeypatch, routes={"/games": {"status": 200, "data": [1, 2]}})
    assert atlas.search(work())["failure"]["code"] == "invalid_response"


def test_health_validates_url_and_token(atlas, monkeypatch):
    Gateway(monkeypatch, routes={"/games": {"status": 200, "data": {"results": []}}})
    assert atlas.health(work()) == {"health": "healthy"}
    Gateway(monkeypatch, routes={"/games": {"status": 401, "error": "no"}})
    assert atlas.health(work())["failure"]["code"] == "invalid_configuration"


def test_media_lists_only_cached_artwork_as_public_links(atlas, monkeypatch):
    digest = "a" * 64
    art = {"results": [
        {"kind": "key_art", "media_url": f"/api/v2/media/{digest}", "width": 600, "height": 900},
        {"kind": "screenshot", "media_url": None, "url": "https://provider.test/s.jpg"},  # not cached: skipped
        {"kind": "weird", "media_url": f"/api/v2/media/{'b' * 64}"},
        {"kind": "hero", "media_url": "/api/v2/media/../../etc/passwd"}]}
    gateway = Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": GAME},
                                           "/games/" + GAME["id"] + "/artwork": {"status": 200, "data": art}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2"}
    out = atlas.media({"request": {}, "candidate": selected})
    assert out == {"assets": [{"kind": "key_art", "url": f"https://atlas.test/media/{digest}", "priority": 0,
                               "width": 600, "height": 900}]}
    schema = json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text())
    jsonschema.validate(out, schema)
    assert all("provider.test" not in call["url"] for call in gateway.calls)


def test_media_without_a_certain_match_returns_no_assets(atlas, monkeypatch):
    Gateway(monkeypatch, routes={"/resolve": {"status": 200, "data": {"results": [{"method": "fuzzy", "game": GAME}]}}})
    out = atlas.media({"request": {}, "candidate": {"provider": "x", "title": "Portal 2", "year": 2011}})
    assert out == {"assets": []}


@pytest.mark.parametrize(("media_type", "fields", "expected"), [
    ("movie", {"developer": "Greta Gerwig", "publisher": "LuckyChap",
                "custom": {"runtime_minutes": 114, "writer": ["Greta Gerwig", "Noah Baumbach"],
                           "production_countries": ["United States"], "tagline": "This Barbie is a film."}},
     {"director": "Greta Gerwig", "studios": ["LuckyChap"], "runtime_minutes": 114,
      "writer": "Greta Gerwig, Noah Baumbach", "countries": ["United States"],
      "custom": {"tagline": "This Barbie is a film."}}),
    ("anime", {"developer": "Bones", "series": "My Hero Academia", "platforms": ["TV"],
                "features": ["Superhero"], "custom": {"format": "TV", "episode_count": 13,
                    "status": "Finished", "source_material": "Manga"}},
     {"studios": ["Bones"], "format": "TV", "episode_count": 13, "tags": ["Puzzle", "Superhero"],
      "custom": {"status": "Finished", "source_material": "Manga", "franchise": "My Hero Academia"}}),
    ("tv_show", {"developer": "Jesse Armstrong", "publisher": "HBO", "series": "Succession",
                  "custom": {"episode_count": 39, "season_count": 4, "episode_runtime_minutes": 60,
                             "status": "Ended"}},
     {"creators": ["Jesse Armstrong"], "episode_count": 39, "episode_runtime_minutes": 60,
      "custom": {"season_count": 4, "status": "Ended", "network": "HBO", "franchise": "Succession"}}),
])
def test_media_fields_map_to_the_app_contract(atlas, monkeypatch, media_type, fields, expected):
    record = {**GAME, "media_type": media_type, **fields}
    Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": record}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": GAME["title"],
                "media_type": media_type}
    result = atlas.metadata({"request": {}, "candidate": selected})
    schema = json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text())
    jsonschema.validate(result, schema)
    data = result["metadata"]
    for key, value in expected.items():
        assert data[key] == value
    assert "developer" not in data and "publisher" not in data


@pytest.mark.parametrize("media_type", ["anime", "movie", "tv_show"])
def test_media_key_art_becomes_a_poster_for_non_games(atlas, monkeypatch, media_type):
    digest = "e" * 64
    record = {**GAME, "media_type": media_type}
    routes = {"/games/" + GAME["id"]: {"status": 200, "data": record},
              "/games/" + GAME["id"] + "/artwork": {"status": 200, "data": {"results": [
                  {"kind": "key_art", "media_url": f"/api/v2/media/{digest}", "width": 600, "height": 900}]}}}
    Gateway(monkeypatch, routes=routes)
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": GAME["title"],
                "media_type": media_type}
    assert atlas.media({"request": {}, "candidate": selected}) == {"assets": [
        {"kind": "poster", "url": f"https://atlas.test/media/{digest}", "priority": 0, "width": 600, "height": 900}]}


def test_cross_type_identity_is_rejected_and_achievements_are_game_only(atlas, monkeypatch):
    record = {**GAME, "media_type": "game"}
    gateway = Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": record}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": GAME["title"],
                "media_type": "movie"}
    assert atlas.metadata({"request": {}, "candidate": selected}) == {}
    assert atlas.metadata({"request": {"resource": "achievements"}, "candidate": selected}) == {}
    assert len(gateway.calls) == 2  # neither path requests the game achievement catalogue


def test_richer_atlas_fields_are_forwarded_and_validated_against_the_host_schema(atlas, monkeypatch):
    rich = {**GAME, "genres": ["Puzzle", "puzzle", "Platformer"], "themes": ["Sci-fi"], "languages": ["English"],
            "aliases": ["Portal Two", "Portal 2", ""], "age_rating": "PEGI 12", "website": "https://thinkwithportals.com",
            "critic_score": 95, "user_score": 90}
    Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": rich}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2"}
    result = atlas.metadata({"request": {}, "candidate": selected})
    jsonschema.validate(result, json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text()))
    data = result["metadata"]
    assert data["genres"] == ["Puzzle", "Platformer"] and data["tags"] == ["Puzzle", "Sci-fi"]
    assert data["languages"] == ["English"] and data["alternate_titles"] == ["Portal Two"]
    assert data["age_rating"] == "PEGI 12" and data["scores"] == {"critic": 95, "user": 90}
    assert data["links"] == [
        {"label": "Atlas record", "url": "https://atlas.test/game/" + GAME["id"]},
        {"label": "Website", "url": "https://thinkwithportals.com"},
    ]


@pytest.mark.parametrize("hostile", [
    {"genres": "Puzzle", "languages": [1, None], "aliases": {"a": 1}, "age_rating": 12, "website": "javascript:alert(1)",
     "critic_score": "95", "user_score": True},
    {"website": "https://evil.test/a b", "critic_score": 101, "user_score": -1, "genres": ["x" * 500]},
])
def test_malformed_optional_fields_are_dropped_not_forwarded(atlas, monkeypatch, hostile):
    Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": {**GAME, **hostile}}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2"}
    result = atlas.metadata({"request": {}, "candidate": selected})
    jsonschema.validate(result, json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text()))
    for key in ("genres", "languages", "alternate_titles", "age_rating", "scores"):
        assert key not in result["metadata"], key
    assert result["metadata"]["links"] == [
        {"label": "Atlas record", "url": "https://atlas.test/game/" + GAME["id"]}
    ]


def test_atlas_multiplayer_fields_are_forwarded_and_validated_against_the_host_schema(atlas, monkeypatch):
    rich = {**GAME, "custom": {"players_min": 1, "players_max": 4, "crossplay": "partial"}}
    Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": rich}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2"}
    result = atlas.metadata({"request": {}, "candidate": selected})
    jsonschema.validate(result, json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text()))
    assert (result["metadata"]["players_min"], result["metadata"]["players_max"]) == (1, 4)
    assert result["metadata"]["crossplay"] == "partial"


@pytest.mark.parametrize("custom, expected", [
    ({}, {}),
    ({"players_max": 4}, {"players_max": 4}),
    ({"players_min": 5, "players_max": 2}, {}),
    ({"players_min": 1, "players_max": 64}, {"players_min": 1}),
    ({"players_min": "1", "players_max": True, "crossplay": "maybe"}, {}),
    ({"crossplay": "no"}, {"crossplay": "no"}),
])
def test_invalid_or_unknown_multiplayer_values_are_left_unset(atlas, custom, expected):
    patch = atlas.patch({**GAME, "custom": custom})
    assert {k: patch[k] for k in ("players_min", "players_max", "crossplay") if k in patch} == expected


def test_other_atlas_custom_fields_are_forwarded_as_bounded_provider_values(atlas, monkeypatch):
    rich = {**GAME, "custom": {"players_max": 4, "difficulty": "hard", "runtime_min": 90, "story": True,
                               "modes": ["Co-op", "PvP"], "Bad Key": "x", "empty": "", "nested": {"a": 1},
                               "long": "y" * 501, "ratio": 1.5}}
    Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": rich}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2"}
    result = atlas.metadata({"request": {}, "candidate": selected})
    jsonschema.validate(result, json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text()))
    assert result["metadata"]["custom"] == {"difficulty": "hard", "runtime_min": 90, "story": True,
                                            "modes": ["Co-op", "PvP"], "ratio": 1.5}
    assert result["metadata"]["players_max"] == 4  # typed field, not duplicated in custom


def test_no_custom_fields_means_no_custom_key(atlas):
    assert "custom" not in atlas.patch({**GAME, "custom": {}}) and "custom" not in atlas.patch(GAME)


DIGEST = "c" * 64
ACHIEVEMENTS = {"results": [
    {"id": "ach_1", "name": "Wake Up Call", "description": "Finish chapter 1", "global_percent": 40.5, "hidden": False,
     "icon_url": f"/api/v2/media/{DIGEST}", "locked_icon_url": f"/api/v2/media/{'d' * 64}", "kind": "missable",
     "tier": "gold", "points": 50, "external_ids": {"steam": "ACH_1", "Bad Key": "x"}},
    {"id": "ach_2", "name": "Hidden achievement", "description": "", "hidden": True, "icon_url": None},
    {"id": "ach_3", "name": "", "description": "unnamed is skipped"},
    {"id": "ach_1", "name": "Duplicate id is skipped", "global_percent": 400, "icon_url": "javascript:alert(1)"},
    {"name": "No id is skipped"},
]}


KEY_A, KEY_B = "ak1:" + "a" * 26, "ak1:" + "b" * 26


def _catalogue(atlas, monkeypatch, results):
    Gateway(monkeypatch, routes={"/games/" + GAME["id"] + "/achievements": {"status": 200, "data": {"results": results}},
                                 "/games/" + GAME["id"]: {"status": 200, "data": GAME}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2"}
    result = atlas.metadata({"request": {"resource": "achievements"}, "candidate": selected})
    jsonschema.validate(result, json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text()))
    return result["metadata"]["achievements"]


def test_the_stable_atlas_key_is_the_external_id_and_the_row_id_rides_as_the_atlas_row_bridge(atlas, monkeypatch):
    items = _catalogue(atlas, monkeypatch, [
        {"id": "01JROW1", "key": KEY_A, "keys": [KEY_A], "name": "Keyed", "external_ids": {"steam": "ACH_1"}},
        {"id": "01JROW2", "key": KEY_B, "name": "Hidden achievement", "hidden": True, "external_ids": {}}])
    assert [i["external_id"] for i in items] == [KEY_A, KEY_B]
    assert items[0]["source_ids"] == {"atlas.row": "01JROW1", "steam": "ACH_1"}
    assert items[1]["source_ids"] == {"atlas.row": "01JROW2"} and items[1]["hidden"] is True
    assert set(items[0]) <= {"name", "external_id", "hidden", "description", "global_percent", "icon_url",
                             "locked_icon_url", "kind", "tier", "points", "source_ids"}  # no field the 1.1.19 host rejects


def test_an_atlas_without_keys_falls_back_to_the_row_id(atlas, monkeypatch):
    items = _catalogue(atlas, monkeypatch, [{"id": "01JROW1", "name": "Old Atlas"}])
    assert items[0]["external_id"] == "01JROW1" and items[0]["source_ids"] == {"atlas.row": "01JROW1"}


@pytest.mark.parametrize("bad", ["ak1:short", "ak2:" + "a" * 26, "ak1:" + "A" * 26, "ak1:" + "1" * 26, "", None, 7, ["ak1"]])
def test_a_malformed_key_is_never_forwarded_as_the_identity(atlas, monkeypatch, bad):
    items = _catalogue(atlas, monkeypatch, [{"id": "01JROW1", "key": bad, "name": "Bad key"}])
    assert items[0]["external_id"] == "01JROW1"


def test_the_bridge_keeps_its_slot_when_an_entry_carries_eight_provider_ids(atlas, monkeypatch):
    ids = {f"src{n}": f"v{n}" for n in range(12)}
    items = _catalogue(atlas, monkeypatch, [{"id": "01JROW1", "key": KEY_A, "name": "Crowded", "external_ids": ids}])
    assert len(items[0]["source_ids"]) == 8 and items[0]["source_ids"]["atlas.row"] == "01JROW1"


def test_entries_sharing_a_key_are_delivered_once(atlas, monkeypatch):
    items = _catalogue(atlas, monkeypatch, [{"id": "01JROW1", "key": KEY_A, "name": "First"},
                                            {"id": "01JROW9", "key": KEY_A, "name": "Same key, other row"}])
    assert [i["name"] for i in items] == ["First"]


def test_declares_the_achievements_resource(atlas):
    assert atlas.DECLARATION["metadata_resources"] == ["entity", "achievements"]


def test_achievements_resource_returns_the_catalogue_validated_against_the_host_schema(atlas, monkeypatch):
    Gateway(monkeypatch, routes={"/games/" + GAME["id"] + "/achievements": {"status": 200, "data": ACHIEVEMENTS},
                                 "/games/" + GAME["id"]: {"status": 200, "data": GAME}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2"}
    result = atlas.metadata({"request": {"resource": "achievements"}, "candidate": selected})
    jsonschema.validate(result, json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text()))
    items = result["metadata"]["achievements"]
    assert [i["external_id"] for i in items] == ["ach_1", "ach_2"]
    assert items[0] == {"name": "Wake Up Call", "external_id": "ach_1", "hidden": False,
                        "description": "Finish chapter 1", "global_percent": 40.5,
                        "icon_url": f"https://atlas.test/media/{DIGEST}",  # Atlas's public path, not the token-gated one
                        "locked_icon_url": "https://atlas.test/media/" + "d" * 64, "kind": "missable", "tier": "gold",
                        "points": 50, "source_ids": {"atlas.row": "ach_1", "steam": "ACH_1"}}
    assert items[1]["hidden"] is True and "icon_url" not in items[1]
    assert "title" not in result["metadata"]  # the achievements resource carries only the catalogue


def test_achievements_resolve_from_a_linked_steam_identity(atlas, monkeypatch):
    result = {"results": [{"canonical_id": GAME["id"], "method": "crosswalk", "game": GAME}]}
    gateway = Gateway(monkeypatch, routes={
        "/resolve": {"status": 200, "data": result},
        "/games/" + GAME["id"] + "/achievements": {"status": 200, "data": ACHIEVEMENTS},
    })
    selected = {
        "provider": "official.metadata-steam.steam", "external_id": "620", "title": "Portal 2",
        "year": 2011, "media_type": "game", "provider_ids": {"steam": "620"},
    }
    response = atlas.metadata({"request": {"resource": "achievements"}, "candidate": selected})
    assert response["metadata"]["achievements"][0]["external_id"] == "ach_1"
    resolve_call = next(call for call in gateway.calls if call["url"].endswith("/resolve"))
    assert resolve_call["body"]["items"][0]["media_type"] == "game"
    assert resolve_call["body"]["items"][0]["provider_ids"] == {"steam": "620"}


def test_games_without_achievements_return_nothing_rather_than_an_error(atlas, monkeypatch):
    Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": GAME}})  # no achievements route: 404
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2"}
    assert atlas.metadata({"request": {"resource": "achievements"}, "candidate": selected}) == {}


def _entry(number):
    return {"id": f"ach_{number}", "name": f"Achievement {number}", "hidden": False, "icon_url": None}


class PagedAchievements(Gateway):
    """Atlas achievements with limit/offset/next_offset (Atlas v2 paging, unpaged when asked not to)."""

    def __init__(self, monkeypatch, entries, paging=True, fail_at=None):
        super().__init__(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": GAME}})
        self.entries, self.paging, self.fail_at = entries, paging, fail_at

    def __call__(self, method, capability, payload=None):
        if method == "network.request" and "/achievements" in payload["url"]:
            from urllib.parse import parse_qs, urlsplit
            self.calls.append(payload)
            query = parse_qs(urlsplit(payload["url"]).query)
            if not self.paging:  # a host/Atlas without paging ignores the parameters
                return {"status": 200, "data": {"results": self.entries}}
            limit, offset = int(query["limit"][0]), int(query["offset"][0])
            if offset == self.fail_at:
                return {"status": 503}
            page = self.entries[offset:offset + limit]
            end = offset + len(page)
            return {"status": 200, "data": {"results": page, "total": len(self.entries),
                                            "next_offset": end if end < len(self.entries) else None}}
        return super().__call__(method, capability, payload)


def _achievements(atlas):
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2", "media_type": "game"}
    return atlas.metadata({"request": {"resource": "achievements"}, "candidate": selected})


def _delivered(atlas, cursor=None):
    """Follow next_cursor like the host and merge pages by external_id (host PR 447 semantics).

    Returns (merged items, page responses); a failing page is returned as-is."""
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2", "media_type": "game"}
    merged, pages, seen = {}, [], set()
    while True:
        request = {"resource": "achievements", **({"cursor": cursor} if cursor else {})}
        response = atlas.metadata({"request": request, "candidate": selected})
        if "failure" in response:
            return response
        pages.append(response)
        for item in response.get("metadata", {}).get("achievements", []):
            merged[item["external_id"]] = item
        cursor = response.get("next_cursor")
        if cursor is None:
            return list(merged.values()), pages
        assert cursor not in seen
        seen.add(cursor)


def _achievement_calls(gateway):
    from urllib.parse import parse_qs, urlsplit
    return [parse_qs(urlsplit(call["url"]).query) for call in gateway.calls if "/achievements" in call["url"]]


def test_large_catalogues_are_read_in_pages_of_200_and_deduplicated(atlas, monkeypatch):
    entries = [_entry(number) for number in range(450)]
    entries[210] = {**entries[10]}  # a boundary shift between pages repeats an id
    gateway = PagedAchievements(monkeypatch, entries)
    items, pages = _delivered(atlas)
    assert [item["external_id"] for item in items] == [f"ach_{n}" for n in range(450) if n != 210]
    assert len(pages) == 3 and "next_cursor" not in pages[-1]
    assert [call["offset"] for call in _achievement_calls(gateway)] == [["0"], ["200"], ["400"]]
    assert {call["limit"][0] for call in _achievement_calls(gateway)} == {"200"}


def test_a_server_without_paging_returns_everything_in_one_response(atlas, monkeypatch):
    gateway = PagedAchievements(monkeypatch, [_entry(number) for number in range(120)], paging=False)
    items, pages = _delivered(atlas)
    assert len(items) == 120 and len(pages) == 1 and len(_achievement_calls(gateway)) == 1


def test_a_failing_later_page_is_an_error_not_a_truncated_catalogue(atlas, monkeypatch):
    PagedAchievements(monkeypatch, [_entry(number) for number in range(450)], fail_at=200)
    assert _delivered(atlas) == {"failure": {"code": "unavailable"}}


def test_a_cursor_that_does_not_advance_cannot_loop_and_the_forwarding_cap_holds(atlas, monkeypatch):
    class Stuck(PagedAchievements):
        def __call__(self, method, capability, payload=None):
            if method == "network.request" and "/achievements" in payload["url"]:
                self.calls.append(payload)
                return {"status": 200, "data": {"results": [_entry(len(self.calls))], "next_offset": 0}}
            return super().__call__(method, capability, payload)

    gateway = Stuck(monkeypatch, [])
    items, pages = _delivered(atlas)
    assert len(items) == 1 and len(pages) == 1 and len(_achievement_calls(gateway)) == 1
    big = PagedAchievements(monkeypatch, [_entry(number) for number in range(2500)])
    items, pages = _delivered(atlas)
    assert len(items) == 2000 and "next_cursor" not in pages[-1]
    assert len(_achievement_calls(big)) == 10


def _realistic(number):
    digest = lambda salt: hashlib.sha256(f"{salt}{number}".encode()).hexdigest()
    return {"id": f"ach_{number:05d}_{digest('i')[:12]}", "name": f"Achievement number {number}: a typical title",
            "description": "Complete the objective described here without being defeated. " * 3,
            "hidden": number % 17 == 0, "global_percent": 12.345, "kind": "progression", "tier": "gold",
            "points": 25, "icon_url": f"/api/v2/media/{digest('a')}", "locked_icon_url": f"/api/v2/media/{digest('b')}",
            "external_ids": {"steam": f"ACH_SOMETHING_{number}", "retroachievements": str(number)}}


@pytest.mark.parametrize("count", [450, 2000])
def test_realistic_catalogues_stay_under_the_runtime_output_limit_and_arrive_exactly_once(atlas, monkeypatch, count):
    PagedAchievements(monkeypatch, [_realistic(number) for number in range(count)])
    items, pages = _delivered(atlas)
    assert len(pages) > 1  # one response could never carry this many entries
    for page in pages:
        assert len(json.dumps(page).encode("utf-8")) <= 56 * 1024 < 64 * 1024
    assert [item["external_id"] for item in items] == [_realistic(n)["id"] for n in range(count)]
    delivered = [item["external_id"] for page in pages for item in page["metadata"]["achievements"]]
    assert len(delivered) == len(set(delivered)) == count  # no repeat or gap across the pages
    assert all("next_cursor" in page for page in pages[:-1]) and "next_cursor" not in pages[-1]


def test_an_invalid_achievement_cursor_is_rejected_without_a_request(atlas, monkeypatch):
    gateway = PagedAchievements(monkeypatch, [_entry(1)])
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2", "media_type": "game"}
    for bad in ("-1", "abc", "1.5"):
        response = atlas.metadata({"request": {"resource": "achievements", "cursor": bad}, "candidate": selected})
        assert response == {"failure": {"code": "invalid_response"}}
    assert _achievement_calls(gateway) == []
