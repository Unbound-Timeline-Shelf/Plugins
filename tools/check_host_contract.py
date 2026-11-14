"""Explicit cross-repository conformance check; never imported by plugin payloads.

Run with --host-root /path/to/unnamed_tracking_app on plugin-manager. Normal
plugin tests remain independent of host source. This tool calls real validators
and the installation registry, not host test fixtures. It does not enable code.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field


def load_catalogue_entry(host_root: Path, dependency_model: type[BaseModel]) -> type[BaseModel]:
    """Load transport models from either supported host route layout."""
    source = host_root / "src/backend/src/api/routes/plugin_manager/models.py"
    if not source.exists():
        source = host_root / "src/backend/src/api/routes/plugins.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    models = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name in {"PluginCatalogRelease", "PluginCatalogEntry"}
    ]
    if not any(node.name == "PluginCatalogEntry" for node in models):
        raise ValueError(f"Host catalogue entry model is missing from {source}")
    namespace = {"BaseModel": BaseModel, "Field": Field, "PluginDependency": dependency_model}
    exec(compile(ast.Module(body=models, type_ignores=[]), str(source), "exec"), namespace)
    for model in models:
        namespace[model.name].model_rebuild(_types_namespace=namespace)
    return namespace["PluginCatalogEntry"]


def main() -> None:
    """Inspect actual distribution packages against the selected host contract."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host-root", required=True, type=Path)
    parser.add_argument("--temporary-root", type=Path)
    parser.add_argument(
        "--distribution-root", type=Path, default=Path(__file__).parents[1] / ".validation"
    )
    args = parser.parse_args()
    sys.path.insert(0, str(args.host_root / "src/backend"))
    sys.path.insert(0, str(args.host_root / "src/plugin-runtime"))
    from distribution import discover_plugins
    from check_source_layout import SUPPORTED_CONTRACTS
    from publisher_registry import load_registry
    from runtime import PluginRegistry, PluginSupervisor, RuntimePolicyError
    from src.plugin_api.capabilities import capability_definition
    from src.plugin_api.metadata_contracts import (
        MetadataProviderRegistration, MetadataProviderRequest, ProviderResponse,
    )
    from src.plugin_api.contracts import (
        PLUGIN_API_CONTRACT_VERSION,
        Capability,
        PluginDependency,
        PluginManifest,
        PluginUiDocument,
    )
    from src.plugin_api.updates import (
        PackageVerificationError,
        PluginPackageVerifier,
        TrustedPublisher,
    )

    root = Path(__file__).parents[1]
    for name, model in (("metadata-registration-v1", MetadataProviderRegistration),
                        ("metadata-request-v1", MetadataProviderRequest),
                        ("metadata-response-v1", ProviderResponse)):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["x-api-contract-version"] = PLUGIN_API_CONTRACT_VERSION
        assert schema == json.loads((root / "tools/schemas" / f"{name}.schema.json").read_bytes()), name
    # The manifest schema is the host's PluginManifest as generated (including the optional
    # api_contract_max of Plugin API 1.1.20), so validate_packages refuses exactly what the host refuses.
    assert PluginManifest.model_json_schema() == json.loads(
        (root / "tools/schemas/manifest-v1.schema.json").read_bytes()
    ), "manifest-v1"
    from src.plugin_api import (
        NotificationTypeRegistration, NotificationEventEmission,
        NotificationProviderRegistration, NotificationFieldLayout,
        NotificationLifecycleQuery, NotificationLifecyclePage,
        PluginNotificationContent, PluginNotificationDestination,
    )
    for name, model in (("notification-type-v1", NotificationTypeRegistration),
                        ("notification-event-v1", NotificationEventEmission),
                        ("notification-provider-v1", NotificationProviderRegistration),
                        ("notification-layout-v1", NotificationFieldLayout),
                        ("notification-content-v1", PluginNotificationContent),
                        ("notification-destination-v1", PluginNotificationDestination),
                        ("notification-lifecycle-query-v1", NotificationLifecycleQuery),
                        ("notification-lifecycle-page-v1", NotificationLifecyclePage)):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["x-api-contract-version"] = {
            "notification-provider-v1": "1.1.14",
            "notification-content-v1": "1.1.5",
            "notification-destination-v1": "1.1.5",
            "notification-lifecycle-query-v1": "1.1.14",
            "notification-lifecycle-page-v1": "1.1.14",
        }.get(name, "1.1.2")
        expected_schema = json.loads(
            (root / "tools/schemas" / f"{name}.schema.json").read_bytes()
        )
        if schema != expected_schema and name == "notification-provider-v1":
            print("\\n".join(difflib.unified_diff(
                json.dumps(expected_schema, indent=2, ensure_ascii=False).splitlines(),
                json.dumps(schema, indent=2, ensure_ascii=False).splitlines(),
                fromfile="checked-in provider schema",
                tofile="host-generated provider schema",
                lineterm="",
            )))
        assert schema == expected_schema, name
    from src.plugin_api import notification_contract_schemas, plugin_notification_schemas
    published = {**notification_contract_schemas(), **plugin_notification_schemas()}
    for name, schema in published.items():
        # The canonical 1.0.0 contract and the 1.1.14 plugin documents are pinned verbatim.
        assert schema == json.loads(
            (root / "tools/schemas" / f"{name}.schema.json").read_bytes()
        ), name
    from src.plugin_api.auth_contracts import PasswordResetFlowDefinition
    auth_schema = PasswordResetFlowDefinition.model_json_schema()
    auth_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    auth_schema["x-api-contract-version"] = "1.1.7"
    assert auth_schema == json.loads((root / "tools/schemas/auth-password-reset-v1.schema.json").read_bytes())
    from src.plugin_api.auth_contracts import UserInviteFlowDefinition, UserInviteIssue, UserInviteIdentity
    for name, model in (("auth-user-invite-v1", UserInviteFlowDefinition),
                        ("auth-user-invite-issue-v1", UserInviteIssue),
                        ("auth-user-invite-identity-v1", UserInviteIdentity)):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["x-api-contract-version"] = "1.1.8" if name == "auth-user-invite-identity-v1" else "1.1.11"
        assert schema == json.loads((root / "tools/schemas" / (name + ".schema.json")).read_bytes()), name
    from src.plugin_api import NotificationDestinationStatusQuery, NotificationDestinationStatusPage
    for name, model in (("notification-destination-status-query-v1", NotificationDestinationStatusQuery),
                        ("notification-destination-status-page-v1", NotificationDestinationStatusPage)):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["x-api-contract-version"] = "1.1.11"
        assert schema == json.loads((root / "tools/schemas" / (name + ".schema.json")).read_bytes()), name
    catalogue = json.loads((args.distribution_root / "list.json").read_text(encoding="utf-8"))
    # Evaluate the actual public catalogue entry model without loading database
    # configuration or the API server. Additional distribution fields remain
    # additive to its v1 contract; this does not imply old hosts consume them.
    catalogue_entry = load_catalogue_entry(args.host_root, PluginDependency)
    for entry in catalogue["plugins"]:
        catalogue_entry.model_validate(entry)
    publishers = {
        key: TrustedPublisher(
            key_id=key,
            public_key=record.public_key,
            publisher=record.publisher,
            status=record.status,
            plugin_id_prefixes=record.plugin_id_prefixes,
            channel=record.channel,
            legacy_manifest_hashes=record.legacy_manifest_hashes,
            require_manifest_binding=True,
            plugin_ids=record.plugin_ids,
            not_before=record.not_before,
            not_after=record.not_after,
            historical_package_sha256=record.historical_package_sha256,
        )
        for key, record in load_registry().items()
    }
    with tempfile.TemporaryDirectory(dir=args.temporary_root) as temporary:
        work = Path(temporary)
        supervisor = PluginSupervisor(root=work / "workers", storage_root=work / "storage")
        registry = PluginRegistry(work / "installed", supervisor)
        for source, _ in discover_plugins(root):
            manifest = PluginManifest.model_validate_json((source / "manifest.json").read_bytes())
            document = PluginUiDocument.model_validate_json((source / "ui.json").read_bytes())
            assert manifest.plugin_id == document.plugin_id
            assert manifest.api_contract_version == document.api_contract_version
            assert manifest.api_contract_version in SUPPORTED_CONTRACTS
            assert all(capability_definition(ref.name) for ref in manifest.capabilities)
            assert capability_definition(Capability.FRONTEND_NATIVE).highly_privileged
            for key in ("settings", "actions", "pages", "menus"):
                assert set(getattr(manifest.ui, key)) == {x.id for x in getattr(document, key)}
            entry = next(e for e in catalogue["plugins"] if e["plugin_id"] == manifest.plugin_id)
            path = args.distribution_root / "dist" / entry["package"]["filename"]
            manifest = PluginManifest.model_validate(entry["manifest"])
            PluginPackageVerifier(publishers, require_signature=False).inspect(path)
            if manifest.integrity.signature is None:
                try:
                    PluginPackageVerifier(publishers).inspect(path)
                except PackageVerificationError:
                    pass
                else:
                    raise AssertionError("Strict verifier accepted an unsigned development package")
            else:
                PluginPackageVerifier(publishers).inspect(path)
            installed = registry.install_package(
                path.read_bytes(), path.name, installation_id=str(uuid4())
            )
            assert installed["plugin_id"] == manifest.plugin_id
            assert installed["version"] == manifest.version
            item = next(item for item in registry.list() if item["plugin_id"] == manifest.plugin_id)
            assert item["enabled"] is False
            runtime_document = registry.ui(manifest.plugin_id)
            PluginUiDocument.model_validate(runtime_document)
            if manifest.native_frontend is None:
                print(
                    f"{manifest.plugin_id}: host manifest/UI, payload digest, "
                    "installation and disabled lifecycle passed"
                )
                continue
            assert runtime_document["native_frontend"]["entry"] == manifest.native_frontend.entry
            try:
                registry.frontend(manifest.plugin_id, manifest.native_frontend.entry, native=True)
            except RuntimePolicyError:
                pass
            else:
                raise AssertionError("Disabled native assets were served")
            print(
                f"{manifest.plugin_id}: strict manifest/UI, permissions, digest, "
                "real installation and disabled lifecycle passed"
            )


if __name__ == "__main__":
    main()

