# Vendored host fixtures

`vocab-v1.json` is the shared vocabulary file the host publishes (CONTRACTS-v1 C7.4), copied unchanged from
`obsoletelabs/unnamed_tracking_app_2` at `contracts/vocab-v1.json` (revision `efded8ae`, branch
`programme/m10-plugin-api-books`, Plugin API 1.1.20 with books) with its SHA-256 in `vocab-v1.json.sha256` (computed over LF line
endings). `tests/test_metadata_atlas.py` pins the digest and compares it with this repository's
`contracts/vocab-v1.json` and Atlas's copy in `tests/fixtures/atlas/`. Copy a new file and its digest together.
`tools/check_metadata_atlas_host.py` also compares the plugin's registry with a host checkout's live registry.
