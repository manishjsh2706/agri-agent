"""Stage MCP.5 -- programmatic MCP client to test our server end-to-end.

This is a minimal MCP client that:
    1. Spawns agri_agent_mcp_server.py as a subprocess (stdio transport)
    2. Speaks the MCP protocol to it
    3. Lists all registered tools with their schemas
    4. Invokes 3 tools to prove the round-trip works

Purpose: prove the server works without needing a browser (MCP Inspector)
or a full MCP client app (Claude Desktop / Cursor). This is exactly what
Claude Desktop does under the hood -- we're just doing a tiny slice of it
for testing.

Run:
    python test_mcp_client.py

Expected output: a nicely printed list of 12 tools, then 3 successful
tool invocations with their results.
"""

from __future__ import annotations

# ---- SQLite compatibility shim ----------------------------------------
try:
    __import__("pysqlite3")
    import sys as _sys
    _sys.modules["sqlite3"] = _sys.modules.pop("pysqlite3")
except ImportError:
    pass
# -----------------------------------------------------------------------

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# The server script we want to test
SERVER_SCRIPT = "agri_agent_mcp_server.py"


# ---------------------------------------------------------------------------
# Test invocations. Each is (tool_name, args, human-readable label).
# Kept small: 3 different tools that exercise different parts of the system.
# ---------------------------------------------------------------------------
TEST_CALLS = [
    (
        "list_farmers",
        {},
        "List all registered farmers (exercises DB)",
    ),
    (
        "get_weather",
        {"latitude": 18.5204, "longitude": 73.8567, "days": 3},
        "Weather for Pune (exercises external API)",
    ),
    (
        "lookup_scheme_info",
        {"question": "How much money will I get from PM-Kisan?"},
        "RAG scheme lookup (exercises Chroma + LLM)",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _print_header(text: str) -> None:
    print()
    print("=" * 70)
    print(text)
    print("=" * 70)


def _shorten(text: str, n: int = 300) -> str:
    if len(text) <= n:
        return text
    return text[:n] + f"... [truncated {len(text) - n} more chars]"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> int:
    # Verify the server script exists before we try to launch it.
    server_path = Path(SERVER_SCRIPT).resolve()
    if not server_path.exists():
        print(f"[error] Server script not found: {server_path}")
        return 2

    # Configure how to launch the server (as a Python subprocess on stdio).
    params = StdioServerParameters(
        command=sys.executable,           # use the same Python we're running
        args=[str(server_path)],          # ... to run this server script
    )

    _print_header(f"Connecting to MCP server: {SERVER_SCRIPT}")

    # stdio_client returns a pair (read, write) for talking to the server.
    async with stdio_client(params) as (read, write):
        # ClientSession wraps read/write with the MCP protocol handshake.
        async with ClientSession(read, write) as session:
            # Step 1: initialize the session (protocol handshake).
            init_result = await session.initialize()
            print(f"[init] Connected to server: "
                  f"'{init_result.serverInfo.name}' "
                  f"v{init_result.serverInfo.version}")

            # Step 2: list all tools the server exposes.
            _print_header("Tools exposed by the server")
            tools_response = await session.list_tools()
            print(f"Total tools: {len(tools_response.tools)}")
            for t in tools_response.tools:
                desc = (t.description or "").strip().split("\n")[0]
                print(f"  * {t.name:<25} -- {desc[:80]}")

            # Step 3: invoke each test call and print the result.
            for tool_name, args, label in TEST_CALLS:
                _print_header(f"CALLING: {tool_name}  ({label})")
                print(f"Arguments: {json.dumps(args, ensure_ascii=False)}")
                try:
                    result = await session.call_tool(tool_name, args)
                    # Tool results come back as a list of content items;
                    # for our text-returning tools, we want the first text.
                    if result.isError:
                        print(f"[error] Tool returned an error:")
                        for c in result.content:
                            text = getattr(c, "text", str(c))
                            print(f"        {text}")
                    else:
                        for c in result.content:
                            text = getattr(c, "text", str(c))
                            print("Result:")
                            print(_shorten(text, 500))
                except Exception as e:
                    print(f"[exception] {type(e).__name__}: {e}")

    _print_header("Done")
    print("MCP server responded to init, list_tools, and 3 tool calls.")
    print("If you saw the tools listed and the calls returned results,")
    print("the server is working correctly.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
