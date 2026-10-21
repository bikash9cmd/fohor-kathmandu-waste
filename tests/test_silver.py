import pyarrow as pa

from fohor import config, silver
from fohor.ingest import bronze_for, ingest_hrsl, ingest_release, load_manifest
from fohor.source import LocalSource
from fohor.storage import read_arrow
from tests.conftest import RELEASE_A, make_release


def _bronze(upstream, lake, release=RELEASE_A):
    ingest_release(LocalSource(upstream), lake, release)
    return {k: read_arrow(lake, v) for k, v in bronze_for(lake, release).items()}


def test_local_govs_pinned_by_id_and_bad_source_name_is_flagged(upstream, lake):
    t = _bronze(upstream, lake)
    lgs, issues = silver.build_local_govs(t["division"], t["division_area"])
    assert len(lgs) == 18
    mahalaxmi = lgs[lgs["name_en"] == "Mahalaxmi"].iloc[0]
    assert mahalaxmi["name_ne"] == "महालक्ष्मी नगरपालिका"          # ours, not the source's
    assert [i["check"] for i in issues] == ["local_gov_name"]
    assert not any("Dakshinkali" in i["detail"] for i in issues)   # ZWJ difference is not a mismatch


def test_missing_local_gov_blocks(upstream, lake):
    make_release(upstream, "2026-09-23.0", drop_mahalaxmi=True)
    t = _bronze(upstream, lake, "2026-09-23.0")
    lgs, issues = silver.build_local_govs(t["division"], t["division_area"])
    assert len(lgs) == 17
    assert any(i["severity"] == "block" and "Mahalaxmi" in i["detail"] for i in issues)


def test_population_uses_census_and_shares_the_residual(upstream, lake):
    t = _bronze(upstream, lake)
    ingest_hrsl(LocalSource(upstream), lake)
    lgs, _ = silver.build_local_govs(t["division"], t["division_area"])
    pts = read_arrow(lake, load_manifest(lake)["hrsl"]["key"])
    pop, points, issues = silver.build_population(pts, lgs, silver.district_polygons(t["division_area"]),
                                                  silver.load_census())
    p = pop.set_index("name_en")
    assert p.at["Kathmandu Metropolitan City", "population"] == 845_767
    assert p.at["Kathmandu Metropolitan City", "population_source"] == "census_2021"
    # Bhaktapur district has no municipal figures: its 432,132 is shared by HRSL weight.
    bkt = pop[pop["district"] == "Bhaktapur"]
    assert abs(bkt["population"].sum() - 432_132) <= 2
    assert set(bkt["population_source"]) == {"hrsl_share_of_census_residual"}
    # Lalitpur's residual is shared with the rural LGs outside the valley too.
    ltp = pop[(pop["district"] == "Lalitpur") & (pop["population_source"] != "census_2021")]
    assert ltp["population"].sum() < 551_667 - 299_843
    assert any(i["check"] == "census_parts_sum" for i in issues)
    # Point weights add up to the calibrated totals.
    assert abs(points["weight"].sum() - pop["population"].sum()) < 5


def test_facility_rules(upstream, lake):
    t = _bronze(upstream, lake)
    fac, issues = silver.build_facilities(t["place"], t["infrastructure"], silver.load_overrides())
    names = set(fac["name"].dropna())
    assert "Boudha Garbage Recycling" in names                    # by name, category was tour_operator
    assert not names & {"Naulo Junkiri Lodge", "Dumpling Fast Food Restro"}
    sand = fac[fac["name"].str.startswith("Salambu", na=False)].iloc[0]
    assert sand["source_record"] == "n4803502725"                 # version suffix stripped
    assert not sand["active"] and sand["review"].startswith("excluded")
    dup = fac[(fac["dataset"] == "meta") & (fac["name"] == "Kauda Kawadi")].iloc[0]
    assert dup["duplicate_of"] is not None and not dup["active"]
    assert fac[fac["name"] == "Doko Recyclers"].iloc[0]["kind"] == "collector"
    assert "toilets" not in set(fac["evidence"])


def test_facility_key_survives_rekeying(upstream, lake):
    a = _bronze(upstream, lake)
    make_release(upstream, "2026-09-23.0", rekey=True)
    b = _bronze(upstream, lake, "2026-09-23.0")
    fa, _ = silver.build_facilities(a["place"], a["infrastructure"], {})
    fb, _ = silver.build_facilities(b["place"], b["infrastructure"], {})
    osm_a = fa[fa["dataset"] == "OpenStreetMap"]
    osm_b = fb[fb["dataset"] == "OpenStreetMap"]
    assert set(osm_a["gers_id"]).isdisjoint(osm_b["gers_id"])
    assert set(osm_a["facility_key"]) == set(osm_b["facility_key"])


def test_road_edges_split_at_connectors():
    import shapely
    line = shapely.LineString([(85.30, 27.70), (85.32, 27.70)])
    seg = pa.Table.from_pylist([{
        "id": "s", "geometry": shapely.to_wkb(line), "subtype": "road", "class": "primary",
        "connectors": [{"connector_id": "a", "at": 0.0}, {"connector_id": "m", "at": 0.25},
                       {"connector_id": "b", "at": 1.0}]}, {
        "id": "f", "geometry": shapely.to_wkb(line), "subtype": "road", "class": "footway",
        "connectors": [{"connector_id": "a", "at": 0.0}, {"connector_id": "b", "at": 1.0}]}])
    edges, nodes, _ = silver.build_road_edges(seg)
    assert list(edges["segment_id"]) == ["s", "s"]                  # footways are not truck roads
    total = edges["length_m"].sum()
    assert 1960 < total < 1990                                     # 0.02 deg of longitude at 27.7 N
    assert abs(edges["length_m"].iloc[0] - total / 4) < 1
    assert set(nodes["node"]) == {"a", "m", "b"}
    assert config.TRUCK_ROAD_CLASSES
