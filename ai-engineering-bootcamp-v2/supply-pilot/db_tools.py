"""DB Tools for the Agent ."""
import os
import re
import time
from pathlib import Path
from dotenv import load_dotenv
import psycopg

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
