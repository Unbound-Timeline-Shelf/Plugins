# Separate publisher identities and signing configuration

Official is a reviewed publisher channel, not a synonym for a valid signature.
The host shows Official only after verification of a v2 package using a registered
`channel: official` key scoped to its plugin ID. Existing example signing keys
are `channel: demo`, including keys whose historical publisher text says Official.
Unknown keys, invalid signatures and unsigned packages never receive that badge.
Invalid signatures are blocked; unsigned/unknown keys require explicit consent.
Official status does not bypass permissions.

The successor identities registered in this repository are:

| Key ID | Channel | Plugin ID scope |
| --- | --- | --- |
| `unnamed-tracking-examples-2026-10-07-v2` | demo | `example.` |
| `unnamed-tracking-official-2026-10-07-v2` | official | `official.` plus exact `example.self-service-session-manager` |
| `unnamed-tracking-generic-2026-10-07-v2` | community | `example.`, `plugin.` |

Existing keys have an exclusive `not_after` of `2026-10-07T16:00:00Z`: midnight
at the start of October 8 in Australia/Perth. The builder refuses an expired
signer. The verifier accepts expired-key packages only when their complete
archive SHA-256 appears in the key's reviewed `historical_package_sha256` list.
All 51 existing signed archives are pinned; the two unsigned historical archives
remain unchanged and untrusted. Signatures, scope and v1 manifest binding remain
mandatory. A claimed build timestamp cannot bypass expiry, and revocation
overrides historical exceptions.

`not_before` and `not_after` must be timezone-aware ISO timestamps with a valid
interval. `plugin_ids` grants exact IDs alongside existing prefix scopes; the
official session manager exception does not grant the entire example namespace.
The host currently ignores these policy fields and does not yet trust the new
public keys. [Host issue #7](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/issues/7)
requests that implementation and deployment. This repository's checks do not
claim expiry is enforced by an unchanged host.

Adding Actions secrets alone does not register a publisher. The builder registry,
matching public key file and deployed host registry must contain the same public
identity. Existing historical registrations remain intact. The generic identity
can sign examples when their folder-specific pair is entirely missing; these
packages retain community trust rather than acquiring demo/official trust.
It cannot sign official plugins. Official fallback requires another registered
official identity scoped to the plugin; missing official keys fail publication.
Invalid configured keys are never silently replaced, even if fallback is enabled.
All three display publishers match the existing `release.json` value,
`Unnamed Tracking Official`. Display text does not confer official status: the
reviewed channel and scope determine that status, and publication checks the
declared display publisher against the registered identity.

Do not generate a self-trusted identity for each release or commit private seeds.
New public keys require explicit registration and deployment before hosts trust
them. Development jobs already produce unsigned previews without new identities;
production jobs preserve the previous published catalogue if signing fails.

Set these GitHub Actions secrets (or builder environment variables):

| Key | Purpose |
| --- | --- |
| `PLUGIN_EXAMPLES_SIGNING_KEY_ID` | Registered demo key for `examples/` |
| `PLUGIN_EXAMPLES_SIGNING_KEY_B64` | Base64 raw 32-byte Ed25519 private seed for that key |
| `PLUGIN_OFFICIAL_SIGNING_KEY_ID` | New reviewed official key for `official/` |
| `PLUGIN_OFFICIAL_SIGNING_KEY_B64` | Protected private seed for the official key |
| `PLUGIN_SIGNING_KEY_ID` | Optional generic/legacy fallback identity |
| `PLUGIN_SIGNING_KEY_B64` | Private seed for the generic identity |

Set repository variable `PLUGIN_SIGNING_FALLBACK` to `generic`, `unsigned` or
`error` (default `generic`). Folder pairs take precedence. A partial/malformed,
unregistered, revoked or incorrectly scoped configured key fails without falling
back. `unsigned` permits missing keys only for preview builds. Signed publication
always requires a valid key for every new package. A generic demo key cannot sign
an official source, and an official key cannot sign examples. Generic sources
may live in `plugins/`. Existing published packages can be reused without access
to their retired private keys.

Register **only public material** in `publishers/registry.json` and its companion
`.public-key.b64`. Independently review/deploy the same official key, channel,
scope and SHA-256 in the host's `trusted_publishers.json`, or a reviewed registry
selected with host environment `PLUGIN_TRUSTED_PUBLISHER_REGISTRY`. The host
does not need private signing environment variables. Never commit a private key,
including a supposedly temporary expiring key. A disclosed seed permits
impersonation until every verifier has revoked it.

No production official identity is invented by development. Until its public key
is reviewed and private secret provisioned, `python tools/build_packages.py`
produces an unsigned development PWA in `.validation/`; it is not published as
an official signed release. `--publish` fails atomically when official signing is
missing. This prevents a demo key or unsigned package silently replacing an
official release.

New signatures use `v2:` followed by Ed25519 signature base64. The signature
covers `plugin-package-v2:<payload-sha256>`. The payload includes
`package-signature-v2.json` containing the complete manifest without integrity
and the signer key ID. Verifiers compare this signed manifest with the outer
manifest, preventing changes to permissions, ID, version or PWA declarations.
Historical v1 packages remain readable without rewriting immutable archives.
Their exact manifest hashes are pinned against payload hashes in both reviewed
registries (`legacy_manifest_hashes`); changing permissions, identity or version
invalidates the review. Newly signed packages require v2. A deployed registry
rejects an unpinned v1 package, and v1 signatures cannot establish official status
or publish a PWA contribution.
