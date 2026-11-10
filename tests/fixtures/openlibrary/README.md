# Open Library fixtures (synthetic)

Every file here is **synthetic**: titles, people, publishers, descriptions, subjects, ISBNs and ids were written
for these tests and describe no real book. No Open Library data is copied, because its descriptions and covers
are not redistributable (CONTRACT-C15 §3.2). The files are offered under CC0.

What is real is the **shape**: each file follows the response the plugin reads from the live service, checked on
2026-11-10 with `tools/check_metadata_openlibrary_live.py` (the same paths and parameters the plugin sends):

| File | Endpoint |
| --- | --- |
| `search_*.json` | `GET /search.json?q=…&fields=…&limit=…&page=…` (`search_key_*`: `q=key:"/works/OL…W"`) |
| `books_isbn_*.json` | `GET /api/books?bibkeys=ISBN:…&format=json&jscmd=details` (`{}` when unknown) |
| `work_*.json` | `GET /works/OL…W.json`; `OL900000009W` is a merge redirect, `OL900000008W` a redirect chain |
| `editions_*.json` | `GET /works/OL…W/editions.json?limit=50` |
| `edition_*.json` | `GET /books/OL…M.json` (a candidate that names an edition) |
| `http_429.json` | the host gateway's answer to a rate-limited request (`network.request`) |

The cases follow C15 §3.4: a work with free-text dates (`June 1937`, `Aug 01, 1605`, `c1950`), one without dates
or covers, 31 authors (truncated to 30), an ISBN-10-only edition, an edition whose ISBN-13 has a wrong check
digit, a repeated ISBN, an unknown format, an empty search, an unknown ISBN and a rate-limited answer. Ids use the
`OL9000000nnX` range and ISBNs the `978-0-00-00000x-x` block, both with valid shapes and check digits.

`SHA256SUMS` pins every file (SHA-256 over LF line endings). `tests/test_metadata_openlibrary.py` fails when a
file is changed, added or removed without updating it: regenerate the digest together with the file.
