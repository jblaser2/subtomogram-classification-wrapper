"""
run_streaming()'s cancellation support -- the mechanism behind the GUI's
per-package Cancel button (see orchestrator.run_config()'s cancel_flags and
process.cancel_scope). Uses real subprocesses (python3 -c "sleep(...)"),
no external cryoET package needed, so this runs in plain CI.
"""
import threading
import time

import pytest

from stw.process import JobCancelled, cancel_scope, run_streaming


def _sleep_argv(seconds: float) -> list[str]:
    import sys

    return [sys.executable, "-c", f"import time; time.sleep({seconds})"]


def test_run_streaming_without_cancel_event_completes_normally():
    returncode, timing = run_streaming(_sleep_argv(0.1))
    assert returncode == 0
    assert timing.returncode == 0


def test_cancel_event_kills_a_long_running_subprocess():
    cancel_event = threading.Event()

    def _fire_soon():
        time.sleep(0.3)
        cancel_event.set()

    threading.Thread(target=_fire_soon, daemon=True).start()

    start = time.time()
    with pytest.raises(JobCancelled):
        run_streaming(_sleep_argv(30), cancel_event=cancel_event)
    elapsed = time.time() - start

    assert elapsed < 5.0  # nowhere near the full 30s sleep


def test_cancel_event_already_set_before_launch_kills_immediately():
    cancel_event = threading.Event()
    cancel_event.set()

    start = time.time()
    with pytest.raises(JobCancelled):
        run_streaming(_sleep_argv(30), cancel_event=cancel_event)
    elapsed = time.time() - start

    assert elapsed < 5.0


def test_cancel_event_not_set_lets_subprocess_finish_naturally():
    cancel_event = threading.Event()
    returncode, _timing = run_streaming(_sleep_argv(0.1), cancel_event=cancel_event)
    assert returncode == 0


def test_cancel_scope_is_picked_up_implicitly_without_an_explicit_param():
    """Adapters never pass cancel_event themselves -- the orchestrator sets it
    once via cancel_scope() and every run_streaming() call underneath, however
    deep in an adapter's own call stack, observes it automatically."""
    cancel_event = threading.Event()

    def _fire_soon():
        time.sleep(0.3)
        cancel_event.set()

    threading.Thread(target=_fire_soon, daemon=True).start()

    start = time.time()
    with cancel_scope(cancel_event), pytest.raises(JobCancelled):
        run_streaming(_sleep_argv(30))  # no cancel_event kwarg
    elapsed = time.time() - start

    assert elapsed < 5.0


def test_cancel_scope_resets_after_the_block():
    from stw.process import _CURRENT_CANCEL_EVENT

    assert _CURRENT_CANCEL_EVENT.get() is None
    cancel_event = threading.Event()
    with cancel_scope(cancel_event):
        assert _CURRENT_CANCEL_EVENT.get() is cancel_event
    # Outside the block, run_streaming must NOT see a stale cancel_event --
    # otherwise every later call in this thread would silently become
    # cancellable by a long-dead scope's Event.
    assert _CURRENT_CANCEL_EVENT.get() is None
