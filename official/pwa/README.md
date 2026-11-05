# Unnamed Tracking PWA

The maintained official PWA integrates the mobile repository's PWA assets with
the complete Unnamed Tracking web application. The plugin release version and
the separately reviewed mobile asset version are recorded in
[`manifest.json`](manifest.json) and [`pwa/version.json`](pwa/version.json).
Stable 1.0.0 requires an explicit human release decision.

Install its `.utp` through Plugin Manager, review `frontend.pwa`, and enable it.
The permission publishes public install metadata and icons and enables the
host-owned root worker. It grants no account APIs, native JavaScript or arbitrary
host routes. Only one PWA provider may be enabled per server. The host refuses
conflicting providers rather than selecting one silently.

Use HTTPS (localhost works for development). Android Chrome and Windows
Chrome/Edge offer an install button when available. On iOS Safari, use Share →
Add to Home Screen. Installation requires browser support and is separate from
installing the server plugin. Native Android, WebView and Windows/WinUI clients
remain independent and unchanged.

The installed app opens the full website and uses its normal login/session/SSO.
Passwords are never saved by this plugin. Session expiry returns to normal login.
Offline navigation displays a neutral waiting-for-internet page, never account
data. Private API and authentication responses are never cached. A bounded
exception caches only immutable, digest-addressed public theme assets.
Reconnect restores normal navigation.

The full application, sign-in/SSO redirects and neutral offline page follow
Light, Dark or System and the last device palette, including Orange, Green and
custom colors. Only cosmetic color roles are cached locally; saved account
preferences take precedence online. Browser bars follow the current background.
The public signed installation manifest never contains personal appearance data.

Updates replace the host worker generation and remove only owned old caches.
The offline page has no time expiry. Disable, permission revocation or uninstall
withdraws the manifest/icons and retires the worker when the browser next reaches
the server. Offline devices cannot learn about a server-side removal immediately.
An installed shortcut remains an ordinary website shortcut, with plugin settings
guidance. Reinstallation gets a new installation/cache identity.

Assets are synchronized from [Mobile-Apps/pwa](https://github.com/Unbound-Timeline-Shelf/Mobile-Apps/tree/main/pwa) using
`tools/sync_pwa.py --mobile-root PATH --host-root PATH`; `--check` validates exact
provenance and a plugin release that does not precede its mobile asset version.
The host never executes a worker from an
untrusted package: reviewed worker/offline infrastructure is shipped by the host.
Metadata colors are typed for future theme support; no mobile UI redesign is
included.

Development previews may be unsigned and require explicit untrusted-package
consent. They do not receive the verified Official badge. Official publication
requires a separately registered official public key and protected signing secret.
See [signing configuration](../../docs/official-signing.md).
