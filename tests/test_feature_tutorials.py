"""Execute exact wiki recipes with the shipped SDK and explicit protocol replies.

These establish plugin-side behavior, not host grant enforcement or persistence.
"""
import json
import re
import shutil
import subprocess
import sys

import pytest

from tools.distribution import ROOT

CASES = {
    "games": ("games.md", [{"games": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}],
              [("games.list", "games.read")], {"game_count": 3}),
    "media": ("media.md", [{"items": [{"id": "movie-1"}]}],
              [("media.list", "media.read")], {"items": [{"id": "movie-1"}]}),
    "events": ("events.md", [{"events": [{"event_type": "game.updated"}]}],
               [("events.poll", "events.subscribe")], {"event_types": ["game.updated"]}),
    "notifications": ("notifications.md", [{"sent": True}],
                      [("notifications.send", "notifications.send")], {"sent": True}),
    "background": ("background-tasks.md", [{}, {}],
                   [("capabilities.check", "tasks.background"), ("storage.put", "plugin.storage")],
                   {"queued": True}),
    "settings": ("settings.md", [{"value": "expanded"}],
                 [("settings.get", "plugin.settings")], {"display_mode": "expanded"}),
    "storage": ("storage.md", [{"value": '{"schema_version": 1, "game_count": 3}'}],
                [("storage.get", "plugin.storage")], {"report": {"schema_version": 1, "game_count": 3}}),
    "external-links": ("external-links.md", [], [],
                       {"redirect_url": "https://github.com/Unbound-Timeline-Shelf/Plugins"}),
}


def run_recipe(tmp_path, name, responses, values=None):
    page = (ROOT / "wiki/docs/development" / CASES[name][0]).read_text(encoding="utf-8")
    block = re.search(r"<!-- recipe: " + re.escape(name) + r" -->\s*```python\n(.*?)\n```", page, re.S)
    assert block, f"Missing exact recipe {name}"
    (tmp_path / "recipe.py").write_text(block[1], encoding="utf-8")
    shutil.copytree(ROOT / "sdk", tmp_path / "sdk", ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
    values = values if values is not None else {"_plugin_context": {"user_id": "alice"}}
    program = "import json,recipe; print(json.dumps({'result': recipe.run(" + repr(values) + ")}))"
    return subprocess.run([sys.executable, "-c", program], cwd=tmp_path,
                          input="".join(json.dumps(response) + "\n" for response in responses),
                          text=True, capture_output=True)


@pytest.mark.parametrize("name", CASES)
def test_exact_recipe_protocol_and_result(tmp_path, name):
    _, responses, calls, expected = CASES[name]
    result = run_recipe(tmp_path, name, [{"payload": reply} for reply in responses])
    assert result.returncode == 0, result.stderr
    output = [json.loads(line) for line in result.stdout.splitlines()]
    assert output[-1] == {"result": expected}
    assert [(call["method"], call["capability"]) for call in output[:-1]] == calls
    assert all(call["api_version"] == "v1" for call in output[:-1])
    if name == "games": assert output[0]["payload"] == {"limit": 50}
    if name == "media": assert output[0]["payload"] == {"limit": 100}
    if name == "storage": assert output[0]["payload"]["key"] == "users/alice/latest-report"
    if name == "background":
        assert output[1]["payload"]["key"].startswith("sync/requests/")
        assert json.loads(output[1]["payload"]["value"]) == {"requested": True}


@pytest.mark.parametrize("name", [name for name in CASES if name != "external-links"])
def test_denied_gateway_reply_fails_without_further_requests(tmp_path, name):
    result = run_recipe(tmp_path, name, [{"error": "Permission denied"}])
    assert result.returncode != 0 and "Permission denied" in result.stderr
    assert len(result.stdout.splitlines()) == 1


@pytest.mark.parametrize("value", [None, "", False, 0])
def test_settings_defaults_only_absent_values(tmp_path, value):
    result = run_recipe(tmp_path, "settings", [{"payload": {"value": value}}])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "result": {"display_mode": "compact" if value is None else value}}


def test_storage_requires_host_identity_and_rejects_corrupt_json(tmp_path):
    result = run_recipe(tmp_path, "storage", [], values={})
    assert result.returncode != 0 and not result.stdout
    result = run_recipe(tmp_path, "storage", [{"payload": {"value": "corrupt"}}])
    assert result.returncode != 0 and "JSONDecodeError" in result.stderr
