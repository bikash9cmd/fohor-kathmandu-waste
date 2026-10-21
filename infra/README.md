# Deploying to AWS

Everything is defined in [`template.yaml`](template.yaml) (AWS SAM). Region: **us-west-2**, next to the Overture bucket (ADR-007 in [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)).

## Prerequisites

- An AWS account and credentials (`aws configure`)
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) and Docker (the image is built for arm64)

## Deploy

```bash
sam build --template-file infra/template.yaml
sam deploy --guided --region us-west-2      # stack name e.g. fohor; set OpsEmail to get alarms
```

`sam deploy --guided` creates an ECR repository for the image and saves your answers in `samconfig.toml` (git-ignored).

## First build

The stack starts empty. Start one execution; the sensor sees no published release and builds the latest one (~200 MB read from Overture, a couple of minutes):

```bash
aws stepfunctions start-execution --state-machine-arn <StateMachineArn from the outputs> --input '{}'
```

From then on the schedule checks every Monday at 02:00 UTC and only builds when Overture has a new release.

To build a specific release (it must still be in the Overture bucket, or already in bronze):

```bash
aws stepfunctions start-execution --state-machine-arn <arn> --input '{"release": "2026-09-23.1", "force": true}'
```

## Query

In the Athena console pick the `fohor` workgroup and database and try [`sql/athena/`](../sql/athena/). Every query needs `WHERE release = '…'` (partition projection with an injected value). The current release is in `s3://<lake>/gold/_current.json`.

## Rebuild without touching upstream

Every stage is idempotent and silver/gold read only bronze. Invoke the Silver function, then Gold, with `{"release": "2026-09-23.1", "run_id": "manual"}`. Locally, `make rebuild RELEASE=2026-09-23.1 LAKE=s3://<bucket>` does the same.

## Tear down

```bash
sam delete
```

The lake bucket is versioned, so empty it first, including old versions.

## What's verified and what isn't

- `cfn-lint infra/template.yaml` passes, and CI runs it.
- The five handlers run in state-machine order against mocked S3 and SNS in `tests/test_aws_handlers.py`, with the six ingests as separate invocations like the Map state.
- The ingest code has run against the real `s3://overturemaps-us-west-2` and `s3://dataforgood-fb-data` buckets (anonymous reads), and the full pipeline has run end to end on that data locally, for both September 2026 releases.
- The stack itself has **not** been deployed to an AWS account, so expect small fixes on a first deploy (IAM edge cases, the arm64 image build, Lambda memory sizing).
