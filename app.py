import json
import os
from pathlib import Path
from typing import cast

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from state import TravelState, make_initial_state

load_dotenv()

EXAMPLES_DIR = Path("examples")
REPO_URL = ""  # add your GitHub repository link here once it exists

STATUS = {
    "within_budget": ("success", ":material/check_circle:", "Within budget"),
    "over_budget_final": ("warning", ":material/warning:", "Over budget after the last revision"),
    "incomplete": ("error", ":material/error:", "Incomplete: an agent failed, so a cost is unknown"),
    "needs_revision": ("info", ":material/autorenew:", "Needs revision"),
}
CATEGORY_LABELS = {
    "flights": "Flights",
    "hotel": "Hotel",
    "activities": "Activities",
    "food": "Food",
    "local_transport": "Local transport",
}
DAY_TYPE_LABELS = {
    "arrival": "Arrival",
    "full": "Full day",
    "departure": "Departure",
    "arrival_and_departure": "Arrival & departure",
}

# Blue border = agent that uses the LLM, orange border = code-only step.
ARCHITECTURE_DOT = """
digraph {
    rankdir=LR; bgcolor="transparent"; pad=0.3; nodesep=0.3; ranksep=0.25; newrank=true;
    node [shape=box, style="rounded,filled", fillcolor="#1a1c24", color="#3987e5", penwidth=2,
          fontname="Helvetica", fontcolor="#f0efec", fontsize=15, margin="0.20,0.12"];
    edge [color="#8b8d98", fontname="Helvetica", fontcolor="#c3c2b7", fontsize=13, arrowsize=0.7, penwidth=1.4];


    subgraph cluster_research {
        label="1 · Research  (runs once)"; labeljust=l; labelloc=b; style="rounded,dashed"; color="#4a4c57";
        fontname="Helvetica"; fontcolor="#c3c2b7"; fontsize=13; margin=12;
        flight [label=<<b>Flights</b><br/><font point-size="12" color="#c3c2b7">tool · no LLM</font>>, color="#d95926"];
        destination [label=<<b>Destination</b><br/><font point-size="12" color="#c3c2b7">LLM + web search</font>>];
    }
    subgraph cluster_plan {
        label="2 · Plan  →  3 · Check  (repeats up to 2×)"; labeljust=l; labelloc=b; style="rounded,dashed"; color="#4a4c57";
        fontname="Helvetica"; fontcolor="#c3c2b7"; fontsize=13; margin=12;
        hotel [label=<<b>Hotel</b><br/><font point-size="12" color="#c3c2b7">LLM + price cap</font>>];
        activities [label=<<b>Activities</b><br/><font point-size="12" color="#c3c2b7">LLM + budget &amp; hours</font>>];
        restaurants [label=<<b>Restaurants</b><br/><font point-size="12" color="#c3c2b7">LLM + meal target</font>>];
        itinerary [label=<<b>Itinerary</b><br/><font point-size="12" color="#c3c2b7">LLM + hour limits</font>>];
        budget [label=<<b>Budget check</b><br/><font point-size="12" color="#c3c2b7">code only</font>>, color="#d95926"];
    }
    flight -> destination -> hotel -> activities -> restaurants -> itinerary -> budget;
    budget:n -> hotel:n [label="  over budget → revise  ", style=dashed, color="#d95926", constraint=false];
}
"""

AGENTS = [
    ("Flights", "No", "Calls the flights tool. Marks flights as a fixed cost."),
    ("Destination", "Yes", "4 web searches: areas, transport, best time, visa rules for the origin country."),
    ("Hotel", "Yes", "LLM picks a hotel; code checks the price against the nightly cap."),
    ("Activities", "Yes", "LLM ranks activities; code keeps them within budget and hours."),
    ("Restaurants", "Yes", "Searches near the hotel and activities, aimed at the meal target."),
    ("Itinerary", "Yes", "LLM groups activities into days; code enforces limits and repairs the plan."),
    ("Budget check", "No", "Adds up real costs, checks each cap, decides whether to revise."),
]
DESIGN_IDEAS = [
    ("The LLM proposes, code verifies",
     "The LLM makes judgment calls (which hotel, what goes together). Code does all the math "
     "and enforces every rule, and the output records who decided (`selected_by`, `planned_by`)."),
    ("Unknown is never zero",
     "A missing cost is `None`. If an agent fails, the budget check says **incomplete** "
     "instead of a false 'within budget'."),
    ("Targeted revisions",
     "Each revision cuts the budget share only for the categories over their cap, then "
     "re-runs the planning agents. At most 2 revisions, so the loop always ends."),
    ("Guaranteed-valid LLM output",
     "Every LLM call uses Groq structured outputs with strict mode (constrained decoding), "
     "plus retries that match the error type."),
]

st.set_page_config(page_title="Multi-Agent Travel Planner", page_icon=":material/flight:", layout="wide")


# ---------- helpers ----------

def md(text: object) -> str:
    """Escape $ so Streamlit doesn't render text between two $ signs as a math formula."""
    return str(text).replace("$", r"\$")


def money(value: float | None) -> str:
    return "unknown" if value is None else f"${value:,.0f}"


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


def example_label(name: str, result: dict) -> str:
    analysis = result.get("budget_analysis", {})
    status = STATUS.get(analysis.get("status", ""), ("", "", "unknown"))[2].lower()
    revisions = result.get("revision_count", 0)
    return f"{money(result.get('budget'))} budget · {status} · {revisions} revision(s)   ({name})"


# ---------- result sections ----------

def render_summary(result: dict) -> None:
    analysis = result.get("budget_analysis", {})
    st.subheader(
        f"{result.get('origin')} → {result.get('destination')} · {result.get('travel_dates')} · "
        f"{result.get('travelers')} travelers"
    )
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total cost", money(analysis.get("total_usd")), border=True)
    col2.metric("Budget", money(result.get("budget")), border=True)
    col3.metric("Remaining", money(analysis.get("remaining_usd")), border=True)
    col4.metric("Revisions", result.get("revision_count", 0), border=True)

    kind, icon, message = STATUS.get(analysis.get("status", ""), ("info", ":material/info:", "Unknown status"))
    getattr(st, kind)(message, icon=icon)


def render_revision_story(result: dict) -> None:
    if not result.get("revision_count"):
        return
    with st.container(border=True):
        st.markdown("**:material/autorenew: What the revision loop did**")
        cuts: dict[str, int] = result.get("category_cuts") or {}
        if cuts:
            cut_text = ", ".join(f"{CATEGORY_LABELS.get(k, k).lower()} {v}×" for k, v in cuts.items())
            st.markdown(f"The first plan was over budget, so the budget check lowered the share for: **{cut_text}**.")
        if result.get("revision_notes"):
            st.caption(md(f"Last note sent to the agents: {result['revision_notes']}"))


def render_budget(result: dict) -> None:
    analysis = result.get("budget_analysis", {})
    rows = analysis.get("breakdown", [])
    if not rows:
        st.warning("No budget analysis is available.")
        return
    for row in rows:
        label = CATEGORY_LABELS.get(row["category"], row["category"])
        actual, cap = row["actual_usd"], row["cap_usd"]
        if cap is None:
            st.markdown(md(f"**{label}** · {money(actual)} · fixed cost"))
            continue
        over = row["over_cap_usd"]
        flag = f"  :orange-badge[:material/warning: {md(money(over))} over cap]" if over else ""
        st.markdown(md(f"**{label}** · {money(actual)} of {money(cap)}") + flag)
        st.progress(min((actual or 0) / cap, 1.0) if cap else 0.0)
    if analysis.get("local_transport_basis"):
        st.caption(md(f"Local transport is a {analysis['local_transport_basis']}."))
    with st.expander("Budget table"):
        table = [
            {
                "Category": CATEGORY_LABELS.get(row["category"], row["category"]),
                "Actual": money(row["actual_usd"]),
                "Cap": money(row["cap_usd"]) if row["cap_usd"] is not None else "fixed",
                "Over cap": money(row["over_cap_usd"]) if row["over_cap_usd"] else "",
            }
            for row in rows
        ]
        st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")


def render_hotel(result: dict) -> None:
    hotel = result.get("selected_hotel", {})
    with st.container(border=True):
        st.markdown("**:material/hotel: Hotel**")
        if not hotel:
            st.warning("No hotel was selected.")
            return
        st.markdown(md(f"### {hotel.get('name')}"))
        st.markdown(md(f":blue-badge[{hotel.get('star_rating', '?')}-star]  {hotel.get('area')}"))
        st.markdown(md(
            f"**${hotel.get('estimated_price_per_night_usd', 0):,.0f}**/night × {hotel.get('nights')} nights "
            f"= **${hotel.get('total_stay_cost_usd', 0):,.0f}**"
        ))
        st.caption(md(
            f"Cap ${hotel.get('nightly_cap_usd', 0):,.0f}/night · chosen by {hotel.get('selected_by')}"
        ))
        st.markdown(":orange-badge[:material/search: Price from web search, not verified]")
        st.caption(md(f"Evidence: {hotel.get('price_evidence', 'not given')}"))


def render_visa(result: dict) -> None:
    notes = result.get("destination_research", {}).get("visa_and_entry_notes")
    if not notes:
        return
    with st.container(border=True):
        st.markdown("**:material/badge: Visa and entry**")
        st.markdown(md(notes))


def render_day(day: dict) -> None:
    used = day["activity_hours"] + day["transit_hours"]
    st.markdown(md(f"**{day['area_focus']}** · {used:g} of {day['capacity_hours']} activity hours"))
    st.progress(min(used / day["capacity_hours"], 1.0) if day["capacity_hours"] else 0.0)
    if day["activities"]:
        for activity in day["activities"]:
            st.markdown(md(
                f"- :material/place: **{activity['name']}** · {activity['location']} · "
                f"{activity['duration_hours']:g} h · ${activity['total_cost_usd']:,.0f} for the group"
            ))
    else:
        st.markdown("- :material/self_improvement: Free time")
    for meal in day["meals"]:
        place = meal["restaurant"] or "no restaurant found"
        st.markdown(md(
            f"- :material/restaurant: {meal['meal'].title()}: **{place}** · "
            f"${meal['cost_for_group_usd']:,.0f} · {meal['match']}"
        ))
    st.caption(md(day["reasoning"]))


def render_itinerary(result: dict) -> None:
    itinerary = result.get("itinerary", {})
    days = itinerary.get("days", [])
    st.markdown("#### :material/calendar_month: Day-by-day plan")
    if not days:
        st.warning("No itinerary was produced.")
        return
    st.caption(
        f"Planned by: {itinerary.get('planned_by')} · "
        f"{itinerary.get('planned_activity_hours')} of {itinerary.get('capacity_hours')} activity hours used"
    )
    tabs = st.tabs([
        f"Day {day['day_number']} · {DAY_TYPE_LABELS.get(day['day_type'], day['day_type'])}" for day in days
    ])
    for tab, day in zip(tabs, days):
        with tab:
            render_day(day)
    unscheduled = itinerary.get("unscheduled_activities", [])
    if unscheduled:
        names = ", ".join(a["name"] for a in unscheduled)
        st.caption(md(f"Didn't fit the daily hour limits: {names}"))


def render_result(result: dict) -> None:
    render_summary(result)
    render_revision_story(result)

    left, right = st.columns([3, 2], gap="large")
    with left:
        render_itinerary(result)
    with right:
        st.markdown("#### :material/payments: Budget")
        render_budget(result)
        render_hotel(result)
        render_visa(result)

    errors = result.get("errors", [])
    with st.expander(f"Errors and warnings ({len(errors)})", expanded=bool(errors)):
        for error in errors:
            st.markdown(md(f"- {error}"))
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
    names = list(examples)
    default = next((i for i, n in enumerate(names) if "revision" in n), 0)
    name = st.selectbox(
        "Saved run",
        names,
        index=default,
        format_func=lambda n: example_label(n, examples[n]),
        help="Real runs saved by main.py. No API calls are made.",
    )
    render_result(examples[name])


def live_tab() -> None:
    if not live_mode_available():
        st.info(
            "Live planning is turned off here because no API keys are configured. "
            "Clone the repository, add GROQ_API_KEY and TAVILY_API_KEY to .env, "
            "and run `streamlit run app.py` to try your own trip.",
            icon=":material/key_off:",
        )
        return
    password = os.getenv("APP_PASSWORD")
    if password and st.text_input("Password", type="password") != password:
        st.info("Enter the password to run the planner.")
        return

    with st.form("trip", border=True):
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
        submitted = st.form_submit_button("Plan my trip", type="primary", icon=":material/travel_explore:")

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
                    for node_name, update in cast(dict, chunk).items():
                        st.write(f":material/check: {node_name}")
                        update = update or {}
                        if update.get("budget_analysis", {}).get("needs_revision"):
                            st.write(md(
                                f":material/autorenew: **Over budget → revision {update['revision_count']}:** "
                                f"{update['revision_notes']}"
                            ))
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
        icon=":material/download:",
    )


def about_tab() -> None:
    steps = [
        (":material/travel_explore:", "1 · Research",
         "Flights are priced once, and the destination is researched with web search."),
        (":material/edit_calendar:", "2 · Plan",
         "Hotel, activities and restaurants are found, then arranged into a day-by-day plan."),
        (":material/fact_check:", "3 · Check & revise",
         "Code adds up the real costs. If the trip is over budget, it cuts the over-budget "
         "share and re-plans, at most twice."),
    ]
    for column, (icon, title, text) in zip(st.columns(3), steps):
        with column.container(border=True, height="stretch"):
            st.markdown(f"#### {icon} {title}")
            st.write(text)

    st.markdown("#### The agent graph")
    st.graphviz_chart(ARCHITECTURE_DOT)
    st.caption(
        "A trip request goes in on the left; the final plan comes out of the budget check. "
        "Blue border: agent that uses the LLM (with code checks). "
        "Orange border: code-only step. Dashed orange arrow: the budget revision loop."
    )

    st.markdown("#### Who does what")
    st.dataframe(
        pd.DataFrame(AGENTS, columns=["Agent", "Uses LLM", "Job"]),
        hide_index=True,
        width="stretch",
    )

    st.markdown("#### Key design ideas")
    for title, text in DESIGN_IDEAS:
        with st.expander(title):
            st.markdown(text)

    st.warning(md(
        "**Known limitation:** prices come from search snippets and are not verified, so "
        "very low prices (for example a 4-star hotel at about $25/night) can be accepted. "
        "See the README for the full list."
    ), icon=":material/report:")


def sidebar() -> None:
    with st.sidebar:
        st.markdown("### :material/timer: 2-minute review")
        st.markdown(
            "1. **Example runs:** see a real run, including what the revision loop changed.\n"
            "2. **How it works:** the agent graph and the key design decisions.\n"
            "3. **Plan a trip:** run it live (needs API keys)."
        )
        st.divider()
        st.markdown("**Stack:** LangGraph · Groq (`gpt-oss-120b`) · Tavily · Pydantic · Streamlit")
        st.markdown("**Quality:** 33 pytest tests, no API calls needed")
        if REPO_URL:
            st.link_button("View the code on GitHub", REPO_URL, icon=":material/code:")


sidebar()
st.title(":material/flight_takeoff: Multi-Agent Travel Planner")
st.markdown(
    "Seven AI agents plan a trip, check every cost against the budget, and "
    "**revise the plan themselves** when it goes over."
)
st.markdown(
    ":blue-badge[LangGraph] :blue-badge[Groq · gpt-oss-120b] :blue-badge[Tavily search] "
    ":gray-badge[7 agents] :gray-badge[Budget revision loop] :gray-badge[33 tests]"
)
tab_examples, tab_live, tab_about = st.tabs([
    ":material/play_circle: Example runs",
    ":material/travel_explore: Plan a trip (live)",
    ":material/account_tree: How it works",
])
with tab_examples:
    examples_tab()
with tab_live:
    live_tab()
with tab_about:
    about_tab()