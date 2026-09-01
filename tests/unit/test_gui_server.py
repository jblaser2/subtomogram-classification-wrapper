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


def _wait_for_preview(client, preview_id):
    """/api/preview and /api/preview-mask run as a background job (progress-bar
    support, see _throttled_progress in stw.gui.server) -- drain its SSE stream
    to completion, then fetch the result. Returns (status_code, body_or_detail)."""
    with client.stream("GET", f"/api/preview/{preview_id}/events") as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith("data: ") and '"preview_complete"' in line:
                break
    res = client.get(f"/api/preview/{preview_id}/result")
    if res.status_code != 200:
        return res.status_code, res.json()["detail"]
    return res.status_code, res.json()


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


def test_start_run_creates_a_cancel_flag_per_package(client, tiny_fixture_dir, tmp_path):
    from stw.gui.server import RUNS

    body = {
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "k": 2, "seeds": 1, "mask": {"kind": "sphere", "radius": 9.0},
        "packages": ["hac"], "out_dir": str(tmp_path / "out"),
    }
    res = client.post("/api/runs", json=body)
    assert res.status_code == 200
    d = res.json()
    assert d["packages"] == ["hac"]

    state = RUNS[d["run_id"]]
    assert "hac" in state.cancel_flags
    assert not state.cancel_flags["hac"].is_set()


def test_cancel_endpoint_sets_the_matching_event(client, tiny_fixture_dir, tmp_path):
    from stw.gui.server import RUNS

    body = {
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "k": 2, "seeds": 1, "mask": {"kind": "sphere", "radius": 9.0},
        "packages": ["hac"], "out_dir": str(tmp_path / "out"),
    }
    run_id = client.post("/api/runs", json=body).json()["run_id"]

    res = client.post(f"/api/runs/{run_id}/cancel/hac")
    assert res.status_code == 200
    assert res.json() == {"cancelled": "hac"}
    assert RUNS[run_id].cancel_flags["hac"].is_set()

    # drain the run so it doesn't linger as a background thread past the test
    with client.stream("GET", f"/api/runs/{run_id}/events") as resp:
        for line in resp.iter_lines():
            if line.startswith("data: ") and '"run_complete"' in line:
                break


def test_cancel_endpoint_404s_for_unknown_run_id(client):
    res = client.post("/api/runs/does-not-exist/cancel/hac")
    assert res.status_code == 404


def test_cancel_endpoint_404s_for_a_package_not_in_the_run(client, tiny_fixture_dir, tmp_path):
    body = {
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "k": 2, "seeds": 1, "mask": {"kind": "sphere", "radius": 9.0},
        "packages": ["hac"], "out_dir": str(tmp_path / "out"),
    }
    run_id = client.post("/api/runs", json=body).json()["run_id"]

    res = client.post(f"/api/runs/{run_id}/cancel/eman2")
    assert res.status_code == 404

    with client.stream("GET", f"/api/runs/{run_id}/events") as resp:
        for line in resp.iter_lines():
            if line.startswith("data: ") and '"run_complete"' in line:
                break


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

    def spy(class_averages, n_per_class, title):
        captured["class_averages"] = class_averages
        captured["n_per_class"] = n_per_class
        return original(class_averages, n_per_class, title)

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


def test_panel_reflects_current_run_not_a_stale_disk_cache(client, tiny_fixture_dir, tmp_path):
    """Regression test for a real bug found via the GUI: the class-average panel
    endpoint used to cache its rendered PNG on disk at a path keyed only by
    out_dir/package/k/seed -- reusing the same out_dir for a second, different
    dataset (e.g. switching from a test fixture to a real one without changing
    out_dir) served the FIRST dataset's stale rendered image even though the
    underlying class-average MRCs had correctly been overwritten with the new
    dataset's own averages. Panels are no longer disk-cached at all (see
    stw.gui.render's module docstring) -- this proves it end to end, not just
    that the function signature changed."""
    import mrcfile
    import numpy as np

    out_dir = tmp_path / "out"  # SAME out_dir reused for both runs, on purpose

    body1 = {
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "k": 2, "seeds": 1, "mask": {"kind": "sphere", "radius": 9.0},
        "packages": ["hac"], "out_dir": str(out_dir),
    }
    res1 = client.post("/api/runs", json=body1)
    run_id1 = res1.json()["run_id"]
    with client.stream("GET", f"/api/runs/{run_id1}/events") as resp:
        for line in resp.iter_lines():
            if line.startswith("data: ") and '"run_complete"' in line:
                break
    panel1 = client.get(f"/api/runs/{run_id1}/panel/hac/2/1").content

    other_dir = tmp_path / "other_particles"
    other_dir.mkdir()
    rng = np.random.default_rng(1)
    for i in range(8):
        with mrcfile.new(other_dir / f"p_{i:02d}.mrc", overwrite=True) as m:
            m.set_data(rng.normal(size=(24, 24, 24)).astype("float32"))
            m.voxel_size = 5.0
    body2 = {**body1, "particles": str(other_dir), "pattern": "*.mrc"}
    res2 = client.post("/api/runs", json=body2)
    run_id2 = res2.json()["run_id"]
    with client.stream("GET", f"/api/runs/{run_id2}/events") as resp:
        for line in resp.iter_lines():
            if line.startswith("data: ") and '"run_complete"' in line:
                break
    panel2 = client.get(f"/api/runs/{run_id2}/panel/hac/2/1").content

    assert panel1 != panel2  # must reflect the second run's own data, not the first's


def test_preview_dataset_returns_specs_and_png(client, tiny_fixture_dir):
    res = client.post("/api/preview", json={
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
    })
    assert res.status_code == 200
    preview_id = res.json()["preview_id"]
    assert res.json()["n_particles"] == 32

    status, d = _wait_for_preview(client, preview_id)
    assert status == 200
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
    preview_id = res.json()["preview_id"]

    status, d = _wait_for_preview(client, preview_id)
    assert status == 200
    assert d["n_particles"] == 32
    assert len(d["preview_png_base64"]) > 0


def test_preview_dataset_emits_progress_events(client, tiny_fixture_dir):
    """The GUI's dataset-preview progress bar depends on real "progress" SSE
    events (done/total), not just a final result -- see _throttled_progress."""
    import stw.gui.server as server_module

    # Other tests share this exact fixture/pattern/pixel-size fingerprint and may
    # have already warmed the cache -- a cache hit skips global_average() (and
    # therefore progress_cb) entirely, so force a cold start here.
    server_module._GLOBAL_AVG_CACHE.clear()
    server_module._GLOBAL_AVG_CACHE_ORDER.clear()

    res = client.post("/api/preview", json={
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
    })
    preview_id = res.json()["preview_id"]

    events = []
    with client.stream("GET", f"/api/preview/{preview_id}/events") as resp:
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            evt = json.loads(line[len("data: "):])
            events.append(evt)
            if evt["event"] == "preview_complete":
                break

    progress_events = [e for e in events if e["event"] == "progress"]
    assert progress_events, "no progress events emitted"
    assert progress_events[-1]["payload"]["done"] == 32
    assert progress_events[-1]["payload"]["total"] == 32
    assert events[-1]["event"] == "preview_complete"
    assert events[-1]["payload"]["status"] == "done"


def test_preview_mask_reuses_dataset_preview_global_average(client, tiny_fixture_dir, monkeypatch):
    """Regression test: previewing the mask right after previewing the dataset
    (or vice versa) must not re-stream the whole particle set off disk a second
    time -- see _cached_global_average(), keyed on ParticleSet.fingerprint()."""
    import stw.gui.server as server_module

    # The cache is a module-level dict shared across tests in this session (same
    # story as RUNS/ALIGNS) -- other tests reuse this exact fixture/pattern/pixel
    # size combo, so clear it first to guarantee a cold start here.
    server_module._GLOBAL_AVG_CACHE.clear()
    server_module._GLOBAL_AVG_CACHE_ORDER.clear()

    calls = []
    real_global_average = server_module.global_average

    def counting_global_average(*args, **kwargs):
        calls.append(1)
        return real_global_average(*args, **kwargs)

    monkeypatch.setattr(server_module, "global_average", counting_global_average)

    body = {"particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0}
    res1 = client.post("/api/preview", json=body)
    status1, _ = _wait_for_preview(client, res1.json()["preview_id"])
    assert status1 == 200
    assert len(calls) == 1

    res2 = client.post("/api/preview-mask", json={**body, "mask": {"kind": "sphere", "radius": 9.0}})
    status2, _ = _wait_for_preview(client, res2.json()["preview_id"])
    assert status2 == 200
    assert len(calls) == 1, "mask preview recomputed the global average instead of reusing the cache"


def test_preview_mask_rejects_missing_required_params(client, tiny_fixture_dir):
    # Fails synchronously (422, no preview_id) -- _validate_mask_body() runs
    # before any background job starts, so a typo'd mask form doesn't need an
    # SSE round trip just to report itself.
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


def test_preview_mask_center_override_actually_shifts_the_mask(client, tiny_fixture_dir):
    """Regression test for the GUI's off-center mask question: mask.center must
    reach the built mask, not just be silently accepted and ignored."""
    import base64

    from stw.masks.primitives import box_center, build_sphere

    res_centered = client.post("/api/preview-mask", json={
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "mask": {"kind": "sphere", "radius": 6.0},
    })
    res_offcenter = client.post("/api/preview-mask", json={
        "particles": str(tiny_fixture_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "mask": {"kind": "sphere", "radius": 6.0, "center": [4, 4, 4]},
    })
    assert res_centered.status_code == 200
    assert res_offcenter.status_code == 200
    status_centered, d_centered = _wait_for_preview(client, res_centered.json()["preview_id"])
    status_offcenter, d_offcenter = _wait_for_preview(client, res_offcenter.json()["preview_id"])
    assert status_centered == 200
    assert status_offcenter == 200
    png_centered = base64.b64decode(d_centered["preview_png_base64"])
    png_offcenter = base64.b64decode(d_offcenter["preview_png_base64"])
    assert png_centered != png_offcenter

    # sanity-check the underlying primitive directly too (isolates GUI plumbing
    # from the mask math itself)
    box = 24
    default = build_sphere((box, box, box), box_center((box, box, box)), 6.0, 3.0)
    offcenter = build_sphere((box, box, box), (4, 4, 4), 6.0, 3.0)
    assert not (default == offcenter).all()


def test_packages_expose_algorithm_summary(client):
    res = client.get("/api/packages")
    packages = {p["name"]: p for p in res.json()}
    assert packages["stopgap"]["algorithm"]
    assert "Ward-HAC" in packages["hac"]["algorithm"]
    assert packages["pytom-preview"]["capabilities"]["k_range"] == [2, 2]


def test_align_check_endpoint_returns_availability_shape(client):
    """CI-safe regardless of whether this machine actually has PyTom's FRM
    extension compiled -- just checks the endpoint never crashes and reports
    a well-formed availability check."""
    res = client.get("/api/align/check")
    assert res.status_code == 200
    d = res.json()
    assert isinstance(d["available"], bool)
    assert {c["kind"] for c in d["checks"]} == {"conda_env", "conda_python_import"}


def test_start_align_rejects_invalid_config(client, tmp_path):
    res = client.post("/api/align", json={"particles": str(tmp_path), "mask": {"kind": "none"}})
    assert res.status_code == 422
    assert "requires a mask" in res.json()["detail"]


def test_unknown_align_id_404s(client):
    assert client.get("/api/align/does-not-exist/report").status_code == 404
    assert client.get("/api/align/does-not-exist/events").status_code == 404
    assert client.get("/api/align/does-not-exist/preview").status_code == 404


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
