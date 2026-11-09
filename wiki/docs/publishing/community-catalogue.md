# Publish your own community catalogue

You do not need official repository membership. This tutorial publishes the
Library Summary plugin from your own repository using the existing `.utp`,
signing registry and catalogue v1 generator.

**Goal:** publish a signed independent package and an HTTPS catalogue consumed
by Plugin Manager. **Prerequisites:** complete Library Summary, a namespace and
hosting account you control, Python/Git, a reviewed Ed25519 signing identity and
a disposable host for consent/update tests. The steps below preserve the existing
package/signature/catalogue contract.

## 1. Prepare an independent source set

Start from your own fork/check-out of these tools. Keep `sdk/`, `tools/`, exported
schemas, tests and docs. Replace the official `examples/` source set with your
own complete plugins. Follow [Create your first plugin](../getting-started/first-plugin.md)
and replace `org.example.library-summary` with a namespace you control.

Official historic packages belong to the official distribution; in a **new**
independent repository start with empty generated output/history rather than
copying unrelated official releases. This is not permission to remove history
from an existing published repository. Keep your own published packages forever
at their advertised versioned URLs.

Create `catalogue.json`:

```json
{"name": "Example Community Plugins", "base_url": "https://plugins.example.org"}
```

The generator advertises `https://plugins.example.org/dist/<plugin-id>-<version>.utp`.
Your catalogue endpoint is `https://plugins.example.org/list.json`. GitHub raw
hosting works too: use your own repository's `.../main` base and retain immutable
filenames/bytes as commits advance. HTTPS URLs must be absolute with no credentials,
query or fragment.

## 2. Register your publisher's public key

Generate an Ed25519 key pair in your secure signing environment, outside Git.
Create `publishers/community.public-key.b64` containing only base64-encoded
32-byte public bytes. Replace the official registry in your new repository with
your reviewed identity:

```json
{
  "schema_version": 1,
  "publishers": [{
    "key_id": "community-2026",
    "publisher": "Example Community",
    "public_key_file": "community.public-key.b64",
    "public_key_b64": "REPLACE_WITH_BASE64_PUBLIC_KEY",
    "public_key_sha256": "REPLACE_WITH_SHA256_OF_RAW_PUBLIC_BYTES",
    "status": "active",
    "plugin_id_prefixes": ["org.example."]
  }]
}
```

These placeholders are deliberately not a fabricated key. Calculate the public
hash from the decoded public bytes (not the base64 text). Set `release.json`'s
publisher to the exact reviewed label. Register your real namespace prefixes.
Keep the private 32-byte seed only in your secure CI secret store; supply its
base64 encoding as `PLUGIN_SIGNING_KEY_B64` and the key ID separately.

## 3. Generate and verify the catalogue JSON

Commit the independent sources, tools, configuration and public registry. Run a
preview and all tests, then publish through the existing signed command:

```sh
python tools/build_packages.py
python tools/distribution.py --root .validation --check-source --include-unreleased
python tools/build_packages.py --require-signing
python tools/distribution.py --check-source
python tools/verify_packages.py dist/*.utp
python tools/validate_packages.py dist/*.utp
```

The **actual `list.json`** has `{version: 1, name, plugins: [...]}`. Each current
entry includes the exact manifest, URL, payload `sha256`, complete `package_sha256`,
signing identity, permissions, README, notes, resolved update policy and complete
ordered `releases`. `releases/<plugin-id>.json` records the same exact history
without hosting-specific URLs. Do not hand-copy partial entry JSON; use the
[catalogue specification](../catalogue-specification.md) and generated snapshot.
The tests build a real independent `org.community.*` package/catalogue with a
disposable test publisher and verify both hashes and immutable history.

## 4. Host immutable bytes before updating the list

Upload every versioned `.utp` and history first. Serve JSON as UTF-8
`application/json`, packages as binary downloads, and revalidate the mutable
list. Retain all old URLs. Download an uploaded package and compare its complete
SHA-256 against that release's `package_sha256`; also run signature/payload
verification. Only then atomically replace `list.json`.

GitHub users commit/push the generated package, history, list and resolved source
versions together. GitHub Releases can distribute those same artifacts. Do not
advertise packages before their URLs resolve or overwrite an older version.
The current host limits catalogue JSON to 4 MiB; generation enforces this.
`list.json` embeds one full record per plugin plus a compact summary per version
and links the complete `releases/<plugin-id>.json` history.
Split very large collections into separate catalogues without deleting history.

## 5. Register the catalogue and review trust separately

On a disposable host, open **Settings → Plugins**, use catalogue management to
add your HTTPS `list.json` endpoint and enable it. The actual administrative API
is `POST /api/plugins/catalogues` with `{name, url}`. Refresh/browse that source,
preview your package and review the advertised identity, version, digests and
permission rationales against the actual package.

Register the reviewed publisher public key independently in the host deployment's
trusted publisher registry. Catalogue registration alone grants **no trust and no
permissions**. An unknown/unsigned package remains unverified; elevated grants
still require the host's consent/reauthentication policy. Test denial as well as
approval, enable/start, new-version preview, changed scopes and rollback.

An aggregator can list packages from multiple authors if it derives all fields
from verified immutable packages and retains their exact release records. This
repository's generator builds local sources with one configured base URL; it is
not a remote aggregation service. Never fabricate author signatures or assign
your own permission risk classifications.

## Test command

```sh
python -m pytest tests/test_community_catalogue.py
python tools/distribution.py --check-source
```

Run the second command in your independent repository after signed publication.
The test builds an actual independent signed package with a disposable identity.

## Expected result

Your generated list advertises immutable package URLs with exact manifests,
archive/payload hashes, signing identity and release history. The host can browse
the enabled endpoint, then independently review publisher trust and permissions.

## Common mistakes

Copying unrelated official history into a new catalogue; hashing base64 text
rather than raw public bytes; advertising a URL before its package exists;
overwriting old archives; hand-editing generated entries; assuming registering
the endpoint also trusts its publishers or approves permissions.
