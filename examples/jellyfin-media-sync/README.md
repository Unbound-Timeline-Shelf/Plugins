# Jellyfin Media Sync (Demo)

This is a working example of Plugin API capabilities, retained as a demonstration
under `example.jellyfin-media-sync`. It is not the supported official feature.
The separate official preview uses `official.jellyfin-media-sync` and begins at
0.0.1; it does not inherit this demo's configuration, credentials or grants.

An installation-wide Jellyfin integration for Movies, TV and Anime, using the
existing Plugin API v1 gateway, secure plugin storage and supervised worker.
The native plugin page handles setup and sync status; its media-page contribution
opens the exact Jellyfin item with **Watch Now**.

## Administrator setup

1. Install the built `.utp` on the host branch containing the generic `media.sync`,
   background subscription and `network.request` additions. Review permissions
   before enabling. Version 3 requires those additions; older hosts are unsupported.
2. Open **Jellyfin Sync** in Settings or the sidebar. Enter the server URL, including
   any reverse-proxy base path, and a **server API key** created in Jellyfin's
   administration dashboard. Use HTTPS outside a trusted local network.
3. Save the server, then **Test connection & discover**. The plugin discovers
   Jellyfin users and virtual libraries, and persists the connection result.
4. Map each included library. For example, Movies → Movies, TV Shows → TV,
   Anime → Anime. Choose Ignore to exclude a library. Save the mappings.
5. Approve each host user's corresponding Jellyfin identity. Users provide the host
   user ID shown in their account panel; select their discovered Jellyfin identity
   and press **Approve identity**. Approval prevents another user selecting an
   account they do not own. Users never need the server URL or credential.

![Administrator server settings](https://raw.githubusercontent.com/Unbound-Timeline-Shelf/Plugins/main/wiki/docs/assets/screenshots/jellyfin-admin-settings.png)
![Explicit library mapping](https://raw.githubusercontent.com/Unbound-Timeline-Shelf/Plugins/main/wiki/docs/assets/screenshots/jellyfin-library-mapping.png)

## User setup

Open Jellyfin Sync, choose your approved Jellyfin identity, optionally enable
periodic synchronization, and press **Link my account**. Press **Sync now** to
queue a sync for your account. Without administrator approval the panel shows
instructions and your host user ID, rather than exposing other users' accounts.
Unlinking stops your subscription and retains imported media. Disabling the plugin
stops all workers; enabling it resumes durable work and subscribed periodic syncs.

![User account mapping](https://raw.githubusercontent.com/Unbound-Timeline-Shelf/Plugins/main/wiki/docs/assets/screenshots/jellyfin-user-mapping.png)

## Library mapping and supported media

Explicit mapping always wins over genre/tag detection. Automatic mode retains
metadata-based anime detection as a fallback. Movies and Series roots are imported;
TV and anime episodes retain season/episode numbers and watched flags. Anime films
use a single native episode so their completion has the same model semantics.
Unsupported/malformed items, including episodes without usable numbering, are
counted as skipped. Specials with season number zero are supported.

An existing item changing category is flagged for manual review instead of
creating a duplicate or discarding notes/list references. Changing mappings
restarts the bounded census. A server or approved identity change requires
relinking; a server change also invalidates the destination-bound credential and
requires discovery and mapping again.

## Identity and completion

Identity is scoped by plugin ID, host user, server, Jellyfin user and Jellyfin item
ID. The host creates a deterministic existing-media primary key; the plugin stores
that host ID, remote ID and last watch-state revision. Renames update unlocked
metadata without creating another row. Equal titles with different IDs remain
separate. Plugin code never imports host modules or accesses the host database.

| Field | Authority and behavior |
| --- | --- |
| Film completion | Jellyfin `Played=true` → WATCHED; false → WATCHLIST, or IN_PROGRESS when a playback position exists. A partial position never means completed. |
| TV/anime episodes | Jellyfin supplies each episode's watched boolean, including watched reversals. Native episode flags and season counters update together. |
| Season/show completion | WATCHED only after a successful complete episode inventory with a nonempty episode set and every episode watched. Partial sets stay IN_PROGRESS or WATCHLIST. A Series object's existence/Played flag never completes the show. |
| Titles, genres, artwork | Jellyfin supplies unlocked metadata. Host `locked_fields` are respected. Artwork URLs contain no credential. |
| Ratings, notes, favorites, rewatches | Host-owned; synchronization does not replace them. |
| Local watch edits | Optimistic revision comparison detects changes since the previous import and reports a conflict. It does not silently replace them. |

Use **Use Jellyfin watched state** on a reported watch-state conflict to explicitly
accept the remote state. The host checks the revision again, so a newer edit still
produces a conflict. Category changes and local deletions require manual review.
Two-way playback synchronization is **not enabled**: the public host API does not
provide a complete provider-neutral local playback change stream. This integration
writes no watched/progress changes back to Jellyfin.

## Watch Now

On an imported film, TV or anime detail page, the plugin contributes Watch Now
through `media.detail.after-header` and the existing contextual action mechanism.
The destination is `<server>/web/index.html#!/details?id=<Jellyfin item ID>`.
Series pages open the series; anime films open the film. No token is included,
playback is not proxied, and Jellyfin may ask you to sign in. Missing, removed or
other-user mappings show an unavailable message. The host button uses declared
external-navigation behavior; the native panel also offers a normal safe link.

![Watch Now on the real media page](https://raw.githubusercontent.com/Unbound-Timeline-Shelf/Plugins/main/wiki/docs/assets/screenshots/jellyfin-watch-now.png)

## Sync behavior

A worker handles users in round-robin order. Each tick processes at most four
100-record remote pages, with persisted library/phase/offset checkpoints. Root
metadata is normalized and compared before sending host writes; unchanged items
are not reimported. Episodes are checked separately so watched changes and
unwatched reversals are detected even when show metadata has not changed.
Finalization processes at most 25 mapped roots per tick. A completed census marks
removed roots unavailable for Watch Now while retaining host media and local data;
missing remote episodes are removed through the public API after inventory checks.

Jellyfin does not expose a reliable universal timestamp filter for watched
reversals. The plugin therefore uses a bounded rolling census with incremental
host writes, rather than claiming an unreliable timestamp-only sync. Large
libraries take multiple ticks. No unbounded remote full-library request is made.
Manual requests arriving during work survive for a later tick. Retry checkpoints
survive runtime restart and errors use exponential delay up to one hour. Manual
Sync now permits an earlier retry. Default periodic interval is 15 minutes
(minimum 5, maximum 1440); periodic sync is opt-in per user.

![Synchronization status](https://raw.githubusercontent.com/Unbound-Timeline-Shelf/Plugins/main/wiki/docs/assets/screenshots/jellyfin-sync-status.png)

## Credentials and security

One server credential is stored in the existing reserved `secrets/master_token`
namespace and bound to the exact normalized server URL. It is never returned by
configuration/status/actions, placed in URLs, or stored per user. The administrator
alone can change the server, token, library mapping and account approval. User
identity comes from the host's authenticated action context, never a caller's
claimed host user ID. Background subscriptions are host-owned and each delegated
write rechecks both background and media grants for the target user.

The host's generic outbound JSON operation runs outside the isolated worker and
checks the live `network.outbound` grant before HTTP. It refuses redirects, checks
TLS normally, caps responses at 4 MiB and uses an 8-second timeout. The server
credential travels only in an Authorization header. Error/status messages omit
remote response bodies and arbitrary gateway exception details.

Permissions: `media.write`, `plugin.storage`, `tasks.background`,
`network.outbound`, native frontend, navigation, settings/routes, media contexts
and page extension. No database, full API, games, documents or session access is
requested. Native frontend remains a privileged permission under existing review.

## Troubleshooting and upgrade

* **No approved identities:** copy your host user ID to the administrator and ask
  them to approve your own discovered Jellyfin identity.
* **Connection/credential error:** verify the final server URL, base path, TLS,
  API key access and host egress. A redirect requires configuring its final URL.
* **Permission error:** review both installation and target-user grants. Revoked
  grants stop imports; the plugin never substitutes the enabling user's scope.
* **Partial completion:** inspect skipped items and episode numbering. Completion
  waits for a complete inventory; ongoing shows may become incomplete as new
  episodes arrive.
* **Watch-state conflict:** review your host edit and explicitly accept Jellyfin
  state only if desired. Ratings/notes remain local.
* **Watch Now unavailable:** relink the account, check its approved identity and
  library mappings, and complete a sync. Deleted remote roots retain host history.
* **Updating from 2.x:** configure a master server credential and approve/link users
  explicitly. Old user-bound credentials are never promoted to installation-wide
  authority and are removed when a replacement master credential is saved.
  Legacy title-matched imports lack durable remote identity; review/archive those
  legacy records before initial version-3 import. Automatic title matching would
  risk merging unrelated films, so this upgrade does not guess their identity.

## Testing, build and release

```sh
pytest
python tools/build_packages.py
python tools/verify_packages.py .validation/dist/*.utp
python tools/validate_packages.py .validation/dist/*.utp
python -m mkdocs build --strict
```

Version 3.0.0 is a major configuration migration. Release artifacts and metadata
are generated together by the existing publisher tooling; historical `dist/`
packages are immutable. Development previews are unsigned in `.validation/dist`.
Production signing uses the existing reviewed publisher workflow. Acceptance uses
a disposable signing key and never commits private signing material.

Cross-repository verification runs the actual built, signed `.utp` against the
host/runtime, PostgreSQL and a Jellyfin HTTP fixture: master setup, identity
approval/link, Movies/TV/Anime import, remote watched changes, native completion,
repeat sync, exact Watch Now, restart, disable/enable, update, rollback and
preserving reinstall. See host `tools/check_plugin_repository_lifecycle.py`.
Screenshots are captured from that real installation using disposable fixture data.
