# Create your first plugin

Build a small **Library Summary** action. It counts the first 50 games returned
for the authenticated caller. It does not claim to count an unbounded library.

**Goal:** produce a real package and run its action in a development host.
**Prerequisites:** Python 3.11+, Git, and an isolated Plugin Manager host build
for installation. Node is needed for browser/native frontend tests, not for this
Python/declarative exercise. Check the host version before claiming compatibility.

## 1. Prepare your environment

Install Python 3.11+ and Git. Clone this repository into your own working directory:

```sh
git clone https://github.com/Unbound-Timeline-Shelf/Plugins.git
cd unnamed_tracking_app_plugins
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv/Scripts/Activate.ps1
python -m pip install -r requirements-dev.txt
python tools/check_source_layout.py
```

Create `examples/library-summary/`. Use your own namespace instead of `example.*`
when publishing. The tutorial identity below is illustrative; replace it in both
JSON files before public distribution.

## 2. Write the minimal manifest

Save the following as `examples/library-summary/manifest.json`:

<!-- tutorial: manifest.json -->
```json
{
  "manifest_version": 1,
  "api_contract_version": "1.1.0",
  "plugin_id": "org.example.library-summary",
  "name": "Library Summary",
  "version": "1.0.0",
  "description": "Count up to 50 games for the authenticated caller.",
  "entrypoint": "plugin:main",
  "sdk_version_range": "^1.1.0",
  "application_version_range": "^1.0.0",
  "capabilities": [{"name": "games.read", "version": 1}],
  "permissions": [{"capability": {"name": "games.read", "version": 1}, "rationale": "Count the caller's game library on request."}],
  "dependencies": [],
  "ui": {"settings": [], "actions": ["summarize"], "pages": ["summary"], "menus": []},
  "storage": {"quota_mb": 1},
  "integrity": {"sha256": "0000000000000000000000000000000000000000000000000000000000000000", "signature": null, "key_id": null}
}
```

The source digest is a placeholder. The builder calculates real integrity from
payload bytes. `games.read` is the sole requested capability. No sidebar or native
grant is needed to display a page inside the plugin detail panel.

## 3. Write the minimal Python entrypoint and action

Save `examples/library-summary/plugin.py`:

<!-- tutorial: plugin.py -->
```python
from __future__ import annotations

import time
from sdk.plugin_protocol import request


def summarize(values: dict) -> dict:
    del values
    result = request("games.list", "games.read", {"limit": 50})
    games = result.get("games", result.get("items", []))
    return {"game_count": len(games)}


def main() -> None:
    request("lifecycle.ready", "lifecycle.ready", {})
    while True:
        time.sleep(3600)
```

The host imports `plugin:main`; no script argument parser is needed. The worker
must remain alive after readiness. The host invokes `plugin:summarize` in a
separate authenticated action subprocess. Keep stdout for the SDK protocol and
write diagnostics to stderr.

## 4. Connect the action to a page

Save `examples/library-summary/ui.json`:

<!-- tutorial: ui.json -->
```json
{
  "schema_version": "v1",
  "api_contract_version": "1.1.0",
  "plugin_id": "org.example.library-summary",
  "title": "Library Summary",
  "settings": [],
  "actions": [{"id": "summarize", "label": "Count games", "handler": "plugin:summarize", "capability": {"name": "games.read", "version": 1}}],
  "pages": [{"id": "summary", "title": "Library Summary", "description": "Count up to 50 games.", "actions": ["summarize"]}],
  "menus": []
}
```

Save a non-empty `README.md` with purpose, configuration and permission rationale:

<!-- tutorial: README.md -->
```text
# Library Summary

Counts up to 50 games for the authenticated user when Count games is clicked.
Requires games.read; saves no data and contacts no external service.
The host must approve the permission before the action can run.
```

`release.json` is optional for this local exercise; the existing builder uses an
independent developer label and default update policy. Add explicit metadata
before [publishing](../publishing/packages.md).

## 5. Build your first .utp

From the repository root:

```sh
python tools/check_source_layout.py
python tools/build_packages.py
python tools/distribution.py --root .validation --check-source --include-unreleased
python tools/verify_packages.py .validation/dist/org.example.library-summary-1.0.0.utp
python tools/validate_packages.py --full .validation/dist/org.example.library-summary-1.0.0.utp
python -m zipfile -l .validation/dist/org.example.library-summary-1.0.0.utp
```

The package contains the real manifest, Python entrypoint, SDK, UI, README and
generated `distribution.json`. Other official plugins are also built/reused by
the same discovery mechanism. Nothing in published `dist/` changes.

The tutorial is executable: repository tests extract these exact four blocks,
build an isolated package with the existing tools, validate its UI/action and
execute its packaged SDK action with a protocol fixture. You can run
`python -m pytest tests/test_author_tutorial.py`.

## 6. Try it in Plugin Manager

Use a disposable installation of the current host `plugin-manager` build.
Open **Settings → Plugins**, upload the generated `.utp`, review its unsigned
status and `games.read` rationale, and complete the host's consent flow. Approve
the requested read grant, enable it if needed, then open its page and click
**Count games**. A library of three games should return `game_count: 3`.

Do not describe this preview as publisher-verified. Install refusal or a denied
grant should remain a denial; follow [troubleshooting](../troubleshooting/index.md)
instead of bypassing the host. Next, add [settings](../development/settings.md),
[storage](../development/storage.md) or [publishing metadata](../publishing/packages.md).

## Test command and expected result

```sh
python -m pytest tests/test_author_tutorial.py
```

The test extracts these exact four blocks, packages and validates them, then runs
the packaged action and SDK. Three protocol-fixture games return `game_count: 3`.
Installation, grants and real user ownership are checked in the actual host.

## Common mistakes

* Returning immediately after readiness causes an unhealthy worker.
* Printing diagnostics to stdout corrupts the SDK protocol; use stderr.
* Keeping the tutorial namespace in a public release risks identity collisions.
* Editing integrity/signature fields manually does not create a valid package.
* A denied read request must fail; do not present it as an empty library.
* PowerShell needs explicit filenames or the [wildcard form](../publishing/packages.md).
