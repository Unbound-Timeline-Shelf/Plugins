"""Provider wire, pagination and policy regressions; no live-success claims."""
import importlib.util
import json
import sys
from pathlib import Path

import jsonschema
import pytest

from sdk import metadata_provider as sdk

ROOT = Path(__file__).resolve().parents[1]


def plugin(slug, monkeypatch):
    directory = ROOT / "official" / ("metadata-" + slug)
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("metadata_test_" + slug, directory / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("source", sorted((ROOT / "official").glob("metadata-*/plugin.py")))
def test_official_provider_registration_matches_exported_public_contract(source, monkeypatch):
    module = plugin(source.parent.name.removeprefix("metadata-"), monkeypatch)
    schema = json.loads((ROOT / "tools/schemas/metadata-registration-v1.schema.json").read_text())
    jsonschema.validate(module.DECLARATION, schema)
    manifest = json.loads((source.parent / "manifest.json").read_text())
    expected = {"metadata-hltb": "1.1.13", "metadata-atlas": "1.1.20", "metadata-openlibrary": "1.1.20"}
    assert manifest["api_contract_version"] == expected.get(source.parent.name, "1.1.1")
    for action in module.DECLARATION["operations"].values():
        assert callable(getattr(module, action))


def test_variable_size_episode_pages_preserve_every_entry_within_action_limit():
    episodes = [{"episode_number": number, "description": "世界 " * (number % 40 + 1)}
                for number in range(1, 1403)]
    work = {}
    received = []
    while True:
        response = sdk.metadata_page(work, "episodes", episodes)
        assert len(json.dumps(response, ensure_ascii=False).encode()) < 64 * 1024
        received.extend(response["metadata"]["episodes"])
        if not response.get("next_cursor"):
            break
        work["cursor"] = response["next_cursor"]
    assert received == episodes
    with pytest.raises(sdk.ProviderFailure, match="invalid_response"):
        sdk.metadata_page({}, "episodes", [{"episode_number": 1, "description": "x" * 65000}])


def test_identity_lookup_rejects_ambiguous_titles_and_wrong_year():
    selected = {"title": "Dune", "year": 2021}
    older = {"title": "Dune", "year": 1984, "external_id": "old"}
    current = {"title": "Dune", "year": 2021, "external_id": "new"}
    assert sdk.exact_identity([older, current], selected) == current
    assert sdk.exact_identity([current, dict(current)], selected) is None
    assert sdk.exact_identity([older], selected) is None


@pytest.mark.parametrize("status,code", [(401, "invalid_configuration"), (429, "rate_limited"),
                                         (503, "unavailable")])
def test_network_failures_do_not_retain_remote_bodies(status, code, monkeypatch):
    monkeypatch.setattr(sdk, "request", lambda *args: {
        "status": status, "data": {"secret": "do not retain"}, "retry_after_seconds": 12})
    with pytest.raises(sdk.ProviderFailure) as failure:
        sdk.network("https://example.test/provider?key=private")
    assert failure.value.code == code
    assert "private" not in str(failure.value)
    assert "do not retain" not in json.dumps(failure.value.response())


def test_interactive_does_not_retry_but_background_can_retry(monkeypatch):
    calls = []
    sleeps = []
    def unavailable(*args, **kwargs):
        calls.append(1)
        raise sdk.ProviderFailure("unavailable")
    monkeypatch.setattr(sdk, "network", unavailable)
    monkeypatch.setattr(sdk.time, "sleep", sleeps.append)
    with pytest.raises(sdk.ProviderFailure):
        sdk.ProviderHttp({"policy": "interactive"}, "provider")("https://example.test")
    assert len(calls) == 1 and sleeps == []
    with pytest.raises(sdk.ProviderFailure):
        sdk.ProviderHttp({"policy": "background"}, "provider")("https://example.test")
    assert len(calls) == 4 and sleeps == [1, 2]


def test_token_rejection_is_returned_to_the_provider_without_background_retries(monkeypatch):
    calls = []
    def rejected(*args, **kwargs):
        calls.append(1)
        raise sdk.ProviderFailure("unavailable", status=403)
    monkeypatch.setattr(sdk, "network", rejected)
    with pytest.raises(sdk.ProviderFailure) as caught:
        sdk.ProviderHttp({"policy": "background"}, "provider")("https://example.test")
    assert caught.value.status == 403 and calls == [1]






def test_tmdb_collection_and_recommendations_use_separate_resources(monkeypatch):
    module = plugin("tmdb", monkeypatch)
    monkeypatch.setattr(module, "resolve", lambda values: "1")
    items = {"/movie/1": {"belongs_to_collection": {"id": 2}},
             "/collection/2": {"name": "A collection", "parts": [
                 {"id": 1, "title": "First", "release_date": "2000-01-01"},
                 {"id": 3, "title": "Next", "release_date": "2001-01-01"}]},
             "/movie/1/recommendations": {"results": [{"id": 4, "title": "Recommended"}]}}
    monkeypatch.setattr(module, "get", lambda values, path, **kwargs: items[path])
    values = {"request": {"resource": "relations", "media_type": "movie"}, "candidate": {}}
    result = module.metadata(values)
    assert result["metadata"]["relation_group"] == "A collection"
    assert [entry["candidate"]["external_id"] for entry in result["metadata"]["relations"]] == ["3"]
    values["request"]["resource"] = "recommendations"
    assert module.metadata(values)["metadata"]["relations"][0]["group"] == "recommendation"
