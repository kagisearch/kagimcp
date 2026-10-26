# Kagi MCP Server

An MCP server backed by the [Kagi API](https://help.kagi.com/kagi/api/overview.html). It exposes search and extraction tools to MCP-compatible clients.

## Tools

- **`kagi_search_fetch`** - web, news, videos, podcasts, and image search with optional page extracts, filters, and Kagi lenses.
- **`kagi_extract`** - fetch a page's full content as markdown.

> **Note:** The previous `kagi_fastgpt` and `kagi_summarizer` tools have been removed. Both are planned to return in a future release.

## Hosted Server

We run a hosted MCP server at **`https://mcp.kagi.com/mcp`** — no install required. Point any HTTP-capable MCP client at it and authenticate with your Kagi API key.

OAuth2 isn't supported yet (it's on our roadmap), so for now grab your [API key from the dashboard](https://kagi.com/api/keys) and pass it via `Bearer` HTTP authentication.

Example with Claude Code:

```bash
claude mcp add kagi https://mcp.kagi.com/mcp --transport http --header "Authorization: Bearer $(read -sp 'API key: ' k; echo $k)" --scope user
```

Prefer to run it yourself? See [Client Setup](#client-setup) for the local `uvx` install, or [Self-Hosting](#self-hosting) to host the HTTP server on your own infrastructure.

## Requirements

- A Kagi API key in `KAGI_API_KEY`, or you can login via OAuth to your Kagi account to automatically set this up.
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
`KAGI_MCP_PUBLIC_URL` | Public base URL of this MCP server for OAuth discovery; defaults to `https://mcp.kagi.com`.
`KAGI_OAUTH_ISSUER` | Advertised authorization server issuer; defaults to `https://account.kagi.com`.
`KAGI_OAUTH_METADATA_URL` | OIDC metadata for Authorization; defaults to `https://account.kagi.com/.well-known/openid-configuration`.

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

### OAuth token renewal

For OAuth-enabled deployments, the server advertises `offline_access` in its
protected-resource metadata so clients that use discovery to select scopes can
request refresh tokens. Zitadel requires this scope to issue refresh tokens in
the authorization code flow; see its [standard scopes documentation](https://zitadel.com/docs/apis/openidoauth/scopes#standard-scopes).
The client stores and uses refresh tokens to obtain new access tokens through
the [refresh token grant](https://zitadel.com/docs/apis/openidoauth/endpoints#refresh-token-grant).
Token renewal is handled by the client, not the MCP server.

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
