"""CI change selection: shared or unknown changes run everything; plugin diffs run their areas."""

from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))

from ci_changes import classify, everything, tool_plugins


def test_unknown_change_sets_select_everything():
    assert classify(None) == everything()


@pytest.mark.parametrize("path", [
    "sdk/plugin_protocol.py", "tools/build_packages.py", "publishers/registry.json",
    ".github/workflows/ci.yml", "requirements-dev.txt", "package.json", "catalogue.json",
    "tools/ci_changes.py", "tools/check_host_lifecycle.py", "tools/check_metadata_live.py",
    "tools/capture_sessions.mjs", "tools/schemas/manifest.schema.json",
])
def test_shared_files_select_everything(path):
    selection = classify([path])
    assert selection["lifecycle"] and selection["lifecycle_reference"]
    assert selection["lifecycle_jellyfin"] and selection["lifecycle_pwa"] and selection["full_tests"]


def test_a_single_plugin_selects_only_its_acceptance_steps():
    jellyfin = classify(["official/jellyfin-media-sync/sync.py"])
    assert jellyfin["plugins"] == ["official/jellyfin-media-sync"]
    assert jellyfin["lifecycle"] and jellyfin["lifecycle_jellyfin"] and jellyfin["full_tests"]
    assert not jellyfin["lifecycle_pwa"] and not jellyfin["lifecycle_reference"]
    pwa = classify(["official/pwa/pwa/README.md"])
    assert pwa["lifecycle_pwa"] and not pwa["lifecycle_jellyfin"]
    example = classify(["examples/ui-api/plugin.py", "examples/help-button/ui.json"])
    assert example["plugins"] == ["examples/help-button", "examples/ui-api"]
    assert example["lifecycle_reference"] and not example["lifecycle_jellyfin"] and not example["lifecycle_pwa"]
    other = classify(["official/epic-games/epic.py"])
    assert other["lifecycle"] and not (
        other["lifecycle_jellyfin"] or other["lifecycle_pwa"] or other["lifecycle_reference"])


@pytest.mark.parametrize("path, owners", [
    ("tools/check_collectors_archive_ui.mjs", ["official/collectors-archive"]),
    ("tools/capture_collectors_archive.mjs", ["official/collectors-archive"]),
    ("tools/check_epic_host.py", ["official/epic-games"]),
    ("tools/check_jellyfin_official_lifecycle.py", ["official/jellyfin-media-sync"]),
    ("tools/capture_jellyfin_official.mjs", ["official/jellyfin-media-sync"]),
])
def test_plugin_scoped_tools_select_only_their_plugin(path, owners):
    selection = classify([path])
    assert selection["plugins"] == owners
    assert selection["lifecycle"] and selection["full_tests"]
    assert selection["lifecycle_jellyfin"] == (owners == ["official/jellyfin-media-sync"])
    assert not selection["lifecycle_pwa"] and not selection["lifecycle_reference"]


def test_the_live_atlas_lane_runs_for_the_atlas_plugin_its_tests_and_shared_files_only():
    assert classify(["official/metadata-atlas/plugin.py"])["atlas_live"]
    assert classify(["tests/atlas_live/test_atlas_live_contract.py"])["atlas_live"]
    assert classify(["tools/check_metadata_atlas_live.py"])["plugins"] == ["official/metadata-atlas"]
    assert classify(["tools/check_metadata_atlas_live.py"])["atlas_live"]
    assert classify(["sdk/metadata_provider.py"])["atlas_live"]  # shared files select everything
    assert classify(["official/jellyfin-media-sync/sync.py"])["atlas_live"] is False
    assert classify(["tests/test_hltb.py"])["atlas_live"] is False
    assert classify(["wiki/docs/testing/atlas-live-contract.md"])["atlas_live"] is False
    assert everything()["atlas_live"] is True


def test_tool_ownership_needs_one_plugin_and_a_check_or_capture_name():
    available = ["official/metadata-hltb", "official/metadata-tmdb", "official/pwa",
                 "examples/ui-api"]
    assert tool_plugins("check_metadata_live.py", available) == set()  # shared by several
    assert tool_plugins("check_pwa_lifecycle.py", available) == {"official/pwa"}
    assert tool_plugins("check_ui_api_cases.py", available) == {"examples/ui-api"}
    assert tool_plugins("build_pwa.py", available) == set()  # not a check/capture script
    assert tool_plugins("check_unknown.py", available) == set()


def test_documentation_only_changes_skip_plugin_lifecycle_and_package_work():
    selection = classify(["wiki/docs/index.md", "README.md", "docs/official-signing.md"])
    assert selection["plugins"] == []
    assert not any(selection[key] for key in selection if key != "plugins")


def test_test_only_changes_run_the_test_job_but_not_lifecycle():
    selection = classify(["tests/test_hltb.py"])
    assert selection["full_tests"] and not selection["lifecycle"]


def test_mixed_diff_combines_areas_and_unknown_paths_are_shared():
    selection = classify(["official/pwa/manifest.json", "wiki/docs/index.md", "Makefile"])
    assert selection["lifecycle_jellyfin"]  # an unrecognised root file is treated as shared
    assert classify(["official/pwa/manifest.json", "wiki/docs/index.md"])["lifecycle_pwa"]
    assert classify(["", "  "])["lifecycle"] is False


def test_main_tags_and_missing_base_run_everything(tmp_path):
    script = Path(__file__).parents[1] / "tools/ci_changes.py"
    def run(*args):
        return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, check=True).stdout
    assert "lifecycle_pwa=true" in run("--ref", "main", "--event", "pull_request")
    assert "lifecycle_pwa=true" in run("--ref", "refs/tags/v1", "--event", "push")
    assert "lifecycle_pwa=true" in run("--ref", "feature", "--event", "push", "--base", "0" * 40, "--head", "abc")
    assert "plugins=*" in run("--ref", "feature", "--event", "workflow_dispatch")
