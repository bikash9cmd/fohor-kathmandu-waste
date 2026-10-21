"""A synthetic Overture release and HRSL file, laid out like the real buckets.

The geography is fake but shaped like the real thing: the 18 valley local governments
(with their real GERS ids) as 0.05 degree squares, three districts, a landfill to the
north, a 1 km road grid, and a handful of waste facilities, including the traps found
in the real data (a "Junkiri" lodge, a "Dumpling" momo shop, a recycler filed as a tour
operator, a versioned OSM record id). Rows far outside the valley go in their own row
groups so the tests can see them pruned.
"""
from __future__ import annotations

import gzip
import hashlib
import uuid
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely

from fohor import config

STEP = 0.01
GRID_LON = (85.15, 85.55)
GRID_LAT = (27.55, 27.92)
LANDFILL_XY = (85.2502, 27.9002)


def _uid(*parts) -> str:
    return str(uuid.UUID(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()))


def lg_box(i: int) -> shapely.Polygon:
    col, row = i % 6, i // 6
    x0, y0 = 85.20 + 0.05 * col, 27.60 + 0.05 * row
    return shapely.box(x0, y0, x0 + 0.05, y0 + 0.05)


def _bbox(g):
    x0, y0, x1, y1 = shapely.bounds(g)
    return {"xmin": float(x0), "xmax": float(x1), "ymin": float(y0), "ymax": float(y1)}


def _names(primary, en=None):
    return {"primary": primary, "common": [("en", en)] if en else None}


def _write(path: Path, rows: list[dict], schema: pa.Schema | None = None, far_rows: int = 200):
    """Write rows plus `far_rows` copies placed in South America, in separate row groups."""
    path.parent.mkdir(parents=True, exist_ok=True)
    far = []
    if rows and far_rows:
        template = rows[0]
        for k in range(far_rows):
            g = shapely.Point(-60 - k * 0.01, -10)
            far.append({**template, "id": _uid("far", path, k), "geometry": shapely.to_wkb(g), "bbox": _bbox(g)})
    table = pa.Table.from_pylist(far[: far_rows // 2] + rows + far[far_rows // 2:], schema=schema)
    pq.write_table(table, path, row_group_size=50)


def make_release(root: Path, release: str, *, rekey: bool = False, facilities: bool = True,
                 drop_mahalaxmi: bool = False, landfill_id: str | None = None) -> None:
    base = root / "release" / release

    # divisions
    div, areas = [], []
    for i, lg in enumerate(config.VALLEY_LOCAL_GOVS):
        if drop_mahalaxmi and lg.name_en == "Mahalaxmi":
            continue
        name = "ललितपुर महानगरपालिका" if lg.name_en == "Mahalaxmi" else lg.name_ne
        g = lg_box(i)
        div.append({"id": lg.gers_id, "bbox": _bbox(g), "names": _names(name, lg.name_en), "subtype": "locality",
                    "local_type": [("en", "locality")], "parent_division_id": config.DISTRICTS[lg.district],
                    "country": "NP"})
        areas.append({"id": _uid("area", lg.gers_id), "geometry": shapely.to_wkb(g), "bbox": _bbox(g),
                      "division_id": lg.gers_id, "subtype": "locality", "class": "land", "is_land": True})
    for d, gid in config.DISTRICTS.items():
        members = [lg_box(i) for i, lg in enumerate(config.VALLEY_LOCAL_GOVS) if lg.district == d]
        if d == "Lalitpur":
            members.append(shapely.box(85.20, 27.50, 85.30, 27.60))  # rural LGs outside the valley
        g = shapely.union_all(members)
        div.append({"id": gid, "bbox": _bbox(g), "names": _names(f"{d} जिल्ला", d), "subtype": "county",
                    "local_type": [("en", "district")], "parent_division_id": None, "country": "NP"})
        areas.append({"id": _uid("area", gid), "geometry": shapely.to_wkb(g), "bbox": _bbox(g), "division_id": gid,
                      "subtype": "county", "class": "land", "is_land": True})
    _write(base / "theme=divisions/type=division/part-0.parquet", div)
    _write(base / "theme=divisions/type=division_area/part-0.parquet", areas)

    # land use: the landfill
    lf = shapely.box(LANDFILL_XY[0] - 0.001, LANDFILL_XY[1] - 0.001, LANDFILL_XY[0] + 0.001, LANDFILL_XY[1] + 0.001)
    _write(base / "theme=base/type=land_use/part-0.parquet", [{
        "id": landfill_id or config.LANDFILL_GERS_ID, "geometry": shapely.to_wkb(lf), "bbox": _bbox(lf),
        "names": _names(config.LANDFILL_NAME), "subtype": "landfill", "class": "landfill"}])

    # roads: a 1 km grid, plus an unconnected service road right next to the landfill
    segs = []
    xs = np.round(np.arange(GRID_LON[0], GRID_LON[1] + 1e-9, STEP), 4)
    ys = np.round(np.arange(GRID_LAT[0], GRID_LAT[1] + 1e-9, STEP), 4)
    for y in ys:
        for x0, x1 in zip(xs[:-1], xs[1:], strict=True):
            segs.append(((x0, y), (x1, y)))
    for x in xs:
        for y0, y1 in zip(ys[:-1], ys[1:], strict=True):
            segs.append(((x, y0), (x, y1)))
    seg_rows = []
    for a, b in segs:
        line = shapely.LineString([a, b])
        seg_rows.append({"id": _uid("seg", a, b), "geometry": shapely.to_wkb(line), "bbox": _bbox(line),
                         "subtype": "road", "class": "residential",
                         "connectors": [{"connector_id": _uid("node", a), "at": 0.0},
                                        {"connector_id": _uid("node", b), "at": 1.0}]})
    island = shapely.LineString([(LANDFILL_XY[0] + 0.0001, LANDFILL_XY[1]), (LANDFILL_XY[0] + 0.0004, LANDFILL_XY[1])])
    seg_rows.append({"id": _uid("island"), "geometry": shapely.to_wkb(island), "bbox": _bbox(island),
                     "subtype": "road", "class": "service",
                     "connectors": [{"connector_id": _uid("island", 0), "at": 0.0},
                                    {"connector_id": _uid("island", 1), "at": 1.0}]})
    _write(base / "theme=transportation/type=segment/part-0.parquet", seg_rows)

    # facilities
    tag = "rekeyed" if rekey else "orig"
    kmc = lg_box(0)
    cx, cy = kmc.centroid.x, kmc.centroid.y
    infra = []
    if facilities:
        for k, (cls, name, rec) in enumerate([
            ("recycling", "Kauda Kawadi", "w676201243@2"),
            ("recycling", None, "n2086900002@3"),
            ("recycling", "Salambu Devi Baluwa Prasodhan Udyog Pvt Ltd", "n4803502725@1"),
            ("waste_basket", None, "n7682014471@1"),
            ("waste_disposal", None, "n2027904884@3"),
        ]):
            p = shapely.Point(cx + 0.005 * k, cy)
            infra.append({"id": _uid("infra", tag, k), "geometry": shapely.to_wkb(p), "bbox": _bbox(p),
                          "names": _names(name), "subtype": "waste_management", "class": cls,
                          "sources": [{"dataset": "OpenStreetMap", "record_id": rec}]})
    p = shapely.Point(cx, cy + 0.01)
    infra.append({"id": _uid("toilet", tag), "geometry": shapely.to_wkb(p), "bbox": _bbox(p), "names": _names(None),
                  "subtype": "pedestrian", "class": "toilets",
                  "sources": [{"dataset": "OpenStreetMap", "record_id": "n1@1"}]})
    _write(base / "theme=base/type=infrastructure/part-0.parquet", infra)

    places = []
    for k, (name, primary, conf) in enumerate([
        ("Khaalisisi", "recycling_center", 0.72),
        ("Doko Recyclers", "garbage_collection_service", 0.73),
        ("Boudha Garbage Recycling", "tour_operator", 0.80),
        ("Naulo Junkiri Lodge", "lodge", 0.68),
        ("Dumpling Fast Food Restro", "fast_food_restaurant", 0.71),
        ("Kauda Kawadi", "recycling_center", 0.60),  # same shop as the OSM point, 20 m away
    ]):
        p = shapely.Point(cx + 0.002 * k, cy - 0.004) if name != "Kauda Kawadi" else shapely.Point(cx + 0.0002, cy)
        places.append({"id": _uid("place", k), "geometry": shapely.to_wkb(p), "bbox": _bbox(p), "names": _names(name),
                       "taxonomy": {"primary": primary, "hierarchy": [primary], "alternates": []},
                       "basic_category": primary, "confidence": conf, "operating_status": None,
                       "sources": [{"dataset": "meta", "record_id": str(1000 + k)}]})
    if not facilities:
        places = places[3:5]
    _write(base / "theme=places/type=place/part-0.parquet", places)


def make_hrsl(root: Path, per_lg: int = 150_000) -> None:
    rows = ["latitude\tlongitude\tpopulation"]
    for i, _ in enumerate(config.VALLEY_LOCAL_GOVS):
        b = lg_box(i)
        x0, y0, _, _ = shapely.bounds(b)
        for a in range(1, 5):
            for c in range(1, 5):
                rows.append(f"{y0 + 0.01 * c + 0.0003}\t{x0 + 0.01 * a + 0.0003}\t{per_lg / 16}")
    for a in range(1, 9):  # rural Lalitpur outside the valley
        rows.append(f"{27.55 + 0.0003}\t{85.20 + 0.01 * a + 0.0003}\t{2500}")
    rows.append("28.3\t82.4\t5.0")  # far west Nepal, outside the bbox
    path = root / config.HRSL_KEY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress("\n".join(rows).encode()))


RELEASE_A = "2026-08-20.0"
RELEASE_B = "2026-09-23.0"


@pytest.fixture
def upstream(tmp_path):
    root = tmp_path / "upstream"
    make_release(root, RELEASE_A)
    make_hrsl(root)
    return root


@pytest.fixture
def lake(tmp_path):
    from fohor.storage import LocalLake

    return LocalLake(tmp_path / "lake")
