"""The Lambdas in Step Functions order, against mocked S3 and SNS."""
import boto3
import pytest
from moto import mock_aws

from fohor import config
from fohor.aws import handlers
from fohor.source import LocalSource
from tests.conftest import RELEASE_A


@pytest.fixture
def aws(monkeypatch, upstream):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-west-2")
        s3.create_bucket(Bucket="fohor-lake", CreateBucketConfiguration={"LocationConstraint": "us-west-2"})
        topic = boto3.client("sns", region_name="us-west-2").create_topic(Name="fohor-ops")["TopicArn"]
        monkeypatch.setenv("LAKE_BUCKET", "fohor-lake")
        monkeypatch.setenv("OPS_TOPIC", topic)
        monkeypatch.setattr(handlers, "_overture", lambda: LocalSource(upstream))
        monkeypatch.setattr(handlers, "_hrsl", lambda: LocalSource(upstream))
        yield s3


def test_state_machine_order(aws):
    state = handlers.sensor_handler({})
    assert state["release"] == RELEASE_A and state["new"]
    # Map state: one ingest per theme, run independently.
    results = [handlers.ingest_handler({"release": state["release"], "theme": t}) for t in state["themes"]]
    assert {r["status"] for r in results} == {"extracted"}
    assert handlers.hrsl_handler({})["status"] == "extracted"
    state = handlers.silver_handler(state)
    out = handlers.gold_handler(state)
    assert out["passed"] and out["bytes_read"] > 0
    keys = [o["Key"] for o in aws.list_objects_v2(Bucket="fohor-lake")["Contents"]]
    assert "gold/_current.json" in keys
    assert any(k.startswith("gold/municipality_waste/release=") for k in keys)

    again = handlers.sensor_handler({})
    assert not again["new"]


def test_parallel_theme_ingest_does_not_lose_manifest_entries(aws):
    # Six ingests that each saw an empty manifest when they started must all survive.
    for t in sorted(config.THEMES):
        handlers.ingest_handler({"release": RELEASE_A, "theme": t})
    from fohor.ingest import load_manifest
    from fohor.storage import S3Lake
    assert set(load_manifest(S3Lake("fohor-lake"))["releases"][RELEASE_A]) == set(config.THEMES)
