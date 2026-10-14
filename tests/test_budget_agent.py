from agents.budget_agent import budget_agent
from planning_rules import MAX_REVISIONS
from state import TravelState, make_initial_state


def make_state(
    budget: float = 2000.0,
    hotel: float = 428.0,
    activities: float = 154.0,
    meal_for_group: float = 24.0,
    revision_count: int = 0,
    cuts: dict[str, int] | None = None,
) -> TravelState:
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
    meal = {"meal": "lunch", "restaurant": "Sample Restaurant", "cost_for_group_usd": meal_for_group}
    state["flight_options"] = {"total_usd": 1000.0}
    state["selected_hotel"] = {"name": "Sample Hotel", "total_stay_cost_usd": hotel}
    state["activities"] = [{"name": "Sample Activity", "included": True}]
    state["restaurants"] = [{"name": "Sample Restaurant"}]
    state["itinerary"] = {"days": [
        {"activities": [{"name": "Sample Activity", "total_cost_usd": activities}], "meals": [meal] * 8},
    ]}
    state["revision_count"] = revision_count
    state["category_cuts"] = cuts or {}
    return state


def test_within_budget_changes_nothing():
    result = budget_agent(make_state())
    analysis = result["budget_analysis"]
    assert analysis["status"] == "within_budget"
    assert analysis["total_usd"] == 1874.0
    assert analysis["needs_revision"] is False
    assert "revision_count" not in result
    assert result["errors"] == []


def test_over_budget_asks_for_a_revision_and_cuts_only_food():
    result = budget_agent(make_state(meal_for_group=60.0))
    assert result["budget_analysis"]["status"] == "needs_revision"
    assert result["revision_count"] == 1
    assert result["category_cuts"] == {"food": 1}
    assert "food" in result["revision_notes"]
    assert "hotel" not in result["revision_notes"]


def test_no_revision_after_the_last_one_is_used():
    result = budget_agent(make_state(meal_for_group=60.0, revision_count=MAX_REVISIONS))
    assert result["budget_analysis"]["status"] == "over_budget_final"
    assert result["budget_analysis"]["over_by_usd"] == 162.0
    assert "revision_count" not in result
    assert "category_cuts" not in result


def test_missing_flights_is_incomplete_not_within_budget():
    state = make_state()
    state["flight_options"] = {}
    result = budget_agent(state)
    analysis = result["budget_analysis"]
    assert analysis["status"] == "incomplete"
    assert analysis["missing_costs"] == ["flights"]
    assert analysis["over_by_usd"] is None
    assert "revision_count" not in result
    assert result["errors"]


def test_failed_activities_agent_counts_as_missing():
    state = make_state()
    state["activities"] = []
    result = budget_agent(state)
    assert result["budget_analysis"]["status"] == "incomplete"
    assert "activities" in result["budget_analysis"]["missing_costs"]


def test_cuts_every_adjustable_category_when_none_is_over_its_cap():
    # $1,500 budget: every adjustable category is exactly at its cap,
    # but the fixed $100 transport estimate pushes the total $50 over.
    state = make_state(budget=1500.0, hotel=225.0, activities=100.0, meal_for_group=125 / 8)
    result = budget_agent(state)
    assert result["budget_analysis"]["status"] == "needs_revision"
    assert result["category_cuts"] == {"hotel": 1, "activities": 1, "food": 1}
    assert "local_transport" not in result["revision_notes"]


def test_existing_cuts_are_added_to_not_overwritten():
    # After one hotel cut the hotel cap is $400, so a $350 hotel is under it
    # and only food (over its $250 cap) gets a new cut.
    state = make_state(hotel=350.0, meal_for_group=60.0, revision_count=1, cuts={"hotel": 1})
    result = budget_agent(state)
    assert result["category_cuts"] == {"hotel": 1, "food": 1}
    assert state["category_cuts"] == {"hotel": 1}
    