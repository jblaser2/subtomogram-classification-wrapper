"""
GUI backend tests -- exercises the FastAPI app via TestClient, no browser or
real network socket needed. Runs an actual job (HAC Baseline, Tier A, always
"installed") through the full HTTP surface: submit -> SSE progress -> report
-> rendered class-average panel PNG. HAC needs the `viz` extra (matplotlib)
for panel rendering, already pulled in by the `gui` extra.
"""
import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from stw.gui.server import create_app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(create_app())


def test_list_packages_includes_hac_and_capabilities(client):
    res = client.get("/api/packages")
    assert res.status_code == 200
    packages = res.json()
    names = {p["name"] for p in packages}
    assert "hac" in names
    assert "stopgap" in names
    hac = next(p for p in packages if p["name"] == "hac")
    assert hac["installed"] is True  # Tier A, always vendored
    assert "mask_kinds" in hac["capabilities"]


def test_schema_endpoint_returns_runconfig_json_schema(client):
    res = client.get("/api/schema")
    assert res.status_code == 200
    schema = res.json()
    assert "particles" in schema["properties"]
    assert "packages" in schema["properties"]


def test_static_frontend_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    res = client.get("/app.js")
    assert res.status_code == 200


def test_start_run_rejects_invalid_config(client):
    res = client.post("/api/runs", json={"particles": "/nonexistent", "packages": []})
    assert res.status_code == 422
    assert "packages" in res.json()["detail"]


def test_unknown_run_id_404s(client):
    assert client.get("/api/runs/does-not-exist/report").status_code == 404
    assert client.get("/api/runs/does-not-exist/events").status_code == 404


def test_report_not_ready_while_running_returns_409_or_completes(client, tiny_fixture_dir, tmp_path):
    """Loose timing check: right after submit the run may already be done (HAC
    on 32 particles is fast) or still running -- either is a valid immediate
    response, the real behavior is exercised end-to-end below."""
    body = {
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "k": 2, "seeds": 1, "mask": {"kind": "sphere", "radius": 9.0},
        "packages": ["hac"], "out_dir": str(tmp_path / "out"),
    }
    res = client.post("/api/runs", json=body)
    run_id = res.json()["run_id"]
    res = client.get(f"/api/runs/{run_id}/report")
    assert res.status_code in (200, 409)


def test_full_run_via_http_api(client, tiny_fixture_dir, tmp_path):
    body = {
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "k": 2, "seeds": 1, "mask": {"kind": "sphere", "radius": 9.0},
        "packages": ["hac"], "out_dir": str(tmp_path / "out"),
    }
    res = client.post("/api/runs", json=body)
    assert res.status_code == 200
    run_id = res.json()["run_id"]

    events = []
    with client.stream("GET", f"/api/runs/{run_id}/events") as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            evt = json.loads(line[len("data: "):])
            events.append(evt)
            if evt["event"] == "run_complete":
                break

    assert events, "no SSE events received"
    assert events[-1]["event"] == "run_complete"
    assert events[-1]["payload"]["status"] == "done"
    assert any(e["event"] == "start_job" and e["package"] == "hac" for e in events)
    assert any(e["event"] == "finish_job" and e["package"] == "hac" for e in events)

    res = client.get(f"/api/runs/{run_id}/report")
    assert res.status_code == 200
    report = res.json()
    hac_result = next(r for r in report["results"] if r["package"] == "hac")
    assert hac_result["status"] == "ok"
    assert sum(hac_result["n_per_class"].values()) == 32

    res = client.get(f"/api/runs/{run_id}/panel/hac/2/1")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert len(res.content) > 0


def test_comparison_png_404s_with_only_one_successful_package(client, tiny_fixture_dir, tmp_path):
    """build_comparison needs >=2 successful results (same rule the orchestrator
    itself enforces) -- a single-package run has no comparison figure at all."""
    body = {
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "k": 2, "seeds": 1, "mask": {"kind": "sphere", "radius": 9.0},
        "packages": ["hac"], "out_dir": str(tmp_path / "out"),
    }
    res = client.post("/api/runs", json=body)
    run_id = res.json()["run_id"]
    with client.stream("GET", f"/api/runs/{run_id}/events") as resp:
        for line in resp.iter_lines():
            if line.startswith("data: ") and '"run_complete"' in line:
                break

    assert client.get(f"/api/runs/{run_id}/comparison.png").status_code == 404
