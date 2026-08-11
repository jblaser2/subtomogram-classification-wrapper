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
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    result = CHECKERS[ReqKind.CONDA_ENV](Requirement(ReqKind.CONDA_ENV, "nonexistent_env"))
    assert result.ok is False


def test_conda_env_checker_found(tmp_path, monkeypatch):
    (tmp_path / "conda-envs" / "myenv").mkdir(parents=True)
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
