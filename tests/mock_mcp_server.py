"""用于测试的 MCP mock server。"""

from mcp.server import Server
from mcp.server.stdio import stdio_server

server = Server("test-server")


@server.list_tools()
async def list_tools():
    from mcp.types import Tool

    return [
        Tool(
            name="echo",
            description="Echo back the input message",
            inputSchema={
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
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    from mcp.types import TextContent

    if name == "echo":
        return [TextContent(type="text", text=arguments["message"])]
    elif name == "add":
        result = arguments["a"] + arguments["b"]
        return [TextContent(type="text", text=str(result))]
    else:
        raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
