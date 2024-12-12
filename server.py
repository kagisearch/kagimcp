import logging
from kagiapi import KagiClient

import mcp.types as types
from mcp.server import Server, stdio_server
from pydantic import BaseModel, Field


def setup_logger():
    logger = logging.getLogger("kagi_mcp")
    logger.info("Starting Kagi Server")
    return logger


logger = setup_logger()
server = Server("kagi-mcp")
kagi_client = KagiClient()


class ToolModel(BaseModel):
    @classmethod
    def as_tool(cls):
        return types.Tool(
            name=cls.__name__,
            description=cls.__doc__,
            inputSchema=cls.model_json_schema(),
        )


class Search(ToolModel):
    """Perform web search based on query provided."""

    query: str = Field(description="query term")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools."""
    logger.info("Listing available tools")
    tools = [
        Search.as_tool(),
    ]
    logger.info(f"Available tools: {[tool.name for tool in tools]}")
    return tools


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests."""
    logger.info(f"Tool called: {name} with arguments: {arguments}")
    try:
        if name == "Search":
            query = arguments.get("query") if arguments else None
            if not query:
                raise ValueError("Search called with no query")
            results = kagi_client.search(query, limit=10)
            return [types.TextContent(type="text", text=format_search_results(results))]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]


def format_search_results(results):
    output = []

    for result in results["data"]:
        # Format each result
        if result["t"] == 0:
            result_str = f"""[{result['title']}]({result['url']})
    {result['snippet'].replace('<b>', '').replace('</b>', '')}
    """
            output.append(result_str)

    # Join all results with a separator
    return "\n---\n".join(output)


async def main():
    logger.info("Starting Spotify MCP server")
    try:
        options = server.create_initialization_options()
        async with stdio_server() as (read_stream, write_stream):
            logger.info("Server initialized successfully")
            await server.run(read_stream, write_stream, options)
    except Exception as e:
        logger.error(f"Server error occurred: {str(e)}", exc_info=True)
        raise
