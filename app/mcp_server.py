"""FastMCP server exposing get_actuator_by_part_number and recommend_actuators as MCP tools.

Both tools carry readOnlyHint=True so MCP clients (Claude Desktop, Cursor) know they
never mutate state and can run without per-call approval friction."""

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from app.tools.get_actuator import get_actuator_by_part_number
from app.tools.recommend import recommend_actuators

mcp = FastMCP("Actuator Tools")
mcp_app = mcp.http_app(path="/")

_READ_ONLY = ToolAnnotations(readOnlyHint=True)


@mcp.tool(annotations=_READ_ONLY)
async def get_actuator(part_number: str) -> str:
    """Get exact technical specifications for a Series 76 actuator by its Base Part Number.

    Args:
        part_number: The Base Part Number (e.g., '763A00-11300000/A').
    """
    # ainvoke runs the sync tool in a threadpool so the blocking DB/LLM call
    # doesn't stall the FastMCP event loop (matches the HTTP path's await ainvoke).
    return await get_actuator_by_part_number.ainvoke({"part_number": part_number})


@mcp.tool(annotations=_READ_ONLY)
async def recommend(requirements: str) -> str:
    """Recommend Series 76 actuators based on natural language technical requirements.

    Args:
        requirements: Natural language description (e.g., 'explosionproof 300 Nm 220V').
    """
    return await recommend_actuators.ainvoke({"requirements": requirements})
