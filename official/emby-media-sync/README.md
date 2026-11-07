# Emby Media Sync — official preview

Connect your own Emby account and sync what you have watched into Movies, TV and Anime,
with a **Watch in Emby** link on each synced media page.

## Connect

Install the package, approve its permissions and enable it. Open **Settings → Account →
Connections → Emby** and enter the **server URL** your host can reach (a reverse-proxy
path is allowed), your Emby **username** and **password**.

The password is sent once to your server's sign-in endpoint and never saved. The plugin
keeps only the resulting **user session token** (not an administrator API key), so it sees
exactly the libraries your Emby user can see. It lists your movie and TV libraries; music,
books, Live TV and collections are never read. Connecting a different account or server is
refused until you disconnect.

## Sync

Sync reads each chosen library in bounded pages of 50 items (100 episodes), writing
through the public `media.sync` enrich contract after each page and saving a checkpoint:

* **Movies and shows** become your own Movies, TV or Anime records. Provider IDs
  (IMDb, TMDB, TVDB) and unique exact title/year matches enrich a record you already have
  instead of creating a duplicate. Library categories can be **Automatic** (anime is
  detected from genres and tags), fixed, or **Do not sync**.
* **Watch state**: watched, in progress, playback position, runtime, percentage, play count
  and last-played time. Counts are never turned into invented viewing sessions.
* **Episodes** carry their real season and episode numbers. An episode without numbers
  keeps its progress but is never given invented numbers, and its series is not marked
  complete in that census. Anime films become a one-episode anime entry.
* **Watch in Emby**: every synced item carries `watch_url` (the item's page in your
  server's web app, without any credential) and `watch_label` (`Emby · <server name>`,
  at most 80 characters). The host stores them and shows **Watch in Emby** on the media
  page with no live lookup (Plugin API 1.1.18+). An item missing from two complete
  censuses is re-sent with `available: false`, so the host stops offering the link; your
  record, notes and history are kept.

Your notes, ratings, locked metadata and local watch edits are protected by the host.
When the host reports a conflict (several possible matches, a local watch change since
the last sync, a changed category, or a locally deleted item) nothing is changed: the
item appears under **Needs review**, where you choose to keep it separate, merge it into
one of the listed items, use the Emby watch state, or keep your category. The decision
applies on the next sync of that item. Deleted items stay deleted.

## Where sync runs

* **Settings → Account → Connections → Sync now** runs on the server through your personal
  sync task and does not need this page open.
* **Account → Background tasks → Emby autosync** is off until you enable it (default
  every six hours, 15 minutes to one week). Each run advances one checkpoint and asks the
  host to continue after 60 seconds until the census is complete.
* **Sync now** on this page runs the same step while the page is open. Closing the page
  pauses a sync started here; the checkpoint is kept and any of the three resumes it.

All three share one per-account lease and checkpoint, so they never run two steps at once.
A checkpoint older than six hours starts a fresh census. If the library changes during a
scan, the scan restarts (at most five times in a row). A rate limit asks the host to wait
at least five minutes; a rejected sign-in turns the personal schedule off until you
reconnect. Disconnecting keeps every synced record.

## Security and privacy

The session token is sent in the `X-Emby-Token` header, which the host's outbound allowlist
permits; it never appears in a URL. Poster and backdrop URLs are token-free item image
addresses on your server, which Emby serves without authentication by default; if your
server requires authentication for images they may not display. Disconnecting signs the
session out on the server (best effort) and removes the saved token.

The credential is kept in this plugin's private `plugin.storage` record, bound to the
server URL and account it was issued for, and is never returned by any action, status,
summary or error. Every remote failure is reported with a fixed message that contains no
URL, header or server reply. Requests go through the host's bounded `network.request`
transport: verified TLS (an untrusted certificate is reported, never bypassed), no
redirects, an 8-second timeout and a 4 MiB limit. HTTP server URLs work but send the
credential unencrypted; prefer HTTPS. The plugin never changes anything on the server.
Plugin storage is access-controlled by the runtime, not an encrypted vault.

## Permissions

| Capability | Why |
| --- | --- |
| `media.write` | Create or enrich your own Movies, TV and Anime records. |
| `network.outbound` | Read your server with your own user session, and sign out on disconnect. |
| `plugin.storage` | Credential, connection, library choices, checkpoint and review queue. |
| `tasks.background` | Server-run Connections sync and the opt-in personal autosync. |
| `frontend.connections` | The row on Settings → Account → Connections. |

## Status and testing

Official **preview** (0.1.0, Plugin API 1.1.20), not yet signed or listed in the catalogue:
`catalogue.json` keeps it in `unreleased_plugins` until an owner validates it against a
real server and approves signed publication. Branch CI's `unsigned-dist` artifact carries
an installable unsigned preview for the host's untrusted-package flow.

Behavior is covered by fixture-based tests that replay Emby-shaped JSON through a fake
host gateway (`tests/test_media_server_sync.py`): connection, pagination, episodes, conflict
review, availability, scheduling hints and the absence of credentials from every output.
It has **not** yet been exercised against a live Emby server.

```sh
python -m pytest tests/test_media_server_sync.py
python tools/check_source_layout.py
python tools/build_packages.py
```
