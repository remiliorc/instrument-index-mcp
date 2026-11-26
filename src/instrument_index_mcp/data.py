"""Synthetic instrument index generator.

Produces a fictitious plant instrument list (ISA-5.1 style tags) in SQLite.
Every value is random but reproducible from the seed: there is no real asset,
site or vendor behind it.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

# function letters -> (description, unit, (lo, hi) choices)
TYPES = {
    "TT": ("Temperature transmitter", "degC", [(0, 150), (0, 400), (-50, 100)]),
    "PT": ("Pressure transmitter", "barg", [(0, 10), (0, 40), (-1, 5)]),
    "FT": ("Flow transmitter", "m3/h", [(0, 50), (0, 250), (0, 1200)]),
    "LT": ("Level transmitter", "%", [(0, 100)]),
    "AT": ("Analyzer transmitter", "pH", [(0, 14)]),
    "FV": ("Flow control valve", "%", [(0, 100)]),
    "PSV": ("Pressure safety valve", "barg", [(0, 16), (0, 45)]),
}
SERVICES = ["Raw material feed", "Mixing tank outlet", "Cooling water return",
            "Hot water supply", "Product storage tank", "Recirculation line",
            "Wastewater sump", "Heat exchanger outlet", "Pump discharge",
            "Compressed air header"]
SIGNALS = ["4-20 mA HART", "4-20 mA", "FOUNDATION Fieldbus", "PROFIBUS PA"]
STATUSES = ["in service", "in service", "in service", "in service",
            "out of service", "spare"]
AREAS = [100, 200, 300, 400]

SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
    tag TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    description TEXT NOT NULL,
    service TEXT NOT NULL,
    area INTEGER NOT NULL,
    loop TEXT NOT NULL,
    range_lo REAL NOT NULL,
    range_hi REAL NOT NULL,
    unit TEXT NOT NULL,
    signal TEXT NOT NULL,
    alarm_lo REAL,
    alarm_hi REAL,
    sil INTEGER,
    status TEXT NOT NULL,
    last_calibration TEXT NOT NULL,
    calibration_interval_days INTEGER NOT NULL
);
"""


def generate(n_loops: int = 60, seed: int = 42,
             today: date = date(2026, 1, 1)) -> list[dict]:
    rng = random.Random(seed)
    rows: list[dict] = []
    used: set[str] = set()
    for _ in range(n_loops):
        area = rng.choice(AREAS)
        number = rng.randint(1, 99)
        variable = rng.choice(["T", "P", "F", "L", "A"])
        loop = f"{variable}-{area + number}"
        if loop in used:
            continue
        used.add(loop)
        service = rng.choice(SERVICES)
        members = [f"{variable}T"]
        if variable == "F":
            members.append("FV")
        if variable == "P" and rng.random() < 0.4:
            members.append("PSV")
        for t in members:
            desc, unit, ranges = TYPES[t]
            lo, hi = rng.choice(ranges)
            span = hi - lo
            interval = rng.choice([180, 365, 730])
            last = today - timedelta(days=rng.randint(0, 800))
            is_measure = t.endswith("T")
            rows.append({
                "tag": f"{t}-{area + number}",
                "type": t,
                "description": desc,
                "service": service,
                "area": area,
                "loop": loop,
                "range_lo": float(lo),
                "range_hi": float(hi),
                "unit": unit,
                "signal": rng.choice(SIGNALS) if t != "PSV" else "none",
                "alarm_lo": round(lo + 0.1 * span, 2) if is_measure else None,
                "alarm_hi": round(lo + 0.9 * span, 2) if is_measure else None,
                "sil": rng.choice([None, None, None, 1, 2]) if is_measure else None,
                "status": rng.choice(STATUSES),
                "last_calibration": last.isoformat(),
                "calibration_interval_days": interval,
            })
    return rows


def build_db(path: str | Path, **kw) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    rows = generate(**kw)
    with sqlite3.connect(path) as con:
        con.executescript(SCHEMA)
        con.executemany(
            "INSERT INTO instruments VALUES (:tag,:type,:description,:service,"
            ":area,:loop,:range_lo,:range_hi,:unit,:signal,:alarm_lo,:alarm_hi,"
            ":sil,:status,:last_calibration,:calibration_interval_days)", rows)
    return path


if __name__ == "__main__":
    import sys
    out = build_db(sys.argv[1] if len(sys.argv) > 1 else "data/instruments.db")
    print(f"wrote {out}")
