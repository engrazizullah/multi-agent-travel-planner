from pydantic import BaseModel, Field
from typing import Literal

class Neighborhood(BaseModel):
    name: str
    best_for: str
    notes: str


class DestinationResearch(BaseModel):
    summary: str
    popular_areas: list[str]
    major_attractions: list[str]
    local_transport: list[str]
    best_time_to_visit: str
    travel_considerations: list[str]
    visa_and_entry_notes: str = Field(
        description=(
            "Entry and visa notes for travelers from the origin country only. "
            "Never generalize to 'most nationalities'. Always advise confirming "
            "with official government sources."
        )
    )
    estimated_daily_spend_usd_per_person: float = Field(
        ge=0,
        description=(
            "Typical daily spend per person on food, local transport and "
            "attraction entry fees. EXCLUDES accommodation and flights."
        ),
    )
    cost_notes: str
    recommended_neighborhoods: list[Neighborhood]

class HotelOption(BaseModel):
    name: str
    area: str
    star_rating: int = Field(ge=1, le=5)
    guest_rating: str = Field(
        description="Guest review score if the snippets show one, otherwise 'unknown'."
    )
    estimated_price_per_night_usd: float = Field(
        ge=0, description="Estimated price per room per night in USD."
    )
    price_evidence: str = Field(
        description=(
            "Where the price comes from: the snippet or source that showed it, "
            "or 'no price in snippets' if it is your own estimate."
        )
    )
    distance_to_attractions: str
    why_recommended: str


class HotelRecommendations(BaseModel):
    options: list[HotelOption] = Field(description="3 to 5 hotel options.")
    selected_hotel_name: str = Field(
        description="Must exactly match the name of one of the options."
    )
    selection_reason: str

class Activity(BaseModel):
    name: str
    location: str = Field(description="The specific area or neighborhood where it happens.")
    category: str = Field(description="Which traveler interest it serves, e.g. food or beaches.")
    estimated_cost_per_person_usd: float = Field(
        ge=0, description="Ticket or entry price per person in USD; 0 if free."
    )
    price_evidence: str = Field(
        description=(
            "Where the price comes from: the snippet or source that showed it, "
            "or 'no price in snippets' if it is your own estimate."
        )
    )
    duration_hours: float = Field(gt=0, le=12)
    best_time_to_visit: str
    why_relevant: str


class ActivityRecommendations(BaseModel):
    activities: list[Activity] = Field(
        description="6 to 10 activities in priority order for this traveler, including some free ones."
    )

class Restaurant(BaseModel):
    name: str
    area: str
    cuisine: str
    price_level: Literal["budget", "mid-range", "upscale"]
    estimated_cost_per_person_usd: float = Field(
        ge=0, description="Typical cost of one meal per person in USD."
    )
    price_evidence: str = Field(
        description=(
            "Where the price comes from: the snippet or source that showed it, "
            "or 'no price in snippets' if it is your own estimate."
        )
    )
    near_activity_number: int = Field(
        ge=0,
        description="Number of the planned activity it is near, from the numbered list, or 0 if near the hotel.",
    )

    best_meal: Literal["breakfast", "lunch", "dinner"]
    why_recommended: str


class RestaurantRecommendations(BaseModel):
    restaurants: list[Restaurant] = Field(
        description="5 to 8 restaurants close to the planned activities or the hotel."
    )

class DayPlan(BaseModel):
    day_number: int = Field(ge=1)
    area_focus: str = Field(
        description="Main area or neighborhood for this day, so travelers stay in one part of the city."
    )
    activity_numbers: list[int] = Field(
        description="Numbers of the activities for this day, in visiting order. An empty list is allowed."
    )
    reasoning: str = Field(
        description="One or two sentences on why these activities belong together on this day."
    )


class ItineraryDraft(BaseModel):
    days: list[DayPlan] = Field(
        description="Exactly one entry per trip day, from day 1 to the last day."
    )