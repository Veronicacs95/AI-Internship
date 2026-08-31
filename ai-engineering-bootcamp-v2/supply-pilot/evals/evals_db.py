"""
Database helpers for the SupplyPilot evaluation dashboard.

These functions are NOT tools available to the ADK agent.

They are used by Streamlit to read evaluation results directly
from PostgreSQL and quantify the improvements made during TRACE.

Evaluation flow:

1. Individual trace evaluation
2. Fix 1 - Failure observability
3. Fix 2 - LLM call limit
4. Fix 3 - Planning logic
5. Final regression - baseline vs final 20-trace run
"""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


# --------------------------------------------------
# ENVIRONMENT
# --------------------------------------------------

# Load the .env file located in the same folder as this file.
_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)


# PostgreSQL / Supabase connection string.
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured")


# ==================================================
# 1. INDIVIDUAL TRACE EVALUATION
# ==================================================

def get_trace_evaluation(trace_id: int):
    """
    Return the evaluation and linked Golden Case for one trace.

    This function supports the first Streamlit tab.

    The user selects a trace ID manually and Streamlit displays:

    - PASS / FAIL evaluation dimensions
    - efficiency metrics
    - evaluation notes
    - linked Golden Case

    This is an evaluation/dashboard helper.
    It is NOT exposed as a tool to the SupplyPilot agent.
    """

    # Connect directly to PostgreSQL using the same DATABASE_URL
    # used by the SupplyPilot application.
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:

            # trace_evaluations contains the PASS / FAIL results.
            #
            # trace_reviews provides the relationship between the
            # evaluated trace and its Golden Case.
            #
            # golden_cases contains the validated expected behaviour
            # and reference answer.
            cursor.execute(
                """
                SELECT

                    -- PASS / FAIL evaluation
                    e.trace_id,
                    e.completion_pass,
                    e.answer_correctness_pass,
                    e.tool_selection_pass,
                    e.tool_arguments_pass,
                    e.calculation_correctness_pass,
                    e.constraint_compliance_pass,
                    e.policy_retrieval_pass,
                    e.grounding_pass,
                    e.response_relevance_pass,
                    e.required_fields_pass,

                    -- Efficiency metrics
                    e.duplicate_tool_calls,
                    e.total_tool_calls,
                    e.llm_calls,

                    -- Human evaluation explanation
                    e.evaluation_notes,

                    -- Linked Golden Case
                    g.case_number,
                    g.evaluation_question,
                    g.main_capability,
                    g.expected_tools,
                    g.expected_behavior,
                    g.gold_answer,
                    g.gold_criteria,
                    g.expected_policy_docs,
                    g.gold_source,
                    g.priority,
                    g.gold_status

                FROM trace_evaluations e

                LEFT JOIN trace_reviews r
                    ON r.trace_id = e.trace_id

                LEFT JOIN golden_cases g
                    ON g.id = r.golden_case_id

                WHERE e.trace_id = %s;
                """,
                (trace_id,),
            )

            row = cursor.fetchone()

    # The selected trace does not have an evaluation yet.
    if row is None:
        return None

    # Return a structured object that Streamlit can display directly.
    return {
        "trace_id": row[0],

        "evaluation": {
            "completion_pass": row[1],
            "answer_correctness_pass": row[2],
            "tool_selection_pass": row[3],
            "tool_arguments_pass": row[4],
            "calculation_correctness_pass": row[5],
            "constraint_compliance_pass": row[6],
            "policy_retrieval_pass": row[7],
            "grounding_pass": row[8],
            "response_relevance_pass": row[9],
            "required_fields_pass": row[10],

            "duplicate_tool_calls": row[11],
            "total_tool_calls": row[12],
            "llm_calls": row[13],

            "evaluation_notes": row[14],
        },

        "golden_case": {
            "case_number": row[15],
            "evaluation_question": row[16],
            "main_capability": row[17],
            "expected_tools": row[18],
            "expected_behavior": row[19],
            "gold_answer": row[20],
            "gold_criteria": row[21],
            "expected_policy_docs": row[22],
            "gold_source": row[23],
            "priority": row[24],
            "gold_status": row[25],
        },
    }


# ==================================================
# 2. FIX 1 - FAILURE OBSERVABILITY
# ==================================================

def get_observability_fix_traces():
    """
    Return the before/after traces used to evaluate Fix 1.

    Fix 1 corrected how failed agent executions are stored.

    Trace 20 - BEFORE:
    The agent failed to produce a final answer, but the trace was
    incorrectly stored with status = "success".

    Trace 23 - AFTER:
    The agent still failed because it reached the LLM-call limit,
    but the failure was now correctly stored with:

        status = "failed"
        error_message = populated

    Streamlit can use these traces to quantify:

        Failure-state accuracy
        Before = 0%
        After  = 100%
    """

    # This is evaluation infrastructure and is NOT an agent tool.
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:

            # Retrieve only the execution fields needed to evaluate
            # whether failures were persisted correctly.
            cursor.execute(
                """
                SELECT
                    id,
                    assistant_output,
                    llm_calls,
                    status,
                    error_message
                FROM agent_traces
                WHERE id IN (20, 23)
                ORDER BY id;
                """
            )

            rows = cursor.fetchall()

    results = []

    for row in rows:
        trace = {
            "trace_id": row[0],
            "assistant_output": row[1],
            "llm_calls": row[2],
            "status": row[3],
            "error_message": row[4],
        }

        # Run the deterministic observability check.
        check = check_failure_state(trace)

        trace["observability_pass"] = check["passed"]
        trace["observability_reason"] = check["reason"]

        # Convert PASS / FAIL into a percentage so that
        # Streamlit can quantify the fix directly.
        trace["observability_pass_rate"] = (
            100 if check["passed"] else 0
        )

        results.append(trace)

    return results


def check_failure_state(trace):
    """
    Code-based check for Fix 1.

    If an execution produced no final assistant output,
    it must be recorded as:

        status = "failed"

    and it must contain an error message.

    PASS = failure was persisted correctly
    FAIL = failure was incorrectly persisted
    """

    no_output = not trace["assistant_output"]

    # If there is no final output, the run should explicitly
    # be stored as a failed execution.
    if no_output:

        passed = (
            trace["status"] == "failed"
            and bool(trace["error_message"])
        )

        reason = (
            ""
            if passed
            else (
                "Trace produced no final output but the failure "
                "state was not recorded correctly."
            )
        )

        return {
            "passed": passed,
            "reason": reason,
        }

    # If the run produced a final answer, this particular
    # failure-state check does not detect an observability problem.
    return {
        "passed": True,
        "reason": "",
    }


# ==================================================
# 3. FIX 2 - LLM CALL LIMIT
# ==================================================

def get_llm_limit_fix_traces():
    """
    Return the traces used to evaluate Fix 2.

    Fix 2 increased the maximum number of LLM calls available
    for complex end-to-end planning requests.

    Trace 23:
        8 LLM calls
        FAILED

    Trace 24:
        12 LLM calls
        FAILED

    Trace 25:
        Ceiling increased to 20
        Agent completed in 15 LLM calls
        SUCCESS

    The important metric is COMPLETION PASS RATE.

        Before Fix 2 = 0%
        After Fix 2  = 100%

    The 20-call value is a safety ceiling, not a target.
    """

    # Evaluation/dashboard query only.
    # This is NOT available to the SupplyPilot agent.
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    assistant_output,
                    llm_calls,
                    status,
                    error_message
                FROM agent_traces
                WHERE id IN (23, 24, 25)
                ORDER BY id;
                """
            )

            rows = cursor.fetchall()

    results = []

    for row in rows:

        status = row[3]

        # Completion is a binary evaluation:
        #
        # success = PASS
        # failed  = FAIL
        completion_pass = status == "success"

        results.append(
            {
                "trace_id": row[0],
                "assistant_output": row[1],
                "llm_calls": row[2],
                "status": status,
                "error_message": row[4],

                # Quantified result for Streamlit
                "completion_pass": completion_pass,
                "completion_pass_rate": (
                    100 if completion_pass else 0
                ),
            }
        )

    return results


# ==================================================
# 4. FIX 3 - PLANNING LOGIC
# ==================================================

def get_planning_logic_fix_traces():
    """
    Return traces 25-28 and quantify the planning-logic fix.

    Fix 3 corrected the replenishment planning-point logic.

    Trace 25:
        Agent completed, but mixed planning points and produced
        conflicting replenishment calculations.

    Trace 26:
        Logic improved, but the calculation still used the wrong
        inventory value and returned 120 units.

    Trace 27:
        Final quantity was corrected to 160 units, but planning-point
        selection was still implicit.

    Trace 28:
        The deterministic planning-point selector explicitly selected
        CW and all downstream calculations consistently used CW.

    Planning logic pass rate:

        number of TRUE checks
        --------------------- x 100
        applicable checks

    NULL values are ignored because NULL means that the dimension
    was not applicable.
    """

    # Evaluation/dashboard query only.
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:

            # These five evaluation dimensions are specifically
            # relevant to the planning-logic fix.
            cursor.execute(
                """
                SELECT
                    trace_id,
                    answer_correctness_pass,
                    tool_arguments_pass,
                    calculation_correctness_pass,
                    constraint_compliance_pass,
                    required_fields_pass,
                    evaluation_notes
                FROM trace_evaluations
                WHERE trace_id IN (25, 26, 27, 28)
                ORDER BY trace_id;
                """
            )

            rows = cursor.fetchall()

    results = []

    for row in rows:

        # Collect the five binary planning-related checks.
        checks = [
            row[1],  # answer correctness
            row[2],  # tool arguments
            row[3],  # calculation correctness
            row[4],  # constraint compliance
            row[5],  # required fields
        ]

        # NULL = not applicable.
        # It should therefore not count as PASS or FAIL.
        applicable_checks = [
            value
            for value in checks
            if value is not None
        ]

        # Boolean TRUE counts as one passed check.
        passed_checks = sum(
            value is True
            for value in applicable_checks
        )

        total_checks = len(applicable_checks)

        # Convert the binary evaluation results into a percentage.
        pass_rate = (
            passed_checks / total_checks * 100
            if total_checks > 0
            else 0
        )

        results.append(
            {
                "trace_id": row[0],

                "answer_correctness_pass": row[1],
                "tool_arguments_pass": row[2],
                "calculation_correctness_pass": row[3],
                "constraint_compliance_pass": row[4],
                "required_fields_pass": row[5],

                "evaluation_notes": row[6],

                # Quantified results for Streamlit
                "passed_checks": passed_checks,
                "total_checks": total_checks,
                "planning_pass_rate": pass_rate,
            }
        )

    return results


# ==================================================
# 5. FINAL REGRESSION - ALL FIXES
# ==================================================

def get_regression_comparison():
    """
    Compare the original 20-trace baseline with the final
    20-trace regression run after all three fixes.

    Baseline:
        traces 1-20

    Final regression:
        traces 29-48

    This evaluates the accumulated impact of:

        Fix 1 - failure observability
        Fix 2 - LLM execution limit
        Fix 3 - deterministic planning logic

    Each evaluation dimension contains:

        TRUE  = PASS
        FALSE = FAIL
        NULL  = not applicable

    PostgreSQL AVG ignores NULL values.

    Therefore:

        AVG(boolean::int) * 100

    gives:

        number of PASS
        -------------- x 100
        applicable cases

    Streamlit can use these values to display the percentage-point
    improvement from the baseline to the final regression run.
    """

    # Query the evaluation table directly.
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:

            # Boolean values are cast to integers:
            #
            # TRUE  -> 1
            # FALSE -> 0
            #
            # AVG * 100 therefore produces the PASS percentage.
            cursor.execute(
                """
                SELECT

                    CASE
                        WHEN trace_id BETWEEN 1 AND 20
                            THEN 'Baseline'

                        WHEN trace_id BETWEEN 29 AND 48
                            THEN 'After all fixes'
                    END AS run,

                    -- Number of traces in the run
                    COUNT(*) AS total_traces,

                    -- Evaluation PASS rates
                    AVG(completion_pass::int) * 100,
                    AVG(answer_correctness_pass::int) * 100,
                    AVG(tool_selection_pass::int) * 100,
                    AVG(tool_arguments_pass::int) * 100,
                    AVG(calculation_correctness_pass::int) * 100,
                    AVG(constraint_compliance_pass::int) * 100,
                    AVG(policy_retrieval_pass::int) * 100,
                    AVG(grounding_pass::int) * 100,
                    AVG(response_relevance_pass::int) * 100,
                    AVG(required_fields_pass::int) * 100,

                    -- Efficiency metrics
                    AVG(total_tool_calls),
                    AVG(llm_calls),
                    SUM(duplicate_tool_calls)

                FROM trace_evaluations

                WHERE trace_id BETWEEN 1 AND 20
                   OR trace_id BETWEEN 29 AND 48

                GROUP BY
                    CASE
                        WHEN trace_id BETWEEN 1 AND 20
                            THEN 'Baseline'

                        WHEN trace_id BETWEEN 29 AND 48
                            THEN 'After all fixes'
                    END;
                """
            )

            rows = cursor.fetchall()

    results = {}

    for row in rows:

        total_traces = row[1]

        results[row[0]] = {

            # This allows Streamlit to verify that the comparison
            # really contains the expected 20 traces on each side.
            "total_traces": total_traces,
            "expected_trace_count": 20,
            "complete_run": total_traces == 20,

            # Evaluation percentages
            "completion": (
                float(row[2])
                if row[2] is not None
                else None
            ),

            "answer_correctness": (
                float(row[3])
                if row[3] is not None
                else None
            ),

            "tool_selection": (
                float(row[4])
                if row[4] is not None
                else None
            ),

            "tool_arguments": (
                float(row[5])
                if row[5] is not None
                else None
            ),

            "calculation_correctness": (
                float(row[6])
                if row[6] is not None
                else None
            ),

            "constraint_compliance": (
                float(row[7])
                if row[7] is not None
                else None
            ),

            "policy_retrieval": (
                float(row[8])
                if row[8] is not None
                else None
            ),

            "grounding": (
                float(row[9])
                if row[9] is not None
                else None
            ),

            "response_relevance": (
                float(row[10])
                if row[10] is not None
                else None
            ),

            "required_fields": (
                float(row[11])
                if row[11] is not None
                else None
            ),

            # Efficiency metrics
            "avg_tool_calls": (
                float(row[12])
                if row[12] is not None
                else None
            ),

            "avg_llm_calls": (
                float(row[13])
                if row[13] is not None
                else None
            ),

            "duplicate_tool_calls": int(row[14] or 0),
        }

    return results