# CLAUDE.md — MLE Agent Development Guide

## 1. Competition Overview
This is a **purple agent** on the AgentBeats MLE-Bench leaderboard. Agents solve ML problems autonomously. The green agent (`mle-bench-green` at `/home/six004/agentbeats/mle-bench-green/`) orchestrates each assessment: it sends competition data, receives the submission, and scores it.

## 2. Green Agent Interaction Protocol
The A2A communication protocol is already implemented in `src/agent.py`. Refer to that file for exact message formats and implementation details.

**The Assessment Loop:**
* **Receive:** The Green Agent provides task instructions and a dataset archive (`competition.tar.gz`).
* **Validate (Debug):** Before finalizing, you can verify your output format by sending a `status_update` message containing the text `"validate"` and your `submission.csv`. This can print the validation result to stdout.
* **Submit:** Call `updater.add_artifact(...)` with `submission.csv`. The Green Agent will score the submission and return a JSON artifact containing your metrics.

## 3. Ethics
Adhere to standard open-source and dataset licensing.

## 4. Repository Architecture
**Root:** `/home/six004/agentbeats/mle_agent/`
Do not modify files outside this root. Update this section if the structure changes.

* `src/agent.py`: MAIN LOGIC — edit freely; extend with new files/dirs as needed.
* `src/state.py`: LangGraph AgentState TypedDict — edit when adding state fields.
* `src/llm.py`: Anthropic API wrapper with tiered model dispatch — edit to change model config.
* `src/tools.py`: Tool implementations + Anthropic tool schemas — edit to add/modify tools.
* `src/tool_node.py`: Universal_ToolNode (tool call dispatcher) — edit to change dispatch logic.
* `src/competition_ids.py`: Static set of 82 known MLE-bench competition IDs. Used by `src/agent.py` to identify which competition is being run from the tar archive. Originally a medal-threshold lookup; D8 removed runtime threshold use, D24 stripped the score columns and renamed.
* `src/nodes.py`: LangGraph node implementations — Action Node wrapper (ReAct loop), System_Architect, Router_Brain.
* `src/graph.py`: LangGraph StateGraph construction — registers nodes, wires edges, compiles the graph.
* `src/prompts.py`: Prompt loader + assembly (system prompts and Router input blocks).
* `src/executor.py`: Task lifecycle — edit ONLY if changing task handling.
* `src/server.py`: Agent metadata — edit ONLY to update agent card.
* `src/messenger.py`: A2A messaging utility — DO NOT EDIT.
* `tests/`: A2A conformance tests — DO NOT REMOVE.
* `.github/workflows/test-and-publish.yml`: CI — edit ONLY to change build logic.
* `Dockerfile`: Edit ONLY for base image or system deps.
* `pyproject.toml` / `uv.lock`: See Section 7 for strict dependency rules.
* `amber-manifest.json5`: Edit ONLY for image tag or env changes.
* `specs/`: Design specifications. Read each spec **once** when implementing its module, then treat as cold storage (see §9 READ LIMITS).
  * `spec.md`: Master overview and key invariants. Read first for the big picture.
  * `spec_memory.md`: Workspace isolation, macro/micro-memory, operating rules. Read when implementing workspace bootstrap and memory management.
  * `spec_state.md`: LangGraph node definitions, State schema, edge rules. Read when implementing the state graph and node logic.
  * `spec_tool.md`: Tool definitions and usage constraints. Read when implementing Universal_ToolNode.
  * `spec_LLM.md`: Model tier assignments. Read when implementing LLM dispatch.
  * `spec_prompting.md`: Prompting architecture, node contracts, Router interface, **prompt assembly formula**. Read when implementing prompt loading and node initialization.
* `prompts/`: Pre-written prompt bases — do not edit during a competition run.
  * `nodes/`: Static system prompt base for each node (`architect`, `router`, `data_engineer`, `model_engineer`, `evaluator`).
  * `protocols/`: Wake-Up and Sign-Off ritual snippets (embedded verbatim into Action Node prompts at runtime).
  * `dynamic/ml_rules_template.md`: Fillable template for competition-specific `ml_rules.md`.

**Competition Workspaces (Runtime):** The mle_agent creates an isolated workspace directory for each competition run — with its own `git init`, memory files, code, and data. This workspace is completely separate from this dev repository. See `specs/spec_memory.md` §0 for the bootstrap sequence and path convention.

## 5. Local Testing
Local testing = full end-to-end assessment, not unit testing. For quick function-level checks, use plain Python scripts.

```bash
# Run full assessment with logs (both agents auto-started)
cd /home/six004/agentbeats/agentbeats-tutorial
uv run agentbeats-run scenario.toml --show-logs
```

**[MANDATORY VERIFICATION] - Toy Data Testing:**
After finishing or editing any new phase, function, or submodule, you **MUST** write and execute a temporary Python script using minimal dummy data. You must verify dimensional correctness, data types, and logic *before* moving on.

## 6. Local Storage (Strict Limit)
System disk (`/`) has ~13 GB free. Check `df -h /` before any large download.
**RULE:** Large files (datasets, models, caches) must be written to `/data1/six004/`. Never write large downloads directly under `/home/six004/`.

**Execution Pattern:**
1. `mv /home/six004/<name> /data1/six004/<name>`
2. `ln -s /data1/six004/<name> /home/six004/<name>`

## 7. Dependency Management (Strict uv Conformance)

The build environment strictly relies on `uv`. All dependencies must be resolvable via `pyproject.toml` and `uv.lock`, or the Docker build will fail.

* **Standard Flow:** Prefer `uv add <package>` to automatically update configuration files. 
* **Edge-Case Installations:** If a specific package requires `uv pip install` or `pip install` to resolve correctly, you are permitted to use them. However, you **must** immediately manually add that package to `pyproject.toml` and run `uv lock` to synchronize the environment.
* **Pre-Commit Verification:** Before completing any task that alters dependencies, you must ensure `uv sync --locked` executes successfully. Never edit `uv.lock` manually.


## 8. Version Control

**Remote:** `https://github.com/dirk61/mle_agent` — pushing to `main` triggers CI and publishes `ghcr.io/dirk61/mle_agent:latest`.

- Commit locally after each completed, tested sub-module or feature, or made a major change or fixed a major bug.
- Stage all relevant files 
- Never auto-push — user decides when to push
- Write descriptive commit messages (what and why)

## 9. Shift Handover Memory Protocol
Your context window might reset between sessions. You MUST follow this protocol to maintain continuity.

> **Two memory layers exist — do not confuse them.** The Dev Memory below is for YOU (Claude Code the developer). The Agent Memory is for the mle_agent you are building — it manages its own parallel system at runtime.

### Dev Memory (YOUR files as Claude Code)
These files track YOUR development work on building the mle_agent codebase:
1. `CLAUDE.md`: Permanent rules and constraints (this file).
2. `progress.txt`: Your immediate dev state (Objective, Blockers, Next Steps).
3. `todo.md`: Your development task checklist with cross-references to specs.
4. `specs/spec.md`: Technical blueprint (Cold Storage — read on demand).

### Agent Memory (the mle_agent's runtime files)
The mle_agent you are building has a **parallel memory system** for competition runs. These files do NOT exist in this repo — the agent creates them at runtime inside an isolated competition workspace:
- `ml_rules.md`: Competition-specific system prompt (loaded every loop)
- `ml_spec.md`: ML pipeline blueprint (Cold Storage)
- `ml_todo.md`: Agent's task checklist with blueprint cross-references
- `ml_progress.txt`: Agent's shift handover scratchpad

The agent memory mirrors the dev memory by design (Recursive Agentic Memory). See `specs/spec_memory.md` for the full agent memory specification, workspace isolation, and operating rules.

### [WAKE-UP] — Dev Layer (execute immediately on new prompt)
* Read `progress.txt` and `todo.md`.
* Run `git status` and `git log -n 5`.
* Note: the mle_agent has its own Wake-Up protocol — see `prompts/protocols/wake_up.md`.

### [READ LIMITS & UPDATES] — Specs are Cold Storage after initial implementation
Spec files follow a two-phase discipline:

**During initial implementation** — you ARE building the system from specs. Read each spec file **once** when implementing its corresponding module. Your `todo.md` tasks should cross-reference the specific spec (e.g., `Ref: spec_state.md → Node Definitions`), just like the agent's `ml_todo.md` cross-references `ml_spec.md`.

**After the module is built** — that spec becomes cold storage:
* NEVER re-read spec files for routine coding, debugging, or minor fixes.
* ONLY re-read a specific spec section if explicitly referenced by a `todo.md` item, or when architecting a brand-new module.
* The code you already wrote IS the implementation — read your code, not the spec.

**CASCADE RULE:** If you modify any spec file, you MUST immediately review and update `todo.md` to ensure the task list reflects the change.

### [SIGN-OFF] — Dev Layer (execute before ending your turn)
1. **Mark Done:** Change `[ ]` to `[x]` in `todo.md` for completed work.
2. **State Sync:** Overwrite `progress.txt` strictly using this format:
   * *Current Objective:* [...]
   * *Current State/Blockers:* [Include specific errors/tracebacks if stuck]
   * *Next Steps:* [Exact command or file the next agent should start with]
3. **Commit:** `git commit -m` if a sub-task is complete or stable.
* Note: the mle_agent has its own Sign-Off protocol — see `prompts/protocols/sign_off.md`.

### [ITERATION-MODE CAPTURE RULE] — applies post-0→1

After 0→1 completion (Phases 1–6), the Shift Handover protocol still applies. The rule below is added on top.

**When iteration produces a load-bearing change, capture it in [`decisions.md`](decisions.md) BEFORE the [SIGN-OFF] commit.**

Trigger — fire when the change involves any of:
* A tradeoff resolution ("we picked X over Y because…")
* A philosophy shift (e.g., "spec is context, not prescription")
* A dropped approach (e.g., "removed medal targets — caused loops")
* An architectural choice with non-local consequences
* Behavior added in code that diverges from any spec or prompt
* A named distinction worth a future reader

Don't fire for routine bug fixes, doc tweaks, or trivial refactors.

**The bar:** *would a reader six months from now reading the commit log alone be confused about why this is the way it is?* If yes, capture.

**Format:** new `## Dn` entry in `decisions.md`. Match root vault's pattern (bold title, date, decision, reasoning, to-revisit-if). Cross-reference the commit hash inline. Update [`specs/spec.md`](specs/spec.md) "Current state vs original spec" delta header if the decision invalidates an original-spec claim.

**Drift cross-check rule.** Specs, prompts, and code can drift apart silently in this project. When you change a behavior in one of them, scan the other two for stale claims about the same behavior:
* If a divergence existed and is **intentional** (e.g., D13: prompt says iter ≥10, code says >15 — defense in depth), document it in `decisions.md`.
* If it's **accidental**, fix the inconsistent one in the same commit. Don't leave drift uncaptured.

The cross-check applies in both directions — code changes scan specs+prompts, prompt changes scan specs+code, spec changes scan code+prompts.

**Active enforcement: `/sync` operation.** The cross-check rule above is the *passive intent* — discipline written here so future-Claude reads it. The active enforcement is `/sync`, defined at [`operations/sync.md`](operations/sync.md). Run periodically (or whenever a session is about to wind down) to mechanically scan all 7 artifact axes for drift. D8 propose-don't-commit applies; sync produces a report, Dirk triages, sync-driven edits commit with a `sync:` prefix. The slash command at `.claude/commands/sync.md` is a thin wrapper.

**Deferred register at [`decisions.md`](decisions.md) `## Deferred`.** Milestone-gated divergences (e.g., post-2026-05-03 work) live in the `## Deferred` section of `decisions.md`, with `[Fn]` entries. `/sync` references this register; findings matching an entry get the `**Deferred:**` marker rather than `**Proposed:**`.