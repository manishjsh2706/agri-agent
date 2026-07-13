"""Stage D.3 -- the LLM tool router.

The LLM (OpenAI GPT-4o-mini) sees the farmer's free-text question and
decides which of our Python tools (from agent_tools.py) to call.
Our code executes the tool with real data. The LLM then reads the tool
result and writes a natural-language reply for the farmer.

This module deliberately does not touch prices, forecasts, or the
database directly -- all of that lives in the tools. That separation
is the safety property of the agent: the LLM never invents a number.

Public entry point
------------------
    ask_agent(message: str, phone: str = "") -> {"summary": str, "tool_trace": [...]}
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv

# Load .env so OPENAI_API_KEY is picked up.
load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    HumanMessage, SystemMessage, AIMessage, ToolMessage,
)

from agent_tools import ALL_TOOLS


# ---------------------------------------------------------------------------
# Model + tool binding (done once at import, so calls are cheap)
# ---------------------------------------------------------------------------
MODEL_NAME = os.environ.get("AGRI_AGENT_MODEL", "gpt-4o-mini")

_llm = ChatOpenAI(model=MODEL_NAME, temperature=0)
_llm_with_tools = _llm.bind_tools(ALL_TOOLS)
_tool_map = {t.name: t for t in ALL_TOOLS}


SYSTEM_PROMPT = """You are Agri-Agent, an advisor for small farmers in \
Pune district, Maharashtra, India. You help them decide WHICH mandi to \
sell at and WHEN to sell (now or wait).

You have five tools:
  * get_farmer_profile_tool(phone)        -- look up a registered farmer
  * get_current_prices_tool(crop)         -- today's prices across mandis
  * compare_mandis_tool(crop, lat, lon, vehicle, quantity_quintals, radius_km)
                                          -- rank mandis by net price
  * best_window_tool(crop)                -- forecast + sell-now/wait
  * list_farmers_tool()                   -- list every registered farmer

Rules you MUST follow:
1. Never invent a price or a distance. If a tool would answer it, call the tool.
2. If a phone number is given AND the farmer asks "which mandi" or "when to \
sell", FIRST call get_farmer_profile_tool to get their village lat/lon, \
vehicle and stock; then call the right analytical tool.
3. If no phone number is given, use these defaults: lat=18.4956, lon=73.8588, \
vehicle="mini_truck", quantity_quintals=10.
4. Prefer compare_mandis_tool when the question is about WHERE to sell.
   Prefer best_window_tool when the question is about WHEN to sell.
5. Keep your final reply under ~4 sentences unless the farmer asks for detail. \
Speak in the farmer's language: if the message is in Hindi or Marathi, reply \
in that language.
6. If the crop is unclear, ask the farmer to specify.
7. Never talk about topics outside agricultural mandi pricing.
"""


def ask_agent(message: str, phone: str = "", max_steps: int = 5) -> dict:
    """Run one turn of the tool-routing agent.

    Returns a dict with:
       summary   : the final natural-language reply
       tool_trace: a list of {tool, args, result} entries showing what
                   happened (useful for debugging and for the resume story)
    """
    system_text = SYSTEM_PROMPT
    if phone:
        system_text += f"\nThe user's registered phone number is: {phone}"
    messages = [
        SystemMessage(content=system_text),
        HumanMessage(content=message),
    ]

    tool_trace: list[dict] = []

    for _ in range(max_steps):
        response: AIMessage = _llm_with_tools.invoke(messages)
        messages.append(response)

        # No tool call means the LLM produced a final answer.
        if not response.tool_calls:
            return {
                "summary":    response.content,
                "tool_trace": tool_trace,
            }

        # Execute every requested tool and add its output to the message log.
        for tc in response.tool_calls:
            name = tc["name"]
            args = tc.get("args", {}) or {}
            tool = _tool_map.get(name)
            if tool is None:
                result: object = {"error": f"unknown tool '{name}'"}
            else:
                try:
                    result = tool.invoke(args)
                except Exception as e:
                    result = {"error": f"{type(e).__name__}: {e}"}
            tool_trace.append({"tool": name, "args": args, "result": result})
            messages.append(ToolMessage(
                content=json.dumps(result, default=str),
                tool_call_id=tc["id"],
            ))

    return {
        "summary":    "I couldn't finish that in a few steps -- please try a simpler question.",
        "tool_trace": tool_trace,
    }
