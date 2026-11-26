"""Domain layer: read-only queries and engineering calculations.

Kept free of MCP imports so it can be unit-tested and reused by any client
(CLI, REST API, agent framework).
"""

from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

TAG_RE = re.compile(r"^(?P<func>[A-Z]{2,4})-(?P<num>\d{3,4})(?P<suffix>[A-Z])?$")
FIRST_LETTER = {"T": "temperature", "P": "pressure", "F": "flow",
                "L": "level", "A": "analysis"}
# Modifier allowed right after the first letter (ISA-5.1): PDT, FQI, ...
MODIFIER = {"D": "differential", "F": "ratio", "Q": "totalize", "K": "rate of change"}
SUCCEEDING = {"T": "transmitter", "V": "valve", "SV": "safety valve",
              "CV": "control valve",
              "I": "indicator", "C": "controller", "E": "element",
              "S": "switch", "Y": "relay/compute", "R": "recorder",
              "G": "gauge", "A": "alarm"}
# Trailing modifiers on switches and alarms: LSHH, PSL, TAH, ...
LEVEL = {"HH": "high-high", "LL": "low-low", "H": "high", "L": "low"}


class NotFound(LookupError):
    pass


@dataclass
class InstrumentIndex:
    db_path: Path

    def _q(self, sql: str, params: tuple = ()) -> list[dict]:
        uri = f"file:{Path(self.db_path).resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as con:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute(sql, params).fetchall()]

    # ---- queries -------------------------------------------------------
    def search(self, text: str = "", type: str | None = None,
               area: int | None = None, status: str | None = None,
               limit: int = 25) -> list[dict]:
        sql = "SELECT * FROM instruments WHERE 1=1"
        p: list = []
        if text:
            sql += (" AND (tag LIKE ? ESCAPE '\\' OR service LIKE ? ESCAPE '\\'"
                    " OR description LIKE ? ESCAPE '\\')")
            escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{escaped}%"
            p += [like, like, like]
        if type:
            sql += " AND type = ?"
            p.append(type.upper())
        if area is not None:
            sql += " AND area = ?"
            p.append(int(area))
        if status:
            sql += " AND status = ?"
            p.append(status)
        sql += " ORDER BY tag LIMIT ?"
        p.append(max(1, min(int(limit), 200)))
        return self._q(sql, tuple(p))

    def get(self, tag: str) -> dict:
        rows = self._q("SELECT * FROM instruments WHERE tag = ?", (tag.upper(),))
        if not rows:
            raise NotFound(f"tag {tag!r} not found")
        return rows[0]

    def loop(self, loop: str) -> list[dict]:
        rows = self._q("SELECT * FROM instruments WHERE loop = ? ORDER BY tag",
                       (loop.upper(),))
        if not rows:
            raise NotFound(f"loop {loop!r} not found")
        return rows

    def calibration_due(self, within_days: int = 30,
                        today: date | None = None) -> list[dict]:
        today = today or date.today()
        out = []
        for r in self._q("SELECT * FROM instruments WHERE status = 'in service'"):
            due = (date.fromisoformat(r["last_calibration"])
                   + timedelta(days=r["calibration_interval_days"]))
            days = (due - today).days
            if days <= within_days:
                out.append({"tag": r["tag"], "due_date": due.isoformat(),
                            "days_left": days, "overdue": days < 0,
                            "sil": r["sil"]})
        return sorted(out, key=lambda x: x["days_left"])

    def summary(self) -> dict:
        by_type = self._q("SELECT type, COUNT(*) n FROM instruments GROUP BY type")
        by_status = self._q("SELECT status, COUNT(*) n FROM instruments GROUP BY status")
        sil = self._q("SELECT COUNT(*) n FROM instruments WHERE sil IS NOT NULL")
        return {"by_type": {r["type"]: r["n"] for r in by_type},
                "by_status": {r["status"]: r["n"] for r in by_status},
                "sil_rated": sil[0]["n"]}

    # ---- engineering helpers ------------------------------------------
    def evaluate_reading(self, tag: str, value: float) -> dict:
        r = self.get(tag)
        if not math.isfinite(value):
            return {"tag": r["tag"], "value": None, "state": "invalid reading",
                    "device_status": r["status"], "signal": r["signal"]}
        span = r["range_hi"] - r["range_lo"]
        pct = (value - r["range_lo"]) / span * 100
        state = "normal"
        if value < r["range_lo"] or value > r["range_hi"]:
            state = "out of range"
        elif r["alarm_hi"] is not None and value >= r["alarm_hi"]:
            state = "high alarm"
        elif r["alarm_lo"] is not None and value <= r["alarm_lo"]:
            state = "low alarm"
        out = {"tag": r["tag"], "value": value, "unit": r["unit"],
               "percent_of_span": round(pct, 2), "state": state,
               "device_status": r["status"], "signal": r["signal"]}
        if r["status"] != "in service":
            out["warning"] = (f"device is '{r['status']}': the reading may not "
                              "reflect the process")
        return out


def ma_to_eu(ma: float, lo: float, hi: float) -> dict:
    """Convert a 4-20 mA signal to engineering units (NAMUR NE43 checks).

    NE43: measurement information between 3.8 and 20.5 mA, of which
    3.8-4.0 mA is under-range and 20.0-20.5 mA is over-range (still valid
    values, flagged); failure information at <= 3.6 mA or >= 21.0 mA. The
    bands between (3.6-3.8 and 20.5-21.0 mA) are not defined as measurement
    and are reported without a value."""
    if not math.isfinite(ma):
        return {"value": None, "status": "invalid reading"}
    if ma <= 3.6:
        return {"value": None, "status": "failure (low, NE43)"}
    if ma >= 21.0:
        return {"value": None, "status": "failure (high, NE43)"}
    if ma < 3.8 or ma > 20.5:
        return {"value": None, "status": "outside NE43 measurement range"}
    if ma < 4.0:
        status = "under-range (NE43)"
    elif ma > 20.0:
        status = "over-range (NE43)"
    else:
        status = "ok"
    value = lo + (ma - 4.0) / 16.0 * (hi - lo)
    return {"value": round(value, 4), "status": status}


def parse_tag(tag: str) -> dict:
    """Explain an ISA-5.1 style tag such as 'FT-212', 'PDT-301' or 'LSHH-120'."""
    m = TAG_RE.match(tag.strip().upper())
    if not m:
        return {"valid": False, "reason": "expected LETTERS-NUMBER[SUFFIX], e.g. TT-101"}
    func = m["func"]
    variable = FIRST_LETTER.get(func[0])
    rest = func[1:]
    modifier = None
    if len(rest) > 1 and rest[0] in MODIFIER:
        modifier, rest = MODIFIER[rest[0]], rest[1:]
    level = None
    for suffix in ("HH", "LL", "H", "L"):
        if rest.endswith(suffix) and len(rest) > len(suffix):
            level, rest = LEVEL[suffix], rest[: -len(suffix)]
            break
    if rest in SUCCEEDING:
        role = SUCCEEDING[rest]
    elif all(c in SUCCEEDING for c in rest):
        role = " ".join(SUCCEEDING[c] for c in rest)
    else:
        role = None
    valid = variable is not None and role is not None
    out = {"valid": valid, "variable": variable, "modifier": modifier,
           "function": role, "level": level, "loop_number": m["num"],
           "suffix": m["suffix"]}
    if not valid:
        out["reason"] = "letters not in the supported ISA-5.1 subset"
    return out
