# Unnamed Tracking plugins

Official reference plugins, useful demos and developer tooling for **Plugin API v1**.
Build and publish independently using the same SDK, `.utp` format, signing model
and catalogue specification as the official repository.

**The host owns runtime, lifecycle, gateway and permissions; plugins provide
application behavior.** Plugin code uses the public gateway, never application
database models or private host modules.

## Install a plugin

Download the versioned `.utp` linked by [the generated catalogue](list.json) or
[GitHub Releases](https://github.com/Unbound-Timeline-Shelf/Plugins/releases).
A `.utp` is a validated ZIP containing a manifest and payload, not a renamed Python file.
In Unnamed Tracking open **Settings → Plugins → Install plugin**, select the
package/source, review identity, publisher/signature, compatibility and permissions,
then complete approval/configuration and enable it as required by the host flow.

Maintained user-facing functionality lives in [official/](official/README.md).
The [Epic Games Library](official/epic-games/README.md) imports a personal game
library in resumable steps and requires host Plugin API 1.1.19. It depends on
Epic's unofficial launcher services and is experimental.
The [Extended Session Manager](official/extended-session-manager/README.md) is
now official functionality and preserves its existing plugin ID for updates.
The [PWA](official/pwa/README.md) is published through the registered official
signing identity; the [catalogue](list.json) records its current signed version.
The [Discord Bot Notifications](official/discord-bot-notifications/README.md) provider
is also published under **Unnamed Tracking Official**, retaining manual updates.
Ordinary PRIVATE DMs work without verification; SECURE recovery requires independent
host destination proof and explicit consent. Allowed server channels stay PUBLIC.
Examples remain
demonstrations, even when their historical publisher text contains Official.
See [folder-specific signing and environment keys](docs/official-signing.md).

Catalogue membership does not establish trust. Publisher signing and host
permission approval are separate. Unsigned preview packages remain untrusted.
Full API/native frontend authority needs particular review; request narrow scopes.

To test a branch or pull request, open its [Plugin checks workflow run](https://github.com/Unbound-Timeline-Shelf/Plugins/actions/workflows/ci.yml)
and download **unsigned-dist**. This job runs for every non-draft PR and for pushes to branches without an open PR
(a branch with a PR is covered once by the PR run), independently of the full test job. Extract the artifact and upload the chosen
`.utp` through the install screen. Review permissions and explicitly consent to
the unsigned preview. No build tools or signing key are needed on your machine.
The artifact includes source commits and package digests; it never updates
published packages or release history. Previews disable automatic updates.

[Collector's Archive](official/collectors-archive/README.md) preserves Cards, Sets and Bounties and is prepared for signed official catalogue
publication under **Unnamed Tracking Official** with manual updates. Its personal, retryable import reads
the host's retained legacy records through a separate permission. Its compiled
native pages share the host's Vue runtime and themed components. Run `npm ci`
and `npm run build:native` after editing its UI; CI checks the committed bundle.

## Create your first plugin

The [Game Night setup guide](wiki/docs/examples/discord-game-night.md) walks
operators and players through the Discord bot, Activity URL mappings, scoped or
legacy library connections, personal rules and troubleshooting. The separate
[Game Night plugin](official/discord-social-activity/README.md) is an API 1.1.12
Discord Activity published under **Unnamed Tracking Official**, with manual
updates and its identity adapter in Discord Bot Notifications. See the
[catalogue](list.json) for the signed package.

Start with the executable [first-plugin tutorial](wiki/docs/getting-started/first-plugin.md),
then use the [developer manual](wiki/docs/index.md) and [complete API reference](wiki/docs/plugin-author-guide.md).
The tutorial creates a minimal manifest, Python entrypoint/action and page,
builds a real `.utp`, validates it and explains install/consent.

```sh
python -m venv .venv
# Activate .venv for your shell, then:
python -m pip install -r requirements-dev.txt
python tools/check_source_layout.py
python tools/check_docs.py
python -m pytest
python tools/build_packages.py
python tools/distribution.py --root .validation --check-source --include-unreleased
python -m mkdocs build --strict
python -m mkdocs serve
```

The Material/MkDocs wiki uses the same light/dark organization as the main app's
wiki. Its sources live under `wiki/docs/`; `mkdocs serve` opens the local developer wiki
at `http://127.0.0.1:8000`. [Testing](wiki/docs/testing/index.md) includes package,
browser and actual host conformance/lifecycle commands and PowerShell instructions.

Use the [tutorial map](wiki/docs/development/index.md) for one-feature exercises,
[architecture](wiki/docs/architecture/index.md) for the public boundary,
[lifecycle matrix](wiki/docs/testing/lifecycle.md) for updates/recovery, and
[release audit](wiki/docs/publishing/release-history.md) before publication.

## Find a working example

| Source | Purpose |
| --- | --- |
| [UI/API](examples/ui-api/README.md) | Small reference: declarative page, setting and library action |
| [Home Widgets](examples/home-widgets/README.md) | v1.1 personal widget options, separate phone layout and embedded media demo |
| [Blue Hour and Purple Blocks](examples/theme-palettes/README.md) | Personal light/dark palettes and optional square-control CSS with a separate native permission |
| [Shortcut Playground](examples/shortcut-playground/README.md) | v1.1.x host-managed random bindings, removal and a deliberate Search conflict |
| [Playtime Report](examples/playtime-report/README.md) | Read → calculate → persist a user-scoped report |
| [Recently Played Notifier](examples/recently-played-notifier/README.md) | Library data and host notifications |
| [Metadata Curator](examples/metadata-curator/README.md) | Settings, metadata search and normalized state |
| [Discord Notifications](official/discord-notifications/README.md) | Official protected layouts; owner webhooks and routing remain in the host |
| [Notification Chaos Demo](examples/notification-chaos-provider/README.md) | Signed demo: approved fields, selectable failures and bounded simulation state |
| [UI Playground](examples/ui-playground/README.md) | Sandboxed Vue pages and bridge; CDN teaching limitation |
| [Help Button](examples/help-button/README.md) | Native contributions, dialogs, overlays, navigation and cleanup |
| [Jellyfin Media Sync](examples/jellyfin-media-sync/README.md) | Master server, approved user identities, library mapping, episode completion and Watch Now |
| [Scoped Document Viewer](examples/scoped-document-viewer/README.md) | Scoped document APIs and sandbox PDF/text/Office reader |

The [example map](wiki/docs/examples/index.md) identifies tests and relevant captures.
Small references stay small; real demos document supported behavior and host limitations.

## Understand the repository

| Path | Role |
| --- | --- |
| `examples/` | Functional reference/demo sources, including the original Jellyfin demo |
| `official/` | Independently packaged official features and clearly labelled previews |
| `sdk/` | Public v1 protocol helper bundled with packages |
| `tools/`, `tests/` | Existing build/validation tools and conformance tests |
| `wiki/docs/`, `mkdocs.yml` | Developer wiki, real assets and dated evidence |
| `publishers/` | Reviewed public keys/registry; never private signing keys |
| `dist/` | Generated immutable installable `.utp` versions |
| `releases/` | Append-only generated release metadata/history, including retired plugins |
| `retired_plugins.json` | Reviewed retirement decisions; historical archives and release records stay immutable |
| `catalogue.json` | Authored display name and HTTPS hosting base URL |
| `list.json` | Generated current catalogue with complete per-plugin histories |

Development builds write isolated `.validation/` previews. Published packages
and historical records remain unchanged. Do not manually edit generated lists,
re-sign old ZIPs, or remove historical packages to tidy the repository. GitHub
Releases distributes/presents these same outputs; repository history is retained.

### Reproduce and share validation outputs

A fresh clone does not need anyone else's `.validation` folder. The committed
`tools/` and `tests/` recreate preview packages from maintained source;
cross-repository workflows explicitly check out their host/mobile dependencies.
Run the development commands above to regenerate `.validation/dist`, `list.json`
and release metadata. Package filenames follow the version in each preview's
manifest; signed publication can advance source versions, so do not assume a
fixed filename from an earlier release.

For sharing, download **unsigned-dist** or **validated-plugin-distribution** from
the [Plugin checks run](https://github.com/Unbound-Timeline-Shelf/Plugins/actions/workflows/ci.yml).
These artifacts include the generated packages/catalogue and contain no private
signing keys. Public conformance tools and dated review evidence live in `tools/`
and `wiki/docs/`. Keep local environment files, credentials, cookies and private
deployment logs out of shared artifacts; the whole `.validation` folder is not
a distribution input.

Official features and examples use the same SDK, package validator, permission
review and sandbox. [Jellyfin's official preview](official/jellyfin-media-sync/README.md)
starts at 0.0.1 with a separate identity; the original Jellyfin package stays a demo.
`catalogue.json.unreleased_plugins` explicitly keeps previews outside signed
publication until reviewed signer scope exists. Development builds still include
and fully validate every maintained source, including unreleased previews.

## Sign and publish independently

Author `release.json` for publisher/tags/icon/notes/update policy. The existing
builder creates canonical payload and final archive hashes, signs Ed25519 over
`plugin-package-v2:<payload hash>` (with a signed manifest envelope in the payload), verifies the result, and derives all release
and catalogue metadata from the package. Conventional Commits select SemVer;
explicit higher source versions remain supported. Update policy belongs to each release.

Official main publication uses `python tools/build_packages.py --require-signing`
with separate folder-specific protected keys and the active scoped publisher registry. It preserves
all historical packages and commits packages/history/catalogue/resolved versions
together. Tag only an already-published snapshot. Never commit a private key.

Follow [package publishing](wiki/docs/publishing/packages.md),
[versioning](wiki/docs/publishing/versioning.md), and the complete
[third-party catalogue tutorial](wiki/docs/publishing/community-catalogue.md).
The [catalogue v1 specification](wiki/docs/catalogue-specification.md) is unchanged:
HTTPS immutable package URLs, exact hashes/manifests/signatures and retained
history. Register catalogue endpoints and reviewed publisher keys separately
in Plugin Manager; permissions always remain host-controlled.

### Notification compatibility: Plugin API 1.1.2

The SDK advertises contract 1.1.2. The recently played example and the official Discord Notifications provider require host SDK ^1.1.2: notification acceptance and physical delivery now pass through the host controller. Generic plugin actions cannot authorize Discord transport. The legacy Discord endpoint remains PUBLIC; only host-approved public release facts may reach it. Legacy custom plugin notifications remain PRIVATE and may be suppressed by preferences. See each example's README for the limits of this compatibility bridge.

The shared SDK is included in plugin packages, so this contract update changes the PWA package fingerprint too. Its development source advances from 0.0.5 to 0.0.6 under the existing explicit patch policy. Its UI and service worker behavior are unchanged. Published packages and release history remain immutable; development previews use the existing validation output directories.

The [Password Reset Routing Demo](examples/password-reset-notification-demo/README.md) and [User Invite Routing Demo](examples/user-invite-notification-demo/README.md) are executable Plugin API 1.1.2 event-source demonstrations. They submit caller-owned typed events, use host SMTP/inbox routing and simulate expiring token confirmation without changing authentication or creating users. Reset requires the separately reviewed sensitive-content grant and SECURE external recovery routing. They are demo source previews, not official production authentication features.

The [Story Notification Demo](examples/story-notification-demo/README.md) demonstrates the versioned notification contract of Plugin API 1.1.14: a lifecycle story, typed facts, a typed host-authorised action and a Markdown contribution through `sdk/notification_stories.py`. It needs a 1.1.14 host and stays unreleased until that host ships.
