from llm import invoke_structured
from schemas import DestinationResearch
from state import TravelState, make_initial_state
from tools.web_search_tool import search_web


def destination_researcher(state: TravelState) -> dict:
    destination = state["destination"]
    interests = ", ".join(state.get("interests", []))
    errors: list[str] = []
    snippets: list[str] = []
    sources: list[str] = []

    origin = state.get("origin", "")
    queries = [
        f"{destination} best areas to stay for tourists",
        f"{destination} getting around local transportation for tourists",
        f"{destination} best time to visit and travel tips",
        f"{destination} visa requirements for {origin} passport holders",
    ]
    for query in queries:
        result = search_web(query, max_results=3)
        if result["error"]:
            errors.append(f"destination_researcher: search failed for '{query}': {result['error']}")
            continue
        for item in result["results"]:
            snippets.append(f"- {item['title']}: {item['snippet']}")
            sources.append(item["url"])

    search_text = "\n".join(snippets) if snippets else "No search results were available."

    prompt = f"""You are a travel destination researcher.
Trip: {destination}, {state.get("travel_dates", "dates not given")}, \
{state.get("duration", "?")} days, {state.get("travelers", "?")} travelers \
coming from {origin or "an unspecified country"}.
Traveler interests: {interests}.

Use the web search snippets below as your main evidence. Where they are
silent, use general knowledge, but keep costs as honest estimates and do not
invent specific facts you are unsure about.

Rules:
- Visa and entry rules depend on nationality. Only describe what applies to
  travelers from {origin or "the origin country"}. If the snippets do not
  clearly cover it, say so and tell the traveler to check official sources.
- estimated_daily_spend_usd_per_person must EXCLUDE accommodation and flights,
  because other agents price those separately.

Search snippets:
{search_text}
"""

    try:
        research = invoke_structured(DestinationResearch, prompt)
    except Exception as error:
        errors.append(f"destination_researcher: LLM step failed: {error}")
        return {"destination_research": {}, "errors": errors}

    data = research.model_dump()

    if isinstance(research, DestinationResearch):
        data = research.model_dump()
    else:
        data = DestinationResearch.model_validate(research).model_dump()

    data["sources"] = sorted(set(sources))
    return {"destination_research": data, "errors": errors}


if __name__ == "__main__":
    import json

    sample_state = make_initial_state(
        origin="Pakistan",
        destination="Dubai",
        travel_dates="December 10-14",
        duration=5,
        travelers=2,
        budget=2000.0,
        interests=["food", "shopping", "beaches", "sightseeing"],
        hotel_preference="4-star",
    )
    print(json.dumps(destination_researcher(sample_state), indent=2, ensure_ascii=False))