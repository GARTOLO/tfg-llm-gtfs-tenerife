# src/agent/orchestrator.py

import os
import asyncio
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

from datetime import datetime

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
                # 1. Get the current system time
                now = datetime.now()
                date_str = now.strftime("%Y-%m-%d")
                time_str = now.strftime("%H:%M")

                days_of_week = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo (Festivo)"]
                current_day = days_of_week[now.weekday()]

                # 2. Create a dynamic text block
                time_context = f"""

                CONTEXTO TEMPORAL ACTUAL (¡CRÍTICO!):
                - La fecha y hora actual en la que te habla el usuario es: {current_day}, {date_str} a las {time_str} (Hora de Canarias).
                - Si el usuario pide una ruta "ahora" o no especifica la hora, DEBES usar obligatoriamente las {time_str} al llamar a la herramienta 'plan_trip'.
                - Si el usuario dice "mañana", suma un día a la fecha actual para tus cálculos.
                """

                # 3. Concatenate your static prompt with the dynamic clock
                messages = [
                    SystemMessage(content=SYSTEM_PROMPT + time_context)
                ]

                print("\n" + "=" * 50)
                print("🚌 TitsaGPT Tenerife - Chat Started 🚊")
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
                    try:
                        response = await llm_with_tools.ainvoke(messages)
                        messages.append(response)
                    except Exception as google_error:
                        print(f"❌ Error temporal en el servidor de lenguaje (Google): {google_error}")
                        print(
                            "🤖 Agent: Lo siento, sufro una alta latencia con mi servidor central. ¿Podrías repetir la consulta?")
                        continue

                        # 2. Autonomous tool loop
                    while response.tool_calls:
                        for tool_call in response.tool_calls:
                            print(f"⚙️  Agent is calling MCP tool: {tool_call['name']}...")

                            # =========================================================
                            # Strict argument sanitization layer
                            # =========================================================
                            raw_args = tool_call["args"]
                            if "kwargs" in raw_args and len(raw_args) == 1:
                                raw_args = raw_args["kwargs"]

                            clean_args = {}
                            alias_map = {
                                "linea_id": "route_id", "line_id": "route_id", "line": "route_id",
                                "parada_id": "stop_id", "stop": "stop_id",
                                "tipo_dia": "day_type", "day_of_week": "day_type", "day": "day_type",
                                "address": "location_name", "location": "location_name", "lugar": "location_name",
                                "origin_latitude": "origin_lat",
                                "origin_longitude": "origin_lon",
                                "destination_latitude": "destination_lat",
                                "destination_longitude": "destination_lon"
                            }

                            for k, v in raw_args.items():
                                new_name = alias_map.get(k, k)
                                clean_args[new_name] = str(v)

                            if tool_call["name"] == "get_line_occupancy":
                                clean_args.pop("time", None)
                                clean_args.pop("hour", None)
                                clean_args.pop("hora", None)

                            # Execute tool
                            result = await session.call_tool(tool_call['name'], arguments=clean_args)

                            if hasattr(result, 'content') and isinstance(result.content, list):
                                tool_text = "\n".join(block.text for block in result.content if hasattr(block, 'text'))
                            else:
                                tool_text = str(result)

                            print(f"✅ Tool '{tool_call['name']}' returned data successfully.")

                            messages.append(ToolMessage(
                                tool_call_id=tool_call['id'],
                                name=tool_call['name'],
                                content=tool_text
                            ))

                        # 3. Next loop iteration protected against Google call failures
                        try:
                            response = await llm_with_tools.ainvoke(messages)
                            messages.append(response)
                        except Exception as google_error:
                            print(f"❌ Error en la llamada de retorno (Google): {google_error}")
                            response.tool_calls = []
                            print(
                                "🤖 Agent: He recopilado los datos pero mis servidores están saturados para procesar la respuesta final.")
                            break

                        # 4. Final response to user
                    if response.content:
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
