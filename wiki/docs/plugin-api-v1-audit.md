# Plugin API v1 cross-repository audit

This dated snapshot describes the commits below. For the current lifecycle and
Plugin Manager contract, use [the author guide](plugin-author-guide.md) and
[catalogue specification](catalogue-specification.md).

Audited on 1 October 2026 (Australia/Perth):

- Plugin repository `main`: [`ed7d1d0299a9fc891fb90dfef7e35f84fcd86320`](https://github.com/Unbound-Timeline-Shelf/Plugins/commit/ed7d1d0299a9fc891fb90dfef7e35f84fcd86320).
- Host `plugin-manager`: [`daedc1d8125662065bf27d64ac6311380249a5e6`](https://github.com/Rosefall-a/unnamed_tracking_app/commit/daedc1d8125662065bf27d64ac6311380249a5e6).

This is an audit, not a reference-plugin feature implementation. Plugin source, manifests, SDK, checked-in packages, catalogue, workflows, signing keys and signing behavior were left unchanged. The package builder was exercised in an isolated copy so existing signatures were preserved.

## Result

The SDK wire format, all ten current manifests, declared capability names/versions, seven backend routes, package format, payload integrity, catalogue identities and package versions match the current host. All ten catalogue packages contain current source payloads. However, the repository is **not fully compatible at the UI and activation boundaries**: missing frontend permissions hide existing contributions, three UI documents fail the host schema, and four entrypoints exit rather than remain healthy. Publishing succeeded for the route-example commit, but its workflow has reproducible defects. Seven obsolete/unlisted packages remain in `dist/`.

## What stages 1–4 actually require

The stage names come from [the platform design](history/design-plan.md), section 19. The host changes are:

| Stage | Host implementation | Required plugin-side response |
| --- | --- | --- |
| 1: architecture/security/contracts | `9638e87`, capability hierarchy, exact permission/version matching, installation identities and contribution contracts | Declare each capability actually consumed, with matching permission versions and rationales. Existing domain capability names remain valid. Plugins do not supply installation identity or import the host's permission/lifecycle implementation. |
| 2: installer/trust/dependencies/updates | `c6853c6`, followed by authorization and installation-transaction fixes through the audited head | Keep manifests/packages valid and support healthy activation. Trust and user consent belong to the host. No plugin-side installer, trust classifier, dependency coordinator, package-format change or signing-key change is required. |
| 3: frontend/integration framework | `8bc27ed`, `ce70d58`, `b2bd256` | Existing host contributions need their scoped frontend grants. Sandboxed `frontend` bundles remain valid; none of these examples declares `native_frontend`, so none needs `frontend.native` or conversion to a native Vue bundle. |
| 4: backend integration | `08f9351`, plus later live-grant/lifecycle corrections | **Only plugins opting into backend handlers** need `backend_routes`, a route-scope capability/permission and handlers implementing the request/response envelope. Plugins without backend routes need no migration. |

The later host fixes enforce live grants, current installation identity, active contributions, worker shutdown and atomic permission/package commits. They do not change the SDK request shape, add a required manifest field to every plugin, or require plugins to implement host infrastructure.

### Required corrections for existing behavior

1. Request `frontend.navigation.main` v1, with a matching permission rationale, in **Discord Delivery Provider, Help Button, Jellyfin Media Sync, Scoped Document Viewer and Self-Service Session Manager**. These five already declare `pages[].navigation.sidebar`; `src/frontend/src/state/pluginExtensions.ts` creates that legacy navigation only with this grant.
2. Help Button also needs `frontend.overlay` v1 for `app.global` and `frontend.page.replace.home` v1 for `home.replace`. The actual host `_filter_ui_document` removes both extensions under its current empty capability set. Preserve the separate page-specific grant; do not substitute `api.full`.
3. Correct the already-shipped UI documents for **Playtime Report, Recently Played Notifier and Metadata Curator**. `pages[].components` is not a `UiPage` field. Metadata Curator additionally puts a field directly in `settings[]`; the host expects a settings section with `title` and `fields`. These are **pre-existing v1 contract violations**, not new fields/removals introduced by stages 1–4: the same schema rejects them before `9638e87`. Their action declarations also lack handlers; do not claim that changing JSON alone completes their interactive functionality.
4. **UI/API Example, Playtime Report, Recently Played Notifier and Metadata Curator** execute startup requests, report ready and exit with code 0. The host supervisor's `running()` and registry's `health()` then return false; current lifecycle gating deactivates contributions. A successful `lifecycle.ready` response does not establish lasting health. Decide how to retain existing work under the host's long-lived entrypoint/action model before claiming successful activation. This is an existing runtime-model mismatch exposed by the stricter stages 1–2 lifecycle work, not a reason to loosen host health checks.

Any later manifest/payload corrections should receive appropriate new plugin versions, updated catalogue entries and fresh packages. Newly requested frontend permissions must pass the host's normal update consent flow.

## Recent namespaced backend route changes

[`7f459a7`](https://github.com/Unbound-Timeline-Shelf/Plugins/commit/7f459a7062ca6bf7ad9e73e3875f4e60b27dc0cd) opted two existing plugins into stage 4. Adding these examples was optional; the following parts are required **once those handlers are shipped**:

- Document Viewer: version `1.2.0` → `1.3.0`; add `backend.routes.plugin` v1 and its permission; declare two relative `plugin`-scope GET routes; expose `list_documents_route` and `read_document_route`.
- Session Manager: version `1.1.0` → `1.2.0`; add the same route capability and permission; declare two user routes and three admin routes; expose five corresponding handlers. All three admin declarations use `authorization: admin`.
- Handlers consume normalized query lists and path parameters and return `{status_code, body}`. Existing scoped domain methods remain the data-access boundary. They do not obtain cookies, bearer tokens, ORM objects, routers or database sessions.
- SDK `route_response` and `route_query_value` are **convenience helpers**, not mandatory new SDK APIs. Equivalent inline code satisfies the host. Formatting `request()` did not change its wire behavior.
- The route-aware package validator, tests and route documentation are supporting validation/documentation, not runtime infrastructure that belongs in the plugin repository.
- The two changed versions require packages and catalogue updates. Because every package bundles `sdk/plugin_protocol.py`, changing that helper also requires rebuilding the other eight current packages. `ed7d1d0` performed this rebuild.

No package-builder algorithm, publisher registry, signing implementation or workflow was changed by `7f459a7`/`ed7d1d0`. Removing obsolete examples, redesigning Help Button/Jellyfin, adding native bundles, expanding document/session functionality or changing signing identities is **not** required by this route contract.

| Plugin | Method/path relative to `/api/plugins/<plugin-id>/` | Authorization | Scoped gateway method |
| --- | --- | --- | --- |
| Document Viewer | GET `documents` | authenticated | `documents.list` / `documents.read` capability |
| Document Viewer | GET `documents/{document_id}` | authenticated | `documents.read` / `documents.read` capability |
| Session Manager | GET `sessions` | authenticated | `sessions.list` / `sessions.read` capability |
| Session Manager | DELETE `sessions/{session_id}` | authenticated | `sessions.revoke` |
| Session Manager | GET `admin/sessions` | admin | `sessions.admin.list` / `sessions.admin.read` capability |
| Session Manager | DELETE `admin/sessions/{session_id}` | admin | `sessions.admin.revoke` |
| Session Manager | DELETE `admin/sessions` | admin | `sessions.admin.revoke_all` / `sessions.admin.revoke` capability |

All declarations pass the actual host manifest model: IDs, relative paths, parameter names, methods, handler entrypoints, scope, authorization and route overlap rules. All seven actual packaged handlers were executed using the host runtime's `_route_command` and actual SDK, with fixture gateway responses; their responses passed the host's `PluginBackendRouteResponse`. Host route tests separately cover authentication, installation grants, admin checks, disabled/failed plugins and lifecycle changes.

These backend handlers are opt-in HTTP APIs. Existing sandboxed frontends still use the host `plugin.run-action` bridge; changing them to call the new URLs is not a required migration. Browser destructive-action confirmation remains part of the action/UI flow; it is not an additional backend-route manifest contract.

## Verification matrix

| Check | Result and qualification |
| --- | --- |
| SDK/API v1 | Pass: SDK emits `api_version: v1`, `method`, `capability`, object `payload`, consumes `payload`/`error` responses. Host runtime defaults capability semantics to version 1 and injects authoritative user/installation context. `lifecycle.ready` is a runtime-local method, so its descriptive capability string is not a newly required manifest capability. |
| Manifest fields | Pass: all ten source and current package manifests validate through actual host `PluginManifest`, including optional `frontend` and `backend_routes`; permission names/versions match capabilities. SDK `1.0.0` and application `1.0.0` satisfy the declared ranges. This does not imply compatibility with arbitrary future application versions. |
| Capability names/versions | Pass for declared capabilities: all resolve to the host enum and request version 1. Missing frontend declarations are the separate failures above. |
| Backend routes | Pass for all seven shipped declarations/handlers; no example claims a direct host route or requests `backend.routes.host`. |
| Frontend assets/bridge | Pass: five `frontend/index.html` declarations resolve to packaged assets, use the sandboxed bridge, and require no native bundle. The runtime overlays `frontend` from the manifest onto `ui.json`; omission from the source UI document is valid. |
| UI schema/contributions | Fail as detailed above. Six shipped `ui.json` documents validate; three fail. UI/API Example has no `ui.json`: the runtime supplies a valid empty document, so manifest IDs alone do not demonstrate an actual declarative page. |
| Package builder/host acceptance | Pass for package structure/integrity: fresh ordinary builds produce exactly ten packages accepted by actual host inspection. UI/runtime failures remain separate from package acceptance. |
| Unsigned classification | Pass: fresh builds are `unsigned`, `signature_present=false`, `signature_verified=false`, publisher identity/key both null. The consent-aware inspection marks them installable but unverified. The host's strict signature verifier rejects them; neither path silently treats them as trusted. The two old 1.0.0 domain packages are also correctly classified unsigned. |
| Signed publisher | Pass cryptographically: all ten current catalogue packages are signed by `non-secret-testkey`. The current host identifies them as **Unnamed Tracking Official (test key)** and accepts that `retiring`, `example.`-scoped key. Older lifecycle/events/advanced packages use `official-example-2026`, identified as **Unnamed Tracking Official**. Do not describe current packages as signed with the production official-example key. |
| Publisher policy agreement | Pre-existing drift: plugin registry labels `non-secret-testkey` active/“Unnamed Tracking Official”; host labels it retiring/“Unnamed Tracking Official (test key)”. Public key bytes, digest and scope match. This needs an explicit publisher-policy decision, not an automatic key rotation or signature workaround. |
| Catalogue URLs/versions/set | Pass: `list.json` has exactly ten unique IDs, matching source manifest identity, name, description and current version. Every URL is the canonical repository `main/dist/<id>-<version>.utp` path and names a tracked package. Every package filename version matches its embedded manifest. |
| Generated packages current | Pass for all ten catalogue artifacts: embedded manifests match source except build-computed integrity; payload bytes match Git blobs, including the shared SDK, UI and frontend assets. Git blobs were used to avoid mistaking Windows CRLF conversion for stale published Linux payloads. Fail for `dist/` as a canonical current-only set: seven obsolete files remain. |
| README plugin set | Fail: prose says “four” real demos but lists six; installable count says eight but actual set is ten; table omits Help Button and Jellyfin. Removal claims do not describe the obsolete packages still tracked in `dist/`. |
| Publish CI | Last observed route-example publish and CI runs succeeded, but edge cases fail or bypass intended change detection; see below. Existing checks were neither removed nor weakened. |
| Release signing | Unchanged by the route work/audit: same environment variable names, registered active/scoped signer check, Ed25519 algorithm, canonical payload SHA-256 and `plugin-package-v1:<sha256>` signature bytes, and `--require-signing` workflow invocation. A release build without its signer fails closed. No production secret was requested or used. |
| Host implementation imports | Pass: AST inspection of all ten plugin source files and SDK found no host `src`, `plugin_api`, FastAPI or SQLAlchemy imports. Plugin-owned storage/secret files and standard-library imports are not host-source dependencies. Host-side test fixtures are not plugin code. |

## Repository cleanup and CI findings, separate from stages 1–4

### Supported set and stale packages

The actual source/catalogue set is ten plugins: six real demos (**Playtime Report, Recently Played Notifier, Metadata Curator, UI Playground, Help Button, Jellyfin Media Sync**) and four references (**UI/API Example, Scoped Document Viewer, Self-Service Session Manager, Discord Delivery Provider**). These are present-day repository identities, not a claim that every example is fully functional on the audited host.

The seven unlisted `dist/` files are:

- `example.advanced-1.0.0.utp`
- `example.events-1.0.0.utp`
- `example.lifecycle-1.0.0.utp`
- `example.scoped-document-viewer-1.0.0.utp`
- `example.scoped-document-viewer-1.2.0.utp`
- `example.self-service-session-manager-1.0.0.utp`
- `example.self-service-session-manager-1.1.0.utp`

They are valid historical artifacts, not current supported sources. The builder intentionally deletes all `dist/*.utp` before generating the ten-manifest set, but publishing runs `git add dist/*.utp list.json`. In Bash the wildcard expands to surviving files, leaving deleted tracked packages unstaged. This reproduces ` D dist/old.utp` in a local fixture and explains why rebuilding does not remove these old files from Git. If current-only `dist/` remains the policy, stage deletions with a directory-based command such as `git add -A -- dist list.json`; preserve actual historical Releases.

README counts/table and stale `AGENTS.md` reference lists should be reconciled with the ten manifests. Changing those lists or removing obsolete packages is repository cleanup, not a host API migration. `list.json` itself already matches the supported source set and does not need speculative new entries.

### Publishing defects

The [route-example publish run](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/actions/runs/36808810557) successfully ran tests, signed, verified, validated and committed all ten current packages. The [parallel CI run](https://github.com/Rosefall-a/unnamed_tracking_app_plugins/actions/runs/36808810625) also succeeded. Nevertheless:

1. Checkout has the default shallow history. The successful publish log actually contains `fatal: Invalid revision range` for its before/after range. `git diff ... || true` produces empty `CHANGED`; `echo "$CHANGED" | grep -vq '^dist/'` regards that blank line as a non-dist change and sets `needs_build=true`. The run succeeded through this fallback, not successful change detection. A new branch/all-zero `before` also needs explicit handling.
2. With usable history, `echo "changed=$CHANGED" >> $GITHUB_OUTPUT` writes bare second/subsequent filenames when multiple files changed. Those lines do not use valid Actions output syntax. Fetching history alone is therefore not a complete fix; eliminate the unused output or use the documented multiline form.
3. In a shallow release/manual run, `git rev-parse HEAD~1` can print the unresolved `HEAD~1` before failing, so the fallback substitution contains an invalid range. With full history, a release/manual run at the current dist-only commit chooses `needs_build=false`, gating off tests, signing and verification before unconditional release upload. Release builds must be explicitly unconditional; ordinary push filtering must not bypass release signing.
4. The package commit has no no-change guard. Repeated signed builds are deterministic; `git commit` then exits 1 if nothing changed. This is reproducible without changing signing behavior.
5. Bash staging misses deleted artifacts as described above. A release event resolving to `refs/heads/main` also satisfies the current commit step; constrain branch writeback to intended events and avoid changing signed historical releases as a cleanup technique.

Repair these workflow issues together as repository publishing work. Preserve the full test suite, package verification/validation, required release signer, and reviewed publisher identity. Do not make them non-blocking to obtain a green run.

### Validator coverage gaps

`tools/validate_packages.py` checks a useful subset, not the complete host manifest/UI contract. A package changed to `backend_routes[0].authorization = "anonymous"` passes the local validator but is rejected by actual host `PluginManifest`. Unknown route fields, host field-length constraints, full capability-name validation and UI schema/contribution grants are likewise not fully covered. Its handler checks validate syntax rather than proving that the module/function exists; actual shipped handlers do exist. The original CI suite therefore passes while incompatible UIs and hidden contributions remain.

Keep validation strict and add regression coverage for these real failures when implementing fixes. Do not copy host installation/runtime infrastructure into plugins or claim that the local validator replaces host validation.

## Verification performed and limits

- Original plugin suite: **38 passed** (`python -m pytest -q`, with a workspace-local temporary directory on Windows).
- Host API/manifest/UI contract suites: **40 passed**.
- Host backend-route, route-capability and UI-extension suites: **31 passed**.
- Host cross-repository signed-package trust/installation tests: **2 passed**, using this plugin checkout.
- Actual host inspection of all **17** checked-in packages; plugin verification/validation of each; exact source/payload comparison for the **10** current artifacts; catalogue/filename/internal-version checks.
- Isolated fresh unsigned build: **10** packages, all accepted by consent-aware host inspection and rejected by the strict signed verifier; second build byte-identical; missing release signer rejected.
- Actual packaged handler subprocesses: **7** routes, actual SDK requests and host response model, fixture gateway responses. Actual four one-shot entrypoint subprocesses exited 0 and were rejected as healthy by the host supervisor. Actual Help Button host UI filtering removed both ungranted extensions.
- Existing publish shell reproduced against full and shallow local checkouts; invalid multiline outputs, release bypass, unstaged deletions and no-op commit failure observed.
- GitHub job summaries and logs inspected for the successful route-example publish run; production signing secrets and live releases were not accessed or changed.

Useful existing host test commands (from the host's `src/backend`, with development
configuration available). Set `HOST_BACKEND` to that checkout's absolute backend
directory; these test paths belong to the host, not this plugin repository:

```bash
python -m pytest -q "$HOST_BACKEND/tests/test_plugin_api_contracts.py" "$HOST_BACKEND/tests/test_plugin_manifest.py" "$HOST_BACKEND/tests/test_plugin_ui_contracts.py"
python -m pytest -q "$HOST_BACKEND/tests/test_plugin_backend_routes.py" "$HOST_BACKEND/tests/test_plugin_route_capabilities.py" "$HOST_BACKEND/tests/test_plugin_ui_extensions.py"
PLUGIN_REPOSITORY_PATH=/path/to/unnamed_tracking_app_plugins python -m pytest -q "$HOST_BACKEND/tests/test_plugin_repository_trust.py"
```

This is package/contract and fixture-based integration verification. It does not establish production browser rendering, live database ownership behavior for every example, real Jellyfin/Discord delivery, or Linux process/network isolation. No full Docker/database E2E or signed production rebuild was performed. The existing host cross-repository test selects one checked-in package; the audit's separate inspection covered every package.

## Coherent follow-up boundaries

Keep subsequent implementation in a small number of coherent commits: (1) required existing frontend declarations and their consent/version/package updates; (2) existing UI/lifecycle compatibility corrections with regression tests, without expanding reference functionality; (3) publishing/catalogue/documentation cleanup. Publisher-policy changes, native frontend examples and stages 5–7 feature work need separate explicit scope. The current audit is one documentation commit and leaves CI and release signing unchanged.
