"""Universal_ToolNode — non-LLM LangGraph node that executes tool calls.

Reads the last AI message from state, extracts tool_use content blocks,
dispatches to the corresponding tool function, and returns tool_result
messages back into the calling node's message history.

See spec_state.md → Node 0 for the authoritative definition.
"""

from __future__ import annotations

from src.state import AgentState
from src.tools import (
    bash_async,
    dynamic_task_manager,
    edit_file_chunk,
    kill_process,
    read_file,
    run_bash_with_truncation,
    wait_and_tail,
    write_file,
)


def universal_tool_node(state: AgentState) -> dict:
    """Execute all tool_use blocks in the last AI message.

    Returns a state update with:
    - messages: full list with appended tool_result message
    - micro_tasks: updated list (only if dynamic_task_manager was called)
    """
    messages = state["messages"]
    workspace_dir = state.get("workspace_dir", ".")
    micro_tasks = state.get("micro_tasks", [])

    last_message = messages[-1]
    assert last_message["role"] == "assistant", (
        "Universal_ToolNode expects the last message to be an assistant message"
    )

    tool_results = []
    updated_micro_tasks = micro_tasks
    tasks_changed = False

    for block in last_message["content"]:
        if block["type"] != "tool_use":
            continue

        name = block["name"]
        inp = block["input"]
        tool_use_id = block["id"]

        result_text = _dispatch(name, inp, workspace_dir, updated_micro_tasks)

        # dynamic_task_manager returns (text, updated_list)
        if name == "dynamic_task_manager" and isinstance(result_text, tuple):
            result_text, updated_micro_tasks = result_text
            tasks_changed = True

        tool_results.append(
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": result_text}
        )

    tool_result_message = {"role": "user", "content": tool_results}
    state_update: dict = {"messages": messages + [tool_result_message]}

    if tasks_changed:
        state_update["micro_tasks"] = updated_micro_tasks

    return state_update


def _dispatch(
    name: str,
    inp: dict,
    workspace_dir: str,
    micro_tasks: list[dict],
) -> str | tuple[str, list[dict]]:
    """Route a tool call to its implementation."""
    if name == "run_bash_with_truncation":
        return run_bash_with_truncation(
            command=inp["command"],
            timeout_seconds=inp.get("timeout_seconds", 300),
            workspace_dir=workspace_dir,
        )

    if name == "bash_async":
        return bash_async(
            command=inp["command"],
            log_path=inp["log_path"],
            workspace_dir=workspace_dir,
        )

    if name == "wait_and_tail":
        return wait_and_tail(
            pid=int(inp["pid"]),
            log_path=inp["log_path"],
            max_wait_seconds=int(inp["max_wait_seconds"]),
            tail_lines=int(inp.get("tail_lines", 200)),
            workspace_dir=workspace_dir,
        )

    if name == "kill_process":
        return kill_process(pid=int(inp["pid"]))

    if name == "read_file":
        return read_file(
            file_path=inp["file_path"],
            workspace_dir=workspace_dir,
            start_line=inp.get("start_line"),
            end_line=inp.get("end_line"),
        )

    if name == "write_file":
        return write_file(
            file_path=inp["file_path"],
            content=inp["content"],
            workspace_dir=workspace_dir,
        )

    if name == "edit_file_chunk":
        return edit_file_chunk(
            file_path=inp["file_path"],
            search_string=inp["search_string"],
            replace_string=inp["replace_string"],
            workspace_dir=workspace_dir,
        )

    if name == "dynamic_task_manager":
        return dynamic_task_manager(
            action=inp["action"],
            micro_tasks=micro_tasks,
            task_id=inp.get("task_id"),
            description=inp.get("description"),
        )

    return f"[ERROR: Unknown tool '{name}']"


def dispatch_tool_calls(
    assistant_msg: dict,
    workspace_dir: str,
    micro_tasks: list[dict],
) -> tuple[dict, list[dict]]:
    """Execute tool_use blocks from an assistant message dict.

    Lighter-weight entry point used by the internal ReAct loop
    in Action Nodes. Reuses _dispatch() for actual tool execution.

    Returns:
        (tool_result_message, updated_micro_tasks) tuple.
    """
    tool_results: list[dict] = []
    updated_tasks = micro_tasks

    for block in assistant_msg["content"]:
        if block["type"] != "tool_use":
            continue

        name = block["name"]
        inp = block["input"]
        tool_use_id = block["id"]

        result = _dispatch(name, inp, workspace_dir, updated_tasks)

        if name == "dynamic_task_manager" and isinstance(result, tuple):
            result_text, updated_tasks = result
        else:
            result_text = result

        tool_results.append(
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": result_text}
        )

    return {"role": "user", "content": tool_results}, updated_tasks
