import pytest

from planning_rules import (
    category_budget,
    spendable_budget,
    total_activity_hours,
    total_meals,
    trip_days,
)
from state import TravelState, make_initial_state


def make_state(budget: float = 2000.0, flights: float = 1000.0,
               cuts: dict[str, int] | None = None) -> TravelState:
    state = make_initial_state(
        origin="Pakistan",
        destination="Dubai",
        travel_dates="December 10-14",
        duration=5,
        travelers=2,
        budget=budget,
        interests=["food"],
        hotel_preference="4-star",
    )
    state["flight_options"] = {"total_usd": flights}
    state["category_cuts"] = cuts or {}
    return state


def test_five_day_trip_has_light_first_and_last_day():
    days = trip_days(5)
    assert [day["day_type"] for day in days] == ["arrival", "full", "full", "full", "departure"]
    assert [day["capacity_hours"] for day in days] == [3, 6, 6, 6, 2]


def test_one_day_trip_is_both_arrival_and_departure():
    days = trip_days(1)
    assert len(days) == 1
    assert days[0]["day_type"] == "arrival_and_departure"


@pytest.mark.parametrize(
    ("duration", "hours", "meals"),
    [(1, 2, 1), (2, 5, 2), (3, 11, 4), (5, 23, 8)],
)
def test_hour_and_meal_totals(duration: int, hours: float, meals: int):
    assert total_activity_hours(duration) == hours
    assert total_meals(duration) == meals


def test_spendable_budget_subtracts_flights():
    assert spendable_budget(make_state()) == 1000.0


def test_spendable_budget_is_never_negative():
    assert spendable_budget(make_state(budget=800.0)) == 0.0


def test_category_budgets_without_cuts():
    state = make_state()
    assert category_budget(state, "hotel") == 450.0
    assert category_budget(state, "activities") == 200.0
    assert category_budget(state, "food") == 250.0
    assert category_budget(state, "transport_buffer") == 100.0


def test_a_cut_only_changes_its_own_category():
    state = make_state(cuts={"food": 1})
    assert category_budget(state, "food") == 200.0
    assert category_budget(state, "hotel") == 450.0
    assert category_budget(state, "activities") == 200.0


def test_cuts_stop_at_the_floor():
    state = make_state(cuts={"hotel": 10})
    assert category_budget(state, "hotel") == 300.0