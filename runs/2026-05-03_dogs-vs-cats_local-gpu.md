# 2026-05-03 — Dogs vs. Cats Redux, Local GPU Validation

**Goal:** Validate the new async-bash tool trio (D17), end-to-end on a real MLE-Bench competition, on the lab box's 2× RTX 4090. Pre-GHA-push smoke test.

**Outcome:** Validated. Manually killed before natural completion at 137 min wall-clock — by then the agent had produced a refine-ensemble submission at OOF=0.0273 (well below leaderboard target 0.033) and was deep into a second-backbone exploration. Code stale relative to subsequent prompt edits, so completion would have validated nothing new.

---

## Setup

- **Backbone path used:** `efficientnet_b3.ra2_in1k @ 288px` (later: `convnext_base.fb_in22k_ft_in1k @ 224px` for second-backbone ensemble)
- **Tier dispatch at run-start:** Architect=Opus 4.7, Data_Engineer=Sonnet 4.6, Model_Engineer=Sonnet 4.6, Router=Haiku 4.5
- **Hardware:** 2× RTX 4090 (24 GB each), 120 GB RAM, /data1 mounted (3 TB free)
- **Workspace:** `/data1/six004/tmp/mle_agent_workspaces/dogs-vs-cats-redux-kernels-edition_20260503_101837/`

## What worked

- **A2A payload through after the 2GB cap bump.** Wire payload measured at ~1.4 GB (1076 MB tar × 4/3 base64). The 512 MB cap that was in place before would have been a hard block.
- **All three new tools fired cleanly.** `bash_async` × 4 launches across iterations, `wait_and_tail` × many (typical max_wait=120-180s), `kill_process` × 0 (no run needed killing). Trace inspector confirmed no unpaired async, no sync `run_bash_with_truncation` for training.
- **Self-recovery from a real script bug.** Iter 2's `train_all_folds.py` crashed with `FileNotFoundError` on missing checkpoint mid-training (folds 1-2 had completed). Agent saw `Status: exited(code=1)` from `wait_and_tail`, applied `edit_file_chunk` to fix the resume logic, re-launched only `--folds 3 4`, and continued. Exactly the recovery pattern the new tools enable.
- **GPU utilization with DataParallel.** Iter 3's refine pass and iter 4's ConvNeXt run both used `DataParallel` across both 4090s — agent picked this autonomously. ~95% util sustained on both cards.
- **Resource snapshots gave clean phase visibility.** Every phase boundary logged `rss=...MB | mem_avail=...MB | tmp_free=...MB`; useful even on the lab box for sanity.
- **Scoring.** Best submission.csv hit **0.0273 OOF** (5-fold refine ensemble of `efficientnet_b3`); leaderboard gold target is 0.033 (lower=better). Single-fold val_ll alone was 0.0272 — ensemble added <0.0001 over fold 0.

## What didn't go well

- **Architect's clipping warning didn't propagate into ME's training scripts.** ml_rules.md explicitly warned "all final probabilities must be clipped to [1e-15, 1-1e-15]." Sonnet ME wrote unclipped log-loss formulas anyway — fold 0 epoch 1 returned `nan ValLL`, fold 1 returned `nan/inf` for all 5 epochs. The agent recovered (val_ll for the saved best checkpoint was clipped correctly), but it cost rounds. **D21's ME-on-Opus upgrade should reduce this category of bug.**
- **TTA experiments hurt the score.** Iter 2 tried 4-view TTA (+10.8% regression, OOF 0.0407 vs 0.0371 base) and H-flip TTA (+1.4%, OOF 0.0375). Both were dropped, costing ~30 min. Standard "let's try something" exploration that doesn't pay off on a problem where the model is already very confident.
- **Iteration-boundary re-orientation tax.** Each Router-rewind to ME spent ~7-9 rounds re-reading ml_progress.txt, ls'ing dirs, smoke-testing torch+timm imports. The wake_up.md protocol mandates 4 actions but the agent did more. Worth tightening if it shows up on GHA too — but it's not architecture-level, just prompt discipline.
- **Total wall-clock ballooned.** Architect 3.3 min + DE 5.3 min + ME (3 iterations) ~120 min ≈ 130 min by the time we killed. On GHA CPU this same shape would be 12-37 hours — way over budget. Drove D22 (one-pipeline discipline + env-tunable iter cap).

## Decisions captured during this run

All landed via prompt/code edits; details in `decisions.md`:

- **D17** — `bash_async` / `wait_and_tail` / `kill_process` tool trio + sweep on node exit + 1MB auto-commit cap
- **D18** — `[BLOCKER] TYPE: Unrecoverable` for explicit early-end on hopeless cases
- **D19** — Modality-aware CPU strategy (no trees on images) + remove 4hr wall-clock cap (env-tunable)
- **D20** — CV default lowered 5→3 fold; CPU image/audio prefers single 80/20 holdout
- **D21** — Model_Engineer upgraded to Opus 4.7 (was Sonnet 4.6)
- **D22** — Time-constrained envs: one-pipeline discipline + `MAX_ITERATIONS` env-tunable

Pre-flight infra fixes that also landed:
- Free `tar_bytes` + gc.collect after extraction (OOM fix at agent boot, important for CI)
- `resource_snapshot()` helper + phase markers in `src/agent.py` + `src/nodes.py`
- A2A `max_content_length` 512MB → 2GB
- Stage tar to `/data1` when available (avoids tmpfs `/tmp` on lab box)
- `[GHA_MILESTONE]` / `[BG_LAUNCH]` / `[BG_DONE]` / `[SUBMISSION_WRITE]` grep tags for live-log monitoring on GHA

## Open items going into GHA

- Validate on a CPU-only env that the new prompts steer Architect to a small CNN (efficientnet_b0 / mobilenetv3) and ME to a single 80/20 holdout single-pipeline run, not the 5-fold-then-refine pattern from this lab run.
- Validate Opus 4.7 ME produces fewer script bugs than Sonnet did in this run.
- Watch `[GHA_MILESTONE] iter_end` lines — should not exceed 5-6 iters with `MLE_AGENT_MAX_ITERATIONS=6`.
- Watch for `[BG_LAUNCH]` count: should be 1 (or 2 if recovery) per ME entry, NOT multiple full trainings.

## Reference

- Live log: `/data1/six004/tmp/agentbeats_logs/dogs_vs_cats_run2.log` (preserved, not committed — too large)
- Workspace: `/data1/six004/tmp/mle_agent_workspaces/dogs-vs-cats-redux-kernels-edition_20260503_101837/` (preserved)
- Best submission.csv on disk reflects the 0.0273 refine-ensemble (written 11:53)
- Trace inspector mid-flight reading: `tool_call_counts={'run_bash_with_truncation': 35+, 'bash_async': 4, 'wait_and_tail': 7+, ...}`, `unpaired_bash_async: []`, `run_bash_used_for_training: []` (clean)
