"""Hold the Open Library plugin's real responses to the host's own validators (C15 §6.2-§6.4, T-P2).

Explicit cross-repository check; never imported by plugin payloads. Run with ``--host-root`` pointing at a host
checkout with Plugin API 1.1.20 and books (programme/m10-plugin-api-books or later). The plugin runs unchanged
against the synthetic fixtures in ``tests/fixtures/openlibrary`` through a stand-in gateway; nothing from the host
is mocked:

- the declaration (``book`` only) is accepted where it enters the host, under the declared contract, and refused
  under 1.1.19 (``MetadataProviderRegistration`` with the contract context);
- an ISBN typed into a book search becomes the reserved ``isbn`` option through the host's own normaliser
  (``parse_isbn``), the request validates, and the plugin answers it with the work that holds the edition;
- every search, metadata and media response validates as ``ProviderResponse`` under the declared contract, the
  book responses are refused under 1.1.19, and ``confine_to_namespaces`` keeps the plugin's ids;
- the work and every edition pass the host's ``BookCreate``/``BookEditionCreate`` the way the book page fills them
  (``bookMetadata.ts``: the work form and "Add this edition");
- a merged Open Library work is followed by the host's own identity reader and refresh decision (C4.4).

Exit 0 when everything holds; every failure is printed and exits 1.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "official" / "metadata-openlibrary"
FIXTURES = ROOT / "tests" / "fixtures" / "openlibrary"
PROVIDER = "official.metadata-openlibrary.openlibrary"
W1, MERGED = "OL900000001W", "OL900000009W"
ISBN_QUERY = "978-0-00-000001-9"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Gateway:
    """The host gateway as the plugin sees it, answered from the synthetic fixtures."""

    def __call__(self, method: str, capability: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if method == "metadata_providers.configuration":
            return {"values": {}}
        if method == "storage.get":
            return {"value": None}
        if method == "storage.compare_and_swap":
            return {"swapped": True}
        parts = urlsplit((payload or {})["url"])
        query = parse_qs(parts.query)
        if parts.path == "/search.json":
            q = query["q"][0]
            name = f"search_key_{q.split('/')[-1].rstrip(chr(34))}.json" if q.startswith("key:") \
                else "search_lighthouse.json"
        elif parts.path == "/api/books":
            name = f"books_isbn_{query['bibkeys'][0].removeprefix('ISBN:')}.json"
        elif parts.path.endswith("/editions.json"):
            name = f"editions_{parts.path.split('/')[2]}.json"
        elif parts.path.startswith("/works/"):
            name = f"work_{parts.path.split('/')[2].removesuffix('.json')}.json"
        else:
            name = f"edition_{parts.path.split('/')[2].removesuffix('.json')}.json"
        if not (FIXTURES / name).exists():
            return {"status": 200, "data": {}} if parts.path == "/api/books" else {"status": 404}
        return {"status": 200, "data": fixture(name)}


def load_plugin(gateway: Gateway):
    sys.path[:0] = [str(ROOT), str(PLUGIN_DIR)]
    from sdk import metadata_provider

    metadata_provider.request = gateway
    spec = importlib.util.spec_from_file_location("openlibrary_plugin_for_check", PLUGIN_DIR / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def responses(plugin) -> dict[str, dict[str, Any]]:
    """Every operation over every fixture case, as the host would receive it."""
    def candidate(work_id: str, **extra: Any) -> dict[str, Any]:
        return {"provider": PROVIDER, "external_id": work_id, "title": "Synthetic", "media_type": "book",
                "provider_ids": {"openlibrary": work_id}, **extra}

    out = {"search: title": plugin.search({"request": {"query": "synthetic lighthouse", "media_type": "book",
                                                       "limit": 5}})}
    for name, selected in {
        "work with candidate authors": candidate(W1, authors=["Ada Example", "B. Placeholder"], year=1937),
        "work, authors by key search": candidate(W1),
        "thirty-one authors": candidate("OL900000004W"),
        "seventeenth-century day": candidate("OL900000003W"),
        "no dates or authors": candidate("OL900000002W", year=1990),
        "merged work": candidate(MERGED),
        "edition id": {**candidate("OL900000012M"), "provider_ids": {}},
        "matched edition outside the first fifty": candidate(W1, isbn_13="9780000000040"),
    }.items():
        out["metadata: " + name] = plugin.metadata({"request": {}, "candidate": selected})
        out["media: " + name] = plugin.media({"request": {}, "candidate": selected})
    return out


def check_declaration(host, plugin, declared: str) -> list[str]:
    from pydantic import ValidationError

    problems = []
    try:
        host.MetadataProviderRegistration.model_validate(plugin.DECLARATION, context=host.contract_context(declared))
    except ValidationError as exc:
        problems.append(f"declaration: the host refuses it at {declared}: {exc.errors()[:2]}")
    try:
        host.MetadataProviderRegistration.model_validate(plugin.DECLARATION, context=host.contract_context("1.1.19"))
    except ValidationError:
        pass
    else:
        problems.append("declaration: the host accepted a book declaration under 1.1.19")
    print(f"declaration: book-only, accepted at {declared} and refused at 1.1.19")
    return problems


def _book_day(value: Any) -> tuple[str | None, str | None]:
    """A host book date as the book page stores it (``bookMetadata.ts`` ``bookDate``)."""
    if value is None:
        return None, None
    year, month, day = (value.date.split("-") + ["01", "01"])[:3]
    return f"{year}-{month}-{day}", None if value.precision == "day" else value.precision


def check_book_forms(patch, label: str) -> list[str]:
    from pydantic import ValidationError
    from src.api.schemas.book import BookCreate, BookEditionCreate

    problems = []
    book = patch.book
    first, precision = _book_day(book.first_published if book else None)
    work = {"title": patch.title, "subtitle": book and book.subtitle,
            "authors": [author.name for author in book.authors] if book else [],
            "description": patch.description, "first_published": first, "first_published_precision": precision,
            "genres": list(patch.genres), "tags": list(patch.tags), "provider_ids": dict(patch.provider_ids)}
    try:
        BookCreate.model_validate({key: value for key, value in work.items() if value is not None})
    except ValidationError as exc:
        problems.append(f"{label}: the host's book form refuses the work: {exc.errors()[:2]}")
    for edition in book.editions if book else ():
        publish, publish_precision = _book_day(edition.publish_date)
        entry = {"isbn_13": edition.isbn_13, "isbn_10": None if edition.isbn_13 else edition.isbn_10,
                 "format": edition.format or "other", "publisher": edition.publisher, "publish_date": publish,
                 "publish_date_precision": publish_precision if publish else None,
                 "page_count": edition.page_count, "language": edition.language}
        try:
            BookEditionCreate.model_validate({key: value for key, value in entry.items() if value is not None})
        except ValidationError as exc:
            problems.append(f"{label}: 'Add this edition' refuses {edition.name or edition.isbn_13}: "
                            f"{exc.errors()[:2]}")
    return problems


def check_isbn_search(host, plugin, declared: str) -> list[str]:
    from src.features.books.isbn import parse_isbn

    context = host.contract_context(declared)
    isbn = parse_isbn(ISBN_QUERY).isbn_13
    request = {"request_id": "00000000-0000-4000-8000-000000000001", "user_id": "00000000-0000-4000-8000-000000000002",
               "query": ISBN_QUERY, "media_type": "book", "limit": 5, "options": {host.ISBN_OPTION: isbn}}
    host.MetadataProviderRequest.model_validate(request, context=context)
    found = host.ProviderResponse.model_validate(plugin.search({"request": request}), context=context)
    if [item.isbn_13 for item in found.candidates] != [isbn]:
        return [f"isbn: the search {ISBN_QUERY!r} answered {found.candidates}, expected one work with {isbn}"]
    chosen = found.candidates[0].model_dump(mode="json", exclude_unset=True)
    patch = host.ProviderResponse.model_validate(plugin.metadata({"request": {}, "candidate": chosen}),
                                                 context=context).metadata
    if patch is None or patch.book is None or patch.book.isbn_13 != isbn \
            or not any(edition.isbn_13 == isbn for edition in patch.book.editions):
        return [f"isbn: the details of the ISBN result do not name the edition {isbn}"]
    print(f"isbn: the host's ISBN search {ISBN_QUERY!r} finds {chosen['external_id']} with {isbn}, "
          f"whose details name that edition")
    return check_book_forms(patch, "isbn")


def check_identity(host, declared: str, merged: dict[str, Any], require_decision: bool) -> list[str]:
    """C4.4 rule 2: the host follows the merged-away Open Library id it holds to the live work."""
    from src.features.metadata.namespaces import confine_to_namespaces
    from src.features.metadata.provider_reports import provider_identities

    parsed = host.ProviderResponse.model_validate(merged, context=host.contract_context(declared))
    patch = confine_to_namespaces(parsed, {PROVIDER, "openlibrary"}).metadata
    identities = provider_identities({"k": SimpleNamespace(metadata={PROVIDER: patch})}, ["k"], [PROVIDER])
    verdict = identities.get(PROVIDER) or {}
    if verdict.get("match") != "redirect" or verdict.get("previous_ids") != {"openlibrary": MERGED} \
            or patch.provider_ids.get("openlibrary") != W1:
        return [f"identity: the host reads {identities} and id {patch.provider_ids}, expected {MERGED} -> {W1}"]
    try:
        from src.features.game_identity import refresh_match
    except ImportError as exc:
        if (exc.name or "").split(".")[0] not in {"sqlalchemy", "greenlet"} and "greenlet" not in str(exc):
            raise
        skipped = f"identity: the host's refresh decision was NOT run (SQLAlchemy with asyncio is missing: {exc})"
        if require_decision:
            return [skipped]
        print(skipped)
        return []
    decision = refresh_match.classify({"openlibrary": MERGED}, {PROVIDER: dict(patch.provider_ids)},
                                      game_title="Synthetic", reported_title=patch.title, identities=identities)
    expected = {"openlibrary": {"from": MERGED, "to": W1, "provider": PROVIDER}}
    if decision.tier != "id" or decision.followed != expected:
        return [f"identity: the host decides {decision.tier} and follows {decision.followed}, expected {expected}"]
    print(f"identity: the host follows {MERGED} -> {W1} from the plugin's patch (tier {decision.tier})")
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host-root", required=True, type=Path)
    parser.add_argument("--require-decision", action="store_true",
                        help="fail when the host's refresh decision cannot run (SQLAlchemy missing)")
    args = parser.parse_args()
    sys.path.insert(0, str(args.host_root / "src/backend"))
    from pydantic import ValidationError

    try:
        from src.plugin_api import metadata_contracts as host
        from src.plugin_api.contracts import PLUGIN_API_CONTRACT_VERSION
        from src.api.schemas.book import BookCreate  # noqa: F401  (books need the M10 host)
    except ImportError as exc:
        print(f"FAIL the host has no book contract ({exc}); C15 needs the M10 host (programme/m10-plugin-api-books)")
        return 1
    if not hasattr(host, "contract_context"):
        print(f"FAIL host Plugin API {PLUGIN_API_CONTRACT_VERSION} predates contract-gated responses")
        return 1
    manifest = json.loads((PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
    declared = manifest["api_contract_version"]
    plugin = load_plugin(Gateway())
    problems: list[str] = []
    if plugin.API_CONTRACT != tuple(int(part) for part in declared.split(".")):
        problems.append(f"the plugin read {plugin.API_CONTRACT} from its manifest, which declares {declared}")
    problems += check_declaration(host, plugin, declared)
    problems += check_isbn_search(host, plugin, declared)

    from src.features.metadata.namespaces import confine_to_namespaces

    current = responses(plugin)
    books = 0
    for name, response in current.items():
        if "failure" in response:
            problems.append(f"{name}: the plugin failed: {response['failure']}")
            continue
        try:
            parsed = host.ProviderResponse.model_validate(response, context=host.contract_context(declared))
        except ValidationError as exc:
            problems.append(f"{declared} {name}: the host refuses the response: {exc.errors()[:3]}")
            continue
        if confine_to_namespaces(parsed, {PROVIDER, "openlibrary"}) != parsed:
            problems.append(f"{name}: the plugin sent ids outside its own namespaces")
        uses_books = any(item.media_type.value == "book" for item in parsed.candidates) or bool(
            parsed.metadata and parsed.metadata.book)
        if uses_books:
            books += 1
            try:
                host.ProviderResponse.model_validate(response, context=host.contract_context("1.1.19"))
            except ValidationError:
                pass
            else:
                problems.append(f"{name}: the host accepted book fields under a 1.1.19 declaration")
        if parsed.metadata is not None:
            problems += check_book_forms(parsed.metadata, name)
    if books < 6:
        problems.append(f"only {books} responses carried book fields; the fixtures no longer exercise them")
    print(f"validated {len(current)} responses at {declared} against host Plugin API {PLUGIN_API_CONTRACT_VERSION}; "
          f"{books} carry book fields and are refused under 1.1.19")
    problems += check_identity(host, declared, current["metadata: merged work"], args.require_decision)
    for problem in problems:
        print("FAIL", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
