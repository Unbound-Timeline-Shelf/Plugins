"""The checked-in manifest schema follows the host's PluginManifest (Plugin API 1.1.20, host PR #534)."""

import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "tools/schemas/manifest-v1.schema.json").read_text(encoding="utf-8"))


def atlas_manifest(**changes):
    manifest = json.loads((ROOT / "official/metadata-atlas/manifest.json").read_text(encoding="utf-8"))
    manifest.update(changes)
    return manifest


def test_every_official_manifest_validates():
    for path in sorted(ROOT.glob("official/*/manifest.json")):
        jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), SCHEMA)


@pytest.mark.parametrize("value", ["1.1.25", None])
def test_a_manifest_may_declare_api_contract_max(value):
    """C16 22.6 / W-6: the optional newest contract a plugin also supports (absent or null means the declared one)."""
    jsonschema.validate(atlas_manifest(api_contract_version="1.1.20", api_contract_max=value), SCHEMA)


def test_api_contract_max_is_a_string_and_unknown_fields_stay_refused():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(atlas_manifest(api_contract_max=1), SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(atlas_manifest(api_contract_maximum="1.1.25"), SCHEMA)
