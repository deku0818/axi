"""用于测试的 MCP mock server。"""

from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

TOOLS = [
    Tool(
        name="echo",
        description="Echo back the input message",
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The message to echo"},
            },
            "required": ["message"],
        },
    ),
    Tool(
        name="add",
        description="Add two numbers",
        input_schema={
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
        },
    ),
    Tool(
        name="boom",
        description="Always fails with a tool-level error",
        input_schema={"type": "object", "properties": {}},
    ),
]


def _text(text: str, is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)], is_error=is_error
    )


async def list_tools(
    ctx: ServerRequestContext, params: PaginatedRequestParams | None
) -> ListToolsResult:
    return ListToolsResult(tools=TOOLS)


async def call_tool(
    ctx: ServerRequestContext, params: CallToolRequestParams
) -> CallToolResult:
    arguments = params.arguments or {}
    if params.name == "echo":
        return _text(arguments["message"])
    if params.name == "add":
        return _text(str(arguments["a"] + arguments["b"]))
    if params.name == "boom":
        return _text("kaboom", is_error=True)
    return _text(f"Unknown tool: {params.name}", is_error=True)


server = Server("test-server", on_list_tools=list_tools, on_call_tool=call_tool)


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
