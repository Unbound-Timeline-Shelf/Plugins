# Open Library Metadata Provider

An optional, keyless book provider for hosts with or without Atlas (CONTRACT-C15 D15.9). It searches
[Open Library](https://openlibrary.org) by title, author or ISBN and fills a book's details: ordered authors,
subtitle, description, subjects, first publication, up to 50 editions and a cover. The host has no hardcoded book
provider (#265); this plugin, like `metadata-atlas`, is one of the optional ones.

It declares **Plugin API 1.1.20**, the one bump that carries books (C15 §6.4, D15.11), and serves only the `book`
media type. A host older than 1.1.20 refuses to install it. The plugin reads the contract from its own manifest
and does not start under an older declaration.

## Install and configure

Install the `.utp` through the Plugin Manager and grant its permissions. No key or account is needed. The
provider appears in **Settings → Metadata/API** and in the book search.

One optional field, **Contact e-mail or URL sent to Open Library** (system scope, not secret), is sent with
every request in the `User-Agent` header when an administrator sets it. Open Library asks API clients to identify
themselves and allows an identified client a higher request rate. Nothing about the operator is sent unless an
administrator fills it in (C15 §3.2, D15.7). Without it the header names only the app, this plugin's version and
this repository's URL.

## What it does

| Operation | Open Library request | Result |
| --- | --- | --- |
| Search (title/author) | `GET /search.json?q=…&fields=…&limit=…&page=…` | Works with title, first-publication year (when within the host's 1800-3000 range), authors and `title: subtitle` as an alternate title. 20 pages at most |
| Search (ISBN) | `GET /api/books?bibkeys=ISBN:…&format=json&jscmd=details` | The work that holds the edition, with `isbn_13` naming it. The host's reserved `isbn` option and a query that is itself a valid ISBN-10/13 are identifier lookups and never fall back to a title search |
| Metadata | `GET /works/{id}.json`, `GET /works/{id}/editions.json?limit=50`, and when needed `GET /search.json?q=key:"/works/{id}"` | Title, description, subjects (the first 10 as genres, up to 40 more as tags, D15.12), a link to the work page and `book`: authors, subtitle, first publication, editions, and the matched edition's ISBNs and pages |
| Media | `GET /works/{id}.json` | The first real cover as a `poster` (D15.5), `https://covers.openlibrary.org/b/id/{cover_id}-L.jpg`, by cover id only |
| Health | one title search | `healthy`, or the failure classification |

Details:

- **Ids.** The external id and `provider_ids.openlibrary` are the **work** id (`OL…W`). A candidate may also name
  an edition (`OL…M`) or carry an ISBN from another provider; both are resolved to their work with one request.
  Anything else, author ids (`OL…A`) included, is refused before any request.
- **Merged works.** Open Library leaves a redirect record behind when it merges works. The plugin follows one such
  redirect within openlibrary.org and reports it as `identity: {match: "redirect", previous_ids: {openlibrary: <old>}}`,
  so the host follows the id it holds (C4.4). A chain of redirects is not followed.
- **No HTTP redirects.** The host's `network.request` follows none. That is why ISBNs go through `/api/books` and
  not `/isbn/{isbn}.json`, which redirects. Covers are fetched by the host, which does follow redirects.
- **Authors.** Open Library's search lists a work's author names in the work's order, so the names come from the
  selected search result or from one search by the work's key. There is no request per author.
  Every creator has the role `author`, and there are at most 30.
- **Dates.** Open Library dates are free text. `1937` is a year, `June 1937` a month, `Aug 01, 1937` a day, and `c1937`,
  `[1937]` or `©1937` a year. Anything else, an uncertain date (`1937?`, `193-`) or a year outside 1000-2100 is
  dropped, never guessed. Without a work date, search's `first_publish_year` is used at year precision. Dates are
  sent as `{date, precision}`; the host shows them through its shared date formatter.
- **Editions.** Editions with an ISBN come first, then the newest. An edition matched by an ISBN search leads the list,
  even when it is not among the first 50. A repeated ISBN keeps the first edition. An edition whose ISBN-13 has a
  wrong check digit keeps no ISBN. An ISBN-10 alone gives its ISBN-13. The free-text format maps to
  `paperback`, `hardcover`, `ebook`, `audiobook` or `other`. The language is Open Library's code (`eng`).
- **Size.** A result stays under the runtime's 64 KiB action output limit (56 KiB measured). A very long
  description is shortened first, to no less than 4000 characters, and only then are editions dropped from the end.
- **Pacing.** One request a second without a contact, about three with one, shared by every worker through
  `plugin.storage` (`ProviderHttp`). Interactive requests never wait more than a second for a slot. Search preloads
  may therefore report `rate_limited` for some results; the host keeps the others.

## Permissions

| Capability | Why |
| --- | --- |
| `metadata_providers.register`, `.search`, `.metadata`, `.media`, `.health` | The provider operations above |
| `metadata_providers.configuration` | Read the optional contact |
| `network.outbound` | Requests to `openlibrary.org` only |
| `plugin.storage` | The shared pacing slot |

## Data and licence

Open Library's descriptions and covers are not redistributable (C15 §3.2). The plugin only passes them to the host
that asked. The tests use **synthetic** fixtures only (`tests/fixtures/openlibrary`, CC0, pinned by SHA-256), which
copy the response shapes but no Open Library data.

## Test

```sh
python -m pytest tests/test_metadata_openlibrary.py
python tools/check_metadata_openlibrary_host.py --host-root <host checkout with books> --require-decision
python tools/check_reference_lifecycle.py --host-root <host checkout with books> --source official/metadata-openlibrary  # Linux
python tools/check_metadata_openlibrary_live.py   # optional; about six live requests, never in CI
```

The host check holds every response to the host's own validators, book forms and identity reader (see
[the testing guide](../../wiki/docs/testing/index.md)). The lifecycle check runs the real worker through install,
restart, update, rollback, purge and uninstall. CI runs both against the pinned books host.

## Distribution

The plugin is listed in `catalogue.json` `unreleased_plugins` until the host with books is released. Until then,
branch CI's `unsigned-dist` artifact carries a preview, and signed publication uses the official pipeline.
