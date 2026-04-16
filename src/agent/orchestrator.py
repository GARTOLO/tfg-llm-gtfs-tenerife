# src/agent/orchestrator.py

import os
import asyncio
import json
import traceback
from typing import List
from dotenv import load_dotenv

# Official MCP protocol libraries
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

# Import the personality and instructions
from prompts import SYSTEM_PROMPT

# Load environment variables
load_dotenv()

def extract_clean_text(content) -> str:
    """Extracts plain text from Gemini's complex block responses."""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # Join text from all blocks that contain a 'text' key
        return "\n".join(block.get('text', '') for block in content if isinstance(block, dict) and 'text' in block)
    return str(content)

async def start_langchain_agent():
    """
    Starts the local MCP server, connects to the LLM (Gemini), and opens the chat interface.
    """
    print("Starting the Orchestrator...")
    print("Connecting to the local MCP Server on port 8000...")
    print(" (Make sure you started 'src/mcp/server.py' in another terminal!)")

    # Connect to the external MCP server via SSE (Server-Sent Events)
    url = "http://localhost:8000/sse"

    try:
        async with sse_client(url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Fetch tools from MCP Server
                tools_response = await session.list_tools()

                # Convert MCP tools to LangChain format
                mcp_tools = []
                for mcp_tool in tools_response.tools:
                    @tool(name_or_callable=mcp_tool.name, description=mcp_tool.description)
                    async def dynamic_tool(**kwargs) -> str:
                        result = await session.call_tool(mcp_tool.name, arguments=kwargs)
                        return str(result.content)

                    mcp_tools.append(dynamic_tool)

                print(f"✅ Loaded {len(mcp_tools)} tools from MCP into Agent's mind.")

                # Initialize the LLM (Gemini)
                llm = ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash",
                    temperature=0.2,
                    api_key=os.getenv("GOOGLE_API_KEY")
                )

                llm_with_tools = llm.bind_tools(mcp_tools)

                # Context Memory
                messages: List[BaseMessage] = [
                    SystemMessage(content=SYSTEM_PROMPT),
                ]

                print("\n" + "=" * 50)
                print("🚌 TransitGPT Tenerife - Chat Started 🚊")
                print("Type 'exit' or 'quit' to terminate.")
                print("=" * 50 + "\n")

                # Chat loop
                while True:
                    user_input = input("\nYou: ")
                    if user_input.lower() in ['exit', 'quit']:
                        print("Goodbye!")
                        break

                    messages.append(HumanMessage(content=user_input))

                    # Get Gemini's response
                    response = await llm_with_tools.ainvoke(messages)
                    messages.append(response)

                    # Execute tool if Gemini requested it
                    if response.tool_calls:
                        for tool_call in response.tool_calls:
                            print(f"⚙️  Agent is calling MCP tool: {tool_call['name']}...")

                            result = await session.call_tool(tool_call['name'], arguments=tool_call["args"])

                            if hasattr(result, 'content') and isinstance(result.content, list):
                                tool_text = "\n".join(block.text for block in result.content if hasattr(block, 'text'))
                            else:
                                tool_text = str(result)

                            # tool_to_execute = next(t for t in mcp_tools if t.name == tool_call['name'])
                            # tool_result = await tool_to_execute.ainvoke(tool_call["args"])
                            print(f"✅ Tool '{tool_call['name']}' returned: {tool_text}")

                            messages.append(ToolMessage(
                                tool_call_id=tool_call['id'],
                                name=tool_call['name'],
                                content=tool_text
                            ))

                        # Get final human-readable response
                        final_response = await llm_with_tools.ainvoke(messages)
                        print(f"🤖 Agent: {extract_clean_text(final_response.content)}")
                        messages.append(final_response)

                    else:
                        print(f"🤖 Agent: {extract_clean_text(response.content)}")

    except Exception as e:
        print(f"\nConnection Error: Could not connect to the MCP server at {url}.")
        print("Did you forget to run 'python src/mcp/server.py' in a separate PyCharm terminal?")
        print(f"Details: {e}")
        print("--- FULL ERROR TRACEBACK ---")
        traceback.print_exc()  # This will unpack the TaskGroup and show us the real error!
        print("----------------------------")


if __name__ == "__main__":
    try:
        # Since the whole process is asynchronous, we run the main function with asyncio
        asyncio.run(start_langchain_agent())
    except KeyboardInterrupt:
        print("\nChat terminated by the user.")