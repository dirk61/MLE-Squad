# Memory Architecture Specification (`spec_memory.md`)

> **0→1 baseline.** Post-0→1 changes captured in [`../decisions.md`](../decisions.md) — notably **D5** (workspace bootstrap pins `--python 3.12`, strips `VIRTUAL_ENV`/`CONDA_PREFIX`, symlinks prompts/, writes `.gitignore` at bootstrap, copies dataset from staging — none of which is reflected in §0 below).

> **SSoT** for macro-memory file definitions, workspace isolation, and agent memory operating rules.
> Node definitions → `spec_state.md`. Protocol step sequences → `prompts/protocols/`.

The overarching philosophy is **Recursive Agentic Memory**: the `mle_agent` operates with the same best practices as an autonomous AI developer. It dynamically generates and manages a file-based macro-memory system, supplemented by a tool-based micro-memory system and a persistent message history accumulator.

---

## 0. Competition Workspace Isolation

Each competition run operates in a **self-contained workspace directory**. This is the FIRST action the agent takes upon receiving a competition task — before any EDA, before System_Architect writes any memory files.

### Bootstrap Sequence
1. Create workspace directory: `<workspace_root>/<competition_id>_<timestamp>/` — the timestamp ensures uniqueness when the same competition is received multiple times
2. Run `git init` inside the workspace
3. Run `uv init` inside the workspace — creates an isolated `pyproject.toml` and `.venv`
4. Set the workspace as the working directory for all subsequent tool calls
5. All macro-memory files (`ml_rules.md`, `ml_spec.md`, `ml_todo.md`, `ml_progress.txt`) are created inside this workspace root
6. All code artifacts (scripts, models, processed data) live under this workspace
7. All git operations and `uv` commands operate on this workspace — not on the dev repo

### Path Convention
```
<workspace>/
├── ml_rules.md              # System prompt (Layer 2 dynamic injection)
├── ml_spec.md               # Technical blueprint (Cold Storage)
├── ml_todo.md               # Task checklist with spec cross-references
├── ml_progress.txt          # Shift handover scratchpad
├── submission.csv            # Final submission
├── src/                     # Pipeline scripts
├── data/
│   ├── raw/                 # Unmodified competition data
│   └── processed/           # Clean arrays, splits
├── models/                  # Trained model artifacts
└── logs/                    # Metric logs, evaluation output
```

### Why Isolation Matters
- Prevents cross-competition file pollution
- Gives each run a clean git history for Wake-Up/Sign-Off protocols
- Allows the agent to `git log` without seeing unrelated commits
- Separates the agent's runtime workspace from the Claude Code dev repo entirely
- Makes cleanup trivial (delete the workspace directory)

---

## 1. Macro-Memory (The File-Based Workspace)

Upon starting a new competition, the `mle_agent` autonomously generates and maintains these four files inside the competition workspace:

* **`ml_rules.md`:** The agent's persistent System Prompt, analogous to `CLAUDE.md` for Claude Code. Contains the competition overview, I/O paths, submission format, constraints, ethics & first-principles rules, version control discipline, dependency management, and active phase. Loaded into context on every loop.
* **`ml_spec.md`:** The technical blueprint (Cold Storage). Written after initial EDA to document the chosen ML architecture, pipelines, and models. Only read when explicitly cross-referenced by `ml_todo.md`.
* **`ml_todo.md` (The Submodule Tracker):** The high-level project roadmap with checkboxes. Tasks must include explicit cross-references to the blueprint (e.g., `Ref: ml_spec.md → Section 3.2`). This enables context-efficient lazy loading of architectural instructions.
* **`ml_progress.txt`:** The Shift Handover scratchpad. Overwritten (not appended) at each Sign-Off with: Current Objective, Current State, Blockers (typed), and Next Steps.

---

## 2. Micro-Memory and Runtime State

### Dynamic Task Manager (Ephemeral)
A tool function allowing the agent to `push`, `pop`, `complete`, `update`, and `list` micro-tasks in real-time (e.g., the 5–10 logical steps to write a specific script). Acts as an ephemeral execution scratchpad stored in LangGraph State. **Wiped on every Router transition** to prevent context bleeding between phases.

### Message History Accumulator (`all_messages`) (Persistent)
A list in LangGraph State that accumulates ALL messages from ALL nodes across the entire competition run. Unlike `dynamic_task_manager`, `all_messages` is **never wiped** — it grows monotonically.

**Mechanism:** Router appends the current `messages` array to `all_messages` before wiping `messages`. This is the only write path — no other node touches `all_messages`.

**Purpose:** Enables post-run LLM-as-a-judge evaluation of the complete agent trace, including cross-node reasoning chains, tool call sequences, and error recovery patterns.

→ See `spec_state.md` §3 for the full LangGraph State Schema.

---

## 3. Operating Rules

The `mle_agent` interacts with its macro-memory using these strict rules to prevent context collapse:

* **Wake-Up Protocol:** On every node entry, the agent reads `ml_progress.txt`, then `ml_todo.md`, then runs `git status && git log`. Authoritative step sequence → `prompts/protocols/wake_up.md`.
* **Sign-Off Protocol:** Before yielding to Router, the agent marks `ml_todo.md` done items, overwrites `ml_progress.txt`, commits, and emits a handoff message. Authoritative step sequence → `prompts/protocols/sign_off.md`.
* **Cold Storage Read Limits:** `ml_spec.md` is strictly Cold Storage. The agent MUST NOT read it during routine code generation. It may ONLY read specific sections if explicitly cross-referenced by an active `ml_todo.md` item (e.g., `Ref: ml_spec.md → Section 2.1`), or when architecting a brand-new pipeline phase.
* **The Cascade Rule:** If the agent updates `ml_spec.md`, it MUST immediately review and update `ml_todo.md` to ensure the task list reflects the new blueprint.
