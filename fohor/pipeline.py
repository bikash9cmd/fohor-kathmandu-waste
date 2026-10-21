"""The stages wired together. The CLI and the Lambdas both call these functions."""
from __future__ import annotations

import hashlib
import io
import logging
import uuid
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

from fohor import analysis, config, geo, gold, quality, silver
from fohor.ingest import bronze_for, ingest_hrsl, ingest_release, latest_release, load_manifest
from fohor.source import Source
from fohor.storage import Lake, read_arrow, read_json, write_json

log = logging.getLogger(__name__)

CURRENT = "gold/_current.json"
SILVER_TABLES = ("local_gov", "population", "pop_points", "facilities", "road_edges", "road_nodes", "haul", "access")


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


def _write_df(lake: Lake, key: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), buf, compression="zstd")
    lake.write_bytes(key, buf.getvalue())


def _read_df(lake: Lake, key: str) -> pd.DataFrame:
    return pq.read_table(io.BytesIO(lake.read_bytes(key))).to_pandas()


def silver_key(release: str, table: str) -> str:
    return f"silver/release={release}/{table}.parquet"


def gold_key(release: str, table: str) -> str:
    return f"gold/{table}/release={release}/part-0.parquet"


def _seed_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(config.SEEDS_DIR.glob("*.csv")):
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def inputs_signature(lake: Lake, release: str) -> dict:
    m = load_manifest(lake)
    themes = {k: v["fingerprint"] for k, v in sorted(m["releases"][release].items())}
    return {"themes": themes, "hrsl": (m.get("hrsl") or {}).get("etag"), "seeds": _seed_hash()}


# --- stages ---------------------------------------------------------------------------

def run_ingest(source: Source, hrsl_source: Source, lake: Lake, release: str | None = None) -> dict:
    release = release or latest_release(source)
    result = ingest_release(source, lake, release)
    result["hrsl"] = ingest_hrsl(hrsl_source, lake)
    return result


def run_silver(lake: Lake, release: str) -> dict:
    keys = bronze_for(lake, release)
    t = {name: read_arrow(lake, key) for name, key in keys.items()}
    issues: list[dict] = []

    lgs, i = silver.build_local_govs(t["division"], t["division_area"])
    issues += i
    if len(lgs) != len(config.VALLEY_LOCAL_GOVS):
        return {"release": release, "issues": issues, "built": False}
    districts = silver.district_polygons(t["division_area"])
    hrsl_key = load_manifest(lake)["hrsl"]["key"]
    pop, pts, i = silver.build_population(read_arrow(lake, hrsl_key), lgs, districts, silver.load_census())
    issues += i

    fac, i = silver.build_facilities(t["place"], t["infrastructure"], silver.load_overrides())
    issues += i
    fac["gers_id_lg"] = _assign_local_gov(fac, lgs)

    edges, nodes, i = silver.build_road_edges(t["segment"])
    issues += i
    landfill, i = silver.landfill_point(t["land_use"])
    issues += i
    haul = pd.DataFrame(columns=["gers_id", "haul_km_mean", "haul_km_p10", "haul_km_p90"])
    if landfill is not None:
        haul, i = analysis.haul_distances(edges, nodes, pts, landfill)
        issues += i
    access = analysis.drop_off_access(pts, fac)

    for name, df in {"local_gov": lgs, "population": pop, "pop_points": pts, "facilities": fac,
                     "road_edges": edges, "road_nodes": nodes, "haul": haul, "access": access}.items():
        _write_df(lake, silver_key(release, name), df)
    write_json(lake, f"silver/release={release}/_build.json",
               {"inputs": inputs_signature(lake, release), "issues": issues, "landfill": landfill})
    return {"release": release, "issues": issues, "built": True,
            "rows": {"facilities": len(fac), "pop_points": len(pts), "road_edges": len(edges)}}


def _assign_local_gov(fac: pd.DataFrame, lgs: pd.DataFrame) -> list[str | None]:
    out: list[str | None] = [None] * len(fac)
    if fac.empty:
        return out
    lon, lat = fac["lon"].to_numpy(), fac["lat"].to_numpy()
    for gid, g in zip(lgs["gers_id"], geo.from_wkb(lgs["geometry"]), strict=True):
        inside = shapely.contains_xy(g, lon, lat)
        for k in np.flatnonzero(inside):
            out[k] = out[k] or gid
    return out


def ingested_releases(lake: Lake) -> list[str]:
    return sorted(load_manifest(lake)["releases"])


def run_gold(lake: Lake, release: str, run_id: str | None = None) -> dict:
    run_id = run_id or new_run_id()
    build = read_json(lake, f"silver/release={release}/_build.json")
    if build is None:
        raise RuntimeError(f"silver for {release} has not been built")
    s = {name: _read_df(lake, silver_key(release, name)) for name in
         ("population", "haul", "access", "facilities")}

    releases = [r for r in ingested_releases(lake) if r <= release]
    per_release = {r: _read_df(lake, silver_key(r, "facilities")) for r in releases
                   if lake.exists(silver_key(r, "facilities"))}
    history = gold.facility_history(releases, per_release)
    out = gold.build_gold(s["population"], s["haul"], s["access"], s["facilities"], history)

    current = read_json(lake, CURRENT)
    previous_release = current["release"] if current and current["release"] != release else None
    previous_gold = None
    if previous_release:
        previous_gold = {"facility_registry": _read_df(lake, gold_key(previous_release, "facility_registry"))}
    earlier = [r for r in releases if r < release and r in per_release]
    out["facility_changes"] = gold.facility_changes(per_release[earlier[-1]] if earlier else None,
                                                    s["facilities"], release)

    issues = build["issues"] + quality.gold_checks(out, previous_gold)
    verdict = quality.decide(issues)
    report = {"run_id": run_id, "release": release, "inputs": build["inputs"], **verdict,
              "rows": {k: len(v) for k, v in out.items()}, "at": datetime.now(UTC).isoformat()}
    write_json(lake, f"quality/release={release}/run={run_id}.json", report)
    if not verdict["passed"]:
        log.error("release %s blocked: %s", release, verdict["blocking"])
        return report
    for name, df in out.items():
        _write_df(lake, gold_key(release, name), df)
    write_json(lake, CURRENT, {"release": release, "run_id": run_id, "published_at": report["at"]})
    return report


def run_all(source: Source, hrsl_source: Source, lake: Lake, release: str | None = None) -> dict:
    ing = run_ingest(source, hrsl_source, lake, release)
    rel = ing["release"]
    sig = inputs_signature(lake, rel)
    current = read_json(lake, CURRENT)
    if current:
        built = read_json(lake, f"silver/release={current['release']}/_build.json") or {}
        if built.get("inputs") == sig and current["release"] == rel:
            return {"release": rel, "ingest": ing, "status": "unchanged"}
    sv = run_silver(lake, rel)
    if not sv["built"]:
        report = quality.decide(sv["issues"])
        write_json(lake, f"quality/release={rel}/run={new_run_id()}.json", {"release": rel, **report})
        return {"release": rel, "ingest": ing, "status": "blocked", **report}
    report = run_gold(lake, rel)
    return {"release": rel, "ingest": ing, "status": "published" if report["passed"] else "blocked", "gold": report}


def load_current(lake: Lake, table: str) -> tuple[str, pd.DataFrame]:
    current = read_json(lake, CURRENT)
    if not current:
        raise RuntimeError("nothing published yet; run the pipeline first")
    return current["release"], _read_df(lake, gold_key(current["release"], table))
