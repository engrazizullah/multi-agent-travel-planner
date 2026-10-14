from llm import invoke_structured
from planning_rules import category_budget, total_activity_hours
from schemas import ActivityRecommendations
from state import TravelState, make_initial_state
from tools.web_search_tool import search_web


def _activity_limits(state: TravelState) -> tuple[float, float]:
    cost_cap = category_budget(state, "activities")
    hours_cap = total_activity_hours(state["duration"])
    return cost_cap, hours_cap


def _select_activities(activities: list[dict], cost_cap: float, hours_cap: float) -> list[dict]:
    spent = 0.0
    hours = 0.0
    selected: list[dict] = []
    for activity in activities:
        fits_money = spent + activity["total_cost_usd"] <= cost_cap
        fits_time = hours + activity["duration_hours"] <= hours_cap
        included = fits_money and fits_time
        if included:
            spent += activity["total_cost_usd"]
            hours += activity["duration_hours"]
            note = "included"
        elif not fits_money:
            note = "over activities budget"
        else:
            note = "schedule full"
        selected.append({**activity, "included": included, "selection_note": note})
    return selected


def activities_agent(state: TravelState) -> dict:
    destination = state["destination"]
    travelers = state["travelers"]
    interests = state.get("interests", []) or ["sightseeing"]
    cost_cap, hours_cap = _activity_limits(state)
    errors: list[str] = []

    queries = [
        f"best {interest} experiences in {destination} ticket price"
        for interest in interests[:4]
    ]

    snippets: list[str] = []
    for query in queries:
        result = search_web(query, max_results=3)
        if result["error"]:
            errors.append(f"activities_agent: search failed for '{query}': {result['error']}")
            continue
        for item in result["results"]:
            snippets.append(f"- {item['title']}: {item['snippet']}")

    search_text = "\n".join(snippets) if snippets else "No search results were available."
    research = state.get("destination_research", {})
    attractions = ", ".join(research.get("major_attractions", [])) or "No research available."
    revision_text = state.get("revision_notes", "") or "None"

    prompt = f"""You are an activities specialist for a travel planner.
Trip: {destination}, {state.get("travel_dates", "dates not given")},
{state["duration"]} days, {travelers} travelers.
Traveler interests: {", ".join(interests)}.
Activities budget for the whole group: about ${cost_cap:.0f}
(about ${cost_cap / travelers:.0f} per person).

Major attractions from the destination research: {attractions}

Budget revision notes: {revision_text}

Rules:
- Suggest 6 to 10 real activities in priority order for these travelers,
  covering their interests. Include some free options.
- Base each price on the snippets. If no snippet shows a price, give a
  realistic estimate and set price_evidence to 'no price in snippets'.
- Never adjust a price to fit the budget. The code checks the budget.
- location must be a specific area, because restaurants will be chosen near it.
- If the revision notes ask for cheaper choices, favor free and low-cost activities.

Search snippets:
{search_text}
"""

    try:
        recommendation = invoke_structured(ActivityRecommendations, prompt)
    except Exception as error:
        errors.append(f"activities_agent: LLM step failed: {error}")
        return {"activities": [], "errors": errors}

    activities: list[dict] = []
    for activity in recommendation.activities:
        data = activity.model_dump()
        data["total_cost_usd"] = round(activity.estimated_cost_per_person_usd * travelers, 2)
        activities.append(data)

    if not activities:
        errors.append("activities_agent: the LLM returned no activities")
        return {"activities": [], "errors": errors}

    return {"activities": _select_activities(activities, cost_cap, hours_cap), "errors": errors}


if __name__ == "__main__":
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
    sample_state["flight_options"] = {"total_usd": 1000.0}
    sample_state["destination_research"] = {
        "major_attractions": [
            "Burj Khalifa", "Dubai Mall & Dubai Fountain", "Desert Safari",
            "JBR Beach", "Dubai Marina", "Al Fahidi & Dubai Creek souks",
        ]
    }

    result = activities_agent(sample_state)
    for a in result["activities"]:
        mark = "IN " if a["included"] else "OUT"
        print(f"{mark} {a['name']} | {a['location']} | ${a['estimated_cost_per_person_usd']}/person "
              f"| {a['duration_hours']}h | {a['price_evidence']} | {a['selection_note']}")
    chosen = [a for a in result["activities"] if a["included"]]
    print("included total cost:", sum(a["total_cost_usd"] for a in chosen))
    print("included hours:", sum(a["duration_hours"] for a in chosen))
    print("errors:", result["errors"])