"""Tool implementations and Anthropic tool schemas for the MLE Agent.

All tools operate relative to a workspace_dir (the competition workspace).
See spec_tool.md for authoritative parameter definitions and constraints.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time

# ── Constants ────────────────────────────────────────────────────────────────

MAX_OUTPUT_CHARS = 8_000
TRUNCATION_KEEP = 2_000
MAX_FILE_LINES = 10_000

# Cap on wait_and_tail's max_wait_seconds. Forces the agent to resurface every
# 3 minutes worst-case so the harness's wall-clock check, trace dump, and
# context-windowing keep firing. The agent picks values <= this per call.
WAIT_AND_TAIL_CAP_SECONDS = 180

INTERACTIVE_BLOCKLIST = frozenset(
    {"vim", "vi", "nano", "emacs", "less", "more", "top", "htop"}
)

# Process registry for bash_async-spawned children. Keyed by PID; values carry
# the process group ID (so we can SIGTERM/SIGKILL the whole tree), the log
# path, the original command, and timing info. Module-global because the
# LangGraph runtime is single-process; cleaned by _sweep_active_processes
# in src/nodes.py at every Action Node exit.
_ACTIVE_PROCESSES: dict[int, dict] = {}

# ── 1. Execution Tools ──────────────────────────────────────────────────────


def _check_command_guards(command: str) -> str | None:
    """Return an error string if the command is blocked, else None."""
    first_token = command.strip().split()[0] if command.strip() else ""
    if first_token in INTERACTIVE_BLOCKLIST:
        return (
            f"[ERROR: Interactive command '{first_token}' is not allowed. "
            "Use non-interactive alternatives.]"
        )
    if command.strip() in ("python", "python3"):
        return (
            "[ERROR: Interactive Python REPL is not allowed. "
            "Use 'uv run python script.py' instead.]"
        )
    return None


def _build_subprocess_env() -> dict:
    """Strip venv/conda vars and apply /data1 cache defaults."""
    env = {
        k: v for k, v in os.environ.items()
        if k not in ("VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV")
    }
    if os.path.isdir("/data1"):
        env.setdefault("UV_CACHE_DIR", "/data1/six004/tmp/uv_cache")
        env.setdefault("TMPDIR", "/data1/six004/tmp")
    return env


def run_bash_with_truncation(
    command: str,
    timeout_seconds: int = 300,
    *,
    workspace_dir: str = ".",
) -> str:
    """Execute a shell command with output truncation and timeout."""
    err = _check_command_guards(command)
    if err is not None:
        return err

    env = _build_subprocess_env()

    try:
        result = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
            cwd=workspace_dir,
            text=True,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        # Capture any partial output the process produced before being killed
        partial = ""
        if e.stdout:
            partial = e.stdout if isinstance(e.stdout, str) else e.stdout.decode("utf-8", errors="replace")
            # Keep last 2K chars so the agent can see what happened
            if len(partial) > 2000:
                partial = "...\n" + partial[-2000:]
        _persist_bash_output(workspace_dir, command, partial, -1)
        return f"[ERROR: Command timed out after {timeout_seconds}s]\n{partial}"
    except Exception as e:
        return f"[ERROR: Failed to execute command]\n{e}"

    output = result.stdout or ""
    exit_code = result.returncode

    # Persist all command output to a log file that survives context wipes.
    # Any future node can read_file("logs/bash_history.log") to see past output.
    _persist_bash_output(workspace_dir, command, output, exit_code)

    # Truncate if combined output exceeds limit
    if len(output) > MAX_OUTPUT_CHARS:
        output = (
            output[:TRUNCATION_KEEP]
            + "\n...[OUTPUT TRUNCATED]...\n"
            + output[-TRUNCATION_KEEP:]
        )

    if exit_code != 0:
        return f"[ERROR: Command failed with exit code {exit_code}]\n{output}"

    return output


def _persist_bash_output(workspace_dir: str, command: str, output: str, exit_code: int) -> None:
    """Append command output to logs/bash_history.log for cross-session persistence.

    Only logs commands that run Python scripts or failed commands — skips
    trivial shell commands (ls, pwd, git, wc, head, cat, etc.) to keep
    the log focused on training/processing output.
    """
    # Skip trivial commands — only persist script runs and errors
    cmd_start = command.strip().split()[0] if command.strip() else ""
    is_script_run = "python" in command or ".py" in command
    is_error = exit_code != 0
    if not is_script_run and not is_error:
        return

    try:
        log_dir = os.path.join(workspace_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "bash_history.log"), "a") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"$ {command}\n")
            f.write(f"exit_code={exit_code}\n")
            f.write(f"{'='*60}\n")
            # Keep last 3K chars of output — enough for training summaries
            if len(output) > 3000:
                f.write("...[truncated]...\n" + output[-3000:])
            else:
                f.write(output)
            f.write("\n")
    except Exception:
        pass  # non-critical


# ── 1b. Async Execution Tools (background process + log tail + kill) ────────


def bash_async(
    command: str,
    log_path: str,
    *,
    workspace_dir: str = ".",
) -> str:
    """Launch a shell command in a new process group; return PID immediately.

    stdout+stderr redirect to log_path inside the workspace. Use for any
    command expected to run >60s (training, hyperparameter searches). Always
    pair with wait_and_tail to observe and kill_process to terminate.
    """
    err = _check_command_guards(command)
    if err is not None:
        return err

    full_log_path = log_path if os.path.isabs(log_path) else os.path.join(workspace_dir, log_path)
    if os.path.exists(full_log_path) and os.path.getsize(full_log_path) > 0:
        return (
            f"[ERROR: log_path '{log_path}' already exists and is non-empty. "
            "Pick a unique path like logs/train_attempt2.log to keep replay history clean.]"
        )

    parent = os.path.dirname(full_log_path)
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
        except Exception as e:
            return f"[ERROR: Cannot create log directory: {e}]"

    env = _build_subprocess_env()

    try:
        log_fh = open(full_log_path, "w")
    except Exception as e:
        return f"[ERROR: Cannot open log file for writing: {e}]"

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            cwd=workspace_dir,
            text=True,
            env=env,
            start_new_session=True,
        )
    except Exception as e:
        log_fh.close()
        return f"[ERROR: Failed to launch process: {e}]"

    # Caller doesn't need the file handle — process owns it now.
    log_fh.close()

    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        # Process exited immediately — pgid lookup fails. Treat as exited.
        pgid = proc.pid

    _ACTIVE_PROCESSES[proc.pid] = {
        "pgid": pgid,
        "log_path": full_log_path,
        "command": command,
        "started_at": time.time(),
        "workspace_dir": workspace_dir,
    }

    return (
        f"Started PID {proc.pid} (pgid {pgid}); logging to {log_path}.\n"
        f"Use wait_and_tail(pid={proc.pid}, log_path='{log_path}', max_wait_seconds=N) "
        f"to observe (cap {WAIT_AND_TAIL_CAP_SECONDS}s). "
        f"Use kill_process(pid={proc.pid}) to terminate on divergence."
    )


def _read_log_tail(full_log_path: str, tail_lines: int) -> str:
    """Read the last N lines of a log file via shell tail, with truncation."""
    if not os.path.isfile(full_log_path):
        return f"[log file not found: {full_log_path}]"
    try:
        result = subprocess.run(
            ["tail", "-n", str(tail_lines), full_log_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        out = result.stdout or ""
    except Exception as e:
        return f"[tail failed: {e}]"
    if len(out) > MAX_OUTPUT_CHARS:
        out = (
            out[:TRUNCATION_KEEP]
            + "\n...[OUTPUT TRUNCATED]...\n"
            + out[-TRUNCATION_KEEP:]
        )
    return out


def _process_status(pid: int) -> tuple[str, int | None]:
    """Probe a PID; return (status, exit_code).

    status: 'running' | 'exited' | 'dead'
    exit_code populated only on 'exited' (we reaped it).
    """
    # Try to reap if it's our child
    try:
        wpid, status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        # Not our child or already reaped — fall through to liveness probe.
        wpid = 0
        status = 0

    if wpid == pid:
        # Reaped naturally
        if os.WIFEXITED(status):
            return "exited", os.WEXITSTATUS(status)
        if os.WIFSIGNALED(status):
            return "exited", -os.WTERMSIG(status)
        return "exited", None

    # Liveness probe via signal 0
    try:
        os.kill(pid, 0)
        return "running", None
    except ProcessLookupError:
        return "dead", None
    except PermissionError:
        # Process exists but we can't signal it — treat as running.
        return "running", None


def wait_and_tail(
    pid: int,
    log_path: str,
    max_wait_seconds: int,
    tail_lines: int = 200,
    *,
    workspace_dir: str = ".",
) -> str:
    """Block up to max_wait_seconds OR until process exits, whichever first.

    NOTE: max_wait_seconds is a CAP, not a kill — exceeding it leaves the
    process running. The agent then decides: wait_and_tail again, kill_process,
    or move on. Capped at WAIT_AND_TAIL_CAP_SECONDS (180s) for harness safety.
    """
    clamped = False
    if max_wait_seconds > WAIT_AND_TAIL_CAP_SECONDS:
        max_wait_seconds = WAIT_AND_TAIL_CAP_SECONDS
        clamped = True
    if max_wait_seconds < 0:
        max_wait_seconds = 0

    full_log_path = log_path if os.path.isabs(log_path) else os.path.join(workspace_dir, log_path)

    started_at = _ACTIVE_PROCESSES.get(pid, {}).get("started_at")
    deadline = time.time() + max_wait_seconds
    poll_interval = 2.0
    final_status = "running"
    exit_code: int | None = None

    while True:
        status, code = _process_status(pid)
        if status != "running":
            final_status = status
            exit_code = code
            break
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(poll_interval, remaining))

    # Drop from registry on terminal status
    if final_status in ("exited", "dead"):
        _ACTIVE_PROCESSES.pop(pid, None)

    runtime_seconds = (time.time() - started_at) if started_at else None

    header_parts = [f"Status: {final_status}"]
    if final_status == "exited" and exit_code is not None:
        header_parts[0] = f"Status: exited(code={exit_code})"
    if runtime_seconds is not None:
        header_parts.append(f"runtime={runtime_seconds:.1f}s")
    if clamped:
        header_parts.append(
            f"[NOTE: max_wait_seconds clamped to {WAIT_AND_TAIL_CAP_SECONDS}s — "
            "harness safety cap]"
        )
    header = " | ".join(header_parts)

    tail = _read_log_tail(full_log_path, tail_lines)
    return f"{header}\n--- last {tail_lines} lines of {log_path} ---\n{tail}"


def kill_process(pid: int) -> str:
    """SIGTERM the process group; SIGKILL after 5s grace. Return final tail."""
    entry = _ACTIVE_PROCESSES.get(pid)
    pgid = entry["pgid"] if entry else None
    if pgid is None:
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            return f"PID {pid} already exited."

    log_path = entry["log_path"] if entry else None

    # SIGTERM first
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        _ACTIVE_PROCESSES.pop(pid, None)
        return f"PID {pid} already exited."
    except PermissionError as e:
        return f"[ERROR: Cannot signal pgid {pgid}: {e}]"

    # Poll up to 5s for exit
    deadline = time.time() + 5.0
    while time.time() < deadline:
        status, _ = _process_status(pid)
        if status != "running":
            break
        time.sleep(0.2)

    # SIGKILL if still alive
    status, _ = _process_status(pid)
    if status == "running":
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        # SIGKILL is asynchronous; poll briefly for the kernel to reap.
        deadline2 = time.time() + 2.0
        while time.time() < deadline2:
            status, _ = _process_status(pid)
            if status != "running":
                break
            time.sleep(0.05)

    _ACTIVE_PROCESSES.pop(pid, None)

    tail_text = ""
    if log_path:
        tail_text = "\n--- last 50 lines ---\n" + _read_log_tail(log_path, 50)
    return f"Killed PID {pid} (pgid {pgid}).{tail_text}"


# ── 2. File Operations ───────────────────────────────────────────────────────


def read_file(
    file_path: str,
    *,
    workspace_dir: str = ".",
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read file contents, optionally a line range (1-indexed, inclusive)."""
    full_path = file_path if os.path.isabs(file_path) else os.path.join(workspace_dir, file_path)

    if not os.path.isfile(full_path):
        return f"[ERROR: File not found: {file_path}]"

    try:
        with open(full_path, encoding="utf-8") as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        return f"[ERROR: File is not valid UTF-8: {file_path}]"
    except Exception as e:
        return f"[ERROR: Cannot read file: {e}]"

    if len(lines) > MAX_FILE_LINES and start_line is None:
        return (
            f"[ERROR: File has {len(lines)} lines (limit: {MAX_FILE_LINES}). "
            "Use start_line/end_line or run_bash_with_truncation with head/tail.]"
        )

    if start_line is not None or end_line is not None:
        start = (start_line - 1) if start_line else 0
        end = end_line if end_line else len(lines)
        lines = lines[start:end]

    return "".join(lines)


def write_file(
    file_path: str,
    content: str,
    *,
    workspace_dir: str = ".",
) -> str:
    """Create or overwrite a file with the given content."""
    full_path = file_path if os.path.isabs(file_path) else os.path.join(workspace_dir, file_path)
    parent = os.path.dirname(full_path)

    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return f"[ERROR: Cannot write file: {e}]"

    return f"File written: {file_path} ({len(content)} chars)"


def edit_file_chunk(
    file_path: str,
    search_string: str,
    replace_string: str,
    *,
    workspace_dir: str = ".",
) -> str:
    """Surgical find-and-replace. search_string must match exactly once."""
    full_path = file_path if os.path.isabs(file_path) else os.path.join(workspace_dir, file_path)

    if not os.path.isfile(full_path):
        return f"[ERROR: File not found: {file_path}]"

    try:
        with open(full_path, encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"[ERROR: Cannot read file: {e}]"

    count = content.count(search_string)

    if count == 0:
        return (
            f"[ERROR: search_string not found in {file_path}. "
            "Check leading whitespace and exact content.]"
        )
    if count > 1:
        return (
            f"[ERROR: search_string found {count} times in {file_path}. "
            "Provide a larger, more unique search_string.]"
        )

    new_content = content.replace(search_string, replace_string, 1)

    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        return f"[ERROR: Cannot write file: {e}]"

    return f"Edit applied to {file_path}"


# ── 3. Micro-Memory Management ──────────────────────────────────────────────

_VALID_ACTIONS = frozenset({"push", "pop", "complete", "update", "list"})


def dynamic_task_manager(
    action: str,
    micro_tasks: list[dict],
    task_id: str | None = None,
    description: str | None = None,
) -> tuple[str, list[dict]]:
    """Manage the ephemeral micro-task queue. Returns (result_text, updated_tasks)."""
    if action not in _VALID_ACTIONS:
        return (
            f"[ERROR: Invalid action '{action}'. Must be one of: {sorted(_VALID_ACTIONS)}]",
            micro_tasks,
        )

    tasks = [dict(t) for t in micro_tasks]  # shallow copy each dict

    if action == "push":
        if not task_id or not description:
            return ("[ERROR: 'push' requires both task_id and description]", tasks)
        if any(t["task_id"] == task_id for t in tasks):
            return (f"[ERROR: task_id '{task_id}' already exists]", tasks)
        tasks.append(
            {"task_id": task_id, "description": description, "status": "pending"}
        )
        return (f"Task '{task_id}' added.", tasks)

    if action == "pop":
        if not tasks:
            return ("[INFO: Task queue is empty]", tasks)
        removed = tasks.pop(0)
        return (f"Popped task: {removed['task_id']} — {removed['description']}", tasks)

    if action == "complete":
        if not task_id:
            return ("[ERROR: 'complete' requires task_id]", tasks)
        for t in tasks:
            if t["task_id"] == task_id:
                t["status"] = "completed"
                return (f"Task '{task_id}' marked as completed.", tasks)
        return (f"[ERROR: task_id '{task_id}' not found]", tasks)

    if action == "update":
        if not task_id:
            return ("[ERROR: 'update' requires task_id]", tasks)
        for t in tasks:
            if t["task_id"] == task_id:
                if description:
                    t["description"] = description
                return (f"Task '{task_id}' updated.", tasks)
        return (f"[ERROR: task_id '{task_id}' not found]", tasks)

    # action == "list"
    if not tasks:
        return ("[INFO: Task queue is empty]", tasks)
    lines = [f"  [{t['status']}] {t['task_id']}: {t['description']}" for t in tasks]
    return ("Current tasks:\n" + "\n".join(lines), tasks)


# ── Anthropic Tool Schemas ───────────────────────────────────────────────────

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "run_bash_with_truncation",
        "description": (
            "Execute a shell command. Output over 8000 chars is truncated "
            "to the first and last 2000 chars (stack traces at the end are "
            "preserved). Use 'uv run python script.py' for Python scripts. "
            "Returns combined stdout/stderr."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Maximum execution time in seconds. Default is 300 (5 min) — override explicitly for long training runs.",
                    "default": 300,
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "bash_async",
        "description": (
            "Launch a shell command in a new process group; returns immediately "
            "with the PID. Use for any command expected to run >60s (training, "
            "hyperparameter searches, long preprocessing). stdout+stderr go to "
            "log_path inside the workspace. log_path must be unique — pick "
            "logs/<descriptive>.log. Always pair with wait_and_tail; terminate "
            "with kill_process before this node yields."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute in the background.",
                },
                "log_path": {
                    "type": "string",
                    "description": (
                        "Workspace-relative path for stdout+stderr. Must not "
                        "already exist (non-empty). Convention: logs/train_*.log, "
                        "logs/search_*.log, etc."
                    ),
                },
            },
            "required": ["command", "log_path"],
        },
    },
    {
        "name": "wait_and_tail",
        "description": (
            "Block up to max_wait_seconds OR until the process exits, whichever "
            "first. Returns status (running/exited/dead), exit_code if exited, "
            "runtime, and last N lines of the log. NOTE: max_wait_seconds is a "
            "CAP not a kill — exceeding it leaves the process running. After "
            "review, decide: kill_process, wait_and_tail again, or move on. "
            "Hard-capped at 180s; values above are clamped."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pid": {
                    "type": "integer",
                    "description": "PID returned by bash_async.",
                },
                "log_path": {
                    "type": "string",
                    "description": "Same log_path passed to bash_async.",
                },
                "max_wait_seconds": {
                    "type": "integer",
                    "description": (
                        "Maximum wait before returning even if process still "
                        "running. Cap is 180s. Pick small (30-120s) for early "
                        "calibration, larger once trends are clear."
                    ),
                },
                "tail_lines": {
                    "type": "integer",
                    "description": "Number of trailing log lines to return (default 200).",
                    "default": 200,
                },
            },
            "required": ["pid", "log_path", "max_wait_seconds"],
        },
    },
    {
        "name": "kill_process",
        "description": (
            "Terminate a bash_async process group. SIGTERM first, SIGKILL after "
            "5s if still alive. Use when wait_and_tail shows divergence (NaN "
            "loss, no progress, wrong direction, immediate exception). Returns "
            "the final 50 lines of the log so you see what was happening at "
            "termination."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pid": {
                    "type": "integer",
                    "description": "PID returned by bash_async.",
                },
            },
            "required": ["pid"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a file's contents. Use for code and tracker files. "
            "Do not use on raw data files (.csv, .parquet)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative path to the file.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Line number to begin reading (1-indexed).",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Line number to stop reading (inclusive).",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Create a new file or overwrite an existing file entirely. "
            "Prefer edit_file_chunk for modifications to existing files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative path to the file.",
                },
                "content": {
                    "type": "string",
                    "description": "Complete file content to write.",
                },
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "edit_file_chunk",
        "description": (
            "Surgical find-and-replace in an existing file. "
            "search_string must match exactly once. "
            "Preferred over write_file for modifying existing code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative path to the file.",
                },
                "search_string": {
                    "type": "string",
                    "description": "Exact text block currently in the file to replace.",
                },
                "replace_string": {
                    "type": "string",
                    "description": "New text to insert in place of search_string.",
                },
            },
            "required": ["file_path", "search_string", "replace_string"],
        },
    },
    {
        "name": "dynamic_task_manager",
        "description": (
            "Manage an ephemeral micro-task queue for complex multi-step work. "
            "Tasks are wiped on phase transitions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["push", "pop", "complete", "update", "list"],
                    "description": "The operation to perform.",
                },
                "task_id": {
                    "type": "string",
                    "description": "Unique identifier for the task (required for push/complete/update).",
                },
                "description": {
                    "type": "string",
                    "description": "Task description (required for push, optional for update).",
                },
            },
            "required": ["action"],
        },
    },
]
