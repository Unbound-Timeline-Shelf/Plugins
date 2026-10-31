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
* **Rename**: a source renaming its entry keeps the Atlas id.
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
| `atlas_78_achievement_external_ids_survive_an_atlas_edit` | Atlas #78: achievement ids are new on every list replacement; the host deletes and recreates the catalogue |
| `atlas_86_a_child_edition_or_dlc_names_its_parent` | Atlas #86: no relationships, so no `relations` reach the host |
| `atlas_96_resolve_reports_the_conflict_it_found` | Atlas #96: `/resolve` drops `conflict` |
| `n_plus_one_media_needs_one_request_for_a_known_atlas_id` | plugin: re-reads `/games/<id>` before `/artwork` |
| `n_plus_one_each_achievement_page_costs_one_request` | plugin: re-reads `/games/<id>` for every achievements page |

`test_request_counts_today` pins the current request counts so any change, better or worse, is visible.
