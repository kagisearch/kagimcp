import textwrap
from typing import Literal, cast
import os
import argparse

import httpx
from openapi_client import (
    ApiClient,
    Configuration,
    Search200Response,
    SearchApi,
    SearchRequest,
)
from mcp.server.fastmcp import FastMCP
from pydantic import Field

_api_key = os.environ.get("KAGI_API_KEY")
if not _api_key:
    raise ValueError("KAGI_API_KEY environment variable is required")

# TODO: summarizer is not yet live on v1, so it's called directly against the v0 endpoint for now

_V0_BASE_URL = "https://kagi.com/api/v0"

_api_client = ApiClient(Configuration(access_token=_api_key))
search_api = SearchApi(_api_client)

mcp = FastMCP("kagimcp", dependencies=["openapi_client", "httpx", "mcp[cli]"])


@mcp.tool()
def kagi_search_fetch(
    query: str = Field(
        description="A concise, keyword-focused search query. Include essential context for standalone use."
    ),
) -> str:
    """Fetch web results for a query using the Kagi Search API. Use for general search and when the user explicitly tells you to 'fetch' results/information. Results are numbered so that a user may refer to a result by a specific number."""
    if not query:
        raise ValueError("Search called with no query.")

    try:
        response = search_api.search(SearchRequest(query=query, limit=10))
    except Exception as e:
        raise ValueError(
            f"Error calling Kagi Search API (Currently in beta, make sure you have been granted access. Can be granted by emailing support@kagi.com): {e}"
        )

    return format_search_results(query, response)


def format_search_results(query: str, response: Search200Response) -> str:
    """Formatting of results for response. Need to consider both LLM and human parsing."""

    result_template = textwrap.dedent(
        """
        {result_number}: {title}
        {url}
        Published Date: {published}
        {snippet}
    """
    ).strip()

    query_response_template = textwrap.dedent(
        """
        -----
        Results for search query "{query}":
        -----
        {formatted_search_results}
    """
    ).strip()

    not_available_str = "Not Available"
    results = (response.data.search if response.data else None) or []

    formatted_results_list = [
        result_template.format(
            result_number=result_number,
            title=result.title or not_available_str,
            url=result.url or not_available_str,
            published=result.time or not_available_str,
            snippet=result.snippet or not_available_str,
        )
        for result_number, result in enumerate(results, start=1)
    ]

    return query_response_template.format(
        query=query,
        formatted_search_results="\n\n".join(formatted_results_list),
    )


@mcp.tool()
def kagi_summarizer(
    url: str = Field(description="A URL to a document to summarize."),
    summary_type: Literal["summary", "takeaway"] = Field(
        default="summary",
        description="Type of summary to produce. Options are 'summary' for paragraph prose and 'takeaway' for a bulleted list of key points.",
    ),
    target_language: str | None = Field(
        default=None,
        description="Desired output language using language codes (e.g., 'EN' for English). If not specified, the document's original language influences the output.",
    ),
) -> str:
    """Summarize content from a URL using the Kagi Summarizer API. The Summarizer can summarize any document type (text webpage, video, audio, etc.)"""
    if not url:
        raise ValueError("Summarizer called with no URL.")

    engine = os.environ.get("KAGI_SUMMARIZER_ENGINE", "cecil")

    valid_engines = {"cecil", "agnes", "daphne", "muriel"}
    if engine not in valid_engines:
        raise ValueError(
            f"Summarizer configured incorrectly, invalid summarization engine set: {engine}. Must be one of the following: {valid_engines}"
        )

    engine = cast(Literal["cecil", "agnes", "daphne", "muriel"], engine)

    params: dict[str, str] = {
        "url": url,
        "engine": engine,
        "summary_type": summary_type,
    }
    if target_language is not None:
        params["target_language"] = target_language

    try:
        response = httpx.get(
            f"{_V0_BASE_URL}/summarize",
            params=params,
            headers={"Authorization": f"Bot {_api_key}"},
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise ValueError(f"Kagi Summarizer API error: {e}")

    body = response.json()
    if errors := body.get("error"):
        raise ValueError(f"Kagi Summarizer API error: {errors}")

    output = body.get("data", {}).get("output")
    if not output:
        raise ValueError("Kagi Summarizer API returned no output.")
    return output


def main():
    parser = argparse.ArgumentParser(description="Kagi MCP Server")
    parser.add_argument(
        "--http", action="store_true", help="Use HTTP transport instead of stdio"
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port to listen on (default: 8000)"
    )
    args = parser.parse_args()

    if args.http:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run("streamable-http")
    else:
        mcp.run()  # default stdio mode


if __name__ == "__main__":
    main()
