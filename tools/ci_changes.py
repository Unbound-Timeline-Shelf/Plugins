"""Decide which CI areas a diff needs; unknown or shared changes select everything."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOTS = ("examples", "official", "plugins")
DOC_ROOTS = ("wiki", "docs")
ZERO_SHA = "0" * 40
JELLYFIN = "official/jellyfin-media-sync"
PWA = "official/pwa"
ATLAS = "official/metadata-atlas"
ATLAS_LIVE_TESTS = "tests/atlas_live/"
REPOSITORY = Path(__file__).resolve().parents[1]
TOOL_NAME = re.compile(r"^(?:check|capture)_(?P<rest>.+?)\.[^.]+$")


def tool_plugins(name: str, available: list[str] | None = None) -> set[str]:
    """Plugins a ``tools/check_<plugin>*`` or ``tools/capture_<plugin>*`` script belongs to.

    A script belongs to a plugin when its name continues the plugin directory name
    (``check_collectors_archive_ui`` -> ``collectors-archive``) or, failing that, when its
    first word identifies exactly one plugin (``check_epic_host`` -> ``epic-games``,
    ``check_jellyfin_official_lifecycle`` -> the official Jellyfin plugin). Anything else,
    including a word shared by several plugins (``check_metadata_live``), stays shared.
    """
    match = TOOL_NAME.match(name)
    if not match:
        return set()
    rest = match["rest"]
    if available is None:
        available = [f"{root}/{child.name}" for root in PLUGIN_ROOTS
                     if (REPOSITORY / root).is_dir()
                     for child in sorted((REPOSITORY / root).iterdir()) if child.is_dir()]
    slugs = {path: path.split("/")[1].replace("-", "_") for path in available}
    exact = {path for path, slug in slugs.items() if rest == slug or rest.startswith(slug + "_")}
    if exact:
        return exact
    first = rest.split("_")[0]
    related = {path for path, slug in slugs.items() if slug.split("_")[0] == first}
    if "official" in rest.split("_"):
        related = {path for path in related if path.startswith("official/")}
    return related if len({slugs[path] for path in related}) == 1 else set()


def classify(files: list[str] | None) -> dict[str, object]:
    """Map changed paths to the CI areas that must run.

    ``None`` means the change set is unknown. Paths outside plugin sources, documentation
    and tests (SDK, tools, publishers, workflows, dependency files, ...) are shared and
    select everything, except per-plugin ``tools/check_<plugin>*`` and
    ``tools/capture_<plugin>*`` scripts, which count as changes to that plugin.
    Documentation-only diffs skip plugin lifecycle and package work.
    """
    if files is None:
        return everything()
    plugins: set[str] = set()
    shared = tests = atlas_tests = False
    for raw in files:
        path = raw.strip().replace("\\", "/")
        if not path:
            continue
        parts = path.split("/")
        if parts[0] in PLUGIN_ROOTS and len(parts) > 2:
            plugins.add("/".join(parts[:2]))
        elif parts[0] in DOC_ROOTS or (len(parts) == 1 and path.endswith(".md")):
            continue
        elif parts[0] == "tools" and len(parts) == 2 and (owners := tool_plugins(parts[1])):
            plugins.update(owners)
        elif parts[0] == "tests":
            tests = True
            atlas_tests = atlas_tests or path.startswith(ATLAS_LIVE_TESTS)
        else:
            shared = True
    return {
        "plugins": sorted(plugins),
        "lifecycle": shared or bool(plugins),
        "lifecycle_reference": shared or any(p.startswith("examples/") for p in plugins),
        "lifecycle_jellyfin": shared or JELLYFIN in plugins,
        "lifecycle_pwa": shared or PWA in plugins,
        "full_tests": shared or tests or bool(plugins),
        "atlas_live": shared or atlas_tests or ATLAS in plugins,
    }


def everything() -> dict[str, object]:
    return {"plugins": ["*"], "lifecycle": True, "lifecycle_reference": True,
            "lifecycle_jellyfin": True, "lifecycle_pwa": True, "full_tests": True, "atlas_live": True}


def changed_files(event: str, base: str, head: str) -> list[str] | None:
    if event not in {"pull_request", "push"} or not base or base == ZERO_SHA or not head:
        return None
    # Two dots on push (before..after); the PR base is merged into a three-dot range.
    spec = f"{base}...{head}" if event == "pull_request" else f"{base}..{head}"
    result = subprocess.run(["git", "diff", "--name-only", spec], capture_output=True, text=True)
    return result.stdout.splitlines() if result.returncode == 0 else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", default=os.environ.get("EVENT", ""))
    parser.add_argument("--base", default=os.environ.get("BASE_SHA", ""))
    parser.add_argument("--head", default=os.environ.get("HEAD_SHA", ""))
    parser.add_argument("--ref", default=os.environ.get("REF", ""), help="main and tags always run everything")
    args = parser.parse_args()
    if args.ref == "main" or args.ref.startswith("refs/tags/"):
        selection = everything()
    else:
        selection = classify(changed_files(args.event, args.base, args.head))
    lines = [f"{key}={str(value).lower() if isinstance(value, bool) else ','.join(value)}"
             for key, value in selection.items()]
    print("\n".join(lines))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
