"""Atlas provider, books (C15 6.3-6.5): the `book` media type, the Atlas book view mapped to `MetadataPatch.book`,
the ISBN identifier lookup, and the declared-contract switch. Synthetic records only (no Open Library data)."""
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest

from sdk import metadata_provider as sdk

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "atl_secret_token"
RESPONSE_SCHEMA = json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text(encoding="utf-8"))
REGISTRATION_SCHEMA = json.loads(
    (ROOT / "tools/schemas/metadata-registration-v1.schema.json").read_text(encoding="utf-8"))
BOOK_ID = "atlas:" + "k" * 26
SERIES_ID = "atlas:" + "s" * 26
# Synthetic ISBNs with valid check digits (the 978-0-00 block is not assigned to a real book list here).
ISBN_A13, ISBN_A10 = "9780000000002", "0000000000"
ISBN_B13, ISBN_B10 = "9780000000019", "0000000019"
ISBN_C13 = "9780000000026"
ISBN_979 = "9790000000018"
SUBJECTS = [f"Subject {n:02d}" for n in range(12)]
BOOK = {
    "id": BOOK_ID, "media_type": "book", "title": "The Synthetic Lighthouse",
    "description": "A keeper writes letters to a town that is not there.", "developer": "Ada Example",
    "authors": [{"name": "Ada Example", "role": "author", "ids": {"openlibrary": "OL1A"}},
                {"name": "B. Placeholder", "role": "translator"}],
    "subtitle": "A Coastal Novel", "page_count": 412, "original_language": "en",
    "release_date": None, "release_year": 1937, "first_release": {"date": "1937-06", "precision": "month"},
    "features": SUBJECTS, "genres": ["Fiction"],
    "editions": [
        {"name": "Hardcover, Example Press 1937", "provider_ids": {"openlibrary_edition": "OL1M"},
         "sources": ["openlibrary"], "isbn_13": ISBN_A13, "isbn_10": ISBN_A10, "format": "hardcover",
         "publisher": "Example Press", "published": {"date": "1937-06", "precision": "month"}, "pages": 412,
         "language": "en"},
        {"name": "Paperback, Example Press 2005", "provider_ids": {"openlibrary_edition": "OL2M"},
         "sources": ["openlibrary"], "isbn_13": ISBN_B13, "format": "paperback", "publisher": "Example Press",
         "published": {"date": "2005-08-01", "precision": "day"}, "pages": 528, "language": "en"},
    ],
    "relations": {"parents": [], "members_of": [
        {"id": SERIES_ID, "type": "series_member", "title": "The Fictional Coast", "media_type": "series",
         "position": "2"}], "children": [], "members": [], "counts": {}, "truncated": False},
    "provider_ids": {"openlibrary": "OL1W", "isbn": ISBN_A13},
}
SELECTED = {"provider": "official.metadata-atlas.atlas", "external_id": BOOK_ID, "title": "The Synthetic Lighthouse",
            "media_type": "book"}


@pytest.fixture
def atlas(monkeypatch):
    directory = ROOT / "official" / "metadata-atlas"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("metadata_test_atlas_books", directory / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Gateway:
    def __init__(self, monkeypatch, routes=None):
        self.routes = routes or {}
        self.calls = []
        monkeypatch.setattr(sdk, "request", self)

    def __call__(self, method, capability, payload=None):
        if method == "metadata_providers.configuration":
            return {"values": {"base_url": "https://atlas.test/", "api_token": TOKEN}}
        self.calls.append(payload)
        url = payload["url"].split("?")[0]
        for suffix, response in self.routes.items():
            if url.endswith(suffix):
                return response
        return {"status": 404, "error": "not found"}


def book_details(atlas, monkeypatch, record=BOOK, selected=SELECTED):
    Gateway(monkeypatch, routes={"/games/" + BOOK_ID: {"status": 200, "data": record}})
    result = atlas.metadata({"request": {}, "candidate": selected})
    jsonschema.validate(result, RESPONSE_SCHEMA)
    return result["metadata"]


def older_contract(atlas, monkeypatch):
    monkeypatch.setattr(atlas, "API_CONTRACT", (1, 1, 19))


# --- declaration ---

def test_book_is_declared_under_the_unified_contract(atlas):
    assert atlas.MEDIA_TYPES == ("game", "anime", "movie", "tv_show", "book")
    assert atlas.DECLARATION["media_types"] == list(atlas.MEDIA_TYPES)
    assert atlas.UNIFIED_CONTRACT == atlas.RELEASES_CONTRACT == (1, 1, 20)
    jsonschema.validate(atlas.DECLARATION, REGISTRATION_SCHEMA)


def test_an_older_declaration_does_not_offer_books(atlas, monkeypatch):
    older_contract(atlas, monkeypatch)
    assert atlas.media_types() == ("game", "anime", "movie", "tv_show")
    assert not atlas.sends_books()


def test_the_declaration_follows_the_manifest_it_is_packaged_with(tmp_path, monkeypatch):
    source = ROOT / "official" / "metadata-atlas"
    for name in ("plugin.py", "vocab.py"):
        (tmp_path / name).write_bytes((source / name).read_bytes())
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    (tmp_path / "manifest.json").write_text(json.dumps({**manifest, "api_contract_version": "1.1.19"}),
                                            encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    spec = importlib.util.spec_from_file_location("metadata_atlas_books_1119", tmp_path / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "book" not in module.DECLARATION["media_types"] and len(module.DECLARATION["media_types"]) == 4


# --- search ---

def test_search_for_books_returns_book_candidates_with_authors(atlas, monkeypatch):
    gateway = Gateway(monkeypatch, routes={"/api/v2/games": {"status": 200, "data": {"results": [BOOK]}}})
    result = atlas.search({"request": {"query": "lighthouse", "limit": 5, "media_type": "book"}})
    jsonschema.validate(result, RESPONSE_SCHEMA)
    assert result["candidates"] == [{
        "provider": atlas.PROVIDER_ID, "external_id": BOOK_ID, "title": "The Synthetic Lighthouse",
        "media_type": "book", "year": 1937, "authors": ["Ada Example", "B. Placeholder"],
        "provider_ids": {"atlas": BOOK_ID, "isbn": ISBN_A13, "openlibrary": "OL1W"}}]
    assert "type=book" in gateway.calls[0]["url"]


def test_a_book_search_never_lists_another_media_type(atlas, monkeypatch):
    game = {"id": "atlas:" + "g" * 26, "title": "Lighthouse Game", "media_type": "game"}
    Gateway(monkeypatch, routes={"/api/v2/games": {"status": 200, "data": {"results": [game, BOOK]}}})
    result = atlas.search({"request": {"query": "lighthouse", "media_type": "book"}})
    assert [item["external_id"] for item in result["candidates"]] == [BOOK_ID]


def test_an_isbn_lookup_resolves_the_work_through_the_isbn_crosswalk(atlas, monkeypatch):
    answer = {"results": [{"canonical_id": BOOK_ID, "reason": "crosswalk", "method": "crosswalk", "game": BOOK}]}
    gateway = Gateway(monkeypatch, routes={"/resolve": {"status": 200, "data": answer}})
    result = atlas.search({"request": {"query": "978-0-00-000001-9", "media_type": "book",
                                       "options": {"isbn": ISBN_B13}}})
    jsonschema.validate(result, RESPONSE_SCHEMA)
    assert [item["isbn_13"] for item in result["candidates"]] == [ISBN_B13]
    assert gateway.calls[0]["method"] == "POST"
    assert gateway.calls[0]["body"] == {"items": [{"provider_ids": {"isbn": ISBN_B13}, "media_type": "book"}],
                                        "include_view": True}


@pytest.mark.parametrize("answer", [
    {"results": [{"canonical_id": BOOK_ID, "reason": "conflict", "conflict": {"canonical_ids": [BOOK_ID]},
                  "game": BOOK}]},
    {"results": [{"canonical_id": None, "reason": "none"}]},
    {"results": [{"canonical_id": BOOK_ID, "reason": "crosswalk", "game": {**BOOK, "media_type": "game"}}]},
    # an older Atlas (no `reason`, only `method`) whose view lacks a usable id: nothing, never a KeyError
    {"results": [{"canonical_id": BOOK_ID, "method": "crosswalk",
                  "game": {key: value for key, value in BOOK.items() if key != "id"}}]},
    {"results": [{"canonical_id": BOOK_ID, "method": "crosswalk", "game": {**BOOK, "id": "not-an-atlas-id"}}]},
    {"results": []},
])
def test_an_isbn_lookup_without_a_certain_book_lists_nothing(atlas, monkeypatch, answer):
    Gateway(monkeypatch, routes={"/resolve": {"status": 200, "data": answer}})
    result = atlas.search({"request": {"query": ISBN_A13, "media_type": "book", "options": {"isbn": ISBN_A13}}})
    assert result == {"candidates": []}


@pytest.mark.parametrize("raw", ["978-0-00-000001-9", " 978 0000000019 ", ISBN_B10, "0-00-000001-9"])
def test_a_non_canonical_isbn_option_is_normalised_to_the_isbn_13_lookup(atlas, monkeypatch, raw):
    gateway = Gateway(monkeypatch, routes={"/resolve": {"status": 200, "data": {"results": [
        {"canonical_id": BOOK_ID, "reason": "crosswalk", "game": BOOK}]}}})
    atlas.search({"request": {"query": raw, "media_type": "book", "options": {"isbn": raw}}})
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["body"]["items"] == [{"provider_ids": {"isbn": ISBN_B13}, "media_type": "book"}]


@pytest.mark.parametrize("options", [{"isbn": "9780000000003"}, {"isbn": 9780000000002}, {"isbn": "0000000001"},
                                     {"isbn": "lighthouse"}, {"isbn": ["9780000000002"]}])
def test_an_invalid_isbn_option_lists_nothing_and_never_runs_a_title_search(atlas, monkeypatch, options):
    gateway = Gateway(monkeypatch, routes={"/api/v2/games": {"status": 200, "data": {"results": [BOOK]}}})
    result = atlas.search({"request": {"query": "lighthouse", "media_type": "book", "options": options}})
    assert result == {"candidates": []}
    assert gateway.calls == []


@pytest.mark.parametrize("options", [{}, {"isbn": None}, {"isbn": ""}])
def test_a_book_search_without_an_isbn_option_is_a_title_search(atlas, monkeypatch, options):
    gateway = Gateway(monkeypatch, routes={"/api/v2/games": {"status": 200, "data": {"results": [BOOK]}}})
    atlas.search({"request": {"query": "lighthouse", "media_type": "book", "options": options}})
    assert gateway.calls[0]["url"].split("?")[0].endswith("/api/v2/games")


def test_the_isbn_option_is_ignored_for_other_media_types(atlas, monkeypatch):
    gateway = Gateway(monkeypatch, routes={"/api/v2/games": {"status": 200, "data": {"results": []}}})
    atlas.search({"request": {"query": "portal", "media_type": "game", "options": {"isbn": ISBN_A13}}})
    assert gateway.calls[0]["url"].split("?")[0].endswith("/api/v2/games")


# --- metadata: the section 6.5 mapping ---

def test_a_book_record_maps_to_the_book_patch(atlas, monkeypatch):
    meta = book_details(atlas, monkeypatch)
    assert meta["book"] == {
        "authors": [{"name": "Ada Example", "role": "author"}, {"name": "B. Placeholder", "role": "translator"}],
        "subtitle": "A Coastal Novel", "page_count": 412, "original_language": "en",
        "series_name": "The Fictional Coast", "series_position": "2",
        "first_published": {"date": "1937-06", "precision": "month"},
        "editions": [
            {"key": "OL1M", "name": "Hardcover, Example Press 1937", "isbn_13": ISBN_A13, "isbn_10": ISBN_A10,
             "format": "hardcover", "publisher": "Example Press",
             "publish_date": {"date": "1937-06", "precision": "month"}, "page_count": 412, "language": "en"},
            {"key": "OL2M", "name": "Paperback, Example Press 2005", "isbn_13": ISBN_B13, "format": "paperback",
             "publisher": "Example Press", "publish_date": {"date": "2005-08-01", "precision": "day"},
             "page_count": 528, "language": "en"}]}
    assert meta["title"] == "The Synthetic Lighthouse" and meta["year"] == 1937
    assert meta["provider_ids"] == {"atlas": BOOK_ID, "isbn": ISBN_A13, "openlibrary": "OL1W"}
    # D15.12: the first ten subjects are genres (after Atlas's own genres), the rest are tags
    assert meta["genres"] == ["Fiction", *SUBJECTS[:10]] and meta["tags"] == SUBJECTS[10:]
    # a book is not a game: no game fields and no game relations; a pre-1950 date is not a C5.1 first_release
    for key in ("developer", "publisher", "series", "features", "platforms", "relations", "first_release"):
        assert key not in meta
    assert meta["links"][0] == {"label": "Atlas record", "url": "https://atlas.test/game/" + BOOK_ID}


def test_a_modern_first_publication_is_also_the_first_release(atlas, monkeypatch):
    record = {**BOOK, "first_release": {"date": "2005", "precision": "year"}}
    meta = book_details(atlas, monkeypatch, record)
    assert meta["book"]["first_published"] == meta["first_release"] == {"date": "2005", "precision": "year"}
    assert meta["year"] == 2005


@pytest.mark.parametrize("first, release_date, expected", [
    (None, "1605", {"date": "1605", "precision": "year"}),            # older Atlas: a year lock in the legacy key
    (None, "1937-06-01", {"date": "1937-06-01", "precision": "day"}),
    ({"date": "0999", "precision": "year"}, None, None),              # outside the host's book years
    ({"date": "2101", "precision": "year"}, None, None),
    ({"date": "1937", "precision": "month"}, None, None),             # precision does not match the shape
    ("1937", None, None),
])
def test_the_first_publication_is_read_at_its_real_precision(atlas, monkeypatch, first, release_date, expected):
    record = {**BOOK, "first_release": first, "release_date": release_date}
    meta = book_details(atlas, monkeypatch, record)
    assert meta["book"].get("first_published") == expected


def test_without_authors_the_developer_is_the_single_author(atlas, monkeypatch):
    record = {key: value for key, value in BOOK.items() if key != "authors"}
    meta = book_details(atlas, monkeypatch, record)
    assert meta["book"]["authors"] == [{"name": "Ada Example", "role": "author"}]


def test_author_entries_are_validated_and_bounded(atlas, monkeypatch):
    authors = ([{"name": "  Ada   Example ", "role": "author"}, "Plain String", {"name": "  "}, {"name": "x\u0000y"},
                {"name": "Future Role", "role": "letterer"}, {"name": "No Role"}, {"name": "Ada Example"},
                {"name": "N" * 201}, 42, None]
               + [{"name": f"Author {n}"} for n in range(40)])
    meta = book_details(atlas, monkeypatch, {**BOOK, "authors": authors})
    got = meta["book"]["authors"]
    assert got[:4] == [{"name": "Ada Example", "role": "author"}, {"name": "Plain String", "role": "author"},
                       {"name": "Future Role", "role": "contributor"}, {"name": "No Role", "role": "author"}]
    assert len(got) == 30 and got[4] == {"name": "Author 0", "role": "author"}


def test_the_series_falls_back_to_the_series_hint_and_then_to_the_name(atlas, monkeypatch):
    base = {**BOOK, "relations": {"members_of": []}}
    meta = book_details(atlas, monkeypatch, {**base, "series": {"name": "Coast Hint", "position": "2.5"}})
    assert (meta["book"]["series_name"], meta["book"]["series_position"]) == ("Coast Hint", "2.5")
    meta = book_details(atlas, monkeypatch, {**base, "series": "Plain Series"})
    assert meta["book"]["series_name"] == "Plain Series" and "series_position" not in meta["book"]
    meta = book_details(atlas, monkeypatch, {**base, "series": {"name": "", "position": "x" * 17}})
    assert "series_name" not in meta["book"] and "series_position" not in meta["book"]


def test_the_series_relation_wins_over_the_hint_and_a_bad_position_is_dropped(atlas, monkeypatch):
    members = [{"id": "atlas:" + "c" * 26, "type": "collection_member", "title": "Box Set"},
               {"id": SERIES_ID, "type": "series_member", "title": "The Fictional Coast", "position": "x" * 17}]
    record = {**BOOK, "relations": {"members_of": members}, "series": {"name": "Hint", "position": "9"}}
    meta = book_details(atlas, monkeypatch, record)
    assert meta["book"]["series_name"] == "The Fictional Coast" and "series_position" not in meta["book"]


def test_editions_are_validated_deduplicated_and_bounded(atlas, monkeypatch):
    editions = [
        {"name": "Bad check digit", "isbn_13": "9780000000003", "isbn_10": ISBN_A10, "format": "paperback"},
        {"name": "Hyphenated", "isbn_13": "978-0-00-000002-6"},
        {"name": "Only ISBN-10", "isbn_10": ISBN_B10},
        {"name": "Repeats an ISBN", "isbn_13": ISBN_B13},
        {"name": "Mismatched pair", "isbn_13": ISBN_A13, "isbn_10": ISBN_B10},
        {"name": "ISBN in provider ids", "provider_ids": {"isbn": ISBN_979}},
        {"name": "Future format", "format": "scroll", "pages": 0, "language": "x" * 17,
         "published": {"date": "1937-02-30", "precision": "day"}},
        {"name": "", "provider_ids": {}},
        "not an edition",
    ] + [{"name": f"Printing {n}"} for n in range(60)]
    meta = book_details(atlas, monkeypatch, {**BOOK, "editions": editions})
    got = meta["book"]["editions"]
    assert got[:6] == [
        {"name": "Bad check digit", "format": "paperback"},
        {"name": "Hyphenated", "isbn_13": ISBN_C13},
        {"name": "Only ISBN-10", "isbn_13": ISBN_B13, "isbn_10": ISBN_B10},
        {"name": "Mismatched pair", "isbn_13": ISBN_A13},
        {"name": "ISBN in provider ids", "isbn_13": ISBN_979},
        {"name": "Future format"}]
    assert len(got) == 50
    isbns = [item["isbn_13"] for item in got if "isbn_13" in item]
    assert len(isbns) == len(set(isbns))


def test_the_matched_isbn_names_its_edition(atlas, monkeypatch):
    meta = book_details(atlas, monkeypatch, selected={**SELECTED, "isbn_13": ISBN_A13})
    assert (meta["book"]["isbn_13"], meta["book"]["isbn_10"]) == (ISBN_A13, ISBN_A10)
    meta = book_details(atlas, monkeypatch, selected={**SELECTED, "isbn_13": ISBN_C13})
    assert "isbn_13" not in meta["book"] and "isbn_10" not in meta["book"]


def test_an_older_atlas_book_maps_from_the_generic_view(atlas, monkeypatch):
    """A node that predates the book view (an admin-made `book` type): developer, edition names, features."""
    record = {"id": BOOK_ID, "media_type": "book", "title": "Plain Book", "developer": "Ada Example",
              "release_date": "1999", "features": ["Fiction"], "series": "The Fictional Coast",
              "editions": [{"name": "Paperback", "provider_ids": {}, "sources": ["manual-books"]}],
              "provider_ids": {"isbn": ISBN_A13}}
    meta = book_details(atlas, monkeypatch, record)
    assert meta["book"] == {"authors": [{"name": "Ada Example", "role": "author"}],
                            "series_name": "The Fictional Coast",
                            "first_published": {"date": "1999", "precision": "year"},
                            "editions": [{"name": "Paperback"}]}
    assert meta["genres"] == ["Fiction"] and meta["year"] == 1999


def test_a_book_has_no_achievements(atlas, monkeypatch):
    gateway = Gateway(monkeypatch, routes={"/games/" + BOOK_ID: {"status": 200, "data": BOOK}})
    assert atlas.metadata({"request": {"resource": "achievements"}, "candidate": SELECTED}) == {}
    assert all(not call["url"].split("?")[0].endswith("/achievements") for call in gateway.calls)


def test_a_book_cover_is_a_poster(atlas, monkeypatch):
    digest = "c" * 64
    Gateway(monkeypatch, routes={
        "/games/" + BOOK_ID: {"status": 200, "data": BOOK},
        "/artwork": {"status": 200, "data": {"results": [
            {"kind": "key_art", "media_url": f"/api/v2/media/{digest}"},
            {"kind": "poster", "media_url": f"/api/v2/media/{digest}"}]}}})
    assets = atlas.media({"request": {}, "candidate": SELECTED})["assets"]
    assert [asset["kind"] for asset in assets] == ["poster", "poster"]


def test_a_game_never_carries_a_book_key(atlas, monkeypatch):
    game = {**BOOK, "media_type": "game", "id": BOOK_ID}
    meta = book_details(atlas, monkeypatch, game, selected={**SELECTED, "media_type": "game"})
    assert "book" not in meta


# --- the declared contract is the switch ---

def test_under_an_older_declaration_books_are_neither_searched_nor_mapped(atlas, monkeypatch):
    older_contract(atlas, monkeypatch)
    gateway = Gateway(monkeypatch, routes={"/api/v2/games": {"status": 200, "data": {"results": [BOOK]}},
                                           "/games/" + BOOK_ID: {"status": 200, "data": BOOK}})
    assert atlas.search({"request": {"query": "lighthouse", "media_type": "book"}}) == {
        "failure": {"code": "invalid_response"}}
    assert atlas.metadata({"request": {}, "candidate": SELECTED}) == {}
    assert atlas.media({"request": {}, "candidate": SELECTED}) == {"assets": []}
    assert gateway.calls == []


def test_under_an_older_declaration_a_game_search_drops_book_records(atlas, monkeypatch):
    older_contract(atlas, monkeypatch)
    Gateway(monkeypatch, routes={"/api/v2/games": {"status": 200, "data": {"results": [BOOK]}}})
    result = atlas.search({"request": {"query": "lighthouse", "media_type": "game"}})
    assert result == {"candidates": []}
