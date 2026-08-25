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
