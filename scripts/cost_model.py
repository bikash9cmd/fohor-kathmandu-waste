"""Monthly cost of running Fohor on AWS (us-west-2, on-demand prices, October 2026).

    python scripts/cost_model.py

Inputs are measured where possible (bytes read, run times from a local run against the
real buckets) and marked as assumptions where not. docs/COST.md explains each line.
"""
from __future__ import annotations

# --- prices (us-west-2) ---------------------------------------------------------------
LAMBDA_ARM_GB_S = 0.0000133334
LAMBDA_REQ = 0.20 / 1e6
SFN_TRANSITION = 0.000025
S3_GB_MONTH = 0.023
S3_PUT = 0.005 / 1000
S3_GET = 0.0004 / 1000
ATHENA_TB = 5.0
ATHENA_MIN_BYTES = 10 * 1024**2  # every query bills at least 10 MB
CW_METRIC = 0.30
CW_ALARM = 0.10
CW_LOGS_GB = 0.50
ECR_GB = 0.10

# --- workload -------------------------------------------------------------------------
RELEASES_PER_MONTH = 1.25     # monthly releases plus the odd patch (2026-09-23.1)
SENSOR_RUNS = 4.3             # weekly schedule
# (memory GB, seconds) per build, from a local run; Lambda in-region should be faster.
STEPS = {
    "ingest x6 themes": (1.5, 6 * 12),
    "hrsl": (1.0, 8),
    "silver": (2.0, 10),
    "gold": (1.0, 4),
}
SENSOR = (0.25, 2)
TRANSITIONS_PER_BUILD = 20
NEW_BRONZE_GB_PER_RELEASE = 0.04  # changed themes only; unchanged ones are reused
MONTHS_OF_HISTORY = 12           # average lake size in year one
ATHENA_QUERIES = 1000            # an analyst or a dashboard, generously
CUSTOM_METRICS = 2               # ReleaseAgeDays, ReleasesBlocked
ALARMS = 4
LOG_GB = 0.05
IMAGE_GB = 0.45


def model() -> list[tuple[str, float]]:
    gb_s = sum(m * s for m, s in STEPS.values()) * RELEASES_PER_MONTH + SENSOR[0] * SENSOR[1] * SENSOR_RUNS
    invocations = (6 + 3) * RELEASES_PER_MONTH + SENSOR_RUNS
    lake_gb = 0.06 + NEW_BRONZE_GB_PER_RELEASE * RELEASES_PER_MONTH * MONTHS_OF_HISTORY / 2 + 0.02 * MONTHS_OF_HISTORY
    lines = [
        ("Lambda compute", gb_s * LAMBDA_ARM_GB_S + invocations * LAMBDA_REQ),
        ("Step Functions", TRANSITIONS_PER_BUILD * RELEASES_PER_MONTH * SFN_TRANSITION
         + 4 * SENSOR_RUNS * SFN_TRANSITION),
        ("S3 storage (lake)", lake_gb * S3_GB_MONTH),
        ("S3 requests (our bucket)", 80 * RELEASES_PER_MONTH * S3_PUT + 400 * RELEASES_PER_MONTH * S3_GET),
        ("Athena", ATHENA_QUERIES * ATHENA_MIN_BYTES / 1024**4 * ATHENA_TB),
        ("CloudWatch metrics", CUSTOM_METRICS * CW_METRIC),
        ("CloudWatch alarms", ALARMS * CW_ALARM),
        ("CloudWatch logs", LOG_GB * CW_LOGS_GB),
        ("ECR image", IMAGE_GB * ECR_GB),
    ]
    return lines


def main() -> None:
    lines = model()
    total = sum(v for _, v in lines)
    width = max(len(k) for k, _ in lines)
    for k, v in lines:
        print(f"{k:<{width}}  ${v:7.3f}  {v / total:5.1%}")
    print(f"{'total':<{width}}  ${total:7.3f}")
    mon = sum(v for k, v in lines if k.startswith("CloudWatch"))
    print(f"\nmonitoring share: {mon / total:.0%}")
    # The alternative of querying Overture in place with Athena, per analyst query.
    full = 119.1 / 1024 * ATHENA_TB
    print(f"Athena over Overture directly, worst case full scan of the six themes: ${full:.2f} per query")
    print(f"Upstream bytes this pipeline reads per release: 214.5 MB of 119.1 GB ({214.5 / 119100:.2%})")


if __name__ == "__main__":
    main()
