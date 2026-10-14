import os
import time

from ddgs import DDGS
from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()

AD_URL_MARKERS = ("bing.com/aclick", "duckduckgo.com/y.js")
MAX_SNIPPET_CHARS = 400


def _is_ad(url: str) -> bool:
    return any(marker in url for marker in AD_URL_MARKERS)


def _trim_snippets(results: list[dict]) -> list[dict]:
    trimmed = []
    for item in results:
        snippet = " ".join(item["snippet"].split())
        if len(snippet) > MAX_SNIPPET_CHARS:
            snippet = snippet[:MAX_SNIPPET_CHARS].rsplit(" ", 1)[0] + " ..."
        trimmed.append({**item, "snippet": snippet})
    return trimmed


def _search_tavily(query: str, max_results: int) -> list[dict]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not set")
    client = TavilyClient(api_key=api_key)
    response = client.search(query, max_results=max_results, search_depth="basic")
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
        }
        for item in response.get("results", [])
    ]


def _search_ddgs(query: str, max_results: int, retries: int, delay_seconds: float) -> list[dict]:
    last_error = ""
    for attempt in range(retries + 1):
        try:
            with DDGS() as ddgs:
                raw_results = list(ddgs.text(query, max_results=max_results))
            return [
                {
                    "title": item.get("title", ""),
                    "url": item.get("href", ""),
                    "snippet": item.get("body", ""),
                }
                for item in raw_results
                if not _is_ad(item.get("href", ""))
            ]
        except Exception as error:
            last_error = str(error)
            if attempt < retries:
                time.sleep(delay_seconds * (attempt + 1))
    raise RuntimeError(last_error)


def search_web(
    query: str,
    max_results: int = 5,
    retries: int = 2,
    delay_seconds: float = 2.0,
) -> dict:
    tavily_message = ""
    try:
        results = _search_tavily(query, max_results)
        if results:
            return {"source": "tavily", "query": query, "results": _trim_snippets(results),
                    "error": None, "warning": None}
        tavily_message = "no results"
    except Exception as error:
        tavily_message = str(error)

    try:
        results = _search_ddgs(query, max_results, retries, delay_seconds)
        return {"source": "ddgs", "query": query, "results": _trim_snippets(results),
                "error": None, "warning": f"Tavily failed, used ddgs: {tavily_message}"}
    except Exception as error:
        return {"source": "none", "query": query, "results": [],
                "error": f"tavily: {tavily_message}; ddgs: {error}", "warning": None}

    
if __name__ == "__main__":
    output = search_web("best areas to stay in Dubai for tourists", max_results=3)
    print("source:", output["source"], "| error:", output["error"], "| warning:", output["warning"])
    for item in output["results"]:
        print(len(item["snippet"]), "chars |", item["title"], "|", item["url"])