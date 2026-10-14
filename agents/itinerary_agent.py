from llm import invoke_structured
from schemas import ItineraryDraft
from state import TravelState, make_initial_state
from planning_rules import MEALS_BY_DAY_TYPE, TRANSIT_HOURS_PER_AREA_CHANGE, trip_days


def _day_load(indexes: list[int], activities: list[dict]) -> tuple[float, float]:
    activity_hours = sum(activities[i]["duration_hours"] for i in indexes)
    area_changes = sum(
        1 for a, b in zip(indexes, indexes[1:])
        if activities[a]["location"] != activities[b]["location"]
    )
    return activity_hours, area_changes * TRANSIT_HOURS_PER_AREA_CHANGE


def _fits(indexes: list[int], activities: list[dict], capacity: float) -> bool:
    activity_hours, transit_hours = _day_load(indexes, activities)
    return activity_hours + transit_hours <= capacity


def _clean_draft(draft: ItineraryDraft, days: list[dict], count: int) -> tuple[dict[int, list[int]], dict[int, str], dict[int, str]]:
    plan = {day["day_number"]: [] for day in days}
    areas: dict[int, str] = {}
    reasons: dict[int, str] = {}
    used: set[int] = set()
    for day in draft.days:
        if day.day_number not in plan or day.day_number in areas:
            continue
        areas[day.day_number] = day.area_focus
        reasons[day.day_number] = day.reasoning
        for number in day.activity_numbers:
            index = number - 1
            if 0 <= index < count and index not in used:
                plan[day.day_number].append(index)
                used.add(index)
    return plan, areas, reasons


def _fallback_draft(days: list[dict], activities: list[dict]) -> dict[int, list[int]]:
    plan = {day["day_number"]: [] for day in days}
    groups: dict[str, list[int]] = {}
    for index, activity in enumerate(activities):
        groups.setdefault(activity["location"], []).append(index)
    full_days = [d["day_number"] for d in days if d["day_type"] == "full"] or [days[0]["day_number"]]
    for indexes in groups.values():
        lightest = min(full_days, key=lambda n: sum(_day_load(plan[n], activities)))
        plan[lightest].extend(indexes)
    return plan


def _try_place(index: int, plan: dict[int, list[int]], capacity: dict[int, float], activities: list[dict]) -> bool:
    location = activities[index]["location"]
    same_area = [n for n in plan if any(activities[i]["location"] == location for i in plan[n])]
    others = [n for n in plan if n not in same_area]
    for number in same_area + others:
        if _fits(plan[number] + [index], activities, capacity[number]):
            plan[number].append(index)
            return True
    return False


def _enforce_limits(plan: dict[int, list[int]], days: list[dict], activities: list[dict]) -> tuple[dict[int, list[int]], list[int], int]:
    capacity = {d["day_number"]: d["capacity_hours"] for d in days}
    overflow: list[int] = []
    for number, indexes in plan.items():
        kept: list[int] = []
        for index in indexes:
            if _fits(kept + [index], activities, capacity[number]):
                kept.append(index)
            else:
                overflow.append(index)
        plan[number] = kept
    trimmed = len(overflow)

    planned = {i for indexes in plan.values() for i in indexes}
    overflow += [i for i in range(len(activities)) if i not in planned and i not in overflow]

    moved = 0
    unscheduled: list[int] = []
    for index in sorted(overflow):
        if _try_place(index, plan, capacity, activities):
            moved += 1
        else:
            unscheduled.append(index)
    return plan, unscheduled, trimmed + moved


def _swap_in_priorities(plan: dict[int, list[int]], unscheduled: list[int], days: list[dict], activities: list[dict]) -> tuple[dict[int, list[int]], list[int], int]:
    capacity = {d["day_number"]: d["capacity_hours"] for d in days}
    swaps = 0
    swapped = True
    while swapped:
        swapped = False
        for index in sorted(unscheduled):
            for number in plan:
                kept = list(plan[number])
                removed: list[int] = []
                lower_priority = sorted((i for i in kept if i > index), reverse=True)
                for candidate in lower_priority:
                    if _fits(kept + [index], activities, capacity[number]):
                        break
                    kept.remove(candidate)
                    removed.append(candidate)
                if removed and _fits(kept + [index], activities, capacity[number]):
                    plan[number] = kept + [index]
                    unscheduled.remove(index)
                    for candidate in removed:
                        if not _try_place(candidate, plan, capacity, activities):
                            unscheduled.append(candidate)
                    swaps += 1
                    swapped = True
                    break
            if swapped:
                break
    return plan, sorted(unscheduled), swaps


def _pick_restaurant(meal: str, activity_names: set[str], restaurants: list[dict], used: set[int]) -> tuple[dict | None, str]:
    rules = [
        ("near today's activity", lambda r: r["near_activity"] in activity_names and r["best_meal"] == meal),
        ("near today's activity", lambda r: r["near_activity"] in activity_names),
        ("near hotel", lambda r: r["near_activity"] == "near hotel" and r["best_meal"] == meal),
        ("near hotel", lambda r: r["near_activity"] == "near hotel"),
        ("elsewhere in the plan", lambda r: r["linked_to_plan"]),
    ]
    order = sorted(
        range(len(restaurants)),
        key=lambda i: not restaurants[i].get("within_meal_target", True),
    )
    for allow_repeat in (False, True):
        for match, rule in rules:
            for index in order:
                restaurant = restaurants[index]
                if (allow_repeat or index not in used) and rule(restaurant):
                    used.add(index)
                    return restaurant, match if not allow_repeat else f"{match} (repeat visit)"
    return None, "no restaurant available"


def _build_itinerary(days, plan, areas, reasons, activities, restaurants, hotel) -> list[dict]:
    used_restaurants: set[int] = set()
    built = []
    for day in days:
        number = day["day_number"]
        indexes = plan[number]
        activity_hours, transit_hours = _day_load(indexes, activities)
        names = {activities[i]["name"] for i in indexes}

        meals = []
        for meal in MEALS_BY_DAY_TYPE[day["day_type"]]:
            restaurant, match = _pick_restaurant(meal, names, restaurants, used_restaurants)
            meals.append({
                "meal": meal,
                "restaurant": restaurant["name"] if restaurant else None,
                "area": restaurant["area"] if restaurant else None,
                "cost_per_person_usd": restaurant["estimated_cost_per_person_usd"] if restaurant else 0,
                "cost_for_group_usd": restaurant["meal_cost_for_group_usd"] if restaurant else 0,
                "match": match,
            })

        default_area = activities[indexes[0]]["location"] if indexes else hotel.get("area", "hotel area")
        built.append({
            **day,
            "area_focus": areas.get(number) or default_area,
            "activities": [
                {key: activities[i][key] for key in
                 ("name", "location", "duration_hours", "best_time_to_visit", "total_cost_usd")}
                for i in indexes
            ],
            "activity_hours": activity_hours,
            "transit_hours": transit_hours,
            "meals": meals,
            "reasoning": reasons.get(number, "Grouped by area by the code fallback."),
        })
    return built


def itinerary_agent(state: TravelState) -> dict:
    errors: list[str] = []
    activities = [a for a in state.get("activities", []) if a.get("included")]
    restaurants = state.get("restaurants", [])
    hotel = state.get("selected_hotel", {})
    days = trip_days(state["duration"])

    activity_text = "\n".join(
        f"{n}. {a['name']} | area: {a['location']} | {a['duration_hours']} h | best time: {a['best_time_to_visit']}"
        for n, a in enumerate(activities, start=1)
    ) or "No activities."
    day_text = "\n".join(
        f"Day {d['day_number']} ({d['day_type']}): at most {d['capacity_hours']} h of activities"
        for d in days
    )

    prompt = f"""You are the itinerary planner for a trip to {state["destination"]}.
{state["travelers"]} travelers, staying at {hotel.get("name", "an unknown hotel")}
in {hotel.get("area", "an unknown area")}.

Days and their activity hour limits:
{day_text}

Activities (number | area | duration | best time):
{activity_text}

Rules:
- Return exactly {len(days)} days, numbered 1 to {len(days)}.
- Use each activity number at most once.
- Keep each day in one area, or in areas that are next to each other.
  Every change of area costs {TRANSIT_HOURS_PER_AREA_CHANGE} h of travel, which counts
  toward the day's limit.
- The arrival day and the departure day must stay light. Prefer short
  activities near the hotel on those days.
- Order each day's activities by their best time to visit.
- It is fine to leave activities out if they do not fit. Never break a limit.
"""

    planned_by = "llm"
    try:
        draft = invoke_structured(ItineraryDraft, prompt)
        plan, areas, reasons = _clean_draft(draft, days, len(activities))
    except Exception as error:
        errors.append(f"itinerary_agent: LLM step failed, used code fallback: {error}")
        plan, areas, reasons = _fallback_draft(days, activities), {}, {}
        planned_by = "code_fallback"

    draft_plan = {number: list(indexes) for number, indexes in plan.items()}
    plan, unscheduled, changes = _enforce_limits(plan, days, activities)
    plan, unscheduled, swaps = _swap_in_priorities(plan, unscheduled, days, activities)
    changes += swaps
    if planned_by == "llm" and changes:
        planned_by = "llm_repaired_by_code"
        for number, indexes in plan.items():
            if indexes != draft_plan[number]:
                areas.pop(number, None)
                reasons[number] = "Adjusted by code to respect activity priorities and daily hour limits."

    built_days = _build_itinerary(days, plan, areas, reasons, activities, restaurants, hotel)
    if not restaurants:
        errors.append("itinerary_agent: no restaurants available, meals left empty")

    itinerary = {
        "hotel": hotel.get("name", "unknown"),
        "days": built_days,
        "unscheduled_activities": [
            {"name": activities[i]["name"], "duration_hours": activities[i]["duration_hours"],
             "reason": "does not fit the daily hour limits"}
            for i in unscheduled
        ],
        "planned_activity_hours": sum(d["activity_hours"] for d in built_days),
        "transit_hours": sum(d["transit_hours"] for d in built_days),
        "capacity_hours": sum(d["capacity_hours"] for d in days),
        "included_activity_hours": sum(a["duration_hours"] for a in activities),
        "planned_by": planned_by,
        "breakfast_note": "Breakfast is not planned; check whether the hotel rate includes it.",
    }
    return {"itinerary": itinerary, "errors": errors}


if __name__ == "__main__":
    import json

    sample_state = make_initial_state(
        origin="Pakistan",
        destination="Dubai",
        travel_dates="December 10-14",
        duration=5,
        travelers=2,
        budget=2000.0,
        interests=["food", "shopping", "beaches", "sightseeing"],
        hotel_preference="4-star",
    )
    sample_state["selected_hotel"] = {"name": "Rose Rayhaan by Rotana", "area": "Sheikh Zayed Road"}
    sample_state["activities"] = [
        {"name": "Burj Khalifa At The Top", "location": "Downtown Dubai", "duration_hours": 2,
         "best_time_to_visit": "sunset", "total_cost_usd": 100, "included": True},
        {"name": "Dubai Mall & Fountain Show", "location": "Downtown Dubai", "duration_hours": 3,
         "best_time_to_visit": "evening", "total_cost_usd": 0, "included": True},
        {"name": "Desert Safari with BBQ Dinner", "location": "Lahbab Desert", "duration_hours": 6,
         "best_time_to_visit": "afternoon", "total_cost_usd": 120, "included": True},
        {"name": "JBR Beach", "location": "Jumeirah Beach Residence (JBR)", "duration_hours": 3,
         "best_time_to_visit": "morning", "total_cost_usd": 0, "included": True},
        {"name": "Dubai Marina Walk", "location": "Dubai Marina", "duration_hours": 2,
         "best_time_to_visit": "evening", "total_cost_usd": 0, "included": True},
        {"name": "Old Dubai Souks & Abra Ride", "location": "Al Fahidi & Dubai Creek", "duration_hours": 4,
         "best_time_to_visit": "morning", "total_cost_usd": 10, "included": True},
        {"name": "Global Village", "location": "Dubailand", "duration_hours": 4,
         "best_time_to_visit": "evening", "total_cost_usd": 20, "included": True},
        {"name": "Kite Beach", "location": "Jumeirah", "duration_hours": 5,
         "best_time_to_visit": "afternoon", "total_cost_usd": 0, "included": True},
        {"name": "Helicopter Tour", "location": "Palm Jumeirah", "duration_hours": 1,
         "best_time_to_visit": "morning", "total_cost_usd": 600, "included": False},
    ]
    sample_state["restaurants"] = [
        {"name": "Al Ustad Special Kebab", "area": "Al Fahidi", "estimated_cost_per_person_usd": 12,
         "meal_cost_for_group_usd": 24, "best_meal": "lunch",
         "near_activity": "Old Dubai Souks & Abra Ride", "linked_to_plan": True},
        {"name": "Time Out Market", "area": "Downtown Dubai", "estimated_cost_per_person_usd": 30,
         "meal_cost_for_group_usd": 60, "best_meal": "dinner",
         "near_activity": "Dubai Mall & Fountain Show", "linked_to_plan": True},
        {"name": "Operation Falafel", "area": "Sheikh Zayed Road", "estimated_cost_per_person_usd": 10,
         "meal_cost_for_group_usd": 20, "best_meal": "dinner",
         "near_activity": "near hotel", "linked_to_plan": True},
    ]

    result = itinerary_agent(sample_state)
    print(json.dumps(result, indent=2, ensure_ascii=False))