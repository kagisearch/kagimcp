import textwrap
from typing import Literal, cast
import os
from concurrent.futures import ThreadPoolExecutor
import argparse

from kagiapi import KagiClient
from kagiapi.models import SearchResponse
from mcp.server.fastmcp import FastMCP
from pydantic import Field

kagi_client = KagiClient()
mcp = FastMCP("kagimcp", dependencies=["kagiapi", "mcp[cli]"])


@mcp.tool()
def kagi_search_fetch(
    queries: list[str] = Field(
        description="One or more concise, keyword-focused search queries. Include essential context within each query for standalone use."
    ),
) -> str:
    """Fetch web results based on one or more queries using the Kagi Search API. Use for general search and when the user explicitly tells you to 'fetch' results/information. Results are from all queries given. They are numbered continuously, so that a user may be able to refer to a result by a specific number."""
    if not queries:
        raise ValueError("Search called with no queries.")

    try:
        with ThreadPoolExecutor() as executor:
            results = list(executor.map(kagi_client.search, queries, timeout=10))
    except Exception as e:
        raise ValueError(
            f"Error calling Kagi Search API (Currently in beta, make sure you have been granted access. Can be granted by emailing support@kagi.com): {e}"
        )

    return format_search_results(queries, results)


def format_search_results(queries: list[str], responses: list[SearchResponse]) -> str:
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

    per_query_response_strs = []

    start_index = 1
    for query, response in zip(queries, responses):
        # t == 0 is search result, t == 1 is related searches
        if error := response.get("error"):
            per_query_response_strs.append(
                query_response_template.format(
                    query=query, formatted_search_results=f"ERROR: {error}"
                )
            )
            continue
        results = [result for result in response["data"] if result["t"] == 0]

        # published date is not always present
        not_available_str = "Not Available"
        formatted_results_list = [
            result_template.format(
                result_number=result_number,
                title=result.get("title", not_available_str),
                url=result.get("url", not_available_str),
                published=result.get("published", not_available_str),
                snippet=result.get("snippet", not_available_str),
            )
            for result_number, result in enumerate(results, start=start_index)
        ]

        start_index += len(results)

        formatted_results_str = "\n\n".join(formatted_results_list)
        query_response_str = query_response_template.format(
            query=query, formatted_search_results=formatted_results_str
        )
        per_query_response_strs.append(query_response_str)

    return "\n\n".join(per_query_response_strs)


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

    response = kagi_client.summarize(
        url,
        engine=engine,
        summary_type=summary_type,
        target_language=target_language,
    )
    summary = response["data"]["output"]
    if error := response.get("error"):
        raise ValueError(error)

    return summary


@mcp.tool()
def kagi_fastgpt(
    query: str = Field(
        description="A natural-language question or prompt. FastGPT returns a concise answer grounded in live web search with inline citations."
    ),
    cache: bool = Field(
        default=True,
        description="Whether to allow Kagi to serve a cached answer. Set to False to force a fresh search.",
    ),
) -> str:
    """Answer a question using Kagi FastGPT. FastGPT combines live web search with an LLM to produce a short, cited answer. Use for factual questions where a direct synthesized answer with sources is more useful than a raw list of search results. Output includes the answer followed by numbered references."""
    if not query:
        raise ValueError("FastGPT called with no query.")

    # NOTE: kagiapi 0.2.1 serializes `cache` as a JSON string instead of a
    # bool, which the FastGPT endpoint rejects. Call the endpoint directly
    # via the client's authenticated session to sidestep the bug.
    payload: dict = {"query": query, "cache": bool(cache)}
    try:
        http_response = kagi_client.session.post(
            kagi_client.BASE_URL + "/fastgpt",
            json=payload,
            timeout=30,
        )
        http_response.raise_for_status()
        response = http_response.json()
    except Exception as e:
        raise ValueError(f"Error calling Kagi FastGPT API: {e}")

    if error := response.get("error"):
        raise ValueError(error)

    return format_fastgpt_response(response["data"])


def format_fastgpt_response(data: dict) -> str:
    """Format a FastGPT data block as answer text followed by numbered references."""
    output = data.get("output", "").strip()
    references = data.get("references") or []

    if not references:
        return output

    ref_template = textwrap.dedent(
        """
        [{n}] {title}
        {url}
        {snippet}
    """
    ).strip()

    formatted_refs = "\n\n".join(
        ref_template.format(
            n=i,
            title=ref.get("title", "Not Available"),
            url=ref.get("url", "Not Available"),
            snippet=ref.get("snippet", ""),
        )
        for i, ref in enumerate(references, start=1)
    )

    return f"{output}\n\n-----\nReferences:\n-----\n{formatted_refs}"


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
