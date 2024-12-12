# Kagi MCP server

## Instructions
### Clone repo
`git clone https://github.com/kagisearch/kagi-mcp.git`
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
cd kagi-mcp

# Create virtual environment and activate it
uv venv

source .venv/bin/activate # MacOS/Linux
# OR
.venv/Scripts/activate # Windows

# Install dependencies
uv sync
```
### Setup with Claude Desktop
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
        "/ABSOLUTE/PATH/TO/PARENT/FOLDER/kagi-mcp",
        "run",
        "kagi"
      ],
      "env": {
        "KAGI_API_KEY": "YOUR_API_KEY_HERE"
      }
    }
  }
}
```
### Ask Claude a question requiring search
e.g. "Who was time's 2024 person of the year?"
## Debugging
Run:
```bash
npx @modelcontextprotocol/inspector \
      uv \
      --directory /ABSOLUTE/PATH/TO/PARENT/FOLDER/kagi-mcp \
      run \
      kagi
```
Then access MCP Inspector at `http://localhost:5173`. You may need to add your Kagi API key in the environment variables in the inspector under `KAGI_API_KEY`.
