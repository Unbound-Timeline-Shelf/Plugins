# Package signing and publisher identity

New packages use Ed25519 over ASCII `plugin-package-v2:<canonical-payload-sha256>`.
The sorted path/NUL/bytes/NUL digest includes `package-signature-v2.json`, which
binds the complete manifest without integrity and the signing key ID. The outer
signature is prefixed `v2:`. Verification compares the signed and outer manifests.
The entire final archive has a separate SHA-256; do not conflate these digests.

Historical v1 archives are immutable. They use `plugin-package-v1:<sha256>` and
require an exact reviewed manifest hash in `legacy_manifest_hashes` (payload hash
to a list of approved manifest hashes). They cannot establish Official status.
New official PWA contributions require v2. This closes the legacy manifest
substitution gap while retaining authentic historical packages.

Publisher channels are reviewed `official`, `demo`, or `community`. Official
signing is a separate identity from demo/example signing and grants no extra
permissions. Set folder-specific `PLUGIN_OFFICIAL_SIGNING_KEY_ID/KEY_B64` and
`PLUGIN_EXAMPLES_SIGNING_KEY_ID/KEY_B64`; generic sources and optional fallback
use `PLUGIN_SIGNING_KEY_ID/KEY_B64`. `PLUGIN_SIGNING_FALLBACK` selects `generic`,
`unsigned` or `error`. Missing keys may yield unsigned previews, never unsigned
official publication. Configured invalid keys fail without silent fallback.

`publishers/registry.json` records reviewed public keys, key IDs, public-key hashes,
publisher labels, status and allowed plugin-ID prefixes. New publication requires
an **active** matching signer covering the source set. Retiring keys can verify
historical packages; revoked keys cannot produce or establish trusted releases.
Private seeds never belong in Git, documentation or package payloads.

The repository's signing registry and the host's trusted publisher registry are
separate. Review and register a publisher's key independently in the deployment.
An unknown signature is not trusted just because a catalogue advertises it.
Unsigned development packages remain explicitly untrusted and use the host's
consent path.

The October 7 rotation uses three independent successor identities. Existing
keys expire at `2026-10-07T16:00:00Z`, the end of October 7 in Australia/Perth.
New publication requires the signer to be inside its timezone-aware validity
window. After expiry, only exact already-published archive SHA-256 pins can
verify; signature, scope and v1 manifest-binding checks still apply. Backdating
package metadata does not create a historical exception. Revoked keys are always
rejected, even for pinned archives. Historical packages are never re-signed.

The official successor additionally grants the exact stable ID
`example.self-service-session-manager` for **Extended Session Manager**.
Lookalike IDs and the remaining example namespace are excluded. Host enforcement
and new public-key deployment are requested in
[host issue #7](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/issues/7).
An unchanged host does not enforce these new policy fields.

Follow the [independent catalogue tutorial](../publishing/community-catalogue.md)
to register your own identity and build a signed package using the same tools.

## Generate an independent key in your secure signing environment

Use an access-controlled directory outside your source checkout. For an
independent publisher, set `PLUGIN_KEY_DIRECTORY` to that directory and run:

```python
import base64
import hashlib
import os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

directory = Path(os.environ["PLUGIN_KEY_DIRECTORY"])
key = Ed25519PrivateKey.generate()
private = directory / "publisher.private-seed.b64"
descriptor = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="ascii") as stream:
    stream.write(base64.b64encode(key.private_bytes_raw()).decode("ascii"))
public = key.public_key().public_bytes_raw()
with (directory / "publisher.public-key.b64").open("x", encoding="ascii") as stream:
    stream.write(base64.b64encode(public).decode("ascii"))
print("Public key SHA-256:", hashlib.sha256(public).hexdigest())
```

The script refuses to overwrite a private seed and prints only a public hash.
Restrict the directory's Windows ACLs or POSIX permissions before running it.
Import the private file into the secure CI secret `PLUGIN_SIGNING_KEY_B64` and
set `PLUGIN_SIGNING_KEY_ID` to your reviewed registry ID. Only the public file
and public registry record belong in Git. Never run this to replace the official
repository's signing identity.

With your public registry configured, use the existing signed builder and verify:

```sh
python tools/build_packages.py --require-signing
python tools/distribution.py --check-source
```

Expected result: a verified signature under your active scoped identity and exact
archive/payload hashes. A missing key, mismatched publisher label or out-of-scope
plugin ID must fail. [Community publication](../publishing/community-catalogue.md)
explains registration and HTTPS hosting; signing never bypasses host consent.
