from fastmcp import FastMCP
import asyncio

from db_tools import get_routes_demo
from otp_tools import plan_trip

mcp = FastMCP("Tenerife_Transport_MCP 🚌🚊")

mcp.add_tool(get_routes_demo)
mcp.add_tool(plan_trip)

async def show_registered_tools():
    """Dynamically fetches and prints the registered tools."""
    # We must 'await' the async function
    tools = await mcp.list_tools()
    # Extract the name of each tool
    tool_names = [tool.name for tool in tools]
    print(f"Loaded tools: {', '.join(tool_names)}")

if __name__ == "__main__":
    print("Starting TITSA MCP Server...")

    # 1. Run the async function to print the tools dynamically
    asyncio.run(show_registered_tools())

    # 2. Start the MCP server
    mcp.run()