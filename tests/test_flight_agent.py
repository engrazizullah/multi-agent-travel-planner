from agents.flight_agent import flight_agent
from state import TravelState, make_initial_state


def make_state(destination: str = "Dubai", travelers: int = 2) -> TravelState:
    return make_initial_state(
        origin="Pakistan",
        destination=destination,
        travel_dates="December 10-14",
        duration=5,
        travelers=travelers,
        budget=2000.0,
        interests=["food"],
        hotel_preference="4-star",
    )


def test_known_route_gives_a_fixed_price_and_no_errors():
    result = flight_agent(make_state())
    flights = result["flight_options"]
    assert flights["total_usd"] == 1000.0
    assert flights["route_known"] is True
    assert flights["adjustable_in_revision"] is False
    assert result["errors"] == []


def test_unknown_route_uses_the_default_and_warns():
    result = flight_agent(make_state(destination="Paris"))
    assert result["flight_options"]["route_known"] is False
    assert "warning" in result["errors"][0]


def test_zero_travelers_is_reported_not_raised():
    result = flight_agent(make_state(travelers=0))
    assert result["flight_options"] == {}
    assert "invalid input" in result["errors"][0]


def test_blank_origin_is_reported():
    state = make_state()
    state["origin"] = "   "
    result = flight_agent(state)
    assert result["flight_options"] == {}
    assert "required" in result["errors"][0]