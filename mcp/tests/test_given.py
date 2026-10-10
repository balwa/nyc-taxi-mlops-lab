"""The MCP server against contracts/mcp-tools.json, and the given tool, with serving faked."""

import json
from pathlib import Path

import pytest

import labmcp.server as s

CONTRACT = {t["name"]: t for t in json.loads((Path(__file__).resolve().parents[2] / "contracts" / "mcp-tools.json").read_text())["tools"]}


async def test_tools_match_the_contract():
    tools = {t.name: t for t in await s.mcp.list_tools()}
    assert set(tools) == set(CONTRACT)
    for name, spec in CONTRACT.items():
        want, got = spec["inputSchema"], tools[name].inputSchema
        assert set(got.get("properties", {})) == set(want.get("properties", {})), name
        assert set(got.get("required", [])) == set(want.get("required", [])), name
        for prop, w in want.get("properties", {}).items():
            g = got["properties"][prop]
            flat = g if "anyOf" not in g else {k: v for alt in g["anyOf"] for k, v in alt.items() if alt.get("type") != "null"}
            for key in ("enum", "minimum", "maximum"):
                assert flat.get(key) == w.get(key), (name, prop, key)
        assert tools[name].description == spec["description"], name


async def test_get_model_info_reads_serving_champion(monkeypatch):
    seen = []

    async def champion(method, path, body=None):
        seen.append((method, path))
        return {"name": "trip-duration", "version": "3", "alias": "champion", "loaded_at": "2026-10-10T10:00:00+00:00",
                "tags": {"training_window": "2024-01..2024-03", "holdout_month": "2024-04", "features_version": "1", "mae_min": "3.65", "p95_latency_ms": "3.2", "git_sha": "x"}}

    monkeypatch.setattr(s, "champion", champion)
    out = json.loads((await s.mcp.call_tool("get_model_info", {}))[0].text)
    assert out["version"] == "3" and out["training_window"] == "2024-01..2024-03" and "git_sha" not in out
    assert seen == [("GET", "/model")]


def test_zone_names_resolve_and_typos_get_suggestions():
    assert s.zone_id("JFK Airport") == 132 and s.zone_id("times sq/theatre district") == 230
    with pytest.raises(ValueError, match="did you mean 'jfk airport'"):
        s.zone_id("JFK Airprot")
    assert s.DAYS.index("sunday") == 0  # features.yaml: pickup_dow 0 = Sunday
