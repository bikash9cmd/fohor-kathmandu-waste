"""The two computations SQL is bad at: shortest truck routes and nearest-facility distance."""
from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from fohor import config, geo


def _issue(check: str, severity: str, detail: str) -> dict:
    return {"check": check, "severity": severity, "detail": detail}


def road_graph(edges: pd.DataFrame) -> nx.Graph:
    g = nx.Graph()
    # Keep the shorter of parallel edges between the same two connectors.
    e = edges.sort_values("length_m").drop_duplicates(["u", "v"])
    g.add_weighted_edges_from(zip(e["u"], e["v"], e["length_m"], strict=True))
    return g


def haul_distances(edges: pd.DataFrame, nodes: pd.DataFrame, pts: pd.DataFrame, landfill: tuple[float, float],
                   max_snap_m: float = 500.0) -> tuple[pd.DataFrame, list[dict]]:
    """Road distance from where people live to the landfill gate, per local government.

    Snapping goes to the largest connected component only. The connector nearest the
    landfill is on an internal service road that the extract does not join to the
    public network; snapping there made every route "unreachable" (bug #5).
    """
    issues: list[dict] = []
    g = road_graph(edges)
    main = max(nx.connected_components(g), key=len)
    share = len(main) / max(1, g.number_of_nodes())
    if share < 0.9:
        issues.append(_issue("road_graph_connected", "warn", f"largest component holds only {share:.0%} of nodes"))
    n = nodes[nodes["node"].isin(main)].reset_index(drop=True)
    nx_, ny_ = geo.to_metres(n["lon"].to_numpy(), n["lat"].to_numpy())
    tree = cKDTree(np.column_stack([nx_, ny_]))

    lx, ly = geo.to_metres(landfill[0], landfill[1])
    gate_d, gate_i = tree.query([lx, ly])
    if gate_d > max_snap_m:
        issues.append(_issue("landfill_snap", "block", f"nearest connected road is {gate_d:.0f} m from the landfill"))
        return pd.DataFrame(), issues
    gate = n.at[int(gate_i), "node"]
    dist = nx.single_source_dijkstra_path_length(g, gate, weight="weight")
    node_km = np.array([dist.get(k, np.nan) for k in n["node"]]) / 1000.0

    px, py = geo.to_metres(pts["lon"].to_numpy(), pts["lat"].to_numpy())
    snap_d, snap_i = tree.query(np.column_stack([px, py]))
    km = node_km[snap_i] + snap_d / 1000.0
    ok = np.isfinite(km) & (snap_d <= max_snap_m)
    p = pts.assign(haul_km=km, ok=ok)
    far = p.loc[~ok, "weight"].sum() / max(1.0, p["weight"].sum())
    if far > 0.02:
        issues.append(_issue("haul_coverage", "warn", f"{far:.1%} of people are >{max_snap_m:.0f} m from a truck road"))
    p = p[p["ok"]]
    out = (p.groupby("gers_id")
             .apply(lambda d: pd.Series({
                 "haul_km_mean": np.average(d["haul_km"], weights=d["weight"]),
                 "haul_km_p10": _wq(d["haul_km"].to_numpy(), d["weight"].to_numpy(), 0.1),
                 "haul_km_p90": _wq(d["haul_km"].to_numpy(), d["weight"].to_numpy(), 0.9),
             }), include_groups=False)
             .reset_index())
    out["landfill_gate_snap_m"] = round(float(gate_d), 1)
    return out, issues


def _wq(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    cw = np.cumsum(weights[order])
    return float(values[order][np.searchsorted(cw, q * cw[-1])])


def drop_off_access(pts: pd.DataFrame, facilities: pd.DataFrame) -> pd.DataFrame:
    """Straight-line distance from every populated 30 m cell to the nearest active drop-off.

    Straight line, not walking distance: it is a lower bound, which is the honest
    direction to err in when the headline is "most people are far from one".
    """
    f = facilities[(facilities["kind"] == "drop_off") & facilities["active"]]
    px, py = geo.to_metres(pts["lon"].to_numpy(), pts["lat"].to_numpy())
    if f.empty:
        d = np.full(len(pts), np.inf)
    else:
        fx, fy = geo.to_metres(f["lon"].to_numpy(), f["lat"].to_numpy())
        d, _ = cKDTree(np.column_stack([fx, fy])).query(np.column_stack([px, py]))
    rows = []
    p = pts.assign(d=d)
    for gid, grp in p.groupby("gers_id"):
        w = grp["weight"].to_numpy()
        row = {"gers_id": gid, "nearest_drop_off_m_median": _wq(grp["d"].to_numpy(), w, 0.5)}
        for r in config.ACCESS_RADII_M:
            row[f"share_within_{r}m"] = float(w[grp["d"].to_numpy() <= r].sum() / max(1e-9, w.sum()))
        rows.append(row)
    return pd.DataFrame(rows)
