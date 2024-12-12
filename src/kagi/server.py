import asyncio
import logging
import textwrap
from concurrent.futures import ThreadPoolExecutor

import mcp.types as types
from kagiapi import KagiClient
from mcp.server import Server, stdio_server
from pydantic import BaseModel, Field


def setup_logger():
    logger = logging.getLogger("kagi-mcp")
    logger.info("Starting Kagi Server")
    return logger


logger = setup_logger()
server = Server("kagi")
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
    """Perform web search based on one or more queries. Results are from all queries given. They are numbered continuously, so that a user may be able to refer to a result by a specific number."""

    queries: list[str] = Field(
        description="One or more concise, keyword-focused search queries. Include essential context within each query for standalone use."
    )


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
            queries = arguments.get("queries") if arguments else None
            if not queries:
                raise ValueError("Search called with no queries.")

            with ThreadPoolExecutor() as executor:
                results = list(executor.map(kagi_client.search, queries, timeout=10))

            return [
                types.TextContent(
                    type="text", text=format_search_results(queries, results)
                )
            ]

        raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]


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
        results = [result for result in response["data"] if result["t"] == 0]

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


async def main():
    logger.info("Starting Kagi MCP server")
    try:
        options = server.create_initialization_options()
        async with stdio_server() as (read_stream, write_stream):
            logger.info("Server initialized successfully")
            await server.run(read_stream, write_stream, options)
    except Exception as e:
        logger.error(f"Server error occurred: {str(e)}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
