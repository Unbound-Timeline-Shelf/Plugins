# Plex Media Sync — official preview

Connect your own Plex account on a Plex Media Server and sync what you have watched into
Movies, TV and Anime, with a **Watch in Plex** link on each synced media page.

## Connect

Install the package, approve its permissions and enable it. Open **Settings → Account →
Connections → Plex** and enter:

* the **server URL** your host can reach (for example `https://plex.example.net:32400`;
  a reverse-proxy path is allowed), and
* your **Plex token**.

The plugin checks the server's identity, confirms the token on the server and asks
plex.tv once which Plex account the token belongs to, so two people (or a Plex Home user)
never share sync state. It then lists your movie and TV libraries. Connecting a token for a
different account or server is refused until you disconnect.

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
* **Watch in Plex**: every synced item carries `watch_url` (the item's page in your
  server's web app, without any credential) and `watch_label` (`Plex · <server name>`,
  at most 80 characters). The host stores them and shows **Watch in Plex** on the media
  page with no live lookup (Plugin API 1.1.18+). An item missing from two complete
  censuses is re-sent with `available: false`, so the host stops offering the link; your
  record, notes and history are kept.

Your notes, ratings, locked metadata and local watch edits are protected by the host.
When the host reports a conflict (several possible matches, a local watch change since
the last sync, a changed category, or a locally deleted item) nothing is changed: the
item appears under **Needs review**, where you choose to keep it separate, merge it into
one of the listed items, use the Plex watch state, or keep your category. The decision
applies on the next sync of that item. Deleted items stay deleted.

## Where sync runs

* **Settings → Account → Connections → Sync now** runs on the server through your personal
  sync task and does not need this page open.
* **Account → Background tasks → Plex autosync** is off until you enable it (default
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

Plex tokens are not scoped: a token can do whatever its Plex account can. This plugin only
ever sends read requests to the server and plex.tv. The host's outbound header allowlist
does not include `X-Plex-Token`, so the token is sent as Plex's documented `X-Plex-Token`
query parameter on requests to your server and plex.tv. Those URLs are built inside the
plugin and are never stored, shown or logged by it. Plex artwork needs a token, so no
poster or backdrop URL is sent to the host (a token must never appear in a stored image
URL). Disconnecting removes the saved token; revoke it from your Plex account's
authorized devices if it may have been exposed.

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
| `network.outbound` | Read your server and, once at sign-in, plex.tv. |
| `plugin.storage` | Credential, connection, library choices, checkpoint and review queue. |
| `tasks.background` | Server-run Connections sync and the opt-in personal autosync. |
| `frontend.connections` | The row on Settings → Account → Connections. |

## Status and testing

Official **preview** (0.1.0, Plugin API 1.1.20), not yet signed or listed in the catalogue:
`catalogue.json` keeps it in `unreleased_plugins` until an owner validates it against a
real server and approves signed publication. Branch CI's `unsigned-dist` artifact carries
an installable unsigned preview for the host's untrusted-package flow.

Behavior is covered by fixture-based tests that replay Plex-shaped JSON through a fake
host gateway (`tests/test_media_server_sync.py`): connection, pagination, episodes, conflict
review, availability, scheduling hints and the absence of credentials from every output.
It has **not** yet been exercised against a live Plex server.

```sh
python -m pytest tests/test_media_server_sync.py
python tools/check_source_layout.py
python tools/build_packages.py
```
