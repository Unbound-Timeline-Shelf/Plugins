"""Exercise real reference packages using the host's actual runtime registry.

This complements (and never replaces) PostgreSQL/HTTP permission acceptance in
the host's check_plugin_repository_lifecycle.py. Run on Linux; the real runtime
uses POSIX process groups/resource limits. No host/runtime implementation lives
here and no grants, gateway or supervisor are mocked.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("ui-api", "playtime-report", "recently-played-notifier", "metadata-curator",
         "password-reset-notification-demo", "user-invite-notification-demo",
         "notification-chaos-provider")
SOURCE_PATHS = tuple(Path("examples") / name for name in NAMES) + (Path("official/discord-notifications"),)
# Sources whose contract the ordinary companion host does not offer yet: each runs alone with ``--source``
# against a host that does (CI: the pinned Plugin API 1.1.20 books host, C15 6.3-6.4).
BOOKS_HOST_SOURCES = (Path("official/metadata-openlibrary"),)


def commit(root: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", message], check=True, capture_output=True)


def releases(root: Path, env: dict) -> dict[str, Path]:
    subprocess.run([sys.executable, str(root / "tools/build_packages.py"), "--publish"],
                   env=env, check=True)
    data = json.loads((root / "list.json").read_text(encoding="utf-8"))
    commit(root, "chore: publish disposable acceptance packages")
    return {e["plugin_id"]: root / "dist" / e["package"]["filename"] for e in data["plugins"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-root", type=Path, required=True)
    parser.add_argument("--temporary-root", type=Path)
    parser.add_argument("--source", type=Path, action="append",
                        help="exercise only this plugin source (repeatable); default: the reference set")
    args = parser.parse_args()
    sources = tuple(args.source or SOURCE_PATHS)
    if any(not (ROOT / source / "manifest.json").is_file() for source in sources):
        parser.error("--source must name a plugin source directory such as official/metadata-openlibrary")
    if os.name != "posix":
        parser.error("real worker acceptance requires Linux; run the required lifecycle CI job")
    sys.path.insert(0, str(args.host_root.resolve() / "src/plugin-runtime"))
    sys.path.insert(0, str(args.host_root.resolve() / "src/backend"))
    from runtime import PluginRegistry, PluginSupervisor, RuntimePolicyError
    from src.plugin_api.updates import PluginPackageVerifier, TrustedPublisher

    with tempfile.TemporaryDirectory(dir=args.temporary_root) as temporary:
        work = Path(temporary)
        source = work / "source"
        for directory in ("tools", "sdk", "publishers"):
            shutil.copytree(ROOT / directory, source / directory,
                            ignore=shutil.ignore_patterns("__pycache__"))
        for relative in sources:
            shutil.copytree(ROOT / relative, source / relative)
        shutil.copyfile(ROOT / ".gitignore", source / ".gitignore")
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes_raw()
        encoded = base64.b64encode(public).decode()
        (source / "publishers/disposable.public-key.b64").write_text(encoded, encoding="utf-8")
        record = {"key_id": "disposable", "publisher": "Unnamed Tracking Official",
                  "public_key_file": "disposable.public-key.b64", "public_key_b64": encoded,
                  "public_key_sha256": hashlib.sha256(public).hexdigest(), "status": "active",
                  "plugin_id_prefixes": ["example."]}
        official_key = Ed25519PrivateKey.generate()
        official_public = official_key.public_key().public_bytes_raw()
        official_encoded = base64.b64encode(official_public).decode()
        (source / "publishers/disposable-official.public-key.b64").write_text(official_encoded, encoding="utf-8")
        official_record = {"key_id": "disposable-official", "publisher": "Unnamed Tracking Official",
                           "public_key_file": "disposable-official.public-key.b64", "public_key_b64": official_encoded,
                           "public_key_sha256": hashlib.sha256(official_public).hexdigest(), "status": "active",
                           "plugin_id_prefixes": ["official."], "channel": "official"}
        (source / "publishers/registry.json").write_text(
            json.dumps({"schema_version": 1, "publishers": [record, official_record]}), encoding="utf-8")
        subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
        for name, value in (("user.name", "Acceptance"), ("user.email", "acceptance@example.invalid")):
            subprocess.run(["git", "-C", str(source), "config", name, value], check=True)
        commit(source, "feat: initialize real reference acceptance")
        env = {**os.environ, "PLUGIN_SIGNING_KEY_ID": "disposable",
               "PLUGIN_SIGNING_KEY_B64": base64.b64encode(key.private_bytes_raw()).decode(),
               "PLUGIN_OFFICIAL_SIGNING_KEY_ID": "disposable-official",
               "PLUGIN_OFFICIAL_SIGNING_KEY_B64": base64.b64encode(official_key.private_bytes_raw()).decode()}
        first = releases(source, env)
        # A real source input changes, so the existing version policy builds a patch.
        for relative in sources:
            path = source / relative / "README.md"
            with path.open("a", encoding="utf-8") as stream:
                stream.write("\nDisposable lifecycle acceptance patch.\n")
        commit(source, "fix: document acceptance transition")
        second = releases(source, env)
        # Package-side permission delta; the HTTP acceptance independently tests
        # actual grants and rejection/staging while the old package stays active.
        for relative in sources:
            path = source / relative / "manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            ref = {"name": "media.read", "version": 1}
            manifest["capabilities"].append(ref)
            manifest["permissions"].append({"capability": ref, "rationale": "Disposable permission delta"})
            path.write_text(json.dumps(manifest), encoding="utf-8")
        commit(source, "feat: exercise permission transition")
        third = releases(source, env)
        # A valid signed package whose real entrypoint cannot activate. This is
        # a runtime failure, not malformed ZIP bytes or a mocked health result.
        for relative in sources:
            with (source / relative / "plugin.py").open("a", encoding="utf-8") as stream:
                stream.write('\n\ndef main() -> None:\n    raise RuntimeError("Disposable activation failure")\n')
        commit(source, "fix: exercise failed activation restoration")
        broken = releases(source, env)
        verifier = PluginPackageVerifier({"disposable": TrustedPublisher(
            key_id="disposable", public_key=public, publisher=record["publisher"],
            status="active", plugin_id_prefixes=("example.",)),
            "disposable-official": TrustedPublisher(
                key_id="disposable-official", public_key=official_public, publisher=record["publisher"],
                status="active", plugin_id_prefixes=("official.",), channel="official")})
        supervisor = PluginSupervisor(work / "workers", work / "runtime/.storage")
        supervisor.probe_isolation()
        registry = PluginRegistry(work / "runtime", supervisor)
        try:
            for plugin_id, package in first.items():
                identity = str(uuid4())
                activation_user = str(uuid4()) if plugin_id == "example.notification-chaos-provider" else "acceptance-user"

                def active():
                    return next(p for p in registry.list() if p["plugin_id"] == plugin_id)

                def stage(path, replace=False):
                    verifier.inspect(path)
                    operation = str(uuid4())
                    registry.install_package(path.read_bytes(), path.name,
                        installation_id=identity, replace=replace, operation_id=operation,
                        expected_version=active()["version"] if replace else None)
                    try:
                        registry.start(plugin_id)
                    except RuntimePolicyError as exc:
                        assert "permission commit" in str(exc)
                    else:
                        raise AssertionError("uncommitted package started")
                    return operation

                def install(path, replace=False):
                    operation = stage(path, replace)
                    registry.finish_installation(plugin_id, operation, commit=True)
                    registry.start(plugin_id, user_id=activation_user)
                    assert registry.health(plugin_id), registry.diagnostics(plugin_id)
                    registry.finish_activation(plugin_id, operation, commit=True)

                install(package)
                if plugin_id == "example.notification-chaos-provider":
                    actor = activation_user
                    render_work = {"delivery": {"notification_id": str(uuid4())}}

                    def render():
                        return registry.notification_layout(plugin_id, "render", render_work,
                            user_id=actor, installation_id=identity, attempt_id=str(uuid4()))

                    from notification_renderer_acceptance import renderer_host
                    with renderer_host(args.host_root.resolve(), registry, actor, plugin_id, identity):
                        registry.settings(plugin_id, {"mode": "plain"})
                        assert render() == {"style": "plain", "fields": ["link", "event_at", "body", "title"]}
                        registry.settings(plugin_id, {"mode": "fail_first"})
                        try:
                            render()
                        except RuntimePolicyError:
                            pass
                        else:
                            raise AssertionError("demo did not simulate first renderer failure")
                        assert render()["style"] == "embed"
                        registry.stop(plugin_id)
                        registry.start(plugin_id, user_id=actor)
                        assert render()["style"] == "embed", "simulation ledger did not survive restart"
                        registry.settings(plugin_id, {"mode": "invalid_layout"})
                        import jsonschema
                        schema = json.loads((ROOT / "tools/schemas/notification-layout-v1.schema.json").read_text())
                        try:
                            jsonschema.validate(render(), schema)
                        except jsonschema.ValidationError:
                            pass
                        else:
                            raise AssertionError("invalid demo layout unexpectedly conformed")
                        registry.settings(plugin_id, {"mode": "always_fail"})
                        for _ in range(3):
                            try:
                                render()
                            except RuntimePolicyError:
                                pass
                            else:
                                raise AssertionError("always-fail demo rendered successfully")
                        registry.settings(plugin_id, {"mode": "embed"})
                        print(f"{plugin_id}: actual packaged renderer modes and restart persistence passed", flush=True)
                configured = {"display_mode": "compact", "query": "Acceptance"}
                settings = {field["id"]: configured.get(field["id"], field.get("default"))
                            for section in registry.ui(plugin_id).get("settings", [])
                            for field in section.get("fields", [])}
                registry.settings(plugin_id, settings)
                registry.storage_put(plugin_id, "users/acceptance-user/sentinel", "persisted")
                storage = work / "runtime/.storage" / plugin_id
                configuration = work / "runtime/.configuration" / f"{plugin_id}.json"
                baseline = {p.relative_to(storage): p.read_bytes() for p in storage.rglob("*") if p.is_file()}
                assert baseline

                def preserved():
                    assert active()["installation_id"] == identity
                    assert json.loads(configuration.read_text(encoding="utf-8")) == settings
                    assert all((storage / p).read_bytes() == data for p, data in baseline.items())
                    assert registry.health(plugin_id)

                supervisor.stop_all()
                supervisor = PluginSupervisor(work / "workers", work / "runtime/.storage")
                supervisor.probe_isolation()
                registry = PluginRegistry(work / "runtime", supervisor)
                registry.restore_enabled()
                preserved()
                registry.stop(plugin_id)
                assert active()["enabled"] is False
                registry.start(plugin_id)
                preserved()
                install(second[plugin_id], replace=True)
                preserved()
                with zipfile.ZipFile(package) as archive:
                    assert active()["version"] != json.loads(archive.read("manifest.json"))["version"]
                # Runtime rollback installs its own retained package, never a fake host.
                history = active()["history"][0]
                rollback = work / "rollback.utp"
                rollback.write_bytes(base64.b64decode(registry.package_archive(plugin_id, history["id"])["package"]))
                install(rollback, replace=True)
                assert active()["version"] == history["version"]
                preserved()
                previous_digest = registry.package(plugin_id)[1]["integrity"]["sha256"]
                rejected = stage(third[plugin_id], replace=True)
                registry.finish_installation(plugin_id, rejected, commit=False)
                assert registry.package(plugin_id)[1]["integrity"]["sha256"] == previous_digest
                preserved()
                install(third[plugin_id], replace=True)
                assert any(p["capability"]["name"] == "media.read" for p in registry.package(plugin_id)[1]["permissions"])
                preserved()
                reinstall = work / "reinstall.utp"
                reinstall.write_bytes(base64.b64decode(registry.package_archive(plugin_id)["package"]))
                install(reinstall, replace=True)
                preserved()
                previous_manifest = registry.package(plugin_id)[1]
                previous_payload = {
                    p.relative_to(registry.package(plugin_id)[0]): p.read_bytes()
                    for p in registry._payload_files(registry.package(plugin_id)[0])
                }
                failed = stage(broken[plugin_id], replace=True)
                registry.finish_installation(plugin_id, failed, commit=True)
                try:
                    registry.start(plugin_id, user_id=activation_user)
                except RuntimePolicyError:
                    pass
                assert not registry.health(plugin_id), "broken candidate was reported healthy"
                registry.finish_activation(plugin_id, failed, commit=False)
                restored, manifest = registry.package(plugin_id)
                assert manifest == previous_manifest
                assert {p.relative_to(restored): p.read_bytes() for p in registry._payload_files(restored)} == previous_payload
                preserved()
                registry.stop(plugin_id)
                registry.purge_data(plugin_id)
                assert not configuration.exists() and not storage.exists()
                registry.start(plugin_id)
                assert registry.health(plugin_id)
                # Recreate data after purge so uninstall proves deletion of
                # nonempty state, rather than checking an already-empty store.
                registry.storage_put(plugin_id, "uninstall-sentinel", "must be deleted")
                registry.settings(plugin_id, settings)
                assert storage.exists() and configuration.exists()
                registry.delete(plugin_id)
                assert not storage.exists() and not configuration.exists()
                assert not (work / "runtime" / plugin_id).exists()
                assert not (work / "runtime/.history" / plugin_id).exists()
                assert all(p["plugin_id"] != plugin_id for p in registry.list())
                print(f"{plugin_id}: real install/configure/start/restart/disable/update/rejected permission transaction/rollback/reinstall/failed activation restoration/purge/nonempty uninstall passed", flush=True)
        finally:
            supervisor.stop_all()


if __name__ == "__main__":
    main()
