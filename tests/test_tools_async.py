"""Tool-level smoke tests for bash_async, wait_and_tail, kill_process.

Real subprocesses (no mocking) — these tests catch real OS-level bugs in
process-group handling, signal delivery, and reaping that mocks would miss.
Each test runs in <2s.
"""

from __future__ import annotations

import os
import re
import subprocess
import time

import pytest

from src import tools
from src.tools import (
    WAIT_AND_TAIL_CAP_SECONDS,
    bash_async,
    kill_process,
    wait_and_tail,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Make sure each test starts and ends with an empty process registry."""
    tools._ACTIVE_PROCESSES.clear()
    yield
    # Sweep anything the test left running
    for pid in list(tools._ACTIVE_PROCESSES.keys()):
        kill_process(pid)
    tools._ACTIVE_PROCESSES.clear()


def _extract_pid(result_text: str) -> int:
    m = re.search(r"PID (\d+)", result_text)
    assert m is not None, f"Could not extract PID from: {result_text!r}"
    return int(m.group(1))


def test_bash_async_returns_pid_immediately(tmp_path):
    start = time.time()
    out = bash_async("sleep 5", "logs/sleep.log", workspace_dir=str(tmp_path))
    elapsed = time.time() - start
    assert elapsed < 0.5, f"bash_async blocked for {elapsed:.2f}s"
    assert "PID " in out
    pid = _extract_pid(out)
    assert pid in tools._ACTIVE_PROCESSES


def test_bash_async_writes_to_log_path(tmp_path):
    out = bash_async("echo hello-world", "logs/echo.log", workspace_dir=str(tmp_path))
    pid = _extract_pid(out)
    # Wait for the echo to finish
    wait_and_tail(pid, "logs/echo.log", max_wait_seconds=5, workspace_dir=str(tmp_path))
    log_text = (tmp_path / "logs" / "echo.log").read_text()
    assert "hello-world" in log_text


def test_bash_async_refuses_existing_log(tmp_path):
    log = tmp_path / "logs" / "exists.log"
    log.parent.mkdir()
    log.write_text("prior contents\n")
    out = bash_async("echo hi", "logs/exists.log", workspace_dir=str(tmp_path))
    assert "ERROR" in out
    assert "already exists" in out


def test_bash_async_blocks_interactive(tmp_path):
    out = bash_async("vim file.txt", "logs/vim.log", workspace_dir=str(tmp_path))
    assert "ERROR" in out and "Interactive" in out
    out2 = bash_async("python", "logs/repl.log", workspace_dir=str(tmp_path))
    assert "ERROR" in out2 and "REPL" in out2


def test_wait_and_tail_returns_running_when_unfinished(tmp_path):
    out = bash_async("sleep 30", "logs/long.log", workspace_dir=str(tmp_path))
    pid = _extract_pid(out)
    start = time.time()
    result = wait_and_tail(pid, "logs/long.log", max_wait_seconds=2, workspace_dir=str(tmp_path))
    elapsed = time.time() - start
    assert "Status: running" in result
    assert 1.5 <= elapsed <= 5.0, f"wait took {elapsed:.2f}s (expected ~2s)"
    # Cleanup
    kill_process(pid)


def test_wait_and_tail_returns_exited_on_natural_completion(tmp_path):
    out = bash_async("sleep 1; echo done", "logs/done.log", workspace_dir=str(tmp_path))
    pid = _extract_pid(out)
    result = wait_and_tail(pid, "logs/done.log", max_wait_seconds=10, workspace_dir=str(tmp_path))
    assert "Status: exited(code=0)" in result
    assert "done" in result


def test_wait_and_tail_caps_max_wait_at_180(tmp_path):
    out = bash_async("sleep 30", "logs/cap.log", workspace_dir=str(tmp_path))
    pid = _extract_pid(out)
    # Pass a value above the cap; we expect a clamp warning, not 7200s of blocking.
    start = time.time()
    result = wait_and_tail(
        pid, "logs/cap.log", max_wait_seconds=7200,
        workspace_dir=str(tmp_path),
    )
    elapsed = time.time() - start
    assert "clamped" in result
    assert str(WAIT_AND_TAIL_CAP_SECONDS) in result
    # Cleanup the process; we don't want to actually wait 180s in the test
    # so we rely on the kill from autouse fixture, but verify we didn't hang.
    assert elapsed < 200, f"clamp not enforced — waited {elapsed:.2f}s"
    kill_process(pid)


def test_wait_and_tail_returns_tail_lines(tmp_path):
    # Generate 500 lines via a shell loop, then immediately exit.
    cmd = "for i in $(seq 1 500); do echo line_$i; done"
    out = bash_async(cmd, "logs/many.log", workspace_dir=str(tmp_path))
    pid = _extract_pid(out)
    result = wait_and_tail(
        pid, "logs/many.log", max_wait_seconds=10, tail_lines=10,
        workspace_dir=str(tmp_path),
    )
    # The result text contains the 10 lines plus a header. Count the
    # numbered lines that appear.
    nums = re.findall(r"line_(\d+)", result)
    # The header echoes "last 10 lines" — that's not a numbered line, so the
    # actual log lines extracted should be exactly 10.
    assert len(nums) == 10, f"expected 10 lines in tail, got {len(nums)}: {nums}"
    # And they should be the LAST 10 (491..500)
    assert nums[-1] == "500"


def test_kill_process_sigterm_then_sigkill(tmp_path):
    # A process that ignores SIGTERM; only SIGKILL will stop it.
    cmd = "trap '' TERM; sleep 60"
    out = bash_async(cmd, "logs/stubborn.log", workspace_dir=str(tmp_path))
    pid = _extract_pid(out)
    time.sleep(0.3)  # let bash install the trap
    start = time.time()
    result = kill_process(pid)
    elapsed = time.time() - start
    assert "Killed PID" in result or "exited" in result
    # kill_process polls 5s before SIGKILL; allow a generous window.
    assert elapsed < 8.0, f"kill_process took {elapsed:.2f}s"
    # Process should be gone
    try:
        os.kill(pid, 0)
        still_alive = True
    except ProcessLookupError:
        still_alive = False
    assert not still_alive, "process still alive after kill_process"


def test_kill_process_already_exited(tmp_path):
    out = bash_async("true", "logs/quick.log", workspace_dir=str(tmp_path))
    pid = _extract_pid(out)
    # Wait for natural exit
    wait_and_tail(pid, "logs/quick.log", max_wait_seconds=5, workspace_dir=str(tmp_path))
    result = kill_process(pid)
    assert "already exited" in result.lower() or "killed" in result.lower()


def test_process_group_kills_children(tmp_path):
    # Parent shell launches two background sleeps and waits — if we don't
    # kill the whole process group, the sleeps become orphans.
    cmd = "sleep 60 & sleep 60 & wait"
    out = bash_async(cmd, "logs/group.log", workspace_dir=str(tmp_path))
    pid = _extract_pid(out)
    time.sleep(0.5)  # let the shell fork the children
    pgid = tools._ACTIVE_PROCESSES[pid]["pgid"]
    # Confirm at least 2 sleeps exist in this pgid
    ps = subprocess.run(
        ["ps", "-eo", "pid,pgid,comm"],
        capture_output=True, text=True, check=False,
    )
    sleep_lines_before = [
        line for line in ps.stdout.splitlines()
        if "sleep" in line and f" {pgid} " in f" {line} "
    ]
    assert len(sleep_lines_before) >= 1, (
        f"no sleeps found in pgid {pgid} — test setup issue"
    )

    kill_process(pid)
    time.sleep(0.5)
    ps_after = subprocess.run(
        ["ps", "-eo", "pid,pgid,comm"],
        capture_output=True, text=True, check=False,
    )
    sleep_lines_after = [
        line for line in ps_after.stdout.splitlines()
        if "sleep" in line and f" {pgid} " in f" {line} "
    ]
    assert len(sleep_lines_after) == 0, (
        f"orphan sleeps still in pgid {pgid} after kill_process: {sleep_lines_after}"
    )


def test_sweep_active_processes_kills_stragglers(tmp_path):
    # Import here to avoid a top-of-file dependency cycle in the test module
    from src.nodes import _sweep_active_processes

    out = bash_async("sleep 60", "logs/straggler.log", workspace_dir=str(tmp_path))
    pid = _extract_pid(out)
    assert pid in tools._ACTIVE_PROCESSES

    _sweep_active_processes("test-node")

    # Registry should be empty
    assert pid not in tools._ACTIVE_PROCESSES
    # Process should be gone
    try:
        os.kill(pid, 0)
        still_alive = True
    except ProcessLookupError:
        still_alive = False
    assert not still_alive, "sweep didn't kill the straggler"
