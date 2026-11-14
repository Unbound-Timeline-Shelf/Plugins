"""Optional live smoke check: the unchanged Open Library plugin against openlibrary.org (C15 §3.4).

Never run in CI. It sends about six paced requests through a stand-in gateway that behaves like the host's
``network.request`` (HTTPS GET, no redirects followed, 4 MiB cap) and asserts the shapes the plugin reads: a title
search, the ISBN lookup, one work with its editions and authors, and its cover. Output is limited to counts, ids and
classifications; no Open Library text is printed or stored (its descriptions are not redistributable).

    python tools/check_metadata_openlibrary_live.py [--query dune] [--isbn 9780441013593] [--contact you@example.org]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "official" / "metadata-openlibrary"


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError(f"redirect refused ({code}); the host follows none")


class LiveGateway:
    def __init__(self, contact: str | None) -> None:
        self.contact = contact
        self.storage: dict[str, str] = {}
        self.requests = 0

    def __call__(self, method, capability, payload=None):
        if method == "metadata_providers.configuration":
            return {"values": {"contact": self.contact} if self.contact else {}}
        if method == "storage.get":
            return {"value": self.storage.get(payload["key"])}
        if method == "storage.compare_and_swap":
            if self.storage.get(payload["key"]) != payload["expected"]:
                return {"swapped": False}
            self.storage[payload["key"]] = payload["value"]
            return {"swapped": True}
        assert method == "network.request" and urlsplit(payload["url"]).hostname == "openlibrary.org"
        self.requests += 1
        request = urllib.request.Request(payload["url"], headers={"Accept": "application/json", **payload["headers"]})
        try:
            with urllib.request.build_opener(NoRedirects()).open(request, timeout=20) as response:
                return {"status": response.status, "data": json.loads(response.read(4 * 1024 * 1024 + 1))}
        except urllib.error.HTTPError as exc:
            retry = exc.headers.get("Retry-After", "")
            return {"status": exc.code, **({"retry_after_seconds": int(retry)} if retry.isdecimal() else {})}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--query", default="dune")
    parser.add_argument("--isbn", default="9780441013593")
    parser.add_argument("--contact", help="identify this run to Open Library (an e-mail or https URL)")
    args = parser.parse_args()
    sys.path[:0] = [str(ROOT), str(PLUGIN_DIR)]
    from sdk import metadata_provider

    gateway = LiveGateway(args.contact)
    metadata_provider.request = gateway
    spec = importlib.util.spec_from_file_location("openlibrary_plugin_live", PLUGIN_DIR / "plugin.py")
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    schema = json.loads((ROOT / "tools/schemas/metadata-response-v1.schema.json").read_text(encoding="utf-8"))
    import jsonschema

    problems: list[str] = []
    started = time.monotonic()

    def run(label, response, check):
        try:
            jsonschema.validate(response, schema)
        except jsonschema.ValidationError as exc:
            problems.append(f"{label}: not a valid response ({exc.message[:120]})")
            return response
        if "failure" in response:
            problems.append(f"{label}: failed with {response['failure']}")
        elif not check(response):
            problems.append(f"{label}: the shape the plugin reads was not there")
        return response

    found = run("search", plugin.search({"request": {"query": args.query, "media_type": "book", "limit": 5,
                                                     "policy": "background"}}),
                lambda r: r["candidates"] and all(item.get("authors") for item in r["candidates"][:1]))
    by_isbn = run("isbn", plugin.search({"request": {"query": args.isbn, "media_type": "book", "policy": "background",
                                                     "options": {"isbn": args.isbn}}}),
                  lambda r: [item["isbn_13"] for item in r["candidates"]] == [args.isbn])
    for item in by_isbn.get("candidates", [])[:1]:
        details = run("metadata", plugin.metadata({"request": {"policy": "background"}, "candidate": item}),
                      lambda r: r.get("metadata", {}).get("book", {}).get("editions"))
        book = details.get("metadata", {}).get("book", {})
        print(json.dumps({"work": item["external_id"], "authors": len(book.get("authors", [])),
                          "editions": len(book.get("editions", [])), "isbn_matched": book.get("isbn_13") == args.isbn,
                          "first_published": (book.get("first_published") or {}).get("precision")}))
        cover = run("media", plugin.media({"request": {"policy": "background"}, "candidate": item}),
                    lambda r: all(asset["url"].startswith("https://covers.openlibrary.org/b/id/")
                                  for asset in r["assets"]))
        print(json.dumps({"covers": len(cover.get("assets", []))}))
    print(json.dumps({"search_candidates": len(found.get("candidates", [])), "requests": gateway.requests,
                      "seconds": round(time.monotonic() - started, 1)}))
    for problem in problems:
        print("FAIL", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
