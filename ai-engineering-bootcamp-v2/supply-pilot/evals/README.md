# SupplyPilot Agent Evaluations

This folder contains the TRACE evaluation work for the SupplyPilot single-agent system.

The purpose of these evaluations is to inspect real agent traces, identify recurring failures, implement targeted fixes, and rerun the same evaluation set to measure whether agent behaviour improved.

## Evaluation Flow

The evaluation followed four stages:

### 1. Baseline Evaluation — Traces 1–20

The original 20-question golden evaluation set was run against the initial agent.

Each trace was reviewed against its corresponding validated golden case and evaluated across:

- completion
- answer correctness
- tool selection
- tool arguments
- calculation correctness
- constraint compliance
- policy retrieval
- grounding
- response relevance
- required fields
- duplicate tool calls
- total tool calls
- LLM calls

These traces establish the baseline before fixes were introduced.

---

### 2. Fix 1 — Failure Observability

**Relevant traces: 20 → 23**

Golden Case 20 exposed an execution-control problem.

The complex end-to-end planning question reached the maximum LLM-call limit before producing a final response.

Originally, this failed execution could still be persisted incorrectly as a successful trace.

The tracing logic was changed so that:

- completed runs are stored as `success`
- incomplete/exception runs are stored as `failed`
- the error message is persisted
- traces are saved even when execution fails

Trace 23 demonstrates the fix: the agent still reaches the LLM-call limit, but the failure is now correctly recorded.

**Result:** observability fixed, but agent completion was not yet fixed.

---

### 3. Fix 2 — LLM Call Limit

**Relevant traces: 23 → 25**

After failure tracking was corrected, the next problem was the execution ceiling.

The original maximum of 8 LLM calls was insufficient for the complex end-to-end Golden Case 20.

An intermediate test with a higher limit still failed to complete.

The maximum LLM-call ceiling was then increased to 20.

Trace 25 successfully completed the end-to-end workflow.

However, completion exposed another problem: the agent produced inconsistent replenishment calculations using different planning points.

**Result:** execution-limit failure fixed, exposing a planning-logic problem.

---

### 4. Fix 3 — Deterministic Planning-Point Logic

**Relevant traces: 25 → 28**

The next fix addressed inconsistent planning-week selection.

For replenishment decisions:

- if the user explicitly requests a future planning week, that week is used
- otherwise, the default replenishment planning point is CW
- stockout week is evaluated separately as a supply-risk/timing signal
- projected inventory, forward demand, WOS, target inventory, gap and replenishment requirement must all use the same selected planning point

A deterministic `select_replenishment_planning_point` function was added and the agent/policy logic was updated.

The progression was:

- Trace 25 — completed but produced competing planning calculations
- Trace 26 — one calculation path remained, but used the wrong inventory input
- Trace 27 — correct 160-unit result, but planning-point selection was still implicit
- Trace 28 — deterministic selector explicitly selects CW and the complete result matches Golden Case 20

For Trace 28:

- CW projected inventory = 23
- forward average demand = 35
- target inventory = 175
- gap = -152
- raw replenishment requirement = 152
- MOQ/order-multiple adjusted quantity = 160
- first stockout = CW+1
- first unmet demand = 11
- existing PO arrival = CW+4
- standard new-order arrival = CW+6
- arrival risk = TRUE
- timing gap = 5 weeks
- recommendation = INCREASE 160 units + review expedite/earlier supply

**Result:** Golden Case 20 passes the corrected deterministic planning workflow.

---

## Full Regression Run — Traces 29–48

After the targeted fixes, the complete 20-question golden evaluation set was run again.

| Dataset | Trace IDs | Purpose |
|---|---:|---|
| Baseline | 1–20 | Original agent behaviour |
| Fix investigation | 20–28 | Diagnose and validate individual fixes |
| Final regression | 29–48 | Rerun all 20 golden questions after fixes |

The final regression set should be compared with traces 1–20 to evaluate overall movement.

Intermediate traces 21–28 are debugging/fix-validation traces and are **not part of the final 20-case before/after aggregate comparison**.

---

## Evaluation Storage

Raw agent execution data is stored in:

`agent_traces`

Human open-coding and golden-case linkage is stored in:

`trace_reviews`

Validated reference answers and expected behaviour are stored in:

`golden_cases`

Structured PASS/FAIL evaluation results are stored in:

`trace_evaluations`

This keeps raw observability separate from human review and evaluation results.

---

## Evaluation Architecture

The evaluation flow is:

User Question
    ↓
Agent Execution
    ↓
agent_traces
    ↓
Human Open Coding
    ↓
trace_reviews
    ↓
Validated Golden Case
    ↓
golden_cases
    ↓
Structured Evaluation
    ↓
trace_evaluations
    ↓
Failure Taxonomy
    ↓
Targeted Fix
    ↓
Regression Run

---

## Evaluation Files

- `traces_baseline.jsonl` — baseline traces before fixes
- `traces_after_llm_limit.jsonl` — traces used around the execution-limit fix
- `traces_after_planning_fix.jsonl` — final 20-case rerun after the planning fix
- `export_traces.py` — exports trace data for evaluation
- `test_traces.py` — deterministic trace assertions

The PostgreSQL evaluation tables remain the primary structured source for PASS/FAIL evaluation results.

---

## Key Finding

The evaluation demonstrated that improving agent reliability required more than increasing the execution limit.

The progression was:

**Detect the failure correctly → allow sufficient execution → fix the underlying planning logic → rerun the complete golden set.**

The final regression run is therefore evaluated not only for completion and answer correctness, but also for tool efficiency, grounding, relevance and deterministic business-rule compliance.

This provides the before/after evidence required by the TRACE workflow:

**Trace → Read → Analyze → Codify → Enforce**