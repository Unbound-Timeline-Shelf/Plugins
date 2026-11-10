"""Execute the Linux workflow selector with offline GitHub API and Git transports."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
VERIFIED_RUNTIME_REF = "main"
LIFECYCLE_SETUP = ROOT / ".github/actions/lifecycle-setup/action.yml"
LIFECYCLE_JOBS = ("lifecycle-official", "lifecycle-reference", "lifecycle-jellyfin", "lifecycle-pwa")


@pytest.mark.parametrize(
    "scenario",
    [
        ("", "main", "main", False, "main"),
        ("", "feature/example", "feature/example", True, "feature/example"),
        ("", "feature/example", "main", False, "main"),
        # A stale branch without an open host PR must not shadow the merged main.
        ("", "feature/example", "feature/example", False, "main"),
        ("pinned-host-sha", "main", "main", False, "pinned-host-sha"),
        ("main", "main", "main", False, "main"),
        ("", "feat/discord-social-activity", "feat/plugin-discord-activity-host", True,
         "feat/plugin-discord-activity-host"),
        ("", "feat/discord-social-activity", "feat/plugin-discord-activity-host", False, "main"),
        ("pinned-host-sha", "feat/discord-social-activity", "feat/plugin-discord-activity-host", True,
         "pinned-host-sha"),
        # The 1.1.20 programme branches test against the open 1.1.20 host PR (#500), then main once it merges.
        ("", "programme/p7-plugins", "programme/m7-plugin-api-1120", True, "programme/m7-plugin-api-1120"),
        ("", "programme/p7-plugins", "programme/m7-plugin-api-1120", False, "main"),
        # Books (C15): the Atlas plugin's `book` needs the M10 host, pinned by commit; an explicit ref still wins.
        ("", "programme/p8-metadata-atlas-books", "programme/p8-metadata-atlas-books", True,
         "efded8aeaed4859d2da43995c8418c37c3a15458"),
        ("pinned-host-sha", "programme/p8-metadata-atlas-books", "main", False, "pinned-host-sha"),
    ],
)
@pytest.mark.parametrize(
    "workflow_name,job",
    [("ci.yml", "lifecycle"), ("ci.yml", "test-and-build")],
)
def test_workflow_selects_owned_host_target(tmp_path, scenario, workflow_name, job):
    """Explicit refs and open paired branches precede each workflow's verified fallback."""
    requested, branch, remote_branch, open_pr, expected = scenario
    workflow = yaml.safe_load((ROOT / ".github/workflows" / workflow_name).read_text())
    steps = workflow["jobs"][job]["steps"]
    if job == "lifecycle":
        # The parallel lifecycle jobs share one setup action that owns the host selection.
        steps = yaml.safe_load(LIFECYCLE_SETUP.read_text())["runs"]["steps"]
    checkout = next(step for step in steps if step.get("with", {}).get("path") == ".validation/host")
    assert checkout["with"]["repository"] == "Unbound-Timeline-Shelf/Unbound-Timeline-Shelf"
    step = next(step for step in steps if step.get("id") == "companion")
    assert "https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf.git" in step["run"]
    if job == "lifecycle":
        assert step["env"]["DEFAULT_HOST_REF"] == VERIFIED_RUNTIME_REF
        if not requested and expected == "main":
            expected = VERIFIED_RUNTIME_REF
    git = tmp_path / "git"
    git.write_text(
        "#!/bin/sh\n"
        'for arg do last="$arg"; done\n'
        '[ "$last" = "refs/heads/$AVAILABLE_HOST_BRANCH" ]\n'
    )
    git.chmod(0o755)
    curl = tmp_path / "curl"
    curl.write_text("#!/bin/sh\nprintf '%s' \"$OPEN_PR_RESPONSE\"\n")
    curl.chmod(0o755)
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "OPEN_PR_RESPONSE": '[{}]' if open_pr else '[]',
            "GITHUB_TOKEN": "test-token",
            "REQUESTED_REF": requested,
            "DEFAULT_HOST_REF": step["env"].get("DEFAULT_HOST_REF", "main"),
            "COMPANION_BRANCH": branch,
            "AVAILABLE_HOST_BRANCH": remote_branch,
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
        check=True,
    )
    assert output.read_text().strip() == "ref=" + expected, result.stdout


def test_every_lifecycle_job_shares_the_setup_and_feeds_the_aggregate_status():
    """The old required `lifecycle` check remains one status that waits for every area."""
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    for name in LIFECYCLE_JOBS:
        uses = [step.get("uses") for step in jobs[name]["steps"]]
        assert "./.github/actions/lifecycle-setup" in uses, name
        assert jobs[name]["needs"] == "gate"
    aggregate = jobs["lifecycle"]
    assert aggregate["if"] == "always()"
    assert set(aggregate["needs"]) == {"gate", *LIFECYCLE_JOBS}
