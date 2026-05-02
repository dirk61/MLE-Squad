# Decisions

Post-0→1 architectural and design decisions for the MLE Agent. The 0→1 baseline is in [`specs/`](specs/); this file captures what's *changed* since then — the *why* that git log alone can't reconstruct.

Each entry: the decision, the date captured, the reasoning, and what would make us revisit. New entries land here on every load-bearing iteration change — see [`CLAUDE.md`](CLAUDE.md) §9 "Iteration-mode capture rule."

---

## D1
**ML spec is context and direction, not binding prescription**

**Date:** 2026-05-01 (captured retroactively; commits `bcac00e` / `9896e5d` / `8728086`)

**Decision:** When Action Nodes (Data_Engineer, Model_Engineer, Evaluator) read `ml_spec.md` from the runtime workspace, they treat it as *what success looks like*, not *exactly how to get there*. The Architect writes high-level intent; the executing node owns implementation choices.

**Reasoning:**
- Original spec framing was prescriptive — Architect plans the pipeline in detail, executors follow. In practice, this fragments under reality: the executor sees data quirks the Architect couldn't anticipate, and following a stale step-by-step plan produces brittle pipelines.
- Reframing the spec as direction-not-prescription gave the Architect a cleaner job (intent + constraints) and gave executors permission to adapt. The result was less back-and-forth between Architect and Action Nodes.
- The shift is implicit in current prompts (`prompts/nodes/data_engineer.md:34-35`, `prompts/nodes/model_engineer.md:43`). The spec files themselves don't yet acknowledge it.

**To revisit if:** Action Nodes start drifting too far from spec intent (poor Architect-node coordination); or if a regression suggests we need a more prescriptive contract.

---

## D2
**Architect HARD STOPs: no `.py` files, no training commands, no commands >60s**

**Date:** 2026-05-01 (captured retroactively; commits `f2c3def`, `050c5b8`)

**Decision:** The Architect prompt enforces three hard rules: (1) no writing `.py` files, (2) no running training commands or any Python script execution, (3) no bash commands taking >60s. The Architect is strictly a planner; execution belongs to Action Nodes.

**Reasoning:**
- Without these guard rails, the Architect would burn time and tokens on actual implementation — drifting into Model_Engineer's territory. The constraint forces the Architect to stay at planning altitude.
- The 60s cap is the real teeth: it eliminates the temptation to "just probe quickly." Anything substantive needs a different node anyway.
- HARD STOP language (vs. soft guidance) is intentional — Anthropic models will respect explicit boundary words more reliably than nuanced phrasing.

**To revisit if:** the Architect's role expands to include *any* runtime validation; or if the 60s cap blocks legitimate Architect work like quick env checks.

---

## D3
**Time-discipline hierarchy: probe-before-commit + 300s default bash + 4hr global wall-clock**

**Date:** 2026-05-01 (captured retroactively; commits `ef0bcd4`, `1518605`, `955519a`, `4fe40ba`)

**Decision:** Three nested time controls operate together:
1. **Probe-before-commit** (Model_Engineer prompt line 13): always run a short probe (few iterations, small trial count, 1-2 epochs) before any long training run.
2. **Default bash timeout 300s** (`src/tools.py:14`), overridable per-call via `timeout_seconds` argument.
3. **Global wall-clock 4hr cap** (`src/nodes.py` `GRAPH_WALL_CLOCK_TIMEOUT=14400`), env-overridable via `MLE_AGENT_TIMEOUT`. Checked inside every ReAct tool round; on exceedance, current node yields gracefully to Router with a "must finalize" handoff.

**Reasoning:**
- Earlier iterations had `120s` default bash and various wall-clock values (100min, 1hr, 2hr). Both got tightened: 300s is the right default for the typical command (data prep, model train, eval), and 4hr matches the AgentBeats platform's expected envelope.
- The probe-before-commit rule is the most-violated and most-valuable: it catches "training won't converge" / "data shape wrong" within seconds instead of an hour-long run. Worth restating in prompts even after it seems obvious.
- Three levels of granularity (per-command / per-graph / agent-rule) cover different failure modes — single command stalls, graph-level runaway, and naive "just train it longer" instinct.

**To revisit if:** AgentBeats platform changes its time envelope; or competition data sizes shift in a way that makes 300s default consistently wrong.

---

## D4
**CV-as-primary-signal + plateau detection at < 0.3% relative delta**

**Date:** 2026-05-01 (captured retroactively; commits `98179e3`, `4d60135`, `7e5a3fd`)

**Decision:** Model_Engineer uses cross-validation as its primary decision signal (default stratified 5-fold, with explicit exceptions for time-series and group-structured data). Plateau detection: when two consecutive training runs each produce a relative CV delta < 0.3% (`|new_cv - best_cv| / |best_cv|`), generate submission and hand off — stop iterating.

**Reasoning:**
- Single holdout splits are noisy enough to cause false-positive "improvement" claims that don't generalize. CV is the right baseline for an autonomous agent that can't sanity-check itself.
- The 0.3% relative threshold is metric-agnostic by design — works equally for accuracy (0–1), RMSE (small or large), AUC, log-loss. Absolute thresholds would need per-metric tuning.
- Two-consecutive-runs requirement prevents single-flat-iteration false stops.

**To revisit if:** competition metrics show that 0.3% genuinely matters (e.g., tight leaderboards where 0.1% separates medals); or if certain metrics have inherently larger noise floors.

---

## D5
**Workspace isolation discipline: per-run isolated workspace with stripped env + uv pin + prompts symlink**

**Date:** 2026-05-01 (captured retroactively; commits `8993f49`, `00a4cd4`, `610eb3b`, `bd05935`)

**Decision:** Each competition run gets its own isolated workspace at `<WORKSPACE_ROOT>/<comp_id>_<timestamp>/`. Bootstrap sequence (`src/nodes.py:_bootstrap_workspace`):
1. Create `data/raw`, `data/processed`, `src`, `models`, `logs` subdirs.
2. Write `.gitignore` blocking `data/raw/`, `*.pt`, `*.pkl`, `*.jpg`, etc.
3. Symlink the project's `prompts/` into the workspace (so `read_file("prompts/...")` works from inside).
4. `git init` + configure user (`MLE Agent` / `agent@mle-bench.local`).
5. `uv init --python 3.12` — clean env with `VIRTUAL_ENV` and `CONDA_PREFIX` *stripped* from subprocess env.
6. Copy dataset from `staging_path/home/data/` to `workspace/data/raw/`.

Workspace cache lives under `/data1/six004/` (server-specific), with logs at `/data1/six004/tmp/mle_agent.log`.

**Reasoning:**
- Without isolation, runs cross-contaminated: a stale `.venv` from a previous competition, a `pyproject.toml` from the project root, or shell-inherited `CONDA_PREFIX` would silently cause "this works in dev but breaks on the server" failures.
- Python 3.12 specifically: widest CUDA torch wheel coverage (3.13 forced source builds; 3.11 was older). Pin removes the auto-uv-version-detection failure mode.
- Prompts symlink (instead of copy) means edits to project-level prompts take effect without re-bootstrapping a workspace. Trade-off: workspace is no longer fully self-contained, but the convenience outweighs the purity here.
- `/data1` cache is server-specific; the host disk had only 13GB free and would fill on multi-competition days.

**This decision is code-only** — no spec or prompt mentions the bootstrap details. If you need to understand workspace setup behavior, read `_bootstrap_workspace()` directly.

**To revisit if:** running on a host without `/data1` (logs fall back to `/tmp/`, which works but isn't durable); or if Python 3.13 CUDA wheels mature and 3.12 becomes the older choice.

---

## D6
**Token-tier mapping: Architect rewinds use Sonnet, not Opus**

**Date:** 2026-05-01 (captured retroactively; commit `a73ae06`)

**Decision:** Model tier dispatch is:
- **Opus** (`claude-opus-4-6`) — System_Architect *first entry only* (initial blueprint).
- **Sonnet** (`claude-sonnet-4-6`) — All Action Nodes (Data_Engineer, Model_Engineer, Evaluator) AND System_Architect *on rewind* (the spec already exists; refining it doesn't need Opus).
- **Haiku** (`claude-haiku-4-5-20251001`) — Router_Brain (self) AND Evaluator on format-validation-only paths.

Router prompt (`prompts/nodes/router.md:35`) explicitly directs Architect rewinds to Sonnet.

**Reasoning:**
- Original tier mapping was "Architect = Opus universally." But Architect *re-entry* is a different job: the spec already exists, the rewind is fixing one aspect (per the blocker reason). Sonnet handles spec-refinement well at lower cost.
- Evaluator dropped to Haiku for format-validation paths — submission shape check, naive-baseline comparison — where Sonnet's depth is wasted. Token costs across 50+ runs add up.
- Router stays Haiku (cheap, fast routing decisions on a typed schema).

**To revisit if:** Architect rewinds start producing measurably worse plans than Opus would; or if model pricing shifts make the tier savings less compelling.

**Note (stale spec):** `specs/spec_LLM.md` still says "Architect = Opus" universally. See spec.md delta header.

---

## D7
**Auto-commit safety net at every Action Node exit**

**Date:** 2026-05-01 (captured retroactively; commit `06993a7`; refined in `050c5b8`)

**Decision:** At the end of every Action Node's ReAct loop, `_auto_commit()` (`src/nodes.py`) automatically runs `git add` (filtered to code/memory files: `*.py`, `*.md`, `*.txt`, `*.json`, `*.yaml`, `*.toml`, `*.lock`, `*.sh`, `src/`, `logs/`) and `git commit -m "Auto-commit after <node> exit"`. Independent of whether the LLM explicitly ran a Sign-Off `git commit` itself.

**Reasoning:**
- Two-mechanism safety net (defense in depth):
  1. **Prompt-level:** Sign-Off protocol asks the LLM to commit (`prompts/protocols/sign_off.md:36`).
  2. **Code-level:** auto-commit runs unconditionally even if the LLM forgot or crashed mid-Sign-Off.
- The filter (only stage code/memory files, not data or models) prevents accidental commits of large artifacts that would balloon the workspace's git history.
- The previous failure mode was real: agents would crash mid-iteration, lose all generated code, and have to redo work from scratch. The safety net costs ~1 second per node exit and recovers entire runs.

**To revisit if:** the auto-commit produces noisy or unhelpful commits that obscure rather than help recovery (e.g., committing failed-state code); or if a future protocol change makes prompt-level commits sufficient.

---

## D8
**Medal targets removed from agent prompts; static lookup retained for competition ID detection**

**Date:** 2026-05-01 (captured retroactively; commit `3c09666`)

**Decision:** Agent prompts contain *zero* references to medal thresholds, gold/silver/bronze targets, or "aim for X score." The static lookup table at `src/medal_thresholds.py` (82 hardcoded competitions) is retained but used *only* for competition ID detection: `src/agent.py:226-249` matches the tar archive's directory prefix against `MEDAL_THRESHOLDS` keys to identify which competition is being run.

**Reasoning:**
- Medal-targeting in prompts caused "relentless loops" — agents would chase the gold threshold even when their CV indicated diminishing returns or actual overfitting. The model's instinct to keep iterating overwhelmed the plateau-detection rule.
- Removing the targets entirely (vs. softening to "aim for") was load-bearing. Soft framing didn't break the loop; only complete absence did.
- The lookup table stays useful for non-targeting purposes — `competition_id` is needed for workspace naming, log routing, and (potentially) post-run analysis. Discarding it would force re-implementation of the directory-prefix matcher.

**To revisit if:** a future protocol introduces a non-loop-inducing way to use medal info (e.g., displayed in logs but invisible to the agent); or if competition_id detection is moved out of agent.py to a different mechanism.

---

## D9
**Evaluator restricted to 2 blocker types: SubmissionFail + MetricFloor**

**Date:** 2026-05-01 (captured retroactively; commit `2171094`)

**Decision:** Evaluator's prompt (`prompts/nodes/evaluator.md:26-29`) explicitly limits it to two blocker types:
- `[BLOCKER] TYPE: SubmissionFail` — submission.csv missing, wrong columns, wrong row count, ID mismatch.
- `[BLOCKER] TYPE: MetricFloor` — no metrics log exists, or CV worse than naive baseline.

`ShapeError`, `Other`, and any free-text blocker types are explicitly forbidden.

**Reasoning:**
- Router_Brain runs on Haiku and routes by typed blocker schema. Free-text blockers force Haiku to interpret them, which fails unpredictably — Haiku doesn't have the headroom for nuanced reading.
- Evaluator's job is independent QA *of finished work*, not generic error-finding. Limiting it to format-correctness and naive-baseline-comparison keeps it focused on the failure modes most likely to make the submission unusable.
- Other blocker types (ImportError, ShapeError) are *Data_Engineer's* purview when caught upstream. Funneling everything through Evaluator created routing chaos.

**To revisit if:** new failure modes emerge that don't fit either type and need a third blocker class; or if Router gets upgraded to Sonnet and could handle free-text robustly.

---

## D10
**A2A robustness: 512MB max content + sample_submission fallback + partial-output capture**

**Date:** 2026-05-01 (captured retroactively; commits `db9a39d`, `9c5f483`, `85d87de`)

**Decision:** Three robustness layers:
1. **A2A `max_content_length=512MB`** (`src/server.py:88`) — supports tar archives with image/audio data.
2. **Sample-submission fallback** (`src/agent.py`) — if the graph finishes without writing `submission.csv`, agent silently copies `data/raw/sample_submission.csv` to `workspace/submission.csv` so the Green Agent always gets *something* scoreable.
3. **Partial-output capture on bash timeout** (`src/tools.py`) — when a command times out, the last 2K chars of partial output are captured and returned (instead of empty), so the LLM can see what was happening before the hang.

Plus a "validate" mechanism: agent can probe submission format by sending text "validate" + CSV via `update_status` before the final `add_artifact` call.

**Reasoning:**
- Earlier failure mode: agent crashes mid-run, no submission produced, Green Agent times out scoring → wasted assessment slot. Sample fallback guarantees *some* score (even if median); the agent learns something from the run.
- 512MB needed for image-classification competitions where the test set tar runs hundreds of MB. Default A2A limits would silently truncate.
- Partial-output capture on timeout: standard subprocess failure mode loses everything, which is the worst signal for the LLM. Last 2K chars usually contain the actual stack trace or "training started, epoch 1/100..." that diagnoses the issue.

**To revisit if:** A2A limits change (newer protocol versions); or the sample fallback masks real issues we'd want to surface.

---

## D11
**Submission-before-optimization mandatory rule**

**Date:** 2026-05-01 (captured retroactively; commit `ce1541b`)

**Decision:** Model_Engineer prompt (`prompts/nodes/model_engineer.md:11`) requires a valid `submission.csv` to exist *before* any tuning iteration starts. Every subsequent improvement overwrites this file; the baseline is always there.

**Reasoning:**
- Pairs with D10's sample-submission fallback: defense in depth. Even if the LLM doesn't reach a "good" model, the *baseline* submission exists from the moment Model_Engineer first writes one. The agent can't accidentally optimize itself into a no-submission state.
- The instinct of "tune first, generate later" is strong but wrong here — the platform scores whatever's in `submission.csv` at end-of-run. A perfect-but-uncommitted model is worth zero.
- Forces Model_Engineer to think about the prediction shape and submission format *first*, surfacing schema bugs early.

**To revisit if:** the cost of always-writing a baseline becomes non-trivial (e.g., for very large test sets where prediction generation is itself expensive).

---

## D12
**Logging hierarchy: selective bash_history + JSONL trace per round + server-level log**

**Date:** 2026-05-01 (captured retroactively; commits `053ab82`, `bee442d`, `fc80909`)

**Decision:** Three logging layers, each with different scope and retention:
1. **`logs/bash_history.log`** (per-workspace) — appends only Python script runs (`python` in command) and any failure (exit_code != 0). Trivial commands (`ls`, `pwd`, `git status`) skipped to keep the log focused. Output capped at last 3K chars per entry.
2. **`logs/all_messages.jsonl`** (per-workspace) — JSONL trace, one entry per ReAct tool round. Captures node, tool_round, router_iteration, elapsed_min, and (truncated) messages. Used for post-run LLM-as-judge evaluation.
3. **Server-level log at `/data1/six004/tmp/mle_agent.log`** (or `/tmp/` fallback) — `logging.INFO` to stderr + file. Covers graph-level events: node entry/exit, wall-clock checks, iteration budget hits.

**Reasoning:**
- Bash history without filtering becomes noise — every `cd`, every `ls`, every git query — and the actual training-run failures get buried. Selective filtering keeps the log human-scannable.
- JSONL trace is the post-mortem artifact: lets us replay and judge runs offline. JSONL (not JSON) so writes are append-only and partial files are still parseable.
- Server-level log is the operator's view: did the graph start, did it timeout, did it crash. Different audience than the LLM-facing per-workspace logs.

**To revisit if:** trace size becomes problematic (currently ~MB-scale per run); or if a competition-specific failure mode would be caught by capturing trivial commands too.

---

## D13
**Iteration budget — two-tier: 10 (Router redirect) + 15 (graph END)**

**Date:** 2026-05-01 (captured retroactively; commits `462861f`, `35a3d91`; current state `MAX_ITERATIONS=15`)

**Decision:** Two iteration thresholds operate together:
- **`ITERATION_COUNT ≥ 10`** (`prompts/nodes/router.md:49`) — Router prompt forces redirect to Evaluator (or END if Evaluator already complete). Catches premature optimization.
- **`iteration_count > MAX_ITERATIONS=15`** (`src/nodes.py:46`) — code-level absolute END. Catches Router-prompt failures or runaway loops.

**Real budget:** "10 iterations or hard-redirected to Evaluator, then 5 more before forced END."

**Reasoning:**
- Defense in depth — prompt-level catches early at the right semantic moment (time to wrap up); code-level catches absolute (iteration counter doesn't tolerate any failure of prompt adherence).
- The two are *intentionally* different numbers, not drift to fix. 10 = "you should be wrapping up by now, write your submission"; 15 = "regardless of what you think, this run is over."
- Not documented in any spec — implicit only. This entry is the durable record.

**To revisit if:** runs consistently hit the 15-iteration cap before producing a submission (suggests 15 is too low for real competitions); or if the 10-vs-15 gap proves to be drift rather than intentional layering (in which case unify them).

---

## D14
**Context-window sliding (first message + last 20 exchange pairs)**

**Date:** 2026-05-01 (captured retroactively; no specific commit — emerged via iteration)

**Decision:** `_windowed_messages()` in `src/nodes.py` keeps the first message (system context) plus the last 20 exchange pairs in the LLM's view, dropping older messages with a one-line summary placeholder. Applied to every ReAct tool round.

**Reasoning:**
- Without windowing, long-running Action Nodes (Model_Engineer especially, with multiple training iterations) would blow past Sonnet's context window mid-run.
- Keeping the first message preserves the original system prompt and competition context — losing that breaks the agent's understanding of what it's doing.
- 20 pairs (not 10, not 50) was tuned empirically — enough recent context for the LLM to "remember" what just happened, small enough that context doesn't bloat token costs.

**This decision is code-only and unrecorded in commits** — it emerged through iteration and is undocumented in any spec or prompt. Worth noting precisely *because* it's silent: a future change to `MAX_CONTEXT_PAIRS` could degrade behavior with no obvious failure signal.

**To revisit if:** Sonnet's context window grows substantially (currently ~200K tokens; if it goes to 1M+ the windowing might be premature optimization); or if specific competitions need longer-window memory (e.g., multi-stage pipelines where step 30 references step 5).

---

## D15
**API key var: `ANTHROPIC_API_KEY` (specs say `CLAUDE_API_KEY` — stale)**

**Date:** 2026-05-01 (captured retroactively; commit `824e9a0`)

**Decision:** Code uses `ANTHROPIC_API_KEY` — `src/llm.py:_get_client()` calls `anthropic.Anthropic()` with no explicit key argument, relying on the SDK's default behavior of reading `ANTHROPIC_API_KEY` from environment. `sample.env` and `.env` carry this name. Amber manifest declares the same.

**Reasoning:**
- Anthropic SDK convention is `ANTHROPIC_API_KEY`. Original spec used `CLAUDE_API_KEY` (renamed before the SDK convention solidified). Code was migrated; specs were not.
- Standard SDK auto-detection means we don't need explicit key-passing in code, which simplifies key handling and matches Anthropic's own docs.

**To revisit if:** Anthropic SDK changes its env var convention (unlikely); or if we ever need multiple API keys per process (Sonnet vs. Opus billing accounts, etc.).

**Stale spec note:** `specs/spec_LLM.md` still says `CLAUDE_API_KEY` in §2 (Credentials). See `specs/spec.md` delta header.
