"""DB Tools for the Agent ."""
import os
import re
import time
from pathlib import Path
from dotenv import load_dotenv
import psycopg
import json


_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)


DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured")



def get_inventory(sku: str):
    """
    Get the current available inventory for one SKU.

    Use this tool when the user asks how many units are currently in stock
    or when current inventory is required for a supply-planning analysis.

    Args:
        sku: The exact NovaTech product SKU.

    Returns:
        The SKU, available inventory quantity, and inventory snapshot date.
        Returns None if the SKU has no inventory record.
    """
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT sku, available_inventory, snapshot_date
                FROM inventory
                WHERE sku = %s;
                """,
                (sku,),)

            row = cursor.fetchone()

    if row is None:
        return None

    return {
        "sku": row[0],
        "available_inventory": row[1],
        "snapshot_date": str(row[2]),  }



def get_product_data(sku: str):
    """
    Get master data and ordering constraints for one product.

    Use this tool when product identity, category, supplier, unit cost,
    minimum order quantity (MOQ), order multiple, or active status is needed.

    Args:
        sku: The exact NovaTech product SKU.

    Returns:
        Product name, category, supplier ID, unit cost, MOQ, order multiple,
        and active status. Returns None if the SKU is not found.
    """
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    sku,product_name,category,supplier_id,unit_cost,moq,order_multiple,active
                FROM products
                WHERE sku = %s;
                """,
                (sku,), )
            row = cursor.fetchone()

    if row is None:
        return None

    return {
        "sku": row[0],
        "product_name": row[1],
        "category": row[2],
        "supplier_id": row[3],
        "unit_cost": float(row[4]),
        "moq": row[5],
        "order_multiple": row[6],
        "active": row[7],
    }


def get_supplier_data(supplier_id: str):
    """
    Get supplier information and standard lead time for one supplier.

    Use this tool when supplier identity, country, active status, or lead time
    is required. If only a SKU is known, first use get_product_data to obtain
    its supplier_id.

    Args:
        supplier_id: The exact NovaTech supplier ID.

    Returns:
        Supplier ID, supplier name, lead time in weeks, country,
        and active status. Returns None if the supplier is not found.
    """
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    supplier_id,supplier_name,lead_time_weeks,country,active
                FROM suppliers
                WHERE supplier_id = %s;
                """,
                (supplier_id,),)
            row = cursor.fetchone()

    if row is None:
        return None

    return {
        "supplier_id": row[0],
        "supplier_name": row[1],
        "lead_time_weeks": row[2],
        "country": row[3],
        "active": row[4],
    }


def get_forecast(sku: str):
    """
    Get the weekly demand forecast for one SKU.

    Use this tool when future expected demand is required for supply planning,
    replenishment analysis, projected inventory, or forward-looking WOS calculations.

    Args:
        sku: The exact NovaTech product SKU.

    Returns:
        A chronological list of weeks and forecast quantities.
        Returns an empty list if no forecast records are found.
    """
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT week_start, forecast_qty
                FROM forecast
                WHERE sku = %s
                ORDER BY week_start;
                """,
                (sku,),
            )
            rows = cursor.fetchall()

    return [
        {
            "week_start": str(row[0]),
            "forecast_qty": row[1],
        }
        for row in rows ]


def get_sales_history(sku: str):
    """
    Get historical weekly sales for one SKU.

    Use this tool when actual historical demand or sales trends are needed.
    Do not use it as a substitute for forecast data when the analysis
    specifically requires future expected demand.

    Args:
        sku: The exact NovaTech product SKU.

    Returns:
        A chronological list of weeks and actual sales quantities.
        Returns an empty list if no sales records are found.
    """
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT week_start, sales_qty
                FROM sales
                WHERE sku = %s
                ORDER BY week_start;
                """,
                (sku,),
            )
            rows = cursor.fetchall()

    return [
        {
            "week_start": str(row[0]),
            "sales_qty": row[1],
        }
        for row in rows ]


def get_open_pos(sku: str):
    """
    Get all outstanding purchase orders representing incoming supply for one SKU.

    Use this tool when the user asks about open POs, incoming supply,
    outstanding quantities, or expected arrival dates.

    This tool already returns PO number, supplier ID, ordered quantity,
    outstanding quantity, order date, expected arrival date, and status.

    Do not call product or supplier tools afterward unless the user explicitly
    needs additional product details, supplier details, or supplier lead time.

    Args:
        sku: The exact NovaTech product SKU.

    Returns:
        A chronological list of open or partially open purchase orders with
        outstanding quantity greater than zero.
    """
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    po_number,supplier_id,ordered_qty,outstanding_qty,order_date,expected_arrival_date,status
                FROM purchase_orders
                WHERE sku = %s
                  AND outstanding_qty > 0
                  AND status IN ('OPEN', 'PARTIAL')
                ORDER BY expected_arrival_date;
                """,
                (sku,),
            )
            rows = cursor.fetchall()

    return [
        {
            "po_number": row[0],
            "supplier_id": row[1],
            "ordered_qty": row[2],
            "outstanding_qty": row[3],
            "order_date": str(row[4]),
            "expected_arrival_date": str(row[5]),
            "status": row[6],
        }
        for row in rows ]



def get_latest_recommendation(sku: str):
    """
    Get the latest validated replenishment recommendation for one SKU.

    Use this tool when the user asks what SupplyPilot previously recommended
    for a SKU, such as:
    - "What was the last recommendation for CAB-604?"
    - "What did we decide last time for LAP-101?"
    - "Show me the latest replenishment recommendation for this SKU."

    Returns:
        The latest validated recommendation memory row for the SKU.
        Returns None if no validated recommendation exists.
    """

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    sku,
                    trace_id,
                    decision,
                    recommended_order_qty,
                    decision_date,
                    current_week,
                    planning_week,
                    planning_week_start,
                    available_inventory_cw,
                    projected_inventory_planning_week,
                    forward_average_demand,
                    projected_wos,
                    target_wos,
                    target_inventory,
                    gap_to_target,
                    initial_replenishment_requirement,
                    moq,
                    order_multiple,
                    stockout_exposure,
                    first_stockout_week,
                    first_stockout_date,
                    first_stockout_unmet_demand,
                    standard_arrival_week,
                    arrival_risk,
                    stockout_gap_weeks,
                    policy_ids,
                    reason_summary,
                    source,
                    trust_level,
                    created_at
                FROM recommendation_memory
                WHERE sku = %s
                  AND trust_level = 'validated'
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (sku,),
            )

            row = cursor.fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "sku": row[1],
        "trace_id": row[2],
        "decision": row[3],
        "recommended_order_qty": row[4],
        "decision_date": str(row[5]) if row[5] else None,
        "current_week": row[6],
        "planning_week": row[7],
        "planning_week_start": str(row[8]) if row[8] else None,
        "available_inventory_cw": row[9],
        "projected_inventory_planning_week": float(row[10]) if row[10] is not None else None,
        "forward_average_demand": float(row[11]) if row[11] is not None else None,
        "projected_wos": float(row[12]) if row[12] is not None else None,
        "target_wos": float(row[13]) if row[13] is not None else None,
        "target_inventory": float(row[14]) if row[14] is not None else None,
        "gap_to_target": float(row[15]) if row[15] is not None else None,
        "initial_replenishment_requirement": float(row[16]) if row[16] is not None else None,
        "moq": row[17],
        "order_multiple": row[18],
        "stockout_exposure": row[19],
        "first_stockout_week": row[20],
        "first_stockout_date": str(row[21]) if row[21] else None,
        "first_stockout_unmet_demand": float(row[22]) if row[22] is not None else None,
        "standard_arrival_week": row[23],
        "arrival_risk": row[24],
        "stockout_gap_weeks": row[25],
        "policy_ids": row[26],
        "reason_summary": row[27],
        "source": row[28],
        "trust_level": row[29],
        "created_at": str(row[30]) if row[30] else None,
    }




# -------------------------------


def save_agent_trace(trace: dict) -> int:
    """
    Persist one complete SupplyPilot execution trace.

    This is application infrastructure, not an agent-facing tool.

    Returns:
        The database ID of the newly created agent trace.
    """

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO agent_traces (
                    user_input,
                    retrieved_context,
                    tool_calls,
                    assistant_output,
                    llm_calls,
                    status,
                    error_message
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    trace.get("user_input"),
                    json.dumps(
                        trace.get("retrieved_context", []),
                        default=str
                    ),
                    json.dumps(
                        trace.get("tool_calls", []),
                        default=str
                    ),
                    trace.get("assistant_output"),
                    trace.get("llm_calls", 0),
                    trace.get("status"),
                    trace.get("error_message"),
                ),
            )

            trace_id = cursor.fetchone()[0]

        conn.commit()

    return trace_id








def save_recommendation_memory(
    memory: dict,
    trace_id: int | None = None
) -> int:
    """
    Save one validated replenishment recommendation as episodic memory.

    This function must only be called after the recommendation
    passes the application's write gate.

    Returns:
        The ID of the created recommendation memory row.
    """

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO recommendation_memory (
                    sku,
                    trace_id,
                    decision,
                    recommended_order_qty,
                    decision_date,
                    current_week,
                    planning_week,
                    planning_week_start,
                    available_inventory_cw,
                    projected_inventory_planning_week,
                    forward_average_demand,
                    projected_wos,
                    target_wos,
                    target_inventory,
                    gap_to_target,
                    initial_replenishment_requirement,
                    moq,
                    order_multiple,
                    stockout_exposure,
                    first_stockout_week,
                    first_stockout_date,
                    first_stockout_unmet_demand,
                    standard_arrival_week,
                    arrival_risk,
                    stockout_gap_weeks,
                    policy_ids,
                    reason_summary,
                    source,
                    trust_level
                )
                VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s::jsonb, %s,
                    %s, %s
                )
                RETURNING id;
                """,
                (
                    memory["sku"],
                    trace_id,
                    memory["decision"],
                    memory.get("recommended_order_qty", 0),
                    memory.get("decision_date"),
                    memory["current_week"],
                    memory["planning_week"],
                    memory.get("planning_week_start"),
                    memory.get("available_inventory_cw"),
                    memory.get("projected_inventory_planning_week"),
                    memory.get("forward_average_demand"),
                    memory.get("projected_wos"),
                    memory.get("target_wos"),
                    memory.get("target_inventory"),
                    memory.get("gap_to_target"),
                    memory.get("initial_replenishment_requirement"),
                    memory.get("moq"),
                    memory.get("order_multiple"),
                    memory.get("stockout_exposure", False),
                    memory.get("first_stockout_week"),
                    memory.get("first_stockout_date"),
                    memory.get("first_stockout_unmet_demand"),
                    memory.get("standard_arrival_week"),
                    memory.get("arrival_risk", False),
                    memory.get("stockout_gap_weeks"),
                    json.dumps(memory.get("policy_ids", [])),
                    memory.get("reason_summary"),
                    "supplypilot_replenishment_skill",
                    "validated",
                ),
            )

            memory_id = cursor.fetchone()[0]

        conn.commit()

    return memory_id