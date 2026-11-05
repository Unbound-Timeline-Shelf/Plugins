# Jellyfin Media Sync demo

This page describes `example.jellyfin-media-sync`, which remains a demo.
The separate [official preview](https://github.com/Unbound-Timeline-Shelf/Plugins/blob/main/official/jellyfin-media-sync/README.md)
starts at 0.0.1 with multiple servers/accounts, richer enrichment and separate
admin/user panels. Installation, trust, permissions and storage remain independent.

Version 3 uses one administrator-configured Jellyfin server, approved per-user
identities, explicit Movies/TV/Anime library mapping and native episode completion.
It contributes Watch Now through the existing media-detail extension slot.

See the [complete setup, behavior, upgrade and troubleshooting guide](https://github.com/Unbound-Timeline-Shelf/Plugins/blob/main/examples/jellyfin-media-sync/README.md).
The host needs the generic Plugin API v1 `media.sync`, `network.request` and
background-subscription operations documented in its development wiki.

![Administrator settings](../assets/screenshots/jellyfin-admin-settings.png)
![Library mapping](../assets/screenshots/jellyfin-library-mapping.png)
![User mapping](../assets/screenshots/jellyfin-user-mapping.png)
![Sync status](../assets/screenshots/jellyfin-sync-status.png)
![Watch Now on the real host media page](../assets/screenshots/jellyfin-watch-now.png)

These screenshots use the actual built package installed into the real host and
runtime, with disposable Jellyfin fixture data. They are captured by
`tools/capture_jellyfin.mjs` during cross-repository acceptance. No live credential
is shown. The server is a temporary local HTTP fixture.

## Verification

Cross-repository CI tests a same-named companion branch when one exists, otherwise
the host's `plugin-manager` branch. Workflow dispatch can explicitly select a host
ref. Every package, signature, permission, lifecycle and browser check remains
enabled. The conformance artifact records both source commits.

The real installation test builds a trusted disposable signed package, creates
separate host users, configures the master server and approved identities, imports
all three categories, changes watched state, checks native completion and repeats
sync without duplicates. It verifies restart, disable/enable, update, rollback,
state-preserving reinstall and token-free Watch Now. The browser also navigates
between mapped and unmapped media in the same SPA session to verify that a previous
item's Watch Now link cannot persist. Production publisher keys are never used by
this fixture.
