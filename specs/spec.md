# Technical Specification — MLE Agent (`spec.md`)

> **Cold Storage.** Do not read during routine coding. Only read when explicitly cross-referenced by `todo.md`, or when architecting a new phase. See CLAUDE.md §9 for the full protocol.

---

## Current state vs original spec

> This spec is the **0→1 baseline** (Phases 1–6, 2026-04-12). The agent has iterated meaningfully since — see [`../decisions.md`](../decisions.md) for the canonical post-0→1 record. Every spec file in this folder is 0→1 baseline; check `decisions.md` before assuming any specific behavior still holds.

Specific deltas (see `decisions.md` for full reasoning):

- API key: `ANTHROPIC_API_KEY`, not `CLAUDE_API_KEY` as below. — [D15]
- Architect rewinds use Sonnet, not Opus. Opus is first-entry only. — [D6]
- Default bash timeout is `300s`, not `120s` as in spec_tool.md. — [D3]
- Wall-clock global cap of 4hr (`GRAPH_WALL_CLOCK_TIMEOUT=14400`, env-overridable). — [D3]
- ML spec at runtime is **context and direction**, not binding prescription. — [D1]
- Workspace bootstrap pins `--python 3.12`, strips `VIRTUAL_ENV`/`CONDA_PREFIX`, symlinks prompts/, writes `.gitignore`. — [D5]
- Auto-commit happens automatically at every Action Node exit. — [D7]
- Iteration budget: two-tier (10 = Router redirect to Evaluator; 15 = graph END). — [D13]
- Context-window sliding: first message + last 20 exchange pairs. — [D14]
- Medal targets removed from prompts; static lookup retained for competition ID detection only. — [D8]
- Evaluator restricted to 2 blocker types (`SubmissionFail`, `MetricFloor`). — [D9]
- Submission-before-optimization rule mandatory. — [D11]
- Logging hierarchy: selective bash_history filter, JSONL trace per round, `/data1` server log. — [D12]
- A2A: 512MB max content, sample_submission fallback, partial-output capture. — [D10]
- Architect HARD STOPs: no `.py` files, no training cmds, no commands >60s. — [D2]
- CV-as-primary-signal + plateau detection at <0.3% relative delta over 2 runs. — [D4]
- LLM tier: opus is `claude-opus-4-7` (not `4-6` as in spec_LLM.md); prompt caching, adaptive thinking, and `effort` levels all enabled. — [D16]
- Tool surface adds `bash_async`/`wait_and_tail`/`kill_process` for any command >60s; sync `run_bash_with_truncation` is forbidden for training. Process state lives in a module-global registry, swept on every node exit. — [D17]

---

## System Overview

The `mle_agent` is an autonomous ML engineering agent. It receives a competition problem and dataset from the Green Agent via A2A, runs a multi-node LangGraph to build an ML pipeline, and returns a `submission.csv`.

Three design principles drive every decision:
- **Context preservation over raw capability** — nodes forget; memory files and commit history don't.
- **Tiered intelligence** — Opus for strategy, Sonnet for execution, Haiku for routing.
- **Fail-forward discipline** — blockers are typed so the Router can route without interpretation.

---

## Architecture Sketch

```
Green Agent ──▶ System_Architect ──▶ Router_Brain ──┬──▶ Data_Engineer ──┐
                                          ▲          ├──▶ Model_Engineer  │
                                          └──────────┴──▶ Evaluator ──────┤
                                                                          │
                              Universal_ToolNode ◀── all Action Nodes ◀──┘

Shared file layer: ml_rules.md · ml_spec.md · ml_todo.md · ml_progress.txt
Runtime state:     LangGraph State { messages · all_messages · handoff_message · current_phase · target_model · iteration_count }
```

---

## Major Components

### Nodes (LangGraph workers)
Five nodes. Three tiers.

| Node | Model | Role |
|---|---|---|
| `System_Architect` | Opus | Blueprints the ML pipeline; writes all macro-memory files |
| `Router_Brain` | Haiku | Wipes context, reads signals, dispatches next node + model tier |
| `Data_Engineer` | Sonnet | EDA, feature engineering, produces clean arrays on disk |
| `Model_Engineer` | Sonnet (Opus on rewind) | Training, inference, metric logging |
| `Evaluator` | Sonnet | Independent QA — format, leakage, validation score; always routes to Router |
| `Universal_ToolNode` | — | Non-LLM executor; returns results back to calling node |

→ Full node definitions, edge rules, and dry-run trace: **`spec_state.md`**

### LLM Dispatch
Router sets `target_model` in State; nodes never self-select. Credentials via `CLAUDE_API_KEY` in `sample.env`.

→ Model IDs and tier rationale: **`spec_LLM.md`**

### Tool Layer
All tools hosted by `Universal_ToolNode`. Action Nodes request calls; results are appended back to `messages`.

| Tool | Purpose |
|---|---|
| `run_bash_with_truncation` | Shell, Python, Git — with timeout + output cap |
| `read_file` | Line-range reads; forbidden on raw data files |
| `write_file` | New files or full config overwrites only |
| `edit_file_chunk` | Surgical find-replace — mandatory for modifying existing pipelines |
| `dynamic_task_manager` | Ephemeral in-State micro-task queue; wiped on every Router handoff |

→ Parameters, failure modes, and usage constraints: **`spec_tool.md`**

### Memory
Two layers working together:

**Macro (files):** `ml_rules.md` loads every loop; `ml_todo.md` and `ml_progress.txt` load on Wake-Up; `ml_spec.md` is cold — only read on explicit cross-reference.

**Micro (State):** `dynamic_task_manager` queue tracks within-loop sub-steps; wiped on phase transition.

**Protocols:** Wake-Up (read trackers → read git) and Sign-Off (mark done → overwrite progress → commit → emit handoff) are enforced on every Action Node entry and exit.

→ Full memory architecture, workspace isolation, and operating rules: **`spec_memory.md`**. Protocol step sequences: **`prompts/protocols/`**.

### Prompting
Prompts assembled at runtime as `static_base + ml_rules_content`. Layer 1 (static, in `prompts/nodes/`) defines node character. Layer 2 (dynamic, from `ml_rules.md`) encodes the current competition.

Router input is a structured harness-assembled block; output is exactly one JSON: `{ next_node, target_model, rewind_reason }`. Blockers in `ml_progress.txt` use a typed schema (`[BLOCKER] TYPE: ...`) so Haiku can route without interpretation.

→ Prompting contracts, Router interface, blocker vocabulary, and template locations: **`spec_prompting.md`**

---

## Key Invariants

1. Router appends `messages` to `all_messages` before wiping — the full trace is always recoverable for post-run LLM-as-a-judge evaluation.
2. `ml_spec.md` is cold — a `ml_todo.md` cross-reference is the only read unlock.
3. `edit_file_chunk` for existing pipelines — never overwrite established scripts with `write_file`.
4. Blockers are typed — free-text fails under Haiku.
5. Commit on every Sign-Off — recovery always starts from a stable state.
6. Each competition runs in an isolated workspace — see `spec_memory.md` §0.
