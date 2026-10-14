import pytest

import agents.itinerary_agent as itinerary_module
from agents.itinerary_agent import _pick_restaurant, itinerary_agent
from schemas import DayPlan, ItineraryDraft
from state import TravelState, make_initial_state

# Activities in priority order: number 1 is the most important.
ACTIVITIES = [
    ("Burj Khalifa", "Downtown", 2),
    ("Dubai Mall", "Downtown", 3),
    ("Desert Safari", "Desert", 6),
    ("JBR Beach", "JBR", 3),
    ("Marina Walk", "Marina", 2),
    ("Old Dubai", "Creek", 4),
    ("Kite Beach", "Jumeirah", 5),
]


def make_state() -> TravelState:
    state = make_initial_state(
        origin="Pakistan",
        destination="Dubai",
        travel_dates="December 10-14",
        duration=5,
        travelers=2,
        budget=2000.0,
        interests=["food"],
        hotel_preference="4-star",
    )
    state["selected_hotel"] = {"name": "Sample Hotel", "area": "Downtown"}
    state["activities"] = [
        {"name": name, "location": area, "duration_hours": hours,
         "best_time_to_visit": "any", "total_cost_usd": 0, "included": True}
        for name, area, hours in ACTIVITIES
    ]
    state["restaurants"] = [
        {"name": "Hotel Cafe", "area": "Downtown", "estimated_cost_per_person_usd": 10,
         "meal_cost_for_group_usd": 20, "best_meal": "dinner", "near_activity": "near hotel",
         "linked_to_plan": True, "within_meal_target": True},
    ]
    return state


def fake_llm(monkeypatch, days: list[tuple[int, list[int]]]) -> None:
    draft = ItineraryDraft(days=[
        DayPlan(day_number=number, area_focus="LLM area", activity_numbers=numbers,
                reasoning="LLM reasoning")
        for number, numbers in days
    ])
    monkeypatch.setattr(itinerary_module, "invoke_structured", lambda schema, prompt: draft)


def scheduled_names(result: dict) -> list[str]:
    return [a["name"] for day in result["itinerary"]["days"] for a in day["activities"]]


def unscheduled_names(result: dict) -> list[str]:
    return [a["name"] for a in result["itinerary"]["unscheduled_activities"]]


def assert_every_day_within_limit(result: dict) -> None:
    for day in result["itinerary"]["days"]:
        assert day["activity_hours"] + day["transit_hours"] <= day["capacity_hours"]


def test_llm_failure_falls_back_to_code_plan(monkeypatch):
    def broken_llm(schema, prompt):
        raise RuntimeError("fake Groq outage")

    monkeypatch.setattr(itinerary_module, "invoke_structured", broken_llm)
    result = itinerary_agent(make_state())
    assert result["itinerary"]["planned_by"] == "code_fallback"
    assert "fake Groq outage" in result["errors"][0]
    assert scheduled_names(result)
    assert_every_day_within_limit(result)


def test_plan_that_breaks_the_hour_limits_is_repaired(monkeypatch):
    fake_llm(monkeypatch, [(1, [1, 2, 3, 4, 5, 6, 7]), (2, []), (3, []), (4, []), (5, [])])
    result = itinerary_agent(make_state())
    assert result["itinerary"]["planned_by"] == "llm_repaired_by_code"
    assert_every_day_within_limit(result)


def test_duplicate_and_unknown_activity_numbers_are_ignored(monkeypatch):
    fake_llm(monkeypatch, [(1, [1, 1, 99]), (2, [2, 1]), (3, []), (4, []), (5, [])])
    result = itinerary_agent(make_state())
    names = scheduled_names(result)
    assert len(names) == len(set(names))


def test_high_priority_activity_replaces_a_low_priority_one(monkeypatch):
    # The LLM leaves out the Desert Safari (#3) and fills day 3 with Kite Beach (#7).
    fake_llm(monkeypatch, [(1, [1]), (2, [2, 5]), (3, [7]), (4, [6]), (5, [])])
    result = itinerary_agent(make_state())
    assert "Desert Safari" in scheduled_names(result)
    assert "Kite Beach" in unscheduled_names(result)
    assert_every_day_within_limit(result)


def test_days_changed_by_code_lose_the_llm_text(monkeypatch):
    fake_llm(monkeypatch, [(1, [1]), (2, [2, 5]), (3, [7]), (4, [6]), (5, [])])
    days = itinerary_agent(make_state())["itinerary"]["days"]
    assert days[0]["reasoning"] == "LLM reasoning"
    assert days[2]["reasoning"].startswith("Adjusted by code")
    assert days[2]["area_focus"] != "LLM area"


def test_meals_follow_the_day_type(monkeypatch):
    fake_llm(monkeypatch, [(1, [1]), (2, []), (3, []), (4, []), (5, [])])
    days = itinerary_agent(make_state())["itinerary"]["days"]
    assert [m["meal"] for m in days[0]["meals"]] == ["dinner"]
    assert [m["meal"] for m in days[2]["meals"]] == ["lunch", "dinner"]
    assert [m["meal"] for m in days[4]["meals"]] == ["lunch"]


@pytest.mark.parametrize(
    ("first_is_affordable", "expected"),
    [(False, "Cheap"), (True, "Pricey")],
)
def test_affordable_restaurant_wins_in_the_same_area(first_is_affordable: bool, expected: str):
    restaurants = [
        {"name": "Pricey", "near_activity": "Dubai Mall", "best_meal": "lunch",
         "linked_to_plan": True, "within_meal_target": first_is_affordable},
        {"name": "Cheap", "near_activity": "Dubai Mall", "best_meal": "lunch",
         "linked_to_plan": True, "within_meal_target": True},
    ]
    restaurant, match = _pick_restaurant("lunch", {"Dubai Mall"}, restaurants, set())
    assert restaurant is not None
    assert restaurant["name"] == expected
    assert match == "near today's activity"