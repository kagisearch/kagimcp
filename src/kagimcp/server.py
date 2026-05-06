from typing import Any, Literal, cast
from datetime import date
import json
import os
import argparse

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)
from urllib3.util.retry import Retry
from openapi_client import (
    ApiClient,
    Configuration,
    ExtractApi,
    ExtractRequest,
    PageInput,
    SearchApi,
    SearchRequest,
    SearchRequestExtract,
    SearchRequestFilters,
    SearchRequestLens,
)
from openapi_client.exceptions import ApiException
from fastmcp import FastMCP
from fastmcp.server.transforms.tool_transform import ToolTransform
from fastmcp.tools.tool_transform import ArgTransformConfig, ToolTransformConfig
from pydantic import Field

_api_key = os.environ.get("KAGI_API_KEY")
if not _api_key:
    raise ValueError("KAGI_API_KEY environment variable is required")

# TODO: summarizer and fastgpt are not yet live on v1, so they're called directly against the v0 endpoint for now

_V0_BASE_URL = "https://kagi.com/api/v0"


def _timeout_from_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number (seconds), got: {raw!r}")
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got: {value}")
    return value


_SEARCH_TIMEOUT = _timeout_from_env("KAGI_SEARCH_TIMEOUT", 10.0)
_EXTRACT_TIMEOUT = _timeout_from_env("KAGI_EXTRACT_TIMEOUT", 30.0)
_SUMMARIZER_TIMEOUT = _timeout_from_env("KAGI_SUMMARIZER_TIMEOUT", 30.0)
_FASTGPT_TIMEOUT = _timeout_from_env("KAGI_FASTGPT_TIMEOUT", 10.0)


def _max_retries_from_env() -> int:
    raw = os.environ.get("KAGI_MAX_RETRIES", "").strip()
    if not raw:
        return 2
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"KAGI_MAX_RETRIES must be an integer, got: {raw!r}")
    if value < 0:
        raise ValueError(f"KAGI_MAX_RETRIES must be >= 0, got: {value}")
    return value


_MAX_RETRIES = _max_retries_from_env()
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

_config = Configuration(access_token=_api_key)
_config.retries = Retry(
    total=_MAX_RETRIES,
    backoff_factor=0.5,
    backoff_max=10.0,
    status_forcelist=list(_RETRY_STATUSES),
    allowed_methods=None,
    respect_retry_after_header=True,
    raise_on_status=False,
)
_api_client = ApiClient(_config)
search_api = SearchApi(_api_client)
extract_api = ExtractApi(_api_client)


@retry(
    stop=stop_after_attempt(_MAX_RETRIES + 1),
    wait=wait_exponential_jitter(initial=0.5, max=10.0),
    retry=retry_if_exception_type(
        (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError)
    ),
    reraise=True,
)
def _httpx_get_with_retry(
    url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float
) -> httpx.Response:
    response = httpx.get(url, params=params, headers=headers, timeout=timeout)
    if response.status_code in _RETRY_STATUSES:
        response.raise_for_status()  # raises HTTPStatusError → retried
    return response


@retry(
    stop=stop_after_attempt(_MAX_RETRIES + 1),
    wait=wait_exponential_jitter(initial=0.5, max=10.0),
    retry=retry_if_exception_type(
        (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError)
    ),
    reraise=True,
)
def _httpx_post_json_with_retry(
    url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float
) -> httpx.Response:
    response = httpx.post(url, json=json, headers=headers, timeout=timeout)
    if response.status_code in _RETRY_STATUSES:
        response.raise_for_status()  # raises HTTPStatusError → retried
    return response


mcp = FastMCP("kagimcp")


_TRACE_HEADER = "x-kagi-trace"

# Per-tool sets of params that may be hidden from the LLM-facing schema via the
# KAGI_HIDDEN_PARAMS env var. Required params (query, url) are intentionally
# omitted — hiding them would break the tool. Hidden params fall back to their
# function-level defaults.
_HIDEABLE_PARAMS: dict[str, set[str]] = {
    "kagi_search_fetch": {
        "workflow",
        "extract_count",
        "limit",
        "include_domains",
        "exclude_domains",
        "time_relative",
        "after",
        "before",
        "file_type",
    },
}


def _apply_hidden_params() -> None:
    raw = os.environ.get("KAGI_HIDDEN_PARAMS", "").strip()
    if not raw:
        return

    requested = {name.strip() for name in raw.split(",") if name.strip()}
    all_hideable = {param for params in _HIDEABLE_PARAMS.values() for param in params}

    if unknown := requested - all_hideable:
        raise ValueError(
            f"KAGI_HIDDEN_PARAMS contains unknown or non-hideable param(s): "
            f"{sorted(unknown)}. Hideable params: {sorted(all_hideable)}."
        )

    transforms: dict[str, ToolTransformConfig] = {}
    for tool_name, hideable in _HIDEABLE_PARAMS.items():
        if to_hide := requested & hideable:
            transforms[tool_name] = ToolTransformConfig(
                arguments={name: ArgTransformConfig(hide=True) for name in to_hide}
            )

    if transforms:
        mcp.add_transform(ToolTransform(transforms))


_apply_hidden_params()


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
    time_relative: Literal["day", "week", "month"] | None = Field(
        default=None,
        description="Restrict to results published/updated within the last day, week, or month, evaluated server-side. Mutually exclusive with 'after'/'before'.",
    ),
    after: date | None = Field(
        default=None,
        description="Only include results published/updated on or after this date (ISO format, e.g., '2024-01-15').",
    ),
    before: date | None = Field(
        default=None,
        description="Only include results published/updated on or before this date (ISO format, e.g., '2024-12-31').",
    ),
    file_type: str | None = Field(
        default=None,
        description="Restrict to results with this file type (e.g., 'pdf', 'docx', 'xlsx'). Specify the extension without a leading dot.",
    ),
) -> str:
    """Fetch web results for a query using the Kagi Search API. Use for general search and when the user explicitly tells you to 'fetch' results/information. Results are numbered so that a user may refer to a result by a specific number."""
    if not query:
        raise ValueError("Search called with no query.")

    extract = SearchRequestExtract(count=extract_count) if extract_count > 0 else None

    if time_relative and (after or before):
        raise ValueError("'time_relative' is mutually exclusive with 'after'/'before'.")

    lens_fields = {
        "sites_included": include_domains or None,
        "sites_excluded": exclude_domains or None,
        "time_relative": time_relative,
        "file_type": file_type,
    }
    lens = (
        SearchRequestLens(**lens_fields)
        if any(value is not None for value in lens_fields.values())
        else None
    )

    filters = (
        SearchRequestFilters(after=after, before=before) if after or before else None
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
                filters=filters,
            ),
            _request_timeout=_SEARCH_TIMEOUT,
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
        response = _httpx_get_with_retry(
            f"{_V0_BASE_URL}/summarize",
            params=params,
            headers={"Authorization": f"Bot {_api_key}"},
            timeout=_SUMMARIZER_TIMEOUT,
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
def kagi_fastgpt(
    query: str = Field(
        description="The question to answer. Phrase as a natural-language question or instruction; FastGPT runs a web search internally and synthesizes an answer with citations."
    ),
    cache: bool = Field(
        default=True,
        description="Whether Kagi may return a cached answer if available. Set to False to force a fresh answer (counts as a full-cost request).",
    ),
) -> str:
    """Answer a query using Kagi FastGPT. FastGPT performs a live web search and synthesizes an LLM answer with numbered references. Use for factual questions where citations matter."""
    if not query:
        raise ValueError("FastGPT called with no query.")

    try:
        response = _httpx_post_json_with_retry(
            f"{_V0_BASE_URL}/fastgpt",
            json={"query": query, "cache": cache},
            headers={"Authorization": f"Bot {_api_key}"},
            timeout=_FASTGPT_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise ValueError(
            f"Kagi FastGPT API error ({e.response.status_code}): "
            f"{_format_error_body(e.response.text)}{_trace_suffix(e.response.headers)}"
        )
    except httpx.HTTPError as e:
        raise ValueError(f"Kagi FastGPT API error: {e}")

    suffix = _trace_suffix(response.headers)
    body = response.json()
    if errors := body.get("error"):
        raise ValueError(f"Kagi FastGPT API error: {errors}{suffix}")

    data = body.get("data") or {}
    output = data.get("output")
    if not output:
        raise ValueError(f"Kagi FastGPT API returned no output.{suffix}")

    references = data.get("references") or []
    if not references:
        return output

    lines = [output, "", "References:"]
    for i, ref in enumerate(references, start=1):
        title = ref.get("title") or ref.get("url") or ""
        url = ref.get("url") or ""
        lines.append(f"[{i}] {title} — {url}" if url else f"[{i}] {title}")
    return "\n".join(lines)


@mcp.tool()
def kagi_extract(
    url: str = Field(description="The HTTPS URL of the page to extract content from."),
) -> str:
    """Extract the content of a web page as markdown using the Kagi Extract API. Use this to read the full content of a page when needed."""
    if not url:
        raise ValueError("Extract called with no URL.")

    try:
        response = extract_api.extract_content(
            ExtractRequest(pages=[PageInput(url=url)], format="markdown"),
            _request_timeout=_EXTRACT_TIMEOUT,
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
        mcp.run("streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()  # default stdio mode


if __name__ == "__main__":
    main()
