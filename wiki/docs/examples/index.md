# Working examples

Demonstrations live under `examples/`; official features live under `official/`.
Jellyfin has separate demo and official preview identities. Every maintained source has a
manifest, implementation, README, tests and support in the existing builder.
The catalogue is generated from their actual packages, not this table.

| Source | Scale / useful behavior | Tests |
| --- | --- | --- |
| [Game Night and Discord bot](discord-game-night.md) | Official Activity preview: independent libraries, guest games, shared choices and scoped own-account writes | engine, identity, package and coordinated host tests |
| [Integration access client](integration-access-client.md) | Packaged non-Discord reference consumer of scoped integration access (consent, writes, rotation, revocation) | contract double and live host acceptance |
| [UI/API](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/ui-api) | Small reference: declarative page, setting, library action | examples, smoke, packaged worker, reference lifecycle |
| [Epic Games Library](epic-games.md) | Official optional account connection and bounded resumable game imports | Epic wire, paging, tokens, restart and grant regressions |
| [Playtime Report](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/playtime-report) | Small demo: calculate/store user report | real plugins, smoke, package, reference lifecycle |
| [Recently Played Notifier](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/recently-played-notifier) | Small demo: library + notification | real plugins, smoke, reference lifecycle |
| [Metadata Curator](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/metadata-curator) | Small demo: setting + search + normalized state | real plugins, smoke, reference lifecycle |
| [Discord Notifications](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/official/discord-notifications) | Official provider: approved fields and host-owned user webhooks | consumer, package, real-worker lifecycle |
| [UI Playground](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/ui-playground) | Demo: iframe Vue pages/bridge; pinned CDN teaching limitation | examples, smoke, no secret echo |
| [Help Button](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/help-button) | Showcase: contributions, dialogs, overlays and native cleanup | help, native frontend, canonical packages |
| [Jellyfin Media Sync](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/jellyfin-media-sync) | Master server, approved user mapping, native episode completion and Watch Now | Jellyfin, native frontend, full host lifecycle/browser |
| [Scoped Document Viewer](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/scoped-document-viewer) | Feature demo: scoped sandboxed content reader | domain, document package, real browser, parity |
| [Extended Session Manager](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/official/extended-session-manager) | Official extension: own/admin sessions and maps; stable installation ID | session, routes, native UI, package |
| [Home Widgets](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/home-widgets) | Account-persisted widget choices/options, responsive layouts and embedded media demo | theme/widget contracts, signed host lifecycle and account isolation |
| [Shortcut Playground](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/shortcut-playground) | v1.1.x dynamic shortcuts and intentional Ctrl/Cmd+K conflict | native lifecycle, host permission enforcement, remapping and account isolation |
| [Blue Hour Palettes](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/theme-palettes) | Optional semantic light/dark palettes with personal copies and separate permission | package/source, palette grants, signed native/iframe acceptance and withdrawal |

Use the smallest example that teaches your requirement. Every real demo's README
describes configuration, grants and current host limitations. Screenshots for
document/native components are collected in [assets](../assets/screenshots/index.md);
browser-enabled host acceptance produces authenticated Plugin Manager evidence.

Old lifecycle/events/advanced source stubs are retired. Their original `.utp`
files and generated release histories remain immutable and downloadable. See
the [audit](../history/ecosystem-audit.md), not duplicate legacy source directories.

## Typed notification source demonstrations

[Password Reset Routing Demo](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/password-reset-notification-demo) and [User Invite Routing Demo](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/user-invite-notification-demo) exercise registered namespaced events and synthetic expiring token confirmation. Both use the included public SDK and existing host capability review, routing, persistence and delivery machinery. Reset requires an explicit sensitive-content grant and SECURE external recovery destination. Invite uses ordinary PRIVATE routing. These are protocol/action demos with no new frontend page; they do not implement production authentication. See their READMEs and tests/test_notification_demos.py for issue/confirm, ownership, replay, expiry, permissions and actual package checks.

[Story Notification Demo](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/story-notification-demo) shows the Plugin API 1.1.14 versioned notification contract: one story that moves from available to installed, typed facts, a typed host-authorised action and a Markdown render contribution. See `tests/test_notification_story_contract.py` for the shared conformance cases and a real signed-package check.


## Legacy Discord replacement

The shared-secret Discord Delivery Provider source is retired. Its immutable
packages and release history remain downloadable, but it is removed from the
current catalogue. Install the new Discord Notifications identity and explicitly
enroll each webhook in Account Notifications. Uninstall the legacy plugin after
reviewing retained notification history; credentials and disclosure consent are
never copied to the replacement. The host retains compatibility with already
installed legacy packages during migration.

## Notification Chaos Demo

The signed [Notification Chaos Demo](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/notification-chaos-provider) uses protected Discord transport with reversed approved fields, persistent first-render failure, repeated failure and invalid-layout modes. It is deliberately unreliable, requests no credential/network access and is independent of the official provider. Unit/package tests and the real reference-worker lifecycle harness cover it. Core owns delivery history, retries and routing; no production feature depends on the demo.

## Maintained user invitations (API 1.1.8)

The working `official.user-invites` plugin enables administrator email invitations through host-owned single-use credentials and core SMTP deliveries. Accounts are created only on acceptance. This is separate from the synthetic routing demo. See [setup and public contract](../development/user-invites.md).
