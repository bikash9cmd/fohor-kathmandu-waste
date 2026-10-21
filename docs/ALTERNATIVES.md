# Alternatives considered

For each layer: what I chose, what else would work, and when I would switch.

## Getting the data

| Option | Verdict | When I'd switch |
|---|---|---|
| **Row-group-pruned extract into our bucket** (chosen) | 214.5 MB read per release, permanent copy, schema checked once | - |
| Athena over Overture in place (`CREATE EXTERNAL TABLE` on the release) | Great for exploration; I used DuckDB the same way to find the problem. Each query reads the footers of every file, and the table breaks when the release is deleted | Ad-hoc national analysis where a slice can't be named in advance |
| Overture's own Python CLI (`overturemaps download --bbox`) | Does the same pruning, but as a black box: no bytes-read accounting, no fingerprints, writes GeoJSON by default | A prototype |
| Geofabrik Nepal OSM extract + osmium | The full OSM tag set (`recycling:paper=yes`, `opening_hours`), which Overture flattens. But no Meta/Microsoft places, no GERS ids, PBF parsing in Lambda, and the host was not reachable from the build environment | If the facility model needs OSM tags Overture drops |
| Overpass API | Live and precise, but rate-limited and shared; not something a scheduled job should hammer | Never for a pipeline; fine for a one-off check |

## Population

| Option | Verdict | When I'd switch |
|---|---|---|
| **Census totals + HRSL pattern** (chosen) | Each source does what it's good at | - |
| HRSL alone | Puts 1.67 million people in KMC (census: 845,767) | Never for totals |
| WorldPop 100 m | Similar dasymetric method, coarser, not on AWS Open Data in a form we could read | If HRSL is withdrawn |
| Overture buildings (1.3 million footprints in the box, 165 MB) | Would let us build our own dasymetric model and separate residential from commercial floor area. I extracted them and dropped them: Overture has no building use for most of the valley, so it would just re-derive HRSL | When building `class` coverage improves |
| Full NSO ward-level census tables | The right answer for all 18 municipalities. Not reachable from the build environment as data; added to the seed by hand as they're verified | As soon as the six missing figures are sourced |

## Transform engine

| Option | Verdict | When I'd switch |
|---|---|---|
| **pyarrow + shapely + DuckDB SQL in Lambda** (chosen) | Silver for a release in ~6 s; same code in tests, on a laptop and in AWS | - |
| DuckDB spatial extension | Would replace shapely, but downloads at runtime from extensions.duckdb.org, which is one more thing to break in Lambda and was blocked in the build environment. Could be baked into the image | If spatial SQL grows past a few joins |
| AWS Glue (Spark) + Apache Sedona | The right tool for all of South Asia. For 200 MB, a 1-minute minimum billing and ~30 s start-up are longer than the job | National or regional scale, or > 10 GB of input |
| Glue Python shell | Same code as Lambda, no 15-minute limit, slower start | If silver ever passes 15 minutes |
| Redshift Serverless / RDS PostGIS | A database is the right home for a city's waste operations system, with trucks and routes updated daily. For monthly batch output it's an idle bill (~$12+/month for the smallest PostGIS instance) | If KMC wanted live truck tracking |

## Routing

| Option | Verdict | When I'd switch |
|---|---|---|
| **networkx single-source Dijkstra on Overture segments** (chosen) | One shortest-path tree for 76,700 nodes in under a second; we see and fix the graph | - |
| Amazon Location Service route matrix | Managed, includes truck profiles. Priced per route; 111,000 origins is a lot of routes; its road data for peri-urban Nepal can't be inspected | Real dispatch with turn restrictions, truck height/weight limits |
| OSRM / Valhalla on EC2 or Fargate | Proper speeds and turn costs on OSM. An always-on service for a monthly batch job | If haul time, not distance, becomes the product |

## Orchestration

| Option | Verdict | When I'd switch |
|---|---|---|
| **Step Functions + EventBridge Scheduler** (chosen) | Per-step retries, a Map state for the six themes, a failure branch; a few cents a month | - |
| S3 event on a new Overture prefix | Can't subscribe to events on a bucket we don't own | - |
| MWAA (managed Airflow) | ~$358/month for the smallest environment, for a job that runs monthly | A team already running Airflow |
| A single Lambda that does everything | Simple, but one failure re-runs the whole release, and silver + six extracts brush against the 15-minute limit from a slow network | A first prototype |

## Table format and catalog

| Option | Verdict | When I'd switch |
|---|---|---|
| **Plain Parquet, one partition per release, partition projection (injected)** (chosen) | A release is immutable, so there are no updates to manage | - |
| Apache Iceberg (via Athena or Glue) | Time travel and row-level updates. We already have time travel: every release is its own partition | If facilities were edited in place by users (a crowdsourced correction app) |
| Glue crawlers | Cost per run and infer schema from whatever file they find first | Never for a schema we own |

## Data quality

| Option | Verdict | When I'd switch |
|---|---|---|
| **Issues raised in code + a gate with block/warn severities** (chosen) | Each check sits next to the logic it protects and carries a human sentence | - |
| Glue Data Quality (DQDL) | Good for column-level rules on tables; most of ours are cross-source (census vs HRSL, release vs release) | If the team standardised on it |
| Great Expectations / Soda | Same, plus a dashboard | Several pipelines sharing rules |
| dbt tests | Natural if gold moved to dbt | If gold grows past ~10 models |

## Serving

| Option | Verdict | When I'd switch |
|---|---|---|
| **Athena + a CLI report + SNS for operators** (chosen) | Fits the users: analysts, a newsroom, a ward office asking one question during a blockade | - |
| QuickSight dashboard | ~$3-24/user/month; a static map does the same job | If a municipality wanted self-serve |
| A public API (API Gateway + Lambda over gold) | Cheap, but then there's a public endpoint to secure and keep up | If an app (e.g. a kabadi-finder) wanted live access |
| GeoJSON / PMTiles on S3 + CloudFront for a map | The natural next step for the drop-off map | When there's a front end |
