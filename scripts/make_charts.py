"""Charts in docs/img, drawn from the silver and gold tables of a local lake.

    python scripts/make_charts.py --lake lake
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402
import shapely  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

from fohor import analysis, geo, pipeline  # noqa: E402
from fohor.storage import open_lake, read_json  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"]
BAND = "#e9e8e4"

plt.rcParams.update({
    "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "xtick.color": INK_2,
    "ytick.color": INK_2, "text.color": INK, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
})


def access_map(lake, release: str, out: Path) -> None:
    lgs = pipeline._read_df(lake, pipeline.silver_key(release, "local_gov"))
    fac = pipeline._read_df(lake, pipeline.silver_key(release, "facilities"))
    edges = pipeline._read_df(lake, pipeline.silver_key(release, "road_edges"))
    nodes = pipeline._read_df(lake, pipeline.silver_key(release, "road_nodes"))
    pop = pipeline._read_df(lake, pipeline.silver_key(release, "population"))
    _, acc = pipeline.load_current(lake, "drop_off_access")
    landfill = read_json(lake, f"silver/release={release}/_build.json")["landfill"]
    share = acc.set_index("gers_id")["share_within_2km"]

    bounds = [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0001]
    cmap, norm = ListedColormap(BLUE_RAMP), BoundaryNorm(bounds, len(BLUE_RAMP))
    fig, ax = plt.subplots(figsize=(9, 7.2))
    for gid, name, wkb in zip(lgs["gers_id"], lgs["name_en"], lgs["geometry"], strict=True):
        g = shapely.from_wkb(bytes(wkb))
        polys = getattr(g, "geoms", [g])
        for p in polys:
            x, y = p.exterior.xy
            ax.fill(x, y, color=cmap(norm(share.get(gid, 0))), ec=SURFACE, lw=1.2)
        c = g.representative_point()
        if name in {"Kathmandu Metropolitan City", "Lalitpur Metropolitan City", "Bhaktapur", "Tarakeshwar",
                    "Godawari", "Chandragiri", "Shankharapur", "Tokha"}:
            label = name.replace(" Metropolitan City", "")
            ax.text(c.x, c.y, label, fontsize=8, ha="center", va="center", color=INK,
                    bbox={"boxstyle": "round,pad=0.15", "fc": SURFACE, "ec": "none", "alpha": 0.75})

    # The truck route from Kathmandu's population centre to the landfill gate.
    g = analysis.road_graph(edges)
    main = max(nx.connected_components(g), key=len)
    n = nodes[nodes["node"].isin(main)].reset_index(drop=True)
    tree = cKDTree(np.column_stack(geo.to_metres(n["lon"].to_numpy(), n["lat"].to_numpy())))
    kmc = pop[pop["name_en"] == "Kathmandu Metropolitan City"].iloc[0]
    _, a = tree.query(np.column_stack(geo.to_metres(kmc["pop_centroid_lon"], kmc["pop_centroid_lat"])))
    _, b = tree.query(np.column_stack(geo.to_metres(landfill[0], landfill[1])))
    path = nx.shortest_path(g, n.at[int(a[0]), "node"], n.at[int(b[0]), "node"], weight="weight")
    xy = n.set_index("node").loc[path, ["lon", "lat"]].to_numpy()
    ax.plot(xy[:, 0], xy[:, 1], color=ORANGE, lw=2, solid_capstyle="round", label="Truck route, Kathmandu to landfill")

    d = fac[(fac["kind"] == "drop_off") & fac["active"]]
    ax.scatter(d["lon"], d["lat"], s=22, color=INK, ec=SURFACE, lw=1, zorder=3, label="Mapped recycling drop-off")
    ax.scatter([landfill[0]], [landfill[1]], s=120, marker="^", color=ORANGE, ec=SURFACE, lw=1.5, zorder=4,
               label="Bancharedanda landfill")
    ax.set_xlim(85.20, 85.62)
    ax.set_ylim(27.55, 27.84)
    ax.set_aspect(1 / np.cos(np.radians(27.7)))
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    cb = fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.01, ticks=bounds[:-1] + [1.0])
    cb.ax.set_yticklabels([f"{b:.0%}" for b in bounds[:-1]] + ["100%"])
    cb.outline.set_visible(False)
    cb.set_label("People within 2 km of a mapped drop-off")
    ax.legend(loc="lower right", frameon=False, fontsize=8.5)
    ax.set_title(f"Most of the valley has no mapped recycling drop-off nearby (Overture {release})",
                 loc="left", fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def tonnage_chart(lake, out: Path) -> None:
    _, mw = pipeline.load_current(lake, "municipality_waste")
    mw = mw.sort_values("tonnes_per_day")
    y = np.arange(len(mw))
    fig, ax = plt.subplots(figsize=(8.5, 6.4))
    kmc = int(np.flatnonzero(mw["name_en"].to_numpy() == "Kathmandu Metropolitan City")[0])
    ax.fill_betweenx([kmc - 0.4, kmc + 0.4], 500, 600, color=BAND, lw=0, zorder=0)
    ax.text(550, kmc - 0.75, "KMC's own figure,\n500-600 t", ha="center", va="top", fontsize=8, color=INK_2)
    lo = np.minimum(mw["tonnes_per_day"], mw["tonnes_per_day_building_share"])
    hi = np.maximum(mw["tonnes_per_day"], mw["tonnes_per_day_building_share"])
    ax.hlines(y, lo, hi, color=GRID, lw=2, zorder=1)
    ax.scatter(mw["tonnes_per_day_building_share"], y, s=44, marker="D", color=ORANGE, ec=SURFACE, lw=1.5,
               zorder=3, label="Shared by building-based population (HRSL)")
    ax.scatter(mw["tonnes_per_day"], y, s=40, color=BLUE, ec=SURFACE, lw=1.5, zorder=4,
               label="Shared by 2021 census population")
    ax.set_yticks(y, mw["name_en"].str.replace(" Metropolitan City", " Metro"))
    ax.set_xlabel("Tonnes a day sent to Bancharedanda (of ~1,400 valley total)")
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.legend(loc="lower right", frameon=False, fontsize=8.5)
    ax.set_title("Where the 1,400 t/day comes from depends on whose population you trust",
                 loc="left", fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", default="lake")
    ap.add_argument("--out", default="docs/img")
    args = ap.parse_args()
    lake = open_lake(args.lake)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    release = read_json(lake, pipeline.CURRENT)["release"]
    access_map(lake, release, out / "drop_off_access.png")
    tonnage_chart(lake, out / "tonnage_by_local_gov.png")


if __name__ == "__main__":
    main()
