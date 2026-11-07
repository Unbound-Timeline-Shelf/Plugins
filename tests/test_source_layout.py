"""Fail rather than silently dropping misplaced or incomplete plugin sources."""
import json
import shutil

import pytest

from tools.check_source_layout import check
from tools.distribution import ROOT, discover_plugins


def test_all_maintained_sources_have_full_contracts(built_distribution):
    check()
    current = json.loads((built_distribution / "list.json").read_text(encoding="utf-8"))
    assert {m["plugin_id"] for _, m in discover_plugins(ROOT)} == {
        p["plugin_id"] for p in current["plugins"]
    }


@pytest.mark.parametrize("contract", [None, "1.0.0", "1.1.21"])
def test_source_validation_rejects_unmigrated_contracts(tmp_path, contract):
    shutil.copytree(ROOT / "examples/ui-api", tmp_path / "examples/ui-api")
    path = tmp_path / "examples/ui-api/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if contract is None:
        manifest.pop("api_contract_version")
    else:
        manifest["api_contract_version"] = contract
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="explicitly target a supported Plugin API contract version"):
        check(tmp_path)


@pytest.mark.parametrize("defect", ["old_tree", "missing_manifest", "missing_entrypoint", "duplicate_id"])
def test_discovery_rejects_layout_drift(tmp_path, defect):
    shutil.copytree(ROOT / "examples/ui-api", tmp_path / "examples/ui-api")
    if defect == "old_tree":
        (tmp_path / "examples.old").mkdir()
    elif defect == "missing_manifest":
        (tmp_path / "examples/stub").mkdir()
        (tmp_path / "examples/stub/README.md").write_text("Obsolete stub", encoding="utf-8")
    elif defect == "missing_entrypoint":
        (tmp_path / "examples/ui-api/plugin.py").unlink()
    else:
        shutil.copytree(tmp_path / "examples/ui-api", tmp_path / "examples/duplicate")
    with pytest.raises(ValueError):
        discover_plugins(tmp_path)


@pytest.mark.parametrize("defect", ["ungranted", "missing-page", "missing-action", "missing-sync", "old-contract"])
def test_connection_contract_is_checked_in_source(defect):
    from tools.distribution import canonical_json, collect_payload
    from tools.validate_packages import validate_current_contract

    source, manifest = next(
        (s, m) for s, m in discover_plugins(ROOT) if m["plugin_id"] == "official.epic-games"
    )
    files, metadata = collect_payload(ROOT, source, manifest)
    files["distribution.json"] = canonical_json(
        {**metadata, "version": manifest["version"], "automatic_update": False}
    )
    validate_current_contract(manifest, files)
    document = json.loads(files["ui.json"])
    if defect == "ungranted":
        manifest = {
            **manifest,
            "permissions": [
                item
                for item in manifest["permissions"]
                if item["capability"]["name"] != "frontend.connections"
            ],
        }
    elif defect == "missing-page":
        document["connections"][0]["page_id"] = "missing"
    elif defect == "missing-action":
        document["connections"][0]["status_action_id"] = "missing"
    elif defect == "missing-sync":
        document["connections"][0]["sync_action_id"] = "missing"
    else:
        manifest = {**manifest, "api_contract_version": "1.1.8"}
        document["api_contract_version"] = "1.1.8"
    files["ui.json"] = json.dumps(document).encode()
    with pytest.raises(ValueError):
        validate_current_contract(manifest, files)


@pytest.mark.parametrize("defect", ["ungranted", "missing-page", "old-contract"])
def test_integrated_administration_slots_require_the_public_contract(defect):
    from tools.distribution import canonical_json, collect_payload
    from tools.validate_packages import validate_current_contract

    source, manifest = next(
        (s, m) for s, m in discover_plugins(ROOT) if m["plugin_id"] == "official.user-invites"
    )
    files, metadata = collect_payload(ROOT, source, manifest)
    files["distribution.json"] = canonical_json({**metadata, "version": manifest["version"], "automatic_update": False})
    validate_current_contract(manifest, files)
    document = json.loads(files["ui.json"])
    if defect == "ungranted":
        manifest["permissions"] = [item for item in manifest["permissions"] if item["capability"]["name"] != "frontend.settings"]
    elif defect == "missing-page":
        document["extensions"][1]["page_id"] = "missing"
    else:
        manifest["api_contract_version"] = document["api_contract_version"] = "1.1.10"
    files["ui.json"] = json.dumps(document).encode()
    with pytest.raises(ValueError):
        validate_current_contract(manifest, files)
