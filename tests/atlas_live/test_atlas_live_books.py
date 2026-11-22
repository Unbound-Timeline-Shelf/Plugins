"""official.metadata-atlas books (C15 T-P1) against a REAL Atlas container with three synthetic books.

The seed (``atlas_live_support.seed_books``) creates the `book` media type on an Atlas that predates the book release,
as an admin would, and adds the `ext.book` member where the Atlas under test accepts it. The tests below hold to what
every such Atlas serves; where the book view (authors with roles, editions with ISBNs) is present they also check it.
"""
import json
import os
from pathlib import Path

import jsonschema
import pytest

if not all(os.environ.get(name) for name in ("ATLAS_LIVE_URL", "ATLAS_LIVE_BOOTSTRAP_TOKEN", "ATLAS_LIVE_CONTAINER")):
    pytest.skip("live Atlas lane: run tools/check_metadata_atlas_live.py (needs Docker); "
                "see tests/atlas_live/README.md", allow_module_level=True)

import atlas_live_support as support  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RESPONSE_SCHEMA = json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text(encoding="utf-8"))


def book_search(plugin, query, **request):
    result = plugin.search({"request": {"query": query, "limit": 10, "media_type": "book", **request}})
    assert "failure" not in result, result
    jsonschema.validate(result, RESPONSE_SCHEMA)
    return result["candidates"]


def book_candidate(plugin, atlas_id, **extra):
    return {"provider": plugin.PROVIDER_ID, "external_id": atlas_id, "provider_ids": {"atlas": atlas_id},
            "media_type": "book", **extra}


def book_details(plugin, atlas_id, **extra):
    result = plugin.metadata({"request": {}, "candidate": book_candidate(plugin, atlas_id, **extra)})
    assert "failure" not in result, result
    jsonschema.validate(result, RESPONSE_SCHEMA)
    return result["metadata"]


def view(atlas_api, seeded, cid):
    return atlas_api.ok("GET", f"/games/{cid}", seeded.read_token)


def test_the_seeded_books_are_book_records(atlas_api, seeded):
    for key in support.BOOKS:
        assert view(atlas_api, seeded, seeded.ids["book_" + key])["media_type"] == "book"


def test_a_book_search_lists_only_books_with_the_host_candidate_shape(plugin, gateway, seeded):
    found = book_search(plugin, "synthetic")
    ids = {item["external_id"] for item in found}
    assert {seeded.ids["book_lighthouse"], seeded.ids["book_tides"], seeded.ids["book_islands"]} <= ids
    assert all(item["media_type"] == "book" for item in found)
    [lighthouse] = [item for item in found if item["external_id"] == seeded.ids["book_lighthouse"]]
    assert lighthouse["title"] == "The Synthetic Lighthouse" and lighthouse["year"] == 1937
    assert lighthouse["authors"][0] == "Ada Example"
    assert lighthouse["provider_ids"]["isbn"] == support.BOOK_ISBNS["lighthouse"]
    assert "type=book" in gateway.calls[-1].query


def test_a_game_search_never_lists_a_book(plugin, gateway, seeded):
    result = plugin.search({"request": {"query": "synthetic", "limit": 10, "media_type": "game"}})
    assert not {seeded.ids["book_" + key] for key in support.BOOKS} & {c["external_id"] for c in result["candidates"]}


def test_a_book_maps_to_the_book_patch(plugin, gateway, atlas_api, seeded):
    cid = seeded.ids["book_lighthouse"]
    served = view(atlas_api, seeded, cid)
    meta = book_details(plugin, cid)
    book = meta["book"]
    assert meta["title"] == "The Synthetic Lighthouse" and meta["year"] == 1937
    assert book["first_published"] == {"date": "1937-06-01", "precision": "day"}
    # a day keeps the host's general years, so it may also travel as the C5.1 first release; a year or month would not
    assert meta.get("first_release") in (None, book["first_published"])
    assert book["authors"][0] == {"name": "Ada Example", "role": "author"}
    assert book["series_name"] == "The Fictional Coast"
    # D15.12: subjects (the book type's `features`) fill genres up to ten, the rest are tags
    assert meta["genres"] == support.BOOK_SUBJECTS[:10] and meta["tags"] == support.BOOK_SUBJECTS[10:]
    assert meta["provider_ids"]["isbn"] == support.BOOK_ISBNS["lighthouse"]
    assert meta["provider_ids"]["atlas"] == cid
    assert not {"developer", "publisher", "series", "features", "platforms", "relations"} & set(meta)
    if isinstance(served.get("authors"), list) and served["authors"]:
        # the book view (A21 on): the ordered list with roles, not just the primary creator
        assert book["authors"] == [{"name": "Ada Example", "role": "author"},
                                   {"name": "B. Placeholder", "role": "translator"}]
    else:
        assert book["authors"] == [{"name": "Ada Example", "role": "author"}]
    served_isbns = {entry.get("isbn_13") for entry in served.get("editions") or [] if isinstance(entry, dict)}
    if support.BOOK_ISBNS["lighthouse"] in served_isbns:
        assert [edition.get("isbn_13") for edition in book["editions"]].count(support.BOOK_ISBNS["lighthouse"]) == 1


def test_an_edition_named_by_an_observation_reaches_the_host(plugin, gateway, atlas_api, seeded):
    cid = seeded.ids["book_islands"]
    served = view(atlas_api, seeded, cid)
    meta = book_details(plugin, cid)
    names = [entry.get("name") for entry in served.get("editions") or []]
    assert [edition.get("name") for edition in meta["book"].get("editions", [])] == names
    assert "Ebook" in names
    assert meta["book"]["authors"][0] == {"name": "C. Example", "role": "author"}


def test_an_isbn_lookup_finds_exactly_the_work_that_holds_it(plugin, gateway, seeded):
    isbn = support.BOOK_ISBNS["tides"]
    found = book_search(plugin, "978-0-00-000001-9", options={"isbn": isbn})
    assert [(item["external_id"], item["isbn_13"]) for item in found] == [(seeded.ids["book_tides"], isbn)]
    assert gateway.paths()[-1] == "/resolve"
    meta = book_details(plugin, seeded.ids["book_tides"], isbn_13=isbn)
    assert meta["book"]["isbn_13"] == isbn and meta["year"] == 2005
    assert meta["book"]["first_published"] == {"date": "2005-08-01", "precision": "day"}
    assert meta.get("first_release") in (None, meta["book"]["first_published"])


def test_an_unknown_isbn_lists_nothing(plugin, gateway):
    assert book_search(plugin, "9780000000033", options={"isbn": "9780000000033"}) == []


def test_a_book_cover_is_offered_as_a_poster(plugin, gateway, seeded):
    result = plugin.media({"request": {}, "candidate": book_candidate(plugin, seeded.ids["book_islands"])})
    jsonschema.validate(result, RESPONSE_SCHEMA)
    assert [asset["kind"] for asset in result["assets"]] == ["poster"]
    assert result["assets"][0]["url"].startswith(seeded.public + "/media/")


def test_a_book_has_no_achievements(plugin, gateway, seeded):
    result = plugin.metadata({"request": {"resource": "achievements"},
                              "candidate": book_candidate(plugin, seeded.ids["book_lighthouse"])})
    assert result == {}
    assert not any(path.endswith("/achievements") for path in gateway.paths())


def test_under_an_older_declaration_no_book_reaches_the_host(plugin, gateway, seeded, monkeypatch):
    monkeypatch.setattr(plugin, "API_CONTRACT", (1, 1, 19))
    assert plugin.search({"request": {"query": "synthetic", "media_type": "book"}}) == {
        "failure": {"code": "invalid_response"}}
    assert plugin.metadata({"request": {}, "candidate": book_candidate(plugin, seeded.ids["book_lighthouse"])}) == {}
    assert gateway.calls == []
