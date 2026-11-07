# Live Atlas contract lane

`official.metadata-atlas` is also tested against a **real Atlas server**, not only against a faked gateway.
The lane starts an Atlas container, seeds synthetic data, and runs the unmodified plugin module against it
with a gateway that makes real HTTP requests. It catches drift in the Atlas API (shape, paging, auth, media
URLs) that the mocked tests in `tests/test_metadata_atlas.py` cannot.

## What is real and what is not

| Real | Not real |
| --- | --- |
| Atlas (built from its own `Dockerfile`), its database, authentication, paging, resolver and media store | The host. `tests/atlas_live/atlas_live_support.py` stands in for the host gateway |
| The plugin module `official/metadata-atlas/plugin.py` and `sdk/metadata_provider.py` | The host's egress policy and worker isolation (covered by the lifecycle jobs) |
| Real HTTP, real timeouts, real `docker pause` for an unreachable server | Providers behind Atlas (Steam, IGDB, RAWG): they are off, and every record is seeded |

The gateway mirrors the host's `outbound_json` (URL and header allow-list, no redirects, 4 MiB cap, status 0
when unreachable, 8 second deadline) and refuses a request the host would refuse. If that host function
changes, update `LiveGateway`.

All data is synthetic (`example.invalid` addresses, invented titles). The bootstrap token is generated per run.

## Run it locally (Linux, macOS, Windows with Docker Desktop)

```sh
python -m pip install -r requirements-dev.txt
python tools/check_metadata_atlas_live.py --atlas-source ../unnamed_tracking_metadata
```

`--image <tag>` reuses an image you already built, `-k <expression>` and any other pytest argument are
passed through, `--keep` leaves the container running and `--log-dir <dir>` saves the container and test logs.
The runner picks a free `127.0.0.1` port, always removes the container, and fails loudly if Docker is not
running. A plain `pytest` skips `tests/atlas_live` (one skip, with the reason) because it needs Docker.

## CI

The `atlas-live-contract` job in `.github/workflows/ci.yml` runs when `official/metadata-atlas`,
`tests/atlas_live`, `tools/check_metadata_atlas_live.py` or any shared file changes. Atlas is a private
repository, so the job needs the repository secret `ATLAS_CHECKOUT_TOKEN` (a read-only token with contents
access to `obsoletelabs/unnamed_tracking_metadata`); until it is configured the job is skipped with a visible
warning and a job summary (it does not pass silently), and once it is set any failure fails the job. It builds Atlas at the revision pinned in the job's `ATLAS_REF` (override with the `atlas_ref`
dispatch input). Bump the pin deliberately; the lane is how you learn what a newer Atlas breaks.

## What it covers

* **Search**: shape, media-type isolation, limit clamp, empty results, bad and revoked tokens, edition set vs. sibling.
* **Resolve and details**: crosswalk by provider id, certain title+year match, fuzzy and conflicting ids refused,
  full field mapping validated against the host response schema, movie mapping.
* **Resolve semantics** (Atlas #96, plugins#70, contract C4): every case of the vendored shared fixture
  `tests/fixtures/atlas/resolve-contract-v1.json` is built in the node and replayed through the plugin, which adopts an
  identity exactly for `id`, `redirect`, `crosswalk` and `exact`. A conflict is logged and adopts nothing; merged ids
  (a chain of two) are followed for metadata, artwork and achievements; a renamed record is found by its provider id
  and not by its old title; a title twin is refused when the client holds a different id. These tests need an Atlas
  with the C4 change (A6 or later); against an older Atlas the six conflict/ambiguity tests fail by design.
* **Rename**: a source renaming its entry keeps the Atlas id.
* **Achievement identity** (Atlas #78, contract C2): the plugin forwards Atlas's stable `ak1` key as the host
  `external_id` and the Atlas row id as `source_ids["atlas.row"]`; the key survives an unchanged re-import and an edit of
  other entries. The stability test needs an Atlas with keys (A4 or later) and fails against an older one; the bridge
  and edit tests cover both cells of the compatibility matrix (key present, and the documented fallback to the row id).
* **Plugin API 1.1.20** (contracts C5.3, C2.6, C7): a month-precision first release with regional entries reaches the
  host as `first_release` and `releases` without a `release_date`; a curator year lock is sent as a year, never as
  1 January; a `releases` lock is forwarded as the release list; `platinum` passes through; an achievement two sources
  list sends its other key as an alias (the second source is written with Atlas's own `facets.set_achievements` in the
  container, because the API writes lists only as the curator). Under a 1.1.19 declaration (the plugin's
  `API_CONTRACT` switched in the test) the same records send none of those fields. These tests branch on what the
  Atlas under test serves: against an Atlas before contract C5/C7 they assert that it refuses the dated observation,
  the platinum list and the `releases` lock, that a free-text `release_date` lock (`TBA`) sends no date, and that a
  year lock in the legacy key is still read as a year. The lane was run against both cells (see the pull request).
* **Relations** (Atlas #86, contract C6.4): a DLC related to its base game with Atlas's curate API reaches the
  host as a `dlc_of` relation naming the base game's Atlas id, both by Atlas id and through `/resolve` by its
  Steam id (the plugin then reads `GET /games/{id}`, the only answer with the relations block); the base game sends
  no relation (incoming edges travel with the other record); a merge of the parent moves the relation to the
  survivor; a 1.1.19 declaration sends none. Against an Atlas before relations (A15) the route is absent and the
  tests assert that no `relations` key is sent.
* **Achievements**: 450 entries over three pages, byte-bounded splitting of oversized pages, hidden-entry
  redaction, icon URLs fetched without credentials, cursor handling, exact request counts.
* **Artwork**: cached copies only, `key_art` to `poster`, `public_base_url`.
* **Offline and timeouts**: unreachable port, a server that accepts and never answers, bounded background
  retries, `docker pause` mid-session and mid-catalogue, recovery.

## Known-issue tests

A test named `test_KNOWN_ISSUE_<what>` states the **desired** behaviour and is
`xfail(strict=True, raises=AssertionError)`. It fails today for the stated reason. When the issue is fixed it
turns XPASS, which is a failure, so the fixing change must remove the marker and the `KNOWN_ISSUE` prefix.

| Test | Waiting for |
| --- | --- |
| `n_plus_one_media_needs_one_request_for_a_known_atlas_id` | plugin: re-reads `/games/<id>` before `/artwork` |
| `n_plus_one_each_achievement_page_costs_one_request` | plugin: re-reads `/games/<id>` for every achievements page |

`test_request_counts_today` pins the current request counts so any change, better or worse, is visible.
