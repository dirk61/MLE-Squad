"""LangGraph State schema for the MLE Agent.

Defines the TypedDict passed between all graph nodes.
See spec_state.md §3 for the authoritative field definitions.

Messages are stored as Anthropic API dicts ({"role": ..., "content": ...}).
- `messages`: no reducer — nodes return the full replacement list.
  Router wipes by returning []. Action/ToolNode append by returning
  state["messages"] + [new_msg].
- `all_messages`: operator.add reducer — append-only accumulator.
  Router appends current messages before wiping.
"""

import operator
from typing import Annotated

from typing_extensions import TypedDict


class AgentState(TypedDict):
    # Active ReAct loop history. Nodes return full replacement list.
    # Router wipes by returning [].
    messages: list

    # Persistent accumulator — Router appends messages here before wiping.
    # Uses operator.add reducer (append-only, never wiped).
    all_messages: Annotated[list, operator.add]

    # Brief instruction passed from exiting node to the next.
    handoff_message: str

    # Active phase label (e.g. "architecture", "data_engineering").
    current_phase: str

    # Model tier for next Action Node ("opus", "sonnet", "haiku").
    # Dictated by Router_Brain.
    target_model: str

    # Total Router transitions. Incremented by Router on each invocation.
    # Safety circuit breaker — Router routes to END when this exceeds max.
    iteration_count: int

    # Ephemeral micro-task queue for dynamic_task_manager.
    # Wiped on macro-phase transitions to prevent context bleeding.
    micro_tasks: list[dict]

    # Absolute path to competition workspace directory.
    workspace_dir: str

    # Competition identifier (e.g. "spaceship-titanic").
    # Used for workspace dir naming and logging; matched against the static
    # ID set in src/competition_ids.py during graph initialization.
    competition_id: str
