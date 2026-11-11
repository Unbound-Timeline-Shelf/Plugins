"""Open Library provider (C15 §3, D15.9, T-P2): keyless book search, the ISBN lookup, work details, editions and
covers, replayed against the synthetic fixtures in tests/fixtures/openlibrary (pinned by SHA-256)."""
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import jsonschema
import pytest

from sdk import metadata_provider as sdk

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "official" / "metadata-openlibrary"
FIXTURES = ROOT / "tests" / "fixtures" / "openlibrary"
RESPONSE_SCHEMA = json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text(encoding="utf-8"))
REGISTRATION_SCHEMA = json.loads(
    (ROOT / "tools/schemas/metadata-registration-v1.schema.json").read_text(encoding="utf-8"))
PROVIDER = "official.metadata-openlibrary.openlibrary"
W1, W2, W3, W4 = "OL900000001W", "OL900000002W", "OL900000003W", "OL900000004W"
SELECTED = {"provider": PROVIDER, "external_id": W1, "title": "The Synthetic Lighthouse", "media_type": "book",
            "year": 1937, "provider_ids": {"openlibrary": W1}, "authors": ["Ada Example", "B. Placeholder"]}


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def openlibrary(monkeypatch):
    monkeypatch.syspath_prepend(str(PLUGIN_DIR))
    monkeypatch.delitem(__import__("sys").modules, "books", raising=False)
    spec = importlib.util.spec_from_file_location("metadata_test_openlibrary", PLUGIN_DIR / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Gateway:
    """The host gateway as the plugin sees it: configuration, pacing storage and mediated GETs answered from the
    fixtures by path (and, for the ISBN lookup and a key search, by query)."""

    def __init__(self, monkeypatch, contact=None, overrides=None):
        self.contact = contact
        self.overrides = overrides or {}
        self.calls = []
        monkeypatch.setattr(sdk, "request", self)

    def __call__(self, method, capability, payload=None):
        if method == "metadata_providers.configuration":
            assert payload == {"provider_id": PROVIDER}
            return {"values": {"contact": self.contact} if self.contact is not None else {}}
        if method == "storage.get":
            return {"value": None}
        if method == "storage.compare_and_swap":
            return {"swapped": True}
        assert method == "network.request" and capability == "network.outbound"
        self.calls.append(payload)
        parts = urlsplit(payload["url"])
        assert parts.scheme == "https" and parts.hostname == "openlibrary.org", payload["url"]
        query = parse_qs(parts.query)
        if parts.path in self.overrides:
            return self.overrides[parts.path]
        name = None
        if parts.path == "/search.json":
            q = query["q"][0]
            name = (f"search_key_{q.split('/')[-1].rstrip(chr(34))}.json" if q.startswith("key:")
                    else "search_lighthouse.json" if "lighthouse" in q or q == "library" else "search_empty.json")
        elif parts.path == "/api/books":
            name = f"books_isbn_{query['bibkeys'][0].removeprefix('ISBN:')}.json"
        elif parts.path.startswith("/works/") and parts.path.endswith("/editions.json"):
            name = f"editions_{parts.path.split('/')[2]}.json"
        elif parts.path.startswith("/works/"):
            name = f"work_{parts.path.split('/')[2].removesuffix('.json')}.json"
        elif parts.path.startswith("/books/"):
            name = f"edition_{parts.path.split('/')[2].removesuffix('.json')}.json"
        if name and (FIXTURES / name).exists():
            return {"status": 200, "data": fixture(name)}
        if parts.path == "/api/books":
            return {"status": 200, "data": fixture("books_isbn_unknown.json")}
        return {"status": 404, "error": "Remote server rejected the request."}

    def paths(self):
        return [urlsplit(call["url"]).path for call in self.calls]


def valid(response):
    jsonschema.validate(response, RESPONSE_SCHEMA)
    return response


# --- package, declaration and fixtures ---------------------------------------------------------------------------
def test_fixtures_are_pinned_by_sha256():
    """T-P2: every fixture is listed in SHA256SUMS with its digest over LF bytes, and nothing else is there."""
    pinned = {}
    for row in (FIXTURES / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = row.split()
        pinned[name] = digest
    present = {path.name for path in FIXTURES.glob("*.json")}
    assert set(pinned) == present
    for name, digest in pinned.items():
        assert hashlib.sha256((FIXTURES / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest, name


def test_declaration_is_book_only_keyless_and_matches_the_public_schema(openlibrary):
    jsonschema.validate(openlibrary.DECLARATION, REGISTRATION_SCHEMA)
    assert openlibrary.DECLARATION["media_types"] == ["book"]
    assert openlibrary.DECLARATION["identifier_namespace"] == "openlibrary"
    # keyless: the only configuration is an optional, non-secret, administrator-chosen contact
    assert openlibrary.DECLARATION["configuration"] == [
        {"key": "contact", "label": "Contact e-mail or URL sent to Open Library (optional)", "scope": "system",
         "required": False, "secret": False}]
    manifest = json.loads((PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
    document = json.loads((PLUGIN_DIR / "ui.json").read_text(encoding="utf-8"))
    assert manifest["api_contract_version"] == document["api_contract_version"] == "1.1.20"
    assert openlibrary.API_CONTRACT == openlibrary.UNIFIED_CONTRACT == (1, 1, 20)
    assert openlibrary.VERSION == manifest["version"]
    declared = {item["name"] for item in manifest["capabilities"]}
    assert declared == {item["capability"]["name"] for item in manifest["permissions"]}
    assert declared == {"metadata_providers.register", "metadata_providers.search", "metadata_providers.metadata",
                        "metadata_providers.media", "metadata_providers.health", "network.outbound",
                        "plugin.storage", "metadata_providers.configuration"}
    assert set(manifest["ui"]["actions"]) == {action["id"] for action in document["actions"]} \
        == set(openlibrary.DECLARATION["operations"].values())
    for action in document["actions"]:
        assert callable(getattr(openlibrary, action["handler"].split(":")[1]))


def test_an_older_declaration_serves_nothing_and_refuses_to_start(openlibrary, monkeypatch):
    gateway = Gateway(monkeypatch)
    monkeypatch.setattr(openlibrary, "API_CONTRACT", (1, 1, 19))
    assert openlibrary.search({"request": {"query": "lighthouse", "media_type": "book"}}) == {"candidates": []}
    assert openlibrary.metadata({"request": {}, "candidate": SELECTED}) == {}
    assert openlibrary.media({"request": {}, "candidate": SELECTED}) == {"assets": []}
    assert gateway.calls == []
    with pytest.raises(RuntimeError, match="1.1.20"):
        openlibrary.main()


# --- search -------------------------------------------------------------------------------------------------------
def test_search_lists_works_with_authors_and_pages(openlibrary, monkeypatch):
    gateway = Gateway(monkeypatch)
    result = valid(openlibrary.search({"request": {"query": "synthetic lighthouse", "media_type": "book",
                                                   "limit": 5}}))
    assert result["candidates"] == [
        {"provider": PROVIDER, "external_id": W1, "title": "The Synthetic Lighthouse", "media_type": "book",
         "year": 1937, "provider_ids": {"openlibrary": W1}, "authors": ["Ada Example", "B. Placeholder"],
         "alternate_titles": ["The Synthetic Lighthouse: A Coastal Novel"]},
        {"provider": PROVIDER, "external_id": W2, "title": "The Synthetic Lighthouse Keeper", "media_type": "book",
         "year": None, "provider_ids": {"openlibrary": W2}, "authors": ["C. Sample"]},
        # 1605 is outside the host's candidate years (1800-3000): no year rather than a wrong one
        {"provider": PROVIDER, "external_id": W3, "title": "An Older Synthetic Almanac", "media_type": "book",
         "year": None, "provider_ids": {"openlibrary": W3}, "authors": ["D. Fixture"]},
    ]
    assert result["next_cursor"] == "2"
    [call] = gateway.calls
    query = parse_qs(urlsplit(call["url"]).query)
    assert query["q"] == ["synthetic lighthouse"] and query["limit"] == ["5"] and query["page"] == ["1"]
    assert "isbn" not in query["fields"][0].split(",")  # C15 §3.1: never requested from search
    agent = call["headers"]["User-Agent"]
    assert agent.startswith("unnamed-tracking-app/1.0 metadata-openlibrary/0.1.0 (+https://github.com/")
    assert "@" not in agent and agent.endswith("Plugins)")


def test_search_last_page_and_empty_and_other_media(openlibrary, monkeypatch):
    gateway = Gateway(monkeypatch)
    last = openlibrary.search({"request": {"query": "synthetic lighthouse", "media_type": "book", "limit": 5,
                                           "cursor": "9"}})
    assert last["next_cursor"] is None  # 9 * 5 >= 45 results
    assert valid(openlibrary.search({"request": {"query": "nothing at all", "media_type": "book"}})) == {
        "candidates": [], "next_cursor": None}
    calls = len(gateway.calls)
    for media_type in ("game", "movie", "tv_show", "anime"):
        assert openlibrary.search({"request": {"query": "lighthouse", "media_type": media_type}}) == {
            "candidates": []}
    assert openlibrary.search({"request": {"query": "lighthouse"}}) == {"candidates": []}
    assert len(gateway.calls) == calls
    assert openlibrary.search({"request": {"query": "x", "media_type": "book", "cursor": "21"}}) == {
        "failure": {"code": "invalid_response"}}


@pytest.mark.parametrize("option", ["9780000000019", "978-0-00-000001-9", "0000000019", "0-00-000001-9"])
def test_isbn_option_is_an_identifier_lookup(openlibrary, monkeypatch, option):
    """C15 §6.2: the reserved `isbn` option asks /api/books (the /isbn/ path redirects, which the host refuses)
    and answers the work that holds the edition, never a title search."""
    gateway = Gateway(monkeypatch)
    result = valid(openlibrary.search({"request": {"query": "anything", "media_type": "book",
                                                   "options": {"isbn": option}}}))
    assert result == {"candidates": [
        {"provider": PROVIDER, "external_id": W1, "title": "The Synthetic Lighthouse", "media_type": "book",
         "year": None, "provider_ids": {"openlibrary": W1}, "isbn_13": "9780000000019",
         "authors": ["Ada Example"]}]}
    assert gateway.paths() == ["/api/books"]
    assert parse_qs(urlsplit(gateway.calls[0]["url"]).query) == {
        "bibkeys": ["ISBN:9780000000019"], "format": ["json"], "jscmd": ["details"]}


def test_isbn_lookup_unknown_invalid_and_typed(openlibrary, monkeypatch):
    gateway = Gateway(monkeypatch)
    assert openlibrary.search({"request": {"query": "x", "media_type": "book",
                                           "options": {"isbn": "9780000000057"}}}) == {"candidates": []}
    assert gateway.paths() == ["/api/books"]
    # a malformed ISBN option lists nothing and makes no request (no title fallback)
    assert openlibrary.search({"request": {"query": "lighthouse", "media_type": "book",
                                           "options": {"isbn": "9780000000003"}}}) == {"candidates": []}
    assert gateway.paths() == ["/api/books"]
    # an ISBN typed as the query (a host without the option) is still an identifier lookup
    typed = openlibrary.search({"request": {"query": "978 0 00 000001 9", "media_type": "book"}})
    assert [item["isbn_13"] for item in typed["candidates"]] == ["9780000000019"]
    assert gateway.paths() == ["/api/books", "/api/books"]


# --- metadata -----------------------------------------------------------------------------------------------------
EXPECTED_EDITIONS = [
    {"key": "OL900000012M", "name": "Paperback, Example Press 2005", "isbn_13": "9780000000019",
     "format": "paperback", "publisher": "Example Press",
     "publish_date": {"date": "2005-08-01", "precision": "day"}, "page_count": 528, "language": "eng"},
    # OL900000016M repeats 9780000000019 and is older: collapsed into the edition above
    {"key": "OL900000014M", "name": "Mass Market Paperback, Pocket Example 1950", "isbn_13": "9780000000026",
     "isbn_10": "0000000027", "format": "paperback", "publisher": "Pocket Example",
     "publish_date": {"date": "1950", "precision": "year"}},
    {"key": "OL900000013M", "name": "First edition", "isbn_13": "9780000000002", "isbn_10": "0000000000",
     "format": "hardcover", "publisher": "Example Press", "publish_date": {"date": "1937-06", "precision": "month"},
     "page_count": 412, "language": "eng"},
    # without an ISBN, newest first; a wrong ISBN-13 check digit drops the edition's ISBN pair
    {"key": "OL900000011M", "name": "Audio CD, Example Audio 2019", "format": "audiobook",
     "publisher": "Example Audio", "publish_date": {"date": "2019", "precision": "year"}, "language": "eng"},
    {"key": "OL900000015M", "name": "E-book, Example Digital 2015", "format": "ebook",
     "publisher": "Example Digital", "publish_date": {"date": "2015-03-02", "precision": "day"}},
    # an unreadable date and a zero page count are left out; the free-text format is `other`
    {"key": "OL900000017M", "name": "Scroll", "format": "other"},
]


def test_metadata_maps_the_work_and_its_editions(openlibrary, monkeypatch):
    gateway = Gateway(monkeypatch)
    result = valid(openlibrary.metadata({"request": {}, "candidate": SELECTED}))
    patch = result["metadata"]
    assert patch["title"] == "The Synthetic Lighthouse"
    assert patch["year"] == 1937
    assert patch["description"].startswith("A lighthouse keeper") and "\r" not in patch["description"]
    assert patch["genres"] == [f"Synthetic subject {n:02d}" for n in range(1, 11)]
    assert patch["tags"] == ["Synthetic subject 11", "Synthetic subject 12", "Fiction"]
    assert patch["provider_ids"] == {"openlibrary": W1}
    assert patch["links"] == [{"label": "Open Library", "url": f"https://openlibrary.org/works/{W1}"}]
    assert "identity" not in patch and "first_release" not in patch
    assert patch["book"] == {
        "authors": [{"name": "Ada Example", "role": "author"}, {"name": "B. Placeholder", "role": "author"}],
        "subtitle": "A Coastal Novel", "first_published": {"date": "1937-06", "precision": "month"},
        "editions": EXPECTED_EDITIONS}
    # the selected candidate's authors are used: two requests, no per-author lookups
    assert gateway.paths() == [f"/works/{W1}.json", f"/works/{W1}/editions.json"]
    assert parse_qs(urlsplit(gateway.calls[1]["url"]).query) == {"limit": ["50"]}


def test_metadata_without_candidate_authors_searches_the_work_key_once(openlibrary, monkeypatch):
    gateway = Gateway(monkeypatch)
    selected = {"provider": PROVIDER, "external_id": W4, "title": "A Synthetic Anthology", "media_type": "book"}
    book = valid(openlibrary.metadata({"request": {}, "candidate": selected}))["metadata"]["book"]
    assert [author["name"] for author in book["authors"]] == [f"Contributor {n:02d}" for n in range(1, 31)]
    assert book["first_published"] == {"date": "2001", "precision": "year"}
    assert gateway.paths() == [f"/works/{W4}.json", f"/works/{W4}/editions.json", "/search.json"]
    assert parse_qs(urlsplit(gateway.calls[2]["url"]).query)["q"] == [f'key:"/works/{W4}"']


def test_metadata_for_an_isbn_match_names_that_edition_first(openlibrary, monkeypatch):
    gateway = Gateway(monkeypatch)
    chosen = {**SELECTED, "isbn_13": "9780000000002", "year": None}
    book = valid(openlibrary.metadata({"request": {}, "candidate": chosen}))["metadata"]["book"]
    assert book["isbn_13"] == "9780000000002" and book["isbn_10"] == "0000000000" and book["page_count"] == 412
    assert [edition["key"] for edition in book["editions"]] == [
        "OL900000013M", "OL900000012M", "OL900000014M", "OL900000011M", "OL900000015M", "OL900000017M"]
    assert len(gateway.calls) == 2


def test_metadata_fetches_a_matched_edition_missing_from_the_first_fifty(openlibrary, monkeypatch):
    gateway = Gateway(monkeypatch)
    chosen = {**SELECTED, "isbn_13": "9780000000040"}
    book = valid(openlibrary.metadata({"request": {}, "candidate": chosen}))["metadata"]["book"]
    assert book["editions"][0] == {
        "key": "OL900000019M", "name": "Anniversary edition", "isbn_13": "9780000000040", "format": "hardcover",
        "publisher": "Example Press", "publish_date": {"date": "2037", "precision": "year"}, "page_count": 430}
    assert book["isbn_13"] == "9780000000040" and book["page_count"] == 430 and "isbn_10" not in book
    assert gateway.paths()[-1] == "/api/books"


def test_metadata_follows_one_work_redirect_and_reports_it(openlibrary, monkeypatch):
    gateway = Gateway(monkeypatch)
    merged = {"provider": PROVIDER, "external_id": "OL900000009W", "title": "Old", "media_type": "book",
              "provider_ids": {"openlibrary": "OL900000009W"}}
    patch = valid(openlibrary.metadata({"request": {}, "candidate": merged}))["metadata"]
    assert patch["provider_ids"] == {"openlibrary": W1}
    assert patch["identity"] == {"match": "redirect", "previous_ids": {"openlibrary": "OL900000009W"}}
    assert gateway.paths()[:2] == ["/works/OL900000009W.json", f"/works/{W1}.json"]
    # a chain of redirects is not followed
    chain = {**merged, "external_id": "OL900000008W", "provider_ids": {"openlibrary": "OL900000008W"}}
    assert openlibrary.metadata({"request": {}, "candidate": chain}) == {}


@pytest.mark.parametrize("value", ["OL900000001A", "OL0W", "works/OL1W", "OL12345678901W", "", "9780000000003"])
def test_metadata_refuses_an_id_that_is_not_a_work_edition_or_isbn_before_any_request(openlibrary, monkeypatch,
                                                                                      value):
    gateway = Gateway(monkeypatch)
    selected = {"provider": PROVIDER, "external_id": value or "x", "title": "x", "media_type": "book",
                "provider_ids": {"openlibrary": value} if value else {}}
    assert openlibrary.metadata({"request": {}, "candidate": selected}) == {}
    assert gateway.calls == []


def test_metadata_from_an_edition_id_or_another_providers_isbn(openlibrary, monkeypatch):
    gateway = Gateway(monkeypatch)
    by_edition = {"provider": PROVIDER, "external_id": "OL900000012M", "title": "x", "media_type": "book"}
    assert openlibrary.metadata({"request": {}, "candidate": by_edition})["metadata"]["provider_ids"] == {
        "openlibrary": W1}
    assert gateway.paths()[0] == "/books/OL900000012M.json"
    gateway.calls.clear()
    other = {"provider": "official.metadata-atlas.atlas", "external_id": "atlas:" + "k" * 26, "title": "x",
             "media_type": "book", "isbn_13": "9780000000019"}
    patch = openlibrary.metadata({"request": {}, "candidate": other})["metadata"]
    assert patch["provider_ids"] == {"openlibrary": W1} and patch["book"]["isbn_13"] == "9780000000019"
    assert gateway.paths()[0] == "/api/books"


def test_metadata_without_dates_covers_or_authors(openlibrary, monkeypatch):
    Gateway(monkeypatch)
    plain = {"provider": PROVIDER, "external_id": W2, "title": "x", "media_type": "book"}
    patch = valid(openlibrary.metadata({"request": {}, "candidate": plain}))["metadata"]
    assert patch == {"title": "The Synthetic Lighthouse Keeper", "description": "A plain-string description.",
                     "provider_ids": {"openlibrary": W2},
                     "links": [{"label": "Open Library", "url": f"https://openlibrary.org/works/{W2}"}]}
    # search's first_publish_year stands in when the work has no date, at year precision only
    dated = valid(openlibrary.metadata({"request": {}, "candidate": {**plain, "year": 1990}}))["metadata"]
    assert dated["book"] == {"first_published": {"date": "1990", "precision": "year"}} and dated["year"] == 1990
    assert openlibrary.media({"request": {}, "candidate": plain}) == {"assets": []}


def test_metadata_takes_the_first_year_from_search_when_the_work_has_no_date(openlibrary, monkeypatch):
    """An ISBN candidate carries no year: a work without `first_publish_date` asks search for its
    `first_publish_year` once, at year precision only. Its authors are the ISBN lookup's."""
    work = fixture(f"work_{W1}.json")
    del work["first_publish_date"]
    gateway = Gateway(monkeypatch, overrides={f"/works/{W1}.json": {"status": 200, "data": work}})
    chosen = valid(openlibrary.search({"request": {"query": "x", "media_type": "book",
                                                   "options": {"isbn": "9780000000019"}}}))["candidates"][0]
    patch = valid(openlibrary.metadata({"request": {}, "candidate": chosen}))["metadata"]
    assert patch["book"]["first_published"] == {"date": "1937", "precision": "year"} and patch["year"] == 1937
    assert patch["book"]["authors"] == [{"name": "Ada Example", "role": "author"}]
    assert gateway.paths() == ["/api/books", f"/works/{W1}.json", f"/works/{W1}/editions.json", "/search.json"]


def test_metadata_keeps_old_dates_as_book_dates_only(openlibrary, monkeypatch):
    Gateway(monkeypatch)
    old = {"provider": PROVIDER, "external_id": W3, "title": "x", "media_type": "book", "authors": ["D. Fixture"],
           "provider_ids": {"openlibrary": W3}}
    patch = valid(openlibrary.metadata({"request": {}, "candidate": old}))["metadata"]
    assert patch["book"]["first_published"] == {"date": "1605-08-01", "precision": "day"}
    assert "year" not in patch  # the host's year starts at 1800


def test_metadata_ignores_other_media_and_resources(openlibrary, monkeypatch):
    gateway = Gateway(monkeypatch)
    assert openlibrary.metadata({"request": {}, "candidate": {**SELECTED, "media_type": "game"}}) == {}
    assert openlibrary.metadata({"request": {"resource": "episodes"}, "candidate": SELECTED}) == {}
    assert gateway.calls == []


def test_metadata_stays_under_the_action_output_limit(openlibrary, monkeypatch):
    work = fixture(f"work_{W1}.json")
    work["description"] = "Ω " * 40_000
    entries = [{"key": f"/books/OL9000{n:05d}M", "edition_name": "E" * 200, "publishers": ["P" * 200],
                "physical_format": "Paperback", "publish_date": "2001"} for n in range(1, 60)]
    Gateway(monkeypatch, overrides={f"/works/{W1}.json": {"status": 200, "data": work},
                                    f"/works/{W1}/editions.json": {"status": 200, "data": {"entries": entries}}})
    result = valid(openlibrary.metadata({"request": {}, "candidate": SELECTED}))
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= openlibrary.RESULT_BYTES
    # the description gives way first; all 50 editions (the host's cap) stay
    assert len(result["metadata"]["book"]["editions"]) == 50
    assert openlibrary.DESCRIPTION_FLOOR <= len(result["metadata"]["description"]) < 50_000
    # with a longer edition list than the limit allows even after that, editions go from the end
    patch = {"description": "d" * 10_000, "book": {"editions": [{"name": "E" * 200, "publisher": "P" * 200}] * 400}}
    fitted = openlibrary.fit(patch)
    assert len(json.dumps({"metadata": fitted}).encode()) <= openlibrary.RESULT_BYTES
    assert len(fitted["description"]) == openlibrary.DESCRIPTION_FLOOR and 0 < len(fitted["book"]["editions"]) < 400


def test_search_stays_under_the_action_output_limit(openlibrary, monkeypatch):
    """Open Library records are user-editable: a page of 50 works with 500-character titles and subtitles and 30
    long author names each would exceed the runtime's 64 KiB limit. Alternate titles go first, then candidates
    from the end; author lists are never shortened (metadata stores the selected candidate's authors)."""
    docs = [{"key": f"/works/OL9{n:08d}W", "title": f"{n:03d} " + "T" * 240, "subtitle": "S" * 240,
             "author_name": [f"{a:02d} " + "A" * 190 for a in range(30)], "first_publish_year": 2001}
            for n in range(50)]
    Gateway(monkeypatch, overrides={"/search.json": {"status": 200, "data": {"numFound": 5000, "docs": docs}}})
    result = valid(openlibrary.search({"request": {"query": "anthology", "media_type": "book", "limit": 50}}))
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= openlibrary.RESULT_BYTES
    candidates = result["candidates"]
    assert 0 < len(candidates) < 50
    assert [item["title"][:3] for item in candidates] == [f"{n:03d}" for n in range(len(candidates))]
    assert all(len(item["authors"]) == 30 and "alternate_titles" not in item for item in candidates)
    assert result["next_cursor"] == "2"
    # a page under the limit is untouched
    small = {"candidates": [{"title": "x", "alternate_titles": ["x: y"]}], "next_cursor": None}
    assert openlibrary.fit_search(small) == {"candidates": [{"title": "x", "alternate_titles": ["x: y"]}],
                                             "next_cursor": None}


# --- media, health, failures and identification -------------------------------------------------------------------
def test_media_offers_the_first_real_cover_by_id(openlibrary, monkeypatch):
    gateway = Gateway(monkeypatch)
    assert valid(openlibrary.media({"request": {}, "candidate": SELECTED})) == {
        "assets": [{"kind": "poster", "url": "https://covers.openlibrary.org/b/id/9000001-L.jpg"}]}
    assert gateway.paths() == [f"/works/{W1}.json"]
    assert openlibrary.media({"request": {}, "candidate": {**SELECTED, "media_type": "movie"}}) == {"assets": []}


def test_health_and_rate_limits(openlibrary, monkeypatch):
    Gateway(monkeypatch)
    assert openlibrary.health({"request": {}}) == {"health": "healthy"}
    Gateway(monkeypatch, overrides={"/search.json": fixture("http_429.json")})
    limited = openlibrary.search({"request": {"query": "lighthouse", "media_type": "book"}})
    assert valid(limited) == {"failure": {"code": "rate_limited", "retry_after_seconds": 30}}
    assert openlibrary.health({"request": {}}) == limited


def test_contact_identifies_the_client_only_when_an_administrator_sets_it(openlibrary, monkeypatch):
    gateway = Gateway(monkeypatch, contact=" books@example.test ")
    paces = []
    original = sdk.ProviderHttp.__init__

    def record(self, work, namespace, *, min_gap=0):
        paces.append((namespace, min_gap))
        original(self, work, namespace, min_gap=min_gap)

    monkeypatch.setattr(sdk.ProviderHttp, "__init__", record)
    openlibrary.search({"request": {"query": "lighthouse", "media_type": "book"}})
    assert gateway.calls[0]["headers"]["User-Agent"].endswith("Plugins; books@example.test)")
    Gateway(monkeypatch)
    openlibrary.search({"request": {"query": "lighthouse", "media_type": "book"}})
    assert paces == [("openlibrary", openlibrary.GAP_IDENTIFIED), ("openlibrary", openlibrary.GAP_ANONYMOUS)]
    # only visible ASCII: control characters, DEL, NEL, U+2028 and other non-ASCII characters are refused here as
    # a configuration error rather than failing every request in the host's HTTP layer
    for bad in ("not a contact", "x@y; z", "http://insecure.example", "a@b\r\nX-Injected: 1", "a@b\x00c",
                "a@b\x85c", "a@b c", "https://x\x7f", "https://exämple.test", "bücher@example.test",
                "a@b\tc"):
        Gateway(monkeypatch, contact=bad)
        assert openlibrary.search({"request": {"query": "lighthouse", "media_type": "book"}}) == {
            "failure": {"code": "invalid_configuration"}}


# --- pure mapping ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("value,expected", [
    ("1965", ("1965", "year")), ("c1965", ("1965", "year")), ("c. 1965", ("1965", "year")),
    ("[1965]", ("1965", "year")), ("©1965", ("1965", "year")), ("1965.", ("1965", "year")),
    ("August 1965", ("1965-08", "month")), ("Aug. 1965", ("1965-08", "month")), ("Sept 1965", ("1965-09", "month")),
    ("Aug 01, 1965", ("1965-08-01", "day")), ("August 1 1965", ("1965-08-01", "day")),
    ("1 August 1965", ("1965-08-01", "day")), ("1965-08", ("1965-08", "month")), ("1965-08-01", ("1965-08-01", "day")),
    ("1605", ("1605", "year")),
    ("1965?", None), ("196-", None), ("Feb 30, 1965", None), ("1965-13", None), ("Spring 1965", None),
    ("0999", None), ("2101", None), ("", None), (None, None), (1965, None), ("sometime around 1990?", None),
])
def test_free_text_dates_keep_only_the_precision_they_prove(openlibrary, value, expected):
    found = openlibrary.books.parse_loose(value)
    assert (found and (found["date"], found["precision"])) == expected if expected else found is None


@pytest.mark.parametrize("value,expected", [
    ("Paperback", "paperback"), ("Mass Market Paperback", "paperback"), ("Hardcover", "hardcover"),
    ("Library Binding", "hardcover"), ("E-book", "ebook"), ("Kindle Edition", "ebook"), ("Audio CD", "audiobook"),
    ("MP3 CD", "audiobook"), ("Scroll", "other"), ("", None), (None, None),
])
def test_physical_format_maps_to_the_shared_vocabulary(openlibrary, value, expected):
    assert openlibrary.books.book_format(value) == expected
