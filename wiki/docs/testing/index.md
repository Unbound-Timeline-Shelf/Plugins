# Test and run conformance

The normal repository suite is host-independent. Cross-repository acceptance
explicitly uses the actual host; plugins never import it at runtime.

| Layer | What it establishes |
| --- | --- |
| Unit/action tests | Calculations, bounded inputs, scoped keys, errors and no secret echoes |
| Manifest/UI tests | v1 schema, unique IDs, exact grants, real handler and contribution references |
| Package tests | Deterministic ZIP, canonical payload/complete archive hashes, bundled assets and SDK |
| Publisher tests | Scoped identity, signature verification, active/retiring/revoked policy |
| Release tests | Conventional bumps, explicit overrides, change selection, policies, history, corruption rejection |
| Tutorial/community tests | Exact documented example builds and independent catalogue generation |
| Browser tests | Actual UI assets, sanitizer/PDF/Office content, bridge failures and cleanup |
| Host contract check | Real host manifest/UI/catalogue/verifier and disabled installation |
| Real reference lifecycle | Four real packages, worker restarts, runtime transactions, persistence and rollback |
| Full host acceptance | PostgreSQL, authenticated HTTP, consent/grants, Jellyfin sync/secrets, automatic/manual updates, failed activation, purge/uninstall |

## Run the local suite

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
node --test tests/session_manager_ui.test.mjs tests/native_frontends.test.mjs tests/jellyfin_official_ui.test.mjs
npm ci
npx playwright install --with-deps chromium --only-shell
npm run check
npm test
python tools/check_source_layout.py
python tools/check_docs.py
python tools/build_packages.py
python tools/distribution.py --root .validation --check-source --include-unreleased
python tools/distribution.py --baseline-ref origin/main
python tools/verify_packages.py dist/*.utp
python tools/validate_packages.py dist/*.utp
python -m mkdocs build --strict
```

Use the [PowerShell wildcard form](../publishing/packages.md) for package paths.
An isolated `--output-root` avoids altering published artifacts. A second preview
build must produce identical bytes for the same source/commit/signer.

## Exercise the real host contract

Clone `Unbound-Timeline-Shelf/Unbound-Timeline-Shelf` at `main` into `.validation/host`
and run `python tools/check_host_contract.py --host-root .validation/host` after
building the preview. It uses actual validators/verifier/registry; it never
enables code during inspection.

Both integration workflows select matching feature branches in that owned host
repository. Contract CI falls back to `main`; runtime CI retains its separately
verified fallback revision below. Explicit workflow-dispatch refs still take
precedence. The host's companion checkout targets
`Unbound-Timeline-Shelf/Plugins` with the same matching-branch convention.

On Linux, `python tools/check_reference_lifecycle.py --host-root .validation/host`
builds signed disposable release sequences for UI/API, report, notifier and
curator, then uses the actual registry and supervisor. It checks pending grant
transactions cannot execute, real start/restart/disable, ordinary and changed-
permission packages, retained rollback, configuration/storage preservation,
reinstall, purge and uninstall. It does not substitute for authenticated host
permission approval. Windows cannot run the real POSIX worker acceptance.

The required `ci.yml` `lifecycle` check aggregates four parallel jobs (`lifecycle-official`,
`lifecycle-reference`, `lifecycle-jellyfin` and `lifecycle-pwa`), each of which runs only when
`tools/ci_changes.py` selects its area and each of which provisions PostgreSQL. A
`tools/check_<plugin>*` or `tools/capture_<plugin>*` script counts as a change to that plugin.
`lifecycle-official` runs the host's
`tools/check_plugin_repository_lifecycle.py` through the plugin repository's
`tools/check_host_lifecycle.py --host-root .validation/host --plugins-root . --work-root <empty-dir> --browser` adapter.
It builds the actual Plugin Manager frontend and verifies consent, effective
grants, new-scope staging, release policy, rollback and failed worker restoration.
`lifecycle-reference` runs the additional reference lifecycle check, `lifecycle-jellyfin` the strict
independent Jellyfin preview and `lifecycle-pwa` the PWA signing and browser lifecycle. The aggregate
status fails if a selected job fails or is skipped, and accepts a skip only for an area the change
selection did not choose. Use the host's
[validation instructions](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/blob/main/wiki/docs/development/plugin-validation.md)
for database, Linux, environment and frontend prerequisites. Never replace this
with a pretend gateway or fake host to get a green lifecycle claim.

## Remaining checks after the host CI fix merges

Runtime CI currently uses verified host commit
`a2d1c898f4fdfb0270234dad58d73f3eee051568`, containing current main and the
validation fixes in [host #432](https://github.com/Rosefall-a/unnamed_tracking_app/pull/432).
The host PR is ready for its required approving review; contract CI continues
checking main. No private `.validation` checkout is needed.

After #432 is merged:

1. Check that main's production image build and its dependent published-image
   runtime smoke both pass, using the exact `sha-<commit>` image tag.
2. Return `DEFAULT_HOST_REF` in `ci.yml` `lifecycle` to `main`, update the
   fallback expectation in `tests/test_host_integration_target.py`, and run its
   actual shell-selector scenarios.
3. Run runtime integration on main after signed publication. The retained signed
   v1.0 worker and verified v1.1 upgrade must both pass even when the catalogue's
   latest release is v1.1.

## Add tests for a new plugin

Write one meaningful action test with successful and denied/malformed responses;
build its real package; run handlers through the packaged SDK; test every UI
contribution and cleanup. Include stored-format compatibility across update and
rollback. Extend real-host acceptance when behavior depends on ownership,
permissions or persistent host records. Keep fixtures disposable and never
commit private test seeds into production publisher configuration.

## CI and release gates

The [lifecycle matrix](lifecycle.md) maps every operation to representative real
packages. The [release audit](../publishing/release-history.md) lists the fields
checked against every archive.

CI and publication run strict MkDocs plus the offline documentation-reference
checker. Distribution checks reject unindexed output, metadata/hash disagreement,
changed historical bytes and disappearing baseline catalogue identities. Tests
and package validation must leave the checkout clean; untracked output fails CI.
Signed publication may stage only the existing authoritative distribution and
resolved manifests; unexpected generated files fail before the commit/upload.
Browser tests execute real assets. Required Linux integration exercises PostgreSQL/HTTP
consent and real worker transactions; unit successes do not replace it.
