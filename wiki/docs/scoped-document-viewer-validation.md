# Scoped Document Viewer validation

Validated on Windows on 2026-10-01. The plugin source baseline was `2293839`; the host `plugin-manager` baseline was `daedc1d8125662065bf27d64ac6311380249a5e6`. The comparison uses the actual [PR #241](https://github.com/Rosefall-a/unnamed_tracking_app/pull/241) source at `a9b7d3102c1efec08a5bf11a919c6d2204376ebc`, including its tests. The completed stages 1–4 platform was inspected alongside the [existing API audit](plugin-api-v1-audit.md).

## Results

| Check | Result |
| --- | --- |
| Original PR backend document tests | 19 passed, 1 symlink test skipped |
| Original PR frontend document service tests | 13 passed |
| Direct source comparison | 28 document cases and 6 traversal cases passed |
| Plugin Python suite | 41 passed |
| Plugin real-browser sandbox suite | 21 passed |
| Relevant host backend suite | 188 passed, 1 symlink test skipped |
| Host frontend Vitest suite | 66 passed in 11 files |
| Host ESLint and Vue TypeScript checks | Passed |
| Host mypy | Passed across 187 source files |
| Host Pylint | 9.16, meets the unchanged CI threshold of 9.0; baseline 9.17 |
| Ruff on changed document contract/policy/gateway/tests and plugin Python | Passed |
| JavaScript syntax and changed frontend formatting | Passed |
| Package build, integrity verification and package validation | Passed for fresh builds and checked-in distribution packages |
| Actual host package/manifest/UI inspection | Passed; the new package is correctly classified as unsigned |

Default host Prettier is **not green**. On this Windows checkout it reports widespread line-ending differences. Read-only snapshots with normalized line endings isolate exactly 23 content-formatting failures, identical in the untouched baseline and updated tree. These are outside this change. The changed frontend files pass the configured formatter. Existing checks and thresholds were not weakened. The host routes module also retains its existing FastAPI `B008` default-dependency warnings; no new document-policy Ruff warnings were introduced.

Windows did not permit symlink creation, so those two symlink tests were skipped rather than removed. The tests retain their escaping-symlink assertions for environments permitting creation. No production Docker/PostgreSQL deployment or Linux runtime sandbox end-to-end run was performed. Host authorization tests use persisted SQLAlchemy rows with SQLite test storage and exercise actual ownership/grant queries and HTTP authorization. Browser tests load the actual plugin assets inside the host's opaque iframe sandbox and CSP. Package tests execute the public SDK from the actual `.utp` in a subprocess.

## Reproduction

In the plugin repository:

```sh
python -m pytest -q
npm ci
npx playwright install --with-deps chromium --only-shell
npm run check
npm test
python tools/build_packages.py
python tools/verify_packages.py dist/*.utp
python tools/validate_packages.py dist/*.utp
python tools/check_document_parity.py --reference /path/to/pr241-checkout --host /path/to/updated-host
```

The standard builder can regenerate unsigned examples. Run it in an isolated checkout when preserving existing signed release artifacts; do not overwrite a signed release with an unsigned rebuild. The new 1.4.0 package was built in isolation and verified against current source and pinned vendor hashes. Existing signed artifacts were preserved.

In the updated host's `src/backend`, with the normal test database/environment
configuration. Set `HOST_BACKEND` to the absolute backend directory of that host
checkout; these tests are external to the plugin repository:

```sh
python -m pytest -q "$HOST_BACKEND/tests/test_plugin_documents.py" "$HOST_BACKEND/tests/test_plugin_domain_gateway.py" "$HOST_BACKEND/tests/test_plugin_authorization_http.py" "$HOST_BACKEND/tests/test_plugin_backend_routes.py" "$HOST_BACKEND/tests/test_plugin_route_capabilities.py" "$HOST_BACKEND/tests/test_plugin_ui_extensions.py" "$HOST_BACKEND/tests/test_plugin_ui_contracts.py" "$HOST_BACKEND/tests/test_plugin_api_contracts.py" "$HOST_BACKEND/tests/test_plugin_manifest.py" "$HOST_BACKEND/tests/test_plugin_lifecycle.py" "$HOST_BACKEND/tests/test_plugin_contribution_lifecycle_e2e.py" "$HOST_BACKEND/tests/test_plugin_repository_trust.py"
python -m mypy src
python -m pylint src
python -m ruff check src/plugin_api/documents.py src/plugin_api/gateway.py src/plugin_api/contracts.py tests/test_plugin_documents.py
```

In the host's `src/frontend`:

```sh
npm ci --ignore-scripts
npm run lint
npm run typecheck
npm run test -- --run
npm run format
```

The direct comparison loads the reference helper from the supplied PR checkout. It does not replace it with a mock or duplicate implementation. Ownership, fresh-grant revocation, unauthorized requests, opaque IDs, traversal, oversized inputs and bounded metadata transport are separately covered by host tests. Browser tests cover HTML attack payloads and absence of outbound requests, malformed PDFs, UTF-8 chunk boundaries, digest mismatches, unsupported MIME types, malformed bridge responses, stale responses, loading/empty states and HTTP deployments without secure-context Web Crypto APIs.

## Delivery restrictions

See the [feature comparison](scoped-document-viewer.md) and [plugin README](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/scoped-document-viewer/README.md) for the explicit PR behavior differences: the platform's 5 MiB PDF cap, sandbox PDF controls, disabled HTML navigation, indexed-document requirement, and unavailable read-only upload/rename operations. The host contract update must accompany the plugin.

The 1.4.0 artifact is an **unsigned local build**, not a trusted signed release. Trusted release signing requires the existing publisher workflow and its private credentials. No signatures or keys were fabricated. The independent plugin GitHub wiki was unavailable (`Repository not found`); a wiki-ready guide is committed in this repository instead.

Before pushing, both commits were rebased onto concurrent session-management updates (`6f58e609` in the host and `489fb2b` in the plugin repository). The combined code preserves host-owned action confirmation and the new session/GeoIP APIs. Integration checks passed: 208 relevant host backend tests (1 symlink skip), 67 host frontend tests, 60 plugin Python tests, 6 session-manager UI tests, Vue TypeScript, ESLint, and package integrity/validation. The document browser assets and package content remain unchanged from the 21-test sandbox run above.


## Version 1.5.0 game Docs reader fix (2026-10-02)

Host baseline: `e1a208cc`; plugin baseline: `5b5babf`. The original authenticated sandbox defect was reproduced: SameSite=Lax login cookies do not accompany opaque iframe CSS/script subrequests. The browser fixture now requires the login cookie instead of serving assets publicly. Authenticated entry responses inline verified package CSS/classic scripts with a fresh nonce; the sandbox keeps `allow-scripts` alone. Actual host HTTP tests verify authorization, nonce CSP, MIME handling and bounded package delivery.

Game Docs now provides indexed document IDs and opens a declared reader in a new tab. The optional library has no mandatory sidebar contribution. The reader opens its contextual ID without listing all documents and downloads the original through the scoped attachment bridge; HEAD and GET repeat ownership and live grant checks. Unsupported/oversized previews retain downloads. DOCX/PPTX/ODT/ODP previews add local inert reading views with bounded ZIP/XML validation; they do not reproduce full Office layout. A [direct-reader screenshot](assets/screenshots/scoped-document-reader-office.png) records the styled result.

| Check | Result |
| --- | --- |
| Plugin Python tests | 89 passed |
| Document sandbox browser tests | 34 passed |
| Other plugin session UI regression tests | 6 passed |
| Host frontend tests | 71 passed across 12 files after the final rebase |
| Relevant host backend tests | 226 passed, 1 Windows symlink skip |
| Full plugin runtime tests | 62 passed, 2 existing Windows failures |
| Full host ESLint / Vue TypeScript | Passed |
| Full host mypy | Passed across 189 source files |
| Full host Pylint | 9.18, above unchanged CI threshold 9.0 |
| Changed document Python Ruff / frontend formatting / JavaScript syntax | Passed |
| Package build, integrity and package validation | All fresh builds and checked-in artifacts passed |
| Real host package and UI contract inspection | Passed; 1.5.0 correctly classified as unsigned |
| Direct comparison to actual PR #241 helper | 28 document cases and 6 traversal cases passed |

The runtime failures are `test_plugin_storage_files_are_owner_only` (Windows does not implement POSIX mode 0600) and `test_action_handler_can_use_the_mediated_plugin_gateway` (`preexec_fn` is unsupported on Windows). Both fail identically in an untouched runtime snapshot from the baseline (58 passed, the same two failures). New inline-asset manifest validation and descriptor tests pass. Tests and CI remain unchanged in strength; neither failure was skipped or relaxed.

Full host Prettier reports 181 files on this Windows checkout. After read-only newline normalization, baseline and updated sources have the same 23 content-formatting failures, with none introduced. Changed frontend files pass. The package validator retains three pre-existing Ruff TRY004 suggestions for its established ValueError contract; the changed document test/tool code passes. Full Pylint still emits existing/style diagnostics; its score meets the configured CI gate. Docker is unavailable here, so production PostgreSQL and Linux bubblewrap end-to-end checks remain unverified. SQLite tests exercise actual SQL ownership and HTTP boundaries.

The 1.5.0 artifact was built with the standard builder in isolation, then copied individually so existing signed releases remain intact. It is an unsigned local artifact pending the repository's normal signing workflow. The host and plugin updates must be deployed together, and existing installations must approve `frontend.context.documents` to register the game reader. PR restrictions remain explicit in the README: PDF previews retain the platform 5 MiB cap, native PDF/password controls remain unavailable in the sandbox, and upload/rename stay host management operations. Large/unsupported originals can now be downloaded.

Before pushing, the host fix was rebased onto concurrent native-page remount fix `17a184c1`. The combined Vue TypeScript check and all 71 frontend tests passed; focused ESLint passed. Both fixes are preserved.


## Configurable preview ceiling

Scoped Document Viewer 1.7.0 adds a persisted maximum preview size in MiB.
Zero requests unlimited size through the existing host document API; omitted
limits from older callers retain the host's legacy 5 MiB default. Finite values
are passed on every chunk request. Browser sandbox, active-content restrictions,
malformed-document checks and Office archive expansion bounds remain enforced.
The historical 1.6.0 package is preserved unchanged.
