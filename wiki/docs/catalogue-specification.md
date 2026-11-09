# Plugin catalogue v1 distribution specification

This is an additive specification for the repository's existing `list.json`
format. It keeps `version: 1`, the existing `plugins` array and the v1 `.utp`
format. It is usable by independent catalogue publishers; an official repository
membership is not required. See the [author guide](plugin-author-guide.md) for
runtime, manifest, package and signing details.

## Current host consumption

The current host on `main` consumes the following contract. The frozen
manifest/UI schema revision is `f1165fcc805e57ee428e7bc42fa6b83f4a6caf25`; CI
also checks the current host rather than treating that older snapshot as
the current implementation.

* Administrators configure catalogue endpoints; catalogues are independent of
  publisher signing trust. The official endpoint is one source among configured
  lists. Adding an endpoint does not grant code execution or approve scopes.
* The host downloads a version-1 JSON object and reads current plugin entries.
  Its public model uses `plugin_id`, `name`, `description`, `version`, `url`,
  `release_notes`, optional `changelog_url`, dependencies, tags, README, publisher,
  permission declarations, hashes, release policy and build/package metadata.
* Install/preview downloads the package, validates its manifest/digest/signature,
  assesses compatibility, dependencies and host-defined permission risks, and
  checks the catalogue's identity/version and payload/archive hashes, and requires
  the appropriate approval. `expected_digest` on the current install URL
  API refers to the canonical **payload** SHA-256, not the complete ZIP hash.
* The manager filters tags, renders sanitized packaged README, discovers newer
  catalogue versions and stages updates. Automatic activation requires host policy,
  trusted signatures, satisfied dependencies, no newly requested scopes and release
  policy permitting it. A false policy in the signed `distribution.json` payload
  also blocks automatic activation. Later releases can opt in independently.
* `releases` lists every published version as a compact summary (see below).
  The host offers those versions in its version picker and binds a catalogue
  install of a non-current version to that list. Update discovery uses only the
  current entry, and the rollback UI uses the host's retained local packages; the
  catalogue does not grant execution, permissions or automatic selection of
  historical versions.

## Authoritative fields

The top-level object has `version: 1`, a catalogue display `name`, and `plugins`.
Each current entry retains the original required fields and adds metadata derived
from the actual latest package. Strings are UTF-8. Versions use strict stable
SemVer. Plugin identity is stable across releases, unique within a list and
publisher-namespaced; do not silently replace an ID with unrelated code.

| Entry field | Meaning |
| --- | --- |
| `plugin_id`, `name`, `description`, `version` | Exact current package manifest values |
| `url` | Absolute HTTPS URL to the immutable complete `.utp` package |
| `manifest` | Exact embedded manifest, including generated integrity |
| `sha256` | Canonical payload SHA-256; equals `manifest.integrity.sha256` |
| `package_sha256` | SHA-256 of the entire final `.utp` byte stream |
| `package` | Filename `<plugin-id>-<version>.utp`, `size_bytes`, `format: "utp-v1"` |
| `signing` | Exact manifest integrity `{sha256, signature, key_id}`; null signature/key for unsigned packages |
| `publisher` | Registered signing identity for signed releases; declared author label for unsigned new builds, not a trust claim |
| `sdk_version_range`, `application_version_range` | Exact manifest compatibility constraints |
| `capabilities` | Exact requested capability names and semantic versions |
| `permissions` | Exact requested references and rationales; no plugin-provided risk classification |
| `dependencies` | Exact manifest plugin dependencies/ranges/optional flags |
| `tags` | Package-provided lowercase category slugs; host owns filtering UI |
| `readme` | Exact UTF-8 text from packaged `README.md` |
| `icon` | Null or packaged relative `path` plus content `sha256` |
| `documentation` | Markdown format, README path and whether documentation was packaged |
| `release_notes` | Package-provided release text (up to 4000 characters) |
| `automatic_update` | Resolved boolean for **this release**, not a global plugin preference |
| `lifecycle`, `lifecycle_stages` | Built preview or published snapshot; recorded distribution stages |
| `build` | Source digest/commit/path/time, builder, contract revision, version-bump reason and legacy flag |
| `source` | Current authoring directory, source stage and manifest schema version |
| `releases` | Every distributed version as a compact summary, ending with the current release |
| `release_history` | Link to the complete history file: `path`, absolute `url`, record `count` and file `sha256` |

`releases` is ordered by numeric SemVer, oldest first, with unique versions, and
its last element is the current release. Each element is a summary with exactly
`version`, `url`, `sha256`, `package_sha256`, `automatic_update` and
`release_notes` (`CATALOGUE_RELEASE_FIELDS` in `tools/distribution.py`): what a
host needs to list a version and bind a catalogue install to its package hashes.
The full release record (identity, manifest, package/signing/publisher
information, README/icon/tags, lifecycle and build provenance) is the entry
itself for the current release and is in the history file for every release.
Current entry values mirror the final release, not the authoring manifest's
placeholder digest. A release-level manifest contains its compatibility,
capabilities, permissions and dependencies; never use today's
permissions/compatibility for an old release. Read it from the history file.

Standalone `releases/<plugin-id>.json` has `{version: 1, plugin_id, releases}` with
the same records excluding deployment-specific URLs. These files are the complete,
append-only history and retain histories for retired plugins too; consumers do
not need to reverse-engineer GitHub commit history. A record's package URL is
`<base_url>/dist/<package.filename>`, the same location pattern as the entry's
`url`. Each current catalogue entry links its file through `release_history`,
whose `sha256` covers the exact published file bytes, so a client that wants
older versions makes one extra, verifiable fetch.

### Lean index

Older catalogues embedded the full record for every historical release in every
entry. Each record repeats its manifest and README, so the official `list.json`
grew by tens of kilobytes per release until it approached the host's download
bound. The catalogue now embeds one full record per plugin (the current entry)
plus a summary of well under 1 KB per version. Packages stay published,
immutable and downloadable at their URLs.

Hosts released before this change keep working without the removed fields:
their catalogue model reads only the summary fields from each release and
ignores the additive `release_history` field. They discover updates from the
current entry, build their version picker from `releases`, install any listed
historical version (bound to its summary's hashes), and roll back from locally
retained packages. The host bounds `releases` to 256 versions per plugin.

The checked-in list and release files are executable examples of this complete
shape. Generate them with the tools rather than transcribing a partial JSON
example and accidentally omitting hashes or release snapshots.

The current host limits decoded catalogue JSON to **4 MiB**. Generation validates
that limit before publication; do not raise it in the generator. For a very large
collection, distribute plugin groups through separate configured catalogues.
Never delete or rewrite history files to meet the cap: CI's baseline check
requires every release that the previous `list.json` advertised, whether as a
full record (older catalogues) or as a summary, to remain unchanged in
`releases/<plugin-id>.json`, and every existing history file to keep its prefix.

## Integrity and historical compatibility

Compute archive hashes only after signing/writing the final ZIP. The payload hash
uses the unchanged v1 sorted `path + NUL + bytes + NUL` stream, excluding the
outer manifest. New Ed25519 signatures use `plugin-package-v2:<payload-sha256>`;
the payload contains a verified manifest envelope and the signature has a `v2:`
prefix. Historical v1 manifests require reviewed pins. The entire package hash
additionally binds the manifest and ZIP bytes. Hashes have distinct
meanings; do not pass `package_sha256` to a host API expecting the payload digest.
Publisher labels and a catalogue URL alone never establish signing trust.

The generator verifies every package against its release record, current fields
against the latest release, URLs against configured hosting, and new payloads
against current source. Never re-sign, replace, remove or silently reuse a version
with different bytes. Key rotation, permissions, README, tags and release policy
changes can create a new package and must use a new version. Retain the old
records and package URLs.

Existing artifacts predating these metadata fields are imported without changing
their bytes or inventing old author intentions. They are `build.legacy: true`,
have absent README/icon and empty tags if those were never packaged, and use
`automatic_update: false` because historical automatic approval was not recorded.
Their original manifests/signatures/hashes remain authoritative. Original UI
defects remain historical too; newly generated packages must pass the full
current manifest/UI/handler validation. Do not advertise a legacy UI as fixed by
attaching a new manifest or today's README to the old package.

## Release-level automatic eligibility and update discovery

Publish every version separately. A disabled major release and permitted patch
are represented as two records, for example:

```text
releases[...]: version=2.0.0, automatic_update=false, its own URL/hashes/manifest
releases[...]: version=2.0.1, automatic_update=true,  its own URL/hashes/manifest
current entry: version=2.0.1, mirrors the second release
```

The false flag on 2.0.0 never permanently marks the plugin disabled for automatic
updates. A history-aware host has enough data to compare numeric versions and
actual digests with an installation, exclude incompatible/dependency-invalid or
untrusted packages, distinguish manual-only from automatic-eligible releases,
and show relevant notes/scopes before approval. It must use the candidate's policy
and manifest, not the flag from an earlier release or the latest entry when
considering a different historical version. It must still enforce its own grants,
automatic-update settings, breaking-change/major-crossing rules, consent,
dependency planning and health checks. `automatic_update: true` does not require
the host to install anything, and does not imply approval to cross any major
version boundary.

The current Plugin Manager consumes the current URL/version and release-specific
policy through its canonical installer and scheduled updater. Older consumers
may ignore these additive fields and must not infer automatic-install approval
from missing policy data. Catalogue history does not replace the host's
locally retained known-good rollback version or restore persistent plugin data.

## Maintaining your own catalogue

Follow the [complete community catalogue tutorial](publishing/community-catalogue.md)
for a step-by-step independent source set, reviewed publisher registry, signed
build, immutable HTTPS hosting and separate host catalogue/trust registration.

You can fork/reuse the builder, SDK helper and schemas with your own source set,
keys and repository. Configure a single `catalogue.json`, for example:

```json
{
  "name": "Example Community Plugins",
  "base_url": "https://raw.githubusercontent.com/your-account/your-plugins/main"
}
```

The generator uses `<base_url>/dist/<filename>` for package URLs. HTTPS URLs must
be absolute and contain no credentials, query or fragment. For GitHub raw hosting,
commit `/dist`, `/releases` and `list.json` together and configure the host endpoint
as `<base_url>/list.json`. For your own static server/object storage, retain the
same layout, upload every package and history first, verify the bytes at the
advertised URLs, then atomically replace `list.json`. Serve JSON as UTF-8
`application/json`, packages as binary downloads and use suitable cache
revalidation for the mutable list. Package URLs must remain immutable and
available. Never publish a current entry before its package can be downloaded.

Run:

```bash
python tools/build_packages.py                  # isolated preview
pytest
python tools/build_packages.py --require-signing
python tools/distribution.py --check-source
python tools/verify_packages.py dist/*.utp
python tools/validate_packages.py dist/*.utp
```

The signed command requires a real scoped registered signer. Adapt the existing
publish workflow's repository/ref/hosting configuration, keep full-history
checkout and all verification, and store private keys in CI secrets. A custom
catalogue may aggregate immutable packages from multiple authors rather than
building them locally; in that case produce the same fields from each verified
package, review identities/URLs and retain exact release records. The repository
generator itself builds local `examples/*` sources and uses one configured base
URL; it is not a remote aggregation service. Do not invent signatures for
third-party packages or classify their permission risk yourself.

Adding the catalogue URL in Plugin Manager is an administrator action. Configure
each publisher's reviewed verification key independently in the host trust store.
Test install preview, compatibility/permission changes, denial, activation and
rollback on a disposable host installation before declaring a package supported.
Current official integration tests validate the existing host model and disabled
installation; they do not certify a live third-party service or arbitrary future
host versions.
