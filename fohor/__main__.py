"""python -m fohor <command>

  run [--release R]        ingest the latest (or given) Overture release, build, gate, publish
  rebuild --release R      rebuild silver and gold from bronze, without touching upstream
  releases                 releases upstream and in the lake
  blockade --days N        the blockade report from the published gold tables
  query "SQL"              DuckDB over the published gold tables
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from fohor import config, pipeline
from fohor.ingest import load_manifest
from fohor.report import blockade_report
from fohor.source import S3Source
from fohor.storage import open_lake


def _sources():
    return (S3Source(config.OVERTURE_BUCKET, config.OVERTURE_REGION),
            S3Source(config.HRSL_BUCKET, config.HRSL_REGION))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fohor")
    ap.add_argument("--lake", default=str(config.LAKE_ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--release")
    rb = sub.add_parser("rebuild")
    rb.add_argument("--release", required=True)
    sub.add_parser("releases")
    b = sub.add_parser("blockade")
    b.add_argument("--days", type=int, default=7)
    q = sub.add_parser("query")
    q.add_argument("sql")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("botocore").setLevel(logging.WARNING)
    lake = open_lake(args.lake)

    if args.cmd == "run":
        overture, hrsl = _sources()
        result = pipeline.run_all(overture, hrsl, lake, args.release)
        print(json.dumps({k: v for k, v in result.items() if k != "ingest"}, indent=2, default=str, ensure_ascii=False))
        return 0 if result["status"] != "blocked" else 1
    if args.cmd == "rebuild":
        pipeline.run_silver(lake, args.release)
        report = pipeline.run_gold(lake, args.release)
        print(json.dumps(report, indent=2, default=str, ensure_ascii=False))
        return 0 if report["passed"] else 1
    if args.cmd == "releases":
        overture, _ = _sources()
        print("upstream:", ", ".join(overture.list_releases()))
        print("in lake: ", ", ".join(sorted(load_manifest(lake)["releases"])))
        return 0
    if args.cmd == "blockade":
        release, backlog = pipeline.load_current(lake, "blockade_backlog")
        _, waste = pipeline.load_current(lake, "municipality_waste")
        print(blockade_report(backlog, waste, args.days, release))
        return 0
    if args.cmd == "query":
        import duckdb

        con = duckdb.connect()
        for table in ("municipality_waste", "blockade_backlog", "drop_off_access", "facility_registry",
                      "data_gaps", "facility_changes"):
            con.register(table, pipeline.load_current(lake, table)[1])
        print(con.sql(args.sql))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
