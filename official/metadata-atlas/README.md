# Atlas Metadata Provider

Search and enrich games, anime, movies and TV shows from an [Atlas](https://github.com/obsoletelabs/unnamed_tracking_metadata) server. Atlas can merge Steam, IGDB, TMDB and curated sources into one canonical record, while the app combines Atlas with its other providers using the user's provider ranking. Uses public Plugin API v1.1.15 (search, metadata, media, health).

## Configure

Install its .utp through Plugin Manager and grant the declared permissions, then set, in the host-rendered provider settings (system or personal scope):

| Setting | Meaning |
| --- | --- |
| **Atlas API URL** | Root used by the app server to reach your Atlas node, e.g. `https://atlas.example.org` or `http://atlas:8000` on a shared Docker network. A path prefix is allowed (`https://host/atlas`). No credentials, query or fragment. |
| **Public Atlas URL (optional)** | Root that a user's browser can reach. Leave blank when it is the same as the API URL. Set it when the app server uses an internal Docker address but Atlas is published at a different URL, such as API URL `http://atlas:8000` and public URL `https://atlas.example.org`. Artwork, achievement icons, and Atlas record links use this address. |
| **Atlas API token** | A token with the `read` scope (`atlas token --name tracker --scopes read`). Write-only and encrypted by the host. |

Use your own server, a LAN mirror or a public one; the plugin contacts only the configured URL. Egress is governed by the `network.outbound` grant, so the administrator chooses the destination.

## Behaviour

- **Search** is filtered to the requested media type and returns lightweight candidates with Atlas ID plus linked store/provider identifiers (`steam`, `igdb`, `tmdb`, ...) so the host can cross-link them.
- **Metadata** is fetched by Atlas ID. A candidate without one is resolved by linked provider IDs or exact title and year, constrained to the same media type; only certain matches (`crosswalk` or `exact`) are accepted. Returned records include an **Atlas record** link so you can open Atlas and propose missing identifiers through its linking workflow.
- **Metadata fields** are mapped by media type to the app's provider-neutral contract. Games include developer, publisher, series, features, platforms and multiplayer facts. Movies include director, studio, runtime, writers and production countries. Anime includes studios, format, episode count and themes. TV shows include creators, episode count and episode runtime; networks and season count remain visible as provider custom details. All types can include release date, description, tags, genres, languages, alternate titles, age rating, links, scores, provider IDs and bounded Atlas custom values. Invalid or missing fields are omitted. Provider ordering in the app determines the default winner when sources disagree; fields no other provider supplies still complement the result.
- **Achievements** are game-only definitions (name, description, hidden flag, global percentage, cached icons, stable IDs and source IDs), never player progress. The host stores definitions without changing progress and can resolve them through linked IDs such as Steam. Non-game records never request the game achievement endpoint.
- **Media** lists only artwork Atlas has already downloaded and verified, as `<public-server>/media/<hash>` links. For anime, movies and TV, Atlas key art is exposed as a poster. Achievement icons use the same verified media path. The public URL must be reachable by the app's browser; keeping it separate from the API URL lets the app server use a private Docker address without exposing that address to browsers.
- Merged Atlas IDs keep working: a record merged into another is returned under its current ID.
- Failures are typed (`not_configured`, `invalid_configuration` for a bad URL or rejected token, `rate_limited`, `unavailable`); remote bodies and the token are never retained.
- Personal data is never sent. Only titles, years and provider IDs go to the server.

Build development packages with `python tools/build_packages.py`. Unsigned previews require explicit installation consent; signed publication uses the existing release workflow.

## Local browser check

For an app and Atlas running in separate Docker containers, set **Atlas API URL** to the container address (for example `http://atlas:8000`) and **Public Atlas URL** to the address your browser can open (for example `http://127.0.0.1:28080`). Save the provider settings, then run **Achievements sync** again under **Settings → Account → Background tasks** so existing achievement icon links are refreshed. The public Atlas URL must serve `/media/<hash>` without requiring a browser token.

This local app test used Atlas 0.7.1 and a small blue icon fixture. The achievement definition, its icon, and separate Pin/Edit controls are visible together:

![Atlas achievement icon loaded in the tracking app](https://github.com/user-attachments/assets/3105f083-1949-4f8e-9eee-7f7958dd21ab)

## Achievement catalogues

Achievements are read from Atlas in pages (`limit=200`, `offset`, following `next_offset`) and handed to the
host the same way: one Atlas page per response, trimmed to 56 KiB (measured as `json.dumps` of the whole
result) so it stays under the plugin runtime's 64 KiB action output limit. A response that does not fit
returns `next_cursor`, the next unsent Atlas offset, and the host asks again until there is none. Typical
entries are 500 to 800 bytes, so about 70 to 110 fit per response: a 450-entry game takes 5 to 7 responses
and a 2000-entry game about 20 to 30.

Achievement identity: the host `external_id` is the stable `ak1:` key Atlas gives each entry (Atlas contract C2, Atlas
`programme/a4-achievement-identity`), which survives list re-imports, edits and node differences; the Atlas row `id` is
not an identity because older Atlas versions minted a new one on every refresh. The row id travels as
`source_ids["atlas.row"]` so a host that stored the catalogue under row ids can re-key it instead of recreating it.
Against an Atlas without keys the plugin falls back to the row `id` (the previous behaviour). No Plugin API field beyond
1.1.19 is sent.

The host accepts at most eight `source_ids` per entry. The `atlas.row` bridge takes the first slot, so an entry that
carries eight or more provider ids loses its last provider id(s). The host links catalogue rows to synced platform rows
through `source_ids`, so such an entry can lose that link for the dropped provider; this is a deliberate trade-off to
keep the re-key bridge. Do not ship this plugin version to users before the host re-key (M6) is deployed: until then
the first sync recreates catalogue rows under the new ids, orphans manual-progress overrides and drops media links.
A plugin rollback changes every `external_id` again, so fix forward instead of rolling back.

The host merges the pages by `external_id` (host PR 447), so an entry repeated across a boundary arrives
once. At most 2000 entries are forwarded, and a failed later page is reported as a failure instead of a
truncated list. An Atlas without paging ignores the parameters and returns everything in one response,
which is still split under the byte budget. Atlas paging needs Atlas PR 95
(obsoletelabs/unnamed_tracking_metadata); without host PR 447 a later page replaces an earlier one.
