"""Upstream: Overture Maps releases and the HRSL population file, both on AWS Open Data.

Two operations matter and both are cheap:

* listing a release's files with their ETags, which fingerprints a theme without
  reading it, so a patch release that republishes identical files costs nothing;
* reading only the row groups whose bbox statistics overlap the valley, and only the
  columns the pipeline uses. Overture sorts its files spatially, so the Kathmandu
  Valley lives in a handful of the ~10,000 row groups of a theme.

S3Source talks to the public buckets anonymously. LocalSource reads the same layout
from a folder, which is what the tests use.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from fohor.config import BBOX, Theme


@dataclass(frozen=True)
class RemoteFile:
    key: str
    size: int
    etag: str


class Source(Protocol):
    def list_releases(self) -> list[str]: ...
    def list_files(self, prefix: str) -> list[RemoteFile]: ...
    def open(self, key: str): ...
    def read_bytes(self, key: str) -> bytes: ...


class S3Source:
    """Anonymous reads from a public bucket. Listing uses boto3 (for ETags), reads use pyarrow."""

    def __init__(self, bucket: str, region: str, client=None, filesystem=None):
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config

        self.bucket = bucket
        self.s3 = client or boto3.client("s3", region_name=region, config=Config(signature_version=UNSIGNED))
        if filesystem is None:
            import pyarrow.fs as pafs

            filesystem = pafs.S3FileSystem(anonymous=True, region=region)
        self.fs = filesystem

    def list_releases(self) -> list[str]:
        resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix="release/", Delimiter="/")
        names = [p["Prefix"].split("/")[1] for p in resp.get("CommonPrefixes", [])]
        return sorted(n for n in names if n)

    def list_files(self, prefix: str) -> list[RemoteFile]:
        out = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".parquet") or obj["Key"].endswith(".gz"):
                    out.append(RemoteFile(obj["Key"], obj["Size"], obj["ETag"].strip('"')))
        return sorted(out, key=lambda f: f.key)

    def open(self, key: str):
        return self.fs.open_input_file(f"{self.bucket}/{key}")

    def read_bytes(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()


class LocalSource:
    """A folder laid out like the bucket: <root>/release/<release>/theme=.../*.parquet."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def list_releases(self) -> list[str]:
        base = self.root / "release"
        return sorted(p.name for p in base.iterdir() if p.is_dir()) if base.exists() else []

    def list_files(self, prefix: str) -> list[RemoteFile]:
        base = self.root / prefix
        if not base.exists():
            return []
        paths = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
        return [RemoteFile(p.relative_to(self.root).as_posix(), p.stat().st_size,
                           hashlib.md5(p.read_bytes()).hexdigest()) for p in paths]

    def open(self, key: str):
        return open(self.root / key, "rb")

    def read_bytes(self, key: str) -> bytes:
        return (self.root / key).read_bytes()


def theme_prefix(release: str, theme: Theme) -> str:
    return f"release/{release}/{theme.path}/"


def fingerprint(files: list[RemoteFile]) -> str:
    """Content identity of a theme in a release: file names and ETags, not dates or paths.

    Overture's 2026-09-23.1 patch republished places with byte-identical files under a new
    prefix; keyed on the release name, we would have re-extracted them.
    """
    h = hashlib.sha256()
    for f in sorted(files, key=lambda f: f.key.rsplit("/", 1)[-1]):
        h.update(f"{f.key.rsplit('/', 1)[-1]}:{f.etag}\n".encode())
    return h.hexdigest()[:16]


@dataclass
class ScanStats:
    files: int = 0
    row_groups_total: int = 0
    row_groups_read: int = 0
    bytes_total: int = 0
    bytes_read: int = 0
    rows: int = 0
    per_file: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "per_file"}


_BBOX_COLS = ("bbox.xmin", "bbox.xmax", "bbox.ymin", "bbox.ymax")


def _overlaps(stats: dict[str, tuple[float, float] | None], bbox) -> bool:
    """Could any row in this row group overlap bbox? Missing statistics mean 'maybe'."""
    xmin, ymin, xmax, ymax = bbox
    if any(stats.get(c) is None for c in _BBOX_COLS):
        return True
    return not (stats["bbox.xmin"][0] > xmax or stats["bbox.xmax"][1] < xmin
                or stats["bbox.ymin"][0] > ymax or stats["bbox.ymax"][1] < ymin)


def _row_group_plan(md: pq.FileMetaData, columns: tuple[str, ...], bbox) -> tuple[list[int], int, int]:
    keep, read_bytes, total_bytes = [], 0, 0
    for i in range(md.num_row_groups):
        rg = md.row_group(i)
        stats: dict[str, tuple[float, float] | None] = {}
        size = 0
        for j in range(rg.num_columns):
            col = rg.column(j)
            path = col.path_in_schema
            total_bytes += col.total_compressed_size
            if path.split(".")[0] in columns:
                size += col.total_compressed_size
            if path in _BBOX_COLS:
                s = col.statistics
                stats[path] = (s.min, s.max) if s is not None and s.has_min_max else None
        if _overlaps(stats, bbox):
            keep.append(i)
            read_bytes += size
    return keep, read_bytes, total_bytes


def bbox_filter(table: pa.Table, bbox) -> pa.Table:
    """Rows whose bbox overlaps ours (not rows contained in it: a municipality that
    crosses the box edge must still come through)."""
    xmin, ymin, xmax, ymax = bbox
    b = table.column("bbox")
    mask = pc.and_(
        pc.and_(pc.less_equal(pc.struct_field(b, "xmin"), xmax), pc.greater_equal(pc.struct_field(b, "xmax"), xmin)),
        pc.and_(pc.less_equal(pc.struct_field(b, "ymin"), ymax), pc.greater_equal(pc.struct_field(b, "ymax"), ymin)),
    )
    return table.filter(mask)


def _extract_file(source: Source, f: RemoteFile, theme: Theme, bbox) -> tuple[pa.Table | None, dict]:
    with source.open(f.key) as fh:
        pf = pq.ParquetFile(fh)
        md = pf.metadata
        keep, read_bytes, total_bytes = _row_group_plan(md, theme.columns, bbox)
        part = None
        if keep:
            cols = [c for c in theme.columns if c in pf.schema_arrow.names]
            part = bbox_filter(pf.read_row_groups(keep, columns=cols), bbox)
    return part, {"key": f.key, "row_groups": md.num_row_groups, "read": len(keep),
                  "bytes_read": read_bytes, "bytes_total": total_bytes}


def extract_theme(source: Source, files: list[RemoteFile], theme: Theme, bbox=BBOX,
                  max_workers: int = 16) -> tuple[pa.Table, ScanStats]:
    """Footers are read one GET per file, and road segments come in 128 files, so files are
    planned and read in parallel: sequentially, the segment theme took 55 s from outside AWS."""
    from concurrent.futures import ThreadPoolExecutor

    stats = ScanStats()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(lambda f: _extract_file(source, f, theme, bbox), files))
    parts = []
    for part, info in results:
        stats.files += 1
        stats.row_groups_total += info["row_groups"]
        stats.row_groups_read += info["read"]
        stats.bytes_total += info["bytes_total"]
        stats.bytes_read += info["bytes_read"]
        stats.per_file.append(info)
        if part is not None and part.num_rows:
            parts.append(part)
    if not parts:
        return pa.table({}), stats
    table = pa.concat_tables(parts, promote_options="permissive")
    stats.rows = table.num_rows
    return table, stats


def read_hrsl(raw: bytes, bbox=BBOX) -> pa.Table:
    """HRSL CSV (tab separated, despite the name) -> points inside bbox."""
    import gzip

    import pyarrow.csv as pacsv

    data = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    table = pacsv.read_csv(io.BytesIO(data), parse_options=pacsv.ParseOptions(delimiter="\t"))
    xmin, ymin, xmax, ymax = bbox
    lon, lat = table.column("longitude"), table.column("latitude")
    mask = pc.and_(pc.and_(pc.greater_equal(lon, xmin), pc.less_equal(lon, xmax)),
                   pc.and_(pc.greater_equal(lat, ymin), pc.less_equal(lat, ymax)))
    return table.filter(mask)
