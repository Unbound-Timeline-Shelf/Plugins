"""The catalogue is a lean index; complete release records live in releases/*.json."""

import hashlib
import json
import shutil

import pytest

from tools.distribution import (
    CATALOGUE_HEADROOM_BYTES,
    CATALOGUE_MANIFEST_FIELDS,
    CATALOGUE_RELEASE_FIELDS,
    MAX_CATALOGUE_BYTES,
    _advertised_matches,
    ROOT,
    load_histories,
    validate_distribution,
)


def test_checked_in_catalogue_summarises_every_release_and_links_complete_history():
    catalogue_bytes = (ROOT / "list.json").read_bytes()
    # The hard bound is the host's download limit. The headroom margin is only
    # a publication warning, but the checked-in catalogue should sit well inside it.
    assert len(catalogue_bytes) < MAX_CATALOGUE_BYTES - CATALOGUE_HEADROOM_BYTES
    catalogue = json.loads(catalogue_bytes)
    histories = load_histories(ROOT)
    for entry in catalogue["plugins"]:
        history = histories[entry["plugin_id"]]
        link = entry["release_history"]
        assert link["path"] == f"releases/{entry['plugin_id']}.json"
        assert link["url"].endswith("/" + link["path"])
        assert link["count"] == len(history)
        assert link["sha256"] == hashlib.sha256((ROOT / link["path"]).read_bytes()).hexdigest()
        # Every published version stays installable from the catalogue on
        # existing hosts: they read exactly these fields per release and require
        # the last one to agree with the current entry.
        assert [r["version"] for r in entry["releases"]] == [r["version"] for r in history]
        for summary, record in zip(entry["releases"], history, strict=True):
            assert set(summary) == {*CATALOGUE_RELEASE_FIELDS, "url"}
            assert summary["url"].endswith("/dist/" + record["package"]["filename"])
            for field in CATALOGUE_RELEASE_FIELDS:
                if field != "manifest":
                    assert summary[field] == record[field]
            # A summary manifest is the compatibility subset of the full one.
            assert summary["manifest"] == {
                k: record["manifest"][k] for k in CATALOGUE_MANIFEST_FIELDS if k in record["manifest"]
            }
            assert summary["manifest"].get("api_contract_version", "1.0.0") == record[
                "manifest"
            ].get("api_contract_version", "1.0.0")
        latest = entry["releases"][-1]
        assert (latest["version"], latest["url"], latest["sha256"], latest["package_sha256"]) == (
            entry["version"], entry["url"], entry["sha256"], entry["package_sha256"]
        )
        # The entry itself remains the complete latest record.
        assert entry["manifest"] == history[-1]["manifest"]


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


def test_catalogue_size_grows_slowly_per_release():
    catalogue = json.loads((ROOT / "list.json").read_bytes())
    rows = [r for e in catalogue["plugins"] for r in e["releases"]]
    row_bytes = sum(len(json.dumps(r, sort_keys=True, indent=2)) for r in rows) / len(rows)
    # Rows no longer embed permissions/capabilities/UI, so thousands more
    # releases fit before the publication warning margin.
    assert row_bytes < 2048


def test_baseline_comparison_accepts_full_or_summary_manifest_but_not_changes():
    record = {"version": "1.0.0", "manifest": {"plugin_id": "a.b", "version": "1.0.0", "permissions": []}}
    assert _advertised_matches("manifest", record["manifest"], record)
    assert _advertised_matches("manifest", {"plugin_id": "a.b", "version": "1.0.0"}, record)
    assert not _advertised_matches("manifest", {"plugin_id": "a.c"}, record)
    assert not _advertised_matches("manifest", {"api_contract_version": "1.0.0"}, record)
    assert _advertised_matches("url", "https://elsewhere/x.utp", record)
    assert not _advertised_matches("version", "1.0.1", record)
