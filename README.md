# Kagi MCP Server

An MCP server backed by the [Kagi API](https://help.kagi.com/kagi/api/overview.html). It exposes search and extraction tools to MCP-compatible clients.

## Tools

- **`kagi_search_fetch`** - web, news, videos, podcasts, and image search with optional page extracts, filters, and Kagi lenses.
- **`kagi_extract`** - fetch a page's full content as markdown.

> **Note:** The previous `kagi_fastgpt` and `kagi_summarizer` tools have been removed. Both are planned to return in a future release.

## Hosted Server

We run a hosted MCP server at **`https://mcp.kagi.com/mcp`** — no install required. Point any HTTP-capable MCP client at it and either sign in with your Kagi account or authenticate with a Kagi API key.

### Sign in with your Kagi account (OAuth)

Your client opens a browser to sign in at `account.kagi.com`, and an API key is set up for your account automatically. Tell your client to use Kagi's OAuth client ID: `393794653092071821`.

> **Team accounts:** automatic key setup currently only works for the account owner. Other members should ask the owner for an [API key](#use-an-api-key) instead.

**Claude Code**

```bash
claude mcp add kagi https://mcp.kagi.com/mcp --transport http --client-id 393794653092071821 --scope user
```

Then run `/mcp`, select `kagi`, and choose **Authenticate**.

**Codex CLI**

```bash
codex mcp add kagi --url https://mcp.kagi.com/mcp --oauth-client-id 393794653092071821
codex mcp login kagi
```

**OpenCode**

Add to `~/.config/opencode/opencode.json`, then run `opencode mcp auth kagi`:

```json
{
  "mcp": {
    "servers": {
      "kagi": {
        "type": "remote",
        "url": "https://mcp.kagi.com/mcp",
        "oauth": { "client_id": "393794653092071821" }
      }
    }
  }
}
```

**Claude (claude.ai and Claude Desktop)**

In **Customize → Connectors**, choose **Add custom connector** and enter `https://mcp.kagi.com/mcp` as the URL. Under **OAuth client**, choose **Use your own OAuth client** and enter `393794653092071821` as the Client ID, leaving the secret empty.

### Use an API key

Grab your [API key from the dashboard](https://kagi.com/api/keys) and pass it via `Bearer` HTTP authentication.

Example with Claude Code:

```bash
claude mcp add kagi https://mcp.kagi.com/mcp --transport http --header "Authorization: Bearer $(read -sp 'API key: ' k; echo $k)" --scope user
```

Prefer to run it yourself? See [Client Setup](#client-setup) for the local `uvx` install, or [Self-Hosting](#self-hosting) to host the HTTP server on your own infrastructure.

## Requirements

- A Kagi API key in `KAGI_API_KEY`. (Signing in with your Kagi account instead is only available over HTTP, such as with the [hosted server](#sign-in-with-your-kagi-account-oauth).)
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

Install uv first.

MacOS/Linux:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows:
```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then in your Claude Desktop config (found through Settings -> Developer -> Edit Config):

```json
{
  "mcpServers": {
    "kagi": {
      "command": "uvx",
      "args": ["kagimcp"],
      "env": {
        "KAGI_API_KEY": "YOUR_API_KEY_HERE"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add kagi -e KAGI_API_KEY="YOUR_API_KEY_HERE" -- uvx kagimcp
```

### Smithery

```bash
npx -y @smithery/cli install kagimcp --client claude
```

### Kiro

Add to your Kiro MCP config file (`~/.kiro/settings/mcp.json` for global, or `.kiro/settings/mcp.json` for project-scoped) using the same `mcpServers` JSON as [Claude Desktop](#claude-desktop). See the [Kiro MCP documentation](https://kiro.dev/docs/mcp/) for more details.

### OpenCode

Edit the OpenCode configuration file in `~/.config/opencode/opencode.json` and add the following:

```json
{
  "mcp": {
    "kagi": {
      "type": "local",
      "command": ["uvx", "kagimcp"],
      "enabled": true,
      "environment": {
        "KAGI_API_KEY": "<YOUR_API_KEY_HERE>"
      }
    }
  }
}
```

## Usage Examples

- Search: `Who was Time's 2024 person of the year?`
- Extract: `extract the full content of https://en.wikipedia.org/wiki/Model_Context_Protocol`

## Configuration

Environment variable | Description
--- | ---
`KAGI_API_KEY` | Required Kagi API key.
`FASTMCP_LOG_LEVEL` | Logging level, for example `ERROR`.
`KAGI_SEARCH_TIMEOUT` | Search timeout in seconds. Defaults to `10`.
`KAGI_EXTRACT_TIMEOUT` | Extract timeout in seconds. Defaults to `30`.
`KAGI_MAX_RETRIES` | Max retry attempts after the first request. Defaults to `2`; set `0` to disable retries.
`KAGI_HIDDEN_PARAMS` | Comma-separated search params to hide from the LLM-facing schema.
`KAGI_SEARCH_FORMAT` | Search result format: `json` (default) or `markdown` (the Search API's own markdown, passed through as-is).
`KAGI_MCP_PUBLIC_URL` | Public base URL of this MCP server, used for OAuth discovery in HTTP mode. Defaults to `https://mcp.kagi.com`; set it to your own URL when [self-hosting](#self-hosting).

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

To let users sign in with their Kagi account, set `KAGI_MCP_PUBLIC_URL` to the
public base URL your server is reachable at (for example
`https://mcp.example.com`). Clients use it to discover where to sign in; left at
its default, it points them at Kagi's hosted server instead of yours.

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
