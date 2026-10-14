from llm import invoke_structured
from schemas import RestaurantRecommendations
from state import TravelState, make_initial_state
from tools.web_search_tool import search_web
from planning_rules import category_budget, total_meals


def _meal_target(state: TravelState) -> float:
    meals = total_meals(state["duration"]) * state["travelers"]
    return round(category_budget(state, "food") / meals, 2)


def _search_areas(activities: list[dict], hotel_area: str) -> list[str]:
    areas: list[str] = []
    if hotel_area:
        areas.append(hotel_area)
    for activity in activities:
        area = activity.get("location", "")
        if area and area not in areas:
            areas.append(area)
    return areas[:4]


def _price_words(meal_target: float) -> str:
    if meal_target < 20:
        return "cheap eats budget"
    if meal_target < 40:
        return "affordable"
    return "best"

def restaurant_agent(state: TravelState) -> dict:
    destination = state["destination"]
    travelers = state["travelers"]
    meal_target = _meal_target(state)
    errors: list[str] = []

    planned = [a for a in state.get("activities", []) if a.get("included")]
    hotel_area = state.get("selected_hotel", {}).get("area", "")
    areas = _search_areas(planned, hotel_area) or [destination]

    snippets: list[str] = []
    for area in areas:
        query = (
            f"{_price_words(meal_target)} restaurants near {area} {destination} "
            f"under {int(meal_target)} USD per person"
        )
        result = search_web(query, max_results=3)
        if result["error"]:
            errors.append(f"restaurant_agent: search failed for '{query}': {result['error']}")
            continue
        for item in result["results"]:
            snippets.append(f"- {item['title']}: {item['snippet']}")

    search_text = "\n".join(snippets) if snippets else "No search results were available."
    activity_lines = [f"0. Near the hotel ({hotel_area or 'hotel area unknown'})"]
    activity_lines += [
        f"{number}. {a['name']} ({a['location']})"
        for number, a in enumerate(planned, start=1)
    ]
    activity_text = "\n".join(activity_lines)

    revision_text = state.get("revision_notes", "") or "None"

    prompt = f"""You are a restaurant specialist for a travel planner.
Trip: {destination}, {state["duration"]} days, {travelers} travelers.
Traveler interests: {", ".join(state.get("interests", []))}.
Hotel area: {hotel_area or "unknown"}.
Target: about ${meal_target:.0f} per person per meal on average.

Planned activities (name and area):
{activity_text}

Budget revision notes: {revision_text}

Rules:
- Recommend 5 to 8 real restaurants that appear in the snippets. Do not invent names.
- near_activity_number must be a number from the planned activities list above
  (0 means near the hotel).
- At least half of the restaurants must cost at or below the target.
  When the target is low, prefer local cafeterias, street food and food courts.
  Include local food if the travelers are interested in food.
- Only places that serve full meals. No dessert, snack or coffee-only stalls.
  best_meal must be exactly one of: breakfast, lunch, dinner.
- Base each price on the snippets. If no snippet shows a price, give a
  realistic estimate and set price_evidence to 'no price in snippets'.
- If a snippet gives a price range, use the middle of the range, not the lowest value.
- Convert other currencies to USD; never copy a non-USD number as if it were USD.  
- Never adjust a price to fit the target.

Search snippets:
{search_text}
"""

    try:
        recommendation = invoke_structured(RestaurantRecommendations, prompt)
    except Exception as error:
        errors.append(f"restaurant_agent: LLM step failed: {error}")
        return {"restaurants": [], "errors": errors}


    restaurants: list[dict] = []
    for restaurant in recommendation.restaurants:
        data = restaurant.model_dump()
        data["meal_cost_for_group_usd"] = round(
            restaurant.estimated_cost_per_person_usd * travelers, 2
        )
        data["within_meal_target"] = restaurant.estimated_cost_per_person_usd <= meal_target

        number = restaurant.near_activity_number
        if number == 0:
            data["near_activity"] = "near hotel"
            data["linked_to_plan"] = True
        elif 1 <= number <= len(planned):
            data["near_activity"] = planned[number - 1]["name"]
            data["linked_to_plan"] = True
        else:
            data["near_activity"] = "unknown"
            data["linked_to_plan"] = False
        restaurants.append(data)

    if not restaurants:
        errors.append("restaurant_agent: the LLM returned no restaurants")

    return {"restaurants": restaurants, "errors": errors}


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
    sample_state["selected_hotel"] = {"name": "Rose Rayhaan by Rotana", "area": "Downtown Dubai"}
    sample_state["activities"] = [
        {"name": "Burj Khalifa At The Top", "location": "Downtown Dubai", "included": True},
        {"name": "Old Town, Souk, Street Food & Abra Ride Tour",
         "location": "Al Fahidi Historic District & Dubai Creek", "included": True},
        {"name": "JBR Public Beach Relaxation",
         "location": "Jumeirah Beach Residence (JBR)", "included": True},
        {"name": "Helicopter Tour", "location": "Palm Jumeirah", "included": False},
    ]

    print("meal target per person:", _meal_target(sample_state))
    result = restaurant_agent(sample_state)
    for r in result["restaurants"]:
        print(f"{r['name']} | {r['area']} | {r['cuisine']} | {r['price_level']} "
              f"| ${r['estimated_cost_per_person_usd']}/person | {r['price_evidence']} "
              f"| near: {r['near_activity']} | linked: {r['linked_to_plan']}")
    print("errors:", result["errors"])

