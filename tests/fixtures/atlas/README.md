# Vendored Atlas fixtures

`resolve-contract-v1.json` is the shared `/resolve` contract fixture (CONTRACTS-v1 C4.5) that Atlas publishes as the
CI artefact `resolve-contract-v1`. It is copied unchanged from
`obsoletelabs/unnamed_tracking_metadata` at `tests/fixtures/resolve-contract-v1.json` (revision `d47173e`, unchanged
up to `f58ff1d`), with its
SHA-256 in `resolve-contract-v1.json.sha256` (computed over LF line endings). `tests/test_metadata_atlas.py` pins the
digest, so a change is deliberate: copy the new file and its digest together, then update the cases the plugin replays.

The fixture is replayed twice: against a mocked gateway (`tests/test_metadata_atlas.py`) and against a real Atlas
(`tests/atlas_live`).

`vocab-v1.json` is the shared vocabulary file Atlas publishes (CONTRACTS-v1 C7.4), copied unchanged from
`contracts/vocab-v1.json` at revision `f58ff1d` with its `.sha256`. `tests/test_metadata_atlas.py` pins its digest and
compares it with this repository's `contracts/vocab-v1.json` and the host's copy in `tests/fixtures/host/`
(`python tools/vocab_check.py compare ...`). It carries the Atlas-only `feed_kinds`, which the comparison skips.

`relations-v1.json` is synthetic (not copied from Atlas): relations blocks in the shape `GET /api/v2/games/{id}`
serves from Atlas A15 on (`atlas/relations.py` `of()` at `f58ff1d`: `parents`, `children`, `members_of`, `members`,
`counts`, `truncated`; each item `{id, type, title, media_type}`), each with the `MetadataPatch.relations` the plugin
must send (CONTRACTS-v1 C6.4). It includes types outside the shared vocabulary (`edition_of`, `bundle_contains`,
`related_to`, `same_game`) that must be ignored. The live lane checks the same shape against a real Atlas.
