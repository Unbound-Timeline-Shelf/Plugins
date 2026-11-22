"""Hold the Atlas plugin's real responses to the host's own validator, under both contract declarations.

    python tools/check_metadata_atlas_host.py --host-root /path/to/unnamed_tracking_app_2

Explicit cross-repository conformance check, like ``check_host_contract.py``; never imported by plugin payloads
and not part of a plain ``pytest`` run, which stays independent of host source. The plugin
(``official/metadata-atlas``) runs unmodified against a faked gateway that answers with synthetic Atlas records:
partial and regional release dates, a legacy year lock, a free-text lock, malformed dates, and an achievement
catalogue with a platinum entry and merged keys. Every response is validated with the host's
``ProviderResponse`` and the validation context the host derives from the declared contract
(``metadata_contracts.contract_context``), exactly as ``PluginMetadataProvider.invoke`` does:

* declared 1.1.20 (the manifest): every response is accepted, and the 1.1.20 fields are present;
* the same plugin switched to a 1.1.19 declaration: every response is accepted, and the host refuses each
  1.1.20 response under that older declaration, which shows the switch is what keeps an older contract safe.

The host's own refresh decision (C4.4 rule 2) must follow a merged Atlas id from the plugin's patch.

Books (C15 6.3-6.5, Plugin API 1.1.20 with books): the plugin's declaration with ``book`` is accepted under the
declared contract and refused under 1.1.19; an ISBN typed into a book search is turned into the reserved ``isbn``
option by the host's own normaliser, the request is valid, and the plugin answers it with the work that holds that
ISBN; the work and every edition it offers pass the host's own ``BookCreate``/``BookEditionCreate`` schemas the way
the book page fills them (``bookMetadata.ts``: the work, "Add this edition"), and the edition the ISBN search named is
among them. Under a 1.1.19 declaration the plugin sends nothing for books.

It also compares the plugin's vocabulary registry with the host's live registry (C7.4). Exit 0 when everything
holds; any failure is printed and exits 1.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "official" / "metadata-atlas"
GAME_ID = "atlas:" + "a" * 26
BOOK_ID = "atlas:" + "k" * 26
NEW_FIELDS = {"first_release", "releases", "identity", "book"}
NEW_CANDIDATE_FIELDS = {"authors", "isbn_13"}
# Synthetic ISBNs with valid check digits; the search below types the second one with hyphens.
ISBN_A13, ISBN_A10, ISBN_B13 = "9780000000002", "0000000000", "9780000000019"
ISBN_QUERY = "978-0-00-000001-9"
BOOKS: dict[str, dict[str, Any]] = {
    # the Atlas book view (C15 2.3-2.6): authors with roles, series relation with a position, editions with ISBNs
    "book view": {
        "id": BOOK_ID, "media_type": "book", "title": "The Synthetic Lighthouse", "developer": "Ada Example",
        "description": "A keeper writes letters to a town that is not there.",
        "authors": [{"name": "Ada Example", "role": "author"}, {"name": "B. Placeholder", "role": "translator"},
                    {"name": "C. Future", "role": "letterer"}],
        "subtitle": "A Coastal Novel", "page_count": 412, "original_language": "en",
        "release_date": None, "first_release": {"date": "1937-06", "precision": "month"},
        "features": [f"Subject {n:02d}" for n in range(12)],
        "editions": [
            {"name": "Hardcover, Example Press 1937", "provider_ids": {"openlibrary_edition": "OL1M"},
             "isbn_13": ISBN_A13, "isbn_10": ISBN_A10, "format": "hardcover", "publisher": "Example Press",
             "published": {"date": "1937-06", "precision": "month"}, "pages": 412, "language": "en"},
            {"name": "Paperback, Example Press 2005", "provider_ids": {"openlibrary_edition": "OL2M"},
             "isbn_13": ISBN_B13, "format": "paperback", "publisher": "Example Press",
             "published": {"date": "2005-08-01", "precision": "day"}, "pages": 528, "language": "en"},
            {"name": "Audiobook", "format": "audiobook", "published": {"date": "2019", "precision": "year"}},
            {"name": "Repeated ISBN", "isbn_13": ISBN_B13},
            {"name": "Bad ISBN", "isbn_13": "9780000000003", "format": "scroll"}],
        "relations": {"members_of": [{"id": "atlas:" + "s" * 26, "type": "series_member",
                                      "title": "The Fictional Coast", "position": "2"}]},
        "provider_ids": {"openlibrary": "OL1W", "isbn": ISBN_A13}},
    # a node that predates the book view: an admin-made `book` type, a year lock, edition names only
    "older book view": {
        "id": BOOK_ID, "media_type": "book", "title": "Plain Book", "developer": "Ada Example",
        "release_date": "1605", "features": ["Fiction"], "series": "The Fictional Coast",
        "editions": [{"name": "Paperback", "provider_ids": {}, "sources": ["manual-books"]}],
        "provider_ids": {"isbn": ISBN_A13}},
}

RECORDS: dict[str, dict[str, Any]] = {
    "partial and regional dates": {
        "id": GAME_ID, "title": "Synthetic Harbor", "release_date": None, "release_year": 2011,
        "first_release": {"date": "2011-04", "precision": "month"},
        "releases": [
            {"date": "2011-04", "precision": "month", "platform": "pc", "region": "ww", "category": "full"},
            {"date": "2011", "precision": "year", "platform": "ps3", "region": "jp", "edition": "Deluxe Edition",
             "category": "full"},
            {"date": "2010-12-01", "precision": "day", "platform": "PC", "category": "beta"},
            {"date": "2011-02-30", "precision": "day", "platform": "x", "category": "full"},
            {"date": "2012", "precision": "year", "region": "europe", "category": "full"},
            {"date": "2013", "precision": "year", "platform": "mac", "category": "port"},
            {"date": "2014", "precision": "year", "platform": "linux", "category": "port"},
            {"date": "2015", "precision": "year", "platform": "switch", "category": "rerelease"},
        ],
        "custom": {"players_min": 1, "players_max": 4, "crossplay": "partial"},
    },
    "day first release": {"id": GAME_ID, "title": "Synthetic Day", "release_date": "2011-04-19",
                          "first_release": {"date": "2011-04-19", "precision": "day"},
                          "releases": [{"date": "2011-04-19", "precision": "day", "region": "us", "category": "full"}]},
    "day first release without the legacy key": {"id": GAME_ID, "title": "Synthetic Day 2", "release_date": None,
                                                 "first_release": {"date": "2011-04-19", "precision": "day"}},
    "contradicting day": {"id": GAME_ID, "title": "Synthetic Clash", "release_date": "2011-04-19",
                          "first_release": {"date": "2011-04-20", "precision": "day"}},
    "older Atlas, year lock": {"id": GAME_ID, "title": "Synthetic Lock", "release_date": "2011"},
    "older Atlas, free-text lock": {"id": GAME_ID, "title": "Synthetic TBA", "release_date": "TBA"},
    "malformed dates": {"id": GAME_ID, "title": "Synthetic Broken", "release_date": "2011-13-40",
                        "first_release": {"date": "1949", "precision": "year"},
                        "releases": [{"date": "2101", "precision": "year"}, "x", {"date": "2011", "precision": "day"}],
                        "custom": {"crossplay": "not_applicable", "players_max": 1}},
    "pre-1950 day": {"id": GAME_ID, "title": "Synthetic Classic", "release_date": "1937-12-21",
                     "first_release": {"date": "1937-12-21", "precision": "day"}},
    "relations": {"id": GAME_ID, "title": "Synthetic Night Expansion", "release_date": "2021-02-02",
                  "relations": {
                      "parents": [{"id": "atlas:" + "b" * 26, "type": "dlc_of", "title": "Synthetic Garden",
                                   "media_type": "game"},
                                  {"id": "atlas:" + "c" * 26, "type": "edition_of", "title": "Unknown type",
                                   "media_type": "game"}],
                      "children": [{"id": "atlas:" + "d" * 26, "type": "mod_of", "title": "Incoming",
                                    "media_type": "game"}],
                      "members_of": [{"id": "atlas:" + "e" * 26, "type": "series_member", "title": "Synthetic",
                                      "media_type": "series"}],
                      "members": [], "counts": {}, "truncated": False}},
    # GAME_ID was merged into LIVE_ID: Atlas serves the live record for the id the host holds (C4.2)
    "merged": {"id": "atlas:" + "f" * 26, "title": "Synthetic Survivor", "release_date": "2012-05-05",
               "redirected_from": GAME_ID, "provider_ids": {"steam": "880001"}},
}
# What the host must ingest from the "relations" record (C6.4): kind and the ids that name the target.
EXPECTED_RELATIONS = [{"kind": "dlc_of", "targets": {"atlas": "atlas:" + "b" * 26}},
                      {"kind": "series_member", "targets": {"atlas": "atlas:" + "e" * 26}}]
KEY = "ak1:" + "a" * 26
ACHIEVEMENTS = [
    {"id": "01JROW1", "key": KEY, "keys": [KEY, "ak1:" + "b" * 26, "ak1:" + "c" * 26], "name": "Everything",
     "tier": "platinum", "hidden": False, "external_ids": {"steam": "ACH_ALL"}},
    {"id": "01JROW2", "key": "ak1:" + "d" * 26, "keys": ["ak1:" + "d" * 26], "name": "First steps", "tier": "bronze"},
    {"id": "01JROW3", "key": "ak1:" + "e" * 26, "name": "Hidden achievement", "hidden": True, "tier": "gold"},
]


class Gateway:
    """The host gateway as the plugin sees it: configuration plus mediated requests, answered from RECORDS."""

    def __init__(self) -> None:
        self.record: dict[str, Any] = {}

    def __call__(self, method: str, capability: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if method == "metadata_providers.configuration":
            return {"values": {"base_url": "https://atlas.invalid", "api_token": "synthetic"}}
        url = (payload or {}).get("url", "").split("?")[0]
        if url.endswith("/achievements"):
            return {"status": 200, "data": {"results": ACHIEVEMENTS, "next_offset": None}}
        if url.endswith("/api/v2/games"):
            return {"status": 200, "data": {"results": [self.record]}}
        if url.endswith("/games/" + GAME_ID) or url.endswith("/games/" + BOOK_ID):
            return {"status": 200, "data": self.record}
        if url.endswith("/resolve"):
            # Atlas's `isbn` crosswalk answers the work that lists the ISBN (C15 2.5)
            isbn = (payload or {}).get("body", {}).get("items", [{}])[0].get("provider_ids", {}).get("isbn")
            listed = {edition.get("isbn_13") for edition in self.record.get("editions", [])}
            if isbn in listed:
                return {"status": 200, "data": {"results": [{"canonical_id": self.record["id"], "reason": "crosswalk",
                                                             "method": "crosswalk", "game": self.record}]}}
            return {"status": 200, "data": {"results": [{"canonical_id": None, "reason": "none"}]}}
        return {"status": 404}


def load_plugin(gateway: Gateway):
    sys.path[:0] = [str(ROOT), str(PLUGIN_DIR)]
    from sdk import metadata_provider
    metadata_provider.request = gateway
    spec = importlib.util.spec_from_file_location("metadata_atlas_host_check", PLUGIN_DIR / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def responses(plugin, gateway: Gateway) -> dict[str, dict[str, Any]]:
    selected = {"provider": plugin.PROVIDER_ID, "external_id": GAME_ID, "title": "Synthetic"}
    out = {}
    for name, record in RECORDS.items():
        gateway.record = record
        out["metadata: " + name] = plugin.metadata({"request": {}, "candidate": selected})
        out["search: " + name] = plugin.search({"request": {"query": "synthetic", "limit": 5}})
    gateway.record = RECORDS["partial and regional dates"]
    out["achievements"] = plugin.metadata({"request": {"resource": "achievements"}, "candidate": selected})
    book = {"provider": plugin.PROVIDER_ID, "external_id": BOOK_ID, "title": "Synthetic", "media_type": "book"}
    for name, record in BOOKS.items():
        gateway.record = record
        out["metadata: " + name] = plugin.metadata({"request": {}, "candidate": book})
        out["search: " + name] = plugin.search({"request": {"query": "synthetic", "limit": 5, "media_type": "book"}})
    return out


def uses_new_contract(response: dict[str, Any]) -> bool:
    meta = response.get("metadata") or {}
    return bool(NEW_FIELDS & set(meta)) or any(
        "aliases" in item or item.get("tier") == "platinum" for item in meta.get("achievements", [])) or any(
        item.get("media_type") == "book" or NEW_CANDIDATE_FIELDS & set(item) for item in response.get("candidates", []))


def _book_day(value: Any) -> tuple[str | None, str | None]:
    """A host book date as the book page stores it (``bookMetadata.ts`` ``bookDate``): the first day of its period,
    with the precision, and no precision for a day."""
    if value is None:
        return None, None
    year, month, day = (value.date.split("-") + ["01", "01"])[:3]
    return f"{year}-{month}-{day}", None if value.precision == "day" else value.precision


def check_books(host, plugin, gateway: Gateway, declared: str) -> list[str]:
    """C15 6.2-6.5: the host's own decisions on the plugin's book declaration, ISBN search and book patch.

    The declaration is validated where it enters the host (``MetadataProviderRegistration`` with the plugin's contract
    context). An ISBN typed into a book search becomes the reserved option through the host's own normaliser
    (``parse_isbn``, as ``api/routes/metadata.book_lookup_options`` does) and the request is validated. The work and
    its editions are then held to the host's own create schemas, filled as ``bookMetadata.ts`` fills them (the work
    form and "Add this edition"), and the edition the ISBN search named must be one of them."""
    from pydantic import ValidationError

    try:
        from src.api.schemas.book import BookCreate, BookEditionCreate
        from src.features.books.isbn import parse_isbn
    except ImportError as exc:
        return [f"books: the host has no book schemas ({exc}); C15 needs the M10 host (programme/m10-plugin-api-books)"]
    problems: list[str] = []
    context = host.contract_context(declared)
    try:
        host.MetadataProviderRegistration.model_validate(plugin.DECLARATION, context=context)
    except ValidationError as exc:
        problems.append(f"books: the host refuses the declaration at {declared}: {exc.errors()[:2]}")
    if "book" not in plugin.DECLARATION["media_types"]:
        problems.append(f"books: the declaration at {declared} does not offer book")
    try:
        host.MetadataProviderRegistration.model_validate(plugin.DECLARATION, context=host.contract_context("1.1.19"))
    except ValidationError:
        pass
    else:
        problems.append("books: the host accepted a book declaration under 1.1.19")

    gateway.record = BOOKS["book view"]
    isbn = parse_isbn(ISBN_QUERY).isbn_13
    request = {"request_id": "00000000-0000-4000-8000-000000000001", "user_id": "00000000-0000-4000-8000-000000000002",
               "query": ISBN_QUERY, "media_type": "book", "limit": 5, "options": {host.ISBN_OPTION: isbn}}
    try:
        host.MetadataProviderRequest.model_validate(request, context=context)
    except ValidationError as exc:
        return problems + [f"books: the host's own ISBN request is invalid: {exc.errors()[:2]}"]
    found = plugin.search({"request": request})
    parsed = host.ProviderResponse.model_validate(found, context=context)
    if [item.isbn_13 for item in parsed.candidates] != [isbn]:
        return problems + [f"books: the ISBN search {ISBN_QUERY!r} answered {found}, expected one work with {isbn}"]
    chosen = parsed.candidates[0].model_dump(mode="json", exclude_unset=True)
    details = plugin.metadata({"request": {}, "candidate": chosen})
    patch = host.ProviderResponse.model_validate(details, context=context).metadata
    book = patch.book if patch else None
    if book is None or book.isbn_13 != isbn:
        return problems + [f"books: the details of the ISBN result name {book and book.isbn_13}, expected {isbn}"]
    if not any(edition.isbn_13 == isbn for edition in book.editions):
        problems.append(f"books: the edition {isbn} the search named is not among the work's editions")

    first, precision = _book_day(book.first_published)
    work = {"title": patch.title, "subtitle": book.subtitle, "authors": [author.name for author in book.authors],
            "description": patch.description, "first_published": first, "first_published_precision": precision,
            "language": book.original_language, "genres": list(patch.genres), "tags": list(patch.tags),
            "series_name": book.series_name, "series_position": book.series_position,
            "provider_ids": dict(patch.provider_ids)}
    try:
        BookCreate.model_validate({key: value for key, value in work.items() if value is not None})
    except ValidationError as exc:
        problems.append(f"books: the host's book form refuses the work: {exc.errors()[:2]}")
    for edition in book.editions:
        publish, publish_precision = _book_day(edition.publish_date)
        entry = {"isbn_13": edition.isbn_13, "isbn_10": None if edition.isbn_13 else edition.isbn_10,
                 "format": edition.format or "other", "publisher": edition.publisher, "publish_date": publish,
                 "publish_date_precision": publish_precision if publish else None,
                 "page_count": edition.page_count, "language": edition.language}
        try:
            BookEditionCreate.model_validate({key: value for key, value in entry.items() if value is not None})
        except ValidationError as exc:
            problems.append(f"books: 'Add this edition' refuses {edition.name or edition.isbn_13}: {exc.errors()[:2]}")
    print(f"books: the host's ISBN search {ISBN_QUERY!r} finds the work with {isbn}; the work and its "
          f"{len(book.editions)} editions pass the host's book schemas at {declared}")
    return problems


def check_relations(host, declared: str, current: dict[str, Any], older: dict[str, Any]) -> list[str]:
    """C6.4: the host's own reader (`provider_reports.provider_relations`, after `confine_to_namespaces`, as a refresh
    runs them) takes exactly the expected game relations from the plugin's patch, and none under 1.1.19."""
    try:
        from src.features.metadata.namespaces import confine_to_namespaces
        from src.features.metadata.provider_reports import provider_relations
    except ImportError as exc:
        return [f"relations: the host has no game relation reader ({exc}); C6.4 needs the 1.1.20 host"]
    from types import SimpleNamespace

    plugin_id = "official.metadata-atlas.atlas"

    def ingested(response: dict[str, Any], contract: str) -> list[dict[str, Any]]:
        parsed = host.ProviderResponse.model_validate(response, context=host.contract_context(contract))
        patch = confine_to_namespaces(parsed, {plugin_id, "atlas"}).metadata
        source = SimpleNamespace(metadata={plugin_id: patch})
        found = provider_relations({"k": source}, ["k"], {plugin_id: "atlas"}, {plugin_id: contract})
        return [{"kind": item["kind"], "targets": item["targets"]} for item in found]

    problems = []
    name = "metadata: relations"
    got = ingested(current[name], declared)
    if got != EXPECTED_RELATIONS:
        problems.append(f"relations: the host would ingest {got}, expected {EXPECTED_RELATIONS}")
    if "relations" in (older[name].get("metadata") or {}):
        problems.append("relations: sent under a 1.1.19 declaration")
    print(f"relations: the host ingests {len(got)} game relations from the plugin's patch at {declared}")
    return problems


def check_identity(host, declared: str, current: dict[str, Any], older: dict[str, Any],
                   require_decision: bool = False) -> list[str]:
    """C4.4 rule 2: the host's own refresh decision (`refresh_match.classify`, fed by `provider_identities` after
    `confine_to_namespaces`, as a refresh runs them) follows the merged Atlas id from the plugin's patch, and the
    1.1.19 patch carries no identity (the host keeps the saved id there, as before).

    `refresh_match` imports SQLAlchemy (asyncio), which `requirements-dev.txt` installs. Without it the check stops
    after the host's own `provider_identities` and says so; with `require_decision` (as CI runs it) that is a
    failure, since the decision itself was then not exercised."""
    try:
        from src.features.metadata.namespaces import confine_to_namespaces
        from src.features.metadata.provider_reports import provider_identities
    except ImportError as exc:
        return [f"identity: the host has no identity reader ({exc}); C4.4 needs the 1.1.20 host"]
    from types import SimpleNamespace

    plugin_id = "official.metadata-atlas.atlas"
    name = "metadata: merged"
    live = RECORDS["merged"]["id"]
    problems = []
    if "identity" in (older[name].get("metadata") or {}):
        problems.append("identity: sent under a 1.1.19 declaration")
    parsed = host.ProviderResponse.model_validate(current[name], context=host.contract_context(declared))
    patch = confine_to_namespaces(parsed, {plugin_id, "atlas"}).metadata
    identities = provider_identities({"k": SimpleNamespace(metadata={plugin_id: patch})}, ["k"], [plugin_id])
    verdict = identities.get(plugin_id) or {}
    followed = verdict.get("match") == "redirect" and verdict.get("previous_ids") == {"atlas": GAME_ID}
    if not followed or patch.provider_ids.get("atlas") != live:
        return problems + [f"identity: the host reads {identities} and atlas id {patch.provider_ids.get('atlas')}, "
                           f"expected a redirect from {GAME_ID} to {live}"]
    try:
        from src.features.game_identity import refresh_match
    except ImportError as exc:
        # SQLAlchemy itself, or its asyncio extra (greenlet), is missing
        if (exc.name or "").split(".")[0] not in {"sqlalchemy", "greenlet"} and "greenlet" not in str(exc):
            raise
        skipped = (f"identity: the host reads a redirect from {GAME_ID} to {live}; its refresh decision was NOT run "
                   f"(SQLAlchemy with asyncio is not installed here: {exc})")
        if require_decision:
            return problems + [skipped]
        print(skipped)
        return problems
    decision = refresh_match.classify({"atlas": GAME_ID}, {plugin_id: dict(patch.provider_ids)},
                                      game_title="Synthetic", reported_title=patch.title, identities=identities)
    expected = {"atlas": {"from": GAME_ID, "to": live, "provider": plugin_id}}
    if decision.tier != "id" or decision.followed != expected:
        problems.append(f"identity: the host decides {decision.tier} and follows {decision.followed}, "
                        f"expected id and {expected}")
    print(f"identity: the host follows {GAME_ID} -> {live} from the plugin's patch at {declared} "
          f"(tier {decision.tier})")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host-root", required=True, type=Path)
    parser.add_argument("--require-decision", action="store_true",
                        help="fail when the host's refresh decision cannot run (SQLAlchemy missing)")
    args = parser.parse_args()
    sys.path.insert(0, str(args.host_root / "src/backend"))
    from pydantic import ValidationError
    from src.plugin_api import metadata_contracts as host
    from src.plugin_api.contracts import PLUGIN_API_CONTRACT_VERSION

    manifest = json.loads((PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
    declared = manifest["api_contract_version"]
    problems: list[str] = []
    if not hasattr(host, "contract_context"):
        print(f"host Plugin API {PLUGIN_API_CONTRACT_VERSION} predates contract-gated responses; this package "
              f"declares {declared} and is refused at install there (C5.3). Use the 1.1.20 host.")
        return 1

    gateway = Gateway()
    plugin = load_plugin(gateway)
    if plugin.API_CONTRACT != tuple(int(part) for part in declared.split(".")):
        problems.append(f"the plugin read {plugin.API_CONTRACT} from its manifest, which declares {declared}")

    current = responses(plugin, gateway)
    problems += check_books(host, plugin, gateway, declared)
    plugin.API_CONTRACT = (1, 1, 19)
    older = responses(plugin, gateway)
    if "book" in plugin.media_types():
        problems.append("books: the plugin still offers book under a 1.1.19 declaration")
    new_seen = 0
    for name, response in current.items():
        try:
            host.ProviderResponse.model_validate(response, context=host.contract_context(declared))
        except ValidationError as exc:
            problems.append(f"{declared} {name}: the host refuses the response: {exc.errors()[:3]}")
        try:
            host.ProviderResponse.model_validate(older[name], context=host.contract_context("1.1.19"))
        except ValidationError as exc:
            problems.append(f"1.1.19 {name}: the host refuses the response: {exc.errors()[:3]}")
        if uses_new_contract(older[name]):
            problems.append(f"1.1.19 {name}: a 1.1.20 field or value was sent under the older declaration")
        if uses_new_contract(response):
            new_seen += 1
            try:
                host.ProviderResponse.model_validate(response, context=host.contract_context("1.1.19"))
            except ValidationError:
                pass
            else:
                problems.append(f"{name}: the host accepted 1.1.20 fields under a 1.1.19 declaration")
    if new_seen < 4:
        problems.append(f"only {new_seen} responses used the 1.1.20 fields; the synthetic records no longer "
                        "exercise them")
    print(f"validated {len(current)} responses at {declared} and 1.1.19 against host Plugin API "
          f"{PLUGIN_API_CONTRACT_VERSION}; {new_seen} carry 1.1.20 fields")
    problems += check_relations(host, declared, current, older)
    problems += check_identity(host, declared, current, older, args.require_decision)

    registry = args.host_root / "src/backend/src/plugin_api/vocab.py"
    if registry.exists():
        spec = importlib.util.spec_from_file_location("host_vocab_for_check", registry)
        host_vocab = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(host_vocab)
        sys.path.insert(0, str(ROOT / "tools"))
        import vocab_check
        differences = vocab_check.compare({"plugin": plugin.vocab.export(), "host": host_vocab.export()})
        problems += [f"vocabulary: {line}" for line in differences]
        print(f"vocabulary: plugin and host registries {'differ' if differences else 'agree'}")
    else:
        problems.append(f"{registry} is missing: the host has no shared vocabulary registry (C7.4)")

    for problem in problems:
        print("FAIL", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
