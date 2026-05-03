"""Tests for src/trace_inspector.py — parses logs/all_messages.jsonl."""

from __future__ import annotations

import json
from pathlib import Path

from src.trace_inspector import inspect_trace


def _write_trace(path: Path, entries: list[dict]) -> None:
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _tool_use(name: str, **inp) -> dict:
    return {"type": "tool_use", "id": "tu_x", "name": name, "input": inp}


def test_inspect_trace_finds_async_pattern(tmp_path):
    trace = tmp_path / "all_messages.jsonl"
    _write_trace(trace, [
        {
            "node": "Model_Engineer",
            "tool_round": 1,
            "router_iteration": 1,
            "elapsed_min": 5.2,
            "messages": [
                {"role": "assistant", "content": [
                    _tool_use("bash_async", command="uv run python train.py", log_path="logs/train.log"),
                ]},
            ],
        },
        {
            "node": "Model_Engineer",
            "tool_round": 2,
            "router_iteration": 1,
            "elapsed_min": 7.4,
            "messages": [
                {"role": "assistant", "content": [
                    _tool_use("wait_and_tail", pid=12345, log_path="logs/train.log", max_wait_seconds=120),
                ]},
            ],
        },
    ])
    result = inspect_trace(str(trace))
    assert result["tool_call_counts"] == {"bash_async": 1, "wait_and_tail": 1}
    assert len(result["bash_async_calls"]) == 1
    assert result["bash_async_calls"][0]["log_path"] == "logs/train.log"
    # Async paired with wait — should not be flagged
    assert result["unpaired_bash_async"] == []


def test_inspect_trace_flags_unpaired_async(tmp_path):
    trace = tmp_path / "all_messages.jsonl"
    _write_trace(trace, [
        {
            "node": "Model_Engineer",
            "tool_round": 1,
            "router_iteration": 1,
            "elapsed_min": 5.0,
            "messages": [
                {"role": "assistant", "content": [
                    _tool_use("bash_async", command="train.py", log_path="logs/train.log"),
                ]},
            ],
        },
        # No subsequent wait_and_tail or kill_process — agent forgot.
        {
            "node": "Model_Engineer",
            "tool_round": 2,
            "router_iteration": 1,
            "elapsed_min": 6.0,
            "messages": [
                {"role": "assistant", "content": [
                    _tool_use("read_file", file_path="config.yaml"),
                ]},
            ],
        },
    ])
    result = inspect_trace(str(trace))
    assert len(result["unpaired_bash_async"]) == 1
    assert result["unpaired_bash_async"][0]["log_path"] == "logs/train.log"


def test_inspect_trace_flags_long_sync_training(tmp_path):
    trace = tmp_path / "all_messages.jsonl"
    _write_trace(trace, [
        {
            "node": "Model_Engineer",
            "tool_round": 1,
            "router_iteration": 1,
            "elapsed_min": 0.5,
            "messages": [
                {"role": "assistant", "content": [
                    _tool_use(
                        "run_bash_with_truncation",
                        command="uv run python train.py --epochs 50",
                        timeout_seconds=3600,
                    ),
                ]},
            ],
        },
        # A short sync command — should NOT be flagged.
        {
            "node": "Model_Engineer",
            "tool_round": 2,
            "router_iteration": 1,
            "elapsed_min": 0.6,
            "messages": [
                {"role": "assistant", "content": [
                    _tool_use(
                        "run_bash_with_truncation",
                        command="ls data/",
                        timeout_seconds=10,
                    ),
                ]},
            ],
        },
    ])
    result = inspect_trace(str(trace))
    flagged = result["run_bash_used_for_training"]
    assert len(flagged) == 1
    assert flagged[0]["timeout_seconds"] == 3600
    assert "train.py" in flagged[0]["command"]
