FLIGHT_PRICES_PER_PERSON_USD = {
    ("PAKISTAN", "DUBAI"): 500.0,
}
DEFAULT_PRICE_PER_PERSON_USD = 500.0


def get_flight_options(origin: str, destination: str, travelers: int) -> dict:
    if travelers < 1:
        raise ValueError("travelers must be at least 1")

    key = (origin.strip().upper(), destination.strip().upper())
    route_known = key in FLIGHT_PRICES_PER_PERSON_USD
    per_person = FLIGHT_PRICES_PER_PERSON_USD.get(key, DEFAULT_PRICE_PER_PERSON_USD)

    return {
        "source": "hardcoded",
        "origin": origin,
        "destination": destination,
        "travelers": travelers,
        "route_known": route_known,
        "price_per_person_usd": per_person,
        "total_usd": per_person * travelers,
        "note": "Fixed estimate for a round trip, not a live fare.",
    }


if __name__ == "__main__":
    print(get_flight_options("Pakistan", "Dubai", 2))
    print(get_flight_options("Pakistan", "Paris", 2))
    try:
        get_flight_options("Pakistan", "Dubai", 0)
    except ValueError as error:
        print("Error:", error)
        