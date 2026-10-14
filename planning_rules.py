from state import TravelState

ARRIVAL_DAY_HOURS = 3
FULL_DAY_HOURS = 6
DEPARTURE_DAY_HOURS = 2
TRANSIT_HOURS_PER_AREA_CHANGE = 0.5

MEALS_BY_DAY_TYPE = {
    "arrival": ["dinner"],
    "full": ["lunch", "dinner"],
    "departure": ["lunch"],
    "arrival_and_departure": ["lunch"],
}


def trip_days(duration: int) -> list[dict]:
    if duration <= 1:
        return [{"day_number": 1, "day_type": "arrival_and_departure",
                 "capacity_hours": DEPARTURE_DAY_HOURS}]
    days = []
    for number in range(1, duration + 1):
        if number == 1:
            day_type, hours = "arrival", ARRIVAL_DAY_HOURS
        elif number == duration:
            day_type, hours = "departure", DEPARTURE_DAY_HOURS
        else:
            day_type, hours = "full", FULL_DAY_HOURS
        days.append({"day_number": number, "day_type": day_type, "capacity_hours": hours})
    return days


def total_activity_hours(duration: int) -> float:
    return sum(day["capacity_hours"] for day in trip_days(duration))

def total_meals(duration: int) -> int:
    return sum(len(MEALS_BY_DAY_TYPE[day["day_type"]]) for day in trip_days(duration))

BUDGET_SHARES = {
    "hotel": 0.45,
    "activities": 0.20,
    "food": 0.25,
    "transport_buffer": 0.10,
}
MIN_BUDGET_SHARES = {
    "hotel": 0.30,
    "activities": 0.10,
    "food": 0.15,
}
SHARE_CUT_PER_REVISION = 0.05
MAX_REVISIONS = 2


def spendable_budget(state: TravelState) -> float:
    flights = state.get("flight_options", {}).get("total_usd", 0.0)
    return max(state["budget"] - flights, 0.0)


def category_budget(state: TravelState, category: str) -> float:
    share = BUDGET_SHARES[category]
    if category in MIN_BUDGET_SHARES:
        cut = SHARE_CUT_PER_REVISION * state.get("category_cuts", {}).get(category, 0)
        share = max(share - cut, MIN_BUDGET_SHARES[category])
    return round(spendable_budget(state) * share, 2)
