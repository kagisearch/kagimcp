# Kagi MCP Server

An MCP server backed by the [Kagi API](https://help.kagi.com/kagi/api/overview.html). It exposes search, extraction, summarization, and FastGPT tools to MCP-compatible clients.

## Tools

- **`kagi_search_fetch`** - web, news, videos, podcasts, and image search with optional page extracts, filters, and Kagi lenses.
- **`kagi_extract`** - fetch a page's full content as markdown.
- **`kagi_summarizer`** - summarize a URL as prose or key takeaways.
- **`kagi_fastgpt`** - answer a question with live web search, synthesis, and numbered references.

## Requirements

- A Kagi API key in `KAGI_API_KEY`.
- [`uv`](https://docs.astral.sh/uv/) for the recommended `uvx` install path.

Install `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Client Setup

### Codex CLI

```bash
codex mcp add kagi --env KAGI_API_KEY=<YOUR_API_KEY_HERE> -- uvx kagimcp
```

Codex writes MCP configuration to `~/.codex/config.toml`.

### Claude Desktop

```json
{
  "mcpServers": {
    "kagi": {
      "command": "uvx",
      "args": ["kagimcp"],
      "env": {
        "KAGI_API_KEY": "YOUR_API_KEY_HERE",
        "KAGI_SUMMARIZER_ENGINE": "cecil"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add kagi -e KAGI_API_KEY="YOUR_API_KEY_HERE" -- uvx kagimcp
```

With a custom summarizer engine:

```bash
claude mcp add kagi -e KAGI_API_KEY="YOUR_API_KEY_HERE" KAGI_SUMMARIZER_ENGINE="daphne" -- uvx kagimcp
```

### Smithery

```bash
npx -y @smithery/cli install kagimcp --client claude
```

## Usage Examples

- Search: `Who was Time's 2024 person of the year?`
- Summarizer: `summarize this video: https://www.youtube.com/watch?v=jNQXAC9IVRw`
- Extract: `extract the full content of https://en.wikipedia.org/wiki/Model_Context_Protocol`

## Configuration

Environment variable | Description
--- | ---
`KAGI_API_KEY` | Required Kagi API key.
`KAGI_SUMMARIZER_ENGINE` | Summarizer engine. Defaults to `cecil`.
`FASTMCP_LOG_LEVEL` | Logging level, for example `ERROR`.
`KAGI_SEARCH_TIMEOUT` | Search timeout in seconds. Defaults to `10`.
`KAGI_EXTRACT_TIMEOUT` | Extract timeout in seconds. Defaults to `30`.
`KAGI_SUMMARIZER_TIMEOUT` | Summarizer timeout in seconds. Defaults to `30`.
`KAGI_FASTGPT_TIMEOUT` | FastGPT timeout in seconds. Defaults to `10`.
`KAGI_MAX_RETRIES` | Max retry attempts after the first request. Defaults to `2`; set `0` to disable retries.
`KAGI_HIDDEN_PARAMS` | Comma-separated search params to hide from the LLM-facing schema.

Hideable search params:

```text
workflow, extract_count, limit, include_domains, exclude_domains, time_relative, after, before, file_type, lens_id
```

Example:

```bash
KAGI_HIDDEN_PARAMS="extract_count,after,before,time_relative,include_domains,exclude_domains"
```

## Local Development

```bash
git clone https://github.com/kagisearch/kagimcp.git
cd kagimcp
uv sync
```

Run locally over stdio:

```bash
KAGI_API_KEY=<YOUR_API_KEY_HERE> uv run kagimcp
```

Run with streamable HTTP transport:

```bash
KAGI_API_KEY=<YOUR_API_KEY_HERE> uv run kagimcp --http --host 0.0.0.0 --port 8000
```

## Self-Hosting

HTTP mode is multi-tenant: each request supplies its API key via the
`Authorization: Bearer <key>` header instead of a server-wide env var, so one
instance can serve multiple users. The repo ships a `Dockerfile` that installs a pinned `kagimcp` from PyPI and
runs it in HTTP mode. The container respects `$PORT` so it works on any
platform that injects one (Railway, Render, Cloud Run, Fly.io, etc.).

Build and run locally:

```sh
docker build -t kagimcp-hosted .
docker run --rm -p 8000:8000 kagimcp-hosted
```

Smoke test:

```sh
curl -sL http://127.0.0.1:8000/mcp -X POST \
  -H "authorization: Bearer $KAGI_API_KEY" \
  -H "content-type: application/json" \
  -H "accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

To bump the version in production, edit the pin in the `Dockerfile` and redeploy.

## Debugging

Inspect the published package:

```bash
npx @modelcontextprotocol/inspector uvx kagimcp
```

Inspect a local checkout:

```bash
npx @modelcontextprotocol/inspector uv --directory /ABSOLUTE/PATH/TO/kagimcp run kagimcp
```

The inspector is usually available at `http://localhost:5173`.

## Prerelease Instructions

If using a prerelease build, the same installation instructions apply, but use `uvx --prerelease allow --from kagimcp==1.0.0rc2 kagimcp` instead of `uvx kagimcp` (replace `1.0.0rc2` with whatever version you're wanting to install).
