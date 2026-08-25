


from datetime import datetime, timedelta


from datetime import datetime, timedelta


def calculate_projected_inventory(
    current_inventory: int,
    forecast_rows: list[dict],
    po_rows: list[dict],
    current_week_start: str, ) -> list[dict]:
    """
    Project available inventory week by week using forecast demand
    and incoming purchase orders.

    Use this tool when you need to know how much inventory is expected
    to remain in CW, CW+1, CW+2, or any future planning week.

    Rules:
    - Start from current available inventory.
    - Use current_week_start as the reference for CW.
    - Derive CW, CW+1, CW+2... from each forecast week_start.
    - Subtract the actual forecast quantity for each week.
    - Add only purchase-order quantities expected to arrive
      during that planning week.
    - Only outstanding PO quantity is treated as incoming supply.
    - Only OPEN or PARTIAL POs are included.
    - Received, cancelled, on-hold, or zero-outstanding POs are excluded.
    - A PO is counted only in the week in which it is expected to arrive.
    - Return the projected inventory for every forecast week.

    Args:
        current_inventory:
            Inventory available at the start of CW.

        forecast_rows:
            Weekly forecast records ordered by week_start.
            Expected format:
            [{
                "week_start": "2026-08-24",
                "forecast_qty": 120
            }, ...]

        po_rows:
            Open purchase-order records.
            Expected format:
            [{
                "expected_arrival_date": "2026-09-14",
                "outstanding_qty": 500,
                "status": "OPEN"
            }, ...]

        current_week_start:
            Monday date representing CW.
            Expected format: "YYYY-MM-DD".
            Example: "2026-08-24".

    Returns:
        A list containing, for each planning week:
        - planning_week: CW, CW+1, CW+2...
        - week_start
        - forecast_qty
        - incoming_supply
        - projected_inventory
    """

    current_week = datetime.strptime(current_week_start, "%Y-%m-%d").date()
    projected_inventory = current_inventory
    projection = []

    for forecast in forecast_rows:
        week_start = datetime.strptime(forecast["week_start"], "%Y-%m-%d").date()
        week_end = week_start + timedelta(days=6)

        weeks_ahead = (week_start - current_week).days // 7
        planning_week = "CW" if weeks_ahead == 0 else f"CW+{weeks_ahead}"

        incoming_supply = sum(
            po["outstanding_qty"]
            for po in po_rows
            if po["status"] in {"OPEN", "PARTIAL"}
            and po["outstanding_qty"] > 0
            and week_start
            <= datetime.strptime(po["expected_arrival_date"], "%Y-%m-%d").date()
            <= week_end
        )

        projected_inventory += incoming_supply - forecast["forecast_qty"]

        projection.append({
            "planning_week": planning_week,
            "week_start": str(week_start),
            "forecast_qty": forecast["forecast_qty"],
            "incoming_supply": incoming_supply,
            "projected_inventory": projected_inventory,
        })

    return projection



def calculate_forward_average_demand(
    forecast_rows: list[dict],
    current_week_start: str,
    planning_week: int = 0,
    window_weeks: int = 5,) -> dict:
    """
    Calculate the forward average weekly demand from a selected planning week.

    Use this tool when you need a stable demand rate for WOS,
    target inventory, or gap-to-target calculations.

    Rules:
    - Use current_week_start as the reference for CW.
    - planning_week=0 means CW.
    - planning_week=1 means CW+1.
    - planning_week=2 means CW+2, and so on.
    - Start from the selected planning week.
    - Average the next window_weeks forecast quantities.
    - Default window is 5 weeks.
    - Do not use this average to project inventory week by week.
      Projected inventory must use the actual forecast for each week.
    - Return the planning week, forecast window, and average demand.

    Args:
        forecast_rows:
            Weekly forecast records ordered by week_start.
            Expected format:
            [{
                "week_start": "2026-08-24",
                "forecast_qty": 120
            }, ...]

        current_week_start:
            Monday date representing CW.
            Expected format: "YYYY-MM-DD".
            Example: "2026-08-24".

        planning_week:
            Number of weeks ahead from CW.
            0 = CW, 1 = CW+1, 2 = CW+2...

        window_weeks:
            Number of forward forecast weeks to average.
            Default = 5.

    Returns:
        A dictionary containing:
        - planning_week
        - start_week
        - end_week
        - weeks_used
        - forecast_values
        - average_weekly_demand
    """

    from datetime import datetime, timedelta

    current_week = datetime.strptime(current_week_start, "%Y-%m-%d").date()
    target_week = current_week + timedelta(weeks=planning_week)

    selected = [
        row for row in forecast_rows
        if datetime.strptime(row["week_start"], "%Y-%m-%d").date() >= target_week
    ][:window_weeks]

    if len(selected) < window_weeks:
        raise ValueError(
            f"Need {window_weeks} forecast weeks from "
            f"{target_week}, but only {len(selected)} are available."
        )

    average = sum(row["forecast_qty"] for row in selected) / window_weeks

    label = "CW" if planning_week == 0 else f"CW+{planning_week}"

    return {
        "planning_week": label,
        "start_week": selected[0]["week_start"],
        "end_week": selected[-1]["week_start"],
        "weeks_used": window_weeks,
        "forecast_values": [row["forecast_qty"] for row in selected],
        "average_weekly_demand": round(average, 2),
    }


def calculate_projected_wos(
    projected_inventory: float,
    forward_average_demand: float,
    planning_week: str,) -> dict:
    """
    Calculate projected Weeks of Supply (WOS) for a selected planning week.

    Use this tool when you need to measure how many weeks of forward
    demand the projected inventory at CW, CW+1, CW+2... can cover.

    Rules:
    - Use projected inventory for the selected planning week.
    - Use the rolling 5-week forward average demand starting from
      the same planning week.
    - Do not use the actual forecast of a single week for WOS.
    - Do not classify the result as healthy, critical, or overstock here.
      Those thresholds come from planning policy.
    - Return the calculated WOS for the selected planning week.

    Args:
        projected_inventory:
            Projected available inventory at the selected planning week.

        forward_average_demand:
            Average weekly demand calculated from the next 5 forecast
            weeks starting from the selected planning week.

        planning_week:
            Planning point being evaluated.
            Expected examples: "CW", "CW+1", "CW+2".

    Returns:
        A dictionary containing:
        - planning_week
        - projected_inventory
        - forward_average_demand
        - projected_wos
    """

    if forward_average_demand <= 0:
        raise ValueError("Forward average demand must be greater than 0.")

    projected_wos = projected_inventory / forward_average_demand

    return {
        "planning_week": planning_week,
        "projected_inventory": projected_inventory,
        "forward_average_demand": forward_average_demand,
        "projected_wos": round(projected_wos, 2),
    }


def calculate_target_inventory(
    forward_average_demand: float,
    target_wos: float,
    planning_week: str,) -> dict:
    """
    Calculate the target inventory quantity for a selected planning week.

    Use this tool when you need to know how many inventory units are
    required to meet NovaTech's planning target at CW, CW+1, CW+2...

    Rules:
    - Use the forward average weekly demand for the selected planning week.
    - Multiply that demand rate by the policy planning target in WOS.
    - The standard NovaTech planning target is currently 5 WOS,
      but this value should be passed into the tool rather than hard-coded.
    - Do not use this tool to decide whether an order should be placed.
      It only converts the WOS target into units.
    - Supplier constraints, incoming POs, and lead time are evaluated separately.

    Args:
        forward_average_demand:
            Rolling forward average weekly demand for the selected planning week.

        target_wos:
            WOS planning target obtained from policy.
            Example: 5.

        planning_week:
            Planning point being evaluated.
            Expected examples: "CW", "CW+1", "CW+2".

    Returns:
        A dictionary containing:
        - planning_week
        - forward_average_demand
        - target_wos
        - target_inventory
    """

    if forward_average_demand < 0:
        raise ValueError("Forward average demand cannot be negative.")

    if target_wos <= 0:
        raise ValueError("Target WOS must be greater than 0.")

    target_inventory = forward_average_demand * target_wos

    return {
        "planning_week": planning_week,
        "forward_average_demand": forward_average_demand,
        "target_wos": target_wos,
        "target_inventory": round(target_inventory, 2),
    }


def calculate_gap_to_target(
    projected_inventory: float,
    target_inventory: float,
    planning_week: str,) -> dict:
    """
    Calculate how many inventory units are below or above target
    for a selected planning week.

    Use this tool when you need to quantify the inventory gap
    at CW, CW+1, CW+2... after projected inventory and target
    inventory have already been calculated.

    Rules:
    - Compare projected inventory with target inventory
      for the same planning week.
    - A negative gap means inventory is below target.
    - A positive gap means inventory is above target.
    - Zero means projected inventory is exactly at target.
    - Return the absolute quantity as well as the signed gap.
    - Do not decide the purchase-order quantity here.
      MOQ, order multiples, incoming supply, and lead time
      are handled separately.

    Args:
        projected_inventory:
            Expected available inventory at the selected planning week.

        target_inventory:
            Inventory units required to meet the policy WOS target
            at the same planning week.

        planning_week:
            Planning point being evaluated.
            Expected examples: "CW", "CW+1", "CW+2".

    Returns:
        A dictionary containing:
        - planning_week
        - projected_inventory
        - target_inventory
        - gap_units
        - difference_units
        - status
    """

    gap = projected_inventory - target_inventory

    return {
        "planning_week": planning_week,
        "projected_inventory": round(projected_inventory, 2),
        "target_inventory": round(target_inventory, 2),
        "gap_units": round(gap, 2),
        "difference_units": round(abs(gap), 2),
        "status": (
            "below_target"
            if gap < 0
            else "above_target"
            if gap > 0
            else "at_target"
        ),
    }

    
def detect_stockout_exposure(
    projection_rows: list[dict],
) -> dict:
    """
    Detect whether projected inventory reaches zero or becomes negative
    in any future planning week.

    Use this tool when you need to identify stockout risk, the first
    stockout week, and how severe the projected inventory gap becomes.

    Rules:
    - Use the week-by-week projected inventory output.
    - Check each planning week in chronological order.
    - A projected inventory of 0 or below is treated as stockout exposure.
    - Return the first week where stockout occurs.
    - Keep the actual projected inventory values so forecast peaks
      and PO timing remain visible.
    - Do not use rolling average demand for this calculation.
    - Do not decide whether to expedite here.
      Expedite decisions must also consider policy, lead time,
      PO timing, and business impact.

    Args:
        projection_rows:
            Output from calculate_projected_inventory().
            Expected format:
            [{
                "planning_week": "CW+2",
                "week_start": "2026-09-07",
                "forecast_qty": 300,
                "incoming_supply": 0,
                "projected_inventory": -50
            }, ...]

    Returns:
        A dictionary containing:
        - stockout_exposure
        - first_stockout_week
        - first_stockout_date
        - first_stockout_inventory
        - lowest_projected_inventory
    """

    stockout_rows = [
        row for row in projection_rows
        if row["projected_inventory"] <= 0
    ]

    if not stockout_rows:
        return {
            "stockout_exposure": False,
            "first_stockout_week": None,
            "first_stockout_date": None,
            "first_stockout_inventory": None,
            "lowest_projected_inventory": min(
                row["projected_inventory"] for row in projection_rows
            ),
        }

    first = stockout_rows[0]

    return {
        "stockout_exposure": True,
        "first_stockout_week": first["planning_week"],
        "first_stockout_date": first["week_start"],
        "first_stockout_inventory": first["projected_inventory"],
        "lowest_projected_inventory": min(
            row["projected_inventory"] for row in projection_rows
        ),
    }

import math


def adjust_order_quantity(
    required_qty: float,
    moq: int,
    order_multiple: int,
    sku: str,) -> dict:
    """
    Convert a replenishment requirement into a valid supplier order quantity.

    Use this tool when you know how many units are required but need to
    respect the SKU's Minimum Order Quantity (MOQ) and order multiple.

    Rules:
    - If required_qty is 0 or below, no order is required.
    - If required_qty is positive but below MOQ, use MOQ.
    - If required_qty is above MOQ, round up to the next valid order multiple.
    - Never round down, because that could leave the replenishment requirement unmet.
    - MOQ and order_multiple must come from product data.
    - This tool validates quantity constraints only.
    - It does not decide whether an order should be placed.
    - Projected inventory, incoming POs, WOS, lead time, and policy
      should already have been considered before calling this tool.

    Args:
        required_qty:
            Number of additional units required.
            Example: 420.

        moq:
            Minimum Order Quantity for the SKU.
            Example: 500.

        order_multiple:
            Valid ordering increment.
            Example: 100.

        sku:
            SKU being evaluated.
            Example: "HPH-501".

    Returns:
        A dictionary containing:
        - sku
        - required_qty
        - moq
        - order_multiple
        - recommended_order_qty
        - adjustment_units
        - order_required
    """

    if moq <= 0 or order_multiple <= 0:
        raise ValueError("MOQ and order multiple must be greater than 0.")

    if required_qty <= 0:
        return {
            "sku": sku,
            "required_qty": round(required_qty, 2),
            "moq": moq,
            "order_multiple": order_multiple,
            "recommended_order_qty": 0,
            "adjustment_units": 0,
            "order_required": False,
        }

    if required_qty <= moq:
        recommended_qty = moq
    else:
        recommended_qty = math.ceil(required_qty / order_multiple) * order_multiple

    return {
        "sku": sku,
        "required_qty": round(required_qty, 2),
        "moq": moq,
        "order_multiple": order_multiple,
        "recommended_order_qty": recommended_qty,
        "adjustment_units": round(recommended_qty - required_qty, 2),
        "order_required": True,
    }

def check_replenishment_arrival_risk(
    projection_rows: list[dict],
    lead_time_weeks: int,
    current_week: str = "CW",) -> dict:
    """
    Check whether a new standard replenishment order would arrive
    before projected inventory reaches zero.

    Use this tool when you need to assess whether normal replenishment
    can arrive in time or whether stockout exposure exists before arrival.

    Rules:
    - Assume a new order is placed in CW.
    - Standard arrival occurs after supplier lead_time_weeks.
    - Use projected inventory week by week.
    - Find the first planning week where projected inventory <= 0.
    - If stockout occurs before the expected standard arrival,
      there is replenishment arrival risk.
    - If no stockout occurs before arrival, standard replenishment
      can arrive before projected stockout.
    - Do not decide whether to expedite here.
      This tool only measures timing risk.
    - Expedite recommendations must also consider policy and business impact.

    Args:
        projection_rows:
            Output from calculate_projected_inventory().
            Expected format:
            [{
                "planning_week": "CW+2",
                "projected_inventory": -50
            }, ...]

        lead_time_weeks:
            Standard supplier lead time in weeks.
            Example: 5.

        current_week:
            Reference planning week.
            Default = "CW".

    Returns:
        A dictionary containing:
        - lead_time_weeks
        - expected_arrival_week
        - stockout_exposure
        - first_stockout_week
        - arrival_risk
        - stockout_gap_weeks
    """

    if lead_time_weeks < 0:
        raise ValueError("Lead time cannot be negative.")

    expected_arrival_week = (
        "CW" if lead_time_weeks == 0 else f"CW+{lead_time_weeks}")

    stockout_rows = [
        row for row in projection_rows
        if row["projected_inventory"] <= 0 ]

    if not stockout_rows:
        return {
            "lead_time_weeks": lead_time_weeks,
            "expected_arrival_week": expected_arrival_week,
            "stockout_exposure": False,
            "first_stockout_week": None,
            "arrival_risk": False,
            "stockout_gap_weeks": 0,
        }

    first_stockout = stockout_rows[0]["planning_week"]

    stockout_week_number = (
        0 if first_stockout == "CW"
        else int(first_stockout.split("+")[1])
    )

    gap = lead_time_weeks - stockout_week_number

    return {
        "lead_time_weeks": lead_time_weeks,
        "expected_arrival_week": expected_arrival_week,
        "stockout_exposure": True,
        "first_stockout_week": first_stockout,
        "arrival_risk": stockout_week_number < lead_time_weeks,
        "stockout_gap_weeks": max(gap, 0),
    }