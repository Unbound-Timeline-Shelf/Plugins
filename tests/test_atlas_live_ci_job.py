"""The live Atlas contract job must never report success without having run the contract suite.

A green `atlas-live-contract` check has to mean the plugin was exercised against a real Atlas. When the
`ATLAS_CHECKOUT_TOKEN` secret is missing on a trusted run the job must fail with an error annotation, and no
step may be silently skipped on the strength of a credential check. Fork pull requests (which never get
secrets) are excluded at job level, so they show the job as skipped rather than passed.
"""

from pathlib import Path
import os
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
JOB = "atlas-live-contract"
CREDENTIAL_STEP = "Require read access to the Atlas repository"


def _job() -> dict:
    workflow = yaml.load((ROOT / ".github" / "workflows" / "ci.yml").read_text(), Loader=yaml.BaseLoader)
    return workflow["jobs"][JOB]


def _credential_step() -> dict:
    steps = [step for step in _job()["steps"] if step.get("name") == CREDENTIAL_STEP]
    assert len(steps) == 1, f"{JOB} must have exactly one step named {CREDENTIAL_STEP!r}"
    return steps[0]


def _run_credential_check(tmp_path: Path, token: str) -> subprocess.CompletedProcess:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not available to run the workflow step")
    step = _credential_step()
    script = tmp_path / "step.sh"
    script.write_text(step["run"], newline="\n")
    output, summary = tmp_path / "output", tmp_path / "summary"
    env = {
        **os.environ,
        "ATLAS_TOKEN": token,
        "ATLAS_REPOSITORY": _job()["env"]["ATLAS_REPOSITORY"],
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    return subprocess.run(
        [bash, "-e", script.as_posix()], env=env, capture_output=True, text=True, timeout=30
    )


def test_a_missing_token_fails_the_job_with_an_error_annotation(tmp_path):
    result = _run_credential_check(tmp_path, token="")
    assert result.returncode != 0, "a missing ATLAS_CHECKOUT_TOKEN must fail the job, not pass it"
    assert "::error" in result.stdout and "ATLAS_CHECKOUT_TOKEN" in result.stdout
    summary = tmp_path / "summary"
    assert summary.exists() and "did not run" in summary.read_text()


def test_a_configured_token_lets_the_job_continue(tmp_path):
    result = _run_credential_check(tmp_path, token="placeholder-not-a-secret")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::error" not in result.stdout


def test_no_step_is_skipped_on_the_strength_of_a_credential_check():
    # A step skipped because the credential was absent would let the job finish green without running
    # anything. Only the evidence upload may carry a condition, and it must be `always()` so failure logs
    # are kept.
    for step in _job()["steps"]:
        condition = step.get("if")
        if condition is None:
            continue
        assert "outputs" not in condition, f"step {step.get('name') or step.get('uses')} is gated on {condition!r}"
        assert condition.strip() == "always()", f"unexpected condition {condition!r}"


def test_the_contract_suite_step_is_unconditional():
    runs = [step for step in _job()["steps"] if "check_metadata_atlas_live.py" in step.get("run", "")]
    assert len(runs) == 1 and "if" not in runs[0]


def test_fork_pull_requests_are_excluded_at_job_level():
    assert "github.event.pull_request.head.repo.fork != true" in _job()["if"]


def test_failures_are_not_swallowed_by_continue_on_error():
    # `continue-on-error: true` on the job, the credential step or the suite step would turn a failed run into
    # a green check, which is the same "success without running" this module exists to prevent.
    assert "continue-on-error" not in _job(), f"{JOB} must not set continue-on-error at job level"
    for step in _job()["steps"]:
        assert "continue-on-error" not in step, (
            f"step {step.get('name') or step.get('uses')} sets continue-on-error, which can hide a failed run"
        )
