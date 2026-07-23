"""Stage MCP.2 -- hello-world MCP server.

The absolute simplest MCP server: two tools that let us verify:
    1. The MCP SDK is installed correctly.
    2. Our Python environment can run an MCP server.
    3. Tool registration works (name, docstring, parameter schema).

Nothing about your existing app changes -- this is a NEW standalone
process that runs alongside everything else.

Run:
    python hello_mcp_server.py

Expected behavior: the process starts and waits SILENTLY on stdin.
That's normal for a stdio-transport MCP server -- it's waiting for
JSON-RPC messages from an MCP client (Claude Desktop, MCP Inspector,
etc.). Press Ctrl+C to stop.

To actually invoke the tools, we'll need an MCP client. That comes
in Stage MCP.5 (MCP Inspector) and Stage MCP.6 (Claude Desktop).

Later stages will:
    * Wrap our existing 12 Agri-Agent tools (MCP.3, MCP.4)
    * Test with MCP Inspector (MCP.5)
    * Wire into Claude Desktop (MCP.6)
    * Deploy to Oracle Cloud (MCP.7)
"""

from mcp.server.fastmcp import FastMCP


# Create the MCP server object.
# The name "agri-agent-hello" is what appears in MCP clients' UI.
# (Later we'll rename it to "agri-agent" for the real server.)
mcp = FastMCP("agri-agent-hello")


# ---------------------------------------------------------------------------
# Tool 1 -- returns a greeting.
#
# Notice the @mcp.tool() decorator. Very similar to LangChain's @tool.
# The function's:
#   * name         -> becomes the tool's name in the MCP schema
#   * type hints   -> become the parameter schema (auto JSON-Schema)
#   * docstring    -> becomes the tool's description shown to the AI client
# ---------------------------------------------------------------------------
@mcp.tool()
def say_hello(name: str = "World") -> str:
    """Say a friendly hello to someone.

    Args:
        name: The person's name. Defaults to "World" if not provided.

    Returns:
        A greeting string.
    """
    return f"Hello, {name}! This is the Agri-Agent MCP server (hello-world stage)."


# ---------------------------------------------------------------------------
# Tool 2 -- adds two integers.
#
# Purpose: prove typed parameters work end-to-end. If the MCP client
# calls this with strings by accident, we'll see a validation error --
# which is a GOOD thing (means the schema is being enforced).
# ---------------------------------------------------------------------------
@mcp.tool()
def add_two_numbers(a: int, b: int) -> int:
    """Add two integers together.

    Simple math tool used to verify that MCP correctly handles
    typed parameters and return values.

    Args:
        a: First integer.
        b: Second integer.

    Returns:
        The sum a + b.
    """
    return a + b


# ---------------------------------------------------------------------------
# Entry point -- start the server on stdio transport.
#
# stdio = communication over standard input / output.
# Best for LOCAL usage where the MCP client (e.g. Claude Desktop) launches
# our server as a subprocess and talks to it via stdin/stdout.
#
# For REMOTE usage (server on Oracle Cloud, client anywhere), we'd use
# transport="sse" (Server-Sent Events over HTTP). We'll get to that in
# Stage MCP.7 if we choose to expose remotely.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()
