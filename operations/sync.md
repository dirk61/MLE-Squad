# /sync — drift detection across mle_agent's artifact axes

> Periodic sweep to surface drift across mle_agent's artifact surface — code behavior diverging from prompt claims, decisions.md falling out of sync with the code it documents, deployment configs disagreeing with each other, README claims going stale, terminology drifting across files, recent-change cascades not yet propagated. Output is a report; D8 propose-don't-commit applies.

This op is a **thin override of the wiki's [root /lint operation](../../../../operations/lint.md)** — same structural shape, same approval flow, same finding-marker conventions. The root spec is the authoritative reference for shared mechanics; this file names only what differs.

- **What's inherited verbatim** — finding format (3-line: title + reasoning + marker), three markers (`Proposed:` / `Watch:` / `Flag:`), output skeleton, propose-don't-commit approval flow per [D8](../../../../decisions.md#D8), focus-hint behavior (empty → baseline; present → prioritize but still baseline-sweep), known-limitations awareness.
- **What's overridden** — the artifact axes walked, the finding categories (drift-detection, not link/orphan/contradiction), the focus-hint vocabulary (artifact scopes + phase modes + recent-change cascades), the absence of a `/graph` preamble, the addition of a 4th `Deferred:` marker for milestone-gated divergences.

## Why mle_agent needs this

mle_agent has 7 artifact axes — `src/`, `prompts/`, `specs/`, `decisions.md`, `CLAUDE.md`, `README.md`, deployment config — all of which can drift independently. Three known intentional divergences already exist (D8 medal_thresholds repurposed for ID detection; D13 iteration budget 10 vs 15; D14 context-window sliding) — proof the surface is wide.

The 2026-05-01 doc-revival turn captured a working norm in `CLAUDE.md` §9: *"specs, prompts, and code can drift apart silently; when you change behavior in one, scan the other two for stale claims."* That rule is the **passive intent**. `/sync` is the **active enforcement** — periodic mechanical scan that turns the rule into actually-discovered findings.

## Scope — what's walked vs not

### Walked

| Path | Notes |
|---|---|
| `CLAUDE.md` | Operational rules; capture-rule framework |
| `README.md` | Public claims — architecture diagrams, leaderboard standings, feature lists |
| `decisions.md` | Canonical post-0→1 record (D-entries + `## Deferred` register) |
| `progress.txt`, `todo.md` | Dev-memory state |
| `Dockerfile`, `pyproject.toml`, `amber-manifest.json5`, `sample.env` | Deployment config |
| `.github/workflows/test-and-publish.yml` | CI |
| `specs/*.md` | **Delta headers + 1-line notes only.** Spec bodies are 0→1 frozen — never propose body edits. Drift in body content routes to delta-header revision. |
| `prompts/nodes/*.md` | Static node prompts (Architect, Router, Data_Engineer, Model_Engineer, Evaluator) |
| `prompts/protocols/*.md` | Wake-Up, Sign-Off ritual snippets |
| `prompts/dynamic/ml_rules_template.md` | Filled at runtime by Architect; checked for template-side claims |
| `src/*.py` | Canonical runtime behavior |

### Not walked

| Path | Reason |
|---|---|
| `.venv/` | Environment |
| `__pycache__/`, `*.pyc`, `.pytest_cache/` | Python build artifacts |
| `.git/` | Git internals |
| `.claude/` | Harness internals (this folder; `.claude/commands/sync.md` is the wrapper, walked indirectly through self-reference) |
| `uv.lock` | Binary-ish; verify drift via `uv sync --locked` test in CI, not by reading file content |
| `tests/` | Test bodies — sync doesn't enforce test-vs-code alignment. Failing tests are a code/test issue, not a sync finding. |
| Workspace runtime artifacts (`/data1/...`, `<workspace_root>/<comp>_<ts>/`) | Don't exist in repo; created at runtime |

### Strict containment

`/sync` does NOT walk the parent umbrella's `subgroups/agentbeats/sources/` (`agentx-agentbeats.md`, `agentbeats-tutorial.md`). Platform context is shared infrastructure across all purple/green pairs; mle_agent's drift is measured against mle_agent's own artifacts only. A `--cross-umbrella` mode (future) could add platform-rule alignment checks, but defer until concrete need.

### Frozen-files asymmetry

When drift is detected involving these files, **propose updating the documenting artifact**, never propose editing the frozen file.

| File | Status (per CLAUDE.md §4) | When drift detected → propose updating |
|---|---|---|
| `src/messenger.py` | DO NOT EDIT | `decisions.md` or `CLAUDE.md` |
| `tests/` | DO NOT REMOVE | a new D-entry or fix the test |
| `.github/workflows/test-and-publish.yml` | edit only for build logic | `decisions.md` |
| `src/medal_thresholds.py` | static lookup; no runtime regeneration | `decisions.md` (D8 covers; new entry if drift) |
| `src/executor.py` | edit only if changing task handling | `CLAUDE.md` §4 (role description) |
| `src/server.py` | edit only for agent card | `CLAUDE.md` §4 |
| `Dockerfile` | edit only for base image / system deps | `decisions.md` |
| `specs/*.md` (bodies) | 0→1 frozen | the delta-header note (top of file) — never spec body |

## Finding categories

For each: what's compared, when it fires, where the fix points.

### Category 1 — Code ↔ Prompts drift

Code behavior diverges from what a prompt claims about behavior, *unintentionally*.

- **Fires when:** prompt makes a behavioral claim (timeout, threshold, budget, mode) that doesn't match what the code enforces, AND the divergence is undocumented.
- **Doesn't fire when:** divergence is documented in `decisions.md` (route to `**Resolved-stale (skip):**` mini-block with reference, e.g., D13).
- **Direction of fix:** propose updating whichever side is stale. Default: update the prompt (code is authoritative for runtime behavior).

### Category 2 — Code ↔ decisions.md drift

A claim in `decisions.md` (D1–D15+) is no longer true of current code.

- **Fires when:** D-entry quotes a specific value, threshold, or behavior that the current code no longer matches.
- **Direction of fix:** **propose updating `decisions.md`** to match code (with a date + commit hash trail). Default proposal direction is decisions.md ← code, since post-0→1 the decisions are the historical record of intent and code is the current truth.
- **Exception:** if the code change was unintentional / a regression, fix code instead. Only Dirk can tell; sync just flags the divergence.

### Category 3 — Specs ↔ delta-header drift

Spec body claims X; delta header at top of `specs/spec.md` (or 1-line note in subordinate spec) hasn't been updated to point at the relevant Dn entry that supersedes X.

- **Fires when:** a new D-entry adds a divergence from a spec, but the spec's delta-header note doesn't reference the new Dn.
- **Direction of fix:** update the spec's delta-header note. **Spec body is 0→1 baseline frozen; never propose body edits.**

### Category 4 — CLAUDE.md ↔ repo drift

Operational claims in `CLAUDE.md` no longer match repo state.

- **Fires when:** §4 file role description says X but file's actual role has shifted; §9 references a file/section that's been moved or renamed; §7 dependency-management rules disagree with what `pyproject.toml` says.
- **Direction of fix:** update `CLAUDE.md`.

### Category 5 — README ↔ code/decisions drift

Public-facing claims in `README.md` go stale.

- **Fires when:** ASCII agent-graph diagram shows old node topology; leaderboard standings table predates a more recent run; feature list claims are no longer true (e.g., "Architect runs on Opus" vs D6).
- **Direction of fix:** update `README.md`. For leaderboard scores: `Watch:` if no newer score is known; `Proposed:` if logs/JSONL traces show a newer score.

### Category 6 — Deployment-config coherence

Cross-file alignment across build/deploy configs.

- **Fires when:** Python version disagrees across `pyproject.toml` (`requires-python`), `Dockerfile` (base image), and `src/nodes.py:_bootstrap_workspace` (`uv init --python` flag) — if the divergence is intentional, it should be captured in D5; if not, finding.
- **Fires when:** port numbers disagree across `Dockerfile` (CMD), `amber-manifest.json5`, and `.github/workflows/test-and-publish.yml` (curl health check).
- **Fires when:** model IDs in `src/llm.py:MODEL_MAP` don't match references in `prompts/nodes/router.md` model-tier list.
- **Fires when:** `amber-manifest.json5` declares env vars (e.g., `ANTHROPIC_API_KEY`) that the code doesn't read, or vice versa.
- **Verification helper:** `uv sync --locked` should succeed without modification — if it doesn't, lock file drift. (Spec says to check; doesn't run the command inside `/sync`. Verification by user post-sweep.)

### Category 7 — Cross-artifact terminology drift

Same concept named differently across artifacts where the difference is unintentional.

- **Fires when:** the same concept appears with inconsistent spelling/casing across artifacts (e.g., "iteration_count" vs "ITERATION_COUNT" vs "iteration budget" — each is fine in its own context, but if one is renamed, others should follow).
- **Doesn't fire when:** form-vs-context (data field name `target_model` vs prose "model tier" — different rendering layers, intentionally distinct).
- **Doesn't fire when:** design-vs-operational asymmetry (a concept that exists in spec but not in CLAUDE.md is fine if CLAUDE.md isn't operationally relevant).

### Category 8 — Recent-change cascade + git-log discovery (meta)

Two sub-cases:

**(a) Recent-change cascade.** When a focus hint names a change (`--recent <topic>` or `--since <git-ref>`), scan all artifacts for stale references to prior state.

- *Example:* `--recent prompt-philosophy-shift` → walk for "binding prescription" or "Architect plans pipeline in detail" — these are pre-D1 framings; if any survive in any artifact, finding.

**(b) Git-log discovery — unlifted decisions.** Walk last 20 commits in `git log` for decision-rationale language (commits with explanatory bodies — "we picked X because…", "removed Y to fix Z"). If the rationale isn't in `decisions.md` or `## Deferred` register, finding: propose lifting to a new D-entry. This is the discovery path for unlifted decisions — implements the drift cross-check rule from CLAUDE.md §9 mechanically.

## Output format

Mirrors root `/lint` skeleton with category replacements + `Deferred:` marker addition.

```
# Sync report — YYYY-MM-DD

Focus: <hints or "full baseline">

## Category 1 — Code ↔ Prompts drift

- **<finding title>** — <file:line or file>
  <one-line reasoning, enough for Dirk to verify without re-reading sources>
  **Proposed:** <concrete action>

## Category 2 — Code ↔ decisions.md drift

- **<finding title>** — <file:line>
  <one-line reasoning>
  **Watch:** <trigger condition>

## ... (categories 3–8 as populated)

**<empty category>:** None.

## Resolved-stale (skip):

- D13 iteration 10 vs 15 — known intentional divergence per decisions.md.

## Summary

Health: <one line — overall assessment>.
Top 1-2: 1. <item>; 2. <item>.
```

### Binding output rules

1. **No file writes during sweep.** D8 propose-don't-commit. Sync produces only a report.
2. **Reasoning on every finding.** One tight line stating *why* it reads as a finding. Enough for Dirk to verify without re-reading sources.
3. **Every finding ends with one marker.**
   - `**Proposed:** <action>` — actionable edit recommended.
   - `**Watch:** <trigger>` — observation; condition under which to escalate.
   - `**Flag:** <note>` — noticed-only; nothing to do but worth being aware.
   - `**Deferred:** revisit when <milestone> (per decisions.md `## Deferred` entry [Fn]).` — milestone-gated; reserved strictly for `## Deferred` register entries. Never invent ad-hoc deferrals in the report.
4. **Resolved-stale mini-block** — when findings match documented intentional divergences, route to `**Resolved-stale (skip):**` mini-block separate from numbered findings, citing the source D-entry.

## Phase modes

Focus-hint argument: `/sync --phase=<mode>`. Default: `active-iteration`.

- **`active-iteration`** *(current, default until 2026-05-03)* — Strict drift detection. Every divergence is a finding; new behavior changes must be captured in `decisions.md` before sync passes clean.
- **`post-deadline-analysis`** *(post-2026-05-03)* — Looser. Drift in active code is allowed under a "lessons learned" frame; sync findings become observations rather than action items. Use when the agent is no longer competing and iteration is in retrospective mode.
- **`frozen`** *(future, if shipping locked)* — Zero tolerance for drift. Any divergence is a bug. Use when mle_agent is treated as a stable artifact (e.g., for a paper / external citation).

User explicitly switches modes via focus hint when ready. Sync does not auto-detect phase.

## Approval flow

D8 — propose, don't commit.

- Sync produces a report. No file writes during the sweep.
- Dirk triages. Agreed edits happen as normal conversation turns with Edit/Write per [D8](../../../../decisions.md#D8).
- Commit sync-driven edits with a `sync:` prefix so `git log --grep='^sync:'` gives a project-history trail.

### Fast-path for explicit deferral

When triage produces "defer this" — either in response to a Category-1-through-7 finding or as a standalone statement during normal work — Dirk's spoken deferral *is* the authoritative trigger to edit `decisions.md` `## Deferred` register immediately in the same turn. Category 8(b) is the fallback discovery path for decisions that *weren't* deferred explicitly.

## Known limitations

- **LLM pattern-matching, not deterministic.** /sync is a Claude-driven sweep, not a static-analysis tool. False negatives (missed drift) and false positives (flagged things that aren't drift) both happen. Treat findings as starting points for triage, not authoritative.
- **No claim-level tracking across sessions.** /sync re-reads files each run; it doesn't remember prior findings. If a finding was triaged-and-dismissed last run, it'll surface again next run unless the underlying state changed.
- **Cross-repo references (parent umbrella, sibling sub-repos) out of scope.** /sync stops at mle_agent's perimeter. Future `--cross-umbrella` mode would address.
- **Phase-mode names are starting guesses.** May iterate as the project's lifecycle becomes clearer post-deadline.
- **Deployment-config drift checks are spec-defined, not executed.** /sync points at things to verify (`uv sync --locked`, port matching) but doesn't run build commands. Verification by user post-sweep.

## Iteration log

History of how this op has evolved. Append entries as the spec is revised.

- **2026-05-01 — initial spec.** 8 finding categories, 7 artifact axes (mle_agent has more than edge_cloud_llm's 4), `Deferred:` marker added (parallel to edge's spec §8 register; lives at `decisions.md` `## Deferred` instead). Phase modes scoped to mle_agent's lifecycle. No `/graph` preamble; no `.paper/` axis (mle_agent has no paper). Frozen-files asymmetry list mirrors CLAUDE.md §4 file-role rules.
