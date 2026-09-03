

run_replenishment_recommendation(
    sku,
    requested_planning_week=None
)

def run_replenishment_recommendation(
    sku: str,
    requested_planning_week: str | None = None,
) -> dict:

    # 1. Product
    product = get_product_data(sku)

    # 2. Inventory
    inventory = get_inventory(sku)

    # 3. Forecast
    forecast = get_forecast(sku)

    # 4. Open POs
    open_pos = get_open_pos(sku)

    # 5. Supplier / lead time
    supplier = get_supplier_data(product["supplier_id"])

    # 6. Inventory projection
    projection = calculate_projected_inventory(...)

    # 7. Stockout
    stockout = detect_stockout_exposure(projection)

    # 8. Arrival risk
    arrival = check_replenishment_arrival_risk(
        projection,
        supplier["lead_time_weeks"],
    )

    # 9. Planning point
    planning_point = select_replenishment_planning_point(
        projection_rows=projection,
        lead_time_weeks=supplier["lead_time_weeks"],
        requested_planning_week=requested_planning_week,
    )

    # 10. Forward demand
    forward_demand = calculate_forward_average_demand(...)

    # 11. Target WOS from policy
    ...

    # 12. WOS
    projected_wos = calculate_projected_wos(...)

    # 13. Target inventory
    target = calculate_target_inventory(...)

    # 14. Gap
    gap = calculate_gap_to_target(...)

    # 15. Requirement
    requirement = calculate_replenishment_requirement(...)

    # 16. MOQ / multiple
    ...

    return {
        ...
    }