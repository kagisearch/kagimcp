# Kagi MCP server

[![smithery badge](https://smithery.ai/badge/kagimcp)](https://smithery.ai/server/kagimcp)

<a href="https://glama.ai/mcp/servers/xabrrs4bka">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/xabrrs4bka/badge" alt="Kagi Server MCP server" />
</a>

## Setup Intructions
> Before anything, unless you are just using non-search tools, ensure you have access to the search API. It is currently in closed beta and available upon request. Please reach out to support@kagi.com for an invite.

Install uv first.

MacOS/Linux:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows:
```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
### Installing via Smithery

Alternatively, you can install Kagi for Claude Desktop via [Smithery](https://smithery.ai/server/kagimcp):

```bash
npx -y @smithery/cli install kagimcp --client claude
```

### Setup with Claude Desktop
```json
// claude_desktop_config.json
// Can find location through:
// Hamburger Menu -> File -> Settings -> Developer -> Edit Config
{
  "mcpServers": {
    "kagi": {
      "command": "uvx",
      "args": ["kagimcp"],
      "env": {
        "KAGI_API_KEY": "YOUR_API_KEY_HERE"
        "KAGI_SUMMARIZER_ENGINE": "YOUR_ENGINE_CHOICE_HERE" // Defaults to "cecil" engine if env var not present
      }
    }
  }
}
```

### Pose query that requires use of a tool
e.g. "Who was time's 2024 person of the year?" for search, or "summarize this video: https://www.youtube.com/watch?v=jNQXAC9IVRw" for summarizer.

### Debugging
Run:
```bash
npx @modelcontextprotocol/inspector uvx kagimcp
```

## Local/Dev Setup Instructions

### Clone repo
`git clone https://github.com/kagisearch/kagimcp.git`

### Install dependencies
Install uv first.

MacOS/Linux:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows:
```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then install MCP server dependencies:
```bash
cd kagimcp

# Create virtual environment and activate it
uv venv

source .venv/bin/activate # MacOS/Linux
# OR
.venv/Scripts/activate # Windows

# Install dependencies
uv sync
```
### Setup with Claude Desktop

#### Using MCP CLI SDK
```bash
# `pip install mcp[cli]` if you haven't
mcp install /ABSOLUTE/PATH/TO/PARENT/FOLDER/kagimcp/src/kagimcp/server.py -v "KAGI_API_KEY=API_KEY_HERE"
```

#### Manually
```json
# claude_desktop_config.json
# Can find location through:
# Hamburger Menu -> File -> Settings -> Developer -> Edit Config
{
  "mcpServers": {
    "kagi": {
      "command": "uv",
      "args": [
        "--directory",
        "/ABSOLUTE/PATH/TO/PARENT/FOLDER/kagimcp",
        "run",
        "kagimcp"
      ],
      "env": {
        "KAGI_API_KEY": "YOUR_API_KEY_HERE"
        "KAGI_SUMMARIZER_ENGINE": "YOUR_ENGINE_CHOICE_HERE" // Defaults to "cecil" engine if env var not present
      }
    }
  }
}
```

### Pose query that requires use of a tool
e.g. "Who was time's 2024 person of the year?" for search, or "summarize this video: https://www.youtube.com/watch?v=jNQXAC9IVRw" for summarizer.

### Debugging
Run:
```bash
# If mcp cli installed (`pip install mcp[cli]`)
mcp dev /ABSOLUTE/PATH/TO/PARENT/FOLDER/kagimcp/src/kagimcp/server.py

# If not
npx @modelcontextprotocol/inspector \
      uv \
      --directory /ABSOLUTE/PATH/TO/PARENT/FOLDER/kagimcp \
      run \
      kagimcp
```
Then access MCP Inspector at `http://localhost:5173`. You may need to add your Kagi API key in the environment variables in the inspector under `KAGI_API_KEY`.

# Advanced Configuration
- Level of logging is adjustable through the `FASTMCP_LOG_LEVEL` environment variable (e.g. `FASTMCP_LOG_LEVEL="ERROR"`)
  - Relevant issue: https://github.com/kagisearch/kagimcp/issues/4
- Summarizer engine can be customized using the `KAGI_SUMMARIZER_ENGINE` environment variable (e.g. `KAGI_SUMMARIZER_ENGINE="daphne"`)
  - Learn about the different summarization engines [here](https://help.kagi.com/kagi/api/summarizer.html#summarization-engines)
