"""The actual builder selects distinct folder signers and fails atomically."""

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

from tools.distribution import ROOT
from tools.validate_packages import validate_package


def build(root, env, *flags):
    return subprocess.run(
        [sys.executable, str(root / "tools/build_packages.py"), *flags],
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture(name="scoped_checkout")
def scoped_checkout_fixture(tmp_path):
    """Provide an isolated signer checkout without shadowing the test arguments."""
    for name in ("tools", "sdk"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "official/pwa", tmp_path / "official/pwa")
    for folder, identity in (("examples", "example.signing"), ("plugins", "community.signing")):
        source = tmp_path / folder / "signing"
        shutil.copytree(ROOT / "official/pwa", source)
        manifest = json.loads((source / "manifest.json").read_text())
        manifest.update(plugin_id=identity, capabilities=[], permissions=[], pwa=None)
        (source / "manifest.json").write_text(json.dumps(manifest))
        document = json.loads((source / "ui.json").read_text())
        document["plugin_id"] = identity
        (source / "ui.json").write_text(json.dumps(document))
    records = []
    env = {k: v for k, v in os.environ.items() if not k.startswith("PLUGIN_")}
    for channel, prefix, scope in (
        ("official", "PLUGIN_OFFICIAL_SIGNING", "official."),
        ("demo", "PLUGIN_EXAMPLES_SIGNING", "example."),
        ("community", "PLUGIN_SIGNING", "community."),
    ):
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes_raw()
        encoded = base64.b64encode(public).decode()
        path = tmp_path / "publishers" / f"{channel}.public-key.b64"
        path.parent.mkdir(exist_ok=True)
        path.write_text(encoded)
        records.append(
            {
                "key_id": channel,
                "publisher": "Unnamed Tracking Official",
                "channel": channel,
                "public_key_file": path.name,
                "public_key_b64": encoded,
                "public_key_sha256": hashlib.sha256(public).hexdigest(),
                "status": "active",
                "plugin_id_prefixes": [scope],
            }
        )
        env[prefix + "_KEY_ID"] = channel
        env[prefix + "_KEY_B64"] = base64.b64encode(key.private_bytes_raw()).decode()
    (tmp_path / "publishers/registry.json").write_text(
        json.dumps({"schema_version": 1, "publishers": records})
    )
    (tmp_path / ".gitignore").write_text(".validation/\n__pycache__/\n")
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "feat: prepare scoped signers"],
        check=True,
        capture_output=True,
    )
    return tmp_path, env


@pytest.fixture(name="pwa_version")
def pwa_version_fixture(scoped_checkout):
    """Use the reviewed source patch while preserving the PWA's 0.0.x boundary."""
    root, _ = scoped_checkout
    version = json.loads((root / "official/pwa/manifest.json").read_text())["version"]
    assert version.startswith("0.0.")
    assert version.removeprefix("0.0.").isdigit()
    return version


def test_real_publish_uses_three_independent_keys(scoped_checkout):
    root, env = scoped_checkout
    result = build(root, env, "--publish")
    assert result.returncode == 0, result.stderr
    seen = {}
    for package in (root / "dist").glob("*.utp"):
        with zipfile.ZipFile(package) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["integrity"]["signature"].startswith("v2:")
            seen[manifest["plugin_id"]] = manifest["integrity"]["key_id"]
        result = subprocess.run(
            [sys.executable, str(root / "tools/verify_packages.py"), str(package)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    assert seen == {
        "official.pwa": "official",
        "example.signing": "demo",
        "community.signing": "community",
    }


def test_game_night_promotion_signs_the_actual_source_and_keeps_other_previews(scoped_checkout):
    root, env = scoped_checkout
    for name in ("discord-bot-notifications", "discord-social-activity"):
        shutil.copytree(ROOT / "official" / name, root / "official" / name,
                        ignore=shutil.ignore_patterns("__pycache__"))
    plugin_id = "official.discord-social-activity"
    config = {"name": "Promotion test", "base_url": "https://example.invalid/plugins",
              "unreleased_plugins": [plugin_id, "community.signing"]}
    (root / "catalogue.json").write_text(json.dumps(config))
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "feat: prepare Game Night"],
                   check=True, capture_output=True)

    result = build(root, env, "--publish", "--promote-plugin", plugin_id)
    assert result.returncode == 0, result.stderr
    entry = next(item for item in json.loads((root / "list.json").read_text())["plugins"]
                 if item["plugin_id"] == plugin_id)
    assert entry["publisher"] == "Unnamed Tracking Official"
    assert entry["signing"]["key_id"] == "official"
    assert entry["signing"]["signature"].startswith("v2:")
    assert entry["lifecycle"] == "published"
    assert entry["automatic_update"] is False
    assert json.loads((root / "catalogue.json").read_text())["unreleased_plugins"] == ["community.signing"]
    assert not list((root / "dist").glob("community.signing-*.utp"))
    package = root / "dist" / entry["package"]["filename"]
    result = subprocess.run([sys.executable, str(root / "tools/verify_packages.py"), str(package)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "folder,prefix,signer",
    [
        ("examples", "PLUGIN_EXAMPLES_SIGNING", "demo"),
        ("official", "PLUGIN_OFFICIAL_SIGNING", "official"),
    ],
)
def test_missing_folder_pair_can_use_appropriately_scoped_generic(
    scoped_checkout, folder, prefix, signer
):
    root, env = scoped_checkout
    for suffix in ("_KEY_ID", "_KEY_B64"):
        env["PLUGIN_SIGNING" + suffix] = env.pop(prefix + suffix)
    # This fixture's generic plugin has an unrelated scope; keep this test
    # focused on the requested folder and its real publication verification.
    shutil.rmtree(root / "plugins")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "chore: isolate fallback scope"],
        check=True,
        capture_output=True,
    )
    env["PLUGIN_SIGNING_FALLBACK"] = "generic"
    result = build(root, env, "--publish")
    assert result.returncode == 0, result.stderr
    plugin_id = "example.signing" if folder == "examples" else "official.pwa"
    package = next((root / "dist").glob(plugin_id + "-*.utp"))
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["integrity"]["key_id"] == signer
    verified = subprocess.run(
        [sys.executable, str(root / "tools/verify_packages.py"), str(package)],
        capture_output=True,
        text=True,
    )
    assert verified.returncode == 0, verified.stderr


def test_registered_community_generic_can_sign_examples_without_official_trust(scoped_checkout):
    root, env = scoped_checkout
    env.pop("PLUGIN_EXAMPLES_SIGNING_KEY_ID")
    env.pop("PLUGIN_EXAMPLES_SIGNING_KEY_B64")
    env["PLUGIN_SIGNING_FALLBACK"] = "generic"
    path = root / "publishers/registry.json"
    registry = json.loads(path.read_text())
    next(r for r in registry["publishers"] if r["channel"] == "community")[
        "plugin_id_prefixes"
    ].append("example.")
    path.write_text(json.dumps(registry))
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "chore: authorize community example fallback"],
        check=True,
        capture_output=True,
    )
    result = build(root, env, "--publish")
    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(next((root / "dist").glob("example.signing-*.utp"))) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["integrity"]["key_id"] == "community"


def test_configured_unknown_key_explains_public_registration(scoped_checkout):
    root, env = scoped_checkout
    env["PLUGIN_OFFICIAL_SIGNING_KEY_ID"] = "not-registered"
    result = build(root, env, "--publish")
    assert result.returncode != 0
    assert "adding Actions secrets alone does not register a publisher" in result.stderr
    assert "publishers/registry.json" in result.stderr
    assert env["PLUGIN_OFFICIAL_SIGNING_KEY_B64"] not in result.stderr
    assert not (root / "dist").exists()


def test_unrelated_generic_key_cannot_rescue_missing_official_key(scoped_checkout):
    root, env = scoped_checkout
    env.pop("PLUGIN_OFFICIAL_SIGNING_KEY_ID")
    env.pop("PLUGIN_OFFICIAL_SIGNING_KEY_B64")
    env["PLUGIN_SIGNING_FALLBACK"] = "generic"
    result = build(root, env, "--publish")
    assert result.returncode != 0
    assert "PLUGIN_SIGNING identity rejected" in result.stderr
    assert "outside the plugin scope" in result.stderr
    assert not (root / "dist").exists()


@pytest.mark.parametrize("defect", ["missing", "partial", "malformed", "demo", "unknown"])
def test_official_signing_failure_never_publishes_or_downgrades(scoped_checkout, defect):
    root, env = scoped_checkout
    if defect == "missing":
        env.pop("PLUGIN_OFFICIAL_SIGNING_KEY_ID")
        env.pop("PLUGIN_OFFICIAL_SIGNING_KEY_B64")
        env["PLUGIN_SIGNING_FALLBACK"] = "unsigned"
    elif defect == "partial":
        env.pop("PLUGIN_OFFICIAL_SIGNING_KEY_ID")
    elif defect == "malformed":
        env["PLUGIN_OFFICIAL_SIGNING_KEY_B64"] = "not base64"
    elif defect == "demo":
        for suffix in ("_KEY_ID", "_KEY_B64"):
            env["PLUGIN_OFFICIAL_SIGNING" + suffix] = env["PLUGIN_EXAMPLES_SIGNING" + suffix]
    else:
        env["PLUGIN_OFFICIAL_SIGNING_KEY_ID"] = "unknown"
    result = build(root, env, "--publish")
    assert result.returncode != 0
    assert not (root / "list.json").exists()
    assert not (root / "dist").exists()


def test_unsigned_preview_is_explicit_and_keeps_zero_zero_version(scoped_checkout, pwa_version):
    """An SDK patch preserves the separately reviewed mobile asset version."""
    root, env = scoped_checkout
    asset_version = json.loads((root / "official/pwa/pwa/version.json").read_text())["version"]
    assert asset_version.startswith("0.0.")
    assert int(pwa_version.split(".")[2]) >= int(asset_version.split(".")[2])
    env = {k: v for k, v in env.items() if "SIGNING_KEY" not in k}
    env["PLUGIN_SIGNING_FALLBACK"] = "unsigned"
    result = build(root, env)
    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(root / f".validation/dist/official.pwa-{pwa_version}.utp") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["version"] == pwa_version
        assert manifest["api_contract_version"] == "1.1.0"
        assert json.loads(archive.read("payload/pwa/version.json"))["version"] == asset_version
        provenance = json.loads(archive.read("payload/pwa/provenance.json"))
        assert provenance["version"] == asset_version
        assert provenance["sha256"]["version.json"] == hashlib.sha256(
            archive.read("payload/pwa/version.json").replace(b"\r\n", b"\n")
        ).hexdigest()
        assert manifest["integrity"]["signature"] is None
        assert manifest["integrity"]["key_id"] is None
    assert not (root / "list.json").exists()


def test_changed_pwa_needs_explicit_patch_even_after_breaking_commit(scoped_checkout, pwa_version):
    """A breaking commit cannot bypass manual 0.0.x PWA release selection."""
    root, env = scoped_checkout
    result = build(root, env, "--publish")
    assert result.returncode == 0, result.stderr
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "chore: retain signed releases"],
        check=True,
        capture_output=True,
    )
    readme = root / "official/pwa/README.md"
    readme.write_text(readme.read_text() + "\nChanged behavior.\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "feat!: change PWA behavior"],
        check=True,
        capture_output=True,
    )
    result = build(root, env, "--publish")
    assert result.returncode != 0
    assert "explicit new 0.0.x patch" in result.stderr
    assert {p.name for p in (root / "dist").glob("official.pwa-*.utp")} == {
        f"official.pwa-{pwa_version}.utp"
    }


@pytest.mark.parametrize("version", ["0.1.0", "1.0.0"])
def test_pwa_stable_promotion_is_rejected(scoped_checkout, version):
    root, env = scoped_checkout
    path = root / "official/pwa/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["version"] = version
    path.write_text(json.dumps(manifest))
    result = build(root, env)
    assert result.returncode != 0
    assert "must remain 0.0.x" in result.stderr
    assert not (root / ".validation/list.json").exists()


def test_packaged_pwa_rejects_source_provenance_drift(scoped_checkout, pwa_version):
    """Changed offline assets invalidate the reviewed source hashes."""
    root, env = scoped_checkout
    result = build(root, env)
    assert result.returncode == 0, result.stderr
    source = root / f".validation/dist/official.pwa-{pwa_version}.utp"
    changed = root / "changed.utp"
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(changed, "w") as archive:
        for name in original.namelist():
            data = original.read(name)
            if name == "payload/pwa/offline.html":
                data += b"<!-- changed -->"
            archive.writestr(name, data)
    with pytest.raises(ValueError, match="provenance hash differs"):
        validate_package(changed, full=True)


def test_packaged_pwa_accepts_current_and_legacy_source_repositories(scoped_checkout, pwa_version):
    root, env = scoped_checkout
    result = build(root, env)
    assert result.returncode == 0, result.stderr
    source = root / f".validation/dist/official.pwa-{pwa_version}.utp"
    with zipfile.ZipFile(source) as original:
        contents = {name: original.read(name) for name in original.namelist()}
    name = "payload/pwa/provenance.json"
    provenance = json.loads(contents[name])
    candidate = root / "provenance-test.utp"
    for identity in (
        "Unbound-Timeline-Shelf/Mobile-Apps",
        "obsoletelabs/unnamed-tracking-mobile-app",
        "Rosefall-a/unnamed-tracking-mobile-app",
        "unrelated/project",
    ):
        with zipfile.ZipFile(candidate, "w") as archive:
            for entry, data in contents.items():
                if entry == name:
                    data = json.dumps({**provenance, "repository": identity}).encode()
                archive.writestr(entry, data)
        if identity == "unrelated/project":
            with pytest.raises(ValueError, match="provenance identity"):
                validate_package(candidate, full=True)
        else:
            validate_package(candidate, full=True)
