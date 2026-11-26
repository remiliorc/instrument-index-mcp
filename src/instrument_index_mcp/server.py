"""MCP server exposing the instrument index as read-only tools.

Run over stdio (Claude Desktop / Claude Code):
    python -m instrument_index_mcp.server
Run over HTTP:
    python -m instrument_index_mcp.server --http --port 8000
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

try:  # MCP Python SDK >= 2
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError
    _SDK_V2 = True
except ImportError:  # MCP Python SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore
    from mcp.server.fastmcp.exceptions import ToolError  # type: ignore
    _SDK_V2 = False

from mcp.types import ToolAnnotations

from .data import build_db
from .index import InstrumentIndex, NotFound, ma_to_eu, parse_tag

DB_PATH = Path(os.environ.get("INSTRUMENT_DB", "data/instruments.db"))
RO = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

mcp = _Server(
    "instrument-index",
    instructions=(
        "Read-only access to a SYNTHETIC plant instrument index. "
        "Use search_instruments to find tags, get_instrument for details, "
        "evaluate_reading to check a live value against range and alarms."
    ),
)


def _index() -> InstrumentIndex:
    if not DB_PATH.exists():
        build_db(DB_PATH)
    return InstrumentIndex(DB_PATH)




@mcp.tool(annotations=RO)
def search_instruments(text: str = "", type: str | None = None,
                       area: int | None = None, status: str | None = None,
                       limit: int = 25) -> list[dict]:
    """Search instruments by free text (tag, service, description) and filters.

    type: ISA function letters, e.g. TT, PT, FT, LT, AT, FV, PSV.
    status: 'in service', 'out of service' or 'spare'.
    """
    return _index().search(text, type, area, status, limit)


@mcp.tool(annotations=RO)
def get_instrument(tag: str) -> dict:
    """Full datasheet row for one tag, e.g. 'FT-104'."""
    try:
        return _index().get(tag)
    except NotFound as e:
        raise ToolError(str(e)) from None


@mcp.tool(annotations=RO)
def get_loop(loop: str) -> list[dict]:
    """All instruments belonging to a control loop, e.g. 'F-104'."""
    try:
        return _index().loop(loop)
    except NotFound as e:
        raise ToolError(str(e)) from None


@mcp.tool(annotations=RO)
def calibration_due(within_days: int = 30) -> list[dict]:
    """In-service instruments whose calibration is due within N days (negative = overdue)."""
    return _index().calibration_due(within_days)


@mcp.tool(annotations=RO)
def evaluate_reading(tag: str, value: float) -> dict:
    """Check a process value against the instrument range and alarm limits.

    Includes the device status and a warning if it is not in service."""
    try:
        return _index().evaluate_reading(tag, value)
    except NotFound as e:
        raise ToolError(str(e)) from None


@mcp.tool(annotations=RO)
def convert_ma(ma: float, range_lo: float, range_hi: float) -> dict:
    """Convert a 4-20 mA current to engineering units with NAMUR NE43 diagnostics."""
    return ma_to_eu(ma, range_lo, range_hi)


@mcp.tool(annotations=RO)
def explain_tag(tag: str) -> dict:
    """Decode an ISA-5.1 style tag into measured variable and function."""
    return parse_tag(tag)


@mcp.tool(annotations=RO)
def index_summary() -> dict:
    """Counts by instrument type and status, and number of SIL-rated devices."""
    return _index().summary()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    if a.http:
        if _SDK_V2:
            mcp.run("streamable-http", host=a.host, port=a.port)
        else:  # 1.x reads host/port from settings
            mcp.settings.host, mcp.settings.port = a.host, a.port
            mcp.run("streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
