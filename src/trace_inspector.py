"""Parse logs/all_messages.jsonl and surface tool-use patterns.

The JSONL trace is append-only and written per ReAct round by `_dump_trace`
in src/nodes.py. This module reads it (mid-run or post-run) and reports
patterns that indicate the agent is using the async-bash tools correctly,
and flags suspected misuse.

Run as a CLI:
    uv run python -m src.trace_inspector <workspace>/logs/all_messages.jsonl
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from typing import Any

# Heuristic: run_bash_with_truncation calls that look like training and used
# a long timeout — these are the calls the agent should have made async.
_TRAINING_KEYWORDS = ("train", "fit", "optuna", "search", "tune")
_TRAINING_TIMEOUT_THRESHOLD = 600


def _iter_tool_uses(messages: list[dict]) -> list[dict]:
    """Yield tool_use blocks from a list of message dicts."""
    out = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                out.append(block)
    return out


def inspect_trace(jsonl_path: str) -> dict[str, Any]:
    """Read a logs/all_messages.jsonl trace and summarize tool usage.

    Returns a dict with:
        tool_call_counts: tool name -> count
        bash_async_calls: list of {round, command, log_path, pid_returned} entries
        unpaired_bash_async: list of pids that have a bash_async but never a
            subsequent wait_and_tail or kill_process — smoking gun for misuse
        run_bash_used_for_training: list of {round, command, timeout} where
            run_bash_with_truncation was called with training-flavored command
            and a timeout above _TRAINING_TIMEOUT_THRESHOLD seconds
        wall_clock_at_node_exit: list of {node, round, elapsed_min}
    """
    counts: dict[str, int] = defaultdict(int)
    bash_async_calls: list[dict] = []
    paired_pids: set[int] = set()
    seen_pids: list[int] = []
    sync_training: list[dict] = []
    node_exits: list[dict] = []

    last_round_per_node: dict[str, int] = {}

    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            node = entry.get("node", "?")
            tool_round = entry.get("tool_round", 0)
            elapsed_min = entry.get("elapsed_min", 0.0)
            messages = entry.get("messages", [])

            last_round_per_node[node] = max(last_round_per_node.get(node, 0), tool_round)

            for block in _iter_tool_uses(messages):
                name = block.get("name", "")
                inp = block.get("input", {}) or {}
                counts[name] += 1

                if name == "bash_async":
                    bash_async_calls.append({
                        "round": tool_round,
                        "node": node,
                        "command": inp.get("command", "")[:200],
                        "log_path": inp.get("log_path", ""),
                    })
                elif name in ("wait_and_tail", "kill_process"):
                    pid = inp.get("pid")
                    if isinstance(pid, int):
                        paired_pids.add(pid)

                if name == "run_bash_with_truncation":
                    cmd = str(inp.get("command", "")).lower()
                    timeout = int(inp.get("timeout_seconds", 300))
                    if (
                        timeout > _TRAINING_TIMEOUT_THRESHOLD
                        and any(kw in cmd for kw in _TRAINING_KEYWORDS)
                    ):
                        sync_training.append({
                            "round": tool_round,
                            "node": node,
                            "command": str(inp.get("command", ""))[:200],
                            "timeout_seconds": timeout,
                        })

            # tool_round may be 0 on initial trace dumps; we look at the last
            # entry per node for the "exit" elapsed minutes.
            if last_round_per_node.get(node) == tool_round:
                # Track candidate exit; will be overwritten by later entries.
                # End-of-loop we keep the highest tool_round per node.
                node_exits = [e for e in node_exits if e["node"] != node]
                node_exits.append({
                    "node": node,
                    "round": tool_round,
                    "elapsed_min": elapsed_min,
                })

    # Find unpaired bash_async — the trace doesn't include the PID returned
    # by bash_async (that's in tool_result, which is truncated). So we
    # approximate: an "unpaired" bash_async is one in a node where there's
    # no subsequent wait_and_tail/kill_process at all.
    unpaired_bash_async: list[dict] = []
    waits_per_node: dict[str, int] = defaultdict(int)
    asyncs_per_node: dict[str, int] = defaultdict(int)
    for call in bash_async_calls:
        asyncs_per_node[call["node"]] += 1
    for entry_node in counts:
        # Sum wait_and_tail and kill_process per node would need re-iteration;
        # we track at the call-site level below.
        pass
    # Re-walk to count waits per node — simpler than threading through above.
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            node = entry.get("node", "?")
            for block in _iter_tool_uses(entry.get("messages", [])):
                if block.get("name") in ("wait_and_tail", "kill_process"):
                    waits_per_node[node] += 1

    for call in bash_async_calls:
        if waits_per_node[call["node"]] == 0:
            unpaired_bash_async.append(call)

    return {
        "tool_call_counts": dict(counts),
        "bash_async_calls": bash_async_calls,
        "unpaired_bash_async": unpaired_bash_async,
        "run_bash_used_for_training": sync_training,
        "wall_clock_at_node_exit": node_exits,
    }


def _format_summary(result: dict[str, Any]) -> str:
    out: list[str] = []
    out.append("=== Tool call counts ===")
    if not result["tool_call_counts"]:
        out.append("  (no tool calls found)")
    for name, count in sorted(
        result["tool_call_counts"].items(), key=lambda kv: -kv[1]
    ):
        out.append(f"  {count:>5d}  {name}")

    out.append("")
    out.append("=== bash_async calls ===")
    if not result["bash_async_calls"]:
        out.append("  (none — agent did no async launches)")
    for call in result["bash_async_calls"]:
        out.append(
            f"  [r{call['round']:>3d} {call['node']}] log={call['log_path']}  "
            f"cmd={call['command']!r}"
        )

    out.append("")
    out.append("=== Unpaired bash_async (no wait/kill in same node) ===")
    if not result["unpaired_bash_async"]:
        out.append("  (clean — every async launch paired with wait or kill)")
    for call in result["unpaired_bash_async"]:
        out.append(
            f"  WARN [r{call['round']} {call['node']}]: {call['command']!r} "
            f"-> {call['log_path']}"
        )

    out.append("")
    out.append("=== Sync training calls (should have been async) ===")
    if not result["run_bash_used_for_training"]:
        out.append("  (clean — no long sync training calls)")
    for call in result["run_bash_used_for_training"]:
        out.append(
            f"  WARN [r{call['round']} {call['node']}] timeout={call['timeout_seconds']}s: "
            f"{call['command']!r}"
        )

    out.append("")
    out.append("=== Wall clock at last trace per node ===")
    for exit_entry in result["wall_clock_at_node_exit"]:
        out.append(
            f"  {exit_entry['node']:<20s} round={exit_entry['round']:>3d} "
            f"elapsed={exit_entry['elapsed_min']:.1f} min"
        )
    return "\n".join(out)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m src.trace_inspector <path-to-all_messages.jsonl>", file=sys.stderr)
        return 2
    result = inspect_trace(sys.argv[1])
    print(_format_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
