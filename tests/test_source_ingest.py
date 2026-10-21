import shutil

import pyarrow.parquet as pq
import pytest

from fohor import config
from fohor.ingest import ThemeMissing, bronze_for, ingest_hrsl, ingest_release, load_manifest
from fohor.source import LocalSource, RemoteFile, extract_theme, fingerprint, theme_prefix
from fohor.storage import read_arrow
from tests.conftest import RELEASE_A, RELEASE_B, make_release


def test_extract_reads_only_overlapping_row_groups(upstream):
    src = LocalSource(upstream)
    theme = config.THEMES["place"]
    files = src.list_files(theme_prefix(RELEASE_A, theme))
    table, stats = extract_theme(src, files, theme)
    assert table.num_rows == 6                       # the far-away rows are gone
    assert stats.row_groups_read < stats.row_groups_total
    assert stats.bytes_read < stats.bytes_total
    assert set(table.column_names) <= set(theme.columns)


def test_row_group_without_statistics_is_read_not_skipped(upstream, tmp_path):
    src = LocalSource(upstream)
    theme = config.THEMES["place"]
    f = src.list_files(theme_prefix(RELEASE_A, theme))[0]
    t = pq.read_table(upstream / f.key)
    nostats = tmp_path / "nostats" / f.key
    nostats.parent.mkdir(parents=True)
    pq.write_table(t, nostats, write_statistics=False, row_group_size=50)
    s2 = LocalSource(tmp_path / "nostats")
    table, stats = extract_theme(s2, s2.list_files(theme_prefix(RELEASE_A, theme)), theme)
    assert table.num_rows == 6 and stats.row_groups_read == stats.row_groups_total


def test_fingerprint_ignores_release_prefix():
    a = [RemoteFile("release/2026-09-23.0/theme=places/type=place/part-0.parquet", 10, "abc")]
    b = [RemoteFile("release/2026-09-23.1/theme=places/type=place/part-0.parquet", 10, "abc")]
    c = [RemoteFile("release/2026-09-23.1/theme=places/type=place/part-0.parquet", 10, "abd")]
    assert fingerprint(a) == fingerprint(b) != fingerprint(c)


def test_ingest_is_idempotent_and_patch_release_reuses_unchanged_themes(upstream, lake):
    src = LocalSource(upstream)
    first = ingest_release(src, lake, RELEASE_A)
    assert {v["status"] for v in first["themes"].values()} == {"extracted"}
    again = ingest_release(src, lake, RELEASE_A)
    assert {v["status"] for v in again["themes"].values()} == {"reused"}

    # A patch release that republishes identical files under a new prefix.
    shutil.copytree(upstream / "release" / RELEASE_A, upstream / "release" / RELEASE_B)
    patch = ingest_release(src, lake, RELEASE_B)
    assert {v["status"] for v in patch["themes"].values()} == {"reused"}
    assert bronze_for(lake, RELEASE_A) == bronze_for(lake, RELEASE_B)
    assert set(load_manifest(lake)["releases"]) == {RELEASE_A, RELEASE_B}


def test_changed_theme_is_extracted_again(upstream, lake):
    src = LocalSource(upstream)
    ingest_release(src, lake, RELEASE_A)
    make_release(upstream, RELEASE_B, rekey=True)
    res = ingest_release(src, lake, RELEASE_B)
    assert res["themes"]["infrastructure"]["status"] == "extracted"


def test_missing_theme_fails_loudly(upstream, lake):
    shutil.rmtree(upstream / "release" / RELEASE_A / "theme=places")
    with pytest.raises(ThemeMissing):
        ingest_release(LocalSource(upstream), lake, RELEASE_A)


def test_hrsl_is_clipped_to_the_bbox(upstream, lake):
    res = ingest_hrsl(LocalSource(upstream), lake)
    pts = read_arrow(lake, res["key"])
    assert pts.num_rows == 18 * 16 + 8                # the far-west point is dropped
    assert ingest_hrsl(LocalSource(upstream), lake)["status"] == "reused"
