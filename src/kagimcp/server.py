import textwrap
from typing import Literal, cast
import os
from concurrent.futures import ThreadPoolExecutor

from kagiapi import KagiClient
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
    try:
        if not queries:
            raise ValueError("Search called with no queries.")

        with ThreadPoolExecutor() as executor:
            results = list(executor.map(kagi_client.search, queries, timeout=10))

        return format_search_results(queries, results)

    except Exception as e:
        return f"Error: {str(e) or repr(e)}"


def format_search_results(queries: list[str], responses) -> str:
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
        results = [result for result in response["data"] if result["t"] == 0]

        # published date is not always present
        formatted_results_list = [
            result_template.format(
                result_number=result_number,
                title=result["title"],
                url=result["url"],
                published=result.get("published", "Not Available"),
                snippet=result["snippet"],
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
    try:
        if not url:
            raise ValueError("Summarizer called with no URL.")

        engine = os.environ.get("KAGI_SUMMARIZER_ENGINE", "cecil")

        valid_engines = {"cecil", "agnes", "daphne", "muriel"}
        if engine not in valid_engines:
            raise ValueError(
                f"Summarizer configured incorrectly, invalid summarization engine set: {engine}. Must be one of the following: {valid_engines}"
            )

        engine = cast(Literal["cecil", "agnes", "daphne", "muriel"], engine)

        summary = kagi_client.summarize(
            url,
            engine=engine,
            summary_type=summary_type,
            target_language=target_language,
        )["data"]["output"]

        return summary

    except Exception as e:
        return f"Error: {str(e) or repr(e)}"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
