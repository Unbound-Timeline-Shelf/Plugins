"""Fixtures for the live Atlas contract lane. See tests/atlas_live/README.md."""
import importlib.util
import os
from pathlib import Path

import pytest

import atlas_live_support as support
from sdk import metadata_provider as sdk

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def live_env():
    return {"url": os.environ["ATLAS_LIVE_URL"].rstrip("/"), "bootstrap": os.environ["ATLAS_LIVE_BOOTSTRAP_TOKEN"],
            "container": os.environ["ATLAS_LIVE_CONTAINER"]}


@pytest.fixture(scope="session")
def atlas_api(live_env):
    return support.Atlas(live_env["url"], live_env["container"])


@pytest.fixture(scope="session")
def seeded(atlas_api, live_env):
    return support.seed(atlas_api, live_env["bootstrap"], live_env["url"])


@pytest.fixture
def plugin(monkeypatch):
    directory = ROOT / "official" / "metadata-atlas"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("metadata_atlas_live_under_test", directory / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def gateway(monkeypatch, live_env, seeded):
    """A gateway configured like a user with a read-scope token, talking to the real container."""
    live = support.LiveGateway(live_env["url"], seeded.read_token)
    monkeypatch.setattr(sdk, "request", live)
    return live

