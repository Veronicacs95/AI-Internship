"""
SupplyPilot TRACE Evaluation Dashboard

This Streamlit app displays evaluation results stored in PostgreSQL.

Tabs:
1. Individual trace evaluator
2. Fix 1 - Failure observability
3. Fix 2 - LLM call limit
4. Fix 3 - Planning logic
5. Final regression - baseline vs after all fixes


"""

# SUPPLY-PILOT
# │
# ├── main.py
# │   └── FastAPI → SupplyPilot agent API
# │
# ├── agent.py
# ├── db_tools.py
# ├── planning_tools.py
# ├── rag_tools.py
# │
# └── evals/
#     ├── evals_db.py
#     │   └── Python functions → PostgreSQL
#     │
#     └── streamlit_app.py
#         └── Streamlit evaluation dashboard

import streamlit as st

from evals_db import (
    get_trace_evaluation,
    get_observability_fix_traces,
    get_llm_limit_fix_traces,
    get_planning_logic_fix_traces,
    get_regression_comparison,
)


# ==================================================
# PAGE CONFIGURATION
# ==================================================

st.set_page_config(
    page_title="SupplyPilot TRACE Evaluation",
    layout="wide",
)

st.title("SupplyPilot TRACE Evaluation Dashboard")

st.caption(
    "Evaluate individual traces and quantify improvements "
    "across the three fixes."
)


# ==================================================
# HELPER FUNCTIONS
# ==================================================

def show_pass_fail(label, value):
    """
    Display one evaluation dimension.

    TRUE  -> PASS
    FALSE -> FAIL
    NULL  -> N/A
    """

    if value is True:
        st.success(f"PASS - {label}")

    elif value is False:
        st.error(f"FAIL - {label}")

    else:
        st.info(f"N/A - {label}")


def format_percentage(value):
    """
    Safely format percentage values returned from PostgreSQL.
    """

    if value is None:
        return "N/A"

    return f"{value:.1f}%"


# ==================================================
# TABS
# ==================================================

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "Trace Evaluator",
        "Fix 1 - Observability",
        "Fix 2 - LLM Limit",
        "Fix 3 - Planning Logic",
        "Final Regression",
    ]
)


# ==================================================
# TAB 1 - INDIVIDUAL TRACE EVALUATOR
# ==================================================

with tab1:

    st.header("Individual Trace Evaluator")

    st.write(
        "Enter any evaluated trace ID to inspect its PASS / FAIL "
        "results and linked Golden Case."
    )

    trace_id = st.number_input(
        "Trace ID",
        min_value=1,
        step=1,
        value=1,
    )

    if st.button("Load Trace Evaluation"):

        result = get_trace_evaluation(int(trace_id))

        if result is None:

            st.warning(
                f"Trace {trace_id} does not have an evaluation record."
            )

        else:

            evaluation = result["evaluation"]
            golden = result["golden_case"]

            st.subheader(f"Trace {result['trace_id']}")

            # ------------------------------------------
            # PASS / FAIL CHECKS
            # ------------------------------------------

            st.markdown("### Evaluation Checks")

            col1, col2 = st.columns(2)

            with col1:

                show_pass_fail(
                    "Completion",
                    evaluation["completion_pass"],
                )

                show_pass_fail(
                    "Answer Correctness",
                    evaluation["answer_correctness_pass"],
                )

                show_pass_fail(
                    "Tool Selection",
                    evaluation["tool_selection_pass"],
                )

                show_pass_fail(
                    "Tool Arguments",
                    evaluation["tool_arguments_pass"],
                )

                show_pass_fail(
                    "Calculation Correctness",
                    evaluation["calculation_correctness_pass"],
                )

            with col2:

                show_pass_fail(
                    "Constraint Compliance",
                    evaluation["constraint_compliance_pass"],
                )

                show_pass_fail(
                    "Policy Retrieval",
                    evaluation["policy_retrieval_pass"],
                )

                show_pass_fail(
                    "Grounding",
                    evaluation["grounding_pass"],
                )

                show_pass_fail(
                    "Response Relevance",
                    evaluation["response_relevance_pass"],
                )

                show_pass_fail(
                    "Required Fields",
                    evaluation["required_fields_pass"],
                )

            # ------------------------------------------
            # EFFICIENCY
            # ------------------------------------------

            st.markdown("### Efficiency")

            metric1, metric2, metric3 = st.columns(3)

            metric1.metric(
                "Total Tool Calls",
                evaluation["total_tool_calls"],
            )

            metric2.metric(
                "LLM Calls",
                evaluation["llm_calls"],
            )

            metric3.metric(
                "Duplicate Tool Calls",
                evaluation["duplicate_tool_calls"],
            )

            # ------------------------------------------
            # NOTES
            # ------------------------------------------

            st.markdown("### Evaluation Notes")

            st.write(
                evaluation["evaluation_notes"]
                or "No evaluation notes recorded."
            )

            # ------------------------------------------
            # GOLDEN CASE
            # ------------------------------------------

            st.markdown("### Golden Case")

            if golden["case_number"] is None:

                st.info(
                    "This trace is not currently linked to a Golden Case."
                )

            else:

                st.write(
                    "**Case number:**",
                    golden["case_number"],
                )

                st.write(
                    "**Question:**",
                    golden["evaluation_question"],
                )

                st.write(
                    "**Main capability:**",
                    golden["main_capability"],
                )

                st.write(
                    "**Expected tools:**",
                    golden["expected_tools"],
                )

                st.write(
                    "**Expected behaviour:**",
                    golden["expected_behavior"],
                )

                st.write(
                    "**Gold answer:**",
                    golden["gold_answer"],
                )

                st.write(
                    "**Gold criteria:**",
                    golden["gold_criteria"],
                )

                st.write(
                    "**Expected policy docs:**",
                    golden["expected_policy_docs"],
                )


# ==================================================
# TAB 2 - FIX 1
# FAILURE OBSERVABILITY
# ==================================================

with tab2:

    st.header("Fix 1 - Failure Observability")

    st.write(
        "This fix corrected how failed agent executions "
        "are persisted in the trace database."
    )

    traces = get_observability_fix_traces()

    if len(traces) < 2:

        st.warning(
            "Expected traces 20 and 23 were not found."
        )

    else:

        before = traces[0]
        after = traces[1]

        col1, col2 = st.columns(2)

        # ------------------------------------------
        # BEFORE
        # ------------------------------------------

        with col1:

            st.subheader("Before - Trace 20")

            st.write(
                "**Status:**",
                before["status"],
            )

            st.write(
                "**LLM calls:**",
                before["llm_calls"],
            )

            st.write(
                "**Assistant output:**",
                before["assistant_output"],
            )

            st.write(
                "**Error message:**",
                before["error_message"],
            )

            if before["observability_pass"]:
                st.success("PASS")
            else:
                st.error("FAIL")

            if before["observability_reason"]:
                st.caption(
                    before["observability_reason"]
                )

        # ------------------------------------------
        # AFTER
        # ------------------------------------------

        with col2:

            st.subheader("After - Trace 23")

            st.write(
                "**Status:**",
                after["status"],
            )

            st.write(
                "**LLM calls:**",
                after["llm_calls"],
            )

            st.write(
                "**Assistant output:**",
                after["assistant_output"],
            )

            st.write(
                "**Error message:**",
                after["error_message"],
            )

            if after["observability_pass"]:
                st.success("PASS")
            else:
                st.error("FAIL")

            if after["observability_reason"]:
                st.caption(
                    after["observability_reason"]
                )

        # ------------------------------------------
        # METRIC MOVEMENT
        # ------------------------------------------

        st.divider()

        st.subheader("Metric Movement")

        before_rate = before["observability_pass_rate"]
        after_rate = after["observability_pass_rate"]

        improvement = after_rate - before_rate

        metric1, metric2, metric3 = st.columns(3)

        metric1.metric(
            "Before",
            f"{before_rate:.0f}% PASS",
        )

        metric2.metric(
            "After",
            f"{after_rate:.0f}% PASS",
        )

        metric3.metric(
            "Improvement",
            f"{improvement:+.0f} pp",
        )


# ==================================================
# TAB 3 - FIX 2
# LLM CALL LIMIT
# ==================================================

with tab3:

    st.header("Fix 2 - LLM Call Limit")

    st.write(
        "The LLM-call safety ceiling was increased so that "
        "complex end-to-end planning requests had enough "
        "iterations to complete."
    )

    traces = get_llm_limit_fix_traces()

    if len(traces) < 3:

        st.warning(
            "Expected traces 23, 24 and 25 were not found."
        )

    else:

        columns = st.columns(3)

        for column, trace in zip(columns, traces):

            with column:

                st.subheader(
                    f"Trace {trace['trace_id']}"
                )

                st.metric(
                    "LLM Calls",
                    trace["llm_calls"],
                )

                st.write(
                    "**Status:**",
                    trace["status"],
                )

                if trace["completion_pass"]:

                    st.success(
                        "PASS - Agent completed"
                    )

                else:

                    st.error(
                        "FAIL - Agent did not complete"
                    )

                if trace["error_message"]:

                    st.caption(
                        trace["error_message"]
                    )

        # ------------------------------------------
        # BEFORE / AFTER MOVEMENT
        # ------------------------------------------

        before = traces[0]   # Trace 23
        after = traces[-1]   # Trace 25

        before_rate = before["completion_pass_rate"]
        after_rate = after["completion_pass_rate"]

        improvement = after_rate - before_rate

        st.divider()

        st.subheader("Metric Movement")

        metric1, metric2, metric3 = st.columns(3)

        metric1.metric(
            "Before - Trace 23",
            f"{before_rate:.0f}% PASS",
        )

        metric2.metric(
            "After - Trace 25",
            f"{after_rate:.0f}% PASS",
        )

        metric3.metric(
            "Improvement",
            f"{improvement:+.0f} pp",
        )

        st.caption(
            "The ceiling was increased to 20 calls. "
            "Trace 25 completed in 15 calls."
        )


# ==================================================
# TAB 4 - FIX 3
# PLANNING LOGIC
# ==================================================

with tab4:

    st.header("Fix 3 - Planning Logic")

    st.write(
        "This fix introduced deterministic planning-point "
        "selection so that all replenishment calculations use "
        "the same planning week."
    )

    traces = get_planning_logic_fix_traces()

    if len(traces) < 4:

        st.warning(
            "Expected traces 25, 26, 27 and 28 were not found."
        )

    else:

        columns = st.columns(4)

        for column, trace in zip(columns, traces):

            with column:

                st.subheader(
                    f"Trace {trace['trace_id']}"
                )

                st.metric(
                    "Planning Pass Rate",
                    f"{trace['planning_pass_rate']:.0f}%",
                )

                st.write(
                    f"{trace['passed_checks']} / "
                    f"{trace['total_checks']} checks passed"
                )

                if trace["planning_pass_rate"] == 100:

                    st.success(
                        "PASS - Planning logic correct"
                    )

                else:

                    st.error(
                        "FAIL - Planning logic still incomplete"
                    )

                if trace["evaluation_notes"]:

                    st.caption(
                        trace["evaluation_notes"]
                    )

        # ------------------------------------------
        # BEFORE / AFTER MOVEMENT
        # ------------------------------------------

        before = traces[0]   # Trace 25
        after = traces[-1]   # Trace 28

        before_rate = before["planning_pass_rate"]
        after_rate = after["planning_pass_rate"]

        improvement = after_rate - before_rate

        st.divider()

        st.subheader("Metric Movement")

        metric1, metric2, metric3 = st.columns(3)

        metric1.metric(
            "Before - Trace 25",
            f"{before_rate:.0f}%",
        )

        metric2.metric(
            "After - Trace 28",
            f"{after_rate:.0f}%",
        )

        metric3.metric(
            "Improvement",
            f"{improvement:+.0f} pp",
        )


# ==================================================
# TAB 5 - FINAL REGRESSION
# TRACES 1-20 VS 29-48
# ==================================================

with tab5:

    st.header("Final Regression - All Fixes")

    st.write(
        "Compare the original 20-trace baseline with the "
        "same 20 Golden cases rerun after all three fixes."
    )

    data = get_regression_comparison()

    if (
        "Baseline" not in data
        or "After all fixes" not in data
    ):

        st.warning(
            "Baseline or final regression data is missing."
        )

    else:

        baseline = data["Baseline"]
        final = data["After all fixes"]

        # ------------------------------------------
        # DATASET SIZE VALIDATION
        # ------------------------------------------

        st.subheader("Regression Set")

        count1, count2 = st.columns(2)

        count1.metric(
            "Baseline Traces",
            f"{baseline['total_traces']} / 20",
        )

        count2.metric(
            "Final Traces",
            f"{final['total_traces']} / 20",
        )

        if (
            baseline["complete_run"]
            and final["complete_run"]
        ):

            st.success(
                "Complete comparison: 20 baseline traces "
                "vs 20 final traces."
            )

        else:

            st.warning(
                "One of the regression runs does not contain "
                "all 20 expected traces."
            )

        # ------------------------------------------
        # PASS RATE COMPARISON
        # ------------------------------------------

        st.divider()

        st.subheader("Evaluation Pass Rates")

        metrics = [
            ("Completion", "completion"),
            (
                "Answer Correctness",
                "answer_correctness",
            ),
            (
                "Tool Selection",
                "tool_selection",
            ),
            (
                "Tool Arguments",
                "tool_arguments",
            ),
            (
                "Calculation Correctness",
                "calculation_correctness",
            ),
            (
                "Constraint Compliance",
                "constraint_compliance",
            ),
            (
                "Policy Retrieval",
                "policy_retrieval",
            ),
            (
                "Grounding",
                "grounding",
            ),
            (
                "Response Relevance",
                "response_relevance",
            ),
            (
                "Required Fields",
                "required_fields",
            ),
        ]

        for label, key in metrics:

            before = baseline[key]
            after = final[key]

            col1, col2, col3 = st.columns(3)

            col1.metric(
                f"{label} - Baseline",
                format_percentage(before),
            )

            col2.metric(
                f"{label} - After",
                format_percentage(after),
            )

            # Only calculate movement when both values exist.
            if before is not None and after is not None:

                difference = after - before

                col3.metric(
                    "Change",
                    f"{difference:+.1f} pp",
                )

            else:

                col3.metric(
                    "Change",
                    "N/A",
                )

        # ------------------------------------------
        # EFFICIENCY
        # ------------------------------------------

        st.divider()

        st.subheader("Efficiency Comparison")

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Average Tool Calls",
            f"{final['avg_tool_calls']:.1f}",
            (
                f"{final['avg_tool_calls'] - baseline['avg_tool_calls']:+.1f}"
            ),
        )

        col2.metric(
            "Average LLM Calls",
            f"{final['avg_llm_calls']:.1f}",
            (
                f"{final['avg_llm_calls'] - baseline['avg_llm_calls']:+.1f}"
            ),
        )

        duplicate_difference = (
            final["duplicate_tool_calls"]
            - baseline["duplicate_tool_calls"]
        )

        col3.metric(
            "Duplicate Tool Calls",
            final["duplicate_tool_calls"],
            f"{duplicate_difference:+d}",
        )

        st.caption(
            "Pass-rate changes are shown in percentage points. "
            "Efficiency metrics are shown separately because they "
            "are counts rather than PASS / FAIL evaluations."
        )