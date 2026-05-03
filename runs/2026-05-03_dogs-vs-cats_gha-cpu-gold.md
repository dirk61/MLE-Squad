# 2026-05-03 — Dogs vs. Cats Redux, GHA CPU — GOLD

**Goal:** First GHA push of the framework after D17–D22 + GHA monitoring tags. Validate that all the time-constrained-env discipline (one-pipeline, single 80/20 holdout, modality-aware CPU strategy) actually steers the agent to a competitive submission inside the GHA 6hr cap on a CPU-only runner.

**Outcome:** **Gold medal. Score 0.02125** vs gold cutoff 0.03882 (lower=better) — submission landed **45% below the gold line**, beating the previous leaderboard top (0.033) by ~36%. Total run: **49.2 min**, well inside the 6hr cap; 5 of 15 router iterations used.

GHA run: <https://github.com/RDI-Foundation/MLE-bench-agentbeats-leaderboard/actions/runs/25289988311> (PR #453)

---

## Setup

- **Image SHA:** `ghcr.io/dirk61/mle-squad@sha256:d877232c8d62b3715b8132dd8da572ca09fb6bf7979f4170c7477d1a01d3b1e1` (built from commit `d193803` — `fix: clear base64 bytes from message FilePart after tar extract (GHA OOM)`)
- **Tier dispatch:** Architect=Opus 4.7, Data_Engineer=Sonnet 4.6, **Model_Engineer=Opus 4.7 (D21 upgrade in effect)**, Evaluator=Haiku 4.5
- **Hardware:** GHA standard runner — no GPU, ~7-8 GB RAM, ~14 GB disk
- **`MLE_AGENT_MAX_ITERATIONS`:** unset → defaulted to 15 (we never came close — only 5 used)
- **Wall-clock cap:** disabled (D19) — no `MLE_AGENT_TIMEOUT` set

## Architect's plan (the load-bearing decision)

> *"CPU-friendly **pretrained-CNN feature extraction → logistic-regression head** pipeline with hflip TTA, single 80/20 stratified holdout, and mandatory probability clipping for log loss safety."*

This was emergent intelligence from Opus Architect — neither D19 ("small pretrained CNN") nor D22 ("one model, one training") explicitly told it to use a *frozen* feature extractor. Opus figured out that fine-tuning a CNN on CPU is intractable in the budget, so it pivoted to a one-pass forward through a frozen pretrained backbone followed by a fast linear head. This is exactly what the leaderboard's prior 0.033 entry probably did.

## What worked

- **OOM fix held.** RSS at `[PHASE] graph_invoked` was 5492 MB on the 7-8 GB runner — tight but stable. The `d193803` base64-clear fix kept the residual at 4 GB instead of 5.5 GB+ (the previous failure point). No exit 137. The Anthropic SDK + LangGraph init pushed to ~5.5 GB and held there without growing.
- **Modality-aware CPU branch (D19) steered to the right model class.** Architect picked CNN feature-extraction, not trees on raw pixels. The pre-D19 prompt would have suggested XGBoost/LightGBM here.
- **D20's single 80/20 holdout was respected.** Architect explicitly wrote it into ml_spec.md; ME built one stratified holdout, not 5-fold CV. Saved ~5× CV compute that wouldn't have fit in the budget.
- **D22's one-pipeline discipline held.** ME made exactly **one** `bash_async` for `train_and_submit.py` (5.9-second runtime — the fast linear-head fit + predict). Zero second-backbone experiments, zero schedule sweeps, zero "let me try TTA variants." Architect's plan executed cleanly.
- **D21 ME-on-Opus 4.7 dispatched correctly.** Router log: `iter_end | iter=3/15 | next=Model_Engineer | tier=opus | phase=model_engineering`. End-to-end wiring confirmed in production.
- **Probability clipping happened automatically.** Architect's metric warning ("mandatory probability clipping for log loss safety") propagated into ME's training script — no `nan ValLL` like in the local-GPU run on Sonnet ME. The D21 Opus upgrade is doing what we hoped: catching the kind of metric-safety bug that Sonnet missed.
- **Self-recovery on script bugs.** DE went through 5 attempts of `build_features.py` (exit 1 → killed → killed → ran without `-u` flag, also killed → finally exit 0 in 19 min). The agent diagnosed each failure via `wait_and_tail`, edited the script, re-launched. Exactly the loop bash_async was designed for.
- **All GHA monitoring tags fired.** `[PHASE]`, `[GHA_MILESTONE]`, `[BG_LAUNCH]`, `[BG_DONE]`, `[BG_KILL]`, `[SUBMISSION_WRITE]`, `[Router] ->` — all visible in the live log. Bumped handoff truncation 300→1500 chars meant the architect's blueprint summary was readable in stdout (above quote came straight from the log line).
- **Total wall-clock: 49.2 min.** Architect 3.4 + DE 44 (across 5 build-features attempts) + ME 0.7 + Eval 0.5 = ~50 min. Well inside GHA's 6hr cap with ~5x headroom.

## What didn't go well

- **DE took 44 min for what should be a 20-min job.** 4 failed `build_features.py` attempts before the 5th worked. Each failure pattern was different (one was exit 1 immediately, one was killed at 6 min, one at 1 min). Sonnet DE wrote a script that needed multiple recovery passes. **An ME-style upgrade to Opus for DE would likely cut this in half** — but DE is also doing simpler work, so the cost/benefit is less clear than for ME. Worth revisiting if multiple competitions show the same pattern.
- **`MLE_AGENT_MAX_ITERATIONS=6` not active.** We added the env var support in D22 but the leaderboard scenario doesn't set it. Default 15 was used. Run only needed 5, so no harm here, but if a future run does loop on something pathological the safety net is looser than intended.
- **One non-actionable mystery: rss=5471 MB at tar_extracted, 5492 MB at graph_invoked, then stable through architect.** The base64-clear fix worked (we got past graph_invoked, which is the previous failure point) but RSS didn't drop as much as predicted (~4 GB target). The framework holds the message somewhere we can't reach. Doesn't matter for this run — it stabilized — but documents what's structurally possible.

## Decisions exercised in this run

All landed before the run via prompt/code edits; details in `decisions.md`:

- **D17** — `bash_async` / `wait_and_tail` / `kill_process` (used heavily by both DE and ME)
- **D19** — Modality-aware CPU strategy (drove Architect to CNN feature extraction over trees)
- **D20** — Single 80/20 holdout for CPU image (Architect adopted explicitly)
- **D21** — ME on Opus 4.7 (visible in router routing, no clipping bug this time)
- **D22** — One-pipeline discipline (ME ran exactly 1 training script, locked in)

Plus the immediate fixes pushed during the GHA debugging session:
- `7220b97` — `amber-manifest.json5` image name fix (was pinned to stale `mle_agent`, now `mle-squad`)
- `d193803` — clear base64 bytes from message FilePart after tar extract (the OOM fix that unblocked this run)

## Open items / follow-ups

- **Submit jigsaw-toxic with same image** — the modality-aware text branch ("small transformer or fastText for text") is untested in production; jigsaw is the natural validation. Previous score 0.981 may improve if the architect picks transformer/embeddings vs the pre-D19 tree-based default.
- **Consider Opus upgrade for Data_Engineer.** This run's DE wasted ~25 min on 4 failed script attempts. ME on Opus didn't have this issue. Cost is small relative to the time saved.
- **Set `MLE_AGENT_MAX_ITERATIONS=6` in the GHA leaderboard scenario** — the env var support is wired but the scenario isn't using it. Belt-and-suspenders for future runs.
- **Investigate why DE's Python script hung for 6 min before being killed** (the second `build_features.py` attempt). Could be a simple bug or a real CPU-bound issue with how features were being built. The agent recovered fine, but this is the kind of thing that cuts margin on harder competitions.

## Reference

- **Live log:** retrievable via `gh run view 25289988311 --repo RDI-Foundation/MLE-bench-agentbeats-leaderboard --log` (only after run completes; GHA holds logs in blob storage during execution)
- **Results artifact:** `gh run download 25289988311 --repo RDI-Foundation/MLE-bench-agentbeats-leaderboard` produces `shard-0/results.json` with the score
- **Iteration timeline (from `[GHA_MILESTONE] iter_end` log lines):**
  - iter=1/15 → Data_Engineer @ 3.4 min
  - iter=2/15 → Data_Engineer @ 26.3 min (rewind after build-features script bugs)
  - iter=3/15 → Model_Engineer (opus) @ 46.9 min
  - iter=4/15 → Evaluator @ 48.5 min
  - iter=5/15 → END @ 49.2 min
- **Final submission:** 33,357 bytes, 2500 rows, `submission_ready` at 49.2 min total
