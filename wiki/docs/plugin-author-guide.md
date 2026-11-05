# Plugin author manual and API reference

New authors: start with [Create your first plugin](getting-started/first-plugin.md).
The [wiki home](index.md) provides development recipes, lifecycle/security,
publishing/catalogue tutorials, testing and troubleshooting. This page retains
the detailed existing v1 reference used by those tutorials.

This guide describes Plugin API v1, the existing `.utp` package format and this
repository's generated distribution. You can develop and publish independently
of the official catalogue. Start with the [catalogue specification](catalogue-specification.md)
if you maintain a list of other authors' packages.

## Host compatibility

The public manifest/UI schemas originated from host `plugin-manager` revision
`f1165fcc805e57ee428e7bc42fa6b83f4a6caf25`. The v1.1 host is now merged into
`main`. Contract CI checks that branch by default, prefers a matching feature branch when
available, and accepts an explicit host revision for coordinated development.
Install and test against the current host build;
the frozen schemas describe the v1 authoring contract, not current host behavior.

Runtime integration temporarily pins verified host revision
`a2d1c898f4fdfb0270234dad58d73f3eee051568` (current main plus validation fixes)
while [host #432](https://github.com/Rosefall-a/unnamed_tracking_app/pull/432)
awaits its required review. This fixes selection of the retained signed v1.0
archive after v1.1 publication advances the catalogue. The same explicit-ref and
matching-branch options remain available. Once #432 is merged, the default
runtime ref can return to `main`.

The current host accepts `list.json` version 1 and `.utp` v1. It consumes the
current identity, name, description, version, package URL, dependencies, release
notes and optional changelog URL. The generated list retains those fields and
adds release history, documentation, tags, scopes, hashes and release policies.
The current Plugin Manager consumes tags, packaged README, permission declarations,
publisher/build information, payload and archive hashes, and per-release update
policy. It checks catalogue identity/version and hashes during preview,
installation and updates. The signed `distribution.json` payload supplies tags,
release notes and resolved automatic-update policy even when the manifest uses
the older optional-field defaults. Permission risk always comes from the host.
Catalogue release history remains distribution metadata; manual rollback selects
a package retained by the host. No second runtime, package format or permission
system is introduced here.

## Project structure

For this builder, place demos below `examples/` and maintained features/previews
below `official/`; both use the same validator and security boundary. The directory name need not
equal the globally unique plugin ID:

```text
my-plugin-repository/
  catalogue.json
  examples/my-plugin/
    manifest.json
    release.json
    README.md
    icon.svg                 # optional, declared by release.json
    plugin.py
    helpers.py               # optional plugin-owned Python modules
    ui.json                  # required when UI IDs are declared
    frontend/                # optional sandboxed browser bundle
    native/                  # optional privileged host Vue modules
  sdk/plugin_protocol.py
  tools/                     # this repository's build/validation tools + schemas
  publishers/registry.json
  publishers/my-key.public-key.b64
  tests/
  dist/                      # immutable generated packages, including old versions
  releases/                  # generated append-only release records
  list.json                  # generated catalogue, never edited by hand
```

Keep private signing keys outside the checkout. Generated metadata and packages
are distribution outputs, not separate authoring inputs. Do not synchronize
versions by manually editing `list.json`, history records or ZIPs.

## Manifest

`manifest.json` is the public runtime/security contract. For a minimal read-only
game plugin, use:

```json
{
  "manifest_version": 1,
  "plugin_id": "org.example.library-summary",
  "name": "Library Summary",
  "version": "1.0.0",
  "description": "Summarizes the signed-in user's game library.",
  "entrypoint": "plugin:main",
  "sdk_version_range": "^1.0.0",
  "application_version_range": "^1.0.0",
  "capabilities": [{"name": "games.read", "version": 1}],
  "permissions": [{
    "capability": {"name": "games.read", "version": 1},
    "rationale": "Count games requested by the signed-in user."
  }],
  "dependencies": [],
  "ui": {"settings": [], "actions": ["summarize"], "pages": ["summary"], "menus": []},
  "storage": {"quota_mb": 1},
  "integrity": {"sha256": "0000000000000000000000000000000000000000000000000000000000000000", "signature": null, "key_id": null}
}
```

Add `frontend.navigation.main` to capabilities and matching permissions if you
choose sidebar navigation. The example below deliberately uses the plugin's
detail page instead. Add `plugin.settings` before using ordinary settings fields
or `settings.get`. `storage.quota_mb` is a quota declaration, not permission to
access host files. A `null` quota leaves quota selection to the host.

`plugin_id` is stable across updates. Use a domain/publisher namespace you own;
do not reuse another plugin's `example.*` or `official.*` identity. Versions are strict stable SemVer
`MAJOR.MINOR.PATCH`; prerelease/build suffixes are not supported by this host.
Compatibility ranges accept exact versions, `^1.0.0`, `~1.0.0`, `1.x`, `*`, and
comma-separated AND constraints such as `>=1.0.0,<2.0.0`. They do not use npm's
space-separated AND or `||` syntax. Declare the range actually tested. Dependencies
use `{ "plugin_id": "org.example.helper", "version_range": "^1.0.0", "optional": false }`.
The host owns dependency resolution, compatibility decisions and activation.

The package builder generates the final manifest version and integrity. Source
manifests retain a placeholder digest and no signature. A signed source manifest
is not a replacement for building and verifying the package.

## Capabilities, permissions and ownership

Each capability reference has a stable name and semantic version. Each requested
permission includes that exact reference and a human-readable rationale. The
host grants/revokes permissions per installation and authenticated context;
declaring a permission does not grant it. The host classifies risk from its own
capability definitions. Do not add `risk`, risk levels or approval decisions to
manifests or `release.json`. The schemas reject such extra fields.

Common capabilities and the existing examples are:

| Capability | Use / example |
| --- | --- |
| `games.read` | `games.list`, `games.metadata.search`; reports and curator |
| `media.read`, `media.write` | `media.list`, `media.import`, `media.sync`; Jellyfin demo and official preview |
| `documents.read` | `documents.list`, `documents.read`; Scoped Document Viewer |
| `sessions.read`, `sessions.revoke` | Current-user session inspection and revocation |
| `sessions.admin.read`, `sessions.admin.revoke` | Explicit administrator session operations |
| `sessions.geoip.read`, `sessions.geoip.configure` | GeoIP status/configuration |
| `notifications.send` | Host notification side effects |
| `notification_providers.register`, `notification_providers.deliver` | Core-coordinated delivery provider |
| `plugin.settings`, `plugin.storage` | Plugin configuration and owned persistent data |
| `events.subscribe`, `tasks.background` | Event polling and supervised background work |
| `backend.routes.plugin` | Namespaced, authenticated JSON handlers |
| `frontend.navigation.*`, `frontend.settings`, `frontend.routes` | Declared host contributions |
| `frontend.native` | Privileged code in the host Vue context |
| `network.outbound` | Permission to contact external destinations under runtime policy |

The full list and object fields are available in the checked-in public schemas
under `tools/schemas/`. Availability of a capability does not imply every
conceivable operation exists. Use documented operations demonstrated by the
examples. `api.full` is an exceptional explicit permission: it allows plugins to
read and modify all user data, and must be reviewed by the host administrator.

Host user data stays host-owned. Plugins must not import database models, access
host filesystem paths or carry their own host credentials. The gateway supplies
authoritative user and installation identities. Do not take a user ID from an
untrusted browser field to choose which user's library to read.

`storage.get`/`storage.put` operate on installation-owned storage. If stored
results contain user data, additionally namespace keys using the host-injected
action context, for example `users/<_plugin_context.user_id>/latest-report`.
Do not assume a plugin-global key is user-private. Use the supported private broker
for credentials, including write-only `secrets/` keys; Jellyfin's official preview
keeps tokens out of frontend results and never persists passwords. This storage is
private installation data with host-managed access controls, not an encrypted vault.
Do not expose secrets through action results,
catalogue metadata or ordinary settings. Uninstallation/retention and rollback
of persistent data are host policy, not package-build operations.

The current Plugin Manager applies these data rules to configuration, secrets and
plugin-owned storage. Packages contain code and defaults, never the installation's
saved data.

Jellyfin's official preview exercises generic provider enrichment, bounded JSON
POST for password/Quick Connect, and optional subscribed-user notifications.
The [media tutorial](development/media.md) documents those additive v1 APIs;
no plugin ID gets a host exemption. `catalogue.json.unreleased_plugins` keeps
an unsigned preview out of signed publication until a reviewed signing key has
the correct namespace scope. Tagging a package official does not establish trust.

| Operation | Plugin-owned data |
| --- | --- |
| Host/runtime restart, disable/enable, normal update | Preserved |
| Manual rollback or failed-update restoration | Preserved; your data format must remain compatible with the previous code |
| Reinstall retaining data | Preserved |
| Explicitly confirmed reinstall with purge | Removed; configuration and permission approval are reset |
| Uninstall | Removed along with plugin-owned host records and retained packages |

Both repository CI workflows now run the host's real-worker/browser lifecycle
acceptance against the current `plugin-manager` branch. It uses a disposable
database and publisher, verifies live official downloads, and tests a signed
Jellyfin release sequence. See the host's
[integration validation instructions](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/blob/main/wiki/docs/development/plugin-validation.md)
for local prerequisites, commands and environment limits.

## Runtime and SDK

Use the bundled SDK for newline-delimited JSON requests over standard I/O:

```python
from __future__ import annotations
import time
from sdk.plugin_protocol import request

def summarize(values: dict) -> dict:
    del values
    result = request("games.list", "games.read", {"limit": 50})
    return {"game_count": len(result.get("games", []))}

def main() -> None:
    request("lifecycle.ready", "lifecycle.ready", {})
    while True:
        time.sleep(3600)
```

`request()` sends `{api_version: "v1", method, capability, payload}` and receives
an object `payload` or error. `lifecycle.ready` is runtime-local; it is not a new
permission to invent in the manifest. The host imports `plugin:main` directly,
so an `if __name__ == "__main__"` block alone cannot initialize the plugin.
Keep the entrypoint alive while enabled. Reporting ready and immediately exiting
does not establish lasting worker health. Put user-triggered work in action
handlers accepting one dictionary and returning a JSON-compatible dictionary.
The host starts a separate handler subprocess and injects `_plugin_context`.
Keep protocol output on stdout; use stderr for diagnostics. Do not log secrets.

The runtime supervises processes, enforces execution/permission policy and stops
disabled/unhealthy workers. Native frontend activation must return cleanup that
removes polling timers, listeners and mounted components. Test denied permissions,
failed gateway responses and disable/unmount behavior. Do not copy host runtime
infrastructure into a plugin.

## Pages, configuration and routes

A minimal `ui.json` corresponding to the manifest above is:

```json
{
  "schema_version": "v1",
  "plugin_id": "org.example.library-summary",
  "title": "Library Summary",
  "settings": [],
  "actions": [{"id": "summarize", "label": "Summarize", "handler": "plugin:summarize", "capability": {"name": "games.read", "version": 1}}],
  "pages": [{"id": "summary", "title": "Library Summary", "description": "Count up to 50 games.", "actions": ["summarize"]}],
  "menus": []
}
```

Pages refer to declared settings sections, actions, tables and dialogs by ID;
`pages[].components` is not a v1 field. Settings are sections with `id`, `title`
and `fields`, not individual fields placed directly in `settings[]`. Action
handlers must actually exist. Manifest UI IDs and `ui.json` IDs must agree.
For field types, validation and contribution slots, use the public UI schema and
the working examples. Request the matching frontend capability for sidebar,
Settings, overlays, routes and other host contributions. The host filters
contributions using effective grants and enabled lifecycle state.

Use `frontend: {"entry": "frontend/index.html"}` for a static sandboxed iframe
bundle. Bundle dependencies and use the host's approved `postMessage` bridge
(`plugin.run-action`, `plugin.save-settings`, `plugin.store-secret` as demonstrated
by the current frontends); the iframe does not get arbitrary access to the host
DOM, cookies or database. `native_frontend` instead declares an entry under
`native/` and optional styles, requires `frontend.native`, and exports
`activate(context)` with the supplied Vue/host APIs. It runs in the privileged
host context and requires the host's appropriate administrator approval.

The current document example declares `document_readers` in `ui.json` with a
page ID and supported extensions and requests `frontend.context.documents`.
That lets the host attach its reader to game-document actions without forcing a
sidebar page. Its `frontend.inline_assets: true` is a boolean declaring the host's
supported asset-inlining path for a sandboxed reader; it does not grant host DOM
access or bypass the iframe bridge.

Optional `backend_routes` declare an ID, relative path, methods, handler,
`scope: "plugin"` and `authorization: "authenticated"` or `"admin"`. A route such
as `documents/{document_id}` is mounted at `/api/plugins/<plugin-id>/...`.
Handlers receive normalized path/query/context dictionaries and return
`{status_code, body}`; SDK `route_response` and `route_query_value` helpers are
available. Namespaced routes require `backend.routes.plugin`. Reserved management
paths cannot be claimed. Exceptional host-level `/api/...` routes require
`backend.routes.host`; the plugin cannot supply its own authentication middleware
or replace the management namespace. See the document/session plugins for complete
working declarations and bounded error handling.

## Release metadata, tags, README and icon

The host manifest forbids unknown distribution-only fields. Author them in
`release.json`; the builder places a generated snapshot in the existing package
payload as `distribution.json`, covered by the payload digest/signature:

```json
{
  "schema_version": 1,
  "publisher": "Example Publisher",
  "tags": ["games", "statistics"],
  "icon": "icon.svg",
  "automatic_update": null,
  "release_notes": "Adds the library summary action."
}
```

All keys shown except `icon`'s non-null value are expected by the validator when
the file is supplied. With no `release.json`, the builder uses an independent
developer label, empty tags/notes, no icon and the default policy. Tags are supplied
by the plugin author: unique lowercase slugs matching `[a-z0-9][a-z0-9-]{0,47}`,
at most 32. There is no fixed official category list. Icons are optional safe
package-relative paths and are bundled with a recorded digest. Catalogue clients
must sanitize/render documentation and icons safely.

Every new package needs a non-empty UTF-8 `README.md`. Explain purpose,
configuration, requested permissions, ownership of stored data, runtime needs,
limitations and release changes. The exact packaged README is embedded as
`readme` text in each generated release and current catalogue entry, so a capable
Plugin Manager does not need to fetch GitHub HTML. Documentation stays attached
to its release even when a later README changes. Legacy packages that never
contained README/icon/tags retain `null`/empty metadata and are marked legacy;
the migration does not attach today's documentation to old code as if it were
originally packaged.

## Building, validation and signing

Use Python 3.11+ with `pytest`, `cryptography` and `jsonschema`; host conformance
checks additionally use `pydantic`. Install the pinned frontend test dependencies
with `npm ci` when working on browser bundles. A normal build is isolated:

```bash
python tools/build_packages.py
python tools/distribution.py --root .validation --check-source --include-unreleased
python tools/verify_packages.py .validation/dist/*.utp
python tools/validate_packages.py .validation/dist/*.utp
pytest
```

The preview is under `.validation/dist`, `.validation/releases` and
`.validation/list.json`; it includes unchanged historical packages. New preview
packages are deliberately unsigned unless signing environment variables are
provided. A preview never rewrites the published distribution or source versions.
An unchanged already-published signed package is reused with its original signature.
Use `--output-root /path/to/preview` for another isolated output location.

`.utp` is ZIP with `manifest.json` and `payload/<relative files>`. The builder
includes plugin Python modules, SDK helper, UI, README, release metadata, declared
icon and frontend/native assets. It excludes caches/hidden directories and uses
LF for text, sorted members, fixed timestamps/modes and deterministic JSON. There
is no compilation of Python to a platform-specific executable; the built plugin
is a validated, packaged Python/static-asset distribution.

`integrity.sha256` is SHA-256 over sorted payload paths and bytes, with a NUL after
each path and file. The manifest is excluded by the unchanged v1 contract.
`package_sha256` separately hashes the entire final ZIP, including the manifest.
New signatures are Ed25519 over ASCII `plugin-package-v2:<payload-sha256>`.
The payload includes `package-signature-v2.json`, binding the complete manifest
without integrity and the signer key ID. The signature string is prefixed `v2:`.
Verifiers compare signed and outer manifests. Catalogue fields remain separate;
the final archive hash verifies download correspondence. Historical v1 manifests
require reviewed pins. Never mutate a signed package.

Register your publisher's public Ed25519 key in your repository's `publishers/`
registry with its reviewed identity, key ID, base64 public bytes, SHA-256 of the
public bytes, status and allowed plugin-ID prefixes. The builder requires the
private key to match an **active** registered public key covering every built
plugin, and the packaged publisher label must match the registered identity.
Generic keys use `PLUGIN_SIGNING_KEY_B64` (base64 raw 32-byte private seed) and
`PLUGIN_SIGNING_KEY_ID` in protected CI secrets. Official and example folders use
the `PLUGIN_OFFICIAL_SIGNING_*` and `PLUGIN_EXAMPLES_SIGNING_*` pairs respectively.
See [signing](security/signing.md) for fallback and channel rules:

```bash
python tools/build_packages.py --require-signing
python tools/distribution.py --check-source
```

`--require-signing` retains the existing release CLI and aliases `--publish`.
Commit source/tooling/publisher changes before using it; signed publication
rejects a dirty authoring tree so recorded source provenance is meaningful.
The host has its own trust registry: publishing a catalogue/public key does not
grant trust or permissions. Administrators must review/register the key in their
deployment. Unsigned packages require the host's explicit untrusted-install flow;
they are never presented as publisher-verified. Key rotation requires reviewed
host trust updates; it does not authorize rewriting old ZIPs. Publish a new
version to use a successor signer. Retain historical key information and let host
trust policy decide which packages may execute.

## Versions, release history and automatic updates

The source manifest's version seeds a new plugin. For changes to an existing
published plugin the builder calculates a fingerprint of the authoring manifest
(excluding generated integrity/version), plugin payload, README, release metadata
and SDK. If the fingerprint is unchanged it reuses the immutable release. Otherwise
it examines Conventional Commits affecting that source directory or SDK since the
previous release's source commit:

| Change | Next version |
| --- | --- |
| `fix:`, other changes, or no available Git history | Patch |
| `feat:` / `feat(scope):` | Minor |
| `type!:` or `BREAKING CHANGE:` / `BREAKING-CHANGE:` footer | Major |

Use full Git history in publication CI. Shared SDK changes can release every
plugin that bundles it. An explicitly higher source-manifest version remains
supported for existing author workflows; edit only that version, not generated
outputs. Signed publication writes the resolved source version back along with
the package/list/history. No-change or distribution-only commits do not create
new releases. Keep meaningful Conventional Commit messages when squashing PRs.

Each `releases/<plugin-id>.json` retains complete versioned records; `list.json`
contains the same history for each currently maintained plugin. Old packages are
never deleted or overwritten. Histories also retain packages for retired plugins
that no longer have source manifests, without advertising them as current plugins.
Each new release records source digest/commit/path/time, version-bump reason,
package format/size, manifest, hashes, signing, README, tags, policy and release
notes. `source_committed_at` is the source commit time, **not** an invented
publication timestamp. New preview records are `built`; signed publication
snapshots are `published`. Recorded stages describe source → validated → built →
catalogued → published → downloadable; actual remote publication occurs when CI
commits/pushes that complete snapshot or uploads its release assets.

Automatic-update permission belongs to one release. `automatic_update: null`
uses this builder's default: major bumps are false; other releases are true.
Set `false` to opt the next generated release out, or `true` to explicitly permit
it. The resolved boolean is packaged and saved permanently for that version.
For example, publish `2.0.0` with false, then change the source `release.json` to
true (or restore null for a patch) and publish `2.0.1`. The history retains false
for `2.0.0` and true for `2.0.1`; the plugin has no permanent opt-out flag.
Do not edit a historical policy in place: policy changes are package changes and
receive a new version. Automatic permission is eligibility data, never a grant to
bypass host compatibility, trust, consent, dependency or health checks.

## Publishing and rollback

The official `main` workflow tests all plugins and browser bundles, builds signed
packages in `/dist`, verifies packages and generated metadata, and commits the
packages, history, list and source version updates together. It serializes jobs
and handles no-change builds. The existing GitHub release event uploads packages,
`list.json` and release records as release assets. Tag a source snapshot **after**
main publication has completed; release events require already-published matching
sources and valid signatures. An early/unpublished tag fails rather than uploading
a catalogue pointing to absent main-branch packages. No signing secret means no
release, never a fallback unsigned official publication.

For your own catalogue, configure `catalogue.json` and publish the same generated
files to stable HTTPS paths; see the catalogue guide for GitHub/static hosting.
Keep old package URLs downloadable and verify uploads before exposing the new
list. The Plugin Manager can install from configured catalogue URLs or `.utp`
uploads through its existing preview/consent/verification flow.

Catalogue release history describes available distributions. Host rollback
describes locally retained known-good installations. One does not substitute for
the other: publishing history does not install old versions or restore plugin
data. The host's update manager stages verified versions, checks dependencies,
switches an active pointer, health-checks activation and can restore the prior
known-good version. Data/schema migrations must remain compatible with your
rollback plan; never promise that changing executable versions undoes all stored
data changes. The host stages new scopes for explicit approval while the old
release remains active, applies release-specific automatic-update policy and
restores the previous package after failed startup. Catalogue history does not
replace locally retained rollback packages. See the compatibility note above.

## Registered notification sources (1.1.2)

The SDK's `sdk.notifications.register_type`, `unregister_type` and `emit` wrap public methods `notification_sources.register`, `notification_sources.unregister` and `notifications.emit`. Registration/unregistration require notification_sources.register; event emission requires notifications.emit. The host binds recipients to the authenticated action or subscribed background user. A source declares its own namespaced event type, PRIVATE/SECURE policy, purpose, severity and bounded plain-text templates with scalar parameters. Events contain only type, dedupe identity, occurrence, facts and optional group. Neither operation selects an arbitrary user, address, provider or delivery state.

SECURE types additionally need the explicit critical notifications.sensitive grant, which broad notifications/api.full grants do not imply. Security/recovery require SECURE; recovery also requires external context, current possession proof, recovery opt-in and suitable transport. Generic plugin facts cannot self-label PUBLIC. Host-reviewed public media projections stay separate. Real auth namespaces remain reserved to the host.

The host persists source interpretation and installation identity, creates deliveries, applies preferences/trust, isolates transport failures and rechecks source grants before I/O. It retains types, history and inactive preferences after uninstall. Reinstall requires fresh activation/grants and cannot reclaim destinations or replay old deliveries. Source registration is bounded to 32 retained types; acceptance to 100 new events per plugin/user/hour using server time. Replay with conflicting facts fails. The demo sources do not import host code or handle SMTP credentials.

See the reset and invite demonstrations in the [example map](examples/index.md). They use synthetic owner-scoped tokens and never mutate real authentication. The existing storage get/put demonstration is not an atomic production token-consumption service.


## Generic notification providers (1.1.5)

`sdk.notifications.register_provider(..., transport="plugin", definition=...)`
declares destination kinds, PUBLIC/PRIVATE privacy, bounded existing `UiField`
configuration fields, server fields, configure/retire/test action IDs and features
such as multiple destinations and critical urgency. The host uses these declarations
to render configuration; adding a provider using the existing storage/network API
does not require host UI or transport changes. Legacy and protected registrations
retain their existing SDK signature and behavior.

Configuration values are transient and write-only at the host boundary. Plugins
own validation, secret storage and transport. Use `provider_context(values,
operation="configure"|"retire"|"deliver")` inside declared actions to validate the
private runtime context. Store installation/destination revision beside credentials,
reject stale configuration callbacks, retain retirement tombstones and require
matching revisions during delivery. Configure returns `configured: true`, retire
returns `retired: true`; delivery returns the existing success/retryable/error result.
Ordinary frontend action values cannot forge the private context.

Existing fieldless linked-account integrations keep authenticated configure actions
and their `ok: true` result. This compatibility path remains PRIVATE/PUBLIC; a
provider declaration or plugin verification flag cannot assert SECURE ownership.
The maintained Discord bot continues to use this path. Per-account core verification
is separate work and is not implemented by this release.

Delivery receives approved title, body, event type/time, urgency and resolved link,
plus opaque notification/destination handles. Host routing rechecks user policy,
trust, installation and grants before handoff. Plugin transport determines its final
bytes, so permission review must explain that it receives approved content and its
own configured secrets. The host never shares SMTP credentials. Failures are safely
normalized and isolated; core retains global attempt/history/retry state.

The maintained [Discord webhook](https://github.com/Unbound-Timeline-Shelf/Plugins/blob/main/official/discord-notifications/README.md)
exercises declared-field configuration; the separately maintained Discord bot
exercises linked-account enrollment. Historical protected demo renderers still work.


API1.1.10 adds `administration.users.actions`: a page title becomes an Admin/Users
button opening a host dialog, guarded by `frontend.navigation.admin`. Dedicated
plugin Settings/dialogs can use the existing sandboxed frontend; its `page` query
parameter selects presentation only. Account security settings use the existing
`frontend.settings` and `frontend.placement.settings.admin` grants. The recovery
contribution reads live `auth_flows.password_reset.status` rather than trusting
saved activation. Host PR85 supplies this additive contract.

API 1.1.11 adds `administration.users.settings` and
`administration.password-policy.after`, guarded by `frontend.settings` and an
administrator. These render inline with host appearance and no extra plugin title,
using the same opaque sandbox and action bridge. The maintained invite and recovery
plugins use these locations and separate saving settings from enabling/disabling.
Invitation registration also supports escaped plain-text email presentation and an
optional recipient name on issuance. SMTP sender addresses and acceptance links
remain host owned; wording-only edits preserve outstanding links.


### Page activation (Plugin API v1.1.17)

For bundles that only register components for declared contributions, set
`native_frontend.activation` to `page` and declare `api_contract_version: "1.1.17"`
in both the manifest and UI document. The host imports that bundle when a
contribution mounts. Omitted activation retains `startup`, which is required for
bundles registering global search, notification providers or startup hooks.
Concurrent contribution mounts share one activation. Existing grant and package
validation requirements apply to both modes.
