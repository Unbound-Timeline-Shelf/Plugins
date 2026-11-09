"""The catalogue is a bounded index; complete histories live in releases/*.json."""

import hashlib
import json
import shutil

import pytest

from tools.distribution import (
    CATALOGUE_RELEASE_WINDOW,
    MAX_CATALOGUE_BYTES,
    ROOT,
    load_histories,
    validate_distribution,
)


def test_checked_in_catalogue_embeds_window_and_links_complete_history():
    catalogue_bytes = (ROOT / "list.json").read_bytes()
    # Keep generous headroom under the host's download bound as plugins grow.
    assert len(catalogue_bytes) < MAX_CATALOGUE_BYTES // 2
    catalogue = json.loads(catalogue_bytes)
    histories = load_histories(ROOT)
    truncated = 0
    for entry in catalogue["plugins"]:
        history = histories[entry["plugin_id"]]
        link = entry["release_history"]
        assert link["path"] == f"releases/{entry['plugin_id']}.json"
        assert link["url"].endswith("/" + link["path"])
        assert link["count"] == len(history)
        assert link["sha256"] == hashlib.sha256((ROOT / link["path"]).read_bytes()).hexdigest()
        # Hosts that only read `releases` still see the current release last,
        # matching the entry, followed by the newest manual-downgrade candidates.
        assert 1 <= len(entry["releases"]) <= CATALOGUE_RELEASE_WINDOW
        assert entry["releases"][-1]["version"] == entry["version"]
        assert entry["releases"][-1]["url"] == entry["url"]
        assert [
            {k: v for k, v in r.items() if k != "url"} for r in entry["releases"]
        ] == history[-CATALOGUE_RELEASE_WINDOW:]
        for release in entry["releases"]:
            assert release["url"].endswith("/dist/" + release["package"]["filename"])
        truncated += len(history) > CATALOGUE_RELEASE_WINDOW
    assert truncated, "fixture data should exercise a history longer than the window"


def candidate(tmp_path):
    root = tmp_path / "candidate"
    shutil.copytree(
        ROOT,
        root,
        ignore=shutil.ignore_patterns(".git", ".validation", "node_modules", "site", "__pycache__"),
    )
    return root


def test_rejects_history_file_that_differs_from_its_catalogue_link(tmp_path):
    root = candidate(tmp_path)
    path = root / "releases/example.help-button.json"
    # Same records, different bytes: the link binds the exact published file.
    path.write_text(json.dumps(json.loads(path.read_bytes())), encoding="utf-8")
    with pytest.raises(ValueError, match="release history file does not match"):
        validate_distribution(root, source_root=root)


def test_rejects_catalogue_without_release_history_link(tmp_path):
    root = candidate(tmp_path)
    path = root / "list.json"
    catalogue = json.loads(path.read_bytes())
    del catalogue["plugins"][0]["release_history"]
    path.write_bytes(
        (json.dumps(catalogue, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    )
    with pytest.raises(ValueError, match="catalogue differs"):
        validate_distribution(root, source_root=root)
