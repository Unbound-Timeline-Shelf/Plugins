"""Synchronize reviewed existing PWA assets; never touch native client sources."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).parents[1]


def sync(mobile_root: Path, host_root: Path, *, check: bool = False) -> None:
    source = mobile_root / "pwa"
    target = ROOT / "official/pwa/pwa"
    version = json.loads((source / "version.json").read_text())["version"]
    if not version.startswith("0.0."):
        raise ValueError("PWA integration must remain 0.0.x")
    manifest = json.loads((ROOT / "official/pwa/manifest.json").read_text())
    # Host contract migrations may release a new plugin around unchanged,
    # exactly reviewed mobile assets. Their versions remain separate.
    plugin_version = manifest["version"]
    if not plugin_version.startswith("0.0.") or int(plugin_version.split(".")[2]) < int(version.split(".")[2]):
        raise ValueError("plugin PWA version must remain 0.0.x and cannot precede its mobile assets")
    names = ("manifest.webmanifest", "service-worker.js", "offline.html", "pwa-icon.svg",
             "icon-192.png", "icon-512.png", "version.json", "README.md")
    hashes = {}
    for name in names:
        data = (source / name).read_bytes()
        is_text = name.endswith((".html", ".js", ".json", ".svg", ".webmanifest", ".md"))
        if is_text:
            data = data.replace(b"\r\n", b"\n")
        hashes[name] = hashlib.sha256(data).hexdigest()
        destinations = [target / name]
        if name in {"service-worker.js", "offline.html"}:
            destinations.append(host_root / "src/backend/src/plugin_api/pwa_assets" / name)
        for destination in destinations:
            if check:
                actual = destination.read_bytes() if destination.is_file() else None
                if actual is not None and is_text:
                    actual = actual.replace(b"\r\n", b"\n")
                if actual != data:
                    raise ValueError(f"PWA asset drift: {destination}")
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
    provenance = {"repository": "Unbound-Timeline-Shelf/Mobile-Apps", "version": version,
                  "source_path": "pwa", "sha256": hashes}
    path = target / "provenance.json"
    if check:
        actual = json.loads(path.read_text())
        # Keep verifiable provenance of previously reviewed assets after a repository transfer.
        if actual.get("repository") in {
            "Rosefall-a/unnamed-tracking-mobile-app",
            "obsoletelabs/unnamed-tracking-mobile-app",
        }:
            actual["repository"] = provenance["repository"]
        if actual != provenance:
            raise ValueError("PWA provenance differs")
    else:
        path.write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mobile-root", type=Path, required=True)
    parser.add_argument("--host-root", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    sync(args.mobile_root, args.host_root, check=args.check)
