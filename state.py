import operator
from typing import Annotated, TypedDict


class TravelState(TypedDict):
    # Inputs: set once by main.py from the user's request
    origin: str
    destination: str
    travel_dates: str
    duration: int
    travelers: int
    budget: float
    interests: list[str]
    hotel_preference: str

    # Agent outputs: each field is written by exactly one agent
    destination_research: dict
    flight_options: dict
    hotel_options: list[dict]
    selected_hotel: dict
    activities: list[dict]
    restaurants: list[dict]
    itinerary: dict
    budget_analysis: dict

    # Control fields: steer the graph
    revision_count: int
    revision_notes: str
    category_cuts: dict[str, int]
    errors: Annotated[list[str], operator.add]


def make_initial_state(
    origin: str,
    destination: str,
    travel_dates: str,
    duration: int,
    travelers: int,
    budget: float,
    interests: list[str],
    hotel_preference: str,
) -> TravelState:
    return {
        "origin": origin,
        "destination": destination,
        "travel_dates": travel_dates,
        "duration": duration,
        "travelers": travelers,
        "budget": budget,
        "interests": interests,
        "hotel_preference": hotel_preference,
        "destination_research": {},
        "flight_options": {},
        "hotel_options": [],
        "selected_hotel": {},
        "activities": [],
        "restaurants": [],
        "itinerary": {},
        "budget_analysis": {},
        "revision_count": 0,
        "revision_notes": "",
        "category_cuts": {},
        "errors": [],
    }