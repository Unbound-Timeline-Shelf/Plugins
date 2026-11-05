"""PWA sync preserves reviewed legacy provenance through repository transfers."""

import json

import pytest

from tools import sync_pwa


def test_sync_accepts_legacy_reviewed_origins_and_writes_current_origin(
    tmp_path, monkeypatch
):
    plugins = tmp_path / "plugins"
    mobile = tmp_path / "mobile"
    host = tmp_path / "host"
    source = mobile / "pwa"
    target = plugins / "official/pwa"
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    (target / "manifest.json").write_text('{"version": "0.0.1"}')
    names = (
        "manifest.webmanifest",
        "service-worker.js",
        "offline.html",
        "pwa-icon.svg",
        "icon-192.png",
        "icon-512.png",
        "version.json",
        "README.md",
    )
    for name in names:
        (source / name).write_bytes(
            b'{"version": "0.0.1"}' if name == "version.json" else name.encode()
        )
    monkeypatch.setattr(sync_pwa, "ROOT", plugins)

    sync_pwa.sync(mobile, host)
    path = target / "pwa/provenance.json"
    provenance = json.loads(path.read_text())
    assert provenance["repository"] == "Unbound-Timeline-Shelf/Mobile-Apps"
    for identity in (
        "Unbound-Timeline-Shelf/Mobile-Apps",
        "obsoletelabs/unnamed-tracking-mobile-app",
        "Rosefall-a/unnamed-tracking-mobile-app",
    ):
        path.write_text(json.dumps({**provenance, "repository": identity}))
        sync_pwa.sync(mobile, host, check=True)

    path.write_text(json.dumps({**provenance, "repository": "unrelated/project"}))
    with pytest.raises(ValueError, match="PWA provenance differs"):
        sync_pwa.sync(mobile, host, check=True)
