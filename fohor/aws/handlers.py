"""AWS Lambda entry points. Same pipeline code as the CLI; only the lake location differs.

Step Functions runs them in this order (infra/template.yaml):

  sensor_handler     is there an Overture release we have not built?  -> {release, new}
  ingest_handler     one theme of that release -> bronze   (a Map state runs six at once)
  hrsl_handler       the population file -> bronze (ETag-checked, nearly always "reused")
  silver_handler     bronze -> silver for the release
  gold_handler       silver -> gold behind the quality gate; SNS on a block or on warnings
"""
from __future__ import annotations

import json
import logging
import os
import time

import boto3

from fohor import config, pipeline
from fohor.ingest import ingest_hrsl, ingest_release, latest_release, load_manifest
from fohor.source import S3Source
from fohor.storage import S3Lake, read_json

log = logging.getLogger()
log.setLevel(logging.INFO)


def _lake() -> S3Lake:
    return S3Lake(os.environ["LAKE_BUCKET"])


def _overture() -> S3Source:
    return S3Source(os.environ.get("OVERTURE_BUCKET", config.OVERTURE_BUCKET), config.OVERTURE_REGION)


def _hrsl() -> S3Source:
    return S3Source(config.HRSL_BUCKET, config.HRSL_REGION)


def _metric(name: str, value: float, unit: str = "Count") -> None:
    """CloudWatch Embedded Metric Format: a log line becomes a metric, with no PutMetricData
    call. Only metrics that an alarm watches are emitted ($0.30 a month each)."""
    print(json.dumps({
        "_aws": {"Timestamp": int(time.time() * 1000), "CloudWatchMetrics": [{
            "Namespace": "Fohor", "Dimensions": [[]], "Metrics": [{"Name": name, "Unit": unit}]}]},
        name: value,
    }))


def sensor_handler(event: dict, context=None) -> dict:
    release = event.get("release") or latest_release(_overture())
    built = read_json(_lake(), pipeline.CURRENT)
    new = event.get("force", False) or not built or built["release"] < release
    days_behind = 0
    if built and not new:
        # Overture ships roughly monthly. If our newest release is old, upstream may have
        # renamed the bucket layout and we are silently listing nothing new.
        y, m, d = (int(x) for x in built["release"].split(".")[0].split("-"))
        days_behind = (time.time() - time.mktime((y, m, d, 0, 0, 0, 0, 0, 0))) / 86400
    _metric("ReleaseAgeDays", round(days_behind, 1), "None")
    return {"release": release, "new": bool(new), "themes": sorted(config.THEMES),
            "run_id": event.get("run_id") or pipeline.new_run_id()}


def ingest_handler(event: dict, context=None) -> dict:
    result = ingest_release(_overture(), _lake(), event["release"], themes=[event["theme"]])
    return result["themes"][event["theme"]] | {"theme": event["theme"]}


def hrsl_handler(event: dict, context=None) -> dict:
    return ingest_hrsl(_hrsl(), _lake())


def silver_handler(event: dict, context=None) -> dict:
    lake = _lake()
    result = pipeline.run_silver(lake, event["release"])
    if not result["built"]:
        raise RuntimeError(f"silver blocked: {[i for i in result['issues'] if i['severity'] == 'block']}")
    return {k: event[k] for k in ("release", "run_id")} | {"silver_rows": result["rows"]}


def gold_handler(event: dict, context=None) -> dict:
    lake = _lake()
    report = pipeline.run_gold(lake, event["release"], event["run_id"])
    _metric("ReleasesBlocked", 0 if report["passed"] else 1)
    topic = os.environ.get("OPS_TOPIC")
    if topic and (not report["passed"] or report["warnings"]):
        status = "published with warnings" if report["passed"] else "BLOCKED"
        lines = [f"- [{i['severity']}] {i['check']}: {i['detail']}" for i in report["blocking"] + report["warnings"]]
        boto3.client("sns").publish(TopicArn=topic, Subject=f"Fohor {event['release']}: {status}"[:100],
                                    Message="\n".join(lines))
    manifest = load_manifest(lake)["releases"].get(event["release"], {})
    scanned = sum(e.get("scan", {}).get("bytes_read", 0) for e in manifest.values())
    return {"release": event["release"], "run_id": event["run_id"], "passed": report["passed"],
            "blocking": len(report["blocking"]), "warnings": len(report["warnings"]), "bytes_read": scanned}
