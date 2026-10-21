"""Bronze: copy the valley's slice of each Overture theme, once per distinct content.

Layout in the lake:

  bronze/overture/theme=<name>/fp=<fingerprint>/part-0.parquet
  bronze/hrsl/etag=<etag>/points.parquet
  bronze/_releases/<release>/<theme>.json   fingerprint, bronze key, scan stats
  bronze/_hrsl.json

One small JSON per (release, theme) rather than one manifest: Step Functions extracts
themes in parallel, and six Lambdas read-modify-writing one file lose each other's
updates (S3 has no compare-and-swap we could rely on when this was written).

Bronze is keyed by content fingerprint, not by release name, so a release that ships an
unchanged theme points at the copy we already have. Overture deletes old releases from
the bucket after a few months; bronze is our only way to rebuild an old release later.
"""
from __future__ import annotations

import logging
import time

from fohor import config
from fohor.source import Source, extract_theme, fingerprint, read_hrsl, theme_prefix
from fohor.storage import Lake, read_json, write_arrow, write_json

log = logging.getLogger(__name__)

RELEASES = "bronze/_releases/"
HRSL_ENTRY = "bronze/_hrsl.json"


class ThemeMissing(RuntimeError):
    """A theme we depend on is not in the release (Overture has renamed themes before)."""


def bronze_key(theme: str, fp: str) -> str:
    return f"bronze/overture/theme={theme}/fp={fp}/part-0.parquet"


def load_manifest(lake: Lake) -> dict:
    releases: dict[str, dict] = {}
    for key in lake.list(RELEASES):
        if not key.endswith(".json"):
            continue
        release, theme = key[len(RELEASES):].removesuffix(".json").split("/")
        releases.setdefault(release, {})[theme] = read_json(lake, key)
    return {"releases": releases, "hrsl": read_json(lake, HRSL_ENTRY)}


def latest_release(source: Source) -> str:
    releases = source.list_releases()
    if not releases:
        raise RuntimeError("no Overture releases listed")
    return releases[-1]


def ingest_release(source: Source, lake: Lake, release: str, themes=None, bbox=config.BBOX) -> dict:
    """Bring one release's themes into bronze. Re-running it is a no-op."""
    manifest = load_manifest(lake)
    result = {"release": release, "themes": {}}
    for name in themes or config.THEMES:
        theme = config.THEMES[name]
        files = source.list_files(theme_prefix(release, theme))
        if not files:
            raise ThemeMissing(f"{release}: no files under {theme.path}")
        fp = fingerprint(files)
        key = bronze_key(name, fp)
        if lake.exists(key):
            prior = next((r[name] for r in manifest["releases"].values()
                          if r.get(name, {}).get("fingerprint") == fp), {})
            write_json(lake, f"{RELEASES}{release}/{name}.json",
                       {**prior, "fingerprint": fp, "key": key, "status": "reused"})
            result["themes"][name] = {"status": "reused", "fingerprint": fp}
            continue
        t0 = time.monotonic()
        table, stats = extract_theme(source, files, theme, bbox)
        if table.num_rows == 0:
            raise RuntimeError(f"{release}/{name}: nothing inside the bbox; refusing to write an empty theme")
        write_arrow(lake, key, table)
        write_json(lake, f"{RELEASES}{release}/{name}.json",
                   {"fingerprint": fp, "key": key, "status": "extracted", "scan": stats.as_dict(),
                    "seconds": round(time.monotonic() - t0, 2)})
        result["themes"][name] = {"status": "extracted", "fingerprint": fp, **stats.as_dict()}
        log.info("%s %s: %d rows, read %.1f MB of %.1f GB", release, name, stats.rows,
                 stats.bytes_read / 1e6, stats.bytes_total / 1e9)
    return result


def ingest_hrsl(source: Source, lake: Lake, bbox=config.BBOX) -> dict:
    files = source.list_files(config.HRSL_KEY)
    if not files:
        raise RuntimeError(f"HRSL file missing: {config.HRSL_KEY}")
    etag = files[0].etag.split("-")[0][:16]
    key = f"bronze/hrsl/etag={etag}/points.parquet"
    if lake.exists(key):
        status = "reused"
    else:
        table = read_hrsl(source.read_bytes(config.HRSL_KEY), bbox)
        write_arrow(lake, key, table)
        status = "extracted"
    write_json(lake, HRSL_ENTRY, {"key": key, "etag": files[0].etag})
    return {"status": status, "key": key}


def bronze_for(lake: Lake, release: str) -> dict[str, str]:
    """theme -> bronze key for a release that has been ingested."""
    entries = load_manifest(lake)["releases"].get(release, {})
    missing = set(config.THEMES) - set(entries)
    if missing:
        raise KeyError(f"release {release}: themes not ingested: {sorted(missing)}")
    return {name: e["key"] for name, e in entries.items()}
