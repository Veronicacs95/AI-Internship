import json
from pathlib import Path
import pytest

# Path to the JSONL dataset exported from PostgreSQL.
TRACE_FILE = Path(__file__).parent / "traces.jsonl"


def load_traces():
    """Load all evaluation traces from the JSONL file."""
    with TRACE_FILE.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def test_success_trace_has_output():
    """
    Failure A: Agent completion / trace status failure.

    A trace marked as successful must contain a final assistant response.
    This catches cases where the agent reaches its iteration limit without
    producing an answer but the trace is incorrectly recorded as successful.
    """
    traces = load_traces()
    failures = []

    for trace in traces:
        if trace.get("status") == "success":
            output = trace.get("assistant_output")

            # A successful run cannot have a missing or empty final answer.
            if output is None or not str(output).strip():
                failures.append(
                    f"case {trace.get('case_number')} "
                    f"trace {trace.get('trace_id')}: "
                    f"status=success but assistant_output is empty"
                )

    # Binary evaluation: PASS if no invalid successful traces are found.
    assert not failures, "\n" + "\n".join(failures)


def test_no_duplicate_tool_calls():
    """
    Failure B: Unnecessary / redundant tool use.

    The agent should not call the same tool more than once with exactly
    the same arguments within a single trace.
    """
    traces = load_traces()
    failures = []

    for trace in traces:
        seen = set()

        for item in trace.get("tool_calls") or []:
            if not isinstance(item, dict):
                continue

            # Support the possible field names used by our trace structure.
            tool_name = (
                item.get("tool")
                or item.get("tool_name")
                or item.get("name")
            )

            arguments = (
                item.get("arguments")
                or item.get("args")
                or item.get("input")
            )

            if not tool_name:
                continue

            # Tool name + arguments uniquely identify an identical tool call.
            key = (
                tool_name,
                json.dumps(arguments, sort_keys=True, default=str)
            )

            if key in seen:
                failures.append(
                    f"case {trace.get('case_number')} "
                    f"trace {trace.get('trace_id')}: "
                    f"duplicate tool call {tool_name}"
                )

            seen.add(key)

    # Binary evaluation: PASS if no duplicate identical tool calls are found.
    assert not failures, "\n" + "\n".join(failures)