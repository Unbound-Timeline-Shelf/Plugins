# Epic Games Library

Optional personal Epic game imports through **Plugin API 1.1.19**. Requires a host
that implements `games.import` with artwork addresses, connection sync actions and
personal scheduled tasks. Older hosts reject this package during compatibility review;
use an earlier Epic release on a host that predates 1.1.19. This plugin uses the existing SDK v1.1.1 wire helper.
The host page/sign-in support is completed by
[host PR40](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/pull/40).

## Experimental service dependency

Epic does not publish or support an API for third-party library imports, and
this plugin is not affiliated with or endorsed by Epic Games. It does not use
Epic Online Services or Epic Account Services, and Unnamed Tracking App has no
Epic-issued OAuth client. Instead, the plugin signs in the same way the Epic
Games Launcher does: Epic's own sign-in page returns a one-time authorization
code for the launcher's public client, and the plugin exchanges that code for
launcher access/refresh tokens. It then reads the same unofficial account,
library, playtime and catalogue services the launcher uses.

Those services are undocumented and Epic can change, rate-limit or withdraw them
at any time. Treat the integration as experimental: an Epic-side change can stop
sign-in, imports or playtime until a new plugin release adapts to it. Epic
support cannot help with this plugin; report problems to this repository instead
(see [Troubleshooting and support](#troubleshooting-and-support)).

An Epic service failure is not host data loss. Failed sign-ins, refreshes,
inventory pages, playtime or catalogue lookups stop the current step and keep
your saved connection, checkpoint and library. The plugin never deletes games.
Disconnecting removes only this plugin's saved tokens and checkpoint for your
account; imported games, notes, ratings, status and playtime stay in the host.

## Imported fields

Each Epic game is imported with its title and its Epic identity (catalogue
namespace and item ID, scoped to the connected account). When Epic's catalogue
supplies them, the description, developer and publisher are imported too. Total
playtime is imported when Epic's playtime service answers. Catalogue text is
requested in US English.

Artwork is sent as addresses only; the host downloads, checks and resizes the
pictures itself and fills only pictures the game does not already have, so an
upload of yours or earlier artwork is never replaced. The plugin picks the best
catalogue `keyImages` entry for each field (preferred type first, then the larger
picture):

| Host field | Epic image types, best first |
| --- | --- |
| `key_art_url` | `DieselGameBoxTall`, `OfferImageTall`, `DieselStoreFrontTall` |
| `banner_url` | `DieselGameBox`, `DieselStoreFrontWide`, `OfferImageWide` |
| `logo_url` | `DieselGameBoxLogo`, `ProductLogo` |
| `icon_url` | `Thumbnail` |

Each address is checked before it is sent, using the host's rules (at most 2048
characters, `http`/`https` on port 80 or 443, no credentials, fragment or
control characters, public host only). An address that fails is dropped and the
game is still imported without that picture. If the host cannot download a
picture it reports it and the import continues; the Epic page counts these as
`artwork_failed` and the next sync offers the address again. Games that are
unavailable never send artwork.

Not imported: release dates (Epic's catalogue exposes only listing and record
timestamps such as `creationDate`, which are not the game's release date, so
sending them would overwrite correct dates), genres/tags, achievements, prices,
DLC/add-ons, ratings badges and install state. Use the host's metadata lookup for
those. The import sends only the fields the host's `games.import` contract
accepts (Plugin API 1.1.19); a test pins this so a future field cannot be added
without a host contract change. Checkpoints saved before artwork support still
resume and import normally; artwork is added on the next sync.

## Connect and import

Install this plugin's `.utp` through Settings → Plugins, approve the declared
permissions and enable it. Open Settings → Account → Connections, where **Epic Games**
is listed with its connection status. Choose **Connect** (or **Manage** once
connected) to open the plugin page in a popup. The page is also reachable at its
plugin route, but it no longer adds a sidebar entry.
The popup uses the host's appearance and spacing, with an account summary and
import controls. Expand **Use your regular browser**, then use **Copy sign-in link** to open Epic in your regular browser while leaving the
app open. If clipboard access is unavailable, copy the selected link manually.
Alternatively, use **Sign in on Epic Games**. The action is declared as external navigation, so
the host validates Epic's returned HTTPS destination and opens it in a new tab,
leaving this popup open; the sandboxed plugin does not open a popup itself.
After signing in, Epic shows a page of text. Select all of it, copy it and paste
it into the code field: pasting the whole page connects without another click.
The one-time authorization code, its JSON page, a single copied JSON line or the
redirect URL are all accepted. Hosts that predate new-tab handling, or a browser
that blocks the tab, navigate the host tab instead; then use browser Back and
reopen **Connections → Epic Games**. No popup permission is needed. Your
password stays on Epic's site. The code is cleared immediately after submission
and is never saved in settings.

If Epic later rejects the saved sign-in (for example after a password change),
the popup shows the code field again. **Replace sign-in** does the same at any
time. The existing connection stays until Epic accepts the new code; an
accepted replacement then starts a fresh import checkpoint, and games already
imported stay in your library.

Launcher access/refresh tokens are validated independently from the 32-character
account ID and bounded to 8 KiB. Hosts must support authorization headers larger
than the original 2 KiB limit; older hosts need the companion token-header fix
before an import can use these tokens. Failed replacement sign-ins retain an
existing connection and never show token values in errors.

Positive, finite access-token lifetimes from Epic are accepted, including lifetimes
longer than one day. The plugin schedules refresh at the shorter of that lifetime
and one day, so a longer provider lifetime does not delay local token rotation.
Malformed expiry values retain an existing connection.

Choose **Import games**. Inventory paging, playtime, catalogue lookup and host
imports run as separate bounded steps. **Pause after this step**, closing the
page or a failed request retains the checkpoint. **Resume import** continues it.
**Start new inventory** deliberately replaces the current checkpoint. Disconnect
removes this user's saved tokens/checkpoint and keeps imported games.

The popup follows Steam's host dialog sizing and shared appearance. Disconnected
accounts show sign-in controls; import controls appear after connecting.
On Games, **Sync / import → Sync Epic Games** starts or resumes the same
import flow. The menu does not add a second connection page.

For automatic imports, open **Account → Background tasks → Epic Games autosync**.
Approve the declared `tasks.background` access and enable your own schedule; it
starts off and normally runs daily. Intervals can range from 5 minutes to 1 week.
Each run advances one bounded checkpoint; incomplete work requests the next step
after 60 seconds, even with the page closed. Completion restores your chosen interval.
Disabling autosync stops queued steps. Manual and automatic imports share the same
per-user lease, tokens, checkpoint and preservation rules; another user's schedule
cannot adopt your Epic account or change your library.

Games use namespace + catalogue identity within the connected account. Similar
titles and another Epic account cannot adopt each other's games. Engine assets,
private sandboxes, DLC and digital extras are skipped. Catalogue requests group
up to 25 entries in one namespace. An entry Epic omits (for example a delisted
item) is skipped individually: it is counted in `skipped`/`catalogue_missing`, listed
in `skipped_entries` (first 25 shown) and later games continue. Transport failures or
an unreadable catalogue response still stop the step and retain the batch for retry. A repeated/invalid cursor, invalid record, incomplete page or safety
limit stops inventory before availability changes.

Successful imports respect the host's field locks, manual status, notes and
ratings. Playtime only increases; absent/unavailable playtime leaves known values
alone. When multiple launcher artifacts share a catalogue identity, the largest
reported artifact total is used to avoid counting duplicate platform entries.
Only a complete valid inventory can mark previously imported games unavailable.

## Troubleshooting and support

Messages come from the plugin and never include token values. Most Epic-side
failures are recovered by waiting and choosing **Resume import**.

| Message or symptom | What it means and what to do |
| --- | --- |
| "Paste the 32-character authorization code, its JSON page or redirect URL." | The pasted text did not contain exactly one code. Choose **Sign in on Epic Games** (or **Copy sign-in link**) again and paste the whole page Epic shows. Each code works once. |
| "Epic rejected this sign-in. Sign in on Epic again and paste a fresh code." | Epic no longer accepts the saved sign-in (for example after a password change), or rejected the pasted code. Choose **Replace sign-in** and paste a fresh code. If this happens during autosync, the schedule turns itself off; re-enable it in **Account → Background tasks** after reconnecting. |
| "Epic returned a different account. Reconnect before importing." | A token refresh answered for another Epic account. Use **Replace sign-in** with the account you intend to import. As above, re-enable autosync afterwards if it turned off. |
| "Epic is busy. Wait a minute, then resume the import." | Epic rate-limited the request. Wait, then **Resume import**. Autosync retries on its own after at least five minutes. |
| "Epic could not be reached or refused the request. Your saved import is retained." | Epic's service was unavailable or answered with an error. Resume later; the checkpoint is kept. |
| "Epic returned an incomplete inventory…", "…invalid inventory paging information", "…repeated an inventory cursor", "…omitted catalogue entries", "…omitted a game title" or "…unreadable game categories" | Epic's reply did not match what the plugin expects. Nothing is marked unavailable from a partial inventory. Resume later; if it persists across days it is probably an Epic-side change, so report it. |
| "Epic playtime was unavailable. Existing playtime was retained." | Games still import; known playtime is not lowered or cleared. A later import fills playtime when Epic answers again. |
| "Another Epic action is running. Wait briefly, then resume." | Two Epic actions for your account overlapped, for example a manual import and autosync. Wait about a minute and resume. |
| "Start a new import for this connected account." | The saved checkpoint belongs to an earlier connection. Choose **Start new inventory**. |
| "Epic's inventory exceeded the safety limit. Availability has not changed." | The library exceeded 10,000 entries or 200 inventory pages. Report it. |
| "The host denied or could not complete this action. Check plugin permissions, then retry." | A host-side refusal, not an Epic failure. In **Settings → Plugins**, check that the plugin is enabled and its permissions are approved. |
| **Local conflicts** count increases | A game you deleted in the app, or one whose identity changed, is left alone instead of being recreated. |

Only a complete, valid inventory marks games that left your Epic library as
unavailable. They are not deleted, and they become available again when a later
import lists them.

Report persistent Epic sign-in or import failures as an
[issue in this repository](https://github.com/Unbound-Timeline-Shelf/Plugins/issues),
not to Epic or the host application. Include the plugin version (shown in
**Settings → Plugins**), the host release or image tag you deployed and the exact
message. Never include the authorization code, the text of Epic's sign-in page,
the redirect URL, tokens or your Epic account ID. Installation, permission and Connections-page problems that
are not specific to Epic belong to the host's plugin documentation.
