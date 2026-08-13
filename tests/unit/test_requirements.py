from stw.requirements import CHECKERS, ReqKind, Requirement


def test_executable_checker_not_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = CHECKERS[ReqKind.EXECUTABLE](Requirement(ReqKind.EXECUTABLE, "definitely_not_a_real_binary"))
    assert result.ok is False
    assert "not found" in result.message


def test_executable_checker_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    result = CHECKERS[ReqKind.EXECUTABLE](Requirement(ReqKind.EXECUTABLE, "python3"))
    assert result.ok is True
    assert result.found == "/usr/bin/python3"


def test_conda_env_checker_not_found(tmp_path, monkeypatch):
    # Force the path-heuristic branch regardless of whether this test runner
    # itself has a real `conda`/`mamba` on PATH.
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    result = CHECKERS[ReqKind.CONDA_ENV](Requirement(ReqKind.CONDA_ENV, "nonexistent_env"))
    assert result.ok is False


def test_conda_env_checker_found_via_path_heuristic(tmp_path, monkeypatch):
    (tmp_path / "conda-envs" / "myenv").mkdir(parents=True)
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    result = CHECKERS[ReqKind.CONDA_ENV](Requirement(ReqKind.CONDA_ENV, "myenv"))
    assert result.ok is True


def test_conda_env_checker_found_via_conda_env_list(monkeypatch):
    """Covers the portability fix: an env living somewhere the hardcoded path
    heuristic would never find (e.g. a container's /opt/conda/envs) is still
    detected when `conda env list --json` reports it."""
    import json

    class FakeCompletedProcess:
        stdout = json.dumps({"envs": ["/opt/conda", "/opt/conda/envs/eman2"]})

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/conda" if name == "conda" else None)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: FakeCompletedProcess())
    result = CHECKERS[ReqKind.CONDA_ENV](Requirement(ReqKind.CONDA_ENV, "eman2"))
    assert result.ok is True
    assert result.found == "/opt/conda/envs/eman2"


def test_conda_env_checker_conda_list_failure_falls_back(tmp_path, monkeypatch):
    """If `conda env list --json` errors (bad install, timeout, ...), the
    checker must fall back to the path heuristic rather than raising."""
    (tmp_path / "conda-envs" / "myenv").mkdir(parents=True)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/conda" if name == "conda" else None)

    def _raise(*a, **k):
        raise OSError("conda not actually runnable")

    monkeypatch.setattr("subprocess.run", _raise)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    result = CHECKERS[ReqKind.CONDA_ENV](Requirement(ReqKind.CONDA_ENV, "myenv"))
    assert result.ok is True


def test_python_import_checker():
    ok_result = CHECKERS[ReqKind.PYTHON_IMPORT](Requirement(ReqKind.PYTHON_IMPORT, "numpy"))
    assert ok_result.ok is True
    bad_req = Requirement(ReqKind.PYTHON_IMPORT, "definitely_not_a_module")
    bad_result = CHECKERS[ReqKind.PYTHON_IMPORT](bad_req)
    assert bad_result.ok is False


def test_env_var_checker(monkeypatch):
    monkeypatch.delenv("STW_TEST_VAR", raising=False)
    assert CHECKERS[ReqKind.ENV_VAR](Requirement(ReqKind.ENV_VAR, "STW_TEST_VAR")).ok is False
    monkeypatch.setenv("STW_TEST_VAR", "1")
    assert CHECKERS[ReqKind.ENV_VAR](Requirement(ReqKind.ENV_VAR, "STW_TEST_VAR")).ok is True


def test_executable_checker_falls_back_to_detail_dirs(tmp_path, monkeypatch):
    """Covers binaries that are commonly a from-source build at a fixed
    location rather than something an installer puts on PATH (e.g. RELION's
    relion_refine) -- req.detail is a searched fallback, not just metadata."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    bin_dir = tmp_path / "relion-install" / "bin"
    bin_dir.mkdir(parents=True)
    binary = bin_dir / "relion_refine"
    binary.write_text("#!/bin/sh\necho fake\n")
    binary.chmod(0o755)

    req = Requirement(ReqKind.EXECUTABLE, "relion_refine", detail=str(bin_dir))
    result = CHECKERS[ReqKind.EXECUTABLE](req)
    assert result.ok is True
    assert result.found == str(binary)


def test_executable_checker_detail_dir_missing_binary(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    req = Requirement(ReqKind.EXECUTABLE, "relion_refine", detail=str(tmp_path))
    result = CHECKERS[ReqKind.EXECUTABLE](req)
    assert result.ok is False


def test_gpu_checker_absent(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = CHECKERS[ReqKind.GPU](Requirement(ReqKind.GPU, "nvidia", optional=True))
    assert result.ok is False


def test_no_checker_ever_raises_when_missing():
    """Every checker must return a clean not-found result, never an exception —
    this is what lets `stw check-env` and adapter contract tests run safely
    with zero cryoET software installed."""
    for kind, checker in CHECKERS.items():
        req = Requirement(kind, "totally-nonexistent-thing-xyz", detail="1")
        result = checker(req)
        assert result.requirement is req
