# PWA assets

These existing assets are the foundation of the maintained `official.pwa` plugin.
PWA integration version is recorded in `version.json`;
native Android, Android WebView and Windows/WinUI versions are independent.

The host owns `/service-worker.js`, `/manifest.webmanifest`, and public `/pwa/`
routes. The plugin contributes validated install metadata and bounded PNG icons
through explicit `frontend.pwa` permission. A worker located under a plugin URL
does not automatically control `/`; do not deploy these files by copying them
into the host's public root. `service-worker.js` is a reviewed host template,
prefixed with host-derived enablement and installation generation metadata.
Without that metadata it fails safely by retiring its own registration.

The PWA exposes the complete existing application, with its normal sessions and
login/SSO. It stores no passwords or private offline data. Only a neutral waiting
for internet HTML page and up to 32 immutable public theme assets are cached.
The asset exception accepts only digest-addressed CSS, images and fonts under
`/api/themes/assets/`; it rejects HTML, query strings and document navigations.
Private APIs, authentication and other non-navigation requests pass through. Offline
content has no time expiry. Version changes replace the owned cache; removal or
disablement is observed on the next online contact, leaving other caches intact.

The offline page follows Light, Dark or System and the device's last selected
Orange, Green or custom palette. The `ui-appearance` localStorage record contains
only a version, mode, palette ID, public hex color roles and a contrast flag.
It contains no account identifier, credentials, widgets or API data. Invalid or
unavailable storage falls back to the default palette and system mode. Browser
theme-color bars follow the page background; install metadata remains public
and does not contain personal settings. Account preferences take precedence
when the complete application reconnects, unless this browser explicitly selects
device appearance. The selected public theme ID and digest-addressed stylesheet
URL are cosmetic localStorage entries, allowing the neutral offline page to use
an installed theme. A successfully loaded theme controls its colors without
native palette overrides; if its CSS is unavailable offline, the retained
personal palette remains usable. They contain no account data. Removal retires the worker and
clears its owned HTML and theme caches, including in-flight asset writes.

From the plugin repository run `python tools/sync_pwa.py --mobile-root PATH
--host-root PATH` and repeat with `--check` to verify source hashes/version and
host infrastructure. Increment the explicit `0.0.x` patch in both source and
plugin metadata for a changed release. Never automatically promote to 1.0.0.
Official releases require separately provisioned protected signing keys; unsigned
previews are visibly unverified. The PWA ZIP in the existing mobile release
workflow remains a source asset bundle, not another native client.

Run `node --test pwa/tests/*.test.mjs`. Real host/plugin lifecycle
and browser acceptance lives in the [host lifecycle tool](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/blob/main/tools/check_pwa_lifecycle.py).
