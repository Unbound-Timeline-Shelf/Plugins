"""Open Library book metadata: keyless search, ISBN lookup, work details, editions and covers.

CONTRACT-C15 §3 (Open Library as the first keyless book provider) and D15.9 (a host plugin for hosts without
Atlas). Books need Plugin API 1.1.20 (the one unified bump, C15 §6.4), which this package declares.
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urlencode

import books
from sdk.metadata_provider import ProviderFailure, ProviderHttp, external_id, operation, provider_values, register

PROVIDER_ID = "official.metadata-openlibrary.openlibrary"
NAMESPACE = "openlibrary"
BASE_URL = "https://openlibrary.org"
COVER_URL = "https://covers.openlibrary.org/b/id/{}-L.jpg"
PROJECT_URL = "https://github.com/Unbound-Timeline-Shelf/Plugins"
# `isbn` is not requested from search (C15 §3.1): a popular work lists hundreds of ISBNs per document.
SEARCH_FIELDS = "key,title,subtitle,author_name,first_publish_year,cover_i,edition_count"
MAX_SEARCH_PAGES = 20
# Open Library asks for at most about one request a second from an unidentified client and allows more to a
# client that names a contact (C15 §3.2 [L]); the per-provider pacing below follows it.
GAP_ANONYMOUS, GAP_IDENTIFIED = 1.0, 0.34
# Visible ASCII only (no space, control, DEL or non-ASCII character), without the characters that would end the
# User-Agent comment or the address: `"();<>` and, in the e-mail parts, `@`.
_MAILBOX = r"[\x21\x23-\x27\x2a-\x3a\x3d\x3f\x41-\x7e]"
_URL = r"[\x21\x23-\x27\x2a-\x3a\x3d\x3f-\x7e]"
CONTACT = re.compile(rf"{_MAILBOX}{{1,64}}@{_MAILBOX}{{1,190}}|https://{_URL}{{1,190}}")
# Below the runtime's 64 KiB action output limit, measured as json.dumps of the whole result.
RESULT_BYTES = 56 * 1024
DESCRIPTION_FLOOR = 4000
# Plugin API 1.1.20 (C15 §6.3-§6.4): the `book` media type, `MetadataPatch.book` and a candidate's `authors` and
# `isbn_13`. The one bump of this release; there is no later book contract.
UNIFIED_CONTRACT = (1, 1, 20)


def _manifest():
    try:
        return json.loads(Path(__file__).with_name("manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def declared_contract():
    """The Plugin API contract this package declares in its own manifest, or None when it cannot be read.

    The host validates every response against it, so it is the feature switch (P3): the plugin never asks the
    host for its version."""
    parts = str(_manifest().get("api_contract_version", "")).split(".")
    if len(parts) != 3 or not all(part.isascii() and part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


API_CONTRACT = declared_contract()
VERSION = str(_manifest().get("version", "0"))


def sends_books():
    """Whether this package may declare and serve `book` (it serves nothing else)."""
    return API_CONTRACT is not None and API_CONTRACT >= UNIFIED_CONTRACT


DECLARATION = {
    "provider_id": PROVIDER_ID, "name": "Open Library", "identifier_namespace": NAMESPACE,
    "media_types": ["book"],
    "metadata_resources": ["entity"],
    "operations": {"search": "search", "metadata": "metadata", "media": "media", "health": "health"},
    # Keyless. The optional contact is sent to Open Library only when an administrator sets it (C15 D15.7).
    "configuration": [
        {"key": "contact", "label": "Contact e-mail or URL sent to Open Library (optional)", "scope": "system",
         "required": False, "secret": False},
    ],
}


class OpenLibrary:
    """Paced, identified GET requests to openlibrary.org through the host's mediated network.

    The host follows no redirects (`network.request`), so every endpoint used here answers directly: ISBNs go
    through `/api/books` rather than `/isbn/{isbn}.json`, which redirects."""

    def __init__(self, work):
        contact = (provider_values(PROVIDER_ID, ()).get("contact") or "").strip()
        if contact and not CONTACT.fullmatch(contact):
            raise ProviderFailure("invalid_configuration")
        self.agent = f"unnamed-tracking-app/1.0 metadata-openlibrary/{VERSION} (+{PROJECT_URL}" + (
            f"; {contact})" if contact else ")")
        self.http = ProviderHttp(work, "openlibrary", min_gap=GAP_IDENTIFIED if contact else GAP_ANONYMOUS)

    def get(self, path, **query):
        data = self.http(BASE_URL + path + ("?" + urlencode(query) if query else ""),
                         headers={"User-Agent": self.agent})
        if not isinstance(data, dict):
            raise ProviderFailure("invalid_response")
        return data


# --- search ---------------------------------------------------------------------------------------------------------
def search_candidate(doc):
    """One `search.json` document as a book candidate, or None without a work id or a title."""
    if not isinstance(doc, dict):
        return None
    work_id = books.key_id(doc.get("key"), books.WORK_ID)
    title = books.line(doc.get("title"), books.MAX_TITLE)
    if not work_id or not title:
        return None
    out = {"provider": PROVIDER_ID, "external_id": work_id, "title": title, "media_type": "book",
           "year": books.candidate_year(doc.get("first_publish_year")), "provider_ids": {NAMESPACE: work_id}}
    names = [author["name"] for author in books.authors(doc.get("author_name"))]
    if names:
        out["authors"] = names
    subtitle = books.line(doc.get("subtitle"), books.MAX_TITLE)
    if subtitle and len(f"{title}: {subtitle}") <= books.MAX_TITLE:
        out["alternate_titles"] = [f"{title}: {subtitle}"]
    return out


def isbn_edition(client, isbn):
    """The edition record Open Library holds for an ISBN-13 (`/api/books`, one request), or None."""
    data = client.get("/api/books", bibkeys="ISBN:" + isbn, format="json", jscmd="details")
    entry = data.get("ISBN:" + isbn)
    details = entry.get("details") if isinstance(entry, dict) else None
    return details if isinstance(details, dict) else None


def edition_work_id(details):
    works = details.get("works") if isinstance(details.get("works"), list) else []
    return books.key_id(works[0].get("key") if works and isinstance(works[0], dict) else None, books.WORK_ID)


def isbn_candidates(client, isbn):
    """The reserved `isbn` option (C15 §6.2): an identifier lookup, never a title search. The work that holds the
    edition, with `isbn_13` naming that edition; nothing when Open Library does not know the ISBN."""
    details = isbn_edition(client, isbn)
    work_id = details and edition_work_id(details)
    title = details and books.line(details.get("title"), books.MAX_TITLE)
    if not work_id or not title:
        return []
    out = {"provider": PROVIDER_ID, "external_id": work_id, "title": title, "media_type": "book", "year": None,
           "provider_ids": {NAMESPACE: work_id}, "isbn_13": isbn}
    raw = details.get("authors") if isinstance(details.get("authors"), list) else []
    names = [author["name"] for author in books.authors([item.get("name") for item in raw if isinstance(item, dict)])]
    if names:
        out["authors"] = names
    return [out]


@operation
def search(values):
    work = values["request"]
    if work.get("media_type", "game") != "book" or not sends_books():
        return {"candidates": []}
    options = work.get("options") if isinstance(work.get("options"), dict) else {}
    client = OpenLibrary(work)
    if options.get("isbn") not in (None, ""):
        # The host's normalised ISBN-13; a malformed one lists nothing and never becomes a title search.
        isbn = books.lookup_isbn(options["isbn"])
        return {"candidates": isbn_candidates(client, isbn) if isbn else []}
    typed = books.lookup_isbn(work.get("query"))
    if typed:
        # A host that predates the `isbn` option sends the ISBN as text: still an identifier lookup.
        return {"candidates": isbn_candidates(client, typed)}
    page, page_offset = decode_cursor(work.get("cursor"))
    limit = max(1, min(int(work.get("limit", 20)), 50))
    data = client.get("/search.json", q=work["query"], fields=SEARCH_FIELDS, limit=limit, page=page)
    docs = data.get("docs") if isinstance(data.get("docs"), list) else []
    if page_offset > len(docs):
        raise ProviderFailure("invalid_response")
    indices, candidates = [], []
    for index, doc in enumerate(docs[page_offset:], start=page_offset):
        found = search_candidate(doc)
        if found:
            indices.append(index)
            candidates.append(found)
    found_count = len(indices)
    total = books.bounded_int(data.get("numFound"), 0, 10**9) or 0
    result = fit_search({"candidates": candidates})
    kept = len(result["candidates"])
    # every candidate found on this page fit: the rest of the page (including any unusable trailing docs) is
    # spent. Otherwise resume right at the first one the trim cut, so it is retried rather than skipped.
    consumed = len(docs) if kept == found_count else indices[kept]
    if consumed < len(docs):
        result["next_cursor"] = encode_cursor(page, consumed)
    else:
        more = page < MAX_SEARCH_PAGES and page * limit < total and len(docs) == limit
        result["next_cursor"] = encode_cursor(page + 1, 0) if more else None
    return result


def decode_cursor(value):
    """``(page, offset)``: the Open Library page to fetch, and how far into its (already fetched) docs to resume
    from. Plain ``"<page>"`` for a fresh page; ``"<page>:<offset>"`` when a previous call on that page had to
    defer candidates to stay under the output limit."""
    text = str(value) if value not in (None, "") else "1"
    page_text, _, offset_text = text.partition(":")
    page, offset = int(page_text), int(offset_text or 0)
    if not 1 <= page <= MAX_SEARCH_PAGES or offset < 0:
        raise ProviderFailure("invalid_response")
    return page, offset


def encode_cursor(page, offset):
    return f"{page}:{offset}" if offset else str(page)


def fit_search(result):
    """Keep a search page under the runtime's action output limit. Open Library records are user-editable, so a
    page of long titles and long author lists can exceed it. Alternate titles go first (from the end), then whole
    candidates from the end. Author lists are never shortened: metadata takes a work's authors from the candidate
    the host selected, and a shortened list would be stored as the work's authors."""
    def overflow():
        return len(json.dumps(result, ensure_ascii=False).encode("utf-8")) - RESULT_BYTES

    candidates = result["candidates"]
    for candidate in reversed(candidates):
        if overflow() <= 0:
            break
        candidate.pop("alternate_titles", None)
    while overflow() > 0 and candidates:
        candidates.pop()
    return result


# --- works ----------------------------------------------------------------------------------------------------------
def lookup_work(client, work_id):
    """``(work, previous_id)``: the work record, following at most one Open Library merge redirect within
    openlibrary.org (C15 §3.3). `previous_id` is the merged-away id the host should follow, else None."""
    work = client.get(f"/works/{quote(work_id)}.json")
    if (work.get("type") or {}).get("key") != "/type/redirect":
        return work, None
    target = books.key_id(work.get("location"), books.WORK_ID)
    if not target or target == work_id or not str(work.get("location")).startswith("/works/"):
        return None, None
    work = client.get(f"/works/{quote(target)}.json")
    if (work.get("type") or {}).get("key") == "/type/redirect":
        return None, None  # a chain of redirects is not followed
    return work, work_id


def selected_work_id(client, selected):
    """The work a candidate names: its Open Library work id, an edition id, or an ISBN (resolved with one request).
    Anything else is refused before any request."""
    value = external_id(selected, PROVIDER_ID, NAMESPACE)
    if isinstance(value, str) and books.WORK_ID.fullmatch(value):
        return value
    if isinstance(value, str) and books.EDITION_ID.fullmatch(value):
        found = client.get(f"/books/{quote(value)}.json")
        return edition_work_id(found)
    isbn = books.lookup_isbn(value) or books.isbn13(selected.get("isbn_13"))
    if isbn:
        details = isbn_edition(client, isbn)
        return details and edition_work_id(details)
    return None


def work_summary(client, work_id):
    """The work's search document (author names in the work's order, `first_publish_year`): one request that
    answers every author at once instead of one request per author (C15 §3.1 lists `/authors/{id}.json`)."""
    data = client.get("/search.json", q=f'key:"/works/{work_id}"', fields="key,author_name,first_publish_year",
                      limit=1)
    docs = data.get("docs") if isinstance(data.get("docs"), list) else []
    return next((item for item in docs if isinstance(item, dict)
                 and books.key_id(item.get("key"), books.WORK_ID) == work_id), {})


def authors_and_first_published(client, work, work_id, selected):
    """``(authors, first_published)`` of a work.

    Authors come from the candidate the host selected when it is this work's search result (Open Library's search
    lists them in the work's order). The first publication is the work's `first_publish_date` at the precision it
    proves; without one, search's `first_publish_year` (which Open Library computes from the editions) at year
    precision. The work's search document is asked for only when one of the two is still missing."""
    own = selected.get("provider") == PROVIDER_ID and external_id(selected, PROVIDER_ID, NAMESPACE) == work_id
    names = selected.get("authors") if own and isinstance(selected.get("authors"), list) else []
    first = books.parse_loose(work.get("first_publish_date"))
    year = books.candidate_year(selected.get("year")) if own else None
    summary = {}
    if (not names and books.work_author_keys(work)) or (first is None and year is None):
        summary = work_summary(client, work_id)
    if first is None:
        year = year or books.candidate_year(summary.get("first_publish_year"))
        first = {"date": f"{year:04d}", "precision": "year"} if year else None
    return books.authors(names or summary.get("author_name")), first


def book_patch(client, work, work_id, selected, previous_id):
    """`MetadataPatch` for one work, with `book` (Plugin API 1.1.20)."""
    title = books.line(work.get("title"), books.MAX_TITLE)
    if not title:
        return {}
    matched = books.isbn13(selected.get("isbn_13"))
    listed = client.get(f"/works/{quote(work_id)}/editions.json", limit=books.MAX_EDITIONS)
    entries = listed.get("entries") if isinstance(listed.get("entries"), list) else []
    first = None
    if matched:
        # the edition the ISBN search named leads the list; when it is not among the first 50, fetch it by ISBN
        first = next((found for found in map(books.edition, entries) if found and found.get("isbn_13") == matched),
                     None)
        if first is None:
            details = isbn_edition(client, matched)
            first = books.edition(details) if details and edition_work_id(details) == work_id else None
    editions = books.editions(entries, first)
    authors, first_published = authors_and_first_published(client, work, work_id, selected)
    book = {
        "authors": authors,
        "subtitle": books.line(work.get("subtitle"), books.MAX_SUBTITLE),
        "first_published": first_published,
        "editions": editions,
    }
    edition = next((item for item in editions if matched and item.get("isbn_13") == matched), None)
    if edition is not None:
        book["isbn_13"] = matched
        book["isbn_10"] = edition.get("isbn_10")
        book["page_count"] = edition.get("page_count")
    genres, tags = books.subjects(work)
    out = {
        "title": title,
        "year": books.candidate_year(int(first_published["date"][:4])) if first_published else None,
        "description": books.text_value(work.get("description")),
        "genres": genres, "tags": tags,
        "provider_ids": {NAMESPACE: work_id},
        "links": [{"label": "Open Library", "url": f"{BASE_URL}/works/{work_id}"}],
        "book": {key: value for key, value in book.items() if value not in (None, "", [])},
    }
    if previous_id:
        # C4.4: the host follows the merged-away id it holds to the live work
        out["identity"] = {"match": "redirect", "previous_ids": {NAMESPACE: previous_id}}
    return fit({key: value for key, value in out.items() if value not in (None, "", [], {})})


def fit(patch):
    """Keep the result under the runtime's action output limit. The description is shortened first (down to
    DESCRIPTION_FLOOR characters), then editions are dropped from the end (the oldest without an ISBN go first),
    then the description is shortened further. Nothing else is large."""
    def overflow():
        return len(json.dumps({"metadata": patch}, ensure_ascii=False).encode("utf-8")) - RESULT_BYTES

    def shorten(floor):
        text = patch["description"]
        # every character is at least one byte, so cutting `overflow()` characters always makes progress
        patch["description"] = text[:max(floor, len(text) - max(256, overflow()))].rstrip()
        if not patch["description"]:
            del patch["description"]

    while overflow() > 0 and len(patch.get("description") or "") > DESCRIPTION_FLOOR:
        shorten(DESCRIPTION_FLOOR)
    while overflow() > 0 and patch.get("book", {}).get("editions"):
        patch["book"]["editions"].pop()
        if not patch["book"]["editions"]:
            del patch["book"]["editions"]
    while overflow() > 0 and patch.get("description"):
        shorten(0)
    return patch


@operation
def metadata(values):
    selected = values["candidate"]
    work = values["request"]
    if selected.get("media_type", "game") != "book" or not sends_books() \
            or work.get("resource", "entity") != "entity":
        return {}
    client = OpenLibrary(work)
    work_id = selected_work_id(client, selected)
    if not work_id:
        return {}
    record, previous_id = lookup_work(client, work_id)
    if not record:
        return {}
    live_id = books.key_id(record.get("key"), books.WORK_ID) or work_id
    if previous_id is None and live_id != work_id:
        return {}
    return {"metadata": book_patch(client, record, live_id, selected, previous_id)}


@operation
def media(values):
    """The work's cover as a `poster` (C15 D15.5), by cover id only (C15 §3.1)."""
    selected = values["candidate"]
    if selected.get("media_type", "game") != "book" or not sends_books():
        return {"assets": []}
    client = OpenLibrary(values["request"])
    work_id = selected_work_id(client, selected)
    record = lookup_work(client, work_id)[0] if work_id else None
    cover = books.first_cover(record.get("covers")) if record else None
    return {"assets": [{"kind": "poster", "url": COVER_URL.format(cover)}] if cover else []}


def health(values):
    result = search({"request": {**values["request"], "query": "library", "limit": 1, "media_type": "book"}})
    return result if result.get("failure") else {"health": "healthy"}


def main():
    if not sends_books():
        raise RuntimeError("metadata-openlibrary serves books only, which need Plugin API 1.1.20; "
                           "the manifest declares an older contract")
    register(DECLARATION)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
