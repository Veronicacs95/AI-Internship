import os
import json
import psycopg

from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")


QUERY = """
SELECT
    g.case_number,
    g.evaluation_question,
    g.gold_answer,
    g.gold_criteria,
    g.expected_tools,
    g.expected_policy_docs,
    g.priority,

    t.id AS trace_id,
    t.user_input,
    t.retrieved_context,
    t.tool_calls,
    t.assistant_output,
    t.llm_calls,
    t.status,
    t.error_message,

    r.open_coding_notes

FROM agent_traces t

LEFT JOIN golden_cases g
    ON t.user_input = g.evaluation_question

LEFT JOIN trace_reviews r
    ON r.trace_id = t.id

WHERE t.id BETWEEN 29 AND 48

ORDER BY t.id;
"""


output_path = (
    Path(__file__).parent / "traces_after_planning_fix.jsonl"
)

with psycopg.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:
        cur.execute(QUERY)

        columns = [column.name for column in cur.description]
        rows = cur.fetchall()


with output_path.open("w", encoding="utf-8") as file:
    for row in rows:
        record = dict(zip(columns, row))

        file.write(
            json.dumps(
                record,
                default=str,
                ensure_ascii=False
            ) + "\n"
        )


print(f"Exported {len(rows)} traces to {output_path}")