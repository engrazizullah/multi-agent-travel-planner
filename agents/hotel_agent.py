import math

from llm import invoke_structured
from schemas import HotelRecommendations
from state import TravelState, make_initial_state
from tools.web_search_tool import search_web
from planning_rules import category_budget


def _stay_details(state: TravelState) -> tuple[int, int, float]:
    nights = max(state["duration"] - 1, 1)
    rooms = max(math.ceil(state["travelers"] / 2), 1)
    nightly_cap = category_budget(state, "hotel") / nights / rooms
    return nights, rooms, round(nightly_cap, 2)


def _choose_hotel(options: list[dict], preferred_name: str) -> tuple[dict, str]:
    for option in options:
        if option["name"] == preferred_name and option["within_nightly_cap"]:
            return option, "llm"
    affordable = [option for option in options if option["within_nightly_cap"]]
    pool = affordable or options
    cheapest = min(pool, key=lambda option: option["estimated_price_per_night_usd"])
    return cheapest, "code_fallback"


def hotel_agent(state: TravelState) -> dict:
    destination = state["destination"]
    preference = state.get("hotel_preference", "") or "mid-range"
    nights, rooms, nightly_cap = _stay_details(state)
    errors: list[str] = []

    research = state.get("destination_research", {})
    neighborhoods = research.get("recommended_neighborhoods", [])
    areas = [n["name"] for n in neighborhoods][:2] or [destination]

    queries = [
        f"best {preference} hotels in {area} {destination} price per night"
        for area in areas
    ]
    queries.append(f"{preference} hotels in {destination} under {int(nightly_cap)} USD per night")

    snippets: list[str] = []
    sources: list[str] = []
    for query in queries:
        result = search_web(query, max_results=3)
        if result["error"]:
            errors.append(f"hotel_agent: search failed for '{query}': {result['error']}")
            continue
        for item in result["results"]:
            snippets.append(f"- {item['title']}: {item['snippet']}")
            sources.append(item["url"])

    search_text = "\n".join(snippets) if snippets else "No search results were available."
    neighborhood_text = "\n".join(
        f"- {n['name']}: {n['best_for']}" for n in neighborhoods
    ) or "No neighborhood research available."
    revision_text = state.get("revision_notes", "") or "None"

    prompt = f"""You are a hotel specialist for a travel planner.
Trip: {destination}, {state.get("travel_dates", "dates not given")}, {nights} nights,
{state["travelers"]} travelers in {rooms} room(s). Hotel preference: {preference}.
Target price: at most about ${nightly_cap:.0f} per room per night.

Recommended neighborhoods:
{neighborhood_text}

Budget revision notes: {revision_text}

Rules:
- Suggest 3 to 5 real hotels that appear in the snippets. Do not invent hotel names.
- estimated_price_per_night_usd is per room per night, for these dates.
- Base each price on the snippets. If no snippet shows a price for that hotel,
  give a realistic estimate for these dates and set price_evidence to
  'no price in snippets'.
- Never adjust a hotel's price to fit the target. Report the realistic price
  even if it is over the target; the code checks the budget separately.
- Prefer hotels that really are at or below the target price. If none are,
  include the cheapest realistic options you can find.
- selected_hotel_name must exactly match one option's name.

Search snippets:
{search_text}
"""

    try:
        recommendation = invoke_structured(HotelRecommendations, prompt)
    except Exception as error:
        errors.append(f"hotel_agent: LLM step failed: {error}")
        return {"hotel_options": [], "selected_hotel": {}, "errors": errors}

    if not isinstance(recommendation, HotelRecommendations):
        recommendation = HotelRecommendations.model_validate(recommendation)

    options: list[dict] = []
    for option in recommendation.options:
        data = option.model_dump()
        data["total_stay_cost_usd"] = round(option.estimated_price_per_night_usd * nights * rooms, 2)
        data["within_nightly_cap"] = option.estimated_price_per_night_usd <= nightly_cap
        options.append(data)

    if not options:
        errors.append("hotel_agent: the LLM returned no hotel options")
        return {"hotel_options": [], "selected_hotel": {}, "errors": errors}

    chosen, selected_by = _choose_hotel(options, recommendation.selected_hotel_name)
    selected_hotel = {
        **chosen,
        "nights": nights,
        "rooms": rooms,
        "nightly_cap_usd": nightly_cap,
        "selected_by": selected_by,
        "selection_reason": (
            recommendation.selection_reason if selected_by == "llm"
            else "Chosen by code: the cheapest option within the nightly cap."
        ),
        "price_basis": "estimate from web search snippets",
        "sources": sorted(set(sources)),
    }
    return {"hotel_options": options, "selected_hotel": selected_hotel, "errors": errors}


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
    sample_state["flight_options"] = {"total_usd": 1000.0}
    sample_state["destination_research"] = {
        "recommended_neighborhoods": [
            {"name": "Dubai Marina / JBR", "best_for": "Beach and dining", "notes": ""},
            {"name": "Downtown Dubai", "best_for": "Shopping and sights", "notes": ""},
        ]
    }
    print(json.dumps(hotel_agent(sample_state), indent=2, ensure_ascii=False))