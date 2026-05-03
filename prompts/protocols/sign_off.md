# Sign-Off Protocol — Prompt Snippet

Embed this block verbatim into any Action Node prompt that participates in the shift handover loop. Execute before yielding control back to Router_Brain.

---

## Before exiting this node, execute these steps in order:

```
0. Process hygiene
   If you started any background process this shift via bash_async, it must
   be terminated before sign-off. Either wait_and_tail until status=exited,
   or kill_process(pid). The harness will sweep stragglers, but leaving
   work for the harness loses the final log tail you would have captured.

1. edit_file_chunk("ml_todo.md")
   Mark completed tasks: change [ ] to [x] for everything finished this shift.
   Do not mark tasks complete that are partially done or blocked.

2. Consistency check
   Skim ml_rules.md. Verify that any I/O paths, column names, or format assumptions
   in the code you wrote or modified this shift still match the contract.
   If you spot a drift, fix it now — one wrong path here becomes a zero-score submission later.

3. write_file("ml_progress.txt")
   Overwrite entirely using this format:

   Current Objective: <what you were working on>
   Current State: <DONE | IN_PROGRESS | BLOCKED>
   Blockers:
     [BLOCKER] TYPE: <ImportError|ShapeError|MetricFloor|SubmissionFail|Unrecoverable|Other>
     MSG: <single line>
     TRACE: <last relevant traceback line or metric value>
   (Omit the Blockers section entirely if there are no blockers.)
   Use Unrecoverable only when retries cannot help — e.g. the same failure
   has repeated across multiple architectures or hyperparameter sets, the
   data is fundamentally unusable, or the wall-clock budget is too tight
   to attempt another approach. Router will not rewind on Unrecoverable;
   it will route directly to Evaluator (or END if no submission.csv exists).
   Next Steps: <exact file path or command the next node should start with>

   Key Findings: (include this section — it helps the next node orient quickly)
   - Important discoveries: strongest predictors, data shapes, metric values
   - Output file paths and their dimensions
   - Any surprises or caveats the next node should know about

4. run_bash_with_truncation("git add <specific files> && git commit -m '<what changed and why>'")
   Commit only relevant files — no accidental staging of data files or secrets.
   Write the commit message in imperative mood: "Add feature engineering pipeline", not "Added..."

5. Emit handoff_message
   One sentence. Tell Router what you accomplished and what state you're leaving things in.
   Example: "Feature arrays written to /data/processed/; validation AUC 0.823 logged to metrics.txt."
```

If you cannot complete Sign-Off because of an unresolved blocker, write the blocker to `ml_progress.txt` first, then commit the partial state, then emit a handoff noting the blocker type and location.
