"""Real builder regressions: immutable versions, signatures, policies and metadata."""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.distribution import (
    ROOT,
    load_histories,
    validate_distribution,
    validate_immutable_history,
    validate_metadata,
)
from tools.validate_packages import validate_package


@pytest.fixture
def checkout(tmp_path):
    """Create an isolated real source checkout with an example-only test signer."""
    shutil.copyfile(ROOT / ".gitignore", tmp_path / ".gitignore")
    for name in ("tools", "sdk", "publishers"):
        shutil.copytree(
            ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    shutil.copytree(ROOT / "examples/help-button", tmp_path / "examples/help-button")
    # Give release-simulation tests a fixed SemVer seed independently of the
    # real plugin's automatically advancing version. Its implementation stays real.
    manifest_path = tmp_path / "examples/help-button/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "2.0.0"
    manifest_path.write_text(json.dumps(manifest))
    # A disposable publisher is registered only inside the isolated test checkout.
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes_raw()
    encoded = base64.b64encode(public).decode()
    (tmp_path / "publishers/test.public-key.b64").write_text(encoded)
    registry = {
        "schema_version": 1,
        "publishers": [
            {
                "key_id": "test",
                "publisher": "Unnamed Tracking Official",
                "public_key_file": "test.public-key.b64",
                "public_key_b64": encoded,
                "public_key_sha256": hashlib.sha256(public).hexdigest(),
                "status": "active",
                "plugin_id_prefixes": ["example."],
            }
        ],
    }
    (tmp_path / "publishers/registry.json").write_text(json.dumps(registry))
    env = {
        **os.environ,
        "PLUGIN_SIGNING_KEY_B64": base64.b64encode(key.private_bytes_raw()).decode(),
        "PLUGIN_SIGNING_KEY_ID": "test",
    }
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    commit(tmp_path, "feat: add example")
    return tmp_path, env


def commit(root, message):
    """Record a simulated source or publication change in the owned checkout."""
    subprocess.run(
        ["git", "-C", str(root), "add", "."], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", message],
        check=True,
        capture_output=True,
    )


def run_build(root, env, *flags, check=True):
    """Run the real builder with the fixture's scoped signing environment."""
    result = subprocess.run(
        [sys.executable, str(root / "tools/build_packages.py"), *flags],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr)
    return result


def records(root):
    """Read the generated release history used by versioning assertions."""
    return json.loads(
        (root / "releases/example.help-button.json").read_text(encoding="utf-8")
    )["releases"]


@pytest.mark.parametrize("version", ["0.0.1", "0.1.0", "1.2.3"])
def test_unreleased_official_preview_is_installable_without_expanding_signer_scope(
    checkout, version
):
    """Advanced source versions still produce valid unsigned official previews."""
    root, env = checkout
    shutil.copytree(
        ROOT / "official/jellyfin-media-sync", root / "official/jellyfin-media-sync"
    )
    # Signed publication advances the real source version before rerunning tests.
    # Exercise the same unsigned preview independently of that release sequence.
    manifest_path = root / "official/jellyfin-media-sync/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = version
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    config = {
        "name": "Disposable catalogue",
        "base_url": "https://example.invalid/plugins",
        "unreleased_plugins": ["official.jellyfin-media-sync"],
    }
    (root / "catalogue.json").write_text(json.dumps(config))
    commit(root, "feat: add independently installable preview")
    # The real official source is built unsigned by the existing developer flow.
    preview_env = {k: v for k, v in env.items() if not k.startswith("PLUGIN_SIGNING_")}
    run_build(root, preview_env)
    preview = root / f".validation/dist/official.jellyfin-media-sync-{version}.utp"
    validate_package(preview)
    with zipfile.ZipFile(preview) as archive:
        preview_manifest = json.loads(archive.read("manifest.json"))
    assert preview_manifest["plugin_id"] == "official.jellyfin-media-sync"
    assert preview_manifest["version"] == version
    assert not preview_manifest["integrity"].get("signature")
    validate_distribution(
        root / ".validation", source_root=root, include_unreleased=True
    )
    run_build(root, env, "--publish")
    assert {
        p["plugin_id"] for p in json.loads((root / "list.json").read_text())["plugins"]
    } == {"example.help-button"}
    assert not (root / "releases/official.jellyfin-media-sync.json").exists()
    commit(root, "chore: retain reviewed distribution")
    config["unreleased_plugins"] = []
    (root / "catalogue.json").write_text(json.dumps(config))
    commit(root, "feat: request official publication")
    denied = run_build(root, env, "--publish", check=False)
    assert denied.returncode != 0 and "scope" in denied.stderr.lower()


def test_signed_releases_preserve_history_and_release_specific_opt_out(checkout):
    root, env = checkout
    metadata_path = root / "examples/help-button/release.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["automatic_update"] = False
    metadata_path.write_text(json.dumps(metadata))
    commit(root, "fix: require manual approval for initial release")
    run_build(root, env, "--publish")
    first = records(root)[0]
    original = (root / "dist" / first["package"]["filename"]).read_bytes()
    assert first["automatic_update"] is False
    assert first["signing"]["signature"]
    commit(root, "chore: publish release")
    metadata["automatic_update"] = True
    metadata["release_notes"] = "Allow automatic updates for this patch."
    metadata_path.write_text(json.dumps(metadata))
    commit(root, "fix: correct release policy")
    run_build(root, env, "--publish")
    history = records(root)
    assert history[0] == first
    assert history[1]["version"] == "2.0.1"
    assert history[1]["automatic_update"] is True
    assert (root / "dist" / first["package"]["filename"]).read_bytes() == original
    commit(root, "chore: publish the policy patch")
    before = {
        p.relative_to(root).as_posix(): p.read_bytes()
        for d in ("dist", "releases")
        for p in (root / d).iterdir()
    }
    run_build(root, env, "--publish", "--reuse-published")
    assert before == {
        p.relative_to(root).as_posix(): p.read_bytes()
        for d in ("dist", "releases")
        for p in (root / d).iterdir()
    }


@pytest.mark.parametrize(
    "message,expected,automatic",
    [
        ("fix: correct behavior", "2.0.1", True),
        ("feat: add behavior", "2.1.0", True),
        ("feat!: change behavior", "3.0.0", False),
    ],
)
def test_versions_follow_conventional_commits(checkout, message, expected, automatic):
    root, env = checkout
    run_build(root, env, "--publish")
    commit(root, "chore: publish package")
    with (root / "examples/help-button/plugin.py").open("a") as stream:
        stream.write("\n# changed behavior\n")
    commit(root, message)
    run_build(root, env, "--publish")
    assert records(root)[-1]["version"] == expected
    assert records(root)[-1]["automatic_update"] is automatic


def test_missing_signer_and_changed_historical_artifact_fail_without_writes(checkout):
    root, env = checkout
    run_build(root, env, "--publish")
    commit(root, "chore: publish package")
    before = (root / "list.json").read_bytes()
    no_signer = {k: v for k, v in env.items() if not k.startswith("PLUGIN_SIGNING_KEY")}
    # Reusing an immutable verified release requires no retired private key.
    run_build(root, no_signer, "--publish")
    assert (root / "list.json").read_bytes() == before
    source = root / "examples/help-button/plugin.py"
    source.write_text(source.read_text() + "\n# New source needs a signer.\n")
    commit(root, "fix: require signing for a new release")
    result = run_build(root, no_signer, "--publish", check=False)
    assert result.returncode != 0 and "required" in result.stderr
    package = next((root / "dist").glob("*.utp"))
    package.write_bytes(package.read_bytes() + b"modified")
    result = run_build(root, env, "--publish", check=False)
    assert result.returncode != 0 and "historical package changed" in result.stderr
    assert (root / "list.json").read_bytes() == before


@pytest.mark.parametrize(
    "defect",
    [
        "package_hash",
        "missing_package",
        "release_policy",
        "version",
        "scope",
        "readme",
        "tag",
        "url",
    ],
)
def test_generated_metadata_corruption_is_rejected(
    built_distribution, tmp_path, defect
):
    shutil.copytree(built_distribution, tmp_path / "candidate")
    root = tmp_path / "candidate"
    path = root / "list.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data["plugins"][0]
    if defect == "missing_package":
        (root / "dist" / entry["package"]["filename"]).unlink()
    elif defect == "package_hash":
        entry["package_sha256"] = "0" * 64
    elif defect == "release_policy":
        entry["releases"][-1]["automatic_update"] = not entry["automatic_update"]
    elif defect == "version":
        entry["version"] = "99.0.0"
    elif defect == "scope":
        entry["permissions"] = []
    elif defect == "readme":
        entry["readme"] = "Wrong documentation"
    elif defect == "tag":
        entry["tags"] = ["Fake Category"]
    else:
        entry["url"] = "https://wrong.invalid/package.utp"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        validate_distribution(root)


@pytest.mark.parametrize(
    "values",
    [
        {"tags": ["Invalid tag"]},
        {"tags": ["games", "games"]},
        {"automatic_update": "false"},
        {"risk": "low"},
    ],
)
def test_invalid_tags_policies_and_plugin_defined_risk_are_rejected(values):
    metadata = {
        "schema_version": 1,
        "publisher": "Developer",
        "tags": [],
        "icon": None,
        "automatic_update": None,
        "release_notes": "",
    }
    with pytest.raises(ValueError):
        validate_metadata({**metadata, **values})


def test_preview_build_never_overwrites_published_distribution(built_distribution):
    history = load_histories(built_distribution)
    original = load_histories(ROOT)
    for plugin_id, releases in original.items():
        assert history[plugin_id][: len(releases)] == releases
        for release in releases:
            filename = release["package"]["filename"]
            assert (built_distribution / "dist" / filename).read_bytes() == (
                ROOT / "dist" / filename
            ).read_bytes()


@pytest.mark.parametrize(
    "plugin_id",
    [
        "example.ui-api",
        "example.playtime-report",
        "example.recently-played-notifier",
        "example.metadata-curator",
    ],
)
def test_packaged_workers_report_ready_and_remain_alive(
    current_packages, tmp_path, plugin_id
):
    with zipfile.ZipFile(current_packages[plugin_id]) as archive:
        for name in archive.namelist():
            if name.startswith("payload/"):
                path = tmp_path / name.removeprefix("payload/")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(name))
    worker = subprocess.Popen(
        [sys.executable, "-c", "import plugin; plugin.main()"],
        cwd=tmp_path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            worker.communicate(input=json.dumps({"payload": {}}) + "\n", timeout=0.5)
        assert worker.poll() is None
    finally:
        worker.terminate()
        output, error = worker.communicate(timeout=5)
    assert not error
    assert json.loads(output.splitlines()[0])["method"] == "lifecycle.ready"


@pytest.mark.parametrize(
    "defect",
    ["handler", "ui_shape", "risk", "range", "metadata_version", "missing_readme"],
)
def test_incompatible_new_packages_are_rejected(current_packages, tmp_path, defect):
    with zipfile.ZipFile(current_packages["example.playtime-report"]) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    document = json.loads(members["payload/ui.json"])
    metadata = json.loads(members["payload/distribution.json"])
    if defect == "handler":
        document["actions"][0]["handler"] = "plugin:missing"
    elif defect == "ui_shape":
        document["pages"][0]["components"] = []
    elif defect == "risk":
        manifest["permissions"][0]["risk"] = "low"
    elif defect == "range":
        manifest["sdk_version_range"] = ">=1.0.0 <2.0.0"
    elif defect == "metadata_version":
        metadata["version"] = "99.0.0"
    else:
        members.pop("payload/README.md")
    members["manifest.json"] = json.dumps(manifest).encode()
    members["payload/ui.json"] = json.dumps(document).encode()
    members["payload/distribution.json"] = json.dumps(metadata).encode()
    candidate = tmp_path / "invalid.utp"
    with zipfile.ZipFile(candidate, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    # Schema failures are jsonschema.ValidationError; cross-field failures are
    # ValueError. Both must reject the package rather than silently strip fields.
    from jsonschema import ValidationError

    with pytest.raises((ValueError, ValidationError)):
        validate_package(candidate, full=True)


def test_early_release_tag_and_dirty_publish_are_rejected(checkout):
    root, env = checkout
    result = run_build(root, env, "--publish", "--reuse-published", check=False)
    assert result.returncode != 0 and "already published" in result.stderr
    with (root / "examples/help-button/plugin.py").open("a") as stream:
        stream.write("\n# not committed\n")
    result = run_build(root, env, "--publish", check=False)
    assert result.returncode != 0 and "commit source" in result.stderr


def test_ci_rejects_rewriting_historical_release_metadata(checkout):
    root, env = checkout
    run_build(root, env, "--publish")
    commit(root, "chore: publish release")
    validate_immutable_history(root, root, "HEAD")
    history_path = root / "releases/example.help-button.json"
    data = json.loads(history_path.read_text(encoding="utf-8"))
    data["releases"][0]["release_notes"] = "Changed historical notes"
    history_path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="historical release metadata"):
        validate_immutable_history(root, root, "HEAD")


def test_ci_checks_baseline_catalogue_releases_against_history_files(checkout):
    """A baseline whose history was only embedded in list.json is still preserved."""
    root, env = checkout
    run_build(root, env, "--publish")
    commit(root, "chore: publish release")
    history_path = root / "releases/example.help-button.json"
    subprocess.run(
        ["git", "-C", str(root), "rm", "-q", "--cached", str(history_path)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "chore: legacy baseline"],
        check=True,
        capture_output=True,
    )
    validate_immutable_history(root, root, "HEAD")
    data = json.loads(history_path.read_text(encoding="utf-8"))
    data["releases"][0]["release_notes"] = "Changed historical notes"
    history_path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="baseline catalogue release"):
        validate_immutable_history(root, root, "HEAD")


def test_ci_rejects_source_and_catalogue_removal_even_with_retained_history(checkout):
    root, env = checkout
    run_build(root, env, "--publish")
    commit(root, "chore: publish release")
    shutil.rmtree(root / "examples/help-button")
    catalogue = json.loads((root / "list.json").read_bytes())
    catalogue["plugins"] = []
    (root / "list.json").write_text(json.dumps(catalogue), encoding="utf-8")
    with pytest.raises(ValueError, match="disappeared from catalogue"):
        validate_immutable_history(root, root, "HEAD")


@pytest.mark.parametrize(
    "field",
    [
        "sha256",
        "package_sha256",
        "manifest",
        "signing",
        "publisher",
        "version",
        "readme",
        "tags",
        "automatic_update",
        "release_notes",
    ],
)
def test_every_release_metadata_field_is_checked_against_package(
    built_distribution, tmp_path, field
):
    root = tmp_path / "candidate"
    shutil.copytree(built_distribution, root)
    path = root / "releases/example.help-button.json"
    document = json.loads(path.read_bytes())
    document["releases"][-1][field] = None
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises((ValueError, TypeError, KeyError)):
        validate_distribution(root)


def test_package_generation_rejects_unindexed_output(built_distribution, tmp_path):
    root = tmp_path / "candidate"
    shutil.copytree(built_distribution, root)
    original = next((root / "dist").glob("*.utp"))
    shutil.copyfile(original, root / "dist/unindexed.utp")
    with pytest.raises(ValueError, match="untracked packages"):
        validate_distribution(root)


def test_new_example_requires_explicit_unreleased_identity(tmp_path):
    from tools.distribution import catalogue_document

    source = tmp_path / "examples/new-example"
    source.mkdir(parents=True)
    manifest = {"plugin_id": "example.new-example"}
    with pytest.raises(ValueError, match="missing release history"):
        catalogue_document(tmp_path, [(source, manifest)], {})
    config = {
        "name": "Preview",
        "base_url": "https://example.invalid/plugins",
        "unreleased_plugins": ["example.new-example"],
    }
    (tmp_path / "catalogue.json").write_text(json.dumps(config))
    assert catalogue_document(tmp_path, [(source, manifest)], {})["plugins"] == []
    config["unreleased_plugins"] = ["example.other"]
    (tmp_path / "catalogue.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="missing release history"):
        catalogue_document(tmp_path, [(source, manifest)], {})



def notification_preview_checkout(checkout):
    """Use the real demo sources with the isolated fixture's example-only key."""
    root, env = checkout
    ids = ["example.password-reset-notification-demo", "example.user-invite-notification-demo"]
    for name in ("password-reset-notification-demo", "user-invite-notification-demo"):
        shutil.copytree(ROOT / "examples" / name, root / "examples" / name)
    config = {"name": "Notification test catalogue", "base_url": "https://example.invalid/plugins",
              "unreleased_plugins": ids}
    (root / "catalogue.json").write_text(json.dumps(config), encoding="utf-8")
    commit(root, "feat: add notification source previews")
    return root, env, ids, config


def test_explicit_notification_promotion_signs_before_removing_preview_policy(checkout):
    root, env, ids, config = notification_preview_checkout(checkout)
    run_build(root, env, "--publish")
    original = records(root)[0]
    original_bytes = (root / "dist" / original["package"]["filename"]).read_bytes()
    assert not (root / "releases" / f"{ids[0]}.json").exists()
    assert json.loads((root / "catalogue.json").read_text()) == config
    commit(root, "chore: publish existing distribution")

    run_build(root, env, "--publish", "--promote-plugin", ids[0])
    promoted = json.loads((root / "releases" / f"{ids[0]}.json").read_text())["releases"][0]
    assert promoted["lifecycle"] == "published" and promoted["signing"]["signature"]
    assert json.loads((root / "catalogue.json").read_text()) == {
        **config, "unreleased_plugins": [ids[1]]}
    assert {p["plugin_id"] for p in json.loads((root / "list.json").read_text())["plugins"]} == {
        "example.help-button", ids[0]}
    assert not (root / "releases" / f"{ids[1]}.json").exists()
    assert (root / "dist" / original["package"]["filename"]).read_bytes() == original_bytes
    subprocess.run([sys.executable, str(root / "tools/distribution.py"), "--check-source"],
                   env=env, check=True, capture_output=True)
    commit(root, "chore: publish first notification demo")

    run_build(root, env, "--publish", "--promote-plugin", ids[1])
    assert json.loads((root / "catalogue.json").read_text())["unreleased_plugins"] == []
    assert json.loads((root / "releases" / f"{ids[0]}.json").read_text())["releases"] == [promoted]
    subprocess.run([sys.executable, str(root / "tools/distribution.py"), "--check-source"],
                   env=env, check=True, capture_output=True)


@pytest.mark.parametrize("flags", [[], ["--catalogue-only"], ["--publish", "--reuse-published"],
                                  ["--publish", "--promote-plugin", "example.unknown"],
                                  ["--publish", "--promote-plugin", "example.help-button"],
                                  ["--publish", "--promote-plugin", "example.password-reset-notification-demo"]])
def test_invalid_promotion_leaves_policy_and_distribution_untouched(checkout, flags):
    root, env, ids, _ = notification_preview_checkout(checkout)
    before = (root / "catalogue.json").read_bytes()
    rejected = run_build(root, env, *flags, "--promote-plugin", ids[0], check=False)
    assert rejected.returncode != 0
    assert "promotion" in rejected.stderr.lower()
    assert (root / "catalogue.json").read_bytes() == before
    assert not (root / "dist").exists() and not (root / "releases").exists()


def test_missing_signer_cannot_promote_notification_demo(checkout):
    root, env, ids, _ = notification_preview_checkout(checkout)
    # No private key is retained outside this disposable test checkout.
    no_signer = {k: v for k, v in env.items() if not k.startswith("PLUGIN_SIGNING_")}
    before = (root / "catalogue.json").read_bytes()
    rejected = run_build(root, no_signer, "--publish", "--promote-plugin", ids[0], check=False)
    assert rejected.returncode != 0 and "required" in rejected.stderr
    assert (root / "catalogue.json").read_bytes() == before
    assert not (root / "dist").exists() and not (root / "releases").exists()



def test_multiple_notification_previews_can_be_promoted_together(checkout):
    root, env, ids, _ = notification_preview_checkout(checkout)
    run_build(root, env, "--publish", "--promote-plugin", ids[0], "--promote-plugin", ids[1])
    assert json.loads((root / "catalogue.json").read_text())["unreleased_plugins"] == []
    assert {p["plugin_id"] for p in json.loads((root / "list.json").read_text())["plugins"]} == {
        "example.help-button", *ids}
    for plugin_id in ids:
        history = json.loads((root / "releases" / f"{plugin_id}.json").read_text())["releases"]
        assert len(history) == 1 and history[0]["signing"]["signature"]


def test_promotion_does_not_expand_signer_scope(checkout):
    root, env, ids, _ = notification_preview_checkout(checkout)
    registry_path = root / "publishers/registry.json"
    registry = json.loads(registry_path.read_text())
    registry["publishers"][0]["plugin_id_prefixes"] = ["example.help-button"]
    registry_path.write_text(json.dumps(registry))
    commit(root, "chore: restrict disposable signing key")
    before = (root / "catalogue.json").read_bytes()
    rejected = run_build(root, env, "--publish", "--promote-plugin", ids[0], check=False)
    assert rejected.returncode != 0 and "scope" in rejected.stderr.lower()
    assert (root / "catalogue.json").read_bytes() == before
    assert not (root / "dist").exists() and not (root / "releases").exists()
