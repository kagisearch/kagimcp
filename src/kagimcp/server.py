from typing import Any, Literal
from datetime import date
import asyncio
import json
import logging
import os
import argparse
from urllib.request import urlopen

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
from fastmcp.server.auth import AccessToken, RemoteAuthProvider, TokenVerifier
from mcp.server.auth.routes import build_resource_metadata_url, cors_middleware
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from fastmcp.server.dependencies import get_access_token, get_http_request
from fastmcp.server.transforms.tool_transform import ToolTransform
from fastmcp.tools.tool_transform import ArgTransformConfig, ToolTransformConfig
from pydantic import AnyHttpUrl, Field
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version

try:
    _USER_AGENT = f"KagiMCP/{version('kagimcp')}"
except PackageNotFoundError:
    _USER_AGENT = "KagiMCP"

# Optional fallback for stdio / single-tenant use. In HTTP mode the key is read
# per-request from the Authorization header instead.
_api_key_env = os.environ.get("KAGI_API_KEY")

# Optional base-URL override
_api_host = os.environ.get("KAGI_API_HOST", "").strip() or None


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


class _KagiKeyPassthroughVerifier(TokenVerifier):
    """No token verification happens on this server, it is passed through to the upstream Search API"""

    async def verify_token(self, token: str) -> AccessToken | None:
        token = token.strip()
        if not token:
            return None
        return AccessToken(token=token, client_id="kagi-user", scopes=[])


def _resolve_api_key() -> str:
    try:
        access = get_access_token()
    except RuntimeError:
        access = None
    if access and access.token:
        return access.token
    if _api_key_env:
        return _api_key_env
    raise ValueError(
        "No Kagi API key found. Send `Authorization: Bearer <key>` or set KAGI_API_KEY."
    )


_AUTH_FAILURE_STATE_KEY = "_kagi_upstream_auth_rejected"


def _mark_upstream_auth_failure(status: int | None) -> None:
    if status != 401:
        return
    try:
        request = get_http_request()
    except RuntimeError:
        return  # Stdio keeps the existing tool-error behavior.
    setattr(request.state, _AUTH_FAILURE_STATE_KEY, True)


class _KagiAuthFailureMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        scope.setdefault("state", {})[_AUTH_FAILURE_STATE_KEY] = False
        replaced = False

        async def send_response(message: Message) -> None:
            nonlocal replaced
            if replaced:
                return  # Discard the original wrapped tool-error body.
            if message["type"] == "http.response.start" and scope["state"].get(
                _AUTH_FAILURE_STATE_KEY
            ):
                # JSON response mode waits for the tool before sending headers.
                replaced = True
                mcp_path = scope["app"].state.path
                resource_url = AnyHttpUrl(
                    f"{str(_MCP_PUBLIC_URL).rstrip('/')}/{mcp_path.lstrip('/')}"
                )
                metadata_url = build_resource_metadata_url(resource_url)
                response = JSONResponse(
                    {"error": "invalid_token"},
                    status_code=401,
                    headers={
                        "WWW-Authenticate": (
                            'Bearer error="invalid_token", '
                            f'resource_metadata="{metadata_url}"'
                        ),
                        "Cache-Control": "no-store",
                    },
                )
                await response(scope, receive, send)
                return
            await send(message)

        await self.app(scope, receive, send_response)


@lru_cache(maxsize=128)
def _clients_for(key: str) -> tuple[SearchApi, ExtractApi]:
    config = Configuration(access_token=key, host=_api_host)
    config.retries = Retry(
        total=_MAX_RETRIES,
        backoff_factor=0.5,
        backoff_max=10.0,
        status_forcelist=list(_RETRY_STATUSES),
        allowed_methods=None,
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    api_client = ApiClient(config)
    api_client.user_agent = _USER_AGENT
    return SearchApi(api_client), ExtractApi(api_client)


_MCP_PUBLIC_URL = AnyHttpUrl(
        os.environ.get("KAGI_MCP_PUBLIC_URL", "https://mcp.kagi.com")
)
_OAUTH_ISSUER = os.environ.get("KAGI_OAUTH_ISSUER", "https://account.kagi.com").rstrip(
    "/"
)
_OAUTH_METADATA_URL = os.environ.get(
    "KAGI_OAUTH_METADATA_URL", f"{_OAUTH_ISSUER}/.well-known/openid-configuration"
)
_OAUTH_RESOURCE_SCOPES = [
    "openid",
    "profile",
    "email",
    "urn:zitadel:iam:org:project:id:393794653092071821:aud",
]


class _IssuerPreservingRemoteAuthProvider(RemoteAuthProvider):
    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        routes = super().get_routes(mcp_path)
        resource_url = self._get_resource_url(mcp_path)
        if resource_url is None:
            return routes

        # The SDK normalizes bare AnyHttpUrl origins with a trailing slash.
        # Kagi's issuer has none; OAuth issuer comparisons must be exact.
        metadata = {
            "resource": str(resource_url),
            "authorization_servers": [_OAUTH_ISSUER],
            "scopes_supported": _OAUTH_RESOURCE_SCOPES,
            "bearer_methods_supported": ["header"],
            "resource_name": "Kagi Search API MCP",
        }

        async def protected_resource_metadata(_request: Request) -> JSONResponse:
            return JSONResponse(metadata)

        endpoint = cors_middleware(protected_resource_metadata, ["GET", "OPTIONS"])
        return [
            Route(route.path, endpoint=endpoint, methods=["GET", "OPTIONS"])
            for route in routes
        ] + [
            Route(
                "/.well-known/oauth-protected-resource",
                endpoint=endpoint,
                methods=["GET", "OPTIONS"],
            )
        ]

mcp = FastMCP(
    "kagimcp",
    auth=_IssuerPreservingRemoteAuthProvider(
        token_verifier=_KagiKeyPassthroughVerifier(),
        authorization_servers=[AnyHttpUrl(_OAUTH_ISSUER)],
        base_url=_MCP_PUBLIC_URL,
        scopes_supported=_OAUTH_RESOURCE_SCOPES,
        resource_name="Kagi Search API MCP",
    ),
)


def _fetch_oauth_authorization_server_metadata() -> dict[str, Any]:
    with urlopen(_OAUTH_METADATA_URL, timeout=5) as response:
        metadata = json.load(response)

    if not isinstance(metadata, dict) or metadata.get("issuer") != _OAUTH_ISSUER:
        raise ValueError("OAuth metadata issuer does not match the advertised issuer")
    if not metadata.get("authorization_endpoint") or not metadata.get("token_endpoint"):
        raise ValueError("OAuth metadata is missing authorization or token endpoints")

    # We do not support dynamic client registration at the moment, so we drop this field.
    metadata.pop("registration_endpoint", None)
    return metadata


_oauth_metadata: dict[str, Any] | None = None
_oauth_metadata_loaded = False
_oauth_metadata_lock = asyncio.Lock()


@mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
async def oauth_authorization_server_metadata(_request: Request) -> JSONResponse:
    global _oauth_metadata, _oauth_metadata_loaded

    if not _oauth_metadata_loaded:
        async with _oauth_metadata_lock:
            if not _oauth_metadata_loaded:
                try:
                    _oauth_metadata = await asyncio.to_thread(
                        _fetch_oauth_authorization_server_metadata
                    )
                except (OSError, ValueError) as exc:
                    logging.getLogger(__name__).warning(
                        "Failed to read authorization server metadata from %s: %s",
                        _OAUTH_METADATA_URL,
                        exc,
                    )
                _oauth_metadata_loaded = True

    if _oauth_metadata is None:
        return JSONResponse(
            {"error": "OAuth metadata unavailable"},
            status_code=503,
            headers={"Access-Control-Allow-Origin": "*"},
        )

    return JSONResponse(_oauth_metadata, headers={"Access-Control-Allow-Origin": "*"})


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
        "lens_id",
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


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def _trace_suffix(headers: Any) -> str:
    if not headers:
        return ""
    try:
        trace = headers.get(_TRACE_HEADER)
    except AttributeError:
        return ""
    return f" (trace id: {trace})" if trace else ""


def _format_error_body(body: str) -> str:
    """Pull message(s) out of a Kagi v1 error envelope (`errors[].message`)."""
    try:
        parsed = json.loads(body)
        errors = parsed.get("errors") or []
        return "; ".join(e.get("message", "") for e in errors) or body
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
    lens_id: str | None = Field(
        default=None,
        description=(
            "Apply a Kagi lens to narrow the search to a curated set of sources. "
            "Built-in lens IDs: "
            "'2' (Academic — education/.edu domains), "
            "'1' (Forums — discussion forums across the web), "
            "'15' (Programming — official programming language sites and forums), "
            "'29' (News 360 — multi-perspective coverage of global news), "
            "'120' (Recipes — high-quality recipe sites, English), "
            "'107' (Small Web — noncommercial domains and topics). "
            "You may also pass a custom lens ID or full URL from https://kagi.com/settings/lenses "
            "(only shareable lenses work). "
            "Mutually exclusive with 'include_domains', 'exclude_domains', 'time_relative', "
            "and 'file_type'; use those args or 'lens_id', not both."
        ),
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
    if lens_id and any(v is not None for v in lens_fields.values()):
        raise ValueError(
            "'lens_id' is mutually exclusive with 'include_domains', 'exclude_domains', "
            "'time_relative', and 'file_type' (the server ignores 'lens_id' when any of "
            "those are set). Use one or the other."
        )
    lens = (
        SearchRequestLens(**lens_fields)
        if any(value is not None for value in lens_fields.values())
        else None
    )

    filters = (
        SearchRequestFilters(after=after, before=before) if after or before else None
    )

    search_api, _ = _clients_for(_resolve_api_key())
    try:
        response = search_api.search_without_preload_content(
            SearchRequest(
                query=query,
                workflow=workflow,
                format="markdown",
                limit=limit,
                extract=extract,
                lens_id=lens_id,
                lens=lens,
                filters=filters,
            ),
            _request_timeout=_SEARCH_TIMEOUT,
        )
    except ApiException as e:
        _mark_upstream_auth_failure(e.status)
        raise ValueError(
            f"Kagi Search API error ({e.status}): {_format_error_body(e.body or '')}{_trace_suffix(e.headers)}"
        )
    except Exception as e:
        raise ValueError(f"Error calling Kagi Search API: {e}")

    _mark_upstream_auth_failure(response.status)
    body = response.data.decode("utf-8")
    if response.status >= 400:
        raise ValueError(
            f"Kagi Search API error ({response.status}): {_format_error_body(body)}{_trace_suffix(response.headers)}"
        )

    return body


@mcp.tool()
def kagi_extract(
    url: str = Field(description="The HTTPS URL of the page to extract content from."),
) -> str:
    """Extract the content of a web page as markdown using the Kagi Extract API. Use this to read the full content of a page when needed."""
    if not url:
        raise ValueError("Extract called with no URL.")

    _, extract_api = _clients_for(_resolve_api_key())
    try:
        # JSON mode returns a structured envelope whose page payload is still markdown.
        response = extract_api.extract_content(
            ExtractRequest(pages=[PageInput(url=url)], format="json"),
            _request_timeout=_EXTRACT_TIMEOUT,
        )
    except ApiException as e:
        _mark_upstream_auth_failure(e.status)
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
    parser.add_argument(
        "--cors-origins",
        type=str,
        help="Comma-separated list of allowed CORS origins for HTTP mode "
        "(e.g. 'https://app.example.com,https://localhost:3000'). "
        "Only applies with --http; omit to disable CORS.",
    )
    args = parser.parse_args()

    if args.http:
        middleware: list[Middleware] = []

        if args.cors_origins:
            from starlette.middleware.cors import CORSMiddleware

            origins = [o.strip() for o in args.cors_origins.split(",") if o.strip()]
            middleware.append(
                Middleware(
                    CORSMiddleware,
                    allow_origins=origins,
                    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                    allow_headers=[
                        "mcp-protocol-version",
                        "mcp-session-id",
                        "Authorization",
                        "Content-Type",
                        _TRACE_HEADER,
                    ],
                    expose_headers=["mcp-session-id"],
                )
            )

        middleware.append(Middleware(_KagiAuthFailureMiddleware))
        mcp.run(
            "streamable-http",
            host=args.host,
            port=args.port,
            stateless_http=True,
            json_response=True,
            middleware=middleware,
        )
    else:
        mcp.run()  # default stdio mode


if __name__ == "__main__":
    main()
