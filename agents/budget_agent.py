from planning_rules import MAX_REVISIONS, category_budget
from state import TravelState, make_initial_state

LOCAL_TRANSPORT_PER_PERSON_PER_DAY_USD = 10.0
CAPPED_CATEGORIES = {
    "hotel": "hotel",
    "activities": "activities",
    "food": "food",
    "local_transport": "transport_buffer",
}

ADJUSTABLE_CATEGORIES = ("hotel", "activities", "food")


def _actual_costs(state: TravelState) -> tuple[dict[str, float | None], list[str]]:
    warnings: list[str] = []
    flights = state.get("flight_options", {}).get("total_usd")
    hotel = state.get("selected_hotel", {}).get("total_stay_cost_usd")

    days = state.get("itinerary", {}).get("days", [])
    activities = food = None
    if days and state.get("activities"):
        activities = sum(a["total_cost_usd"] for day in days for a in day["activities"])
    if days and state.get("restaurants"):
        meals = [meal for day in days for meal in day["meals"]]
        food = sum(meal["cost_for_group_usd"] for meal in meals)
        empty_meals = sum(1 for meal in meals if meal["restaurant"] is None)
        if empty_meals:
            warnings.append(f"{empty_meals} meal(s) have no restaurant, so food cost is too low")

    transport = LOCAL_TRANSPORT_PER_PERSON_PER_DAY_USD * state["travelers"] * state["duration"]
    costs = {
        "flights": flights,
        "hotel": hotel,
        "activities": activities,
        "food": food,
        "local_transport": transport,
    }
    return costs, warnings


def _revision_notes(rows: list[dict], over_by: float) -> str:
    over_cap = sorted(
        (row for row in rows
         if row["category"] in ADJUSTABLE_CATEGORIES and row["over_cap_usd"] > 0),
        key=lambda row: row["over_cap_usd"],
        reverse=True,
    )
    if not over_cap:
        return f"The trip is ${over_by:.0f} over budget. Choose cheaper options in every category."
    return " ".join(
        f"{row['category']} costs ${row['actual_usd']:.0f}, over its ${row['cap_usd']:.0f} cap "
        f"by ${row['over_cap_usd']:.0f}: choose cheaper {row['category']} options."
        for row in over_cap
    )

def _next_cuts(state: TravelState, rows: list[dict]) -> dict[str, int]:
    cuts = dict(state.get("category_cuts", {}))
    over_cap = [
        row["category"] for row in rows
        if row["category"] in ADJUSTABLE_CATEGORIES and row["over_cap_usd"] > 0
    ]
    for category in over_cap or ADJUSTABLE_CATEGORIES:
        cuts[category] = cuts.get(category, 0) + 1
    return cuts


def budget_agent(state: TravelState) -> dict:
    errors: list[str] = []
    budget = state["budget"]
    revision_count = state.get("revision_count", 0)
    costs, warnings = _actual_costs(state)

    missing = [name for name, value in costs.items() if value is None]
    known_total = round(sum(value for value in costs.values() if value is not None), 2)

    rows: list[dict] = []
    for name, value in costs.items():
        cap = category_budget(state, CAPPED_CATEGORIES[name]) if name in CAPPED_CATEGORIES else None
        actual = round(value, 2) if value is not None else None
        over_cap = round(max(actual - cap, 0.0), 2) if actual is not None and cap is not None else 0.0
        rows.append({"category": name, "actual_usd": actual, "cap_usd": cap, "over_cap_usd": over_cap})

    over_by = round(max(known_total - budget, 0.0), 2)
    update: dict = {}
    if missing:
        status = "incomplete"
        errors.append(f"budget_agent: missing costs for {', '.join(missing)}, budget check is incomplete")
    elif known_total <= budget:
        status = "within_budget"
    elif revision_count < MAX_REVISIONS:
        status = "needs_revision"
        update = {
            "revision_count": revision_count + 1,
            "revision_notes": _revision_notes(rows, over_by),
            "category_cuts": _next_cuts(state, rows),
        }
    else:
        status = "over_budget_final"

    budget_analysis = {
        "status": status,
        "needs_revision": status == "needs_revision",
        "budget_usd": budget,
        "total_usd": known_total,
        "over_by_usd": None if missing else over_by,
        "remaining_usd": None if missing else round(max(budget - known_total, 0.0), 2),
        "total_is_partial": bool(missing),
        "breakdown": rows,
        "missing_costs": missing,
        "warnings": warnings,
        "revision_count": revision_count,
        "max_revisions": MAX_REVISIONS,
        "local_transport_basis": (
            f"hardcoded estimate: ${LOCAL_TRANSPORT_PER_PERSON_PER_DAY_USD:.0f} per person per day"
        ),
    }
    return {"budget_analysis": budget_analysis, **update, "errors": errors}


if __name__ == "__main__":
    
    def sample(hotel_total: float, meal_cost: float, revision_count: int = 0) -> TravelState:
        state = make_initial_state(
            origin="Pakistan",
            destination="Dubai",
            travel_dates="December 10-14",
            duration=5,
            travelers=2,
            budget=2000.0,
            interests=["food", "shopping", "beaches", "sightseeing"],
            hotel_preference="4-star",
        )
        state["revision_count"] = revision_count
        state["flight_options"] = {"total_usd": 1000.0}
        state["activities"] = [{"name": "Burj Khalifa", "included": True}]
        state["restaurants"] = [{"name": "Sample Restaurant"}]
        state["selected_hotel"] = {"name": "Sample Hotel", "total_stay_cost_usd": hotel_total}
        meal = {"meal": "lunch", "restaurant": "Sample Restaurant", "cost_for_group_usd": meal_cost}
        state["itinerary"] = {"days": [
            {"activities": [{"name": "Burj Khalifa", "total_cost_usd": 94.0}], "meals": [meal]},
            {"activities": [{"name": "Desert Safari", "total_cost_usd": 60.0}], "meals": [meal, meal]},
            {"activities": [], "meals": [meal, meal]},
            {"activities": [], "meals": [meal, meal]},
            {"activities": [], "meals": [meal]},
        ]}
        return state

    def show(label: str, state: TravelState) -> None:
        result = budget_agent(state)
        analysis = result["budget_analysis"]
        print(f"\n== {label}")
        print(f"status={analysis['status']} total=${analysis['total_usd']} over_by=${analysis['over_by_usd']}")
        for row in analysis["breakdown"]:
            print(f"  {row['category']:<16} actual={row['actual_usd']} cap={row['cap_usd']} over_cap={row['over_cap_usd']}")
        print("  revision_count ->", result.get("revision_count", "unchanged"))
        print("  category_cuts ->", result.get("category_cuts", "unchanged"))
        print("  revision_notes ->", result.get("revision_notes", "unchanged"))
        print("  errors:", result["errors"])

    show("within budget", sample(hotel_total=428.0, meal_cost=24.0))
    show("over budget, revision 0", sample(hotel_total=428.0, meal_cost=60.0))
    show("over budget, last revision used", sample(hotel_total=428.0, meal_cost=60.0, revision_count=2))
    missing = sample(hotel_total=428.0, meal_cost=24.0)
    missing["flight_options"] = {}
    show("flights missing", missing)