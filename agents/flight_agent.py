from state import TravelState, make_initial_state
from tools.flights_tool import get_flight_options


def flight_agent(state: TravelState) -> dict:
    errors: list[str] = []
    origin = state.get("origin", "").strip()
    destination = state.get("destination", "").strip()

    if not origin or not destination:
        errors.append("flight_agent: origin and destination are required")
        return {"flight_options": {}, "errors": errors}

    try:
        flights = get_flight_options(origin, destination, state["travelers"])
    except ValueError as error:
        errors.append(f"flight_agent: invalid input: {error}")
        return {"flight_options": {}, "errors": errors}
    except Exception as error:
        errors.append(f"flight_agent: flight tool failed: {error}")
        return {"flight_options": {}, "errors": errors}

    if not flights["route_known"]:
        errors.append(
            f"flight_agent: warning: no price data for {origin} to {destination}, "
            f"used the default ${flights['price_per_person_usd']:.0f} per person"
        )

    flights["adjustable_in_revision"] = False
    return {"flight_options": flights, "errors": errors}


if __name__ == "__main__":
    def sample(destination: str, travelers: int) -> TravelState:
        return make_initial_state(
            origin="Pakistan",
            destination=destination,
            travel_dates="December 10-14",
            duration=5,
            travelers=travelers,
            budget=2000.0,
            interests=["food", "shopping", "beaches", "sightseeing"],
            hotel_preference="4-star",
        )

    print("known route:  ", flight_agent(sample("Dubai", 2)))
    print("unknown route:", flight_agent(sample("Paris", 2)))
    print("bad input:    ", flight_agent(sample("Dubai", 0)))
    print("no origin:    ", flight_agent({**sample("Dubai", 2), "origin": " "}))

    