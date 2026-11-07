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
                             "locked_icon_url", "kind", "tier", "points", "source_ids"}  # `keys` names only the anchor: no aliases


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


# --- /resolve semantics (contract C4.3): conflicts and ambiguity are never an identity -----------------------------

RESOLVE_FIXTURE = ROOT / "tests" / "fixtures" / "atlas" / "resolve-contract-v1.json"
STEAM_ONLY = {"provider": "official.metadata-steam.steam", "title": "Portal 2", "year": 2011,
              "provider_ids": {"steam": "620"}}
OTHER = "atlas:" + "b" * 26


def resolved(reason, method, *, canonical=GAME["id"], game=GAME, **extra):
    row = {"canonical_id": canonical, "method": method, "confidence": 0.9, "candidates": [],
           "assigned": canonical is not None, "reason": reason, "tier": "id", "redirected_from": None,
           "matched_keys": [], "conflict": None, "game": game}
    return {"results": [{**row, **extra}]}


def lookup(atlas, monkeypatch, data, selected=STEAM_ONLY):
    gateway = Gateway(monkeypatch, routes={"/resolve": {"status": 200, "data": data}})
    return atlas.metadata({"request": {}, "candidate": selected}), gateway


@pytest.mark.parametrize("reason, method", [("id", "crosswalk"), ("redirect", "crosswalk"), ("crosswalk", "crosswalk"),
                                            ("exact", "exact")])
def test_resolve_adopts_only_the_reasons_atlas_calls_safe(atlas, monkeypatch, reason, method):
    out, _ = lookup(atlas, monkeypatch, resolved(reason, method))
    assert out["metadata"]["provider_ids"]["atlas"] == GAME["id"]


@pytest.mark.parametrize("reason, method", [
    ("conflict", "none"), ("type_mismatch", "none"), ("ambiguous", "none"), ("none", "none"), ("fuzzy", "fuzzy"),
    ("a_reason_from_the_future", "exact"),
    # a reason that is not adoptable wins over a method that looks confident
    ("conflict", "crosswalk"), ("ambiguous", "exact"), ("type_mismatch", "crosswalk")])
def test_resolve_never_adopts_conflict_ambiguous_or_cross_type_answers(atlas, monkeypatch, reason, method):
    out, _ = lookup(atlas, monkeypatch, resolved(reason, method))
    assert out == {}


def test_a_conflict_is_logged_without_an_identity_a_failure_or_a_custom_marker(atlas, monkeypatch, capsys):
    conflict = {"canonical_ids": [GAME["id"], OTHER], "own": GAME["id"], "review_id": "01JREVIEW"}
    data = resolved("conflict", "none", canonical=None, game=None, conflict=conflict,
                    candidates=[{"id": GAME["id"], "score": 1.0}, {"id": OTHER, "score": 1.0}])
    out, gateway = lookup(atlas, monkeypatch, data)
    assert out == {}  # no failure code, no patch, nothing in `custom`
    assert atlas.media({"request": {}, "candidate": STEAM_ONLY}) == {"assets": []}
    logged = capsys.readouterr().err
    assert GAME["id"] in logged and OTHER in logged and "conflicting identifiers" in logged
    assert TOKEN not in logged and "Portal 2" not in logged
    assert all(call["url"].endswith("/resolve") for call in gateway.calls)


def test_a_conflict_hint_never_leaks_into_the_patch_even_if_atlas_still_sends_the_record(atlas, monkeypatch):
    """The hint `conflict.own` is for a curator; a client that adopted it would repeat the bug in plugins#70."""
    conflict = {"canonical_ids": [GAME["id"], OTHER], "own": GAME["id"], "review_id": None}
    out, _ = lookup(atlas, monkeypatch, resolved("crosswalk", "crosswalk", conflict=conflict))
    assert out == {}


@pytest.mark.parametrize("answer, accepted", [
    ({"method": "crosswalk"}, True),
    ({"method": "exact"}, True),
    ({"method": "fuzzy"}, False),
    ({"method": "none"}, False),
    ({"method": "crosswalk", "conflict": {"canonical_ids": [GAME["id"], OTHER]}}, False),
    ({"method": "crosswalk", "conflict": ["x"]}, False),
])
def test_an_atlas_without_reason_keeps_the_method_rule_and_refuses_a_conflict_key(atlas, monkeypatch, answer, accepted):
    out, _ = lookup(atlas, monkeypatch, {"results": [{"canonical_id": GAME["id"], **answer, "game": GAME}]})
    assert bool(out) is accepted


def test_a_redirect_is_followed_to_the_live_record(atlas, monkeypatch):
    live = {**GAME, "id": OTHER}
    data = resolved("redirect", "crosswalk", canonical=OTHER, game=live, redirected_from=GAME["id"])
    out, _ = lookup(atlas, monkeypatch, data)
    assert out["metadata"]["provider_ids"]["atlas"] == OTHER
    assert out["metadata"]["links"][0]["url"].endswith("/game/" + OTHER)


@pytest.mark.parametrize("game, canonical", [
    ({**GAME, "id": OTHER}, GAME["id"]),             # the record is not the one Atlas named
    ({**GAME, "id": "../../admin"}, None),            # not an Atlas id
    ({k: v for k, v in GAME.items() if k != "id"}, GAME["id"]),
    (None, GAME["id"]),
])
def test_a_resolved_record_must_be_the_live_record_atlas_named(atlas, monkeypatch, game, canonical):
    out, _ = lookup(atlas, monkeypatch, resolved("redirect", "crosswalk", canonical=canonical, game=game))
    assert out == {}


@pytest.mark.parametrize("year, sent", [(2011, "2011"), (1999, "1999")])
def test_resolve_sends_the_year_alone_as_the_release_date(atlas, monkeypatch, year, sent):
    _, gateway = lookup(atlas, monkeypatch, resolved("exact", "exact"), {**STEAM_ONLY, "year": year})
    assert gateway.calls[0]["body"]["items"][0]["release_date"] == sent


def test_resolve_without_a_year_sends_no_release_date(atlas, monkeypatch):
    selected = {k: v for k, v in STEAM_ONLY.items() if k != "year"}
    _, gateway = lookup(atlas, monkeypatch, resolved("crosswalk", "crosswalk"), selected)
    assert "release_date" not in gateway.calls[0]["body"]["items"][0]


@pytest.mark.parametrize("data", [{}, {"results": []}, {"results": [None]}, {"results": "x"}, {"results": [[]]}])
def test_resolve_survives_an_empty_or_malformed_answer(atlas, monkeypatch, data):
    out, _ = lookup(atlas, monkeypatch, data)
    assert out == {}


def test_a_merged_atlas_id_is_served_under_the_live_id(atlas, monkeypatch):
    """GET /games/{old} returns the live record with `redirected_from` (contract C4.2)."""
    live = {**GAME, "id": OTHER, "redirected_from": GAME["id"]}
    Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": live}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2",
                "provider_ids": {"atlas": GAME["id"], "steam": "620"}}
    out = atlas.metadata({"request": {}, "candidate": selected})["metadata"]
    assert out["provider_ids"] == {"atlas": OTHER, "steam": "620", "igdb": "72"}
    assert out["links"][0]["url"] == "https://atlas.test/game/" + OTHER
    assert "redirected_from" not in out and GAME["id"] not in json.dumps(out)


def test_artwork_and_achievements_of_a_merged_id_use_the_live_id(atlas, monkeypatch):
    live = {**GAME, "id": OTHER, "redirected_from": GAME["id"]}
    gateway = Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": live},
                                           "/artwork": {"status": 200, "data": {"results": []}},
                                           "/achievements": {"status": 404}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2"}
    atlas.media({"request": {}, "candidate": selected})
    atlas.metadata({"request": {"resource": "achievements"}, "candidate": selected})
    urls = [call["url"] for call in gateway.calls]
    assert any(url.endswith("/games/" + OTHER + "/artwork") for url in urls)
    assert any("/games/" + OTHER + "/achievements" in url for url in urls)


@pytest.mark.parametrize("live_id", ["../../admin", "", None, 7, "atlas:short"])
def test_a_redirect_that_does_not_end_on_an_atlas_id_is_refused(atlas, monkeypatch, live_id):
    Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {
        "status": 200, "data": {**GAME, "id": live_id, "redirected_from": GAME["id"]}}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2"}
    assert atlas.metadata({"request": {}, "candidate": selected}) == {}


def test_an_unredirected_record_is_served_as_before(atlas, monkeypatch):
    Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": {**GAME, "redirected_from": None}}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": GAME["id"], "title": "Portal 2"}
    assert atlas.metadata({"request": {}, "candidate": selected})["metadata"]["provider_ids"]["atlas"] == GAME["id"]


# --- the vendored shared fixture (contract C4.5) -------------------------------------------------------------------

SPEC = json.loads(RESOLVE_FIXTURE.read_text(encoding="utf-8"))
SAFE = {"id", "redirect", "crosswalk", "exact"}


def test_the_vendored_resolve_fixture_matches_its_pinned_digest():
    pinned = RESOLVE_FIXTURE.with_name(RESOLVE_FIXTURE.name + ".sha256").read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(RESOLVE_FIXTURE.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == pinned
    assert SPEC["contract"] == "C4" and SPEC["version"] == 1


def fake_ids(spec):
    names = [seed["name"] for seed in spec["seeds"]]
    return {name: "atlas:" + format(index + 1, "x").rjust(26, "0") for index, name in enumerate(names)}


def substitute(value, ids):
    if isinstance(value, str) and value.startswith("$"):
        return ids[value[1:]]
    if isinstance(value, dict):
        return {k: substitute(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, ids) for v in value]
    return value


def candidate_for(request):
    """The candidate a host passes for a /resolve request in the fixture."""
    ids = dict(request.get("provider_ids") or {})
    if request.get("namespace") and request.get("external_id"):
        ids[request["namespace"]] = request["external_id"]
    out = {"provider": "official.metadata-steam.steam", "title": request.get("title"), "provider_ids": ids,
           "media_type": request.get("media_type", "game")}
    if request.get("release_date"):
        out["year"] = int(request["release_date"][:4])
    return out


def has_atlas_id(request):
    return "atlas" in {**(request.get("provider_ids") or {}), request.get("namespace", ""): 1}


@pytest.mark.parametrize("case", [c for c in SPEC["cases"] if not has_atlas_id(c["request"])], ids=lambda c: c["name"])
def test_every_fixture_case_is_adopted_exactly_when_the_contract_says_so(atlas, monkeypatch, case):
    """Replays each expected Atlas answer through the plugin: only id/redirect/crosswalk/exact become an identity.

    Requests that carry an Atlas id are looked up by id (GET), not through /resolve; the live lane covers them."""
    ids = fake_ids(SPEC)
    expect = substitute(case["expect"], ids)
    live = {**GAME, "id": expect["canonical_id"]} if expect["canonical_id"] else None
    conflict = ({"canonical_ids": expect["conflict_ids"], "own": expect["conflict_own"], "review_id": None}
                if expect["reason"] == "conflict" else None)
    answer = {"canonical_id": expect["canonical_id"], "method": expect["method"], "confidence": 0.9, "candidates": [],
              "assigned": live is not None, "reason": expect["reason"], "tier": expect["tier"],
              "redirected_from": expect.get("redirected_from"), "matched_keys": [], "conflict": conflict,
              "game": live}
    gateway = Gateway(monkeypatch, routes={"/resolve": {"status": 200, "data": {"results": [answer]}}})
    out = atlas.metadata({"request": {}, "candidate": candidate_for(substitute(case["request"], ids))})
    assert bool(out) is (expect["reason"] in SAFE), case["name"]
    if out:
        assert out["metadata"]["provider_ids"]["atlas"] == expect["canonical_id"]
    sent = gateway.calls[0]["body"]["items"][0]
    request = case["request"]
    if request.get("release_date"):
        assert sent["release_date"] == request["release_date"][:4]  # a year, never "<year>-01-01"
    assert sent["media_type"] == request.get("media_type", "game")
    assert "atlas" not in sent.get("provider_ids", {})


# --- Plugin API 1.1.20: partial and regional dates, platinum, aliases, crossplay vocabulary (C5.3, C2.6, C7) ---

RESPONSE_SCHEMA = json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text(encoding="utf-8"))
# Fields a host on Plugin API 1.1.19 or older refuses (`extra="forbid"`, and the 1.1.20 contract gate).
NEW_PATCH_FIELDS = {"first_release", "releases", "identity"}
SELECTED = {"provider": "official.metadata-atlas.atlas", "external_id": GAME["id"], "title": "Portal 2"}


def details(atlas, monkeypatch, record):
    Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": record}})
    result = atlas.metadata({"request": {}, "candidate": SELECTED})
    jsonschema.validate(result, RESPONSE_SCHEMA)
    return result["metadata"]


def older_contract(atlas, monkeypatch, version=(1, 1, 19)):
    monkeypatch.setattr(atlas, "API_CONTRACT", version)


def test_the_manifest_and_ui_declare_plugin_api_1_1_20_and_the_plugin_reads_it(atlas):
    directory = ROOT / "official" / "metadata-atlas"
    for name in ("manifest.json", "ui.json"):
        assert json.loads((directory / name).read_text(encoding="utf-8"))["api_contract_version"] == "1.1.20"
    assert atlas.declared_contract() == atlas.API_CONTRACT == (1, 1, 20) and atlas.sends_releases()


@pytest.mark.parametrize("declared, expected", [("1.1.19", (1, 1, 19)), ("1.1.20", (1, 1, 20)), ("1.2.0", (1, 2, 0)),
                                                ("1.1", None), ("1.1.x", None), ("１.1.20", None), (None, None),
                                                (1120, None), ("missing", None), ("unreadable", None)])
def test_the_declared_contract_is_read_from_the_packaged_manifest(tmp_path, monkeypatch, declared, expected):
    """A copy of the plugin next to an edited manifest: an older or unreadable declaration switches 1.1.20 off."""
    source = ROOT / "official" / "metadata-atlas"
    for name in ("plugin.py", "vocab.py"):
        (tmp_path / name).write_bytes((source / name).read_bytes())
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if declared == "missing":
        manifest.pop("api_contract_version")
    else:
        manifest["api_contract_version"] = declared
    if declared != "unreadable":
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    spec = importlib.util.spec_from_file_location("metadata_atlas_contract_copy", tmp_path / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.API_CONTRACT == expected
    assert module.sends_releases() is (expected is not None and expected >= (1, 1, 20))
    patch = module.patch({**GAME, "first_release": {"date": "2011-04", "precision": "month"},
                          "releases": [{"date": "2011-04", "precision": "month", "category": "full"}]})
    assert ("first_release" in patch) is module.sends_releases()
    assert ("releases" in patch) is module.sends_releases()


def test_a_partial_first_release_and_regional_releases_are_mapped(atlas, monkeypatch):
    record = {**GAME, "release_date": None, "release_year": 2011,
              "first_release": {"date": "2011-04", "precision": "month"},
              "releases": [{"date": "2011-04", "precision": "month", "platform": "pc", "region": "ww",
                            "category": "full"},
                           {"date": "2011", "precision": "year", "platform": "ps3", "region": "jp",
                            "edition": "Collector's Edition", "category": "full"},
                           {"date": "2010-12-01", "precision": "day", "platform": "pc", "category": "beta"}]}
    meta = details(atlas, monkeypatch, record)
    assert "release_date" not in meta, "a month is never sent as a day"
    assert meta["year"] == 2011
    assert meta["first_release"] == {"date": "2011-04", "precision": "month"}
    assert meta["releases"] == [
        {"date": "2011-04", "precision": "month", "platform": "pc", "region": "ww", "category": "full"},
        {"date": "2011", "precision": "year", "platform": "ps3", "region": "jp", "edition": "Collector's Edition",
         "category": "full"},
        {"date": "2010-12-01", "precision": "day", "platform": "pc", "category": "beta"}]


def test_a_day_first_release_travels_with_the_legacy_day(atlas, monkeypatch):
    first = {"date": "2011-04-19", "precision": "day"}
    meta = details(atlas, monkeypatch, {**GAME, "first_release": first})
    assert meta["release_date"] == "2011-04-19" and meta["first_release"] == first and meta["year"] == 2011
    # A day first release without the legacy key still fills it, so both name the same day.
    meta = details(atlas, monkeypatch, {**GAME, "release_date": None, "first_release": first})
    assert meta["release_date"] == "2011-04-19" and meta["first_release"] == first


def test_a_day_first_release_that_contradicts_the_legacy_day_is_left_out(atlas, monkeypatch):
    """The host refuses the whole response when release_date and a day first_release differ."""
    meta = details(atlas, monkeypatch, {**GAME, "first_release": {"date": "2011-04-20", "precision": "day"}})
    assert meta["release_date"] == "2011-04-19" and "first_release" not in meta


@pytest.mark.parametrize("legacy, first, year", [
    ("2011", {"date": "2011", "precision": "year"}, 2011),        # an older Atlas serves a year lock in the day key
    ("2011-04", {"date": "2011-04", "precision": "month"}, 2011),
    ("TBA", None, None),                                           # a free-text lock: no date, no year, no crash
    ("2011-02-30", None, None),                                    # not a calendar day
    ("1937-12-21", None, 1937),                                    # an old day keeps its day (and its year)
])
def test_an_older_atlas_without_first_release_is_mapped_from_the_legacy_key(atlas, monkeypatch, legacy, first, year):
    meta = details(atlas, monkeypatch, {**GAME, "release_date": legacy})
    assert meta.get("first_release") == first and meta.get("year") == year
    assert meta.get("release_date") == (legacy if legacy == "1937-12-21" else None)
    assert "releases" not in meta


def test_a_search_result_with_a_free_text_date_still_lists_the_candidate(atlas, monkeypatch):
    records = [{**GAME, "release_date": "TBA"}, {**GAME, "id": "atlas:" + "c" * 26, "release_date": None,
                                                 "first_release": {"date": "2027", "precision": "year"}}]
    Gateway(monkeypatch, routes={"/api/v2/games": {"status": 200, "data": {"results": records}}})
    result = atlas.search(work())
    jsonschema.validate(result, RESPONSE_SCHEMA)
    assert [c["year"] for c in result["candidates"]] == [None, 2027]


@pytest.mark.parametrize("first", [
    {"date": "2011-04", "precision": "day"}, {"date": "2011", "precision": "month"},
    {"date": "2011-13", "precision": "month"}, {"date": "Q3 2025", "precision": "year"},
    {"date": "2025-Q3", "precision": "quarter"}, {"date": "1949", "precision": "year"},
    {"date": "2101-01", "precision": "month"}, {"date": "1799-12-31", "precision": "day"},
    {"date": "٢٠١١", "precision": "year"}, {"date": 2011, "precision": "year"},
    {"precision": "year"}, "2011", ["2011", "year"],
])
def test_a_malformed_first_release_is_ignored_and_the_response_stays_valid(atlas, monkeypatch, first):
    meta = details(atlas, monkeypatch, {**GAME, "release_date": None, "first_release": first})
    assert "first_release" not in meta and "release_date" not in meta and "year" not in meta


def test_release_entries_are_validated_bounded_and_unique(atlas, monkeypatch):
    good = {"date": "2011-04-19", "precision": "day", "category": "full"}
    entries = [
        {**good, "platform": "PC", "region": "ww"},
        {**good, "platform": "pc", "region": "ww", "date": "2011-05-01"},      # same key as above (case-insensitive)
        {**good, "precision": "month"},                                         # precision does not match the shape
        {**good, "date": "2011-02-30"},                                         # not a calendar day
        {**good, "region": "XX"}, {**good, "region": "europe"},                 # not a C5.1 region
        {**good, "category": "soft_launch"},                                    # not in the shared vocabulary
        {**good, "platform": "p" * 129}, {**good, "edition": "e" * 101},        # too long: left out, not cut
        {**good, "platform": 64}, {**good, "edition": "\x00bad"},
        {**good, "label": "ignored extra member", "platform": "switch"},       # unknown members are not forwarded
        "2011", None,
        {"date": "2012", "precision": "year", "platform": "  Xbox   360 ", "region": "na"},
        {"date": "2013-01", "precision": "month", "platform": "ps4", "region": "eu"},
        {"date": "2014", "precision": "year", "platform": "ps5"},
        {"date": "2015", "precision": "year", "platform": "mac", "category": "port"},   # a sixth valid entry
    ]
    meta = details(atlas, monkeypatch, {**GAME, "releases": entries})
    assert meta["releases"] == [
        {**good, "platform": "PC", "region": "ww"},
        {**good, "platform": "switch"},
        {"date": "2012", "precision": "year", "platform": "Xbox 360", "region": "na", "category": "full"},
        {"date": "2013-01", "precision": "month", "platform": "ps4", "region": "eu", "category": "full"},
        {"date": "2014", "precision": "year", "platform": "ps5", "category": "full"}]
    assert len(meta["releases"]) == atlas.MAX_RELEASES == 5


@pytest.mark.parametrize("releases", [None, [], "2011", {"date": "2011"}, [{"date": "bad", "precision": "year"}]])
def test_no_usable_release_entry_means_no_releases_key(atlas, monkeypatch, releases):
    assert "releases" not in details(atlas, monkeypatch, {**GAME, "releases": releases})


def test_under_an_older_declared_contract_no_1_1_20_field_is_sent(atlas, monkeypatch):
    """Feature switch: the same Atlas record under a 1.1.19 declaration sends only what a 1.1.19 host knows."""
    older_contract(atlas, monkeypatch)
    record = {**GAME, "release_date": None, "first_release": {"date": "2011-04", "precision": "month"},
              "releases": [{"date": "2011-04", "precision": "month", "category": "full"}],
              "custom": {"crossplay": "partial"}}
    meta = details(atlas, monkeypatch, record)
    assert not NEW_PATCH_FIELDS & set(meta)
    assert meta["year"] == 2011 and "release_date" not in meta and meta["crossplay"] == "partial"
    meta = details(atlas, monkeypatch, {**GAME, "first_release": {"date": "2011-04-19", "precision": "day"}})
    assert meta["release_date"] == "2011-04-19" and not NEW_PATCH_FIELDS & set(meta)


PLATINUM_ENTRIES = [
    {"id": "01JROW1", "key": KEY_A, "keys": [KEY_A, KEY_B, KEY_A, "ak1:bad", 7, "ak1:" + "c" * 26], "name": "All of it",
     "tier": "platinum"},
    {"id": "01JROW2", "key": KEY_B, "keys": [KEY_B], "name": "First steps", "tier": "bronze"},
    {"id": "01JROW3", "key": "ak1:" + "d" * 26, "name": "Odd", "tier": "diamond"},
]


def test_platinum_and_aliases_are_sent_under_plugin_api_1_1_20(atlas, monkeypatch):
    items = _catalogue(atlas, monkeypatch, PLATINUM_ENTRIES)
    assert [(i["name"], i.get("tier")) for i in items] == [("All of it", "platinum"), ("First steps", "bronze"),
                                                          ("Odd", None)]
    assert items[0]["aliases"] == [KEY_B, "ak1:" + "c" * 26], "the other well-formed keys, once, without the anchor"
    assert "aliases" not in items[1] and "aliases" not in items[2]


def test_platinum_and_aliases_are_not_sent_under_an_older_declared_contract(atlas, monkeypatch):
    older_contract(atlas, monkeypatch)
    items = _catalogue(atlas, monkeypatch, PLATINUM_ENTRIES)
    assert [i.get("tier") for i in items] == [None, "bronze", None]
    assert all("aliases" not in item for item in items)
    assert items[0]["external_id"] == KEY_A and items[0]["source_ids"] == {"atlas.row": "01JROW1"}


def test_aliases_are_bounded_by_the_host_limit(atlas, monkeypatch):
    letters = "abcdefghijklmnopqrstuvwxyz234567"
    keys = ["ak1:" + letters[n] * 26 for n in range(32)] + ["ak1:" + "a" * 25 + letters[n] for n in range(1, 9)]
    items = _catalogue(atlas, monkeypatch, [{"id": "01JROW1", "key": keys[0], "keys": keys, "name": "Merged"}])
    assert items[0]["aliases"] == keys[1:33] and len(items[0]["aliases"]) == atlas.ACHIEVEMENT_ALIAS_LIMIT == 32


@pytest.mark.parametrize("value, sent", [("yes", "yes"), ("partial", "partial"), ("no", "no"),
                                         ("not_applicable", None), ("Yes", None), (True, None), (None, None)])
def test_crossplay_is_sent_only_from_the_shared_vocabulary(atlas, monkeypatch, value, sent):
    meta = details(atlas, monkeypatch, {**GAME, "custom": {"players_max": 1, "crossplay": value}})
    assert meta.get("crossplay") == sent and "crossplay" not in meta.get("custom", {})


# --- the shared vocabulary file (C7.4) ---

VOCAB_FILES = {name: ROOT / path for name, path in (
    ("plugin", "contracts/vocab-v1.json"), ("atlas", "tests/fixtures/atlas/vocab-v1.json"),
    ("host", "tests/fixtures/host/vocab-v1.json"))}


def vocab_tool():
    spec = importlib.util.spec_from_file_location("vocab_check_under_test", ROOT / "tools" / "vocab_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_plugin_uses_the_registry_it_publishes(atlas):
    exported = json.loads(VOCAB_FILES["plugin"].read_text(encoding="utf-8"))
    vocab = atlas.vocab
    assert exported == vocab.export()
    assert set(vocab.ACHIEVEMENT_TIERS) - set(vocab.LEGACY_ACHIEVEMENT_TIERS) == {"platinum"}
    assert set(vocab.LEGACY_ACHIEVEMENT_TIERS) < set(vocab.ACHIEVEMENT_TIERS)
    assert "not_applicable" not in vocab.CROSSPLAY and "feed_kinds" not in exported
    assert vocab_tool().main(["check"]) == 0


@pytest.mark.parametrize("name, digest", [
    ("plugin", "07f8801d7b5fd2b2a5e2b1265ff0c1e40886842b0aee732aa518761390dead7e"),
    ("atlas", "1d2b4dd75502887d68a5e8f785997a680ba278542495756d234f0f549077b29a"),  # Atlas f58ff1d
    ("host", "07f8801d7b5fd2b2a5e2b1265ff0c1e40886842b0aee732aa518761390dead7e"),   # host ff7ebc10 (M7)
])
def test_each_vocabulary_file_matches_its_pinned_digest(name, digest):
    path = VOCAB_FILES[name]
    assert hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest
    assert path.with_name(path.name + ".sha256").read_text(encoding="utf-8").split()[0] == digest
    assert vocab_tool().main(["verify", str(path)]) == 0


def test_the_plugin_atlas_and_host_vocabularies_agree():
    assert vocab_tool().main(["compare", *map(str, VOCAB_FILES.values())]) == 0


@pytest.mark.parametrize("key, values", [("crossplay", ["yes", "partial", "no", "not_applicable"]),
                                         ("achievement_tier", ["bronze", "silver", "gold"]),
                                         ("release_category", ["full"])])
def test_the_compare_reports_a_vocabulary_that_drifted(tmp_path, capsys, key, values):
    drifted = json.loads(VOCAB_FILES["atlas"].read_text(encoding="utf-8"))
    drifted[key] = values
    path = tmp_path / "vocab-v1.json"
    path.write_text(json.dumps(drifted), encoding="utf-8")
    assert vocab_tool().main(["compare", str(VOCAB_FILES["plugin"]), str(path)]) == 1
    assert key + ":" in capsys.readouterr().out


def test_the_check_fails_when_the_published_file_is_stale(tmp_path, capsys):
    tool = vocab_tool()
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "vocab-v1.json").write_text('{"version": 1}\n', encoding="utf-8")
    (tmp_path / "contracts" / "vocab-v1.json.sha256").write_text("0" * 64 + "  vocab-v1.json\n", encoding="utf-8")
    assert tool.main(["check", "--root", str(tmp_path)]) == 1
    assert "run: python tools/vocab_check.py generate" in capsys.readouterr().out


# --- Relations between works (contract C6.4, P5) ---------------------------------------------------------------------

RELATIONS_FIXTURE = json.loads((ROOT / "tests/fixtures/atlas/relations-v1.json").read_text(encoding="utf-8"))
RELATION_CASES = RELATIONS_FIXTURE["cases"]
EMPTY_BLOCK = {"parents": [], "children": [], "members_of": [], "members": [],
               "counts": {"parents": 0, "children": 0, "members_of": 0, "members": 0}, "truncated": False}


def related(atlas, monkeypatch, block, record_id=GAME["id"]):
    """The relations the plugin sends for one Atlas record (GET /games/{id}) carrying ``block`` as `relations`."""
    record = {**GAME, "id": record_id, "relations": block}
    Gateway(monkeypatch, routes={"/games/" + record_id: {"status": 200, "data": record}})
    selected = {"provider": atlas.PROVIDER_ID, "external_id": record_id, "title": "Portal 2"}
    result = atlas.metadata({"request": {}, "candidate": selected})
    jsonschema.validate(result, RESPONSE_SCHEMA)
    assert "failure" not in result
    return result["metadata"].get("relations")


def expected_relations(atlas, case):
    return [{"candidate": {"provider": atlas.PROVIDER_ID, "external_id": item["id"], "title": item["title"],
                           "media_type": "game", "provider_ids": {"atlas": item["id"]}},
             "relation": item["relation"], "group": "related"} for item in case["expect"]] or None


@pytest.mark.parametrize("case", RELATION_CASES, ids=lambda case: case["name"])
def test_outgoing_atlas_relations_become_game_relations_in_a_fixed_order(atlas, monkeypatch, case):
    """parents and members_of are edges from this record (C6.2: `to` is the parent); children and members are the
    other records' own edges and travel with their refresh. Order: vocabulary order of the type, then the Atlas id."""
    assert related(atlas, monkeypatch, case["relations"], case["record_id"]) == expected_relations(atlas, case)


@pytest.mark.parametrize("case", RELATION_CASES, ids=lambda case: case["name"])
def test_relations_do_not_depend_on_the_order_atlas_lists_them_in(atlas, monkeypatch, case):
    block = {name: list(reversed(value)) if isinstance(value, list) else value
             for name, value in case["relations"].items()}
    assert related(atlas, monkeypatch, block, case["record_id"]) == expected_relations(atlas, case)


def test_unknown_relation_types_are_ignored_and_logged_without_titles(atlas, monkeypatch, capsys):
    case = next(c for c in RELATION_CASES if c.get("ignored_types"))
    sent = related(atlas, monkeypatch, case["relations"], case["record_id"])
    assert [item["relation"] for item in sent] == ["expansion_of"]
    logged = capsys.readouterr().err
    assert all(name in logged for name in case["ignored_types"])
    assert "Orbit Universe" not in logged and "Orbit Bundle" not in logged, "titles never reach the log"


BASE = "atlas:" + "b" * 26


@pytest.mark.parametrize("block", [
    None, [], "dlc_of", 7, {"parents": None}, {"parents": BASE}, {"parents": {"id": BASE}},
    {"parents": [None, 7, "x", [], {}]},
    {"parents": [{"id": BASE, "type": None, "title": "Base"}]},
    {"parents": [{"id": BASE, "type": ["dlc_of"], "title": "Base"}]},
    {"parents": [{"id": BASE, "type": "x" * 5000, "title": "Base"}]},
    {"parents": [{"id": BASE + "\n", "type": "dlc_of", "title": "Base"}]},
    {"parents": [{"id": "../../admin", "type": "dlc_of", "title": "Base"}]},
    {"parents": [{"id": 12, "type": "dlc_of", "title": "Base"}]},
    {"parents": [{"id": GAME["id"], "type": "dlc_of", "title": "Itself"}]},
    {"parents": [{"id": BASE, "type": "dlc_of", "title": None}]},
    {"parents": [{"id": BASE, "type": "dlc_of", "title": "   "}]},
    {"parents": [{"id": BASE, "type": "dlc_of", "title": "x" * 513}]},
    {"children": [{"id": BASE, "type": "dlc_of", "title": "A child"}],
     "members": [{"id": "atlas:" + "c" * 26, "type": "series_member", "title": "A member"}]},
], ids=repr)
def test_a_malformed_or_missing_relations_block_sends_no_relations_and_never_fails(atlas, monkeypatch, block):
    assert related(atlas, monkeypatch, block) is None


def test_an_atlas_without_relations_is_mapped_as_before(atlas, monkeypatch):
    """An Atlas before A15 (protocol 1.4) has no relations key; with an empty block the patch is the same."""
    before = details(atlas, monkeypatch, GAME)
    assert "relations" not in before
    assert details(atlas, monkeypatch, {**GAME, "relations": EMPTY_BLOCK}) == before


def test_titles_are_collapsed_and_duplicates_keep_one_entry(atlas, monkeypatch):
    sent = related(atlas, monkeypatch, {"parents": [
        {"id": BASE, "type": "dlc_of", "title": "  Orbit\tGarden  "},
        {"id": BASE, "type": "dlc_of", "title": "Orbit Garden (other spelling)"},
        {"id": BASE, "type": "mod_of", "title": "Orbit Garden"}]})
    assert [(item["relation"], item["candidate"]["title"]) for item in sent] == [
        ("dlc_of", "Orbit Garden"), ("mod_of", "Orbit Garden")]


def _atlas_id(number, letter):
    return "atlas:" + format(number, "026d").replace("0", letter)


def test_relations_are_bounded(atlas, monkeypatch, capsys):
    parents = [{"id": _atlas_id(n, "a"), "type": "dlc_of", "title": f"Base {n}"} for n in range(200)]
    members = [{"id": _atlas_id(n, "s"), "type": "series_member", "title": f"Series {n}"} for n in range(200)]
    sent = related(atlas, monkeypatch, {"parents": parents, "members_of": members})
    assert len(sent) == atlas.RELATION_LIMIT == 64
    assert {item["relation"] for item in sent} == {"dlc_of"}, "vocabulary order first: hierarchy before membership"
    assert sent == sorted(sent, key=lambda item: item["candidate"]["external_id"])
    assert "64" in capsys.readouterr().err


def test_relations_are_sent_only_for_games(atlas, monkeypatch):
    block = RELATION_CASES[0]["relations"]
    for media_type in ("anime", "movie", "tv_show"):
        record = {**GAME, "media_type": media_type, "relations": block}
        Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": record}})
        selected = {**SELECTED, "media_type": media_type}
        assert "relations" not in atlas.metadata({"request": {}, "candidate": selected})["metadata"]


def test_relations_are_not_sent_under_an_older_declared_contract(atlas, monkeypatch):
    """Under 1.1.19 a vocabulary relation has no defined direction (M7: such relations are not ingested)."""
    older_contract(atlas, monkeypatch)
    assert related(atlas, monkeypatch, RELATION_CASES[0]["relations"], RELATION_CASES[0]["record_id"]) is None


def test_the_achievements_resource_never_carries_relations(atlas, monkeypatch):
    record = {**GAME, "relations": RELATION_CASES[0]["relations"]}
    Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": record},
                                 "/games/" + GAME["id"] + "/achievements": {"status": 200, "data": ACHIEVEMENTS}})
    out = atlas.metadata({"request": {"resource": "achievements"}, "candidate": SELECTED})
    assert set(out["metadata"]) == {"achievements"}


# --- One game seen by Steam, IGDB, RAWG and Atlas: identity and merge behaviour ------------------------------------

def test_a_game_found_through_its_steam_id_also_gets_its_relations(atlas, monkeypatch):
    """/resolve answers with the record view, which has no relations block (Atlas adds it only to GET /games/{id}).
    A game the host knows by its Steam id must get the same relations as one it knows by its Atlas id."""
    gateway = Gateway(monkeypatch, routes={
        "/resolve": {"status": 200, "data": resolved("crosswalk", "crosswalk", game={**GAME})},
        "/games/" + GAME["id"]: {"status": 200, "data": {**GAME, "relations": RELATION_CASES[0]["relations"]}}})
    out = atlas.metadata({"request": {}, "candidate": STEAM_ONLY})
    jsonschema.validate(out, RESPONSE_SCHEMA)
    assert [item["relation"] for item in out["metadata"]["relations"]] == ["dlc_of", "series_member"]
    assert [call["url"].split("?")[0].rsplit("/api/v2", 1)[1] for call in gateway.calls] == [
        "/resolve", "/games/" + GAME["id"]]


@pytest.mark.parametrize("status", [404, 500, 429])
def test_a_failed_relations_read_after_resolve_keeps_the_resolved_metadata(atlas, monkeypatch, status):
    Gateway(monkeypatch, routes={"/resolve": {"status": 200, "data": resolved("crosswalk", "crosswalk")},
                                 "/games/" + GAME["id"]: {"status": status, "error": "x"}})
    out = atlas.metadata({"request": {}, "candidate": STEAM_ONLY})
    assert out["metadata"]["provider_ids"]["atlas"] == GAME["id"] and "relations" not in out["metadata"]


def test_relations_read_after_resolve_must_belong_to_the_resolved_record(atlas, monkeypatch):
    """A merge between the two reads answers GET with another record: its relations are not this game's."""
    moved = {**GAME, "id": OTHER, "redirected_from": GAME["id"], "relations": RELATION_CASES[0]["relations"]}
    Gateway(monkeypatch, routes={"/resolve": {"status": 200, "data": resolved("crosswalk", "crosswalk")},
                                 "/games/" + GAME["id"]: {"status": 200, "data": moved}})
    out = atlas.metadata({"request": {}, "candidate": STEAM_ONLY})
    assert out["metadata"]["provider_ids"]["atlas"] == GAME["id"] and "relations" not in out["metadata"]


def test_an_atlas_id_lookup_needs_no_second_read_for_relations(atlas, monkeypatch):
    gateway = Gateway(monkeypatch, routes={"/games/" + GAME["id"]: {"status": 200, "data": GAME}})
    atlas.metadata({"request": {}, "candidate": SELECTED})
    assert len(gateway.calls) == 1, "an Atlas without relations is not asked twice"


# The host's library candidate (`service.library_candidate`): the game's stored ids, plus the candidate's own
# identity under its provider id (`identity.identities`), which for a library game is `local` = the title.
LIBRARY_REFRESH = {"provider": "local", "external_id": "Portal 2", "title": "Portal 2", "year": 2011,
                   "media_type": "game",
                   "provider_ids": {"steam": "620", "igdb": "72", "rawg": "4200", "local": "Portal 2"}}


def test_a_library_refresh_sends_only_real_provider_ids_to_resolve(atlas, monkeypatch):
    """`local` is not an identifier namespace and its value is the title: it must not reach Atlas as identity evidence."""
    _, gateway = lookup(atlas, monkeypatch, resolved("crosswalk", "crosswalk"), selected=LIBRARY_REFRESH)
    assert gateway.calls[0]["body"]["items"][0]["provider_ids"] == {"steam": "620", "igdb": "72", "rawg": "4200"}


def test_a_steam_candidate_does_not_send_its_provider_id_as_a_namespace(atlas, monkeypatch):
    selected = {"provider": "core.steam", "external_id": "620", "title": "Portal 2", "year": 2011,
                "provider_ids": {"steam": "620", "core.steam": "620", "igdb": "72"}}
    _, gateway = lookup(atlas, monkeypatch, resolved("crosswalk", "crosswalk"), selected=selected)
    assert gateway.calls[0]["body"]["items"][0]["provider_ids"] == {"steam": "620", "igdb": "72"}


def test_resolve_stays_inside_the_limits_atlas_validates(atlas, monkeypatch):
    """Atlas answers 422 to a provider id over 256 characters, more than 32 ids or a title over 500 characters, and
    the plugin then reports Atlas as unavailable for that game on every refresh. The host allows 512 and 32 + 1."""
    ids = {f"ns{n:02d}": str(n) for n in range(40)}
    selected = {"provider": "local", "external_id": "x" * 510, "title": "x" * 510, "year": 2011,
                "provider_ids": {**ids, "steam": "620", "long": "9" * 300, "local": "x" * 510}}
    _, gateway = lookup(atlas, monkeypatch, resolved("crosswalk", "crosswalk"), selected=selected)
    item = gateway.calls[0]["body"]["items"][0]
    assert len(item["provider_ids"]) == 32 and "long" not in item["provider_ids"]
    assert all(len(value) <= 256 for value in item["provider_ids"].values())
    assert list(item["provider_ids"]) == sorted(item["provider_ids"]), "a deterministic choice of 32"
    assert "title" not in item, "an over-long title is not sent (cut short, it would name another game)"


def test_a_candidate_with_only_unusable_ids_and_title_sends_nothing(atlas, monkeypatch):
    gateway = Gateway(monkeypatch)
    selected = {"provider": "local", "external_id": "x" * 510, "title": "x" * 510, "media_type": "game",
                "provider_ids": {"local": "x" * 510}}
    assert atlas.metadata({"request": {}, "candidate": selected}) == {}
    assert gateway.calls == []


def test_a_record_with_many_provider_ids_still_yields_a_valid_search_and_patch(atlas, monkeypatch):
    """Atlas lists every namespace its sources claim (one record can exceed the host's 32), and its namespace rule
    allows a leading '.', '-' or '_' the host refuses. One such record must not make the whole response invalid."""
    claimed = {f"src{n:02d}": str(n) for n in range(40)}
    record = {**GAME, "provider_ids": {**claimed, "steam": "620", "_odd": "1", "-dash": "2", "rawg": 4200,
                                       "nothing": None, "many": ["1", "2"], "flag": True, "long": "9" * 600}}
    Gateway(monkeypatch, routes={"/api/v2/games": {"status": 200, "data": {"results": [record]}},
                                 "/games/" + GAME["id"]: {"status": 200, "data": record}})
    search = atlas.search(work())
    jsonschema.validate(search, RESPONSE_SCHEMA)
    ids = search["candidates"][0]["provider_ids"]
    assert len(ids) == 32 and ids["atlas"] == GAME["id"] and ids["rawg"] == "4200"
    assert not {"_odd", "-dash", "nothing", "many", "flag", "long"} & set(ids)
    meta = atlas.metadata({"request": {}, "candidate": SELECTED})
    jsonschema.validate(meta, RESPONSE_SCHEMA)
    assert meta["metadata"]["provider_ids"] == ids

def test_well_known_store_ids_survive_the_cut_before_obscure_namespaces(atlas):
    """The 32-id cut used to be alphabetical, so 40 namespaces sorting before "igdb" and "steam" dropped both."""
    obscure = {f"a{n:02d}": str(n) for n in range(40)}
    record = {**GAME, "provider_ids": {**obscure, "steam": "620", "igdb": "72", "gog": "1207", "tmdb": "9",
                                       "zzz": "1"}}
    ids = atlas.record_provider_ids(record)
    assert len(ids) == 32
    assert list(ids)[:5] == ["atlas", "steam", "igdb", "gog", "tmdb"]
    assert list(ids)[5:] == [f"a{n:02d}" for n in range(27)]  # the rest stay in sorted order
    assert "zzz" not in ids
