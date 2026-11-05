# Session Manager validation

## Official Extended Session Manager and key rotation

On 7 October 2026, the maintained source moved to
`official/extended-session-manager` and was renamed **Extended Session Manager**.
Its existing plugin ID is preserved for updates. All 312 Python tests and the
native/browser checks pass in CI. An isolated signed publication verifies 21
current published plugins, including Extended Session Manager 2.4.0 under the
new official key. The 51 reviewed signed historical archives remain unchanged;
expired keys cannot authorize new or backdated archives after Perth midnight.

The actual unsigned preview package was updated through the disposable host's
public installer, preserving its existing data and permissions. The screenshot
shows the new title, the Advanced sessions switch, browser summaries, map and
administrator table with synthetic users and metadata. Successor trust and
expiry enforcement on deployed hosts are requested in
[host issue #7](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/issues/7).

![Extended Session Manager administrator preview](assets/extended-session-manager.jpg)

## Integrated session pages: 2.4.0 preview

Validation on 7 October 2026 uses the actual locally built unsigned `.utp`,
installed and updated through the disposable host's normal plugin manager.
The companion host adds basic account cards and a compact administrator table;
the plugin replaces those same destinations through separately approved page grants.
The built-in pages remain available when the plugin is disabled, lacks grants,
or the user turns off the Advanced sessions switch at the top of either page.

The independent Linux suite passes 283 tests. All seven native session UI tests
pass, including browser/OS summaries, cancellation, revocation, pagination,
cleanup and map projection/clustering. The strict documentation build and package
digest verification pass. `tools/check_host_contract.py` passes against the
companion host source, including real package installation and disabled lifecycle.

Authenticated browser checks cover both native replacement pages, expandable
user agents, built-in state/user filtering, cancellation and confirmed revocation,
and narrow-screen overflow. Optional City database upload uses the public
MaxMind test database, and screenshots use synthetic users, network metadata,
anomalies and coordinates. The map renders, zooms and displays the simplified
browser summary for a selected marker.

The plugin CI host-contract job selects matching feature branches in the owned
host repository, falling back to `main`. Publication requires the
[companion host PR](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/pull/5)
to merge before the plugin release uses the new page capabilities. The host's full
backend suite passes 1,505 tests with two skips, and its additional acceptance
acquisition regression passes separately. Frontend checks pass 298 tests.
The inherited host Pylint duplicate-code warning was traced to identical image
redirects and removed by sharing their HTTP response, with regression coverage
for status and cache headers. The acceptance harness now substitutes fixture
downloads at the current host acquisition boundary; remote downloads still use
the normal host implementation.
No checks or security boundaries were weakened. Preview packages are unsigned;
official publication continues through the existing signing workflow.

![Integrated administrator sessions and map](assets/screenshots/session-integrated-admin.jpg)

![Integrated personal sessions with browser summaries](assets/screenshots/session-integrated-owner.jpg)

## Historical unsigned CI package: 2.3.1

Validation on 6 October 2026 uses the actual `unsigned-dist` artifact
`11386044038` from companion source
`2236d8f1c93682dda68282545f98d6301762503d`. The installed archive SHA-256 is
`512dc8370dcdd330b0719c47da28153fae087962bbfce78bc70484c9d9712ba1`.
Its payload digest and version match the running package. The production host
image is `uta-ui-production:a1bf2452`; no replacement styles are injected.

All 32 loaded owner/administrator layouts pass in Chromium and WebKit at 320,
390, 768 and 1440 pixels, in light and dark modes. Acceptance measures the
plugin against its actual parent panel, including expanded GeoIP controls,
long account labels, keyboard focus and the table's own horizontal scrolling.
The administrator page is reached through the real Settings buttons. Stress
labels are browser-only; account, session and GeoIP records are unchanged.

The [machine-readable report](assets/screenshots/session-fit-conformance.json)
records all dimensions and captures. Reproduce it against a disposable local
host with the reviewed CI package already installed:

```sh
node tools/check_session_layouts.mjs output http://127.0.0.1:8000 admin-cookies.json installed-session-manager.utp
```

The checker restores cosmetic preferences and temporarily withdrawn demo
plugins. `SESSION_BROWSER=chromium` or `webkit` selects one engine; the default
checks both. `SESSION_SOURCE_HEAD`, `SESSION_HOST_IMAGE` and
`SESSION_ARTIFACT_ID` record provenance.

![Current owner sessions on a phone](assets/screenshots/session-fit-webkit-sessions-390-dark.png)

![Current administrator controls at 320 pixels](assets/screenshots/session-fit-webkit-admin-sessions-320-light.png)

![Current administrator sessions on desktop](assets/screenshots/session-fit-chromium-admin-sessions-1440-light.png)

The full companion Python suite passes all 249 tests, and the native Session
Manager interaction suite passes all six tests. Plugin checks and both host
integration workflows are green for the recorded source. Physical devices and
OS-specific installation prompts remain manual surfaces.

## Historical 2.0.0 validation

Validation on 1 October 2026, against app `plugin-manager` base `daedc1d8125662065bf27d64ac6311380249a5e6` and plugin base `ed7d1d0299a9fc891fb90dfef7e35f84fcd86320`, using the coordinated local changes. PR #248's actual head `5bf43f22bd4991999cd278c5b201817aae439e85` and stages 1–4 contracts/runtime/UI/grant enforcement were inspected before implementation. The earlier [platform audit](plugin-api-v1-audit.md) describes the prior minimized example; [the current README](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/official/extended-session-manager/README.md) supersedes its Session Manager observations.

| Check                                                | Result                                                                                                                                                                                                                                         |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Complete plugin Python suite                         | 57 passed                                                                                                                                                                                                                                      |
| Actual native UI controller/map tests                | 6 passed; filters/pagination, confirmation cancellation, bulk sign-out, errors, cleanup, map math                                                                                                                                              |
| Sandbox frontend syntax                              | `node --check` passed                                                                                                                                                                                                                          |
| Build, payload/signature verifier, package validator | All ten fresh development packages passed; unrelated historical signed artifacts restored unchanged after the build                                                                                                                            |
| Actual host package/manifest/UI inspection           | Passed; new package correctly unsigned; strict signature-required verifier rejects it                                                                                                                                                          |
| Installed package SDK execution                      | Eight actions and seven routes passed using actual runtime command builders, packaged SDK, fixture gateway replies, and host response validation                                                                                               |
| Relevant app backend suites                          | 254 passed, 2 existing skips; all `test_plugin*.py` except the separately attempted install-source integration module, plus auth/session tests                                                                                                 |
| Targeted persisted SQL/HTTP security tests           | Included above: cross-user reads/revokes, independent grants, malformed UUIDs, missing/strict confirmation, disabled plugins, administrator role, bounded pagination, cookie rejection, GeoIP constraints, shared login metadata/anomaly queue |
| Full frontend suite                                  | 59 passed in 10 files                                                                                                                                                                                                                          |
| Frontend lint, types, production build               | ESLint, vue-tsc, Vite passed                                                                                                                                                                                                                   |
| Changed frontend formatting                          | Prettier passed                                                                                                                                                                                                                                |
| Full backend types                                   | mypy passed, 187 source files                                                                                                                                                                                                                  |
| Full backend Pylint                                  | 9.18/10, above existing CI's unchanged 9.0 threshold; warnings remain                                                                                                                                                                          |
| Ruff                                                 | New session module and changed plugin Python files pass project rules. Full backend has pre-existing diagnostics; baseline comparison confirms no new diagnostics                                                                              |
| Visual inspection                                    | Actual native module rendered with local Vue and disposable fixtures; IP/device/ASN/anomaly/current metadata and map visible, table made scrollable, tile referrer corrected. Screenshot linked from README                                    |

## Environment limits and unfinished verification

The broader app plugin run was attempted: 252 passed and 2 skipped, with 238 setup errors in `test_plugin_install_sources.py` because psycopg async rejects Windows' Proactor event loop before connecting to the PostgreSQL fixture. This environment has no provisioned CI PostgreSQL service. This is not a claim that those integration tests passed.

The full runtime suite was attempted: 58 passed, with two failures in Linux-specific behavior (`test_plugin_storage_files_are_owner_only` uses POSIX permission bits; `test_action_handler_can_use_mediated_plugin_gateway` uses `preexec_fn`, unsupported on Windows). Live Linux sandbox/supervisor and PostgreSQL integration must still run in normal Ubuntu CI. No tests, isolation checks, CI thresholds, or approval/trust checks were relaxed.

Global Prettier also reports existing untouched formatting differences. Changed files pass; unrelated files were not reformatted. Ruff baseline diagnostics are recorded rather than suppressed.

The browser's first test confirmation dialog stalled the in-app automation surface; browser interaction checks could not be completed reliably. Confirmation is independently covered by host HTTP, host native bridge, and actual controller tests. The screenshot proves rendering, not a deployed end-to-end authenticated session.

The new checked-in `.utp` is deliberately unsigned. Production release signing uses existing CI configuration and was not exercised without the release key. Both repositories require their coordinated commits for this plugin version. No private key, signing workaround, or altered historical signature is introduced.
