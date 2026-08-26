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


def test_panel_titles_show_real_particle_counts_not_question_marks(client, tiny_fixture_dir, tmp_path, monkeypatch):
    """Regression test for the n=? bug: render_class_average_panel must be handed
    class_averages/n_per_class with matching key types (see test_results.py)."""
    captured = {}
    from stw.gui import render as render_module

    original = render_module.render_class_average_panel

    def spy(class_averages, n_per_class, out_png, title):
        captured["class_averages"] = class_averages
        captured["n_per_class"] = n_per_class
        return original(class_averages, n_per_class, out_png, title)

    monkeypatch.setattr(render_module, "render_class_average_panel", spy)

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

    res = client.get(f"/api/runs/{run_id}/panel/hac/2/1")
    assert res.status_code == 200
    assert set(captured["class_averages"].keys()) == set(captured["n_per_class"].keys())
    assert all(captured["n_per_class"][k] > 0 for k in captured["n_per_class"])


def test_preview_dataset_returns_specs_and_png(client, tiny_fixture_dir):
    res = client.post("/api/preview", json={
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
    })
    assert res.status_code == 200
    d = res.json()
    assert d["n_particles"] == 32
    assert d["box"] == 24
    assert d["pixel_size"] == 5.0
    assert len(d["preview_png_base64"]) > 0


def test_preview_dataset_rejects_bad_particle_dir(client):
    res = client.post("/api/preview", json={"particles": "/definitely/not/a/real/dir"})
    assert res.status_code == 422


@pytest.mark.parametrize(
    "mask",
    [
        {"kind": "sphere", "radius": 9.0},
        {"kind": "cylinder", "radius": 8.0, "half_height": 6.0, "axis": "z"},
        {"kind": "auto"},
    ],
)
def test_preview_mask_returns_specs_and_png(client, tiny_fixture_dir, mask):
    res = client.post("/api/preview-mask", json={
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "mask": mask,
    })
    assert res.status_code == 200
    d = res.json()
    assert d["n_particles"] == 32
    assert len(d["preview_png_base64"]) > 0


def test_preview_mask_rejects_missing_required_params(client, tiny_fixture_dir):
    res = client.post("/api/preview-mask", json={
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc",
        "mask": {"kind": "sphere"},
    })
    assert res.status_code == 422
    assert "radius" in res.json()["detail"]


def test_preview_mask_kind_none_is_rejected(client, tiny_fixture_dir):
    res = client.post("/api/preview-mask", json={
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc",
        "mask": {"kind": "none"},
    })
    assert res.status_code == 422


def test_packages_expose_algorithm_summary(client):
    res = client.get("/api/packages")
    packages = {p["name"]: p for p in res.json()}
    assert packages["stopgap"]["algorithm"]
    assert "Ward-HAC" in packages["hac"]["algorithm"]
    assert packages["pytom-preview"]["capabilities"]["k_range"] == [2, 2]


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
