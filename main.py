import json
import argparse
from pathlib import Path

from dotenv import load_dotenv

from graph import build_graph
from state import TravelState, make_initial_state
from typing import cast


EXAMPLES_DIR = Path("examples")


def print_summary(result: TravelState) -> None:
    hotel = result.get("selected_hotel", {})
    itinerary = result.get("itinerary", {})
    analysis = result.get("budget_analysis", {})

    print("\n=== TRIP SUMMARY ===")
    print(f"{result['origin']} -> {result['destination']}, {result['travel_dates']}, "
          f"{result['travelers']} travelers, budget ${result['budget']:.0f}")
    if hotel:
        print(f"Hotel: {hotel.get('name')} ({hotel.get('area')}), "
              f"${hotel.get('total_stay_cost_usd')} for {hotel.get('nights')} nights "
              f"[selected by {hotel.get('selected_by')}]")

    for day in itinerary.get("days", []):
        names = ", ".join(a["name"] for a in day["activities"]) or "free time"
        meals = ", ".join(f"{m['meal']}: {m['restaurant']}" for m in day["meals"])
        print(f"Day {day['day_number']} ({day['day_type']}): {names} | {meals}")
    for activity in itinerary.get("unscheduled_activities", []):
        print(f"Not scheduled: {activity['name']} ({activity['reason']})")

    print("\n=== BUDGET ===")
    for row in analysis.get("breakdown", []):
        cap = f"${row['cap_usd']:.0f}" if row["cap_usd"] is not None else "fixed"
        actual = f"${row['actual_usd']:.0f}" if row["actual_usd"] is not None else "missing"
        print(f"{row['category']:<16} {actual:>8}   cap {cap}")
    print(f"Total: ${analysis.get('total_usd')} of ${result['budget']:.0f} "
          f"-> {analysis.get('status')} after {result.get('revision_count', 0)} revision(s)")
    if result.get("revision_notes"):
        print(f"Last revision notes: {result['revision_notes']}")

    errors = result.get("errors", [])
    print(f"\n=== ERRORS AND WARNINGS ({len(errors)}) ===")
    for error in errors:
        print(f"- {error}")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-agent travel planner")
    parser.add_argument("--budget", type=float, default=2000.0, help="total trip budget in USD")
    parser.add_argument("--name", default="dubai", help="file name prefix for the saved example")
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    load_dotenv()
    state = make_initial_state(
        origin="Pakistan",
        destination="Dubai",
        travel_dates="December 10-14",
        duration=5,
        travelers=2,
        budget=args.budget,
        interests=["food", "shopping", "beaches", "sightseeing"],
        hotel_preference="4-star",
    )

    graph = build_graph()
    result: TravelState = state
    for mode, chunk in graph.stream(state, stream_mode=["updates", "values"]):
        if mode == "updates":
            for node_name in chunk:
                print(f"finished: {node_name}")
        else:
            result = cast(TravelState, chunk)

    print_summary(result)

    EXAMPLES_DIR.mkdir(exist_ok=True)
    (EXAMPLES_DIR / "dubai_input.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (EXAMPLES_DIR / "dubai_output.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nSaved input and full output to {EXAMPLES_DIR}/")


if __name__ == "__main__":
    main()