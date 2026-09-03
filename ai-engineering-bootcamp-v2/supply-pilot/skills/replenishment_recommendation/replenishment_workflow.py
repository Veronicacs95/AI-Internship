
from db_tools import (
    get_inventory,
    get_product_data,
    get_supplier_data,
    get_forecast,
    get_open_pos,
)

from planning_tools import (
    calculate_projected_inventory,
    select_replenishment_planning_point,
    calculate_forward_average_demand,
    calculate_projected_wos,
    calculate_target_inventory,
    calculate_gap_to_target,
    calculate_replenishment_requirement,
    adjust_order_quantity,
    detect_stockout_exposure,
    check_replenishment_arrival_risk,
)

from rag_tools import search_docs


# Gemini
# ↓
# run_replenishment_workflow
#       │
#       ├── get product
#       ├── get inventory
#       ├── get forecast
#       ├── get POs
#       ├── get supplier
#       ├── projection
#       ├── planning point
#       ├── forward demand
#       ├── target
#       ├── WOS
#       ├── gap
#       ├── requirement
#       ├── MOQ
#       ├── stockout
#       └── arrival risk
# ↓
# one structured result
# ↓
# Gemini explains





def run_replenishment_workflow(
    sku: str,
    requested_planning_week: str | None = None,
):
    """
    Run the standard SupplyPilot replenishment recommendation workflow
    for one SKU.

    Use this tool when the user asks whether replenishment should be
    increased, maintained, reduced, or otherwise reviewed.

    Returns a structured replenishment analysis using current database
    data, deterministic planning calculations, supplier constraints,
    and relevant NovaTech policy.
    """

    # ---------------------------------
    # 1. CURRENT BUSINESS DATA
    # ---------------------------------

    product = get_product_data(sku)

    if product is None:
        raise ValueError(f"SKU {sku} was not found.")

    inventory = get_inventory(sku)

    if inventory is None:
        raise ValueError(f"No inventory found for {sku}.")

    forecast = get_forecast(sku)
    open_pos = get_open_pos(sku)

    supplier = get_supplier_data(
        product["supplier_id"]
    )

    # ---------------------------------
    # 2. PROJECT INVENTORY
    # ---------------------------------

    current_week_start = forecast[0]["week_start"]

    projection = calculate_projected_inventory(
        current_inventory=inventory["available_inventory"],
        forecast_rows=forecast,
        po_rows=open_pos,
        current_week_start=current_week_start,
    )

    # ---------------------------------
    # 3. SELECT AUTHORITATIVE
    #    PLANNING POINT
    # ---------------------------------

    planning_point = select_replenishment_planning_point(
        projection_rows=projection,
        lead_time_weeks=supplier["lead_time_weeks"],
        requested_planning_week=requested_planning_week,
    )

    # ---------------------------------
    # 4. FORWARD DEMAND
    # ---------------------------------

    if planning_point["planning_week"] == "CW":
        planning_week_number = 0
    else:
        planning_week_number = int(
            planning_point["planning_week"].split("+")[1]
        )

    forward_demand = calculate_forward_average_demand(
        forecast_rows=forecast,
        current_week_start=current_week_start,
        planning_week=planning_week_number,
        window_weeks=5,
    )

    # ---------------------------------
    # 5. POLICY TARGET
    # ---------------------------------

    policy = search_docs(
        query="standard target WOS replenishment policy"
    )

    # For your current NovaTech policy,
    # the deterministic target is 5 WOS.
    target_wos = 5

    # ---------------------------------
    # 6. WOS + TARGET INVENTORY
    # ---------------------------------

    projected_wos = calculate_projected_wos(
        planning_week=planning_point["planning_week"],
        projected_inventory=planning_point["projected_inventory"],
        forward_average_demand=forward_demand[
            "average_weekly_demand"
        ],
    )

    target_inventory = calculate_target_inventory(
        planning_week=planning_point["planning_week"],
        forward_average_demand=forward_demand[
            "average_weekly_demand"
        ],
        target_wos=target_wos,
    )

    # ---------------------------------
    # 7. GAP
    # ---------------------------------

    gap = calculate_gap_to_target(
        planning_week=planning_point["planning_week"],
        projected_inventory=planning_point[
            "projected_inventory"
        ],
        target_inventory=target_inventory[
            "target_inventory"
        ],
    )

    # ---------------------------------
    # 8. REPLENISHMENT REQUIREMENT
    # ---------------------------------

    requirement = calculate_replenishment_requirement(
        planning_week=planning_point["planning_week"],
        gap_units=gap["gap_units"],
    )

    adjusted_order = adjust_order_quantity(
        sku=sku,
        required_qty=requirement["required_qty"],
        moq=product["moq"],
        order_multiple=product["order_multiple"],
    )

    # ---------------------------------
    # 9. SUPPLY RISK
    # ---------------------------------

    stockout = detect_stockout_exposure(
        projection_rows=projection
    )

    arrival_risk = check_replenishment_arrival_risk(
        projection_rows=projection,
        lead_time_weeks=supplier["lead_time_weeks"],
        current_week="CW",
    )

    # ---------------------------------
    # 10. PRIMARY DECISION
    # ---------------------------------

    if adjusted_order["recommended_order_qty"] > 0:
        decision = "INCREASE"
    else:
        decision = "MAINTAIN"

    # ---------------------------------
    # 11. STRUCTURED RESULT
    # ---------------------------------

    return {
        "sku": sku,

        "decision": decision,

        "recommended_order_qty":
            adjusted_order[
                "recommended_order_qty"
            ],

        "current_inventory":
            inventory["available_inventory"],

        "planning_week":
            planning_point["planning_week"],

        "planning_week_start":
            planning_point["week_start"],

        "projected_inventory":
            planning_point["projected_inventory"],

        "forward_average_demand":
            forward_demand[
                "average_weekly_demand"
            ],

        "projected_wos":
            projected_wos["projected_wos"],

        "target_wos":
            target_wos,

        "target_inventory":
            target_inventory["target_inventory"],

        "gap_to_target":
            gap["gap_units"],

        "initial_replenishment_requirement":
            requirement["required_qty"],

        "moq":
            product["moq"],

        "order_multiple":
            product["order_multiple"],

        "stockout_exposure":
            stockout["stockout_exposure"],

        "first_stockout_week":
            stockout.get(
                "first_stockout_week"
            ),

        "first_stockout_date":
            stockout.get(
                "first_stockout_date"
            ),

        "first_stockout_unmet_demand":
            stockout.get(
                "first_stockout_unmet_demand"
            ),

        "arrival_risk":
            arrival_risk["arrival_risk"],

        "standard_arrival_week":
            arrival_risk[
                "expected_arrival_week"
            ],

        "policy":
            policy,
    }