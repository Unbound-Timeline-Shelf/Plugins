"""Validate package-level invariants that the host relies on before installation."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
import zipfile
from functools import lru_cache
from pathlib import Path

ROUTE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
ROUTE_HANDLER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*(?::[A-Za-z_][A-Za-z0-9_]*)?$")
ROUTE_SEGMENT = re.compile(r"^(?:[a-z0-9][a-z0-9._-]*|\{[a-z_][a-z0-9_]*\})$")
ROUTE_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
RESERVED_PLUGIN_ROUTE_ROOTS = {
    "actions",
    "changelog",
    "capabilities",
    "disable",
    "enable",
    "frontend",
    "logs",
    "native-frontend",
    "permissions",
    "retry",
    "secrets",
    "settings",
    "ui",
    "update",
}


def validate_package(path: Path, *, full: bool = False) -> None:
    """Check bounded payload structure and declarations independently of publisher trust."""
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        payload_names = {
            name.removeprefix("payload/")
            for name in archive.namelist()
            if name.startswith("payload/") and not name.endswith("/")
        }
        files = {name: archive.read("payload/" + name) for name in payload_names}
        names = archive.namelist()
        if len(names) != len(set(names)) or any(
            "\\" in name
            or name.startswith("/")
            or any(part in {"", ".", ".."} or ":" in part for part in name.rstrip("/").split("/"))
            for name in names
        ):
            raise ValueError(f"{path.name}: duplicate or unsafe archive paths")

    capabilities = {
        (item.get("name"), item.get("version"))
        for item in manifest.get("capabilities", [])
        if isinstance(item, dict)
    }
    for permission in manifest.get("permissions", []):
        if not isinstance(permission, dict):
            raise ValueError(f"{path.name}: permission declaration must be an object")
        capability = permission.get("capability")
        if not isinstance(capability, dict):
            raise ValueError(f"{path.name}: permission capability must be an object")
        key = (capability.get("name"), capability.get("version"))
        if key not in capabilities:
            raise ValueError(
                f"{path.name}: permission {capability.get('name')!r} v{capability.get('version')!r} "
                "is not declared by capabilities"
            )

    route_ids: set[str] = set()
    route_owners: list[tuple[str, str, str]] = []
    capability_names = {name for name, version in capabilities if version == 1}
    for route in manifest.get("backend_routes", []):
        if not isinstance(route, dict):
            raise ValueError(f"{path.name}: backend route must be an object")
        route_id = route.get("id")
        scope = route.get("scope", "plugin")
        route_path = route.get("path")
        methods = route.get("methods", ["GET"])
        handler = route.get("handler")
        if not isinstance(route_id, str) or not ROUTE_ID.fullmatch(route_id):
            raise ValueError(f"{path.name}: backend route id is invalid")
        if route_id in route_ids:
            raise ValueError(f"{path.name}: backend route ids must be unique")
        route_ids.add(route_id)
        if scope not in {"plugin", "host"} or not isinstance(route_path, str):
            raise ValueError(f"{path.name}: backend route scope or path is invalid")
        if scope == "plugin" and route_path.startswith("/"):
            raise ValueError(f"{path.name}: plugin backend route path must be relative")
        if scope == "plugin" and route_path.split("/", 1)[0] in RESERVED_PLUGIN_ROUTE_ROOTS:
            raise ValueError(f"{path.name}: backend route conflicts with plugin management")
        if scope == "host" and not route_path.startswith("/api/"):
            raise ValueError(f"{path.name}: host backend route path must start with /api/")
        if scope == "host" and route_path.startswith("/api/plugins/"):
            raise ValueError(f"{path.name}: host route cannot claim plugin management")
        route_parts = route_path.removeprefix("/api/").split("/")
        if not route_parts or any(not ROUTE_SEGMENT.fullmatch(part) for part in route_parts):
            raise ValueError(f"{path.name}: backend route path is invalid")
        parameters = [part for part in route_parts if part.startswith("{")]
        if len(parameters) != len(set(parameters)):
            raise ValueError(f"{path.name}: backend route repeats a path parameter")
        if (
            not isinstance(methods, list)
            or not methods
            or len(methods) != len(set(methods))
            or any(method not in ROUTE_METHODS for method in methods)
        ):
            raise ValueError(f"{path.name}: backend route methods are invalid")
        if not isinstance(handler, str) or not ROUTE_HANDLER.fullmatch(handler):
            raise ValueError(f"{path.name}: backend route handler is invalid")
        required = "backend.routes.plugin" if scope == "plugin" else "backend.routes.host"
        if route.get("authorization", "authenticated") not in {"authenticated", "admin"}:
            raise ValueError(f"{path.name}: backend route authorization is invalid")
        if not {required, "backend.routes", "api.full"}.intersection(capability_names):
            raise ValueError(f"{path.name}: backend route requires {required}")
        for method in methods:
            for owner_scope, owner_path, owner_method in route_owners:
                owner_parts = owner_path.removeprefix("/api/").split("/")
                overlaps = len(route_parts) == len(owner_parts) and all(
                    left == right or left.startswith("{") or right.startswith("{")
                    for left, right in zip(route_parts, owner_parts, strict=True)
                )
                if scope == owner_scope and method == owner_method and overlaps:
                    raise ValueError(f"{path.name}: backend routes conflict")
            route_owners.append((scope, route_path, method))

    native = manifest.get("native_frontend")
    if native is not None:
        if not isinstance(native, dict) or ("frontend.native", 1) not in capabilities:
            raise ValueError(f"{path.name}: native frontend requires frontend.native")
        entry = native.get("entry")
        activation = native.get("activation", "startup")
        if activation not in {"startup", "page"}:
            raise ValueError(f"{path.name}: invalid native frontend activation")
        if activation == "page" and tuple(map(int, manifest.get("api_contract_version", "1.0.0").split("."))) < (1, 1, 17):
            raise ValueError(f"{path.name}: page activation requires Plugin API v1.1.17")
        styles = native.get("styles", [])
        if not isinstance(entry, str) or not isinstance(styles, list):
            raise ValueError(f"{path.name}: invalid native frontend declaration")
        for asset in [entry, *styles]:
            if (
                not isinstance(asset, str)
                or not asset.startswith("native/")
                or "\\" in asset
                or any(part in {"", ".", ".."} for part in asset.split("/"))
                or asset not in payload_names
            ):
                raise ValueError(f"{path.name}: native asset is unsafe or missing")

    pwa = manifest.get("pwa")
    if pwa is not None:
        if not isinstance(pwa, dict) or ("frontend.pwa", 1) not in capabilities:
            raise ValueError("PWA requires frontend.pwa v1")
        granted = {
            (p["capability"]["name"], p["capability"]["version"]) for p in manifest["permissions"]
        }
        if ("frontend.pwa", 1) not in granted:
            raise ValueError("PWA requires an explicit permission declaration")
        declaration_path = pwa.get("manifest", "pwa/manifest.webmanifest")
        if declaration_path != "pwa/manifest.webmanifest" or declaration_path not in files:
            raise ValueError("PWA manifest is missing or unsafe")
        webmanifest = json.loads(files[declaration_path])
        for field in ("name", "short_name", "theme_color", "background_color"):
            if webmanifest.get(field) != pwa.get(field, "#0f1117"):
                raise ValueError("PWA metadata does not match declaration")
        for field, value in {
            "id": "/",
            "scope": "/",
            "start_url": "/?pwa=1",
            "display": "standalone",
        }.items():
            if webmanifest.get(field) != value:
                raise ValueError("PWA must launch the complete root application")
        for size in (192, 512):
            data = files.get(f"pwa/icon-{size}.png", b"")
            if (
                len(data) > 256 * 1024
                or len(data) < 24
                or data[:8] != b"\x89PNG\r\n\x1a\n"
                or int.from_bytes(data[16:20], "big") != size
                or int.from_bytes(data[20:24], "big") != size
            ):
                raise ValueError("PWA icon is missing, oversized or has invalid dimensions")
        if manifest["plugin_id"] == "official.pwa":
            version = json.loads(files.get("pwa/version.json", b"{}"))
            asset_version = version.get("version", "")
            if (
                not isinstance(asset_version, str)
                or not re.fullmatch(r"0\.0\.[0-9]+", asset_version)
                or not re.fullmatch(r"0\.0\.[0-9]+", manifest["version"])
                or int(manifest["version"].split(".")[2]) < int(asset_version.split(".")[2])
            ):
                raise ValueError(
                    "PWA source/package versions must remain 0.0.x; package cannot precede assets"
                )
            provenance = json.loads(files.get("pwa/provenance.json", b"{}"))
            expected_assets = {
                "manifest.webmanifest",
                "service-worker.js",
                "offline.html",
                "pwa-icon.svg",
                "icon-192.png",
                "icon-512.png",
                "version.json",
                "README.md",
            }
            if (
                provenance.get("repository") not in {
                    "Rosefall-a/unnamed-tracking-mobile-app",
                    "obsoletelabs/unnamed-tracking-mobile-app",
                    "Unbound-Timeline-Shelf/Mobile-Apps",
                }
                or provenance.get("source_path") != "pwa"
                or provenance.get("version") != asset_version
                or set(provenance.get("sha256", {})) != expected_assets
            ):
                raise ValueError("PWA provenance identity/version/assets do not match")
            for asset, digest in provenance["sha256"].items():
                data = files.get("pwa/" + asset, b"")
                if asset.endswith((".html", ".js", ".json", ".svg", ".webmanifest", ".md")):
                    data = data.replace(b"\r\n", b"\n")
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError(f"PWA source provenance hash differs: {asset}")

    frontend = manifest.get("frontend")
    if frontend is not None:
        if isinstance(frontend, dict) and type(frontend.get("inline_assets", False)) is not bool:
            raise ValueError(f"{path.name}: frontend.inline_assets must be a boolean")
        entry = frontend.get("entry") if isinstance(frontend, dict) else None
        if not isinstance(entry, str) or not entry:
            raise ValueError(f"{path.name}: frontend.entry must be a non-empty string")
        if entry not in payload_names:
            raise ValueError(
                f"{path.name}: frontend.entry {entry!r} is not present in the package payload"
            )
    if full:
        validate_current_contract(manifest, files)


@lru_cache(maxsize=None)
def _schema_validator(name: str):
    """Parse each bundled schema once per process instead of once per package."""
    from jsonschema import Draft202012Validator

    schema = Path(__file__).parent / "schemas" / name
    return Draft202012Validator(json.loads(schema.read_text(encoding="utf-8")))


def validate_current_contract(manifest: dict, files: dict[str, bytes]) -> None:
    """Validate current source schemas, handler references and requested UI permissions."""

    try:
        from .distribution import validate_metadata, version_key
    except ImportError:
        from distribution import validate_metadata, version_key
    _schema_validator("manifest-v1.schema.json").validate(manifest)
    version_key(manifest["version"])
    contract = manifest.get("api_contract_version", "1.0.0")
    contract_version = version_key(contract)
    if (any(c["name"].startswith("metadata_providers.") for c in manifest["capabilities"])
            and contract_version < (1, 1, 1)):
        raise ValueError("metadata provider capabilities require Plugin API v1.1.1")
    ranges = [manifest[field] for field in ("sdk_version_range", "application_version_range")]
    ranges.extend(d["version_range"] for d in manifest.get("dependencies", []))
    for value in ranges:
        if not value.strip():
            raise ValueError("version range must not be empty")
        for part in value.split(","):
            part = part.strip()
            if part in {"", "*"}:
                continue
            if re.fullmatch(r"(?:>=|<=|>|<|=)?[0-9]+(?:\.[0-9]+)*\.(?:x|\*)", part):
                continue
            if not re.fullmatch(
                r"(?:\^|~|>=|<=|>|<|=)?(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)",
                part,
            ):
                raise ValueError("invalid host version range")
    for field, identifier in (("capabilities", "name"), ("dependencies", "plugin_id")):
        values = [item[identifier] for item in manifest.get(field, [])]
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate {field}")
    permissions = [item["capability"]["name"] for item in manifest.get("permissions", [])]
    if len(permissions) != len(set(permissions)):
        raise ValueError("duplicate permissions")
    metadata = json.loads(files["distribution.json"])
    validate_metadata(metadata, packaged=True)
    if metadata["version"] != manifest["version"] or type(metadata["automatic_update"]) is not bool:
        raise ValueError("packaged release version/policy mismatch")
    if not files.get("README.md", b"").strip() or (
        metadata.get("icon") and metadata["icon"] not in files
    ):
        raise ValueError("README/icon missing from package")

    def handler_exists(handler: str) -> None:
        module, _, function = handler.partition(":")
        filename = module.replace(".", "/") + ".py"
        if filename not in files:
            raise ValueError(f"handler module is missing: {handler}")
        tree = ast.parse(files[filename])
        if not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == (function or "main")
            for node in tree.body
        ):
            raise ValueError(f"handler function is missing: {handler}")

    handler_exists(manifest["entrypoint"])
    validate_notification_contract(
        manifest,
        contract_version,
        {c["name"] for c in manifest["capabilities"]},
        {p["capability"]["name"] for p in manifest["permissions"]},
    )
    for route in manifest.get("backend_routes", []):
        handler_exists(route["handler"])
    if "ui.json" not in files:
        if any(manifest.get("ui", {}).values()) or manifest.get("scheduled_tasks"):
            raise ValueError("declared UI contributions require ui.json")
        return
    document = json.loads(files["ui.json"])
    if document.get("api_contract_version", "1.0.0") != contract:
        raise ValueError("UI and manifest API contracts must match")
    _schema_validator("ui-v1.schema.json").validate(document)
    if document["plugin_id"] != manifest["plugin_id"]:
        raise ValueError("UI plugin identity mismatch")
    for field in ("settings", "actions", "pages", "menus"):
        ids = [item["id"] for item in document.get(field, [])]
        if len(ids) != len(set(ids)) or set(ids) != set(manifest.get("ui", {}).get(field, [])):
            raise ValueError(f"manifest/UI {field} mismatch")
    for action in document.get("actions", []):
        if not action.get("handler"):
            raise ValueError("actions require executable handlers")
        handler_exists(action["handler"])
        ref = action.get("capability")
        if ref and (ref["name"], ref["version"]) not in {
            (c["name"], c["version"]) for c in manifest["capabilities"]
        }:
            raise ValueError("UI action capability is undeclared")
    for page in document.get("pages", []):
        for field in ("settings", "actions", "tables", "dialogs"):
            if not set(page.get(field, [])) <= {x["id"] for x in document.get(field, [])}:
                raise ValueError(f"page refers to missing {field}")
    declared = {c["name"] for c in manifest["capabilities"]}
    granted = {p["capability"]["name"] for p in manifest["permissions"]}
    validate_scheduled_tasks(manifest, document, contract_version, granted)
    required = set()
    page_ids = {page["id"] for page in document.get("pages", [])}
    for replacement in document.get("page_replacements", []):
        required.add(f"frontend.page.replace.{replacement['page']}")
        if replacement["page_id"] not in page_ids:
            raise ValueError("page replacement refers to a missing page")
    if document.get("connections"):
        if contract_version < (1, 1, 9):
            raise ValueError("connection contributions require Plugin API v1.1.9")
        required.add("frontend.connections")
        action_ids = {action["id"] for action in document.get("actions", [])}
        for connection in document["connections"]:
            if connection["page_id"] not in page_ids:
                raise ValueError("connection refers to a missing page")
            if connection.get("status_action_id") not in (None, *action_ids):
                raise ValueError("connection refers to a missing status action")
            if connection.get("sync_action_id") not in (None, *action_ids):
                raise ValueError("connection refers to a missing sync action")
            if connection.get("sync_action_id") and contract_version < (1, 1, 11):
                raise ValueError("connection sync actions require Plugin API v1.1.11")
    for extension in document.get("extensions", []):
        if extension["slot"] in {"administration.users.settings", "administration.password-policy.after"}:
            if contract_version < (1, 1, 11):
                raise ValueError("administration settings slots require Plugin API v1.1.11")
            if extension["page_id"] not in page_ids:
                raise ValueError("administration settings slot refers to a missing page")
            required.add("frontend.settings")
    if document.get("shortcuts"):
        required.add("frontend.shortcuts")
        validate_shortcut_targets(document, contract_version)
    if any(p.get("navigation", {}).get("sidebar") for p in document.get("pages", [])):
        required.add("frontend.navigation.main")
    if document.get("document_readers"):
        required.add("frontend.context.documents")
        page_ids = {p["id"] for p in document.get("pages", [])}
        if any(reader["page_id"] not in page_ids for reader in document["document_readers"]):
            raise ValueError("document reader refers to a missing page")
    if any(
        not field.get("secret")
        for section in document.get("settings", [])
        for field in section.get("fields", [])
    ):
        required.add("plugin.settings")
    if not required <= declared & granted:
        raise ValueError("UI contributions require declared frontend/settings permissions")


NOTIFICATION_CONTRACT_CAPABILITIES = frozenset({
    "notifications.canonical", "notifications.actions", "notifications.urgency",
    "notifications.templates.html",
})


def validate_notification_contract(
    manifest: dict, contract_version: tuple[int, ...], declared: set[str], granted: set[str]
) -> None:
    """Plugin API 1.1.14 notification capabilities are explicit, versioned and justified."""
    used = declared & NOTIFICATION_CONTRACT_CAPABILITIES
    if not used:
        return
    if contract_version < (1, 1, 14):
        raise ValueError("versioned notification capabilities require Plugin API v1.1.14")
    if not used <= granted:
        raise ValueError("versioned notification capabilities require explicit permissions")
    # Publishing registers a canonical type first, and actions need a declaring event type.
    if "notification_sources.register" not in declared | granted and "notifications.canonical" in used:
        raise ValueError("canonical notifications require notification_sources.register")
    if {"notifications.actions", "notifications.urgency", "notifications.templates.html"} & used and (
        "notifications.canonical" not in used
    ):
        raise ValueError("notification actions, urgency and templates require notifications.canonical")


def validate_scheduled_tasks(
    manifest: dict, document: dict, contract_version: tuple[int, ...], granted: set[str]
) -> None:
    """Match bounded host schedules to non-confirmed actions and explicit background consent."""
    tasks = manifest.get("scheduled_tasks", [])
    if not tasks:
        return
    if contract_version < (1, 1, 0) or "tasks.background" not in granted:
        raise ValueError("scheduled tasks require v1.1 and explicit tasks.background permission")
    identifiers = [task["id"] for task in tasks]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate scheduled tasks")
    actions = {action["id"]: action for action in document.get("actions", [])}
    for task in tasks:
        if task.get("scope", "server") == "user" and contract_version < (1, 1, 11):
            raise ValueError("personal scheduled tasks require Plugin API v1.1.11")
        action = actions.get(task["action_id"])
        if action is None or not action.get("handler") or action.get("confirmation") is not None:
            raise ValueError("scheduled task action must exist and have no confirmation")
        if (
            not task.get("min_interval_minutes", 5)
            <= task.get("default_interval_minutes", 60)
            <= task.get("max_interval_minutes", 43_200)
        ):
            raise ValueError("scheduled task interval is outside its bounds")


def validate_shortcut_targets(document: dict, contract_version: tuple[int, ...]) -> None:
    """Validate consumer references without importing the host implementation."""
    if contract_version < (1, 1, 0):
        raise ValueError("shortcuts require Plugin API v1.1")
    shortcuts = document["shortcuts"]
    identifiers = [item["id"] for item in shortcuts]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate shortcuts")
    targets = {
        field: {item["id"] for item in document.get(collection, [])}
        for field, collection in (
            ("page_id", "pages"),
            ("route_id", "routes"),
            ("when_route_id", "routes"),
            ("action_id", "actions"),
        )
    }
    for shortcut in shortcuts:
        if (
            sum(
                bool(shortcut.get(field))
                for field in ("page_id", "route_id", "action_id", "control")
            )
            != 1
        ):
            raise ValueError("shortcut must target exactly one destination or control")
        if shortcut.get("control") and not shortcut.get("when_route_id"):
            raise ValueError("shortcut controls require a declared route scope")
        if any(
            shortcut.get(field) and shortcut[field] not in allowed
            for field, allowed in targets.items()
        ):
            raise ValueError("shortcut refers to an undeclared destination or scope")


def main() -> None:
    """Validate each supplied package, optionally including current contract schemas."""
    full = "--full" in sys.argv
    paths = [Path(value) for value in sys.argv[1:] if value != "--full"]
    if not paths:
        raise SystemExit("at least one package path is required")
    for package in paths:
        validate_package(package, full=full)


if __name__ == "__main__":
    main()
