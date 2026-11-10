# Official plugins

[Epic Games Library](epic-games/README.md) connects a personal Epic
account and imports games, playtime and artwork addresses through Plugin API 1.1.19. It relies on Epic's
unofficial launcher services, so it is experimental; see its
[service dependency and support notes](epic-games/README.md#experimental-service-dependency).
It preserves manual library state and resumes bounded inventory/catalogue/import
steps after failure. Its packaged sandbox UI uses narrow connections, background
task, storage, network and game-write permissions. Branch CI supplies an unsigned
preview; signed publication uses the existing protected official pipeline.

[Extended Session Manager](extended-session-manager/README.md) enhances the
built-in personal and administrator session pages with GeoIP, network, anomaly
details and maps. It retains the ID `example.self-service-session-manager` so
existing installations can update. New releases use the scoped official signer;
historical demo-signed archives keep their original identity. The successor-key
trust and expiry requirements are tracked in
[host issue #7](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/issues/7).

[Unnamed Tracking PWA](pwa/README.md) is maintained official functionality,
published through the scoped official signing identity. See the [catalogue](../list.json) for its current signed version.

[Jellyfin Media Sync](jellyfin-media-sync/README.md) starts at **0.0.1**, an official
preview under test with the separate ID `official.jellyfin-media-sync`. Its release
uses that same reviewed official signing pipeline. Version 1.0 will follow
validation and an explicit release decision.

[Plex Media Sync](plex-media-sync/README.md) and [Emby Media Sync](emby-media-sync/README.md)
are unreleased **0.1.0** previews (`official.plex-media-sync`, `official.emby-media-sync`,
Plugin API 1.1.20). Each adds a personal Settings → Account → Connections entry that syncs
watched and in-progress state, playback positions and play counts into Movies, TV and Anime
through `media.sync` enrich, records a credential-free `watch_url`/`watch_label` for the host's
"Watch in …" button and marks items unavailable after two complete censuses. Sync runs in
bounded, resumable steps from Connections, an opt-in personal schedule or the page. Both
packages ship a byte-identical shared `engine.py`. They are kept in `unreleased_plugins`
until validated against real servers; branch CI's `unsigned-dist` carries previews.

[Open Library Metadata Provider](metadata-openlibrary/README.md) is an unreleased **0.1.0** preview
(`official.metadata-openlibrary`, Plugin API 1.1.20). It is an optional, keyless book provider for hosts with
or without Atlas: title, author and ISBN search, ordered authors, subjects, first publication, up to 50
editions and covers. It serves only books, so it stays in `unreleased_plugins` until the host with books is
released; branch CI's `unsigned-dist` carries the preview.

The separate [Jellyfin demo](../examples/jellyfin-media-sync/README.md) remains an
example. Official plugins are maintained user-facing features. Demonstrations
remain in `examples/` and use separate demo signing identities. Valid signature
and official status are distinct; every plugin still requires its declared
permissions, with no sandbox exemptions or special host APIs.

[Collector's Archive](collectors-archive/README.md) preserves Cards,
Sets and Bounties after their removal from the host. It is an unreleased source
preview, available in branch CI's `unsigned-dist` artifact. Its native pages use
the public host UI runtime, and its personal import preserves legacy identifiers,
artwork, prestige links, evidence, journals and point history without deleting
server originals. A signed production release requires the official publisher.

[Discord Bot Notifications](discord-bot-notifications/README.md) is published
under **Unnamed Tracking Official**, with manual updates. It supports PRIVATE
per-account direct messages, independently host-verified SECURE recovery destinations
and PUBLIC administrator-allowed server channels. The plugin owns Discord transport
and secrets; the host owns routing, disclosure and delivery lifecycle. Previously
independently signed previews require fresh installation and destination verification.
See the [catalogue](../list.json) for the current signed package.


Maintained password recovery: `official.password-reset` uses host API 1.1.7 with explicit administrator activation and verified external recovery destinations. It performs real password recovery through host-owned tokens/account mutation; synthetic notification demos remain separate. See [setup](password-reset/README.md).


Maintained user invitations: `official.user-invites` uses host API 1.1.8 with explicit administrator activation and built-in SMTP. Accounts are created only by single-use acceptance on the host. See [setup](user-invites/README.md).

[Discord Notifications](discord-notifications/README.md) is the maintained Discord webhook
notification provider. See the [catalogue](../list.json) for its current signed version.

[Game Night](discord-social-activity/README.md) is a Discord Activity for choosing a game
together, published under **Unnamed Tracking Official** with manual updates. See
the [catalogue](../list.json) for its signed package and the
[setup and troubleshooting guide](../wiki/docs/examples/discord-game-night.md).

Metadata providers supply search, metadata and artwork through the host's provider
settings: [GiantBomb](metadata-giantbomb/README.md), [GOG](metadata-gog/README.md),
[HowLongToBeat](metadata-hltb/README.md), [MyAnimeList](metadata-jikan/README.md),
[Kitsu](metadata-kitsu/README.md), [RetroAchievements](metadata-retroachievements/README.md),
[ScreenScraper](metadata-screenscraper/README.md), [TMDB](metadata-tmdb/README.md) and
[TVDB](metadata-tvdb/README.md). See the [catalogue](../list.json) for current signed versions.

[Atlas Metadata Provider](metadata-atlas/README.md) searches and enriches games, anime, movies and TV shows from a self-hosted
[Atlas](https://github.com/obsoletelabs/unnamed_tracking_metadata) server, merged across providers. The server URL and
read token are configured in the provider settings. Source preview; signed publication uses the official pipeline.
