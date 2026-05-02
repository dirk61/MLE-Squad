# MLE-Squad: A High-Fidelity Autonomous ML Engineering Team
<!--This Agent approaches each ML problem EXACTLY the way a real [MLE] (team) would: an Architect reads the problem and designs the pipeline, a Data Engineer builds the features, a Model Engineer trains and iterates, and an Evaluator does sanity checks on the final submission. Each specialist is equipped with sandboxed tools and carries domain-specific ML instincts without assuming fixed solutions — the pipeline adapts to the problem. Above all, a manager (router) coordinates — deciding who's next to work, assigning time and cost budget (Opus vs Sonnet vs Haiku), and pushing back to prior stages if the team is on a wrong route (triggering rewinds). All coordinated through a LangGraph cyclic graph that enables dynamic phase transitions.

The core design challenge mirrors how real [MLE] teams stay aligned across long projects: every agent writes its work to disk — cross-referenced architectural blueprints, task checklists, progress handovers, execution logs — in a git-versioned workspace any agent can audit on re-entry. When the context window compacts between phases, agents re-orient from persistent memory hierarchy rather than losing context. This makes the system robust on complex, multi-phase problems that need long runs. 

Cost-performance balance is a first-class concern: hard iteration caps and prompted ML instincts actively discourage over-optimizing on validation — compute is spent where it generalizes, not where it overfits. A post-run LLM-as-a-judge evaluation is also implemented to enable systematic improvement across competition runs.

We evaluated across a diverse set of competitions spanning different categories and difficulties, showing competitive scores and validating the robustness of this agent design.-->

<!--### A multi-agent MLE team that thinks in Git commits and persists via disk.

**MLE Agent** is an autonomous system that solves machine learning problems by simulating a high-functioning *MLE team*: 
* **Role-Based Specialization:**: Instead of a single "do-it-all" prompt, the system utilizes a **cyclic graph** to coordinate four specialized agents—**Architect, Data Engineer, Model Engineer, and Evaluator**—governed by a strategic **Router (Manager)**.
* **Hierarchical Memory for Team Collaboration:** Think of a typical engineering team's collab workflow: Slack for updates, Git for version control, and shared docs for project specs. Acting the same way, our specialist agents ONLY pass compact handoff messages to their successors, commit every major code change to a Git-versioned workspace, and collectively maintain local files for architectural blueprints, data distribution summaries, and prioritized TODO lists. By offloading project state to disk, the system prevents the "context window collapse" typical of long-running tasks. This allows agents to instantly re-orient by auditing the file system upon entry, ensuring that critical engineering insights are never lost to token limitations.-->
<!--MLE-Squad is an autonomous system that solves machine learning problems by simulating the workflow of a high-functioning engineering team. The architecture follows a three-fold design philosophy to ensure robustness on complex, long-running tasks:



1. Structure: Instead of one prompt doing everything, a Router coordinates four specialists—Architect, Data Engineer, Model Engineer, and Evaluator. This allows the team to move back and forth between tasks as needed—for example, sending a model back to the data stage if features are missing—rather than following a rigid, one-way sequence.

2. Workflow & Memory: To prevent the system from "forgetting" the plan over long runs (Context Window Collapse), every agent writes its work to a Git-versioned workspace.Agents pass concise handoff notes to one another and rely on shared files for blueprints and checklists. This allows an agent to re-orient itself instantly by reading the disk rather than processing thousands of lines of previous chat history.

3. Project Oversight: The system enforces practical boundaries. The Router acts as a lead, evaluating the Evaluator's feedback to decide if a task needs a "do-over" or if the entire plan needs to pivot. It also sets hard limits on time and compute costs, preventing the agents from wasting tokens on endless tuning loops that only offer marginal gains.

This architecture currently validates itself through top-tier performance on the AgentBeats leaderboard (April 2026), where it holds the #1 rank in 4 out of 6 featured competitions. While we are still optimizing it through LLM-as-a-judge evaluation, MLE-Squad already proves to be a robust and scalable framework for autonomous machine learning engineering.-->

> **MLE-Squad** is an autonomous system that solves machine learning problems by simulating a high-functioning engineering team. We abandoned the fragile "do-it-all" mega prompt in favor of a distributed architecture that maps directly to real-world workflows:

<table width="100%">
  <thead>
    <tr style="background-color: #f6f8fa;">
      <th width="50%" align="left">👥 The Human MLE Team</th>
      <th width="50%" align="left">🤖 The MLE-Squad Architecture</th>
    </tr>
  </thead>
  <tbody>
    <tr style="background-color: #f6f8fa;">
      <td colspan="2" align="center"><b>🏗️ Structure</b></td>
    </tr>
    <tr>
      <td valign="top">
        <b>Tech Leads & Specialists</b><br>
        A team lead delegates work. An Architect designs the pipeline, a Data Engineer preps data, an MLE trains, and peers review.
      </td>
      <td valign="top">
        <b>Role-Based Specialization</b><br>
        A <code>Router</code> agent coordinates four specialists (<code>Architect</code>, <code>Data Engineer</code>, <code>Model Engineer</code>, <code>Evaluator</code>).
      </td>
    </tr>
    <tr style="background-color: #f6f8fa;">
      <td colspan="2" align="center"><b>🔄 Workflow</b></td>
    </tr>
    <tr>
      <td valign="top">
        <b>Focused Handoffs</b><br>
        Engineers pass work using clear status updates ("Here is the data shape"), rather than sharing their entire trial-and-error log.
      </td>
      <td valign="top">
        <b>Compact Context Passing</b><br>
        Agents pass only explicit summary strings to the next node, preventing noise from crowding the active context window.
      </td>
    </tr>
    <tr>
      <td valign="top">
        <b>Design Docs & Progress Trackers</b><br>
        The team stays aligned on the big picture by keeping shared design specifications and active to-do lists up to date.
      </td>
      <td valign="top">
        <b>Shared Project Memory</b><br>
        Agents collectively maintain local files (<code>ml_spec.md</code>, <code>ml_todo.md</code>). They read these to instantly re-orient on new tasks.
      </td>
    </tr>
    <tr>
      <td valign="top">
        <b>Git Version Control</b><br>
        Code is systematically versioned. If an experiment fails, the team reviews the commit history and reverts safely.
      </td>
      <td valign="top">
        <b>Git-Driven Workspace</b><br>
        Agents rely on clean Git control. Offloading history to commits fundamentally prevents <b><code>Context Window Collapse</code></b>.
      </td>
    </tr>
    <tr style="background-color: #f6f8fa;">
      <td colspan="2" align="center"><b>🛑 Reality-Checks</b></td>
    </tr>
    <tr>
      <td valign="top">
        <b>Reviews & Course Corrections</b><br>
        Progress isn't linear. A lead might ask an engineer to redo a task, or tell the Architect to scrap the design and pivot.
      </td>
      <td valign="top">
        <b>Dynamic Routing & Rewinds</b><br>
        The <code>Router</code> evaluates progress and can loop an agent to try again, step back a phase, or trigger a complete rewind.
      </td>
    </tr>
    <tr>
      <td valign="top">
        <b>Resource Limits & Cost Balancing</b><br>
        Teams balance performance against time and compute costs, avoiding perfectionism. Engineers operate within boundaries.
      </td>
      <td valign="top">
        <b>Sandboxed Constraints</b><br>
        Agents balance token costs and time via strict tool timeouts and iteration caps, explicitly avoiding endless tuning loops.
      </td>
    </tr>
  </tbody>
</table>
<!--
| 👥 The Human MLE Team | | 🤖 The MLE-Squad Architecture |
| :--- | :---: | :--- |
|| 🏗️ <br>**Structure**  | |
| **Tech Leads & Specialists**<br>A team lead delegates work. An Architect designs the pipeline, a Data Engineer preps data, an MLE trains, and peers review. | ➡️ | **Role-Based Specialization**<br>A `Router` agent coordinates four specialists (`Architect`, `Data Engineer`, `Model Engineer`, `Evaluator`). |
| |🔄 <br> **Workflow**  | |
| **Focused Handoffs**<br>Engineers pass work using clear status updates ("Here is the data shape"), rather than sharing their entire trial-and-error log. | ➡️ | **Compact Context Passing**<br>Agents pass only explicit summary strings to the next node, preventing noise from crowding the active context window. |
| **Design Docs & Progress Trackers**<br>The team stays aligned on the big picture by keeping shared design specifications and active to-do lists up to date. | ➡️ | **Shared Project Memory**<br>Agents collectively maintain local files (`ml_spec.md`, `ml_todo.md`). They read these to instantly re-orient on new tasks. |
| **Git Version Control**<br>Code is systematically versioned. If an experiment fails, the team reviews the commit history and reverts safely. | ➡️ | **Git-Driven Workspace**<br>Agents rely on clean Git control. Offloading history to commits fundamentally prevents **`Context Window Collapse`**. |
|| 🛑 <br> **&nbsp;Reality&#8209;Checks**  | |
| **Reviews & Course Corrections**<br>Progress isn't linear. A lead might ask an engineer to redo a task, or tell the Architect to scrap the design and pivot. | ➡️ | **Dynamic Routing & Rewinds**<br>The `Router` evaluates progress and can loop an agent to try again, step back a phase, or trigger a complete rewind. |
| **Resource Limits & Cost Balancing**<br>Teams balance performance against time and compute costs, avoiding perfectionism. Engineers operate within boundaries. | ➡️ | **Sandboxed Constraints**<br>Agents balance token costs and time via strict tool timeouts and iteration caps, explicitly avoiding endless tuning loops. |
-->

---

## 🏆 Leaderboard Update: mle-bench on AgentBeats
Date: April 14, 2026 | Status: Benchmarking Ongoing 🟢


MLE-Squad currently leads the [MLE-bench leaderboard](https://agentbeats.dev/agentbeater/mle-bench) of the [AgentX-AgentBeats Competition](https://rdi.berkeley.edu/agentx-agentbeats) hosted by [Berkeley RDI](https://rdi.berkeley.edu/).

 The leaderboard utilizes OpenAI's [MLE-bench](https://github.com/openai/mle-bench)—a comprehensive evaluation consisting of 75 Kaggle competitions to test AI agents on real world MLE tasks. 

### 🥇 Current Standing: Rank #1 on 4/6 Featured Leaderboards
On the AgentBeats leaderboard featuring 6 competitions, we currently hold the **top spot** in 4 of the them:
* Spaceship Titanic (Tabular)
* Denoising Dirty Documents (Image-to-Image)
* Aerial Cactus Identification (Image Classification)
* Jigsaw Toxic Comment Classification (Text Classification)

---

### 📊 Performance Summary

| Competition | AgentBeats Rank | Score | Gold<sup>1</sup> | Medal<sup>2</sup> |
|---|---|---|---|---|
| Spaceship Titanic | #1 | 0.832 | 0.821 | Gold 🥇 |
| Denoising Dirty Documents<sup>3</sup> | #1 | 0.013 | 0.018 | Gold 🥇 |
| Aerial Cactus Identification | #1 | 0.99995 | 1.000 | Above median |
| Jigsaw Toxic Comment Classification | #1 | 0.981 | 0.987 | Above median |
| MLSP 2013 Bird Classification | N/A<sup>4</sup> | 0.875 | 0.935 | Bronze 🥉 |


---
<small>¹ The score required to achieve gold medal in the original Kaggle competition.</small><br>
<small>² The medal the agent would win if participating in the original competition (Gold/Silver/Bronze/Above Median/Below Median).</small><br>
<small>³ For *Denoising Dirty Documents*, a lower score indicates superior performance.</small><br>
<small>⁴ We are also benchmarking other competitions in the MLE-bench not featured on the AgentBeats Leaderboard.</small>

---

### 🔍 Next Steps: Optimization & Scaling
As we continue to iterate, our roadmap focuses on two primary objectives:
1. Refining the agent's performance, robustness, and token-efficiency, using a LLM-as-a-judge framework for post-run evaluation. This allows us to identify and optimize towards failure modes, edge cases and bottlenecks.
2. Expanding beyond the 6 featured leaderboards to evaluate against the OpenAI [Lite Evaluation](https://github.com/openai/mle-bench#lite-evaluation) subset of the MLE-bench. This will provide a more comprehensive view of the agent's ability to generalize across the broader MLE-bench landscape.

---

## Architecture

### Agent Graph

```
                              ┌──────────────────────────────────────┐
                              │                                      │
                              ▼                                      │ rewind
                 ┌────────────────────────┐                          │ (spec wrong)
   START ──────► │    System_Architect    │                          │
                 │      Opus · Plan       │                          │
                 └───────────┬────────────┘                          │
                             │                                        │
                             ▼                                        │
                 ┌────────────────────────┐                          │
            ┌──► │      Router_Brain      │ ◄────────────────────────┘
            │    │    Haiku · Manager     │
            │    └──────┬──────┬──────────┘
            │           │      │        │
            │     ┌─────┘      │        └──────────┐
            │     │            │                   │
            │     ▼            ▼                   ▼
            │  ┌──────────┐  ┌──────────┐  ┌───────────┐
            │  │   Data   │  │  Model   │  │ Evaluator │
            │  │Engineer  │  │Engineer  │  │  Haiku    │
            │  │ Sonnet   │  │ Sonnet   │  │           │
            │  ├──────────┤  ├──────────┤  ├───────────┤
            │  │ bash     │  │ bash     │  │ bash      │
            │  │ read_file│  │ read_file│  │ read_file │
            │  │write_file│  │write_file│  │write_file │
            │  │edit_chunk│  │edit_chunk│  │           │
            │  │task_queue│  │task_queue│  │           │
            │  └────┬─────┘  └────┬─────┘  └─────┬─────┘
            │       │             │               │
            └───────┴─────────────┘               │
                      back to Router              │
                                                  ▼
                                                 END
```

### Node Roles

| Node | Model | Responsibility |
|---|---|---|
| `System_Architect` | Opus | Reads competition description, runs data discovery, writes blueprint (`ml_rules.md`, `ml_spec.md`, `ml_todo.md`) |
| `Router_Brain` | Haiku | Reads progress, decides next node, assigns model tier, triggers rewinds on typed blockers |
| `Data_Engineer` | Sonnet | Exploratory data analysis, feature engineering, preprocessing pipeline, produces validated arrays |
| `Model_Engineer` | Sonnet | Model Selection, model training, hyperparameter tuning, generates `submission.csv` |
| `Evaluator` | Haiku | Submission format validation, metric sanity check, gates final submit |

### Toolset

All agents (except Router) can run bash commands, read/write files, and edit code. Here's what they have:

| Tool | What it does |
|---|---|
| `*bash` | Run commands: train scripts, install packages, check data shapes. Output limited to 8K chars. LLM-defined timeout window. |
| `read_file` | Read code, logs, memory files. Not used on raw data files. |
| `write_file` | Create new Python scripts, configs, tracking files. |
| `edit_file_chunk` | Find-and-replace edits in existing code. |
| `task_queue` | Track sub-tasks within a phase. Cleared when moving to the next phase. |



---

## Memory & Context System

Each competition gets its own isolated workspace with git version control. Instead of agents talking to each other directly, they leave notes in shared files — like a real team using Google Docs and Git.

### What's on Disk

```
workspace/
├── ml_rules.md          ← The rules of this specific competition
│                           (reloaded each phase for fresh context)
├── ml_spec.md           ← High-level architecture decisions
│                           (read only when a task needs it)
├── ml_todo.md           ← Checklist of what needs to happen
│                           (marks tasks [x] done or [ ] pending)
├── ml_progress.txt      ← Handoff note from the last phase
│                           (what was done, what's blocking, what's next)
├── logs/
│   ├── metrics.txt      ← Training scores, hyperparameters
│   ├── bash_history.log ← Every script that ran + its output
│   └── all_messages.jsonl ← Complete trace of everything (for post-run analysis)
└── .git/                ← Full history; each phase = one commit
```

### Why This Design Works

- **No context bloat.** The system forgets old messages at the end of each phase, but reads fresh files to re-orient. No stale reasoning carries over.
- **Fast handoffs.** New agents start fast: `pwd && ls` → read progress → read todo → check `git log`. Full context in 3 steps.
- **Trust the files.** If an agent says a task is done but didn't commit it, the next agent sees uncommitted changes and knows not to trust the claim.
- **Lazy loading.** The long spec only gets read when a task says "see ml_spec.md section X." Keeps prompt size down.

---

## Repository Structure

```
mle_squad/
├── src/
│   ├── agent.py              # Entry point: unpack tar, init graph, submit artifact
│   ├── graph.py              # LangGraph StateGraph: nodes, edges, conditional routing
│   ├── nodes.py              # Node implementations: ReAct loop, Architect, Router
│   ├── state.py              # AgentState TypedDict (LangGraph shared state)
│   ├── llm.py                # Tiered LLM dispatch (Opus / Sonnet / Haiku)
│   ├── tools.py              # Tool implementations + Anthropic schemas
│   ├── tool_node.py          # Universal tool dispatcher
│   ├── prompts.py            # Prompt loader + assembly (static + protocols + ml_rules)
│   ├── medal_thresholds.py   # Pre-computed medal scores for all 82 competitions
│   ├── executor.py           # A2A task lifecycle
│   └── server.py             # A2A HTTP server entry point
├── prompts/
│   ├── nodes/                # Static system prompt per node
│   │   ├── architect.md
│   │   ├── router.md
│   │   ├── data_engineer.md
│   │   ├── model_engineer.md
│   │   └── evaluator.md
│   ├── protocols/
│   │   ├── wake_up.md        # pwd · progress · todo · git log
│   │   └── sign_off.md       # update todo · write progress · commit · handoff
│   └── dynamic/
│       └── ml_rules_template.md  # Architect fills this per competition
├── specs/                    # Design specifications (cold storage)
├── Dockerfile
├── amber-manifest.json5      # AgentBeats deployment config
└── pyproject.toml
```



---

## Design Decisions

### 🧩 Why specialists instead of one big agent?

A single agent that tries to do everything either takes too long (trying every angle) or cuts corners (rushing to solutions). Our design: each person does their job well. The Architect spends time on a solid design. The Data Engineer spends time building trustworthy features. The Model Engineer focuses on training. The Evaluator does a final check. Each one can apply deep expertise without getting pulled in five directions. And if something goes wrong, you can send work back to the right person instead of restarting from scratch.

### 🧩 Why write to disk instead of keeping everything in memory?

Two reasons. First, the system needs to forget old conversations between phases — too much noise. Second, the next agent needs to pick up fast. A 10-line handoff note beats reading 100 messages. Plus git log gives you the full audit trail: who did what, when, and if they committed it.

One more thing: agents can be swapped in and out (different models, different strategies) because they all follow the same file protocol. The code is in `/src/`, the data is in `/data/`, the status is in `ml_progress.txt`. As long as you stick to that contract, you can change the agents.



