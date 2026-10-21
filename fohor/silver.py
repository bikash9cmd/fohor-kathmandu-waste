"""Silver: conformed tables for one release, built from bronze.

  local_gov        the 18 valley local governments, pinned by GERS id, with polygons
  population       people per local government (census where we have it, HRSL otherwise)
  pop_points       HRSL points tagged with their local government and a calibrated weight
  facilities       one row per waste facility, from OSM and Meta/Microsoft places, deduplicated
  road_edges       the truck-usable road graph, connector to connector

Every builder returns (table, issues). An issue is {"check", "severity", "detail"}; the
quality gate (quality.py) decides what blocks a publish.
"""
from __future__ import annotations

import csv
import re
import unicodedata

import numpy as np
import pandas as pd
import pyarrow as pa
import shapely

from fohor import config, geo

Issue = dict


def _issue(check: str, severity: str, detail: str) -> Issue:
    return {"check": check, "severity": severity, "detail": detail}


def _norm(name: str | None) -> str:
    """Compare Devanagari names without zero-width joiners or composition differences."""
    if not name:
        return ""
    return unicodedata.normalize("NFC", name).replace("‍", "").replace("‌", "").strip()


def _primary(names) -> str | None:
    return names.get("primary") if isinstance(names, dict) else None


def _common_en(names) -> str | None:
    if not isinstance(names, dict):
        return None
    common = names.get("common")
    if common is None or len(common) == 0:
        return None
    pairs = common.items() if isinstance(common, dict) else common
    return dict(pairs).get("en")


# --- local governments ----------------------------------------------------------------

def build_local_govs(division: pa.Table, division_area: pa.Table) -> tuple[pd.DataFrame, list[Issue]]:
    issues: list[Issue] = []
    div = division.select(["id", "names", "subtype", "parent_division_id"]).to_pandas()
    areas = division_area.select(["division_id", "geometry", "is_land"]).to_pandas()
    areas = areas[areas["is_land"].fillna(True)]
    rows = []
    for lg in config.VALLEY_LOCAL_GOVS:
        match = div[div["id"] == lg.gers_id]
        how = "gers_id"
        if match.empty:
            # GERS ids are meant to be stable, but divisions have been re-keyed before.
            # Fall back to the English name inside the right district, and say so.
            district_id = config.DISTRICTS[lg.district]
            en = div["names"].map(_common_en).fillna("")
            match = div[(div["parent_division_id"] == district_id)
                        & en.str.lower().str.startswith(lg.name_en.lower().split()[0])]
            how = "name_fallback"
            if len(match) != 1:
                issues.append(_issue("local_gov_resolved", "block",
                                     f"{lg.name_en}: GERS id {lg.gers_id} gone and {len(match)} name matches"))
                continue
            issues.append(_issue("local_gov_resolved", "warn",
                                 f"{lg.name_en}: GERS id changed to {match.iloc[0]['id']}, matched by name"))
        row = match.iloc[0]
        polys = areas[areas["division_id"] == row["id"]]
        if len(polys) != 1:
            issues.append(_issue("local_gov_polygon", "block", f"{lg.name_en}: {len(polys)} land polygons"))
            continue
        geom = shapely.from_wkb(bytes(polys.iloc[0]["geometry"]))
        source_name = _primary(row["names"])
        if _norm(source_name) != _norm(lg.name_ne):
            issues.append(_issue("local_gov_name", "warn",
                                 f"{lg.name_en}: source name '{source_name}' differs from '{lg.name_ne}'"))
        area = geo.area_km2(geom)
        if not 3 <= area <= 150:
            issues.append(_issue("local_gov_area", "block", f"{lg.name_en}: implausible area {area:.1f} km2"))
        rows.append({
            "gers_id": row["id"], "name_en": lg.name_en, "name_ne": lg.name_ne, "district": lg.district,
            "source_name": source_name, "resolved_by": how, "area_km2": round(area, 2),
            "geometry": shapely.to_wkb(geom),
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        geoms = geo.from_wkb(out["geometry"])
        overlap = 0.0
        for i in range(len(geoms)):
            for j in range(i + 1, len(geoms)):
                if shapely.intersects(geoms[i], geoms[j]):
                    overlap += geo.area_km2(shapely.intersection(geoms[i], geoms[j]))
        if overlap > 0.5:
            issues.append(_issue("local_gov_overlap", "warn", f"polygons overlap by {overlap:.2f} km2"))
    return out, issues


def district_polygons(division_area: pa.Table) -> dict[str, shapely.Geometry]:
    areas = division_area.select(["division_id", "geometry"]).to_pandas()
    out = {}
    for name, gid in config.DISTRICTS.items():
        polys = areas[areas["division_id"] == gid]
        if len(polys):
            out[name] = shapely.union_all(geo.from_wkb(polys["geometry"]))
    return out


# --- population -----------------------------------------------------------------------

def load_census(path=None) -> pd.DataFrame:
    with open(path or config.SEEDS_DIR / "census_2021.csv", newline="", encoding="utf-8") as fh:
        df = pd.DataFrame(list(csv.DictReader(fh)))
    df["population"] = df["population"].astype(int)
    return df


def build_population(points: pa.Table, local_govs: pd.DataFrame, districts: dict[str, shapely.Geometry],
                     census: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[Issue]]:
    """Totals from the 2021 census, spatial pattern from HRSL.

    HRSL (2019) spreads an older census over building footprints. It puts 1.67 million
    people in Kathmandu Metropolitan City; the 2021 census counts 845,767. So HRSL is
    only used for *where* people live inside a local government, and for local
    governments whose census figure we have not sourced, its share of the district residual.
    """
    issues: list[Issue] = []
    lon = points.column("longitude").to_numpy()
    lat = points.column("latitude").to_numpy()
    pop = points.column("population").to_numpy()
    lg_of = np.full(len(pop), -1)
    geoms = geo.from_wkb(local_govs["geometry"])
    for i, g in enumerate(geoms):
        inside = shapely.contains_xy(g, lon, lat)
        doubly = inside & (lg_of >= 0)
        if doubly.any():
            issues.append(_issue("pop_point_overlap", "warn",
                                 f"{int(doubly.sum())} HRSL points inside two local governments"))
        lg_of = np.where(inside & (lg_of < 0), i, lg_of)

    district_hrsl = {d: float(pop[shapely.contains_xy(g, lon, lat)].sum()) for d, g in districts.items()}
    hrsl = np.array([pop[lg_of == i].sum() for i in range(len(local_govs))])
    lg_census = census[census["level"] == "local_gov"].set_index("name")["population"]
    dist_census = census[census["level"] == "district"].set_index("name")["population"]

    final = np.zeros(len(local_govs))
    source = np.empty(len(local_govs), dtype=object)
    for district, members in local_govs.groupby("district"):
        idx = members.index.to_numpy()
        known = [i for i in idx if local_govs.at[i, "name_en"] in lg_census]
        for i in known:
            final[i] = lg_census[local_govs.at[i, "name_en"]]
            source[i] = "census_2021"
        unknown = [i for i in idx if i not in known]
        if district not in dist_census:
            issues.append(_issue("district_census", "block", f"no 2021 census total for {district}"))
            continue
        if not unknown:
            parts = final[known].sum()
            gap = (dist_census[district] - parts) / dist_census[district]
            if abs(gap) > 0.01:
                issues.append(_issue("census_parts_sum", "warn",
                                     f"{district}: municipal figures sum to {parts:,.0f}, district total "
                                     f"{dist_census[district]:,} ({gap:+.1%}); the two published figures disagree"))
            continue
        # Census residual for the district, shared by HRSL weight among every LG in the
        # district we lack a figure for, including the rural ones outside the valley list.
        residual = dist_census[district] - final[known].sum()
        hrsl_known = hrsl[known].sum()
        hrsl_rest = district_hrsl.get(district, 0.0) - hrsl_known
        if hrsl_rest <= 0:
            issues.append(_issue("district_hrsl", "block", f"{district}: no HRSL population outside census LGs"))
            continue
        for i in unknown:
            final[i] = residual * hrsl[i] / hrsl_rest
            source[i] = "hrsl_share_of_census_residual"

    for i in range(len(local_govs)):
        if hrsl[i] > 0 and source[i] == "census_2021":
            ratio = hrsl[i] / final[i]
            if not 0.67 <= ratio <= 1.5:
                issues.append(_issue("hrsl_vs_census", "warn",
                                     f"{local_govs.at[i, 'name_en']}: HRSL {hrsl[i]:,.0f} vs census {final[i]:,.0f}"))

    scale = np.divide(final, hrsl, out=np.zeros_like(final), where=hrsl > 0)
    in_lg = lg_of >= 0
    pts = pd.DataFrame({"lon": lon[in_lg], "lat": lat[in_lg], "lg_idx": lg_of[in_lg],
                        "hrsl_pop": pop[in_lg]})
    pts["weight"] = pts["hrsl_pop"] * scale[pts["lg_idx"].to_numpy()]
    pts["gers_id"] = local_govs["gers_id"].to_numpy()[pts["lg_idx"].to_numpy()]

    cx = pts.groupby("lg_idx").apply(lambda d: np.average(d["lon"], weights=d["weight"]), include_groups=False)
    cy = pts.groupby("lg_idx").apply(lambda d: np.average(d["lat"], weights=d["weight"]), include_groups=False)
    out = pd.DataFrame({
        "gers_id": local_govs["gers_id"], "name_en": local_govs["name_en"], "district": local_govs["district"],
        "population": final.round().astype(int), "population_source": source,
        "hrsl_population": hrsl.round().astype(int),
        "pop_centroid_lon": [cx.get(i, np.nan) for i in range(len(local_govs))],
        "pop_centroid_lat": [cy.get(i, np.nan) for i in range(len(local_govs))],
    })
    return out, pts.drop(columns=["lg_idx"]), issues


# --- facilities -----------------------------------------------------------------------

INFRA_KIND = {"recycling": "drop_off", "waste_basket": "bin", "waste_disposal": "bin"}
PLACE_KIND = {"recycling_center": "drop_off", "garbage_collection_service": "collector"}
# Word-boundary matches only: substring matching on "junk" and "dump" pulled in
# "Junkiri" (firefly, a common Nepali business name) and every "Dumpling" momo shop.
NAME_PATTERN = re.compile(
    r"\b(recycl\w*|re-cycl\w*|kabad\w*|kawadi|scrap|khaalisisi|fohor|compost\w*|रिसाइक्लो|कबाडी|कवाडी|स्क्र्याप)",
    re.IGNORECASE)
NOT_A_FACILITY = {"lodging", "lodge", "fast_food_restaurant", "restaurant", "travel_company", "gym"}


def _record_id(sources) -> str | None:
    """Upstream record id without its version suffix: 'n4803502725@1' -> 'n4803502725'.
    Overrides keyed on the versioned id stopped matching the first time someone edited the node."""
    if sources is None or len(sources) == 0:
        return None
    rid = sources[0].get("record_id")
    return rid.split("@")[0] if rid else None


def _dataset(sources) -> str | None:
    if sources is None or len(sources) == 0:
        return None
    return sources[0].get("dataset")


def load_overrides(path=None) -> dict[str, dict]:
    with open(path or config.SEEDS_DIR / "facility_overrides.csv", newline="", encoding="utf-8") as fh:
        return {r["source_record"]: r for r in csv.DictReader(fh)}


def build_facilities(place: pa.Table, infrastructure: pa.Table, overrides: dict[str, dict],
                     dedupe_m: float = 75.0) -> tuple[pd.DataFrame, list[Issue]]:
    issues: list[Issue] = []
    rows = []

    infra = infrastructure.select(["id", "geometry", "names", "subtype", "class", "sources"]).to_pandas()
    infra = infra[infra["subtype"] == "waste_management"]
    for r in infra.itertuples():
        # itertuples renames `class` (a keyword) to `_5`, so read it by position: Index, id, geometry,
        # names, subtype, class, sources.
        kind = INFRA_KIND.get(r[5])
        if kind is None:
            continue
        rows.append({"gers_id": r.id, "geometry": r.geometry, "name": _primary(r.names), "kind": kind,
                     "evidence": f"osm:{r[5]}", "confidence": 1.0, "dataset": _dataset(r.sources),
                     "source_record": _record_id(r.sources)})

    pl = place.select(["id", "geometry", "names", "taxonomy", "confidence", "operating_status", "sources"]).to_pandas()
    for r in pl.itertuples():
        tax = r.taxonomy or {}
        primary = tax.get("primary")
        name = _primary(r.names)
        if r.operating_status in ("permanently_closed",):
            continue
        if primary in PLACE_KIND:
            kind, evidence = PLACE_KIND[primary], f"category:{primary}"
        elif name and NAME_PATTERN.search(name) and primary not in NOT_A_FACILITY:
            # Mis-categorised upstream (e.g. "Boudha Garbage Recycling" is a tour_operator).
            kind, evidence = "drop_off", f"name (category was {primary})"
        else:
            continue
        rows.append({"gers_id": r.id, "geometry": r.geometry, "name": name, "kind": kind, "evidence": evidence,
                     "confidence": float(r.confidence or 0), "dataset": _dataset(r.sources),
                     "source_record": _record_id(r.sources)})

    df = pd.DataFrame(rows, columns=["gers_id", "geometry", "name", "kind", "evidence", "confidence", "dataset",
                                     "source_record"])
    if df.empty:
        issues.append(_issue("facilities_found", "block", "no waste facilities in the release"))
        return df.assign(lon=[], lat=[], review=[], duplicate_of=[], active=[], facility_key=[]), issues

    pts = shapely.centroid(geo.from_wkb(df["geometry"]))
    df["lon"], df["lat"] = shapely.get_x(pts), shapely.get_y(pts)
    df["geometry"] = shapely.to_wkb(pts)

    # Human review, versioned in git. Exclude or reclassify by upstream record id.
    df["review"] = "auto"
    for i, r in df.iterrows():
        o = overrides.get(r["source_record"] or "")
        if not o:
            continue
        if o["action"] == "exclude":
            df.at[i, "review"] = f"excluded: {o['reason']}"
        elif o["action"] == "reclassify":
            df.at[i, "kind"] = o["kind"]
            df.at[i, "review"] = f"reclassified: {o['reason']}"
    unused = set(overrides) - set(df["source_record"].dropna())
    if unused:
        issues.append(_issue("override_unused", "warn", f"{len(unused)} overrides match nothing: {sorted(unused)}"))

    # Conflation: the same kabadi shop is often in OSM and in Meta's places. Prefer OSM
    # (it has the tag a mapper chose); keep both rows, mark the duplicate.
    df["duplicate_of"] = None
    x, y = geo.to_metres(df["lon"].to_numpy(), df["lat"].to_numpy())
    order = np.argsort(-(df["evidence"].str.startswith("osm:").to_numpy().astype(int)), kind="stable")
    for a_pos, a in enumerate(order):
        if df.at[a, "duplicate_of"] is not None:
            continue
        for b in order[a_pos + 1:]:
            if df.at[b, "duplicate_of"] is not None or df.at[a, "kind"] != df.at[b, "kind"]:
                continue
            if np.hypot(x[a] - x[b], y[a] - y[b]) <= dedupe_m and _same_name(df.at[a, "name"], df.at[b, "name"]):
                df.at[b, "duplicate_of"] = df.at[a, "gers_id"]
    df["active"] = df["duplicate_of"].isna() & ~df["review"].str.startswith("excluded")
    df["facility_key"] = [facility_key(d, r, g) for d, r, g in zip(df["dataset"], df["source_record"], df["gers_id"],
                                                                     strict=True)]
    return df, issues


def facility_key(dataset: str | None, record: str | None, gers_id: str) -> str:
    """Identity that survives a release. Overture's 2026-09-23.1 patch gave every OSM-derived
    base feature in the valley a new GERS id, so keying history on GERS id reported 50
    facilities closed and 50 opened overnight (bug #1). The upstream record id did not move."""
    if record and dataset:
        return f"{'osm' if dataset == 'OpenStreetMap' else dataset.lower()}:{record}"
    return f"gers:{gers_id}"


def _same_name(a: str | None, b: str | None) -> bool:
    if not isinstance(a, str) or not isinstance(b, str) or not a or not b:
        return True  # an unnamed point next to a named one of the same kind is the same place
    ta = set(re.findall(r"\w+", a.lower()))
    tb = set(re.findall(r"\w+", b.lower()))
    return len(ta & tb) / max(1, min(len(ta), len(tb))) >= 0.5


# --- roads ----------------------------------------------------------------------------

def build_road_edges(segment: pa.Table) -> tuple[pd.DataFrame, pd.DataFrame, list[Issue]]:
    """Split each segment at its connectors. Overture's `at` is a fraction of segment length."""
    issues: list[Issue] = []
    seg = segment.select(["id", "geometry", "subtype", "class", "connectors"]).to_pandas()
    seg = seg[(seg["subtype"] == "road") & seg["class"].isin(config.TRUCK_ROAD_CLASSES)]
    lines = geo.from_wkb(seg["geometry"])
    us, vs, lengths, classes, sids = [], [], [], [], []
    node_xy: dict[str, tuple[float, float]] = {}
    no_conn = 0
    for line, cls, sid, conns in zip(lines, seg["class"], seg["id"], seg["connectors"], strict=True):
        if conns is None or len(conns) < 2:
            no_conn += 1
            continue
        length = geo.line_length_m(line)
        conns = sorted(conns, key=lambda c: c["at"])
        for c in conns:
            if c["connector_id"] not in node_xy:
                p = shapely.line_interpolate_point(line, c["at"], normalized=True)
                node_xy[c["connector_id"]] = (p.x, p.y)
        for c0, c1 in zip(conns[:-1], conns[1:], strict=True):
            us.append(c0["connector_id"])
            vs.append(c1["connector_id"])
            lengths.append((c1["at"] - c0["at"]) * length)
            classes.append(cls)
            sids.append(sid)
    if no_conn:
        issues.append(_issue("segment_connectors", "warn", f"{no_conn} truck-road segments without two connectors"))
    edges = pd.DataFrame({"u": us, "v": vs, "length_m": lengths, "class": classes, "segment_id": sids})
    nodes = pd.DataFrame([(k, x, y) for k, (x, y) in node_xy.items()], columns=["node", "lon", "lat"])
    return edges, nodes, issues


def landfill_point(land_use: pa.Table) -> tuple[tuple[float, float] | None, list[Issue]]:
    lu = land_use.select(["id", "geometry", "names", "class"]).to_pandas()
    hit = lu[lu["id"] == config.LANDFILL_GERS_ID]
    if hit.empty:
        hit = lu[(lu["class"] == "landfill") & (lu["names"].map(_primary) == config.LANDFILL_NAME)]
        if hit.empty:
            return None, [_issue("landfill_found", "block", f"{config.LANDFILL_NAME} not in land_use")]
        return _centroid(hit), [_issue("landfill_found", "warn", "landfill GERS id changed; matched by name")]
    return _centroid(hit), []


def _centroid(df: pd.DataFrame) -> tuple[float, float]:
    c = shapely.centroid(shapely.from_wkb(bytes(df.iloc[0]["geometry"])))
    return (c.x, c.y)
