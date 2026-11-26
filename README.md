# instrument-index-mcp

An [MCP](https://modelcontextprotocol.io) server that gives AI agents **read-only**
access to a plant instrument index. With it, an assistant can answer questions
like "which SIL-rated transmitters are overdue for calibration?" or "is 370 degC
on TT-229 in alarm?" from structured data, without guessing.

> The dataset is **synthetic**: it is generated from a fixed seed (`data.py`) and
> describes no real site, asset or vendor.

## Why

Instrument indexes usually live in spreadsheets or engineering databases that
LLMs cannot query safely. This server shows the pattern:

- A **domain layer** (`index.py`) with no MCP dependency, unit-tested on its own.
- A **thin MCP layer** (`server.py`) whose tools are all marked `readOnlyHint`.
  The database is also opened in SQLite `mode=ro`, so it cannot be written even
  through a bug.
- **Engineering logic the model should not improvise**: 4-20 mA scaling with
  NAMUR NE43 fault detection, alarm and range evaluation, ISA-5.1 tag decoding.
- **Errors are MCP errors**: an unknown tag or loop returns a tool result with
  `isError: true`, so the agent cannot mistake it for data.

## Tools

| Tool | Purpose |
|---|---|
| `search_instruments` | Free text and filters (type, area, status) |
| `get_instrument` | Full record for one tag |
| `get_loop` | All devices in a control loop |
| `calibration_due` | Due or overdue calibrations, flags SIL-rated devices |
| `evaluate_reading` | Value → % of span and normal / alarm / out-of-range state |
| `convert_ma` | 4-20 mA → engineering units, with NE43 diagnostics (failure, under/over-range, undefined band) |
| `explain_tag` | Decodes a tag such as `PSV-130A`, `PDT-301` or `LSHH-120` (subset of ISA-5.1) |
| `index_summary` | Counts by type and status |

## Run

```bash
pip install -e ".[dev]"
pytest -q
python -m instrument_index_mcp.server            # stdio
python -m instrument_index_mcp.server --http     # streamable HTTP on :8000
```

With Docker:

```bash
docker build -t instrument-index-mcp .
docker run --rm -p 127.0.0.1:8000:8000 instrument-index-mcp   # local only: the server has no auth
```

### Claude Desktop / Claude Code (stdio)

```json
{
  "mcpServers": {
    "instrument-index": {
      "command": "python",
      "args": ["-m", "instrument_index_mcp.server"],
      "env": { "INSTRUMENT_DB": "/absolute/path/to/instruments.db" }
    }
  }
}
```

The database is created automatically on first run if it does not exist.

Notes:
- Calibration dates are generated around 2026-01-01 and `calibration_due` compares
  them with today's date, so the overdue list grows over time.
- The HTTP transport has no authentication. Bind it to localhost, or put it
  behind an authenticating proxy before exposing it.

## Example prompts

- "List in-service flow transmitters in area 200 and their signal types."
- "Which SIL-rated instruments are overdue for calibration?"
- "PT-269 reads 13.8 mA. What pressure is that, and is it in alarm?"

## Compatibility

Works with MCP Python SDK 1.x (`FastMCP`) and 2.x (`MCPServer`).

## License

MIT
