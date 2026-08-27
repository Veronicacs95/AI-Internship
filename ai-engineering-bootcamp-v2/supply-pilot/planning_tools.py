


from datetime import datetime, timedelta
import math


def calculate_projected_inventory(
    current_inventory: int,
    forecast_rows: list[dict],
    po_rows: list[dict],
    current_week_start: str,
    unmet_demand_carryover_rate: float = 0.0,) -> list[dict]:
    """
    Project physical inventory week by week using forecast demand,
    incoming purchase orders, and an explicit unmet-demand carryover assumption.

    Use this tool when you need to know how much physical inventory is expected
    to remain in CW, CW+1, CW+2, or any future planning week.

    Rules:
    - Physical projected inventory cannot be negative.
    - Start from current available inventory.
    - Use current_week_start as the reference for CW.
    - Derive CW, CW+1, CW+2... from each forecast week_start.
    - Add only outstanding OPEN or PARTIAL purchase orders arriving that week.
    - Base demand is the forecast quantity for the week.
    - If previous demand could not be fulfilled, carry forward the configured
      proportion of that unmet demand.
    - unmet_demand_carryover_rate = 0 means unmet demand is not carried forward.
    - unmet_demand_carryover_rate = 1 means all unmet demand becomes backlog.
    - Values between 0 and 1 represent partial carryover.
    - Unfulfilled demand is reported separately from physical inventory.

    Args:
        current_inventory:
            Physical inventory available at the start of CW.

        forecast_rows:
            Weekly forecast records ordered by week_start.

        po_rows:
            Purchase-order records containing expected arrival date,
            outstanding quantity, and status.

        current_week_start:
            Monday representing CW in YYYY-MM-DD format.

        unmet_demand_carryover_rate:
            Proportion of the previous week's unmet demand that should
            carry into the next week. Must be between 0 and 1.

    Returns:
        A list containing, for each planning week:
        - planning_week
        - week_start
        - forecast_qty
        - carried_unmet_demand
        - effective_demand
        - incoming_supply
        - projected_inventory
        - unmet_demand
    """

    if not 0 <= unmet_demand_carryover_rate <= 1:
        raise ValueError(
            "unmet_demand_carryover_rate must be between 0 and 1."
        )

    current_week = datetime.strptime(
        current_week_start, "%Y-%m-%d"
    ).date()

    projected_inventory = current_inventory
    previous_unmet_demand = 0
    projection = []

    for forecast in forecast_rows:
        week_start = datetime.strptime(
            forecast["week_start"], "%Y-%m-%d" ).date()

        week_end = week_start + timedelta(days=6)

        weeks_ahead = (week_start - current_week).days // 7

        planning_week = (
            "CW" if weeks_ahead == 0 else f"CW+{weeks_ahead}")

        incoming_supply = sum(
            po["outstanding_qty"]
            for po in po_rows
            if po["status"] in {"OPEN", "PARTIAL"}
            and po["outstanding_qty"] > 0
            and week_start
            <= datetime.strptime(
                po["expected_arrival_date"], "%Y-%m-%d"
            ).date()
            <= week_end)

        carried_unmet_demand = (previous_unmet_demand * unmet_demand_carryover_rate)

        effective_demand = (forecast["forecast_qty"] + carried_unmet_demand)

        available_inventory = (projected_inventory + incoming_supply)

        unmet_demand = max(0,effective_demand - available_inventory,)

        projected_inventory = max(0,available_inventory - effective_demand,)

        projection.append(
            {
                "planning_week": planning_week,
                "week_start": str(week_start),
                "forecast_qty": forecast["forecast_qty"],
                "carried_unmet_demand": carried_unmet_demand,
                "effective_demand": effective_demand,
                "incoming_supply": incoming_supply,
                "projected_inventory": projected_inventory,
                "unmet_demand": unmet_demand,
            }
        )

        previous_unmet_demand = unmet_demand

    return projection



def calculate_forward_average_demand(
    forecast_rows: list[dict],
    current_week_start: str,
    planning_week: int = 0,
    window_weeks: int = 5,) -> dict:
    """
    Calculate the forward average weekly demand from a selected planning week.

    Use this tool when a forward demand rate is needed for WOS,
    target inventory, or gap-to-target calculations.

    This calculation requires forecast data only.
    Do not retrieve current inventory, purchase orders, product data,
    supplier data, or policy unless the user's broader question separately
    requires them.

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

    Use this tool to measure how many weeks of forward forecast demand
    the physical projected inventory at CW, CW+1, CW+2... can cover.

    Rules:
    - Use physical projected inventory for the selected planning week.
    - Projected inventory should be non-negative.
    - Use the rolling 5-week forward average demand starting from
      the same planning week.
    - Do not use the actual forecast of a single week for WOS.
    - Do not subtract unmet demand again here. Any unmet-demand carryover
      should already have been reflected upstream in the projected inventory
      calculation.
    - A projected inventory of 0 produces 0 WOS.
    - Do not classify the result as healthy, critical, or overstock here.
      Those thresholds come from NovaTech planning policy.
    - Return the calculated WOS for the selected planning week.

    Args:
        projected_inventory:
            Physical projected inventory at the selected planning week.

        forward_average_demand:
            Average weekly demand calculated from the next 5 forecast
            weeks starting from the same planning week.

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

    if projected_inventory < 0:
        raise ValueError("Projected inventory cannot be negative.")

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
    planning_week: str,
) -> dict:
    """
    Calculate the target inventory quantity for a selected planning week.

    Use this tool to convert a WOS planning target into the inventory
    quantity required at CW, CW+1, CW+2...

    Rules:
    - Use the forward average weekly demand for the selected planning week.
    - Multiply that demand rate by the target WOS provided to the tool.
    - The target WOS must come from retrieved NovaTech policy or an explicit
      user-provided scenario assumption.
    - Do not infer or choose the target WOS inside this tool.
    - Unmet demand and unmet-demand carryover are not inputs to this calculation.
      Their effects are handled separately in projected inventory.
    - Do not use this tool to decide whether an order should be placed.
    - Supplier constraints, incoming POs, lead time, and projected inventory
      are evaluated separately.

    Args:
        forward_average_demand:
            Rolling forward average weekly demand for the selected planning week.

        target_wos:
            WOS target obtained from NovaTech policy or explicitly provided
            by the user for scenario analysis.

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
    planning_week: str,
) -> dict:
    """
    Calculate how many physical inventory units are below or above target
    for a selected planning week.

    Use this tool after projected inventory and target inventory have
    already been calculated for the same planning week.

    Rules:
    - Compare physical projected inventory with target inventory for
      the same planning week.
    - Projected inventory must be non-negative.
    - A negative gap means projected inventory is below target.
    - A positive gap means projected inventory is above target.
    - Zero means projected inventory is exactly at target.
    - Return both the signed gap and its absolute magnitude.
    - Do not add unmet demand to the inventory gap. Unmet demand is a
      separate planning signal produced by the projected inventory calculation.
    - Do not calculate an order quantity here.
    - MOQ, order multiples, incoming supply, lead time, and other
      replenishment constraints are handled separately.

    Args:
        projected_inventory:
            Physical projected inventory at the selected planning week.

        target_inventory:
            Inventory required to meet the selected WOS target at the
            same planning week.

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

    if projected_inventory < 0:
        raise ValueError("Projected inventory cannot be negative.")

    if target_inventory < 0:
        raise ValueError("Target inventory cannot be negative.")

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
    Detect projected stockout exposure using unmet demand.

    Use this tool when you need to identify whether forecast demand cannot
    be fully fulfilled, the first affected planning week, and the severity
    of projected unmet demand.

    Rules:
    - Use the output from calculate_projected_inventory().
    - Physical projected inventory cannot be negative.
    - A week has stockout exposure when unmet_demand > 0.
    - Check planning weeks in chronological order.
    - Return the first week with unmet demand.
    - Use unmet demand to measure shortage severity.
    - Do not use rolling average demand for this calculation.
    - Do not decide whether to expedite here.
      Expedite decisions also require policy, lead time, PO timing,
      and business context.

    Returns:
        A dictionary containing:
        - stockout_exposure
        - first_stockout_week
        - first_stockout_date
        - first_stockout_unmet_demand
        - maximum_unmet_demand
    """

    stockout_rows = [
        row for row in projection_rows
        if row["unmet_demand"] > 0
    ]

    if not stockout_rows:
        return {
            "stockout_exposure": False,
            "first_stockout_week": None,
            "first_stockout_date": None,
            "first_stockout_unmet_demand": 0,
            "maximum_unmet_demand": 0,
        }

    first = stockout_rows[0]

    return {
        "stockout_exposure": True,
        "first_stockout_week": first["planning_week"],
        "first_stockout_date": first["week_start"],
        "first_stockout_unmet_demand": first["unmet_demand"],
        "maximum_unmet_demand": max(
            row["unmet_demand"] for row in projection_rows
        ),
    }


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
    current_week: str = "CW",
) -> dict:
    """
    Check whether a new standard replenishment order would arrive
    before projected unmet demand begins.

    Use this tool when you need to assess whether normal replenishment
    can arrive in time or whether unmet-demand exposure occurs before arrival.

    Rules:
    - Assume a new standard order is placed in CW.
    - Standard arrival occurs after supplier lead_time_weeks.
    - Use the output from calculate_projected_inventory().
    - Physical projected inventory is non-negative.
    - Stockout exposure occurs when unmet_demand > 0.
    - Find the first planning week where unmet demand occurs.
    - If unmet demand occurs before the expected standard arrival,
      there is replenishment arrival risk.
    - If no unmet demand occurs before arrival, standard replenishment
      can arrive without a projected timing gap.
    - Use unmet demand as the shortage signal; do not infer shortage
      severity from negative inventory.
    - Do not decide whether to expedite here.
      This tool only measures timing risk.
    - Expedite recommendations must also consider NovaTech policy,
      business impact, confirmed incoming supply, and other planning evidence.

    Args:
        projection_rows:
            Output from calculate_projected_inventory().

            Expected format:

            [{
                "planning_week": "CW+2",
                "week_start": "2026-09-07",
                "projected_inventory": 0,
                "unmet_demand": 12
            }, ...]

        lead_time_weeks:
            Standard supplier lead time in weeks.

            Example:
                6

        current_week:
            Reference planning week.

            Default:
                "CW"

    Returns:
        A dictionary containing:
        - lead_time_weeks
        - expected_arrival_week
        - stockout_exposure
        - first_stockout_week
        - first_stockout_unmet_demand
        - arrival_risk
        - stockout_gap_weeks
    """

    if lead_time_weeks < 0:
        raise ValueError("Lead time cannot be negative.")

    expected_arrival_week = (
        "CW"
        if lead_time_weeks == 0
        else f"CW+{lead_time_weeks}"
    )

    stockout_rows = [
        row
        for row in projection_rows
        if row["unmet_demand"] > 0
    ]

    if not stockout_rows:
        return {
            "lead_time_weeks": lead_time_weeks,
            "expected_arrival_week": expected_arrival_week,
            "stockout_exposure": False,
            "first_stockout_week": None,
            "first_stockout_unmet_demand": 0,
            "arrival_risk": False,
            "stockout_gap_weeks": 0,
        }

    first_stockout_row = stockout_rows[0]

    first_stockout_week = first_stockout_row["planning_week"]
    first_stockout_unmet_demand = first_stockout_row["unmet_demand"]

    stockout_week_number = (
        0
        if first_stockout_week == "CW"
        else int(first_stockout_week.split("+")[1])
    )

    arrival_risk = stockout_week_number < lead_time_weeks

    gap = lead_time_weeks - stockout_week_number

    return {
        "lead_time_weeks": lead_time_weeks,
        "expected_arrival_week": expected_arrival_week,
        "stockout_exposure": True,
        "first_stockout_week": first_stockout_week,
        "first_stockout_unmet_demand": first_stockout_unmet_demand,
        "arrival_risk": arrival_risk,
        "stockout_gap_weeks": max(gap, 0),
    }


def calculate_replenishment_requirement(
    gap_units: float,
    planning_week: str,
) -> dict:
    """
    Convert an inventory gap-to-target into an initial replenishment requirement.

    Use this tool after calculate_gap_to_target when you need the positive
    quantity required to close a below-target inventory gap.

    Rules:
    - A negative gap means inventory is below target.
    - Convert a negative gap into a positive replenishment requirement.
    - If gap_units is zero or positive, no replenishment requirement is created.
    - This is an initial planning requirement only.
    - Do not apply MOQ or order multiples here.
    - Do not decide whether an order should be placed here.
    - Incoming supply, timing risk, lead time, policy, and supplier constraints
      must be evaluated separately.

    Returns:
        - planning_week
        - gap_units
        - required_qty
        - replenishment_required
    """

    required_qty = max(0, -gap_units)

    return {
        "planning_week": planning_week,
        "gap_units": round(gap_units, 2),
        "required_qty": round(required_qty, 2),
        "replenishment_required": required_qty > 0,
    }