"""Gold: the published tables, built with DuckDB SQL over silver.

The SQL in fohor/sql/ runs in file order; each file's output is registered as a view
named after the file (minus the number), so later files can use earlier ones.
"""
from __future__ import annotations

from importlib import resources

import duckdb
import pandas as pd

from fohor import config

GOLD_TABLES = ("municipality_waste", "blockade_backlog", "drop_off_access", "facility_registry", "data_gaps")


def _sql_files() -> list[tuple[str, str]]:
    files = sorted(f for f in resources.files("fohor.sql").iterdir() if f.name.endswith(".sql"))
    return [(f.name.split("_", 1)[1].removesuffix(".sql"), f.read_text()) for f in files]


def connect(**frames: pd.DataFrame) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    variables = {
        "landfill_tpd": config.LANDFILL_TONNES_PER_DAY,
        "adb_kg": config.ADB_MSW_KG_PER_CAPITA_DAY,
        "t_per_truck": config.TONNES_PER_TRUCK,
        "truck_kmh": config.TRUCK_AVG_KMH,
        "fleet_surge": config.FLEET_SURGE_FACTOR,
        "organic_share": config.CBS_ORGANIC_SHARE,
    }
    for k, v in variables.items():
        con.execute(f"set variable {k} = {float(v)!r}")
    for name, df in frames.items():
        con.register(name, df)
    return con


def build_gold(population: pd.DataFrame, haul: pd.DataFrame, access: pd.DataFrame, facilities: pd.DataFrame,
               facility_history: pd.DataFrame) -> dict[str, pd.DataFrame]:
    fac = facilities.drop(columns=["geometry"], errors="ignore")
    con = connect(population=population, haul=haul, access=access, facilities=fac,
                  facility_history=facility_history)
    out: dict[str, pd.DataFrame] = {}
    for name, sql in _sql_files():
        df = con.execute(sql).df()
        con.register(name, df)
        out[name] = df
    return out


def facility_history(releases: list[str], per_release: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """First and last release each facility id appeared in, across every release we hold."""
    seen: dict[str, list[str]] = {}
    for r in releases:
        df = per_release.get(r)
        if df is None:
            continue
        for gid in df["facility_key"]:
            seen.setdefault(gid, []).append(r)
    cols = ["facility_key", "first_seen_release", "last_seen_release"]
    return pd.DataFrame([dict(zip(cols, (g, rs[0], rs[-1]), strict=True)) for g, rs in seen.items()], columns=cols)


def facility_changes(previous: pd.DataFrame | None, current: pd.DataFrame, release: str) -> pd.DataFrame:
    """Facilities added, removed or re-keyed since the previous release we hold."""
    cols = ["release", "change", "facility_key", "gers_id", "previous_gers_id", "name", "kind"]
    if previous is None:
        return pd.DataFrame(columns=cols)
    prev = previous.set_index("facility_key")
    cur = current.set_index("facility_key")
    rows = []
    for k in cur.index.difference(prev.index):
        rows.append({"change": "added", "facility_key": k, "gers_id": cur.at[k, "gers_id"], "previous_gers_id": None})
    for k in prev.index.difference(cur.index):
        rows.append({"change": "removed", "facility_key": k, "gers_id": None,
                     "previous_gers_id": prev.at[k, "gers_id"]})
    for k in cur.index.intersection(prev.index):
        if cur.at[k, "gers_id"] != prev.at[k, "gers_id"]:
            rows.append({"change": "rekeyed", "facility_key": k, "gers_id": cur.at[k, "gers_id"],
                         "previous_gers_id": prev.at[k, "gers_id"]})
    out = pd.DataFrame(rows, columns=["change", "facility_key", "gers_id", "previous_gers_id"])
    names = pd.concat([previous, current]).drop_duplicates("facility_key", keep="last").set_index("facility_key")
    out["name"] = out["facility_key"].map(names["name"])
    out["kind"] = out["facility_key"].map(names["kind"])
    return out.assign(release=release)[cols]
