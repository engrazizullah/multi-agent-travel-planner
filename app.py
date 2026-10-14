import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from state import TravelState, make_initial_state
from typing import cast

load_dotenv()

EXAMPLES_DIR = Path("examples")
STATUS_MESSAGES = {
    "within_budget": ("success", "Within budget"),
    "over_budget_final": ("warning", "Over budget after the last revision"),
    "incomplete": ("error", "Incomplete: an agent failed, so a cost is unknown"),
    "needs_revision": ("info", "Needs revision"),
}
ARCHITECTURE_DOT = """
digraph {
    rankdir=LR;
    node [shape=box, style=rounded];
    start [shape=oval]; end [shape=oval];
    start -> flight_agent -> destination_researcher -> hotel_agent -> activities_agent
          -> restaurant_agent -> itinerary_agent -> budget_agent;
    budget_agent -> hotel_agent [label="revise", style=dashed];
    budget_agent -> end [label="done", style=dashed];
}
"""

st.set_page_config(page_title="Multi-Agent Travel Planner", layout="wide")


# ---------- loading data ----------

@st.cache_data
def load_examples() -> dict[str, dict]:
    examples: dict[str, dict] = {}
    for path in sorted(EXAMPLES_DIR.glob("*_output.json")):
        name = path.name.removesuffix("_output.json")
        examples[name] = json.loads(path.read_text(encoding="utf-8"))
    return examples


@st.cache_resource
def get_graph():
    from graph import build_graph  # imported here so replay mode never loads the agents
    return build_graph()


def live_mode_available() -> bool:
    return bool(os.getenv("GROQ_API_KEY") and os.getenv("TAVILY_API_KEY"))


# ---------- rendering one result ----------

def money(value: float | None) -> str:
    return "unknown" if value is None else f"${value:,.0f}"


def render_budget(result: dict) -> None:
    analysis = result.get("budget_analysis", {})
    status = analysis.get("status", "unknown")
    kind, message = STATUS_MESSAGES.get(status, ("info", status))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total cost", money(analysis.get("total_usd")))
    col2.metric("Budget", money(result.get("budget")))
    col3.metric("Remaining", money(analysis.get("remaining_usd")))
    col4.metric("Revisions", result.get("revision_count", 0))
    getattr(st, kind)(message)

    rows = [
        {
            "Category": row["category"],
            "Actual": money(row["actual_usd"]),
            "Cap": money(row["cap_usd"]) if row["cap_usd"] is not None else "fixed",
            "Over cap": money(row["over_cap_usd"]) if row["over_cap_usd"] else "",
        }
        for row in analysis.get("breakdown", [])
    ]
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    if result.get("revision_notes"):
        st.caption(f"Last revision notes: {result['revision_notes']}")
    if result.get("category_cuts"):
        st.caption(f"Categories cut during revisions: {result['category_cuts']}")
    if analysis.get("local_transport_basis"):
        st.caption(f"Local transport: {analysis['local_transport_basis']}")


def render_hotel(result: dict) -> None:
    hotel = result.get("selected_hotel", {})
    if not hotel:
        st.warning("No hotel was selected.")
        return
    st.markdown(f"**{hotel.get('name')}** · {hotel.get('area')} · {hotel.get('star_rating', '?')}-star")
    st.write(
        f"${hotel.get('estimated_price_per_night_usd', 0):,.0f}/night × {hotel.get('nights')} nights "
        f"= **${hotel.get('total_stay_cost_usd', 0):,.0f}** "
        f"(cap ${hotel.get('nightly_cap_usd', 0):,.0f}/night, chosen by {hotel.get('selected_by')})"
    )
    st.caption(f"Price evidence: {hotel.get('price_evidence', 'not given')}")


def render_itinerary(result: dict) -> None:
    itinerary = result.get("itinerary", {})
    days = itinerary.get("days", [])
    if not days:
        st.warning("No itinerary was produced.")
        return
    st.caption(
        f"Planned by: {itinerary.get('planned_by')} · "
        f"{itinerary.get('planned_activity_hours')} of {itinerary.get('capacity_hours')} activity hours used"
    )
    for day in days:
        title = (f"Day {day['day_number']} ({day['day_type']}) · {day['area_focus']} · "
                 f"{day['activity_hours'] + day['transit_hours']:g} of {day['capacity_hours']} h")
        with st.expander(title, expanded=True):
            if day["activities"]:
                for activity in day["activities"]:
                    st.markdown(
                        f"- **{activity['name']}** ({activity['location']}) · "
                        f"{activity['duration_hours']:g} h · ${activity['total_cost_usd']:,.0f} for the group"
                    )
            else:
                st.markdown("- Free time")
            for meal in day["meals"]:
                place = meal["restaurant"] or "no restaurant found"
                st.markdown(f"- {meal['meal'].title()}: {place} · ${meal['cost_for_group_usd']:,.0f} ({meal['match']})")
            st.caption(day["reasoning"])
    for activity in itinerary.get("unscheduled_activities", []):
        st.markdown(f"Not scheduled: **{activity['name']}** ({activity['reason']})")


def render_result(result: dict) -> None:
    st.subheader(
        f"{result.get('origin')} → {result.get('destination')} · {result.get('travel_dates')} · "
        f"{result.get('travelers')} travelers"
    )
    render_budget(result)

    left, right = st.columns([2, 1])
    with left:
        st.markdown("#### Day-by-day itinerary")
        render_itinerary(result)
    with right:
        st.markdown("#### Hotel")
        render_hotel(result)
        research = result.get("destination_research", {})
        if research.get("visa_and_entry_notes"):
            st.markdown("#### Visa and entry")
            st.write(research["visa_and_entry_notes"])

    errors = result.get("errors", [])
    with st.expander(f"Errors and warnings ({len(errors)})", expanded=bool(errors)):
        for error in errors:
            st.markdown(f"- {error}")
        if not errors:
            st.write("None.")
    with st.expander("Full JSON output"):
        st.json(result, expanded=False)


# ---------- tabs ----------

def examples_tab() -> None:
    examples = load_examples()
    if not examples:
        st.info("No saved runs found. Run `python main.py` to create one in examples/.")
        return
    name = st.selectbox("Saved run", list(examples), help="Real runs saved by main.py.")
    st.caption("A replay of a real run. No API calls are made.")
    render_result(examples[name])


def live_tab() -> None:
    if not live_mode_available():
        st.info(
            "Live planning is turned off here because no API keys are configured. "
            "Clone the repository, add GROQ_API_KEY and TAVILY_API_KEY to .env, "
            "and run `streamlit run app.py` to try your own trip."
        )
        return
    password = os.getenv("APP_PASSWORD")
    if password and st.text_input("Password", type="password") != password:
        st.info("Enter the password to run the planner.")
        return

    with st.form("trip"):
        col1, col2 = st.columns(2)
        origin = col1.text_input("Origin country", "Pakistan")
        destination = col2.text_input("Destination", "Dubai")
        travel_dates = col1.text_input("Travel dates", "December 10-14")
        duration = col2.number_input("Days", min_value=1, max_value=10, value=5)
        travelers = col1.number_input("Travelers", min_value=1, max_value=8, value=2)
        budget = col2.number_input("Budget (USD)", min_value=500, max_value=20000, value=2000, step=100)
        interests = st.multiselect(
            "Interests",
            ["food", "shopping", "beaches", "sightseeing", "culture", "nightlife", "adventure"],
            default=["food", "shopping", "beaches", "sightseeing"],
        )
        hotel_preference = st.selectbox("Hotel", ["3-star", "4-star", "5-star"], index=1)
        submitted = st.form_submit_button("Plan my trip")

    st.caption("A run takes a few minutes and makes real API calls. Flight prices are a hardcoded estimate.")
    if not submitted:
        return

    state: TravelState = make_initial_state(
        origin=origin,
        destination=destination,
        travel_dates=travel_dates,
        duration=int(duration),
        travelers=int(travelers),
        budget=float(budget),
        interests=interests or ["sightseeing"],
        hotel_preference=hotel_preference,
    )
    result: dict = dict(state)
    with st.status("Agents are working...", expanded=True) as status:
        try:
            for mode, chunk in get_graph().stream(state, stream_mode=["updates", "values"]):
                if mode == "updates":
                    for node_name in chunk:
                        st.write(f"Finished: {node_name}")
                else:
                    result = cast(dict, chunk)
        except Exception as error:
            status.update(label="The planner stopped with an unexpected error", state="error")
            st.error(f"{type(error).__name__}: {error}")
            return
        status.update(label="Done", state="complete", expanded=False)

    render_result(result)
    st.download_button(
        "Download this run as JSON",
        json.dumps(result, indent=2, ensure_ascii=False),
        file_name="travel_plan.json",
        mime="application/json",
    )


def about_tab() -> None:
    st.markdown(
        "Seven agents share one LangGraph state. The LLM agents propose; code checks every "
        "price, hour limit and budget rule. When the plan is over budget, the budget agent "
        "cuts only the over-budget categories and sends the graph back to the hotel agent, "
        "at most twice."
    )
    st.graphviz_chart(ARCHITECTURE_DOT)
    st.markdown(
        "**Known limitation:** prices come from search snippets and are not verified, so "
        "very low prices (for example a 4-star hotel at about $25/night) can be accepted. "
        "See the README for the full list."
    )


st.title("Multi-Agent Travel Planner")
st.caption("LangGraph · Groq · Tavily · 7 agents · budget revision loop · 33 tests")
tab_examples, tab_live, tab_about = st.tabs(["Example runs", "Plan a trip (live)", "How it works"])
with tab_examples:
    examples_tab()
with tab_live:
    live_tab()
with tab_about:
    about_tab()