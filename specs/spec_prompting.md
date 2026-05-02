# Prompting Specification — MLE Agent

> **0→1 baseline.** Post-0→1 changes captured in [`../decisions.md`](../decisions.md) — notably **D1** (ML spec is *context and direction*, not binding prescription — explicit in current Action Node prompts), **D2** (Architect HARD STOPs), **D8** (no medal targets), **D9** (Evaluator restricted to 2 blocker types).

## Philosophy

Prompt as a manager, not a script writer. A good instruction encodes **what success looks like** and **what is off-limits** — it does not narrate the steps. A node briefed with an identity and a constraint set will find its own route; a node handed a procedure becomes brittle the moment reality diverges from the script.

Three things belong in a system prompt:
1. **Who you are** — a declaration of role and professional instinct, not a job description
2. **What done looks like** — the exit condition for this node's work
3. **Hard rails** — the non-negotiables that protect the rest of the system (I/O hygiene, cold-storage limits, commit discipline)

Everything else is the node's to figure out.

---

## System Prompt Architecture

Prompts are assembled in two layers at runtime:

```
┌─────────────────────────────────────────────────────┐
│ LAYER 1 — Static Base (baked in code at node init)  │
│   • Persona declaration                             │
│   • Tool inventory + usage constraints              │
│   • Hard behavioral rails                           │
│   • Exit condition statement                        │
├─────────────────────────────────────────────────────┤
│ LAYER 2 — Dynamic Injection (prepended each loop)   │
│   • Full content of ml_rules.md                     │
│   • Encodes: competition constraints, I/O paths,    │
│     metric target, submission format, active phase  │
└─────────────────────────────────────────────────────┘
```

Layer 1 is competition-agnostic — it defines the node's character. Layer 2 is session-specific — it tells the node what world it's operating in this run. Keep them cleanly separated so node prompts don't need editing between competitions.

> `ml_rules.md` is the seam between the two layers. It is authored by System_Architect at the start of each competition and loaded verbatim by all Action Nodes each loop.

---

## Node Prompting Contracts

Defines the prompting contract for each node: the role framing, the behavioral anchors to enforce, and what to deliberately leave open.

| Node | Role Framing | Enforce | Leave Open |
|---|---|---|---|
| **System_Architect** | "You are the lead ML architect. You set the foundation; everything downstream builds on your decisions." | Blueprint must cover all pipeline stages. `ml_todo.md` tasks must include explicit `ml_spec.md` cross-references. `bash` only for data discovery in this phase. | Which architecture to choose. How to structure the spec. How deep to go in any section. |
| **Router_Brain** | "You are the project manager. You read signals, not code. You decide where to send work next." | Output exactly one JSON block. Never write code. Choose Opus for architecture decisions and rewinds; Sonnet for execution. | Rationale for routing. How much context to weigh. |
| **Data_Engineer** | "You are a rigorous data engineer. Your job is done when clean, validated, leakage-free data arrays exist on disk." | No full dataframe prints — text summaries only. Strict I/O hygiene: output paths must be explicit and stable. Defensive programming on data shapes. | What EDA to run. How to handle missing values. Feature engineering choices. Which library to use. |
| **Model_Engineer** | "You are an ML engineer focused on signal. You inherit clean data and return trained models with logged metrics." | Log all metrics to disk. Never read raw data — consume only what Data_Engineer wrote. Optimize terminal output for signal-to-noise. | Architecture choices. Hyperparameter strategy. Which optimizer or scheduler. |
| **Evaluator** | "You are an independent, skeptical code reviewer. You do not train models. Finding a problem IS your success." | Check test set integrity, data leakage, and competition submission format compliance. If anything fails, document it in progress.txt with a `[BLOCKER]` entry. | What to look at first. How deep to go. How many checks to run. |

---

## Context Lifecycle Protocols

Wake-Up and Sign-Off are prompt-enforced rituals. The ordering is load-bearing.

### Wake-Up (on node entry)

> Authoritative step sequence: `prompts/protocols/wake_up.md`

**Rationale for the ordering:** Git comes last so the node reads intent before reading reality — this prevents anchoring on stale state if git shows unexpected files.

Do **not** read `ml_spec.md` during Wake-Up unless `ml_todo.md` contains an explicit cross-reference like `Ref: ml_spec.md → Section 2.1`. Cold storage is cold for a reason: reading it adds 3–5K tokens of irrelevant context to routine execution loops.

### Sign-Off (on node exit, before yielding to Router)

> Authoritative step sequence: `prompts/protocols/sign_off.md`

**Rationale:** The commit happens at Sign-Off, not at task completion. Each commit in the log should represent a completed node shift.

---

## Router Decision Interface

Router_Brain operates on Haiku — small context, fast, reliable on structured output. Its input must be structured; its output must be parseable without interpretation.

### Input block (assembled by the Router node function before calling Haiku):
```
CURRENT_PHASE: <phase_name>
HANDOFF_MESSAGE: <content of state.handoff_message from the exiting node>
PROGRESS_EXCERPT:
<last 20 lines of ml_progress.txt>
AVAILABLE_NODES: System_Architect | Data_Engineer | Model_Engineer | Evaluator | END
ITERATION_COUNT: <current iteration count>
```

### Required output (one JSON block, nothing else):
```json
{
  "next_node": "Data_Engineer",
  "target_model": "claude-sonnet-4-6",
  "rewind_reason": null
}
```

`rewind_reason` is non-null only when routing back to an earlier phase. This field is written into the next node's `handoff_message` so it understands why it was rewound — without re-reading progress.txt.

Model tier mapping: Architect/rewinds → `claude-opus-4-6`; execution nodes → `claude-sonnet-4-6`; Router itself → `claude-haiku-4-5-20251001`.

---

## Blocker Expression Vocabulary

Blockers in `ml_progress.txt` must use this schema so Router can pattern-match without LLM interpretation. Free-text blockers are unreliable under Haiku.

```
[BLOCKER] TYPE: <ImportError|ShapeError|MetricFloor|SubmissionFail|Other>
MSG: <single line description>
TRACE: <last relevant traceback line or metric value>
```

**Type → routing semantics:**
- `ImportError` / `ShapeError` → rewind to Data_Engineer (upstream data issue)
- `MetricFloor` → route to Model_Engineer with Opus (architectural rethink)
- `SubmissionFail` → route to Evaluator (format/leakage check)
- `Other` → escalate to System_Architect with Opus

Nodes should prefer a typed blocker over prose even when the type isn't a perfect fit. The `MSG` field is where nuance lives.

---

## Templates Reference

Pre-written starter prompts live in `mle_agent/prompts/`. These are bases, not final prompts — competition-specific context enters via `ml_rules.md` at runtime.

```
mle_agent/prompts/
  nodes/
    architect.md          ← System_Architect system prompt base
    router.md             ← Router_Brain prompt + JSON output schema
    data_engineer.md      ← Data_Engineer system prompt base
    model_engineer.md     ← Model_Engineer system prompt base
    evaluator.md          ← Evaluator system prompt base
  protocols/
    wake_up.md            ← Wake-Up snippet (embed in all Action Node prompts)
    sign_off.md           ← Sign-Off snippet (embed in all Action Node prompts)
  dynamic/
    ml_rules_template.md  ← Starter template for competition-specific ml_rules.md
```

Compose Action Node prompts by concatenating the static base, protocol snippets, and `ml_rules.md` content. See **Implementation Note for Claude Code** below for the exact assembly formula.

---

## Implementation Note for Claude Code

When building the prompt assembly code in `src/agent.py`:

1. **Protocol embedding**: Read the contents of `prompts/protocols/wake_up.md` and `prompts/protocols/sign_off.md` at startup. Concatenate them into each Action Node's system prompt string. The phrase "embed this block verbatim" in the protocol files means literal string concatenation, not a file path reference the LLM should follow at runtime.

2. **Prompt assembly formula for Action Nodes** (Data_Engineer, Model_Engineer, Evaluator):
   ```
   system_prompt = (
       read("prompts/nodes/<node>.md")
       + "\n\n" + read("prompts/protocols/wake_up.md")
       + "\n\n" + read("prompts/protocols/sign_off.md")
       + "\n\n" + read("<workspace>/ml_rules.md")  # dynamic, per-competition
   )
   ```

3. **System_Architect**: Uses the full assembly formula (like other Action Nodes). On first entry, `ml_rules.md` does not exist yet — the static base alone is sufficient for bootstrap. On re-entry (rewind from Router), the protocols ensure it reads current state before revising the blueprint.

4. **Router_Brain**: Uses only `prompts/nodes/router.md` as the system prompt. The user message is the harness-assembled input block (CURRENT_PHASE, HANDOFF_MESSAGE, PROGRESS_EXCERPT, AVAILABLE_NODES, ITERATION_COUNT). No protocol snippets, no `ml_rules.md`.
