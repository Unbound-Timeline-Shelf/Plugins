# Metadata provider plugins

The nine optional official metadata plugins consume the host's additive **Plugin API v1.1.1**
contract. The host owns discovery, ranking, deduplication, sessions, health UI,
enrichment scheduling and persistence. Plugins own external API communication,
authentication, parsing, provider mapping, pacing and retries.

## Install and configure

Build/install packages through the normal plugin workflow, review permissions
and enable them. Open the host's **Settings → Metadata/API** provider panel or
the plugin settings dialog. Administrators may configure system fields; each
user may configure their own fields. User overrides win over system fallback
for fields whose declaration permits both scopes. Values are encrypted and
write-only in UI/API reads; clearing a user value restores the system fallback.

The host reuses its original compact source tiles, colored badges, key buttons
and expandable forms. Core tiles are hardcoded in the host; optional plugin registrations add extra
tiles with live health classifications. Administrators choose **System default**; **My account**
edits only their user scope. Existing account-import connections remain below
the metadata tiles. See the [host screenshots and workflow](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/blob/feat/metadata-provider-orchestration/wiki/docs/integrations/metadata.md).

Core Steam, IGDB, SteamGridDB, TVmaze, AniList, AniZip and OMDb implementations
are maintained inside the host and need no plugin installation. Existing core
keys are carried forward by the host. Optional plugins do not automatically
receive old host keys; configure them in their provider tiles. Account library/achievement
sync credentials remain in their existing account integration settings.

| Package | Media / capabilities | Credentials |
| --- | --- | --- |
| `metadata-gog` | Game catalogue search and metadata | None |
| `metadata-atlas` | Merged game, anime, movie, TV and book search and metadata from an Atlas server (books and the ISBN lookup need Plugin API 1.1.20) | Server URL (plain setting) and read token, system/user |
| `metadata-giantbomb` | Game search, metadata and artwork | GiantBomb API key, system/user |
| `metadata-retroachievements` | Game search and metadata | RetroAchievements username/key, user |
| `metadata-screenscraper` | Selected game artwork | Developer ID/password and account ID/password |
| `metadata-hltb` | Game completion time | None; unofficial API can reject requests |
| `metadata-jikan` | MAL anime search, metadata, episodes, airing and artwork | None; Jikan availability/rate limits apply |
| `metadata-kitsu` | Anime search, metadata, episodes, airing and artwork | None |
| `metadata-tmdb` | Movie/TV/anime search, metadata, episodes, collections, recommendations and artwork | Optional TMDB API key, system/user |
| `metadata-tvdb` | TV search, metadata, franchise relationships and poster | TVDB API key, system/user; optional subscriber PIN, user |

## Public wire contract

`tools/schemas/metadata-registration-v1.schema.json`, `metadata-request-v1.schema.json`
and `metadata-response-v1.schema.json` are exported from the host's public models.
The companion contains no host source imports. `sdk/metadata_provider.py` uses
the existing gateway protocol and can be packaged with ordinary official plugins.

Declare a namespaced provider ID, independent action IDs, media types, identifier
namespace and required configuration. Optional metadata resources identify
entity, episodes, airing, relations and recommendations. Episode sources declare
primary/fallback authority. Declare the required `metadata_providers.*` leaves,
network and storage permissions in the manifest and the matching action capabilities
in the UI document. Call `register(DECLARATION)` after startup.

Actions receive authenticated request context and, for enrichment, a canonical
candidate. Search returns lightweight candidates without metadata or artwork.
At five query characters the host preloads metadata from the top down with up to
five concurrent fetches, refilling each slot as it finishes. Query changes cancel
obsolete work. Artwork still requires selection; providers do not schedule preload work.
Metadata returns partial canonical fields, with scores on 0–100. Media returns
asset references only when the host selects an entity. Cross-ID lookup uses a
unique exact title and known year when an ID is missing; ambiguous titles remain
unresolved. Never manipulate library rows or watched state from a provider plugin.

Use `metadata_page` for large collections. It respects the runtime's 64 KiB
action-output limit, counts actual entries and preserves summaries across variable
page sizes. The host detects repeated cursors and applies one overall deadline.

`ProviderHttp` owns atomic provider pacing through `plugin.storage`. Interactive
requests wait at most one second for a slot and do not retry. Background work can
wait/retry within its own 24-second budget, honoring numeric or HTTP-date Retry-After
values mediated by the host. A background worker does not reserve future slots
ahead of interactive work. Provider failures retain classifications without
remote error bodies, URLs or secrets.

### Completion estimates and HLTB (API 1.1.13)

The updated HLTB source targets API 1.1.13. Its optional metadata fields add
`time_to_beat_extras_hours`, `time_to_beat_completionist_hours` and
`time_to_beat_all_hours` alongside existing Main story `time_to_beat_hours`.
The three additions are finite, nonnegative hour values up to 99,999.9. Earlier
Main-story-only payloads remain valid. Schema snapshots match the host's public
models; no host imports or persistence logic are included in the SDK/plugin.

HLTB obtains a public initialization token and sends it as `X-Auth-Token`, with
the supported browser headers. One search 403 triggers one fresh initialization
and retry. SDK background HTTP retries do not retry 403, leaving renewal to the
provider. Other transient failures retain existing bounded retries and pacing.
No response-cookie API, wider permissions or persisted search tokens are needed.
The existing health action uses the same flow. Missing/invalid categories are
omitted, and ambiguous title matches remain unresolved unless an HLTB ID is known.
The host independently applies native IGDB values only where other completion
estimate sources supply no useful figure.

The source depends on [host PR #136](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/pull/136).
Direct token/search verification on 15 October 2026 succeeded for Portal; historical
live observations below describe the older implementation. Development previews
and final signed publication retain the normal package integrity and trust workflow.

## Validation and limitations

Contract/unit fixtures verify mapping and failure behavior; they do not establish
live service success. `tools/check_metadata_live.py` exercises the native Steam/SteamGridDB core suite
on a disposable host with no required plugin packages. Optional sources continue
to be tested as actual `.utp` packages through the host integration harness. Its optional SteamGridDB flow checks absent,
invalid, user-scoped and system-scoped credentials. Credentials come from local
environment/configuration and are never printed. Keep preview output under ignored
`.validation/`; publication still uses the official signer and immutable histories.

Live optional/preview development validation before the core transfer on
2026-10-07 observed:

- Steam, SteamGridDB and TVmaze: search/enrichment and selected artwork succeeded.
  SteamGridDB rejected invalid credentials and validated both credential scopes.
- AniList and Kitsu: progressive search, selected metadata and artwork succeeded.
  AniList rate limiting and Jikan timeouts did not discard other providers' data.
- AniZip: the corrected `anilist_id` mapping endpoint passed real health checks.
- GOG: public catalogue/metadata responses were reachable in direct live probes.
  The catalogue returns fuzzy matches; the host's title filter keeps unrelated
  products out of the displayed Portal 2 matches. The installed-package harness
  does not establish authenticated GOG account-import success.
- HowLongToBeat: its unofficial endpoint rejected requests; reported unavailable.
- IGDB, GiantBomb, RetroAchievements, ScreenScraper, OMDb and TVDB: missing
  credentials were verified; live authenticated success remains unverified.
- TMDB: signup/live authentication was intentionally skipped. Its optional
  implementation has contract coverage; no live success is claimed.

The host's eight-second interactive and 25-second background deadlines can return
partial long episode/franchise inventories under rate limiting. Prior fields remain
available, and later background refresh can fill missing fields.

## Core ownership

The seven former core preview sources were transferred to the host at the user
request. Their episode regressions moved to the host core suite. This repository
retains nine optional providers: GOG, GiantBomb, RetroAchievements, ScreenScraper,
HowLongToBeat, Kitsu, Jikan, TMDB and TVDB. No private host imports or embedded
host runtime were added here. That transfer kept Plugin API 1.1.1; the later
completion-estimate additions above target API 1.1.13.

After the transfer, the isolated host was verified with **zero installed plugins**
and its plugin runtime stopped. Native Steam search, TVmaze search/details/artwork,
AniList search/details/artwork and AniZip health succeeded. Native SteamGridDB
validated missing, invalid, personal and shared keys and provided selected artwork.
The first native Steam result arrived in 0.56 seconds with no artwork; selected
metadata/artwork appeared in 1.74 seconds in the credential-scope harness.
Remote timing and rate limiting vary. IGDB and OMDb authenticated live success
still require credentials; contract fixtures cover their native mappings.
Later runs observed intermittent TVmaze and SteamGridDB timeouts; successful
results and Steam CDN artwork remained available. These live timings are
observations, not performance guarantees.
