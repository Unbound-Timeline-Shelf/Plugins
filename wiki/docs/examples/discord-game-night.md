# Set up Game Night and the Discord bot

Game Night helps a Discord group choose something to play from their own
libraries. One person hosts the Activity. Participants can connect different
tracking instances, use an older instance's API key, or add games as guests when
the operator permits it. Only the Activity operator needs to configure a bot.

![A two-participant Game Night with artwork, avatars and a shared winner](../images/discord-game-night-live.jpg)

Game Night **0.2.1** is an early signed release in the official catalogue under
**Unnamed Tracking Official**, requiring **Plugin API 1.1.12** or a compatible
newer host and the updated bot adapter. Updates require manual review. A signature
verifies its publisher and package integrity; it does not approve permissions or
claim every planned feature is complete. Back up your instance before testing a
development host branch. Existing
notification destinations do not need to be recreated for an ordinary update
under the same publisher and installation identity.

## Joining a game night

If someone already hosts Game Night, you do **not** need your own Discord bot.
Launch or join their Activity, open **Connections**, and connect your tracking
instance. Approve the request in that instance's browser window, then return and
refresh your library. You can also add games manually if the operator allows guests.

For one or two players, detected multiplayer is enough when no known limits
conflict. Larger groups can approve games under **Game night → Needs attention**.
Set personal restrictions in **My rules**, then shortlist, vote and choose.
Only operators need sections 1–5 below. Players can start at section 6.

## 1. What the operator needs

- An Unnamed Tracking host with API 1.1.12 or a compatible newer version, working plugin runtime and HTTPS public
  URL. The Activity host can also be one of the source libraries.
- Administrator access to that host and permission to configure a Discord
  application in the [Developer Portal](https://discord.com/developers/applications).
- **Discord Bot Notifications** (adapter 0.1.2 or newer) and **Game Night** from
  the official plugin catalogue.
- A Discord test server and the ability to invite the bot. Private applications
  may require participants to be accepted application testers before launching.

For a normal installation, use **Administration → Plugins → Discover** and select
the official Game Night release. Review **Unnamed Tracking Official**, the
signature, dependencies and requested permissions. If you previously used an
unsigned preview, the first signed update requires a fresh permission review;
the host cannot inherit grants from an unverified publisher. Use the normal
update flow to preserve saved data, rather than uninstalling with purge.

For unpublished branch testing, download **unsigned-dist** from the plugin repository's
[Plugin checks workflow](https://github.com/Unbound-Timeline-Shelf/Plugins/actions/workflows/ci.yml).
Extract the archive and select the two `.utp` files. Review the source commit and
permissions. Do not use a random package sent by someone you do not trust.

## 2. Create the Discord application and bot

1. In the Developer Portal, create an application or select the application for
   your existing Discord notification bot. Keep the same application for the bot
   and Activity.
2. Copy **Application ID** from General Information. This is public configuration.
3. On **Bot**, create the bot if necessary and obtain its **bot token**. Save it
   securely; Discord may show it only when created/reset. Do not reset an existing
   working token just to inspect it. Server Members Intent is needed for the
   notification dashboard's member discovery, not for reading participants' chat.
4. Under **OAuth2**, obtain the **Client Secret**. This is different from the bot
   token. If it is hidden and you have no saved copy, its reset is a deliberate
   credential change; update the host afterward.
5. Enable **Activities** and the desktop/mobile platforms you intend to test.
6. Enable the installation contexts needed by your deployment. Guild installation
   supports your server; user installation makes the app available in supported
   personal/DM launch surfaces. Follow Discord's current installation controls.
7. Invite the bot to your chosen server with the Developer Portal's installation
   link. Notification delivery needs View Channel, Send Messages and Embed Links
   in its allowed channels. Do not grant Administrator merely for Game Night.
8. Enable Discord Developer Mode, then copy the server's numeric ID from its
   context menu. A channel ID is a different value.

Keep bot tokens and OAuth secrets in the host's write-only settings. They do not
belong in URL mappings, source code, browser query strings or Discord messages.

## 3. Install and configure the two plugins

1. Open **Settings → Administration → Plugins** on the Activity host. Install or
   update Discord Bot Notifications from the official catalogue first. Review its
   verified publisher, compatibility and requested permissions.
2. Approve the bot's `integrations.identity_provider` permission along with the
   declared permissions its existing features require. Enable the bot.
3. In **Settings → Administration → Discord Bot Notifications**, enter the bot
   token and server ID, then choose **Validate and save**. A healthy directory
   confirms that the bot and server match.
4. In **Discord Activity sign-in**, enter that application's ID and its OAuth
   client secret. Save them. The status should say **Activity OAuth configured**.
   The adapter checks that the configured bot belongs to this application.
5. Install Game Night from Discover, review it and approve `integrations.public_app`
   and `plugin.storage`. Enable it. Its dependency requires the updated bot.
6. In **Settings → Administration → Integration access**, enable integrations.
   Enable hosted guests if people should be able to play without a tracking
   account. Save the policy.

If the runtime reports an isolation problem, use the host's documented runtime
setup and review its diagnostic. Do not add privileged container flags or disable
permission checks to make an Activity launch.

## 4. Point Discord at your HTTPS host

Set the host deployment's public URL to your actual HTTPS origin, for example
`https://tracking.example.com`. This identifies the Activity operator during
source consent. It is not the `discordsays.com` proxy URL.

In **Activities → URL Mappings**, add:

| Prefix | Target |
| --- | --- |
| `/` | `tracking.example.com/api/public-apps/official.discord-social-activity/app/` |
| `/api` | `tracking.example.com/api` |

Use your own domain. The target field may omit `https://` in the Portal UI. Keep
the complete path and trailing slash for the root entry. Save the mappings.

The public Activity page must permit Discord to frame it. The host supplies the
appropriate Content Security Policy. If your reverse proxy adds
`X-Frame-Options: SAMEORIGIN`, exclude only the Activity asset path from that
header. Keep frame protection on the rest of your tracking app.

For Nginx, an operator using a server-wide `add_header X-Frame-Options` can replace
its value with a map in the `http` context:

```nginx
map $uri $tracking_frame_options {
    default "SAMEORIGIN";
    ~^/api/public-apps/official\.discord-social-activity/app/ "";
}
```

In the relevant server configuration, replace the existing frame header with:

```nginx
add_header X-Frame-Options $tracking_frame_options always;
```

Check whether an upstream also sends that header; `proxy_hide_header` removes an
upstream header but cannot remove one added locally by Nginx. Validate your actual
configuration with `nginx -t` before reloading. Do not add a duplicate conflicting
header. Test the public Activity URL: it should return 200 and no blocking frame
header. Opening that URL directly shows the launch page; a real room runs inside
Discord.

## 5. Launch and invite people

Open the configured server's text channel or voice Activity surface, find
the application in Discord's App Launcher and launch it. Accept Discord's private
app test notice if applicable. Discord sign-in identifies the participant and the
bot verifies membership in that exact Activity instance. A tracking account is
not required for a permitted guest.

Participants must join the same Activity instance to share a room. Each person
keeps their own preferences and vetoes. The first active participant becomes the
room host; transferring control requires a separate confirmation. A person with
no game contributions watches without blocking the group by default.

Use **Invite friends** in the Activity header to open Discord's native invitation
dialog. Choose recipients and send from Discord yourself; opening the dialog does
not automatically message anyone. Channel access and private-app tester rules
still apply. If this control is unavailable in a particular Discord surface, use
Discord's own Activity invite/join controls.

Discord currently disables Activity launching in the tested Stage channel: its
launcher shows **You cannot launch an activity here**. Use a text channel, voice
channel or supported DM surface instead; the plugin cannot override Discord's
disabled launch control. Joining a Stage audience does not start an Activity.

### DMs and group DMs

In the bot's **Discord Activity sign-in** settings, enable **Allow Activities in
DMs and group DMs**, then save. Leave the client-secret field blank to keep the
existing saved secret for the same application. This policy is off by default.
It permits private-channel Activity rooms; it does not enable notification DMs or
recovery destinations on anyone's behalf.

![The operator's opt-in private Activity setting](../images/discord-activity-private-rooms.jpg)

Ensure your Discord application permits user installation and the corresponding
private-channel launch contexts. Install it to the testing user's account if
Discord requires that for the launcher. Open the DM/group DM, use its App
Launcher or supported Activity/call launch control, and have the other person
join that same instance. Private applications can still require accepted tester
access. An app hidden by Discord's installation/testing settings will not appear
merely because the host checkbox is enabled.

For an application created with guild-only launch settings, inspect its `launch`
entry point with Discord's [Application Commands API](https://docs.discord.com/developers/interactions/application-commands).
DM launches need user installation (`integration_types` includes `1`) and private
channel context (`contexts` includes `2`). Supporting both guild and private
launches normally uses `integration_types: [0, 1]` and `contexts: [0, 1, 2]`.
Installation contexts alone do not override a command's narrower contexts.

The bot verifies Discord's private-channel location and exact connected member
list. A DM does not need a guild ID. Server rooms remain restricted to the
configured guild even while DM support is enabled. Separate Activity instance IDs
keep server and private rooms separate; connecting a library in one does not
publish its credentials in another. The operator still uses the configured bot
application and its saved OAuth credentials.

## 6. Connect a current tracking instance

The Activity operator saves its own HTTPS origin under **Settings →
Administration → Application → Shared public app URL**. Current hosts resolve
this saved setting through the existing configuration handler; an optional
`PUBLIC_APP_URL` environment or `.env` value takes precedence. An environment
variable is not required. Use the operator's domain, not Discord's proxy domain.

The source instance's administrator first enables Integration access and allows
the Activity host's exact HTTPS origin. They may instead explicitly allow consent
requests from any HTTPS origin; individually disabled origins remain blocked.
Approving an origin only lets it request access. Each person must approve their
own account data.

In Game Night's **Connections** tab, enter the source instance's HTTPS origin.
Library matching requests only identity and game reads. Select **Request optional
tracking and achievement access** only if you want the progress features too.
That adds achievement reads and optional tracking/achievement writes; it does not
request your media, custom lists or field history.
Open the returned consent page in your normal browser and sign in to that source.
Verify the requester name, source instance and requested capabilities. Writes are
optional and initially unchecked. Choose timed access or explicitly choose
**Until revoked**, then approve or deny. Return to the Activity; it polls the
pending request and offers refresh when connected.

A Discord display name cannot silently link a tracking account. After first
consent, the verified Discord identity can reuse its still-valid remembered source
connections on reconnect. Check **Account → Connected apps** on the source to
review scopes, remove capabilities or revoke access. Removing an origin or
disabling integrations blocks its grants too.

## 7. Connect an older tracking instance

If the source cannot be upgraded, the Activity operator can enable **Allow unsafe
legacy API-key connections** in Integration access and save the policy. The
participant selects legacy mode in Connections, enters the old source's HTTPS
origin and an API key created on that source, and acknowledges the broad key.

Legacy keys may have much broader account authority than the Activity needs.
The host encrypts the key, uses only identity/library reads and never returns it
to plugin code. Legacy connections cannot update tracking, achievements or saved multiplayer settings.
Imported artwork may be unavailable; public Steam cover fallback is separate.
Disconnect to remove the broker copy and revoke the key on the old source when
finished. The old instance does not need a new plugin runtime for this read mode.

## 8. Choose games and keep control of your rules

Owned games detected as multiplayer are included automatically after library
refresh. **My games** defaults to owned multiplayer entries; untick its filters
to browse the rest of your library. Detection uses available features/tags and
saved multiplayer markers. It is an inference, not provider verification.

For **one or two active players**, detected multiplayer is valid without entering
exact limits. For larger groups, open **Game night → Needs attention** and choose
**Approve for N players**, or select several games and approve them together.
One person can approve for the current group without supplying extra metadata.
That approval must be renewed if the number of players changes. Known saved or
manually reported limits remain authoritative and cannot be bypassed by approval.

![Two players with automatically eligible multiplayer games](../images/discord-game-night-automatic.jpg)

Choose **Set known player limits** to enter what you know. Both fields are
optional: for example, leave minimum blank and enter maximum **4**. **Save
details** keeps that maximum, labels the minimum **unknown**, and approves only
the current group size. If the group size changes, approve it again; the known
maximum still applies. A minimum on its own works the same way. Blank does not
mean **1** or unlimited, and approval cannot override a known bound.

![Room form with an unknown minimum and a known four-player maximum](../images/discord-game-night-optional-limits.png)

Enter both bounds to confirm a reusable range for future group sizes. Common
ranges are available as buttons. These room details survive
reconnects until room retention expiry; they do not write anyone's source library.
For copies grouped on an instance, confirmations retain the main matching title
so they still apply when the displayed copy has a different title.
If your platform is missing, the form asks only for your own platform. A valid
Steam app ID infers **PC** when the platform is blank; an explicit platform wins.
The host can disable small-group acceptance or Steam inference in room settings.
Steam inference does not prove Windows/Mac/Linux support or crossplay.

Ownership, platform, crossplay, session length, personal rules and vetoes still
apply independently. People without games spectate without blocking by default.
Guest ownership, room approvals and manually entered compatibility are self-reported.

### Save multiplayer details in the tracking app

On a game's **Overview**, choose **Edit multiplayer settings**. Tick **Playable
with others** and save without extra data, or enable known limits and set both
minimum and maximum. Duration and crossplay are optional. You can also use the
ordinary game's Edit form. To update several games in one instance, select them
in the library, open **Bulk Edit**, opt into **Apply multiplayer settings**, and
review the replacement. Unchecked fields are untouched; leaving the playable
marker unchecked explicitly clears saved multiplayer details.

### Save selected games across linked instances

In **Connections**, select **Request optional multiplayer settings access** and
connect/reconnect each current source. Approve **Save your games' multiplayer
settings** on its consent page. Existing grants never gain this permission
automatically. It is separate from progress access and uses `compatibility.write`.

In **My games**, select entries across pages and instances (up to 100). Choose
**Edit selected multiplayer settings**, set a preset or clear it, expand the
target review, and confirm the selected game records. A preset replaces those
games' multiplayer details only. All selected sources must be connected and
grant the new scope. Legacy keys remain read-only. Each game saves independently;
the results list reports successes and source failures. Refresh the affected
connections afterward. A failed source does not roll back successful saves.

![Two players in a DM with one participant's shared player-count confirmation](../images/discord-game-night-shared-limits.jpg)

**My rules** controls your platform, genres, time and ownership/purchase consent.
The host chooses Strict, Balanced or Discovery and can change room matching
defaults. Normalized titles tolerate case, spacing and punctuation; edition or
crossplay differences still need confirmation. Copies someone grouped as one game on
their own instance (Minecraft Java Edition and Minecraft for Windows under Minecraft)
count as that game, matched by its main title, so they meet other people's copies. Current purchase offers are
unavailable, so price/budget/discount filtering is paused and unknown prices are
never called free.

Make a shortlist, vote and choose together. **Veto** removes a game under your own
rules; **Undo veto** restores it without clearing anyone else's veto. Click a
title for public information, a Steam link and your own tracking-page link when
available. Public images do not grant access to another person's source instance.

## 9. Optional tracking and achievement updates

Select optional progress access in Connections, then connect through scoped
consent and approve the relevant writes on your source. An existing read-only
connection needs a new consent request to add these capabilities.
In **Tracking**, choose your connection and game, review the proposed change and
confirm it. Read-only or legacy connections cannot perform these actions. A local
edit to a synced achievement is explicitly self-reported and stored separately
from provider evidence. It is not a Steam unlock or provider verification.
Changing the connection or game clears the approval checkbox. A status update
preserves the completion date unless you select **Change completion date**;
leaving the date blank after selecting that option explicitly clears it. Manual
self-reports appear separately. This preview shows the first achievement page;
use your tracking app to inspect further pages.

## Troubleshooting

### Start with these three checks

A blank Discord Activity does not always mean the bot token is wrong. Check the
worker, the public page and Discord's proxy in that order. A healthy notification
bot alone does not establish that Game Night is running.

1. Open **Administration → Plugins → Game Night → Diagnostics**. Game Night and
   **Discord Bot Notifications** should both be **running** and **healthy**.
   If Game Night failed, read its recent diagnostic events before changing keys.
2. Open your host's public Activity URL:
   `https://tracking.example.com/api/public-apps/official.discord-social-activity/app/`.
   It should return **200** and the Game Night launch page. A direct visit does
   not join a room; launch inside Discord for that.
3. Inspect the response headers on both that URL and
   `https://APPLICATION_ID.discordsays.com/`, replacing `APPLICATION_ID` with the
   ID in the Developer Portal. Both must return the Activity HTML without a
   blocking `X-Frame-Options` header. Confirm the URL mappings in section 4.

For example, on Linux/macOS:

```sh
curl -sS -D - -o /dev/null https://tracking.example.com/api/public-apps/official.discord-social-activity/app/
curl -sS -D - -o /dev/null https://APPLICATION_ID.discordsays.com/
```

On Windows PowerShell, use `curl.exe` and replace `/dev/null` with `NUL`.
These are public-page checks and require no bot token, client secret or API key.
Do not paste credentials into these commands or share unredacted response
headers containing cookies.

### Game Night failed after a host restart

An older preview's room-cleanup worker could exit on a temporary host-gateway
**HTTP 503**, leaving Game Night enabled but **failed / unhealthy**. Its public
page then returned **404** with
`This public app or identity provider is unavailable.` Discord may present this
as a generic refused connection rather than displaying the server's error.

Wait for the host/runtime to become available, then use **Retry** in Game Night's
plugin settings, or **Start** if it is stopped. Refresh Diagnostics and confirm
**running**, **healthy** and no new exit event. Leave the failed Activity in
Discord and launch it again; the failed frame does not refresh itself.
Restarting preserves saved rooms and linked accounts. Reinstalling with purge
is unnecessary for this failure.

Game Night **0.1.0** retries room cleanup when the gateway reports `unavailable`,
with delays of 1, 2, 4, 8, 16 and then at most 30 seconds. It resumes the normal
minute cleanup interval after recovery. A waiting message appears in Diagnostics;
if it continues, investigate host/runtime reachability. Permission denials and
other permanent failures still surface instead of retrying indefinitely. Review
the exact installation's grants and compatibility for those errors.

If the public page returns **403**, check **Administration → Integration access**
and the explicit installation-wide `integrations.public_app` grant. The bot also
needs its separate `integrations.identity_provider` grant for sign-in. Repeated
retries cannot repair a missing permission.

### The page returns 200 but Discord still refuses to connect

Check your outer reverse proxy as well as the application's own proxy. A
server-wide `X-Frame-Options: SAMEORIGIN` or `DENY` can survive Discord's proxy
even when the direct page's Content Security Policy permits Discord. A successful
direct visit therefore does not prove that the embedded page can load.

Apply the narrow Activity-path exception from section 4 to the hostname Discord
actually targets. When moving hosting from a demo domain to your main domain,
the old domain's exception does not apply to the new one. Keep the other security
headers and frame protection for the rest of the application. Check for duplicate
headers from an upstream proxy too. Validate with `nginx -t`, gracefully reload
the proxy, repeat both public header checks, then leave and relaunch the Activity.

### Check OAuth only after the Activity page loads

In **Administration → Discord Bot Notifications**, use **Refresh** to verify the
bot identity and API health. Confirm **Activity OAuth configured**, the same
Application ID as the Developer Portal, and the intended server ID. A bot that
looks offline in Discord can still pass these checks: this integration uses HTTP
and does not maintain a persistent Gateway presence.

The **bot token** authenticates bot API calls; the **OAuth client secret** exchanges
the participant's sign-in code. They are not interchangeable. Leave the secret
field blank to retain an existing secret for the same application. Rotate only
when the credential is invalid, lost or exposed, then update the corresponding
host setting and relaunch. Keep any recovery copy in a private password manager
or other secure operator storage; neither credential belongs in a support ticket,
URL mapping or repository.

### Linking returns HTTP 500 before a consent page opens

An older host's source broker read only the startup `PUBLIC_APP_URL` value and
ignored the shared URL saved in Application settings. A blank environment value
could therefore raise an unhandled origin-validation error. This is host behavior;
reinstalling Game Night or resetting Discord credentials cannot repair it.

Update the **host application** to include the
[saved public URL fix](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/pull/279),
then confirm the shared public HTTPS URL in Application settings and retry
Connections. The fix uses the existing ENV handler and saved setting, and reports
an actionable HTTP 503 if neither supplies a valid public URL. Source-origin
approval and each user's consent remain required, including when the Activity and
source share the same instance.

### Guests, retention and saved participants

Everyone signs in through Discord. **Guest** means there is no active connected
tracking library; it does not mean anonymous, and it does not create a tracking
account. Guests can add self-reported games only when the operator enables them, and can delete their saved data early.
An offline/revoked source is not proof of current access. Linked users' source
grants have their own expiry, including explicitly approved Until revoked access.

In **Administration → Integration access**, guest/room retention can be set from
1 to 8760 hours (365 days). New rooms use the configured duration. Existing rooms
keep their original expiry; expired data is not resurrected. Remembered valid
source connections may outlive a room, so disconnect/revoke those separately.

After updating Game Night, review its new `integrations.public_app.admin` and
native administrator-page permissions. Open **Administration → Game Night
participants** to see saved Discord names/IDs, source origins and connection
states. Older identities receive their verified username on the next Discord
sign-in. Source **Connected apps** also shows the external account label for new
consent requests, or an exact matching local broker connection; older remote
grants need reconnection to supply the label. Names are descriptive, never proof
for linking accounts; the stable account ID distinguishes people with similar names.

**Unlink this connection** forgets its broker credential and signs the participant
out. **Unlink all connections** does the same for that participant's sources.
Manual guest games remain. **Purge participant data** additionally removes their
identity, inputs, votes and room confirmations; affected cached shortlists and
shared history are cleared. Other participants' personal inputs remain.
**Purge all Activity data** removes all local saved identities/connections and
rooms. These actions require an explicit confirmation. They do not delete source
tracking libraries or revoke upstream grants; use that source's Connected apps
for revocation. An administrator can retry cleanup after an interrupted purge.

![Saved Game Night participants in native administration](../images/game-night-admin-participants.jpg)

Retroactive account merging/reassignment needs explicit identity proof and
conflict rules and is tracked in [#45](https://github.com/Unbound-Timeline-Shelf/Plugins/issues/45). For now, reconnect under the intended
source account. Matching display names never merges accounts.

### Player limits from providers

When your tracking instance supports provider player counts, the Activity labels them
**Reported by a metadata provider**. Provider values are never shown as confirmed:
a person's own saved details and a limit confirmed for the room both outrank them. If
two participants' records disagree, the card says so and each person's own range
still applies, so the narrowest one decides. Missing values stay unknown and are never
invented. Bulk saves keep each game's known play time and report saved/failed counts
per instance. Remaining metadata work (editions, platform variants, stale-data states)
is tracked in [#46](https://github.com/Unbound-Timeline-Shelf/Plugins/issues/46).

![Provider-reported player limits and a metadata disagreement](../images/discord-game-night-provider-limits.jpg)

### Your own data and verified-only rooms

**My rules → Your saved Activity data** shows whether you are a linked participant or
a guest, what is saved and when the room expires, and lets you delete it early. This
never changes a tracking library; a connected library is read again while you stay in
the room. The host can turn on **Verified libraries only** under *Room host settings*:
self-reported games then do not count as games or ownership (participants with only
self-reported games spectate), while linked libraries are unaffected.

![Saved data and bulk editor on a narrow screen](../images/discord-game-night-guest-data.jpg)

| Symptom | Check |
| --- | --- |
| `discordsays.com refused to connect` | Check Game Night Diagnostics, direct Activity HTTP status, then both direct and Discord-proxied frame headers |
| Enabled but failed / unhealthy after restart | Read Diagnostics for gateway HTTP 503; wait for host readiness, Retry, then leave and relaunch Discord |
| Public Activity returns 404 / unavailable | Confirm Game Night is installed, compatible and running; check the bot adapter separately for sign-in |
| Public Activity returns 403 | Integration access policy and exact installation-wide public-app permission |
| OAuth not configured / sign-in failed | Same application ID/bot, OAuth client secret rather than bot token, latest bot package, then relaunch |
| Room membership could not be verified | Join this exact instance; confirm configured server or permitted private-channel location |
| Legacy connections disabled | Activity host's Integration access policy, then Save instance policy |
| Owner must approve an origin | Approve the Activity host's actual HTTPS origin on the source, or enable its optional open requester policy |
| Linking returns HTTP 500 before consent | Update the host with the saved public URL fix; confirm Shared public app URL in Application settings |
| Connected but no eligible games | Expand Needs attention; check ownership, group approval, hard rules, source state and other participants' vetoes |
| Bulk multiplayer Save disabled | Every selected source must grant compatibility.write; reconnect with multiplayer settings access and approve it |
| Optional minimum is required after entering a maximum | Update Game Night to 0.2.1 or later, then close and relaunch the Activity to load the new form. Leave unknown bounds blank; saving one bound keeps it and confirms only the current group size |
| Images unavailable | Public metadata may be absent or ambiguous; imported legacy artwork is not supported; readable fallback remains |
| Source offline/revoked | Check the source's reachability and Connected apps grant/key, then refresh or reconnect |
| Old UI after an update | Leave/reload/relaunch Discord so it fetches the versioned frontend assets |
| Bot looks offline | HTTP notification delivery and Activity identity do not require persistent Gateway presence |

For operators, read the [installation guide](../lifecycle/install.md) and
[runtime troubleshooting](../troubleshooting/index.md). Discord's official
[Activity guide](https://docs.discord.com/developers/activities/overview) describes
current app visibility/testing requirements; launch availability depends on your
Discord application settings as well as the installed plugin.

See the [implementation and acceptance matrix](../architecture/discord-game-night.md) for the repository boundaries, current issue coverage and remaining release checks.
