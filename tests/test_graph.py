import graph as graph_module
from graph import route_after_budget
from planning_rules import MAX_REVISIONS
from state import make_initial_state
from state import TravelState, make_initial_state


def make_fake_agents(monkeypatch, meal_for_group: float) -> list[str]:
    """Replace every LLM agent with a fake. The real budget agent stays."""
    calls: list[str] = []

    def fake(name: str, update: dict):
        def agent(state):
            calls.append(name)
            return {**update, "errors": []}
        return agent

    meal = {"meal": "lunch", "restaurant": "Sample Restaurant", "cost_for_group_usd": meal_for_group}
    fakes = {
        "flight_agent": fake("flight_agent", {"flight_options": {"total_usd": 1000.0}}),
        "destination_researcher": fake("destination_researcher", {"destination_research": {}}),
        "hotel_agent": fake("hotel_agent", {"selected_hotel": {"total_stay_cost_usd": 428.0}}),
        "activities_agent": fake("activities_agent", {"activities": [{"name": "A", "included": True}]}),
        "restaurant_agent": fake("restaurant_agent", {"restaurants": [{"name": "Sample Restaurant"}]}),
        "itinerary_agent": fake("itinerary_agent", {"itinerary": {"days": [
            {"activities": [{"name": "A", "total_cost_usd": 154.0}], "meals": [meal] * 8},
        ]}}),
    }
    for name, agent in fakes.items():
        monkeypatch.setattr(graph_module, name, agent)
    return calls


def make_state(budget_analysis: dict | None = None) -> TravelState:
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
    state["budget_analysis"] = budget_analysis or {}
    return state


def run_graph() -> dict:
    return graph_module.build_graph().invoke(make_state())


def test_router_follows_the_budget_decision():
    assert route_after_budget(make_state({"needs_revision": True})) == "revise"
    assert route_after_budget(make_state({"needs_revision": False})) == "done"
    assert route_after_budget(make_state()) == "done"


def test_within_budget_runs_each_agent_once(monkeypatch):
    calls = make_fake_agents(monkeypatch, meal_for_group=24.0)
    result = run_graph()
    assert calls.count("hotel_agent") == 1
    assert calls.count("flight_agent") == 1
    assert result["budget_analysis"]["status"] == "within_budget"
    assert result["revision_count"] == 0


def test_over_budget_loops_at_most_max_revisions_times(monkeypatch):
    calls = make_fake_agents(monkeypatch, meal_for_group=60.0)
    result = run_graph()
    assert calls.count("hotel_agent") == 1 + MAX_REVISIONS
    assert calls.count("flight_agent") == 1
    assert calls.count("destination_researcher") == 1
    assert result["revision_count"] == MAX_REVISIONS
    assert result["budget_analysis"]["status"] == "over_budget_final"
    assert result["category_cuts"]["food"] == MAX_REVISIONS