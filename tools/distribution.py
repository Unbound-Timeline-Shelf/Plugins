"""Repository distribution metadata; consumes the existing v1 package contract."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import urlparse

try:
    from .package_format import canonical_payload_digest
    from .publisher_registry import load_registry
except ImportError:
    from package_format import canonical_payload_digest
    from publisher_registry import load_registry

ROOT = Path(__file__).parents[1]
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
TAG = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
DEFAULT_BASE = (
    "https://raw.githubusercontent.com/Unbound-Timeline-Shelf/Plugins/main"
)
RETIREMENT_FILE = "retired_plugins.json"
# list.json is a lean index. The entry itself is the complete latest record;
# ``releases`` lists every published version as a summary carrying only what
# existing consumers read: the host's catalogue model (version, hashes, update
# policy, notes) and the host's contract-upgrade acceptance, which selects a
# historical release by ``manifest`` and opens ``package.filename``. README,
# icon, signing and build provenance live only in the complete append-only
# records in releases/<plugin-id>.json, linked through ``release_history``.
CATALOGUE_RELEASE_FIELDS = (
    "version",
    "sha256",
    "package_sha256",
    "automatic_update",
    "release_notes",
    "manifest",
    "package",
)
MAX_CATALOGUE_BYTES = 4 * 1024 * 1024


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value))


def version_key(version: str) -> tuple[int, int, int]:
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        raise ValueError(f"invalid stable semantic version: {version!r}")
    return tuple(map(int, version.split(".")))


def git(root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip() if result.returncode == 0 else None


def discover_plugins(root: Path) -> list[tuple[Path, dict]]:
    if (root / "examples.old").exists():
        raise ValueError("obsolete examples.old source tree")
    plugins = []
    for folder in ("examples", "official", "plugins"):
        tree = root / folder
        if not tree.exists():
            continue
        for source in sorted(tree.iterdir()):
            if source.name.startswith(".") or source.name in {
                "__pycache__",
                "node_modules",
            }:
                continue
            if source.is_symlink():
                raise ValueError("plugin source cannot be a symbolic link")
            if source.is_dir():
                if not (source / "manifest.json").is_file():
                    raise ValueError(
                        f"{source.name}: manifest.json is missing (incomplete plugin source)"
                    )
                plugins.append(
                    (
                        source,
                        json.loads(
                            (source / "manifest.json").read_text(encoding="utf-8")
                        ),
                    )
                )
    if not plugins:
        raise ValueError(
            "no plugin manifests found under examples/, official/ or plugins/"
        )
    ids = [m["plugin_id"] for _, m in plugins]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate plugin_id")
    for source, manifest in plugins:
        version_key(manifest["version"])
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", manifest["plugin_id"]):
            raise ValueError("invalid plugin identity")
        if not (source / "plugin.py").is_file():
            raise ValueError(f"{source.name}: plugin.py is missing")
    return plugins


def validate_metadata(metadata: dict, *, packaged: bool = False) -> None:
    allowed = {
        "schema_version",
        "publisher",
        "tags",
        "icon",
        "automatic_update",
        "release_notes",
    }
    if packaged:
        allowed |= {"version", "build"}
    if set(metadata) - allowed or metadata.get("schema_version") != 1:
        raise ValueError(
            "unsupported distribution metadata fields/schema (risk classification belongs to the host)"
        )
    tags = metadata.get("tags")
    if (
        not isinstance(tags, list)
        or len(tags) > 32
        or not all(isinstance(t, str) and TAG.fullmatch(t) for t in tags)
        or len(tags) != len(set(tags))
    ):
        raise ValueError("tags must be unique lowercase category slugs (up to 32)")
    if (
        not isinstance(metadata.get("publisher"), str)
        or not 1 <= len(metadata["publisher"]) <= 256
    ):
        raise ValueError("publisher must be a non-empty display name")
    if (
        metadata.get("automatic_update") is not None
        and type(metadata["automatic_update"]) is not bool
    ):
        raise ValueError("automatic_update must be a boolean or null")
    if (
        not isinstance(metadata.get("release_notes"), str)
        or len(metadata["release_notes"]) > 4000
    ):
        raise ValueError("release_notes must be text of at most 4000 characters")
    icon = metadata.get("icon")
    if icon is not None and (not isinstance(icon, str) or not safe_path(icon)):
        raise ValueError("icon must be a safe package-relative path")


def safe_path(value: str) -> bool:
    return (
        bool(value)
        and "\\" not in value
        and all(p not in {"", ".", ".."} and ":" not in p for p in value.split("/"))
    )


def source_bytes(path: Path) -> bytes:
    if path.is_symlink():
        raise ValueError("package source cannot be a symbolic link")
    data = path.read_bytes()
    # Text is stored as LF in Git, independent of the author's checkout settings.
    return (
        data.replace(b"\r\n", b"\n")
        if path.suffix
        in {".py", ".js", ".css", ".html", ".md", ".json", ".svg", ".webmanifest"}
        else data
    )


def collect_payload(
    root: Path, source: Path, manifest: dict
) -> tuple[dict[str, bytes], dict]:
    path = source / "release.json"
    metadata = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {
            "schema_version": 1,
            "publisher": "Independent developer",
            "tags": [],
            "icon": None,
            "automatic_update": None,
            "release_notes": "",
        }
    )
    validate_metadata(metadata)
    files = {"sdk/plugin_protocol.py": source_bytes(root / "sdk/plugin_protocol.py")}
    if manifest.get("public_app"):
        files["sdk/public_apps.py"] = source_bytes(root / "sdk/public_apps.py")
    if any(capability["name"].startswith("metadata_providers.")
           for capability in manifest.get("capabilities", [])):
        files["sdk/metadata_provider.py"] = source_bytes(root / "sdk/metadata_provider.py")
    if any(capability["name"] in {"notification_sources.register", "notifications.emit",
                                       "notification_providers.register", "notification_providers.deliver"}
           for capability in manifest.get("capabilities", [])):
        files["sdk/notifications.py"] = source_bytes(root / "sdk/notifications.py")
    if any(capability["name"] in {"notifications.canonical", "notifications.actions",
                                       "notifications.urgency", "notifications.templates.html"}
           for capability in manifest.get("capabilities", [])):
        # Plugin API 1.1.14 helpers; they depend only on the always-bundled protocol module.
        files["sdk/notification_stories.py"] = source_bytes(root / "sdk/notification_stories.py")
    # Provider helpers a plugin imports explicitly (for example the Discord embed renderer).
    plugin_text = "\n".join(
        source_bytes(path).decode("utf-8", "replace") for path in source.rglob("*.py")
        if not any(part.startswith(".") or part in {"__pycache__", "node_modules"}
                   for part in path.relative_to(source).parts)
    )
    for helper in ("notification_stories", "discord_embeds"):
        if re.search(rf"from sdk\.{helper} import|import sdk\.{helper}\b|from sdk import [^\n]*\b{helper}\b", plugin_text):
            files[f"sdk/{helper}.py"] = source_bytes(root / f"sdk/{helper}.py")
    if manifest.get("frontend"):
        files["frontend/appearance.js"] = source_bytes(
            root / "sdk/frontend_appearance.js"
        )
        files["frontend/appearance.css"] = source_bytes(
            root / "sdk/frontend_appearance.css"
        )
    for path in source.rglob("*.py"):
        if not any(
            part.startswith(".") or part in {"__pycache__", "node_modules"}
            for part in path.relative_to(source).parts
        ):
            files[path.relative_to(source).as_posix()] = source_bytes(path)
    for name in ("ui.json", "README.md"):
        path = source / name
        if path.exists():
            files[name] = source_bytes(path)
    if not files.get("README.md", b"").strip():
        raise ValueError(f"{source.name}: a non-empty README.md is required")
    for name in ("frontend", "native", "pwa"):
        for path in (source / name).rglob("*"):
            if path.is_file() and not any(
                p.startswith(".") or p == "node_modules"
                for p in path.relative_to(source).parts
            ):
                if path.is_symlink():
                    raise ValueError("package assets cannot be symbolic links")
                files[path.relative_to(source).as_posix()] = source_bytes(path)
    if metadata.get("icon"):
        files[metadata["icon"]] = source_bytes(source / metadata["icon"])
    files["distribution.json"] = canonical_json(metadata)
    return files, metadata


def source_digest(manifest: dict, files: dict[str, bytes]) -> str:
    source = {k: v for k, v in manifest.items() if k not in {"version", "integrity"}}
    return canonical_payload_digest(
        [("manifest.json", canonical_json(source)), *files.items()]
    )


def load_retired_plugins(root: Path) -> set[str]:
    """Read explicit retirements without discarding their immutable release history."""
    path = root / RETIREMENT_FILE
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or not isinstance(data.get("plugins"), list)
    ):
        raise ValueError("invalid retirement policy schema")
    ids = []
    for record in data["plugins"]:
        if not isinstance(record, dict) or not isinstance(record.get("plugin_id"), str):
            raise TypeError("retired plugin records require a string plugin_id")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", record["plugin_id"]):
            raise ValueError("invalid retired plugin identity")
        if (
            record.get("status") != "retired"
            or not isinstance(record.get("reason"), str)
            or not record["reason"].strip()
        ):
            raise ValueError("retirement records require status=retired and a reason")
        ids.append(record["plugin_id"])
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate retired plugin_id")
    return set(ids)


def history_document(plugin_id: str, history: list[dict]) -> dict:
    """The standalone, append-only release-history file for one plugin."""
    return {"version": 1, "plugin_id": plugin_id, "releases": history}


def history_path(plugin_id: str) -> str:
    return f"releases/{plugin_id}.json"


def release_history_link(plugin_id: str, history: list[dict], base: str) -> dict:
    """Bind a catalogue entry to the exact bytes of its complete history file."""
    path = history_path(plugin_id)
    return {
        "path": path,
        "url": base + "/" + path,
        "count": len(history),
        "sha256": hashlib.sha256(
            canonical_json(history_document(plugin_id, history))
        ).hexdigest(),
    }


def load_histories(root: Path) -> dict[str, list[dict]]:
    """Load retained release records and reject mismatched file identities."""
    histories = {}
    for path in (root / "releases").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or path.stem != data.get("plugin_id"):
            raise ValueError("invalid release history identity/schema")
        histories[data["plugin_id"]] = data["releases"]
    return histories


def release_record(
    path: Path,
    *,
    root: Path,
    source: Path | None = None,
    fingerprint: str | None = None,
    published: bool = True,
) -> dict:
    """Derive authoritative metadata from the exact archive and publisher registry."""
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        names = archive.namelist()
        metadata = (
            json.loads(archive.read("payload/distribution.json"))
            if "payload/distribution.json" in names
            else None
        )
        readme = (
            archive.read("payload/README.md").decode("utf-8")
            if "payload/README.md" in names
            else None
        )
        icon_path = metadata.get("icon") if metadata else None
        icon = (
            {
                "path": icon_path,
                "sha256": hashlib.sha256(
                    archive.read("payload/" + icon_path)
                ).hexdigest(),
            }
            if icon_path
            else None
        )
    key_id = manifest["integrity"].get("key_id")
    key = load_registry().get(key_id) if key_id else None
    if metadata:
        validate_metadata(metadata, packaged=True)
        if key and metadata["publisher"] != key.publisher:
            raise ValueError(
                "declared publisher does not match the registered signing identity"
            )
    # Legacy artifacts predate release policy: do not invent automatic approval.
    return {
        "plugin_id": manifest["plugin_id"],
        "version": manifest["version"],
        "manifest": manifest,
        "sha256": manifest["integrity"]["sha256"],
        "package_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "package": {
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "format": "utp-v1",
        },
        "publisher": key.publisher
        if key
        else (metadata["publisher"] if metadata else None),
        "signing": manifest["integrity"],
        "tags": metadata["tags"] if metadata else [],
        "readme": readme,
        "icon": icon,
        "automatic_update": metadata["automatic_update"] if metadata else False,
        "release_notes": metadata["release_notes"]
        if metadata
        else "Legacy distributed package; automatic-update approval was not recorded.",
        "lifecycle": "published" if published else "built",
        "lifecycle_stages": (
            ["source", "validated", "built", "catalogued"]
            if metadata
            else ["built", "catalogued"]
        )
        + (["published", "downloadable"] if published else []),
        "build": {
            **(metadata.get("build", {}) if metadata else {}),
            "legacy": metadata is None,
        },
    }


def import_history(root: Path, histories: dict[str, list[dict]]) -> None:
    """Index older immutable packages that predate standalone release records."""
    for path in sorted((root / "dist").glob("*.utp")):
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        history = histories.setdefault(manifest["plugin_id"], [])
        existing = next(
            (r for r in history if r["version"] == manifest["version"]), None
        )
        if existing:
            if (
                existing["package_sha256"]
                != hashlib.sha256(path.read_bytes()).hexdigest()
            ):
                raise ValueError(f"historical package changed: {path.name}")
        else:
            record = release_record(path, root=root)
            introduced = git(
                root, "log", "--diff-filter=A", "--format=%H", "--", "dist/" + path.name
            )
            record["build"]["source_commit"] = (
                introduced.splitlines()[-1] if introduced else None
            )
            record["build"]["source_digest"] = None
            record["build"]["source_path"] = None
            record["build"]["source_committed_at"] = (
                git(
                    root, "show", "-s", "--format=%cI", record["build"]["source_commit"]
                )
                if introduced
                else None
            )
            history.append(record)
        history.sort(key=lambda r: version_key(r["version"]))


def next_release(
    root: Path, source: Path, manifest: dict, history: list[dict], fingerprint: str
) -> tuple[str, bool, str]:
    if manifest.get("pwa") and manifest["plugin_id"] == "official.pwa":
        if version_key(manifest["version"])[:2] != (0, 0):
            raise ValueError(
                "PWA development releases must remain 0.0.x; stable promotion requires a separate human policy change"
            )
        if history:
            latest = history[-1]
            if version_key(manifest["version"]) < version_key(latest["version"]):
                raise ValueError("PWA source version cannot go backwards")
            if manifest["version"] == latest["version"]:
                if latest["build"]["source_digest"] != fingerprint:
                    raise ValueError(
                        "changed PWA source requires an explicit new 0.0.x patch version"
                    )
                return manifest["version"], True, "none"
    if not history:
        return manifest["version"], False, "initial"
    latest = history[-1]
    current = version_key(latest["version"])
    if version_key(manifest["version"]) > current:
        candidate = version_key(manifest["version"])
        return (
            manifest["version"],
            False,
            "major"
            if candidate[0] > current[0]
            else "minor"
            if candidate[1] > current[1]
            else "patch",
        )
    if latest["build"]["source_digest"] == fingerprint:
        return latest["version"], True, "none"
    revision = latest["build"].get("source_commit")
    paths = [source.relative_to(root).as_posix(), "sdk"]
    # A layout move must not hide Conventional Commits made at the last
    # published source location. Historical provenance remains immutable.
    previous_path = latest["build"].get("source_path")
    if previous_path and safe_path(previous_path) and previous_path not in paths:
        paths.append(previous_path)
    messages = (
        git(root, "log", f"{revision}..HEAD", "--format=%B%x00", "--", *paths)
        if revision
        else ""
    )
    bump = "patch"
    for message in (messages or "").split("\0"):
        subject = message.strip().splitlines()[0] if message.strip() else ""
        if (
            re.match(r"\w+(?:\([^)]*\))?!:", subject)
            or "BREAKING CHANGE:" in message
            or "BREAKING-CHANGE:" in message
        ):
            bump = "major"
            break
        if re.match(r"feat(?:\([^)]*\))?:", subject):
            bump = "minor"
    major, minor, patch = current
    candidate = (
        (major + 1, 0, 0)
        if bump == "major"
        else (major, minor + 1, 0)
        if bump == "minor"
        else (major, minor, patch + 1)
    )
    return ".".join(map(str, candidate)), False, bump


def catalogue_release(release: dict, base: str) -> dict:
    return {**release, "url": base + "/dist/" + release["package"]["filename"]}


def catalogue_release_summary(release: dict, base: str) -> dict:
    """The compact per-version row embedded in list.json ``releases``."""
    return {
        **{field: release[field] for field in CATALOGUE_RELEASE_FIELDS},
        "url": base + "/dist/" + release["package"]["filename"],
    }


def catalogue_document(
    root: Path, plugins: list[tuple[Path, dict]], histories: dict[str, list[dict]]
) -> dict:
    """List maintained sources with their latest package, recent releases and a history link."""
    config_path = root / "catalogue.json"
    config = (
        json.loads(config_path.read_text(encoding="utf-8"))
        if config_path.exists()
        else {"name": "Plugin catalogue", "base_url": DEFAULT_BASE}
    )
    base = config["base_url"].rstrip("/")
    validate_url(base)
    entries = []
    for source, source_manifest in sorted(plugins, key=lambda p: p[1]["plugin_id"]):
        history = histories.get(source_manifest["plugin_id"])
        if not history:
            if source.relative_to(root).parts[0] != "official" and source_manifest[
                "plugin_id"
            ] not in config.get("unreleased_plugins", []):
                raise ValueError(
                    "source is missing release history and is not explicitly unreleased"
                )
            continue
        latest = catalogue_release(history[-1], base)
        manifest = latest["manifest"]
        entries.append(
            {
                **latest,
                "name": manifest["name"],
                "description": manifest.get("description", ""),
                "sdk_version_range": manifest["sdk_version_range"],
                "application_version_range": manifest["application_version_range"],
                "capabilities": manifest["capabilities"],
                "permissions": manifest["permissions"],
                "dependencies": manifest.get("dependencies", []),
                "documentation": {
                    "readme_path": "README.md" if latest["readme"] else None,
                    "format": "markdown",
                    "packaged": not latest["build"]["legacy"],
                },
                "source": {
                    "path": source.relative_to(root).as_posix(),
                    "lifecycle": "source",
                    "manifest_version": source_manifest["manifest_version"],
                },
                "releases": [catalogue_release_summary(r, base) for r in history],
                "release_history": release_history_link(
                    source_manifest["plugin_id"], history, base
                ),
            }
        )
    return {"version": 1, "name": config["name"], "plugins": entries}


def generate_catalogue(
    root: Path,
    output: Path,
    plugins: list[tuple[Path, dict]],
    histories: dict[str, list[dict]],
) -> None:
    """Write the catalogue derived from retained packages and maintained sources."""
    # Keep the growing mutable catalogue within the host's existing bounded download limit.
    (output / "list.json").write_bytes(canonical_json(catalogue_document(root, plugins, histories)))


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
    ):
        raise ValueError(
            "distribution URLs must be absolute HTTPS URLs without credentials, query or fragment"
        )


def validate_distribution(
    output: Path,
    *,
    source_root: Path = ROOT,
    check_source: bool = False,
    baseline_ref: str | None = None,
    include_unreleased: bool = False,
) -> None:
    """Verify every retained archive, generated record, source binding and catalogue entry."""
    try:
        from .validate_packages import validate_package
        from .verify_packages import verify_package
    except ImportError:
        from validate_packages import validate_package
        from verify_packages import verify_package
    histories = load_histories(output)
    filenames = set()
    for plugin_id, history in histories.items():
        if (
            not history
            or len({r["version"] for r in history}) != len(history)
            or history != sorted(history, key=lambda r: version_key(r["version"]))
        ):
            raise ValueError("release history must contain unique ordered versions")
        for release in history:
            manifest = release["manifest"]
            if (
                release["plugin_id"] != plugin_id
                or manifest["plugin_id"] != plugin_id
                or manifest["version"] != release["version"]
            ):
                raise ValueError("release identity/version mismatch")
            name = f"{plugin_id}-{release['version']}.utp"
            if name != release["package"]["filename"]:
                raise ValueError("release filename mismatch")
            path = output / "dist" / name
            if not path.is_file():
                raise ValueError(f"catalogue package is missing: {name}")
            actual = release_record(
                path, root=source_root, published=release["lifecycle"] == "published"
            )
            if actual["build"]["legacy"] != release["build"]["legacy"]:
                raise ValueError("legacy status does not match actual package")
            for field in (
                "plugin_id",
                "version",
                "manifest",
                "sha256",
                "package_sha256",
                "package",
                "publisher",
                "signing",
                "tags",
                "readme",
                "icon",
                "automatic_update",
                "release_notes",
                "lifecycle_stages",
            ):
                if actual[field] != release[field]:
                    raise ValueError(
                        f"{name}: generated {field} does not match package"
                    )
            if type(release["automatic_update"]) is not bool or release[
                "lifecycle"
            ] not in {
                "built",
                "published",
            }:
                raise ValueError("invalid release lifecycle/update policy")
            verify_package(path)
            # Historical packages retain their original UI contract defects;
            # new releases must pass the full current contract.
            if not release["build"]["legacy"]:
                if actual["build"] != release["build"]:
                    raise ValueError(
                        "release build provenance does not match signed package"
                    )
                validate_package(path, full=True)
            filenames.add(name)
    if filenames != {p.name for p in (output / "dist").glob("*.utp")}:
        raise ValueError("dist contains untracked packages")
    catalogue_path = output / "list.json"
    # The v1.1.1 host bounds decoded catalogue downloads to 4 MiB. Fail before
    # publication instead of producing an endpoint it cannot consume.
    if catalogue_path.stat().st_size > MAX_CATALOGUE_BYTES:
        raise ValueError(
            "catalogue exceeds the current Plugin Manager's 4 MiB download limit"
        )
    catalogue = json.loads(catalogue_path.read_text(encoding="utf-8"))
    if catalogue != catalogue_document(
        source_root, discover_plugins(source_root), histories
    ):
        raise ValueError(
            "catalogue differs from authoritative package/release metadata"
        )
    if catalogue["version"] != 1:
        raise ValueError("unsupported catalogue schema")
    entries = catalogue["plugins"]
    if len({e["plugin_id"] for e in entries}) != len(entries):
        raise ValueError("duplicate catalogue identity")
    sources = {m["plugin_id"]: (s, m) for s, m in discover_plugins(source_root)}
    pending = (
        set(
            json.loads((source_root / "catalogue.json").read_text()).get(
                "unreleased_plugins", []
            )
        )
        if (source_root / "catalogue.json").exists()
        else set()
    )
    if not pending.issubset(sources):
        raise ValueError("unreleased identity must have a maintained source contract")
    released_sources = {
        plugin_id
        for plugin_id, (source, _) in sources.items()
        if plugin_id in histories
        or source.relative_to(source_root).parts[0] != "official"
    }
    required_sources = (
        set(sources)
        if include_unreleased
        else (set(sources) if check_source else released_sources) - pending
    )
    entry_ids = {e["plugin_id"] for e in entries}
    if not required_sources.issubset(entry_ids) or not entry_ids.issubset(sources):
        raise ValueError("catalogue does not match source plugin set")
    config_path = source_root / "catalogue.json"
    configured_base = (
        json.loads(config_path.read_text())["base_url"].rstrip("/")
        if config_path.exists()
        else DEFAULT_BASE
    )
    for entry in entries:
        history = histories[entry["plugin_id"]]
        base = configured_base
        validate_url(base)
        if entry["releases"] != [catalogue_release_summary(r, base) for r in history]:
            raise ValueError("catalogue release history mismatch")
        link = release_history_link(entry["plugin_id"], history, base)
        if entry.get("release_history") != link:
            raise ValueError("catalogue release history link mismatch")
        history_file = output / link["path"]
        if (
            not history_file.is_file()
            or hashlib.sha256(history_file.read_bytes()).hexdigest() != link["sha256"]
        ):
            raise ValueError(
                f"release history file does not match catalogue: {link['path']}"
            )
        for key, value in catalogue_release(history[-1], base).items():
            if entry[key] != value:
                raise ValueError(f"catalogue latest {key} mismatch")
        manifest = entry["manifest"]
        for field in (
            "name",
            "description",
            "sdk_version_range",
            "application_version_range",
            "capabilities",
            "permissions",
            "dependencies",
        ):
            if entry[field] != manifest.get(
                field, [] if field == "dependencies" else ""
            ):
                raise ValueError(f"catalogue {field} mismatch")
        if check_source:
            source, authored = sources[entry["plugin_id"]]
            files, _ = collect_payload(source_root, source, authored)
            if history[-1]["build"]["source_digest"] != source_digest(authored, files):
                raise ValueError(
                    "generated package does not correspond to current source"
                )
    if baseline_ref:
        validate_immutable_history(output, source_root, baseline_ref)


def validate_immutable_history(
    output: Path, repository: Path, baseline_ref: str
) -> None:
    """Enforce reviewed retirements while preserving baseline packages and record prefixes."""
    if not git(repository, "rev-parse", "--verify", baseline_ref):
        raise ValueError("baseline Git revision is unavailable; fetch full history")
    baseline_catalogue = subprocess.run(
        ["git", "-C", str(repository), "show", f"{baseline_ref}:list.json"],
        capture_output=True,
        check=False,
    )
    if baseline_catalogue.returncode:
        raise ValueError("cannot read baseline catalogue")
    baseline_entries = json.loads(baseline_catalogue.stdout)["plugins"]
    previous_ids = {entry["plugin_id"] for entry in baseline_entries}
    current_ids = {
        entry["plugin_id"]
        for entry in json.loads((output / "list.json").read_bytes())["plugins"]
    }
    removed = previous_ids - current_ids
    retired = load_retired_plugins(repository)
    unexpected = removed - retired
    if unexpected:
        raise ValueError(
            f"published plugins disappeared from catalogue without retirement policy: {', '.join(sorted(unexpected))}"
        )
    if retired & current_ids:
        raise ValueError(
            f"retired plugins remain in the current catalogue: {', '.join(sorted(retired & current_ids))}"
        )
    sources = {manifest["plugin_id"] for _, manifest in discover_plugins(repository)}
    if retired & sources:
        raise ValueError(
            f"retired plugins still have maintained sources: {', '.join(sorted(retired & sources))}"
        )
    histories = load_histories(output)
    for plugin_id in retired:
        if plugin_id not in histories:
            raise ValueError(
                f"retired plugin has no retained release history: {plugin_id}"
            )
    names = git(
        repository,
        "ls-tree",
        "-r",
        "--name-only",
        baseline_ref,
        "--",
        "dist",
        "releases",
    )
    for name in (names or "").splitlines():
        if not name.endswith((".utp", ".json")):
            continue
        result = subprocess.run(
            ["git", "-C", str(repository), "show", f"{baseline_ref}:{name}"],
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise ValueError("cannot read baseline distribution")
        path = output / name
        if not path.is_file():
            raise ValueError(f"historical distribution removed: {name}")
        if name.endswith(".utp"):
            if path.read_bytes() != result.stdout:
                raise ValueError(f"historical artifact changed: {name}")
        else:
            old = json.loads(result.stdout)
            current = json.loads(path.read_bytes())
            if (
                current["plugin_id"] != old["plugin_id"]
                or current["releases"][: len(old["releases"])] != old["releases"]
            ):
                raise ValueError(f"historical release metadata changed: {name}")
    # Older catalogues embedded complete records; newer ones embed summaries.
    # Either way, every release a baseline catalogue advertised must survive
    # unchanged in the standalone history file that holds the complete records.
    for entry in baseline_entries:
        retained = {
            record["version"]: record for record in histories.get(entry["plugin_id"], [])
        }
        for advertised in entry.get("releases", []):
            record = retained.get(advertised.get("version"))
            if record is None or any(
                record.get(k) != v for k, v in advertised.items() if k != "url"
            ):
                raise ValueError(
                    "baseline catalogue release is missing from or changed in "
                    f"{history_path(entry['plugin_id'])}: {advertised.get('version')}"
                )


def main() -> None:
    """Validate a generated or published distribution against its source and optional baseline."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Verify catalogue, release history and actual package bytes"
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check-source", action="store_true")
    parser.add_argument(
        "--include-unreleased",
        action="store_true",
        help="validate all source previews, including unpublished plugin identities",
    )
    parser.add_argument(
        "--baseline-ref",
        help="reject changes/removal of existing packages or release records in this Git revision",
    )
    args = parser.parse_args()
    validate_distribution(
        args.root.resolve(),
        check_source=args.check_source,
        baseline_ref=args.baseline_ref,
        include_unreleased=args.include_unreleased,
    )
    print("Catalogue, release history, package hashes and metadata verified")


if __name__ == "__main__":
    main()
