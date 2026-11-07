# Atlas Metadata Provider

Search and enrich games, anime, movies and TV shows from an [Atlas](https://github.com/obsoletelabs/unnamed_tracking_metadata) server. Atlas can merge Steam, IGDB, TMDB and curated sources into one canonical record, while the app combines Atlas with its other providers using the user's provider ranking. Uses public Plugin API v1.1.20 (search, metadata, media, health), so it needs a host on Plugin API 1.1.20 or later: an older host refuses to install it and keeps the previous release.

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
- **Metadata** is fetched by Atlas ID. A candidate without one is resolved by linked provider IDs or exact title and year, constrained to the same media type; only certain matches are accepted (Atlas `reason` `id`, `redirect`, `crosswalk` or `exact`). A `conflict` (the candidate's identifiers point at different Atlas records), an `ambiguous` or cross-type answer and a fuzzy match are never adopted: the plugin returns no metadata, writes the conflicting Atlas IDs to its log and leaves the choice to a curator in Atlas. The year is sent as the release date (`2011`). An Atlas that predates `reason` is read as before (`method` `crosswalk` or `exact`, and no `conflict`); it cannot report conflicts, so against it a conflicting pair can still resolve to the record that owns the first identifier. Returned records include an **Atlas record** link so you can open Atlas and propose missing identifiers through its linking workflow.
- **Metadata fields** are mapped by media type to the app's provider-neutral contract. Games include developer, publisher, series, features, platforms and multiplayer facts. Movies include director, studio, runtime, writers and production countries. Anime includes studios, format, episode count and themes. TV shows include creators, episode count and episode runtime; networks and season count remain visible as provider custom details. All types can include release date, description, tags, genres, languages, alternate titles, age rating, links, scores, provider IDs and bounded Atlas custom values. Invalid or missing fields are omitted. Provider ordering in the app determines the default winner when sources disagree; fields no other provider supplies still complement the result.
- **Release dates** keep their precision (Plugin API 1.1.20, Atlas contract C5). Atlas's `first_release` is sent as `first_release` (`{"date": "2011-04", "precision": "month"}`), so a year-only or month-only release is never shown as 1 January. `release_date` stays day-only: it is sent only for a real calendar day, and a day `first_release` always names the same day. Up to five regional `releases` (date, precision, platform, region, edition, category) are forwarded in Atlas's order; an entry with an unusable value is left out, not altered. `year` comes from the first release at any precision. Against an Atlas that predates partial dates, a partial value in its legacy `release_date` key (a curator lock such as `2011`) is read as that year or month, and a free-text one (`TBA`) sends no date.
- **Relations** between games (Plugin API 1.1.20, Atlas contract C6). Atlas's own relations of a game (its `parents`, such as the base game of a DLC, the original of a remake or port, and its `members_of`, a series or collection) are sent as `relations`: `{"candidate": {"provider": "official.metadata-atlas.atlas", "external_id": <the other record's Atlas id>, "title": ..., "provider_ids": {"atlas": ...}}, "relation": "dlc_of", "group": "related"}`, ordered by relation type (the shared vocabulary order) and then Atlas id, at most 64. The host links the game to the one it tracks under that Atlas id, or keeps the reference until it does. Incoming relations (`children`, `members`) belong to the other record and travel with its refresh. Only the twelve types of the shared vocabulary are sent; any other (`edition_of`, `bundle_contains`, a future type) is left out and its name logged, and a malformed entry is skipped. Editions are not relations (C6.1): an edition reaches the host as the `edition` of a regional release. A game found through a Steam or IGDB id gets its relations too: `/resolve` does not include them, so the plugin reads the record once more. An Atlas without relations sends none.
- **Identifiers** sent to the host are bounded as the host requires (at most 32: `atlas` first, then the well-known store and catalogue namespaces such as `steam`, `igdb`, `gog`, `epic`, `rawg`, `tmdb` and `imdb`, then the others sorted, so a record whose sources claim many obscure namespaces keeps its store ids; a value that is not a string or number is left out), and `/resolve` receives only real provider namespaces within Atlas's limits (at most 32 ids of up to 256 characters; a title over 500 characters is left out). The host's library candidate also lists its own identity under its provider id (`local`, whose value is the title); that key is not sent.
- **Achievements** are game-only definitions (name, description, hidden flag, global percentage, cached icons, stable IDs and source IDs), never player progress. The host stores definitions without changing progress and can resolve them through linked IDs such as Steam. Non-game records never request the game achievement endpoint.
- **Media** lists only artwork Atlas has already downloaded and verified, as `<public-server>/media/<hash>` links. For anime, movies and TV, Atlas key art is exposed as a poster. Achievement icons use the same verified media path. The public URL must be reachable by the app's browser; keeping it separate from the API URL lets the app server use a private Docker address without exposing that address to browsers.
- Merged Atlas IDs keep working: a record merged into another (also through a chain of merges) is returned under its current ID, and metadata, artwork and achievements are read from that live record.
- Failures are typed (`not_configured`, `invalid_configuration` for a bad URL or rejected token, `rate_limited`, `unavailable`); remote bodies and the token are never retained.
- Personal data is never sent. Only titles, years and provider IDs go to the server.

Build development packages with `python tools/build_packages.py`. Unsigned previews require explicit installation consent; signed publication uses the existing release workflow.

## Compatibility

The plugin reads the contract it declares in its own `manifest.json` (the version the host validates its responses
against) and sends `first_release`, `releases`, game `relations`, achievement `aliases` and the `platinum` tier only
when that declaration is 1.1.20 or later. A host older than 1.1.20 refuses to install this release, so it never meets those fields; a build
relabelled to an older contract, or a manifest that cannot be read, sends none of them. An Atlas that has no dates,
keys or platinum yet simply leaves the fields out. Tiers, kinds, crossplay, precisions and release categories are
checked against `vocab.py`, the shared vocabulary of CONTRACTS-v1 C7.4: `contracts/vocab-v1.json` is generated from it
(`python tools/vocab_check.py generate`) and compared with the files Atlas and the host publish (`python
tools/vocab_check.py compare contracts/vocab-v1.json tests/fixtures/atlas/vocab-v1.json
tests/fixtures/host/vocab-v1.json`). Crossplay is `yes`, `partial` or `no`; `not_applicable` is derived by the host and
never sent, and an absent value means unknown. `python tools/check_metadata_atlas_host.py --host-root <host checkout>`
holds the plugin's responses to the host's own validator under both a 1.1.20 and a 1.1.19 declaration.

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
Against an Atlas without keys the plugin falls back to the row `id` (the previous behaviour). Under Plugin API 1.1.20 an
entry merged from several sources also sends its other keys as `aliases` (at most 32), so the host keeps a stored
definition when the anchor key moves, and Atlas's `platinum` tier is passed through.

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
