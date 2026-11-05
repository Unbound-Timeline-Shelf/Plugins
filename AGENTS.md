# AGENTS.md

# Purpose

This repository contains **official Unnamed Tracking App plugins, Plugin API v1 examples, SDK/protocol helpers, tests, package-building tooling, publisher verification keys, and distributable `.utp` artifacts**.

It is a consumer of the application's public Plugin API.

It is **not** the plugin host.

The host application is responsible for:

* plugin lifecycle infrastructure;
* plugin runtime;
* permission enforcement;
* gateway implementation;
* plugin storage implementation;
* package installation;
* package verification;
* application/database internals;
* host UI infrastructure.

Plugins are responsible for application-level behavior built on top of those public capabilities.

Do not duplicate host infrastructure here.

---

# 1. Repository Structure

Maintained source is split by product purpose and signing identity:

```text
examples/<plugin-name>/  # complete reference/demo sources (demo signers)
official/<plugin-name>/  # maintained user-facing plugins (official signers)
plugins/<plugin-name>/   # independent sources (generic signers, optional)
reference-clients/<name>/  # packaged non-plugin consumers of public host contracts
sdk/                    # public Plugin API v1 protocol helper
wiki/docs/              # Material/MkDocs developer manual and dated history
tests/                  # source, package, browser and release contract tests
tools/                  # existing builder, validators and host conformance tools
publishers/             # reviewed public keys; never private keys
dist/                   # immutable installable .utp versions
releases/               # append-only generated release histories
catalogue.json          # authored catalogue hosting configuration
list.json               # generated catalogue
wiki/mkdocs.yml         # strict wiki navigation
```

`examples.old/` and README-only plugin directories are invalid. Discovery and CI
reject incomplete source rather than silently omitting it from publication.
UI/API is a focused reference; Discord Notifications is a maintained official provider. Playtime Report,
Recently Played Notifier, Metadata Curator and UI Playground are small useful
demos. Help Button, Jellyfin, Document Viewer and Session Manager demonstrate
more substantial host integrations. Keep this mixture; no duplicate source trees.

Historical lifecycle/events/advanced packages and their release records remain
immutable even though those old source stubs are retired. Never rewrite embedded
historical source paths merely because documentation or directories move.

Do not confuse the reference examples with foundational plugin infrastructure.

---

# 2. Core Plugin Architecture

The central architectural rule is:

> The application provides the platform; plugins provide behavior on top of the platform.

Plugin code must use the supported Plugin API v1 gateway.

For example:

```python
from sdk.plugin_protocol import request
```

is appropriate.

Importing application internals is not.

Do not use:

```python
from src.plugin_api import ...
from src.database import ...
from src.features import ...
```

Do not import test-only gateway fixtures such as:

```python
ValidationGateway
```

Plugins must remain independently understandable and testable.

A plugin repository checkout should not require the host application's source tree to import or understand a plugin.

---

# 3. Plugin Package Contract

Installable plugins use the `.utp` package format.

A plugin has a `manifest.json` declaring its public contract.

The v1 manifest includes concepts such as:

* `manifest_version`;
* `plugin_id`;
* `name`;
* `version`;
* `description`;
* `entrypoint`;
* `sdk_version_range`;
* `application_version_range`;
* capabilities;
* permissions;
* dependencies;
* UI contributions;
* storage quota;
* integrity information.

The normal entrypoint currently follows:

```text
plugin:main
```

Plugin IDs must be unique.

Use stable semantic versions:

```text
MAJOR.MINOR.PATCH
```

Do not change a plugin ID when making a normal update.

A new plugin should receive a new globally unique ID.

---

# 4. Manifest Rules

Every plugin must have a valid manifest.

When adding a plugin:

* choose a stable unique `plugin_id`;
* use a meaningful human-readable `name`;
* use semantic versioning;
* accurately declare the SDK compatibility range;
* accurately declare the application compatibility range;
* declare every capability actually used;
* request only the permissions actually required;
* provide a rationale for permissions;
* declare dependencies accurately;
* declare UI contributions accurately;
* declare storage requirements conservatively;
* provide valid integrity information.

Do not declare broad capabilities "just in case."

Do not request permissions that the plugin does not use.

Do not hide functionality from the manifest.

The manifest is part of the plugin's security and compatibility contract.

---

# 5. Capabilities and Permissions

A plugin must declare the capabilities it consumes.

The plugin should only invoke gateway methods corresponding to capabilities declared and granted to it.

For example, if a plugin uses:

```text
games.list
storage.put
lifecycle.ready
```

its manifest must provide the corresponding capability/permission declarations according to the v1 contract.

When adding a new capability:

1. confirm that the capability already exists in the host API;
2. if it does not, coordinate the API change with `unnamed_tracking_app`;
3. document the capability;
4. declare it in the manifest;
5. request the corresponding permission;
6. explain why the permission is needed;
7. add tests.

Do not invent private gateway methods inside an example plugin.

---

# 6. Plugin Source Style

Plugin source is Python.

Follow the repository's existing Python style:

* 4-space indentation;
* type hints where useful;
* clear `snake_case` names;
* `PascalCase` for classes;
* `UPPER_SNAKE_CASE` for constants;
* explicit imports;
* small focused functions;
* no unnecessary framework abstractions.

Use:

```python
from __future__ import annotations
```

when it matches the surrounding source.

Prefer readable application logic over overly clever abstractions.

Reference examples should stay intentionally small.

Real demo plugins may have more substantial logic, but should still remain easy to understand.

---

# 7. Gateway Usage

Gateway calls are the plugin's interface to the host.

Keep gateway interaction explicit.

A useful pattern is:

```text
receive/request data
    ↓
validate/normalize
    ↓
perform plugin-specific logic
    ↓
persist or present the result
```

Do not assume that host implementation details are available.

Do not directly:

* access the host database;
* access the host filesystem;
* call private application modules;
* manipulate host SQLAlchemy models;
* depend on host test fixtures;
* rely on undocumented endpoints.

If a required operation is unavailable through the public API, treat that as an API design problem rather than bypassing the boundary.

---

# 8. Real Demo Plugin Rules

Real demo plugins should demonstrate useful application-level behavior.

A real demo should generally contain:

* a valid manifest;
* a meaningful plugin ID;
* a `plugin.py`;
* plugin-specific logic;
* appropriate capability/permission declarations;
* documentation;
* tests;
* UI assets when applicable;
* package support.

Examples established by this repository include:

### Playtime Report

Demonstrates:

* game-library access;
* data processing;
* persistent plugin state;
* a useful report;
* plugin UI.

### Recently Played Notifier

Demonstrates:

* game data;
* notification capability;
* persistent state;
* a side effect.

### Metadata Curator

Demonstrates:

* plugin settings;
* metadata search;
* result normalization;
* persistent state.

Use these as architectural templates, not as code to copy wholesale.

---

# 9. Reference Plugin Rules

Reference plugins should remain small and focused.

They exist to demonstrate individual protocol capabilities.

Do not artificially turn every reference plugin into a full application.

Conversely, do not label application-level behavior as a "reference" merely because it is convenient.

Keep the distinction documented.

---

# 10. SDK Rules

The `sdk/` directory contains protocol helpers used by plugins.

The SDK is a public compatibility surface.

Changes to:

```text
sdk/plugin_protocol.py
```

must be treated as API changes.

Before changing it:

1. inspect every example using it;
2. inspect its tests;
3. understand compatibility implications;
4. update examples;
5. update tests;
6. update package integrity;
7. document the change;
8. coordinate with the host application's Plugin API.

Do not add host-specific convenience functions to the SDK unless they belong to the public plugin contract.

Keep the SDK independent of application internals.

---

# 11. Package Building

Packages are built with:

```bash
python tools/build_packages.py
```

The development output is an isolated preview:

```text
.validation/dist/*.utp
```

The package builder includes plugin source, the SDK, UI/assets, README, declared
icon and generated release metadata in the existing package payload. Signed main
publication uses `--require-signing`, writes `dist/`, `list.json`, `releases/` and
resolved source versions together, and preserves immutable historical packages.
Read `wiki/docs/plugin-author-guide.md` and the tutorial wiki configured in `mkdocs.yml` and `wiki/docs/catalogue-specification.md` before
changing distribution or release behavior.

The package digest is calculated from canonical sorted payload paths and bytes.

The package signature is an Ed25519 signature over:

```text
plugin-package-v1:<sha256>
```

Do not change the digest/signature contract casually.

A package integrity change must be coordinated with the host application's verifier.

---

# 12. Signing

Publisher signing is security-sensitive.

Private signing keys must never be committed.

The package builder accepts signing configuration through:

```text
PLUGIN_SIGNING_KEY_B64
PLUGIN_SIGNING_KEY_ID
```

The corresponding public keys live under:

```text
publishers/
```

Only trusted publisher identities should be used for distributable packages.

Do not:

* commit private keys;
* place private keys in source;
* add private keys to `.utp` files;
* silently replace publisher keys;
* reuse a signing identity for an unrelated publisher;
* weaken signature verification because a local build is inconvenient.

If a package cannot legitimately be signed, preserve the repository's existing unsigned/demo behavior rather than fabricating a signature.

---

# 13. `.utp` Artifacts

`.utp` files are installable artifacts, not source files.

Do not:

* rename a `.py` file to `.utp`;
* manually edit a package after signing;
* rebuild signed artifacts with modified payloads while retaining their signatures;
* commit packages whose manifest digest does not match their payload;
* distribute a package with an invalid signature.

When source or SDK contents change, regenerate affected packages correctly and ensure their signatures correspond to the resulting payload.

Checked-in signed artifacts must remain cryptographically consistent.

---

# 14. Tests

Tests are located under:

```text
tests/
```

The repository currently uses pytest.

Tests should cover:

* manifest validity;
* plugin IDs;
* semantic versions;
* entrypoints;
* declared capabilities;
* permissions;
* independence from host application source;
* real demo behavior;
* package construction;
* package integrity;
* signatures where applicable.

Existing tests explicitly ensure that plugins do not import application internals.

Preserve that property.

When adding a plugin, add it to the relevant test coverage rather than relying on a manual inspection.

Do not remove tests because they are inconvenient.

Do not weaken an assertion simply to accommodate an incorrect implementation.

---

# 15. Testing New Plugins

At minimum, verify:

```bash
pytest
python tools/build_packages.py
```

For package changes, additionally inspect the resulting `.utp`.

Verify:

1. `manifest.json` exists;
2. the manifest is valid;
3. the entrypoint is correct;
4. declared capabilities match usage;
5. permissions are appropriate;
6. the payload is present;
7. the canonical digest matches;
8. the signature is valid when the package is intended to be installable;
9. the package can be consumed by the host application.

For changes affecting the host/plugin contract, coordinate testing with:

```text
Unbound-Timeline-Shelf/Unbound-Timeline-Shelf
```

The plugin repository's tests should validate the plugin side.

The host repository's integration/E2E tests should validate actual installation and execution.

---

# 16. Documentation

Every real plugin should have a README.

Documentation should explain:

* what the plugin does;
* what capabilities it uses;
* what permissions it requests and why;
* how to build/test it;
* whether a signed `.utp` is currently distributed;
* how to install it when an artifact is available;
* any important compatibility limitations.

The root README should remain an accurate guide to:

* available plugins;
* the distinction between real demos and references;
* installation;
* development;
* package building;
* signing.

If a new plugin is added, update the root plugin listing.

If installation behavior changes, update the user-facing installation guide.

Do not document a plugin as installable if the repository does not actually publish a valid trusted package for it.

---

# 17. Branching

Use descriptive Conventional-style branch prefixes:

```text
feat/<short-description>
fix/<short-description>
docs/<short-description>
chore/<short-description>
refactor/<short-description>
test/<short-description>
```

Examples:

```text
feat/real-demo-plugins
feat/plugin-settings-example
fix/package-signing
docs/examples-and-installation
chore/update-package-builder
test/plugin-integrity
```

The repository's history already uses names such as:

```text
feat/real-demo-plugins
docs/examples-and-installation
```

Keep branches focused on one logical change.

Do not create branches named:

```text
plugin
stuff
test
new
changes
```

If a change depends on a host application branch/PR, state the dependency clearly in the PR.

---

# 18. Commits

Use Conventional Commits.

Examples:

```text
feat: add real demo plugin playtime-report
feat: add metadata curator example
fix: preserve signed reference packages
fix: remove stale packages before rebuilding
docs: distinguish installable packages from source demos
docs: clarify signed artifact rebuild behavior
ci: support trusted release-time plugin signing
test: validate real demo plugin behavior
build: package real demo plugins
```

Keep commits medium-sized and logically coherent.

Do not combine unrelated:

* plugin implementations;
* documentation;
* CI changes;
* signing changes;
* formatting changes.

unless they are inseparable parts of one feature.

Do not create dozens of meaningless micro-commits.

Do not use AI/tool meta-commentary in commit messages.

---

# 19. Pull Requests

Use a formal-casual engineering tone.

A plugin PR should normally contain:

## Motivation

Explain what plugin capability or user/developer need is being addressed.

## Implementation

Explain:

* plugin structure;
* manifest;
* gateway calls;
* capabilities;
* permissions;
* storage;
* UI;
* package/build changes.

## Testing

List:

```bash
pytest
python tools/build_packages.py
```

and any additional verification.

If host integration was tested, say how.

## Screenshots/GIFs

For plugins with meaningful UI, include screenshots or GIFs when useful.

For protocol-only examples, screenshots are unnecessary.

## Possible extensions

Mention reasonable follow-up ideas that are intentionally outside the PR.

## Breaking changes

Explicitly state whether the Plugin API, SDK, package format, or existing plugin behavior changes.

Use:

```text
Breaking changes: None
```

when appropriate.

Do not include AI-generated-content disclaimers or other AI meta-commentary.

---

# 20. CI

The repository's CI currently performs Python setup followed by:

```bash
pytest
python tools/build_packages.py
```

and verifies generated package integrity/signatures.

Do not remove these checks to make CI pass.

When changing package generation:

* preserve deterministic digest calculation;
* preserve signature verification;
* preserve trusted publisher checks;
* ensure all expected packages are handled;
* ensure every retained historical artifact is indexed and byte-identical;
* reject untracked packages and catalogue/package/hash inconsistencies;
* validate the complete generated preview and current manifest/UI/handler contract.

If CI exposes an invalid checked-in package, fix the artifact or source/signing process rather than weakening verification.

---

# 21. Docker and Development Environment

This repository does not currently require Docker for its normal CI/development workflow.

Do not introduce Docker merely to mirror the host application.

The plugin repository is intentionally independently usable.

A plugin developer should be able to:

1. clone this repository;
2. install its Python test dependencies;
3. run pytest;
4. build packages;
5. inspect the resulting `.utp`.

If Docker is introduced for a specific reason, document why and ensure the plain Python workflow remains usable unless the repository's architecture intentionally changes.

---

# 22. Cross-Repository Boundary

This is the most important architectural rule in this repository.

### This repository owns

* plugin implementations;
* plugin manifests;
* plugin documentation;
* plugin tests;
* SDK/protocol helpers;
* package-building logic;
* publisher public keys;
* distributable plugin artifacts.

### The host repository owns

* plugin runtime;
* plugin lifecycle implementation;
* gateway implementation;
* permission enforcement;
* plugin storage implementation;
* plugin installation;
* package verification;
* application UI framework;
* application database;
* application internals.

Do not solve a missing host feature by importing host code.

If the public API cannot support a plugin requirement:

1. identify the missing capability;
2. document the requirement;
3. coordinate a host API change;
4. update the public contract;
5. update this repository's plugin;
6. test both sides.

Never make a plugin depend on an internal host module just because the internal module already exists.

---

# 23. Architecture Drift Prevention

Agents must not:

* copy the plugin runtime into this repository;
* copy application models into plugins;
* import application source;
* depend on test-only host fixtures;
* create private gateway APIs;
* bypass capability declarations;
* bypass permissions;
* weaken package verification;
* fabricate signatures;
* commit signing secrets;
* make every example depend on every capability;
* turn small reference examples into unnecessary frameworks;
* introduce a second package format without a documented compatibility reason;
* introduce a second SDK;
* duplicate host functionality.

The repository should remain usable independently of the application source tree.

---

# 24. Adding a New Plugin

Use this workflow:

1. Create a branch:

   ```text
   feat/<plugin-name>
   ```

2. Create:

   ```text
   examples/<plugin-name>/
   ```

3. Add:

   ```text
   manifest.json
   plugin.py
   README.md
   ```

4. Add UI assets such as `ui.json` only when required.

5. Implement behavior exclusively through the public gateway.

6. Declare exact capabilities.

7. Declare exact permissions and rationales.

8. Add tests.

9. Add the plugin to package-building configuration.

10. Add it to manifest/package validation tests.

11. Update the root README.

12. Build the package.

13. Verify its integrity.

14. Sign it if it is intended to be distributable.

15. Verify it independently using the same public verification model used by CI.

16. Run all repository tests and package checks.

17. If host integration is relevant, test installation against the real host plugin manager.

---

# 25. Changing an Existing Plugin

For an existing plugin:

* preserve its `plugin_id`;
* use Conventional Commits so publication generates the appropriate semantic version;
* update the manifest;
* update documentation;
* update tests;
* regenerate the package;
* regenerate the signature;
* verify permissions remain minimal;
* check SDK compatibility.

Do not silently change behavior while retaining an old version.

Do not modify a signed artifact without rebuilding/re-signing it.

---

# 26. Agent Completion Checklist

Before considering a task complete:

* [ ] Plugin code uses only the public Plugin API.
* [ ] No host application imports exist.
* [ ] Manifest is valid.
* [ ] Plugin ID is unique.
* [ ] Version is valid semantic versioning.
* [ ] Capabilities are accurate.
* [ ] Permissions are minimal and justified.
* [ ] Tests exist.
* [ ] Existing tests still pass.
* [ ] Package builder succeeds.
* [ ] `.utp` integrity is valid.
* [ ] Signature is valid when applicable.
* [ ] No private signing material was committed.
* [ ] Documentation is updated and `python -m mkdocs build --strict` passes.
* [ ] Root plugin listing is updated when necessary.
* [ ] No unrelated files were modified.
* [ ] No architecture boundaries were bypassed.
* [ ] CI passes.

The guiding principle is:

> A plugin should be a consumer of the platform, not another implementation of the platform.
