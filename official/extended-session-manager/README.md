# Extended Session Manager

This is maintained official functionality in `official/extended-session-manager`.
The stable ID `example.self-service-session-manager` is preserved for updates;
new releases use the official signer through an exact-ID trust grant. Historical
demo packages retain their original signatures. Installing a newly signed release
requires the successor public key and exact-ID policy described in
[host issue #7](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/issues/7).

The 2.x series ports application [PR #248](https://github.com/Rosefall-a/unnamed_tracking_app/pull/248), inspected at head `5bf43f22bd4991999cd278c5b201817aae439e85`. Current branch previews use Plugin API 1.1. The stable ID remains `example.self-service-session-manager`. This replaces the minimized metadata/Refresh example.

## Experience and source parity

The primary experience is **Account → Sessions** (`/settings?area=account&section=sessions`) and administrator-only **Administration → Session Manager** (`/settings?area=administration&section=admin-sessions`). The host now supplies basic pages showing state, IP, browser details and timestamps. This plugin replaces only those two sections with its extended GeoIP, network, anomaly and map interface, using independently approved page-scoped permissions. It registers no duplicate settings entries and retains its stable plugin ID. Controls use native palette and shape tokens; no host code selects this plugin by ID.

Disabling the plugin or declining either replacement permission leaves that built-in page available. The **Advanced sessions** switch at the top of either page selects the extended or built-in view; turning it off opens the basic page with `basic=1`. Native and sandbox plugin-owned page URLs remain available. The companion host change adding `sessions` and `admin-sessions` replacement targets is merged: earlier hosts do not understand the new capabilities. Existing installations must review and grant the new replacement permissions during update.

Native cards, administration rows and selected map markers summarize browser and operating system. The full user agent is available in an expandable detail so diagnostic information remains accessible without filling every row. This formatting stays inside the plugin; it does not import host frontend code.

The 2.3.1 preview bounds native controls to the host panel. User selectors use
the shared field style, long values wrap or stay within their control, and
expanded GeoIP uploads fit narrow screens. The wide administration table keeps
its own horizontal scroller; it does not widen the surrounding settings page.

| PR #248 behavior | Current native plugin |
| --- | --- |
| Current session; active/expired/revoked records | Reproduced with backend state filtering |
| IP, user agent, country/region/city, timestamps | Reproduced, including creation, activity, expiry, revocation |
| Network type/label, ASN/network number, organization | Reproduced with the source credential-free serializer |
| Session search and admin user filters | Reproduced; country/anomaly filters also expose source metadata |
| GIS map, pan/zoom, clustered selectable pins, admin user colors | Reproduced for loaded pages when City GeoIP is usable |
| Own one/all; admin one/user/server revocation | Reproduced with separate destructive grants and explicit confirmation |
| Admin compact table, City/Country/Network MMDB status/uploads | Reproduced with scoped grants, confirmation, and existing host validation |
| Geographic anomaly and provider notifications | Source session metadata and core notification coordinator reused |

The current account session has no individual revoke button, matching the source. Revoke all includes it and returns the browser to sign-in. Bulk actions affect all unrevoked records in scope, including expired ones, regardless of displayed filters, matching the source SQL. API keys are separate and are not revoked.

Anomalies show the reason and previous location. Shared password/OIDC session creation queues `session_anomaly` notifications through the existing core coordinator, deduplication, provider registry, delivery state, and preferences. This plugin does not resend or invent alerts; notification providers/preferences stay in their normal host Settings surfaces.

The map requests visible OpenStreetMap tiles with browser caching, visible attribution, and an origin-only referrer following the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/). OSM receives the viewing browser's IP, application origin, and tile coordinates. Session identifiers, usernames, IP metadata, and user agents are never sent in tile requests. Locations are approximate; private/local addresses are not plotted.

## Permission review: intentionally high risk

| Permission | Why requested | Risk / destructive behavior |
| --- | --- | --- |
| `sessions.read` | Rich records owned by the caller | Sensitive device, IP, approximate location, and network metadata; never tokens/hashes |
| `sessions.revoke` | Own single/bulk revocation | **Destructive:** signs out browsers, including the current browser during bulk revocation |
| `sessions.admin.read` | Cross-user admin records | **High:** sensitive metadata across users; host admin role independently required |
| `sessions.admin.revoke` | Admin single/user/server revocation | **Destructive, High:** can sign out every browser; admin required |
| `sessions.geoip.read` | Database availability | Admin-only status without filesystem paths |
| `sessions.geoip.configure` | Replace optional MMDB databases | **Destructive, High:** changes shared enrichment data; admin and confirmation required |
| `frontend.page.replace.sessions` | Enhance the built-in account Sessions section | **High:** replaces only this page; independent of session read/revoke grants |
| `frontend.page.replace.admin-sessions` | Enhance the built-in administrator Session Manager section | **High:** replaces only this page; the host still requires administrator access |
| `frontend.native` | Native cards, table, map, file controls | **Critical:** reviewed code executes in the host browser realm, with DOM/browser authority; scoped backend grants remain enforced |
| `backend.routes.plugin` | Optional namespaced JSON handlers | Host authentication, admin policies, lifecycle, limits, and installation grants |

No `api.full`, `backend.routes.host`, arbitrary filesystem/network, broad user-read, or notification-send permission is requested. Read and revoke grants are independent. Declining a grant denies its operation; no broader fallback API is used. Without `frontend.native`, the legacy plugin-owned account page supplies a sandboxed own-session fallback with metadata and confirmed revocation. Full map/admin/configuration parity requires the reviewed native grant.

## Backend security and revocation

All destructive actions declare host-owned confirmation text. Both UI modes ask for confirmation; the backend action endpoint requires strict boolean `confirmed: true` before dispatch. The plugin and gateway also require explicit confirmation. JSON route clients must expressly confirm. Confirmation prevents accidents; it does not replace authorization.

The host authenticates the caller, checks live installation grants and health, and creates current-session context from the authenticated cookie. Caller-supplied `_plugin_context` is overwritten. The domain constrains self-service SQL to the caller and independently checks active admin status for cross-user operations. Knowing a foreign UUID cannot change ownership. Malformed UUIDs are rejected. Disabled/unhealthy plugins cannot dispatch actions, routes, or gateway methods. Plugin Python imports only the standard library and public SDK, and receives no cookies, tokens, hashes, ORM objects, or database connections.

Revocation sets `revoked_at`, preserving audit metadata. Subsequent cookie authentication fails immediately. A generic host auth refresh returns remotely revoked browsers to login; current-browser bulk revocation navigates immediately.

Optional routes relative to `/api/plugins/example.self-service-session-manager/`:

| Method/path | Grant | Caller |
| --- | --- | --- |
| GET `sessions` | `sessions.read` | Owner |
| DELETE `sessions/{session_id}` / `sessions` | `sessions.revoke` | Owner |
| GET `admin/sessions` | `sessions.admin.read` | Administrator |
| DELETE `admin/sessions/{session_id}` / `admin/users/{user_id}/sessions` / `admin/sessions` | `sessions.admin.revoke` | Administrator |

DELETE bodies require `{ "confirmed": true }`. Lists accept `q`, `state`, `country`, `anomaly=true|false`, `limit` (up to 200), `cursor`, and admin-only `user_id`.

MMDB upload uses the generic host capability endpoint `POST /api/plugins/<plugin-id>/capabilities/sessions/geoip?kind=city|country|network&confirmed=true` with multipart `file`. The host validates and atomically replaces the database. Reads are bounded to 256 MiB; proxy limits can be lower. There is no automatic database download, license acquisition, or arbitrary server filesystem access.

## Platform stages 1–4 demonstrated

1. Versioned contracts, risk rationales, installation identity, ownership, separate read/write grants.
2. Normal package inspection, development trust consent, update permission review, health/lifecycle gating; the entrypoint stays alive under the supervisor.
3. Native Settings, admin visibility, host Vue integration/cleanup, host action confirmation, sandbox fallback.
4. Namespaced backend routes with authenticated/admin policies, normalized request envelopes, scoped gateway methods.

## Remaining differences from PR #248

- Lists, map pins, and the admin user selector reflect loaded cursor pages rather than one unbounded response. **Load more** exposes the remainder; search can find users beyond loaded pages.
- GeoIP configuration does not disclose host filesystem paths.
- Every single-session destructive action is confirmed; the source account's individual revoke button was immediate.
- Native integration requires reviewing Critical browser authority plus narrow domain grants. The sandbox fallback lacks map/admin/configuration UI.
- Historical sessions without metadata cannot be retroactively enriched. New sessions use the shared source metadata/anomaly path.
- External map tiles, optional MMDB availability, and configured notification delivery remain deployment dependencies, as in the source.

No source user/admin workflow is omitted from the full native experience.

## Build and verification

Requires a Plugin API/SDK 1.1 host, currently the coordinated `feat/ui-ux-redevelopment` branch. A 1.0 host cannot run this new package; its limited legacy support applies to older packages only. Capability version 1 retains its ownership scopes with additive DTO fields/new operations. Strict destructive confirmation is an intentional security tightening; older clients must send confirmation.

```sh
pytest
node --test tests/session_manager_ui.test.mjs
node tools/capture_sessions.mjs /path/to/host /path/to/evidence http://127.0.0.1:8000 /path/to/temporary-admin-cookies.json
python tools/build_packages.py
python tools/verify_packages.py dist/*.utp
python tools/validate_packages.py dist/*.utp
```

Plugin tests exercise permissions, filters, identifier validation, confirmations, routing, packaging, actual UI controller pagination/cancellation/sign-out/errors/cleanup, and map math. Host HTTP tests execute real SQL/grants for cross-user reads/writes, unauthorized revocation, strict confirmation, disabled plugins, malformed IDs, admin checks, pagination, revoked-cookie rejection, GeoIP uploads, and password metadata/anomaly creation. Existing CI checks remain, with Node UI tests added.

The browser verifier requires an installed, running native package on a disposable local host. It creates its own temporary members, exercises owner and administrator filters/confirmed revocation, verifies foreign-session denial and sign-out without refresh, and captures 320/390/1440/1920-pixel light/dark layouts. It never revokes the administrator's session or unrelated users' sessions; its fixtures are removed afterwards. The optional `SESSION_PACKAGE_SHA256` records the exact tested archive.

Local packages are **unsigned**, requiring normal untrusted-package consent. Release CI supplies its configured reviewed signing identity. Historical packages and signing identities are preserved.

The latest authenticated local-host check uses the current unsigned working-tree
preview at 320, 390, 1440 and 1920 pixels. Owner/admin filters, cancellation,
selected-user revocation, foreign-session denial and sign-out without a refresh
pass. Its [report](../../wiki/docs/assets/screenshots/session-native-conformance.json)
identifies the tested archive and records the actual loaded native UI.

![Authenticated account sessions on a phone](../../wiki/docs/assets/screenshots/session-owner-loaded-390-dark.png)

![Authenticated administrator session filters](../../wiki/docs/assets/screenshots/session-admin-loaded-1440-light.png)

![Native admin component with fixture data](../../wiki/docs/assets/screenshots/session-manager-admin.png)

Screenshot uses the actual native module with disposable fixture data in a local Vue harness, not a deployed authenticated host.


Requires Plugin API v1.1.17 for declared page activation. The native bundle loads
when a contributed page is opened, rather than during unrelated library navigation.
