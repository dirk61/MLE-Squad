"""LangGraph node implementations for the MLE Agent.

Implements:
- make_action_node(): Factory for ReAct-loop Action Nodes
  (Data_Engineer, Model_Engineer, Evaluator)
- system_architect_node(): Workspace bootstrap + architecture planning
- router_brain_node(): Context cleansing + routing decisions

See spec_state.md Node Definitions for authoritative definitions.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import time

from src import tools
from src.llm import MODEL_MAP, call_llm
from src.observability import resource_snapshot

log = logging.getLogger("mle_agent")
from src.medal_thresholds import get_medal_thresholds
from src.prompts import assemble_router_input, assemble_system_prompt
from src.state import AgentState
from src.tool_node import dispatch_tool_calls
from src.tools import TOOL_SCHEMAS

# ── Constants ────────────────────────────────────────────────────────────

# Maximum tool-call rounds per Action Node invocation.
# 35 covers a full pipeline: ~10 baseline + ~10 first tuning + ~10 second
# model + ~5 ensemble/finalize. Rounds beyond ~30 are empirically noise-level
# CV gains (<0.3% relative) that hurt test generalization.
DEFAULT_RECURSION_LIMIT = 35

# Wall-clock timeout for the entire graph run (seconds).
# Default 0 = no cap (D19). The 15-iteration Router cap, per-node recursion
# limit, plateau detection, and the new [BLOCKER] TYPE: Unrecoverable path
# already provide multiple termination mechanisms; the wall-clock cap was
# blocking long-but-productive CPU runs. Set MLE_AGENT_TIMEOUT to a positive
# integer to re-enable a hard cap (e.g. for a constrained CI envelope).
GRAPH_WALL_CLOCK_TIMEOUT = int(os.environ.get("MLE_AGENT_TIMEOUT", 0))

# Maximum Router transitions before forcing END.
# Happy path = ~5 cycles. 15 allows 2-3 rewinds within a ~1 hr budget.
MAX_ITERATIONS = 15

# Where competition workspaces are created
# Use /data1 if available (3TB+ disk for torch CUDA packages, models, etc.)
# Falls back to /tmp in Docker/CI where /data1 doesn't exist.
_DEFAULT_WORKSPACE = "/data1/six004/tmp/mle_agent_workspaces" if os.path.isdir("/data1") else "/tmp/mle_agent_workspaces"
WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", _DEFAULT_WORKSPACE)

# Reverse mapping: Anthropic model ID -> tier name
_REVERSE_MODEL_MAP: dict[str, str] = {v: k for k, v in MODEL_MAP.items()}

# Router next_node -> phase label
_PHASE_MAP: dict[str, str] = {
    "System_Architect": "architecture",
    "Data_Engineer": "data_engineering",
    "Model_Engineer": "model_engineering",
    "Evaluator": "evaluation",
    "END": "END",
}


# ── Wall-Clock Safety Net ────────────────────────────────────────────────

_GRAPH_START_KEY = "_MLE_AGENT_GRAPH_START"


def _init_wall_clock() -> None:
    """Set the graph start time (once, on first call)."""
    if _GRAPH_START_KEY not in os.environ:
        os.environ[_GRAPH_START_KEY] = str(time.time())


def _elapsed_min() -> float:
    """Minutes elapsed since graph start."""
    start = os.environ.get(_GRAPH_START_KEY)
    if not start:
        return 0.0
    return (time.time() - float(start)) / 60.0


def _wall_clock_exceeded() -> bool:
    """Check if the total graph run has exceeded GRAPH_WALL_CLOCK_TIMEOUT.

    Returns False when the cap is disabled (<=0), which is the default per D19.
    """
    if GRAPH_WALL_CLOCK_TIMEOUT <= 0:
        return False
    start = os.environ.get(_GRAPH_START_KEY)
    if not start:
        return False
    return (time.time() - float(start)) > GRAPH_WALL_CLOCK_TIMEOUT


# ── Background Process Sweep ─────────────────────────────────────────────


def _sweep_active_processes(node_name: str) -> None:
    """Kill any background processes spawned by bash_async that didn't get cleaned up.

    The "no background process survives a node exit" invariant — see decisions.md
    D17. Called on every exit path of _run_react_loop (end_turn, wall-clock break,
    recursion limit, exceptions). The agent is supposed to wait_and_tail or
    kill_process on its own; this is the safety net.
    """
    if not tools._ACTIVE_PROCESSES:
        return
    leaked_pids = list(tools._ACTIVE_PROCESSES.keys())
    for pid in leaked_pids:
        entry = tools._ACTIVE_PROCESSES.get(pid, {})
        pgid = entry.get("pgid", pid)
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception:
            pass
    # Brief grace period for SIGTERM to take effect
    time.sleep(0.5)
    for pid in leaked_pids:
        entry = tools._ACTIVE_PROCESSES.get(pid, {})
        pgid = entry.get("pgid", pid)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception:
            pass
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        tools._ACTIVE_PROCESSES.pop(pid, None)
    log.warning(
        "[%s] Swept %d straggler process(es) at node exit: %s",
        node_name, len(leaked_pids), leaked_pids,
    )


# ── Trace Dump ───────────────────────────────────────────────────────────

_TRACE_PATH = "logs/all_messages.jsonl"


def _dump_trace(workspace_dir: str, node_name: str, tool_round: int,
                iteration_count: int, messages: list[dict]) -> None:
    """Append the latest messages to a JSONL trace file for mid-run diagnosis.

    Each line is one snapshot: node, round, iteration, elapsed, and the
    latest assistant+tool exchange. The full file is the complete trace.
    """
    if not workspace_dir or workspace_dir == ".":
        return
    trace_file = os.path.join(workspace_dir, _TRACE_PATH)
    os.makedirs(os.path.dirname(trace_file), exist_ok=True)
    # Write the last 2 messages (assistant response + tool result).
    # Truncate long tool results to keep trace readable but still diagnostic.
    recent = messages[-2:] if len(messages) >= 2 else messages
    truncated = []
    for msg in recent:
        msg_copy = dict(msg)
        content = msg_copy.get("content", "")
        if isinstance(content, list):
            new_blocks = []
            for block in content:
                if isinstance(block, dict) and "content" in block:
                    text = str(block["content"])
                    if len(text) > 1000:
                        block = {**block, "content": text[:500] + "\n...[TRUNCATED]...\n" + text[-500:]}
                new_blocks.append(block)
            msg_copy["content"] = new_blocks
        truncated.append(msg_copy)
    entry = {
        "node": node_name,
        "tool_round": tool_round,
        "router_iteration": iteration_count,
        "elapsed_min": round(_elapsed_min(), 1),
        "messages": truncated,
    }
    try:
        with open(trace_file, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass  # non-critical — don't crash the pipeline for a log write

    # Also log a compact summary to stderr so it appears in platform logs
    tool_names = []
    for msg in recent:
        for b in (msg.get("content", []) if isinstance(msg.get("content"), list) else []):
            if isinstance(b, dict) and b.get("type") == "tool_use":
                tool_names.append(b["name"])
    log.info(
        "[TRACE] %s r=%d iter=%d [%.1fmin] tools=%s",
        node_name, tool_round, iteration_count, _elapsed_min(), tool_names or "end_turn",
    )


# ── Context Window Management ────────────────────────────────────────────

# Max recent message pairs (assistant + tool_result) to keep in context.
# Each pair ≈ 2-4K tokens. 20 pairs ≈ 40-80K tokens — fits comfortably
# in context while preventing the unbounded growth that makes round 50
# cost 5x more than round 5.
MAX_CONTEXT_PAIRS = 20


def _windowed_messages(messages: list[dict]) -> list[dict]:
    """Keep the first message + last MAX_CONTEXT_PAIRS exchanges.

    Inserts a summary note when old messages are dropped so the LLM
    knows context was trimmed and can read_file() logs if needed.
    """
    if len(messages) <= 1 + MAX_CONTEXT_PAIRS * 2:
        return messages  # fits already

    first = messages[:1]  # handoff / instructions
    recent = messages[-(MAX_CONTEXT_PAIRS * 2):]
    dropped = len(messages) - len(first) - len(recent)

    summary = {
        "role": "user",
        "content": (
            f"[System: {dropped} earlier messages were trimmed from context to save tokens. "
            "Your earlier work is preserved in logs/bash_history.log and logs/all_messages.jsonl — "
            "use read_file() if you need to review past output.]"
        ),
    }
    return first + [summary] + recent


# ── Message Helpers ──────────────────────────────────────────────────────


def _response_to_message(response) -> dict:
    """Convert an Anthropic Message response to a state message dict.

    Preserves thinking and redacted_thinking blocks alongside text and
    tool_use. With adaptive thinking on (opus/sonnet tiers), the API
    verifies thinking-block signatures across turns — dropping them
    would break the round-trip and waste the cached prefix.
    """
    content: list[dict] = []
    for block in response.content:
        if block.type == "text":
            content.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            content.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
        elif block.type == "thinking":
            content.append({
                "type": "thinking",
                "thinking": block.thinking,
                "signature": block.signature,
            })
        elif block.type == "redacted_thinking":
            content.append({"type": "redacted_thinking", "data": block.data})
    return {"role": "assistant", "content": content}


def _extract_text(response) -> str:
    """Extract concatenated text content from an Anthropic response."""
    parts: list[str] = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
    return "\n".join(parts)


# ── Core ReAct Loop ──────────────────────────────────────────────────────


def _run_react_loop(
    *,
    node_name: str,
    state: AgentState,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
) -> dict:
    """Run the ReAct loop for an Action Node.

    Repeats: LLM call -> tool dispatch -> LLM call ...
    until the LLM produces no tool calls (end_turn) or the
    recursion_limit is reached.

    Returns a state update dict with messages, handoff_message,
    and micro_tasks.
    """
    workspace_dir = state.get("workspace_dir", ".")
    tier = state.get("target_model", "sonnet")
    messages: list[dict] = list(state.get("messages", []))
    micro_tasks: list[dict] = list(state.get("micro_tasks", []))

    # Seed messages with handoff_message if empty (post-Router wipe)
    if not messages:
        handoff = state.get("handoff_message", "")
        messages = [{"role": "user", "content": handoff or "Begin your work."}]

    system = assemble_system_prompt(node_name, workspace_dir=workspace_dir)
    handoff_message = ""
    tool_rounds = 0
    # Track wall-clock start for the entire graph (shared via env marker)
    _init_wall_clock()
    log.info(
        "[%s] Starting ReAct loop (tier=%s) [%.1f min elapsed] | %s",
        node_name, tier, _elapsed_min(), resource_snapshot(),
    )

    try:
        while tool_rounds < recursion_limit:
            # Safety net: abort if total graph time exceeds wall-clock timeout
            if _wall_clock_exceeded():
                handoff_message = (
                    f"[{node_name}] Wall-clock timeout ({GRAPH_WALL_CLOCK_TIMEOUT}s) exceeded. "
                    "Yielding to Router — must validate submission.csv and finalize immediately."
                )
                log.warning(handoff_message)
                break

            # Sliding context window: keep first message (handoff/instructions)
            # + last MAX_CONTEXT_MESSAGES exchanges to prevent unbounded token growth.
            # Old messages are already persisted in logs/all_messages.jsonl and
            # logs/bash_history.log — the LLM can read_file() them if needed.
            llm_messages = _windowed_messages(messages)

            response = call_llm(
                tier=tier,
                system=system,
                messages=llm_messages,
                tools=TOOL_SCHEMAS,
            )

            assistant_msg = _response_to_message(response)
            messages.append(assistant_msg)

            if response.stop_reason == "tool_use":
                tool_calls = [b for b in assistant_msg["content"] if b.get("type") == "tool_use"]
                tool_names = [b["name"] for b in tool_calls]
                # Show timeout for bash calls so it's visible in logs
                bash_timeouts = [
                    f"bash(timeout={b['input'].get('timeout_seconds', 300)}s)"
                    for b in tool_calls if b["name"] == "run_bash_with_truncation"
                ]
                log.info(
                    "[%s] Tool round %d/%d: %s %s [%.1f min]",
                    node_name, tool_rounds + 1, recursion_limit,
                    tool_names, bash_timeouts or "", _elapsed_min(),
                )
                # Log the command being run so it's visible externally
                for b in tool_calls:
                    if b["name"] == "run_bash_with_truncation":
                        cmd = str(b["input"].get("command", "")).replace("\n", " ; ")[:200]
                        log.info("[%s]   cmd: %s", node_name, cmd)
                tool_result_msg, micro_tasks = dispatch_tool_calls(
                    assistant_msg, workspace_dir, micro_tasks
                )
                # Log preview of tool results
                for block in tool_result_msg.get("content", []):
                    if isinstance(block, dict) and "content" in block:
                        preview = str(block["content"])[:500].replace("\n", " | ")
                        log.info("[%s]   -> %s", node_name, preview)
                messages.append(tool_result_msg)
                tool_rounds += 1
                # Dump trace for mid-run diagnosis
                _dump_trace(
                    workspace_dir, node_name, tool_rounds,
                    state.get("iteration_count", 0), messages,
                )
                continue

            if response.stop_reason == "max_tokens":
                # Truncated — ask the LLM to continue
                messages.append({
                    "role": "user",
                    "content": "[System: Your response was truncated. Please continue.]",
                })
                continue

            # end_turn or other — LLM is done
            handoff_message = _extract_text(response)
            log.info(
                "[%s] Done after %d tool rounds [%.1f min]. Handoff: %.300s",
                node_name, tool_rounds, _elapsed_min(), handoff_message,
            )
            _dump_trace(
                workspace_dir, node_name, tool_rounds,
                state.get("iteration_count", 0), messages,
            )
            break
        else:
            # Recursion limit hit
            handoff_message = (
                f"[{node_name}] Recursion limit ({recursion_limit}) reached. "
                "Yielding to Router with partial progress."
            )
    finally:
        # Sweep any background processes the agent left running. Per D17,
        # no bash_async-launched process is allowed to survive a node exit.
        _sweep_active_processes(node_name)

    # Safety net: auto-commit any uncommitted work the LLM left behind.
    # The Sign-Off protocol asks the LLM to commit, but it doesn't always.
    _auto_commit(workspace_dir, node_name)

    log.info(
        "[%s] Exiting ReAct loop after %d rounds [%.1f min] | %s",
        node_name, tool_rounds, _elapsed_min(), resource_snapshot(),
    )

    return {
        "messages": messages,
        "handoff_message": handoff_message,
        "micro_tasks": micro_tasks,
    }


def _auto_commit(workspace_dir: str, node_name: str) -> None:
    """Commit code/memory files the LLM left behind after a node exit.

    Never stages data files, images, models, or archives — only
    source code, scripts, and memory markdown files.
    """
    if not workspace_dir or workspace_dir == ".":
        return
    # Check if there's anything to commit (quick check first)
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace_dir, capture_output=True, text=True, check=False,
    )
    if not status.stdout.strip():
        return  # nothing to commit

    # Stage only code and memory files — never data/images/models
    subprocess.run(
        ["git", "add",
         "*.py", "*.md", "*.txt", "*.json", "*.yaml", "*.yml",
         "*.toml", "*.lock", "*.sh",
         "src/", "logs/",
        ],
        cwd=workspace_dir, capture_output=True, check=False,
    )
    # Unstage any large files so giant training logs don't bloat git history.
    # 1 MB cap is well above bash_history.log (~30KB) but well below typical
    # bash_async training logs.
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=workspace_dir, capture_output=True, text=True, check=False,
    )
    skipped_large: list[str] = []
    for fname in staged.stdout.strip().splitlines():
        full = os.path.join(workspace_dir, fname)
        try:
            size = os.path.getsize(full)
        except OSError:
            continue
        if size > 1_000_000:
            subprocess.run(
                ["git", "reset", "HEAD", "--", fname],
                cwd=workspace_dir, capture_output=True, check=False,
            )
            skipped_large.append(f"{fname} ({size//1024}KB)")
    if skipped_large:
        log.info("[%s] Skipped large files from auto-commit: %s", node_name, ", ".join(skipped_large))

    # Check if anything is still staged after the size filter
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=workspace_dir, capture_output=True, text=True, check=False,
    )
    if not staged.stdout.strip():
        return
    subprocess.run(
        ["git", "commit", "-m", f"Auto-commit after {node_name} exit"],
        cwd=workspace_dir, capture_output=True, check=False,
    )
    log.info("[%s] Auto-committed: %s", node_name, staged.stdout.strip().replace("\n", ", "))


# ── Action Node Factory ─────────────────────────────────────────────────


def make_action_node(node_name: str):
    """Create a LangGraph node function for a standard Action Node.

    Used for Data_Engineer, Model_Engineer, and Evaluator.
    System_Architect has its own node function (with bootstrap).
    """

    def node_fn(state: AgentState) -> dict:
        return _run_react_loop(node_name=node_name, state=state)

    node_fn.__name__ = node_name.lower()
    node_fn.__doc__ = f"Action Node: {node_name}"
    return node_fn


# ── System_Architect Node ────────────────────────────────────────────────


def system_architect_node(state: AgentState) -> dict:
    """System_Architect node with workspace bootstrap on first entry.

    First entry: creates workspace dir, runs git init + uv init,
    copies dataset from staging path, sets workspace_dir in state.
    Re-entry: workspace already exists, runs ReAct loop directly.
    """
    workspace_dir = state.get("workspace_dir", "")
    messages: list[dict] = list(state.get("messages", []))
    first_entry = not workspace_dir

    if first_entry:
        staging_path = state.get("handoff_message", "")
        competition_id = state.get("competition_id", "") or "competition"
        workspace_dir = _bootstrap_workspace(staging_path, competition_id)

        # Annotate the first user message with workspace info only
        bootstrap_note = (
            "\n\n---\n"
            f"[System] Workspace bootstrapped at: {workspace_dir}\n"
            "Dataset files placed in: data/raw/\n"
            "git and uv initialized. All tool paths are relative to workspace root."
        )
        if messages and messages[0]["role"] == "user":
            content = messages[0]["content"]
            if isinstance(content, str):
                messages[0] = {
                    "role": "user",
                    "content": content + bootstrap_note,
                }
            else:
                # Content is a list of blocks — append a text block
                messages[0] = {
                    "role": "user",
                    "content": list(content)
                    + [{"type": "text", "text": bootstrap_note}],
                }
        else:
            messages.insert(0, {"role": "user", "content": bootstrap_note.strip()})

    # Build effective state for the ReAct loop
    effective_state = {
        **state,
        "workspace_dir": workspace_dir,
        "messages": messages,
    }
    # On first entry Router hasn't run yet — force Opus tier
    if first_entry:
        effective_state["target_model"] = "opus"

    # Architect should finish in ~15-20 tool rounds (EDA + write 3 files + commit).
    # Cap at 25 to prevent runaway EDA loops.
    result = _run_react_loop(
        node_name="System_Architect", state=effective_state, recursion_limit=25,
    )
    result["workspace_dir"] = workspace_dir
    return result


def _bootstrap_workspace(staging_path: str, competition_id: str = "competition") -> str:
    """Create and initialize a competition workspace.

    Creates directory structure per spec_memory.md section 0,
    runs git init + uv init, copies dataset from staging_path
    into data/raw/.

    Returns absolute path to the new workspace directory.
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_id = competition_id.replace("/", "_").replace(" ", "_")
    workspace_name = f"{safe_id}_{timestamp}"
    workspace_dir = os.path.join(WORKSPACE_ROOT, workspace_name)

    # Create workspace directory structure
    for subdir in ("data/raw", "data/processed", "src", "models", "logs"):
        os.makedirs(os.path.join(workspace_dir, subdir), exist_ok=True)

    # Write .gitignore to prevent staging large data/model files
    gitignore = os.path.join(workspace_dir, ".gitignore")
    with open(gitignore, "w") as f:
        f.write(
            "# Auto-generated — never commit raw data, images, or model binaries\n"
            "data/raw/\n"
            "data/processed/\n"
            "*.zip\n*.tar\n*.tar.gz\n*.pt\n*.pth\n*.pkl\n*.h5\n*.joblib\n"
            "*.jpg\n*.jpeg\n*.png\n*.gif\n*.bmp\n*.tif\n*.tiff\n"
            "*.mp3\n*.wav\n*.flac\n*.ogg\n"
            ".venv/\n__pycache__/\n*.pyc\n"
        )

    # Symlink project prompts into workspace so read_file("prompts/...") works.
    # Resolves the path mismatch between workspace (/tmp/...) and project root.
    project_prompts = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts"
    )
    workspace_prompts = os.path.join(workspace_dir, "prompts")
    if os.path.isdir(project_prompts) and not os.path.exists(workspace_prompts):
        os.symlink(project_prompts, workspace_prompts)

    # git init + set user config (required in containers with no global git config)
    subprocess.run(["git", "init"], cwd=workspace_dir, capture_output=True, check=False)
    subprocess.run(
        ["git", "config", "user.name", "MLE Agent"],
        cwd=workspace_dir, capture_output=True, check=False,
    )
    subprocess.run(
        ["git", "config", "user.email", "agent@mle-bench.local"],
        cwd=workspace_dir, capture_output=True, check=False,
    )

    # uv init with pinned Python — avoids picking up conda/system interpreters.
    # Strip VIRTUAL_ENV and CONDA_PREFIX so uv uses its own managed Python.
    clean_env = {
        k: v for k, v in os.environ.items()
        if k not in ("VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV")
    }
    if os.path.isdir("/data1"):
        clean_env.setdefault("UV_CACHE_DIR", "/data1/six004/tmp/uv_cache")
        clean_env.setdefault("TMPDIR", "/data1/six004/tmp")
    subprocess.run(
        ["uv", "init", "--python", "3.12"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        check=False,
        env=clean_env,
    )

    # Copy dataset from staging path if available.
    # Green agent packages data under home/data/ inside the tar.
    if staging_path and os.path.isdir(staging_path):
        # Prefer home/data/ subdir if it exists (green agent tar layout)
        data_src = os.path.join(staging_path, "home", "data")
        if not os.path.isdir(data_src):
            data_src = staging_path  # fallback: flat staging dir

        raw_dir = os.path.join(workspace_dir, "data", "raw")
        for item in os.listdir(data_src):
            src_path = os.path.join(data_src, item)
            dst_path = os.path.join(raw_dir, item)
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
            else:
                shutil.copy2(src_path, dst_path)

    return workspace_dir


# ── Router_Brain Node ────────────────────────────────────────────────────


def router_brain_node(state: AgentState) -> dict:
    """Router_Brain: context cleansing + routing decision.

    1. Append messages -> all_messages (via reducer), wipe messages
    2. Wipe micro_tasks
    3. Increment iteration_count
    4. Check iteration budget — force END if exceeded
    5. Call Haiku with assembled Router input block
    6. Parse JSON response, set state fields
    """
    messages = state.get("messages", [])
    iteration_count = state.get("iteration_count", 0) + 1
    workspace_dir = state.get("workspace_dir", ".")
    current_phase = state.get("current_phase", "architecture")
    handoff_message = state.get("handoff_message", "")

    # Context cleansing: feed messages to all_messages reducer, wipe active
    state_update: dict = {
        "all_messages": list(messages),  # operator.add reducer appends
        "messages": [],                  # wipe active history
        "micro_tasks": [],               # wipe ephemeral tasks
        "iteration_count": iteration_count,
    }

    _init_wall_clock()
    log.info(
        "[Router] Iteration %d/%d | Phase: %s [%.1f min elapsed]",
        iteration_count, MAX_ITERATIONS, current_phase, _elapsed_min(),
    )

    # Safety circuit breaker — route to Evaluator first (to validate
    # submission), then END on the next iteration.
    if iteration_count > MAX_ITERATIONS:
        if current_phase != "evaluation":
            # Haven't evaluated yet — give Evaluator one last chance
            state_update.update({
                "current_phase": "evaluation",
                "target_model": "sonnet",
                "handoff_message": (
                    f"Iteration budget ({MAX_ITERATIONS}) exceeded. "
                    "Validate submission.csv and finalize — this is the last pass."
                ),
            })
        else:
            # Already evaluated — go to END
            state_update.update({
                "current_phase": "END",
                "target_model": "sonnet",
                "handoff_message": (
                    f"Iteration budget ({MAX_ITERATIONS}) exceeded. Routing to END."
                ),
            })
        return state_update

    # Assemble Router input block
    router_input = assemble_router_input(
        current_phase=current_phase,
        handoff_message=handoff_message,
        iteration_count=iteration_count,
        workspace_dir=workspace_dir,
    )

    # Call Haiku for routing decision
    system = assemble_system_prompt("Router_Brain")
    response = call_llm(
        tier="haiku",
        system=system,
        messages=[{"role": "user", "content": router_input}],
    )

    # Parse JSON routing decision
    response_text = _extract_text(response)
    decision = _parse_router_json(response_text)

    next_node = decision.get("next_node", "END")
    raw_model = decision.get("target_model", "claude-sonnet-4-6")
    rewind_reason = decision.get("rewind_reason")

    # Map model ID to tier name
    tier = _REVERSE_MODEL_MAP.get(raw_model, "sonnet")

    # Build handoff message for next node
    if rewind_reason:
        new_handoff = rewind_reason
    else:
        new_handoff = f"Proceed with {next_node} phase."

    # Map next_node to phase label
    new_phase = _PHASE_MAP.get(next_node, current_phase)

    state_update.update({
        "current_phase": new_phase,
        "target_model": tier,
        "handoff_message": new_handoff,
    })

    log.info("[Router] -> %s (tier=%s, phase=%s) [%.1f min]", next_node, tier, new_phase, _elapsed_min())
    return state_update


def _parse_router_json(text: str) -> dict:
    """Extract JSON routing decision from Router response text.

    Handles JSON in markdown code blocks, bare JSON, or embedded
    JSON objects. Falls back to routing to END on parse failure.
    """
    # Try code block first (```json ... ```)
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try bare JSON
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Try finding any JSON object in the text
    match = re.search(r"\{[^{}]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Fallback — route to END
    return {
        "next_node": "END",
        "target_model": "claude-sonnet-4-6",
        "rewind_reason": None,
    }
