# Specification: LLM Model Strategy (`spec_LLM.md`)

> **0→1 baseline.** Post-0→1 changes captured in [`../decisions.md`](../decisions.md) — notably **D6** (Architect rewinds use Sonnet, not Opus) and **D15** (`ANTHROPIC_API_KEY`, not `CLAUDE_API_KEY` as below).

This document defines the Large Language Model (LLM) configuration and tiering strategy for the `mle_agent`.


## 1. Model Tiers & Roles
The agent utilizes a tiered dispatch system to optimize for reasoning depth versus execution speed.

| Tier | Role | Model ID |
| :--- | :--- | :--- |
| **Strategic** | **System_Architect**: Blueprinting and complex pivots. | `claude-opus-4-6` |
| **Execution** | **Action Nodes**: Coding and data processing. | `claude-sonnet-4-6` |
| **Routing** | **Router_Brain**: State transitions and log analysis. | `claude-haiku-4-5-20251001` |

---

## 2. Credentials & Storage
* **Mechanism**: Authentication is handled via a root-level environment file `sample.env`.
* **Variable**: `CLAUDE_API_KEY` must be defined in `sample.env`.
* **Example**: `CLAUDE_API_KEY=xxxxxx`

---

## 3. Module Integration
The LLM serves as the reasoning engine that connects the physical workspace with the agent's cognitive architecture.