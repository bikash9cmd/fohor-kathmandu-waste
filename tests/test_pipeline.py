import pandas as pd
import pytest

from fohor import pipeline
from fohor.ingest import ingest_hrsl
from fohor.report import blockade_report
from fohor.source import LocalSource
from fohor.storage import read_json
from tests.conftest import RELEASE_A, RELEASE_B, make_release


def _run(upstream, lake, release=None):
    src = LocalSource(upstream)
    return pipeline.run_all(src, src, lake, release)


def test_end_to_end_publishes(upstream, lake):
    res = _run(upstream, lake)
    assert res["status"] == "published", res
    rel, mw = pipeline.load_current(lake, "municipality_waste")
    assert rel == RELEASE_A and len(mw) == 18
    assert abs(mw["tonnes_per_day"].sum() - 1400) <= 1
    assert mw["haul_km_mean"].between(5, 80).all()
    _, backlog = pipeline.load_current(lake, "blockade_backlog")
    valley = backlog[(backlog["name_en"].str.startswith("Kathmandu Valley")) & (backlog["days_blocked"] == 7)].iloc[0]
    assert valley["backlog_tonnes"] == 9800 and valley["truckloads"] == 1400


def test_rerun_with_same_inputs_does_nothing(upstream, lake):
    _run(upstream, lake)
    assert _run(upstream, lake)["status"] == "unchanged"


def test_landfill_snaps_past_the_unconnected_service_road(upstream, lake):
    _run(upstream, lake)
    build = read_json(lake, f"silver/release={RELEASE_A}/_build.json")
    assert not any(i["check"] == "landfill_snap" for i in build["issues"])
    haul = pipeline._read_df(lake, pipeline.silver_key(RELEASE_A, "haul"))
    assert (haul["landfill_gate_snap_m"] > 15).all()  # the island was nearer, but not connected


def test_rekeyed_release_reports_rekeys_not_churn(upstream, lake):
    _run(upstream, lake)
    make_release(upstream, RELEASE_B, rekey=True)
    assert _run(upstream, lake, RELEASE_B)["status"] == "published"
    _, changes = pipeline.load_current(lake, "facility_changes")
    assert set(changes["change"]) == {"rekeyed"}
    _, reg = pipeline.load_current(lake, "facility_registry")
    assert (reg["first_seen_release"] == RELEASE_A).all()


def test_facility_collapse_blocks_and_keeps_last_good(upstream, lake):
    _run(upstream, lake)
    make_release(upstream, RELEASE_B, facilities=False)
    res = _run(upstream, lake, RELEASE_B)
    assert res["status"] == "blocked"
    assert read_json(lake, pipeline.CURRENT)["release"] == RELEASE_A
    reports = lake.list(f"quality/release={RELEASE_B}/")
    assert reports


def test_landfill_rekey_falls_back_to_name_with_warning(upstream, lake):
    make_release(upstream, RELEASE_A, landfill_id="00000000-0000-0000-0000-000000000000")
    res = _run(upstream, lake)
    assert res["status"] == "published"
    assert any(w["check"] == "landfill_found" for w in res["gold"]["warnings"])


def test_blockade_report(upstream, lake):
    _run(upstream, lake)
    rel, backlog = pipeline.load_current(lake, "blockade_backlog")
    _, waste = pipeline.load_current(lake, "municipality_waste")
    text = blockade_report(backlog, waste, 7, rel)
    assert "9,800 t" in text and "Kathmandu Metropolitan City" in text
    assert "९,८००" in text  # Nepali digits
    with pytest.raises(ValueError):
        blockade_report(backlog, waste, 0, rel)


def test_hrsl_missing_is_an_error(upstream, lake, tmp_path):
    empty = LocalSource(tmp_path / "nothing")
    with pytest.raises(RuntimeError):
        ingest_hrsl(empty, lake)
    assert isinstance(pd.DataFrame(), pd.DataFrame)
