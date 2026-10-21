# Cost

About **$1.14 a month** in us-west-2, on-demand prices. The model is [`scripts/cost_model.py`](../scripts/cost_model.py) (`make cost`); the workload numbers come from running the pipeline against the real buckets.

```text
Lambda compute            $  0.002   0.2%
Step Functions            $  0.001   0.1%
S3 storage (lake)         $  0.014   1.2%
S3 requests (our bucket)  $  0.001   0.1%
Athena                    $  0.048   4.2%
CloudWatch metrics        $  0.600  52.8%
CloudWatch alarms         $  0.400  35.2%
CloudWatch logs           $  0.025   2.2%
ECR image                 $  0.045   4.0%
total                     $  1.136
```

**90% of the bill is monitoring.** The data work costs less than a cent a month. That's the honest shape of a small batch pipeline: the expensive part is knowing when it breaks.

## Where the savings come from

| Technique | Effect, measured |
|---|---|
| **Row-group pruning on bbox statistics** | 31 of 30,432 row groups read; 214.5 MB of 119.1 GB (0.18%) |
| **Column projection** | Places: `websites`, `emails`, `phones`, `brand` and `addresses` are never read |
| **Content-fingerprinted bronze** | The `2026-09-23.1` patch re-read 2 themes of 6; a re-run reads nothing |
| **Input signature on silver/gold** | Weekly sensor runs with no new release cost one `ListObjectsV2` and a 2 s Lambda |
| **Same region as Overture (us-west-2)** | No inter-region transfer for us, and none pushed onto the public bucket's sponsors |
| **Parallel footer reads** | Segment theme 55 s → 7.6 s from outside AWS (128 files, one footer GET each) |
| **arm64 Lambda** | ~20% cheaper per GB-second than x86 |
| **Only alarmed metrics are emitted, via Embedded Metric Format** | 2 custom metrics, no `PutMetricData` calls; each extra metric would add $0.30 |
| **Log retention 14-30 days** | Logs don't accumulate forever |
| **Athena 1 GB scan cap + projection** | A mistaken query can cost at most half a cent |
| **No IA/Glacier lifecycle** | The lake is ~70 MB of mostly small objects; minimum-size and minimum-duration charges would cost more than they save |

## What the alternatives would cost

| Instead of | Using | Roughly |
|---|---|---|
| Extracting once per release | Athena over Overture for every analyst query | up to $0.58 per query for a full scan of the six themes, less with pushdown, and every query pays again |
| Step Functions | MWAA (smallest environment) | ~$358/month |
| Lambda | Glue Spark job, 2 DPU, 2 min | ~$0.03 per run; fine, but slower and more to explain |
| networkx | Amazon Location route matrix, 18 origins | pennies; 111,000 origins, much more, and no control over the network |
| Athena | Redshift Serverless | base capacity billed per RPU-hour while querying; the smallest burst costs more than a month of this |
| Athena | RDS PostgreSQL + PostGIS (db.t4g.micro) | ~$12/month plus storage, idle 29 days of 30 |

## Cost guardrails in the stack

- An AWS Budget at $3/month with 80% actual and 100% forecast emails (when `OpsEmail` is set).
- The Athena workgroup's per-query scan cap.
- No always-on compute: everything scales to zero between runs.
