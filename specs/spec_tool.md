# Specification: Universal_ToolNode Implementation (`spec_tool.md`)

> **0→1 baseline.** Post-0→1 changes captured in [`../decisions.md`](../decisions.md) — notably **D3** (`run_bash_with_truncation` default timeout is `300s`, not `120s` as below), **D12** (selective `bash_history.log` filter — only logs Python script runs and errors), and **D10** (partial-output capture on timeout, last 2K chars).

This document defines the discrete tools accessible via the `Universal_ToolNode`. This node acts as a secure, sandboxed execution environment strictly for Action Nodes. 

The core philosophy of this toolset is **Context Preservation and Fault Tolerance**. Tools are designed to fail gracefully, truncate runaway outputs, and enforce surgical code edits over full-file rewrites.

---

## 1. Execution Tools

### `run_bash_with_truncation`
* **Tool Description:** The primary workhorse. Executes shell commands, Python scripts, and Git operations securely while protecting the agent's context window from massive terminal dumps.
* **Parameters:**
    * `command` (string): The shell command to execute.
    * `timeout_seconds` (int, default=120): Maximum execution time before force-killing the process. Longer for hard tasks such as model training.
* **Execution Behavior:** Runs in the active competition workspace directory (see `spec_memory.md` §0 for workspace isolation and path conventions) and captures both `stdout` and `stderr`. 
* **Failure & Error Handling:** * If combined output exceeds 8,000 characters, it dynamically truncates by returning the first 2,000 chars, a string `\n...[OUTPUT TRUNCATED]...\n`, and the final 2,000 chars (crucial for stack traces).
    * Returns explicit exit codes. If `exit_code != 0`, prefixes the output with `[ERROR: Command failed]`.
    * Kills any interactive shell attempts (e.g., `vim`, `nano`, bare `python`).
* **Usage Constraints:** Use `uv run python <script.py>` (not bare `python`) to execute scripts inside the workspace's isolated environment. Enforce `-m` on git and other tools to bypass interactive prompts.

---

## 2. File Operations (The I/O Suite)

### `read_file`
* **Tool Description:** Reads the exact contents of a specified file from the workspace into the active context window.
* **Parameters:**
    * `file_path` (string): Relative path to the target file.
    * `start_line` (int, optional): Line number to begin reading.
    * `end_line` (int, optional): Line number to stop reading.
* **Execution Behavior:** Returns the requested lines. Strictly enforces UTF-8 encoding.
* **Failure & Error Handling:** Returns a standard file-not-found error if the path is invalid. If the target is excessively large (e.g., >10,000 lines), it aborts the read and returns a system message instructing the agent to use `run_bash_with_truncation` with `head` instead.
* **Usage Constraints:** Excellent for reviewing trackers (`ml_todo.md`) or code modules. Forbidden on raw data files (`.csv`, `.parquet`).

### `write_file`
* **Tool Description:** Creates a completely new file or entirely overwrites an existing file from scratch.
* **Parameters:**
    * `file_path` (string): Relative path to the file.
    * `content` (string): The complete text to write.
* **Execution Behavior:** Writes `content` directly to `file_path`.
* **Failure & Error Handling:** Returns explicit errors for invalid paths or permission denials.
* **Usage Constraints:** Action Nodes are strictly instructed to use this ONLY for creating brand new files or overwriting configurations if necessary.

### `edit_file_chunk`
* **Tool Description:** Performs a surgical, find-and-replace modification on an existing file to prevent the agent from accidentally wiping out unedited code blocks during large pipeline updates.
* **Parameters:**
    * `file_path` (string): Relative path to the target file.
    * `search_string` (string): The exact, verbatim block of text currently in the file to be replaced.
    * `replace_string` (string): The new code block to insert.
* **Execution Behavior:** Executes a strict text-replacement operation within the target file.
* **Failure & Error Handling:** * Fails if `search_string` is not found exactly. Returns a diff-style hint (e.g., "Error: search_string not found. Check leading whitespace.").
    * Fails if multiple identical matches are found in the same file, requiring the agent to provide a larger, more unique `search_string`.
* **Usage Constraints:** The mandatory tool for modifying established ML pipelines and training loops.

---

## 3. Micro-Memory Management

### `dynamic_task_manager`
* **Tool Description:** An ephemeral, dynamic micro-to-do list used to track complex, multi-step code generation tasks mid-loop without causing constant I/O read/writes to the physical disk.
* **Parameters:**
    * `action` (string): Must be one of `['push', 'pop', 'complete', 'update', 'list']`.
    * `task_id` (string, optional): A unique identifier for the micro-task (e.g., `feat_eng_step1`).
    * `description` (string, optional): The content or goal of the task.
* **Execution Behavior:** Manipulates a lightweight queue array stored in the active LangGraph State based on the selected `action`.
* **Failure & Error Handling:** Returns an error if attempting to `complete` or `update` a `task_id` that does not currently exist in the queue.
* **Usage Constraints:** This state is intentionally volatile. It is wiped clean automatically when transitioning between macro-phases to prevent context bleeding.