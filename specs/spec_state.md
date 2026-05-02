# State Graph Specification (`spec_state.md`)

> **0→1 baseline.** Post-0→1 changes captured in [`../decisions.md`](../decisions.md) — notably **D7** (auto-commit at every Action Node exit), **D13** (two-tier iteration budget: 10 Router redirect + 15 graph END), **D14** (context-window sliding: first message + last 20 pairs), and **D6** (Architect rewinds use Sonnet).

> **SSoT** for LangGraph node definitions, State schema, and edge rules.
> Memory file definitions → `spec_memory.md`. Tool details → `spec_tool.md`.

To prevent context collapse, **conversation history (`messages`) is wiped upon transitioning between distinct macro-phases**. Context is preserved through file-based macro-memory, lightweight LangGraph State variables, and the persistent `all_messages` accumulator.

---

## 1. Agent Macro-Memory Files

The agent maintains context across wiped sessions using four core files inside the competition workspace. See `spec_memory.md` §1 for full definitions and operating rules.

Quick reference: `ml_rules.md` (system prompt, every loop) | `ml_spec.md` (cold storage) | `ml_todo.md` (task tracker) | `ml_progress.txt` (shift handover)

---

## 2. Standard Context Protocols

All Action Nodes MUST execute these routines to bridge the amnesia between LangGraph state transitions.

* **Context Start (The "Wake-Up" Protocol):**
  All Action Nodes execute the Wake-Up protocol on entry. See `prompts/protocols/wake_up.md` for the authoritative step sequence.
  Summary: read `ml_progress.txt` → read `ml_todo.md` → run `git status && git log -n 5`. The `handoff_message` is received implicitly via LangGraph State.

* **Context End (The "Sign-Off" Protocol):**
  All Action Nodes execute the Sign-Off protocol before yielding to Router. See `prompts/protocols/sign_off.md` for the authoritative step sequence.
  Summary: mark `ml_todo.md` done → overwrite `ml_progress.txt` → `git commit` → emit `handoff_message`.

---

## 3. LangGraph State Schema (The "Clipboard")

The dictionary passed between nodes contains:

* `messages`: The active ReAct loop history (wiped on macro-node transitions by Router).
* `all_messages`: Persistent accumulator of all messages across all node transitions. **Never wiped.** Router appends `messages` to `all_messages` before wiping `messages`. Enables post-run LLM-as-a-judge evaluation of the complete agent trace.
* `handoff_message`: A brief instruction passed from the exiting node to the next.
* `current_phase`: The active phase tracking.
* `target_model`: Dictated by the Router (e.g., `haiku`, `opus` or `sonnet`). Use `haiku` for routing.
* `iteration_count`: Integer tracking total Router transitions. Incremented by Router on each invocation. Used as a safety circuit breaker — Router routes to END if this exceeds the configured maximum.
* `micro_tasks`: Ephemeral micro-task queue managed by `dynamic_task_manager`. Wiped on macro-phase transitions to prevent context bleeding. See `spec_tool.md` §3.
* `workspace_dir`: Absolute path to the competition workspace directory. Set once during graph initialization and read by all tools.
* `competition_id`: Competition identifier string (e.g. `"spaceship-titanic"`). Used to look up medal score thresholds from the static table in `src/medal_thresholds.py`. Set once during graph initialization.

---

## 4. Global Toolset

Action Nodes share core tool primitives executed by the `Universal_ToolNode`. See `spec_tool.md` for full parameters, failure modes, and constraints.

Tools: `run_bash_with_truncation` | `read_file` | `write_file` | `edit_file_chunk` | `dynamic_task_manager`

---

## Node Definitions

### 0. `Universal_ToolNode` (The Execution Engine)
* **Definition:** A non-LLM LangGraph node that strictly executes the tool calls requested by the Action Nodes.
* **Persona:** N/A
* **Tools Access:** N/A (Hosts the tools).
* **Edges:** Returns strictly back to the calling Action Node.
* **On Start:** Receives tool arguments from the LLM.
* **On Exit:** Appends execution results (stdout, stderr, file contents) back into the calling node's `messages` array.

### 1. `System_Architect` (The Planner)
* **Definition:** The strategic core. Translates the competition problem into a concrete ML pipeline and updates the blueprint if fundamental assumptions fail.
* **Persona:** Lead MLE Architect. Break the project into verifiable submodules.
* **Tools Access:** Full Global Toolset. May use `run_bash_with_truncation` strictly for *Data Discovery* (not pipeline building).
* **Edges:** Routes strictly to `Router_Brain`.
* **On Start:** If no competition workspace exists, bootstrap per `spec_memory.md` §0. Then reads the competition prompt and dataset metadata.
* **On Exit:** Writes/updates `ml_rules.md`, `ml_spec.md`, and `ml_todo.md`. Passes a `handoff_message` summarizing the strategy.

### 2. `Router_Brain` (Traffic Cop & Model Dispatcher)
* **Definition:** Orchestration node. Decides *which* phase happens next and *what model tier* is required.
* **Persona:** Project Manager. Review trackers. Select the next node and LLM tier (use Opus for architecture/rewinds, Sonnet for execution). Do not write code.
* **Tools Access:** None. Router receives a harness-assembled input block (see `spec_prompting.md` → Router Decision Interface) and emits a single JSON routing decision. It does not make tool calls.
* **Edges:** `Data_Engineer`, `Model_Engineer`, `Evaluator`, `System_Architect`, or `END`.
* **On Start (Context Cleanser):** **Appends current `messages` to `all_messages`, then wipes `messages`.** Increments `iteration_count`. The Router node function reads `ml_progress.txt` from disk and assembles the structured input block (HANDOFF_MESSAGE, PROGRESS_EXCERPT, CURRENT_PHASE, ITERATION_COUNT) before calling Haiku.
* **On Exit:** Sets `target_model`, `current_phase`, and `handoff_message` (from `rewind_reason` if rewinding, or a forward directive).

### 3. `Data_Engineer` (Action Node)
* **Definition:** Executes EDA, feature engineering, and data processing.
* **Persona:** Meticulous Data Engineer. Maintain strict I/O hygiene. Program defensively. Use text-based summaries; never print full dataframes.
* **Tools Access:** Full Global Toolset.
* **Edges:** Internal loop to `Universal_ToolNode`. Exits to `Router_Brain`.
* **On Start:** Execute **Wake-Up Protocol** (`prompts/protocols/wake_up.md`).
* **On Exit:** Execute **Sign-Off Protocol** (`prompts/protocols/sign_off.md`).

### 4. `Model_Engineer` (Action Node)
* **Definition:** Executes model architecture, training loops, and inference generation.
* **Persona:** Senior ML Engineer. Optimize for signal-to-noise ratio in terminal outputs. Log metrics to disk. Rely strictly on cleaned data arrays.
* **Tools Access:** Full Global Toolset.
* **Edges:** Internal loop to `Universal_ToolNode`. Exits to `Router_Brain`.
* **On Start:** Execute **Wake-Up Protocol** (`prompts/protocols/wake_up.md`).
* **On Exit:** Execute **Sign-Off Protocol** (`prompts/protocols/sign_off.md`).

### 5. `Evaluator` (The Gatekeeper)
* **Definition:** Independent QA. Checks validation metrics, data leakage, and submission formats.
* **Persona:** Independent, skeptical Code Reviewer. You do not train models. Verify test set integrity and strict competition format compliance.
* **Tools Access:** Full Global Toolset.
* **Edges:** Always routes to `Router_Brain`. Router decides whether to rewind or terminate (END).
* **On Start:** Execute **Wake-Up Protocol** (`prompts/protocols/wake_up.md`).
* **On Exit:**
    * *If Issues Found:* Execute Sign-Off with a typed `[BLOCKER]` in `ml_progress.txt`. Pass a targeted `handoff_message` explaining the failure.
    * *If All Checks Pass:* Verify `submission.csv` exists. Execute Sign-Off with `Current State: DONE` and no blockers. Router will route to END.

---

## Graph Lifecycle (A2A Integration)

The LangGraph graph is invoked by the A2A handler in `src/agent.py`. Two integration points connect the graph to the outside world:

**Entry:** The A2A handler receives the competition task (instructions text + dataset archive). Before invoking the graph, it:
1. Extracts the dataset archive to a staging location
2. Initializes LangGraph State with the competition instructions in `messages` and the dataset path in `handoff_message`
3. Invokes the graph starting at `System_Architect`

**Exit:** When Router routes to END, the handler:
1. Reads `submission.csv` from the competition workspace
2. Submits it as an A2A artifact via `updater.add_artifact(...)`

**Action Node → State handoff:** When an Action Node's ReAct loop ends (LLM produces no more tool calls), the node wrapper captures the LLM's final text response and writes it to `state["handoff_message"]`. This is what Router receives in its input block.

**Implementation note:** Action Nodes use the ReAct pattern (internal loop with Universal_ToolNode). Set a `recursion_limit` (e.g., 50 tool calls per node invocation) to prevent runaway internal loops. This is separate from `iteration_count`, which tracks Router-level transitions.

---

## Appendix: High-Level Dry Run (Housing Prices Competition)

This trace demonstrates the macro-loop handoffs and the context protocols in action.

**1. Workspace Bootstrap & Blueprint Phase**
* **Active Node:** `System_Architect`
* **Action:** Bootstraps competition workspace (`spec_memory.md` §0). Reads the competition prompt. Uses `bash` to run `df.info()` for discovery. Realizes the dataset is tabular with heavy skew.
* **Sign-Off:** Creates `ml_rules.md`, `ml_spec.md`, and `ml_todo.md`.
* **State Handoff:** *"Initial spec created. Dataset is tabular. Pass to Data Engineer."*

**2. The First Route**
* **Active Node:** `Router_Brain`
* **Context Cleanser:** Appends `messages` to `all_messages`, then wipes `messages`. Increments `iteration_count`. Assembles input block with handoff message and progress excerpt.
* **Action:** Routes to `Data_Engineer`.

**3. The Data Pipeline**
* **Active Node:** `Data_Engineer`
* **Wake-Up:** Reads `ml_progress.txt`, `ml_todo.md`. Runs `git log` (sees the Architect's commit).
* **Action:** Writes `data_prep.py` to impute missing values and log-transform the target. Runs it.
* **Sign-Off:** Checks off `ml_todo.md`. Runs `git commit -m "feat: complete imputation"`. Updates `ml_progress.txt`.
* **State Handoff:** *"Data pipeline complete. clean_train.csv saved."*

**4. The Error & The Pivot**
* **Active Node:** `Router_Brain` routes to `Model_Engineer`.
* **Active Node:** `Model_Engineer`
* **Wake-Up:** Reads `ml_progress.txt`, `ml_todo.md`. Runs git protocol.
* **Action:** Writes `train.py` for XGBoost. Runs it.
* **The Bug:** `Universal_ToolNode` returns: `ValueError: DataFrame contains categorical data (Neighborhood)`.
* **Sign-Off:** Realizes it cannot fix data pipelines. Leaves `ml_todo.md` unchecked. Overwrites `ml_progress.txt` with: *"BLOCKER: Categorical column 'Neighborhood' is unencoded. XGBoost failed."*
* **State Handoff:** *"Modeling blocked by data encoding issue. Returning to Router."*

**5. The Rewind**
* **Active Node:** `Router_Brain`
* **Context Cleanser:** Appends `messages` to `all_messages`, wipes `messages`. Increments `iteration_count`. Assembles input block — progress excerpt shows the explicit blocker regarding data encoding.
* **Action:** Routes *backward* to `Data_Engineer`.

**6. The Fix**
* **Active Node:** `Data_Engineer`
* **Wake-Up:** Reads `ml_progress.txt`. Sees its own mistake.
* **Action:** Uses `edit_file_chunk` to add One-Hot Encoding to `data_prep.py`. Re-runs the script.
* **Sign-Off:** `git commit -m "fix: add one-hot encoding"`. Clears the blocker in `ml_progress.txt`.
* **State Handoff:** *"Encoding bug fixed. clean_train.csv overwritten."*

**7. Completion**
* **Router_Brain:** Appends + wipes + increments. Routes to `Model_Engineer`.
* **Model_Engineer:** Successfully trains model. Generates draft `submission.csv`. Hands off to Router.
* **Router_Brain:** Appends + wipes + increments. Routes to `Evaluator`.
* **Evaluator:** Wake-up. Runs validation. Confirms validation score is sane and `submission.csv` strictly matches competition format. Signs off with `Current State: DONE`, no blockers.
* **Router_Brain:** Appends + wipes + increments. Sees Evaluation phase complete, no blockers. Routes to `END`.
* **A2A handler:** Reads `submission.csv` from workspace. Submits as A2A artifact. **Post-run:** `all_messages` contains the full trace — ready for LLM-as-a-judge evaluation.
