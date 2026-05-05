from typing import Any, Literal, cast
import json
import os
import argparse

import httpx
from openapi_client import (
    ApiClient,
    Configuration,
    ExtractApi,
    ExtractRequest,
    PageInput,
    SearchApi,
    SearchRequest,
    SearchRequestExtract,
    SearchRequestLens,
)
from openapi_client.exceptions import ApiException
from mcp.server.fastmcp import FastMCP
from pydantic import Field

_api_key = os.environ.get("KAGI_API_KEY")
if not _api_key:
    raise ValueError("KAGI_API_KEY environment variable is required")

# TODO: summarizer is not yet live on v1, so it's called directly against the v0 endpoint for now

_V0_BASE_URL = "https://kagi.com/api/v0"

_api_client = ApiClient(Configuration(access_token=_api_key))
search_api = SearchApi(_api_client)
extract_api = ExtractApi(_api_client)

mcp = FastMCP("kagimcp", dependencies=["openapi_client", "httpx", "mcp[cli]"])


_TRACE_HEADER = "x-kagi-trace"


def _trace_suffix(headers: Any) -> str:
    if not headers:
        return ""
    try:
        trace = headers.get(_TRACE_HEADER)
    except AttributeError:
        return ""
    return f" (trace id: {trace})" if trace else ""


def _format_error_body(body: str) -> str:
    """
    Pull message(s) out of a Kagi error envelope (v1 `errors[].message`, v0 `error[].msg`).
    """
    # TODO: unneeded when moved over to v1 endpoint completely
    try:
        parsed = json.loads(body)
        errors = parsed.get("errors") or parsed.get("error") or []
        return "; ".join(e.get("message") or e.get("msg") for e in errors) or body
    except Exception:
        return body


@mcp.tool()
def kagi_search_fetch(
    query: str = Field(
        description="A concise, keyword-focused search query. Include essential context for standalone use."
    ),
    workflow: Literal["search", "news", "videos", "podcasts", "images"] = Field(
        default="search",
        description="Type of results to return. Use 'news' for current events and recent reporting, 'videos' for video content (e.g. tutorials, talks), 'podcasts' for audio shows, 'images' for image results, or the default 'search' for general web results. Note that 'search' may return a mix of categories (web, news, videos, images) in one response, like a typical SERP; the other workflows return only their single category.",
    ),
    extract_count: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Number of top results to fetch full page content for, inline as markdown.",
    ),
    limit: int = Field(
        default=10,
        ge=1,
        le=1024,
        description="Maximum number of results per category. In the mixed 'search' workflow this caps each category independently, so the total can exceed this number; in single-category workflows it caps total results.",
    ),
    include_domains: list[str] | None = Field(
        default=None,
        description="Restrict results to these domains (e.g., ['docs.python.org', 'github.com']). Overrides any 'site:' operators in the query.",
    ),
    exclude_domains: list[str] | None = Field(
        default=None,
        description="Exclude results from these domains (e.g., ['pinterest.com', 'quora.com']). Overrides any 'site:' operators in the query.",
    ),
) -> str:
    """Fetch web results for a query using the Kagi Search API. Use for general search and when the user explicitly tells you to 'fetch' results/information. Results are numbered so that a user may refer to a result by a specific number."""
    if not query:
        raise ValueError("Search called with no query.")

    extract = SearchRequestExtract(count=extract_count) if extract_count > 0 else None

    lens = (
        SearchRequestLens(
            sites_included=include_domains or None,
            sites_excluded=exclude_domains or None,
        )
        if include_domains or exclude_domains
        else None
    )

    try:
        response = search_api.search_without_preload_content(
            SearchRequest(
                query=query,
                workflow=workflow,
                format="markdown",
                limit=limit,
                extract=extract,
                lens=lens,
            )
        )
    except ApiException as e:
        raise ValueError(
            f"Kagi Search API error ({e.status}): {_format_error_body(e.body or '')}{_trace_suffix(e.headers)}"
        )
    except Exception as e:
        raise ValueError(f"Error calling Kagi Search API: {e}")

    body = response.data.decode("utf-8")
    if response.status >= 400:
        raise ValueError(
            f"Kagi Search API error ({response.status}): {_format_error_body(body)}{_trace_suffix(response.headers)}"
        )

    return body


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
    except httpx.HTTPStatusError as e:
        raise ValueError(
            f"Kagi Summarizer API error ({e.response.status_code}): "
            f"{_format_error_body(e.response.text)}{_trace_suffix(e.response.headers)}"
        )
    except httpx.HTTPError as e:
        raise ValueError(f"Kagi Summarizer API error: {e}")

    suffix = _trace_suffix(response.headers)
    body = response.json()
    if errors := body.get("error"):
        raise ValueError(f"Kagi Summarizer API error: {errors}{suffix}")

    output = body.get("data", {}).get("output")
    if not output:
        raise ValueError(f"Kagi Summarizer API returned no output.{suffix}")
    return output


@mcp.tool()
def kagi_extract(
    url: str = Field(description="The HTTPS URL of the page to extract content from."),
) -> str:
    """Extract the content of a web page as markdown using the Kagi Extract API. Use this to read the full content of a page when needed."""
    if not url:
        raise ValueError("Extract called with no URL.")

    try:
        response = extract_api.extract_content(
            ExtractRequest(pages=[PageInput(url=url)], format="markdown")
        )
    except ApiException as e:
        raise ValueError(
            f"Kagi Extract API error ({e.status}): {_format_error_body(e.body or '')}{_trace_suffix(e.headers)}"
        )
    except Exception as e:
        raise ValueError(f"Error calling Kagi Extract API: {e}")

    trace = response.meta.trace if response.meta else None
    suffix = f" (trace id: {trace})" if trace else ""

    if not (pages := response.data) or not pages[0].markdown:
        if errors := response.errors:
            raise ValueError(f"Kagi Extract API error: {errors}{suffix}")
        raise ValueError(f"Kagi Extract API returned no content.{suffix}")

    return pages[0].markdown


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
