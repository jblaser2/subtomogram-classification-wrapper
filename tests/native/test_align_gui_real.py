"""
Real end-to-end test of `stw gui`'s Align feature through the actual HTTP
API (FastAPI TestClient, no browser needed) — requires a real PyTom install
plus the compiled FRM extension (see docs/install/pytom.md,
scripts/compile_pytom_frm.sh). Never run in CI. Run manually via:

    pytest tests/native/test_align_gui_real.py -v -m native

Mirrors tests/native/test_align_pytom_frm_real.py's rough-copy technique but
drives it through the GUI's own submit -> SSE progress -> report -> preview
surface, the same contract the frontend actually uses.
"""
import json

import numpy as np
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from stw.align import check_installed  # noqa: E402
from stw.gui.server import create_app  # noqa: E402

pytestmark = pytest.mark.native


def _skip_if_not_installed():
    checks = check_installed()
    if not all(c.ok for c in checks):
        pytest.skip(
            "PyTom / compiled _swig_frm extension not found — see "
            "docs/install/pytom.md and scripts/compile_pytom_frm.sh"
        )


def _make_rough_copy(src_dir, dst_dir, pattern="particle_*.mrc", seed=0):
    import mrcfile
    from scipy.ndimage import rotate
    from scipy.ndimage import shift as nd_shift

    rng = np.random.default_rng(seed)
    dst_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p.name for p in src_dir.glob(pattern))
    for f in files:
        with mrcfile.open(src_dir / f, permissive=True) as m:
            vol = np.asarray(m.data).astype(np.float32)
            apix = float(m.voxel_size.x)
        angles = rng.uniform(-20, 20, size=3)
        shifts = rng.uniform(-3, 3, size=3)
        v = rotate(vol, angles[0], axes=(1, 2), reshape=False, order=1, mode="constant")
        v = rotate(v, angles[1], axes=(0, 2), reshape=False, order=1, mode="constant")
        v = rotate(v, angles[2], axes=(0, 1), reshape=False, order=1, mode="constant")
        v = nd_shift(v, shifts, order=1, mode="constant")
        with mrcfile.new(dst_dir / f, overwrite=True) as m:
            m.set_data(v.astype(np.float32))
            m.voxel_size = apix
    return files


@pytest.fixture
def client():
    return TestClient(create_app())


def test_align_check_reports_available(client):
    _skip_if_not_installed()
    res = client.get("/api/align/check")
    assert res.json()["available"] is True


def test_full_align_via_http_api(client, tiny_fixture_dir, tmp_path):
    _skip_if_not_installed()
    rough_dir = tmp_path / "rough"
    files = _make_rough_copy(tiny_fixture_dir, rough_dir)

    body = {
        "particles": str(rough_dir), "pattern": "particle_*.mrc", "pixel_size": 5.0,
        "mask": {"kind": "sphere", "radius": 10.0}, "out_dir": str(tmp_path / "out"),
    }
    res = client.post("/api/align", json=body)
    assert res.status_code == 200
    align_id = res.json()["align_id"]

    events = []
    with client.stream("GET", f"/api/align/{align_id}/events") as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            evt = json.loads(line[len("data: "):])
            events.append(evt)
            if evt["event"] == "run_complete":
                break

    assert events
    assert events[-1]["event"] == "run_complete"
    assert events[-1]["payload"]["status"] == "done"

    res = client.get(f"/api/align/{align_id}/report")
    assert res.status_code == 200
    report = res.json()
    assert report["status"] == "ok"
    assert report["n_particles"] == len(files)

    res = client.get(f"/api/align/{align_id}/preview")
    assert res.status_code == 200
    preview = res.json()
    assert preview["n_particles"] == len(files)
    assert len(preview["preview_png_base64"]) > 0
