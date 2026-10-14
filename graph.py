from langgraph.graph import END, START, StateGraph

from agents.activities_agent import activities_agent
from agents.budget_agent import budget_agent
from agents.destination_researcher import destination_researcher
from agents.flight_agent import flight_agent
from agents.hotel_agent import hotel_agent
from agents.itinerary_agent import itinerary_agent
from agents.restaurant_agent import restaurant_agent
from state import TravelState


def route_after_budget(state: TravelState) -> str:
    if state.get("budget_analysis", {}).get("needs_revision"):
        return "revise"
    return "done"


def build_graph():
    builder = StateGraph(TravelState)

    builder.add_node("flight_agent", flight_agent)
    builder.add_node("destination_researcher", destination_researcher)
    builder.add_node("hotel_agent", hotel_agent)
    builder.add_node("activities_agent", activities_agent)
    builder.add_node("restaurant_agent", restaurant_agent)
    builder.add_node("itinerary_agent", itinerary_agent)
    builder.add_node("budget_agent", budget_agent)

    builder.add_edge(START, "flight_agent")
    builder.add_edge("flight_agent", "destination_researcher")
    builder.add_edge("destination_researcher", "hotel_agent")
    builder.add_edge("hotel_agent", "activities_agent")
    builder.add_edge("activities_agent", "restaurant_agent")
    builder.add_edge("restaurant_agent", "itinerary_agent")
    builder.add_edge("itinerary_agent", "budget_agent")
    builder.add_conditional_edges(
        "budget_agent",
        route_after_budget,
        {"revise": "hotel_agent", "done": END},
    )
    return builder.compile()


if __name__ == "__main__":
    graph = build_graph()
    print(graph.get_graph().draw_mermaid())