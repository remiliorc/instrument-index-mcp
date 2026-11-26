import asyncio
from datetime import date

import pytest

from instrument_index_mcp.data import build_db, generate
from instrument_index_mcp.index import InstrumentIndex, NotFound, ma_to_eu, parse_tag


@pytest.fixture(scope="module")
def idx(tmp_path_factory):
    db = build_db(tmp_path_factory.mktemp("d") / "i.db")
    return InstrumentIndex(db)


def test_generation_is_reproducible():
    assert generate(seed=7) == generate(seed=7)
    assert generate(seed=7) != generate(seed=8)


def test_search_and_get(idx):
    rows = idx.search(type="FT")
    assert rows and all(r["type"] == "FT" for r in rows)
    one = idx.get(rows[0]["tag"].lower())
    assert one["tag"] == rows[0]["tag"]
    with pytest.raises(NotFound):
        idx.get("ZZ-999")


def test_flow_loops_have_valve(idx):
    ft = idx.search(type="FT", limit=1)[0]
    tags = {r["type"] for r in idx.loop(ft["loop"])}
    assert {"FT", "FV"} <= tags


def test_calibration_due_sorted(idx):
    due = idx.calibration_due(30, today=date(2026, 1, 1))
    assert due == sorted(due, key=lambda x: x["days_left"])
    assert all(d["days_left"] <= 30 for d in due)


def test_evaluate_reading(idx):
    r = idx.search(type="TT", limit=1)[0]
    lo, hi = r["range_lo"], r["range_hi"]
    assert idx.evaluate_reading(r["tag"], (lo + hi) / 2)["state"] == "normal"
    assert idx.evaluate_reading(r["tag"], hi * 0.95 + lo * 0.05)["state"] == "high alarm"
    assert idx.evaluate_reading(r["tag"], hi + 1)["state"] == "out of range"


def test_ma_conversion():
    assert ma_to_eu(12, 0, 100) == {"value": 50.0, "status": "ok"}
    bad = ma_to_eu(3.5, 0, 100)
    assert bad["status"].startswith("failure") and bad["value"] is None
    assert ma_to_eu(20.8, 0, 100) == {"value": None,
                                      "status": "outside NE43 measurement range"}


def test_parse_tag():
    assert parse_tag("FT-212")["variable"] == "flow"
    assert parse_tag("psv-130A")["suffix"] == "A"
    assert parse_tag("hello")["valid"] is False
    assert parse_tag("PSV-130A")["function"] == "safety valve"
    pdt = parse_tag("PDT-301")
    assert (pdt["variable"], pdt["modifier"], pdt["function"]) == (
        "pressure", "differential", "transmitter")
    lshh = parse_tag("LSHH-120")
    assert (lshh["variable"], lshh["function"], lshh["level"]) == (
        "level", "switch", "high-high")
    assert parse_tag("TXZ-101")["valid"] is False


def test_every_tag_in_the_index_decodes(idx):
    for r in idx.search(limit=200):
        assert parse_tag(r["tag"])["valid"], r["tag"]


def test_index_is_read_only(idx):
    import sqlite3
    with pytest.raises(sqlite3.OperationalError):
        idx._q("DELETE FROM instruments")
    assert idx.summary()["by_type"]


def test_out_of_service_reading_is_flagged(idx):
    r = idx.search(type="TT", status="out of service", limit=1)
    if r:
        ev = idx.evaluate_reading(r[0]["tag"], r[0]["range_lo"])
        assert "warning" in ev and ev["device_status"] == "out of service"


def test_mcp_tools_listed_and_callable(tmp_path, monkeypatch):
    import instrument_index_mcp.server as srv
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "x.db")

    async def run():
        tools = {t.name for t in await srv.mcp.list_tools()}
        assert {"search_instruments", "get_instrument", "get_loop",
                "calibration_due", "evaluate_reading", "convert_ma",
                "explain_tag", "index_summary"} <= tools
        res = await srv.mcp.call_tool("convert_ma",
                                      {"ma": 12, "range_lo": 0, "range_hi": 200})
        return res
    res = asyncio.run(run())
    text = res.content[0].text if hasattr(res, "content") else str(res)
    assert "100" in text


def test_ne43_boundaries_and_invalid_values(idx):
    assert ma_to_eu(3.6, 0, 100)["status"].startswith("failure")
    assert ma_to_eu(21.0, 0, 100)["status"].startswith("failure")
    assert ma_to_eu(3.7, 0, 100)["value"] is None
    assert ma_to_eu(3.7, 0, 100)["status"] == "outside NE43 measurement range"
    assert ma_to_eu(3.8, 0, 100) == {"value": -1.25, "status": "under-range (NE43)"}
    assert ma_to_eu(4.0, 0, 100) == {"value": 0.0, "status": "ok"}
    assert ma_to_eu(20.0, 0, 100) == {"value": 100.0, "status": "ok"}
    assert ma_to_eu(20.5, 0, 100) == {"value": 103.125, "status": "over-range (NE43)"}
    assert ma_to_eu(float("nan"), 0, 100)["status"] == "invalid reading"
    r = idx.search(type="TT", limit=1)[0]
    assert idx.evaluate_reading(r["tag"], float("nan"))["state"] == "invalid reading"


def test_search_wildcards_are_literal(idx):
    assert idx.search(text="%") == []
    assert idx.search(text="_") == []
    assert idx.search(text="Pump")


def test_unknown_tag_is_an_mcp_error(tmp_path, monkeypatch):
    """Unknown tags raise ToolError, which the SDK turns into isError=True."""
    import asyncio
    from instrument_index_mcp import server as srv
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "i.db")
    with pytest.raises(srv.ToolError, match="not found"):
        asyncio.run(srv.mcp.call_tool("get_instrument", {"tag": "ZZ-999"}))
    try:  # end-to-end check with the in-memory client of SDK 2.x
        from mcp.client import Client
    except ImportError:
        return

    async def run():
        async with Client(srv.mcp) as c:
            return await c.call_tool("get_instrument", {"tag": "ZZ-999"})
    res = asyncio.run(run())
    assert res.is_error and "not found" in res.content[0].text


def test_control_valve_tag():
    assert parse_tag("FCV-100")["function"] == "control valve"
