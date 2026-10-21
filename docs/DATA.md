# Data: what goes in, what it can and can't tell you

Fohor joins four kinds of input. Two are big open datasets read straight from the AWS Open Data registry, one is a hand-checked seed of census figures, and the rest are a handful of published numbers about the landfill. Every published number lives in [`fohor/config.py`](../fohor/config.py) or [`seeds/`](../seeds/) so it can be challenged in one place.

## 1. Overture Maps Foundation (s3://overturemaps-us-west-2)

Monthly global releases in GeoParquet. Fohor reads six themes and keeps only what overlaps the box `85.00-85.65 E, 27.45-27.95 N` (the valley plus the landfill on the Nuwakot/Dhading border).

| Theme | What we use it for | Rows in the box | Read / total (2026-09-23.0) |
|---|---|---|---|
| `divisions/division` | names and parents of local governments and districts | 1,533 | 1.3 MB / 0.6 GB |
| `divisions/division_area` | their polygons | 627 | 108.8 MB / 4.5 GB |
| `base/infrastructure` | OSM waste points: `recycling`, `waste_basket`, `waste_disposal` | 15,739 | 7.1 MB / 12.9 GB |
| `base/land_use` | the landfill polygon (`landuse=landfill`) | 20,306 | 26.5 MB / 18.5 GB |
| `places/place` | businesses: recycling centres, garbage collection services | 46,891 | 8.2 MB / 10.9 GB |
| `transportation/segment` | the road graph for haul distances | 95,143 | 62.6 MB / 71.7 GB |
| **total** | | | **214.5 MB / 119.1 GB (0.18%)**, 31 of 30,432 row groups |

Licences: ODbL for OSM-derived features, CDLA Permissive 2.0 for places. Attribution is in the README.

Releases in the bucket during this work: `2026-09-23.0` and the patch `2026-09-23.1`. Overture keeps only recent releases, which is why bronze is permanent here.

## 2. HRSL population (s3://dataforgood-fb-data)

Meta and CIESIN's High Resolution Settlement Layer: estimated people per 30 m cell, made by spreading census totals over building footprints detected in satellite imagery. File: `csv/month=2019-06/country=NPL/type=total_population/` (14 MB gzip, 3.0 million cells for Nepal, 111,463 in the valley's local governments). Despite the `.csv` name it is tab-separated. Licence: CC BY 4.0.

**What it's good for:** where people live inside a municipality (dense core vs. empty hills).
**What it's bad at:** totals. It puts 1,673,756 people in Kathmandu Metropolitan City; the 2021 census counts 845,767. Its Nepal total (28.5 million) is close to the census (29.2 million), so the error is in *allocation*: dense commercial buildings in the core look like homes. Fohor uses HRSL for the spatial pattern only.

## 3. 2021 census (seeds/census_2021.csv)

National Population and Housing Census 2021, as tabulated on Wikipedia (links in the seed file). District totals for Kathmandu (2,041,587), Lalitpur (551,667) and Bhaktapur (432,132), and municipal figures for the 11 Kathmandu-district local governments and Lalitpur Metropolitan City.

Two things the seed file records honestly:

- **The Kathmandu municipal figures sum to 1,987,138, 2.7% short of the district total.** Both are labelled 2021 census. The pipeline warns on every run instead of silently picking one.
- **Bhaktapur's 2021 total is 432,132 in the census table and 430,408 in the district article.** The seed uses the census table and notes the other.

For the six local governments without a sourced municipal figure (Mahalaxmi, Godawari, and the four Bhaktapur municipalities), population is the district's census residual shared by HRSL weight, including the rural municipalities outside the valley list, so Lalitpur's residual isn't all pushed into Godawari and Mahalaxmi. The `population_source` column says which method each row used.

## 4. Published figures about the waste itself

| Figure | Value | Source |
|---|---|---|
| Waste reaching Bancharedanda | ~1,400 t/day, ~200 tipper trucks/day, from 21 local governments | OnlineKhabar English, 21 Aug 2026 |
| Landfill history | Opened 24 May 2022 with a 20-year design life; "overwhelmed in four years"; maybe 4 more years at current rates | same |
| Kathmandu Metropolitan City's own output | ~500 t/day (Himalayan Times, Feb 2020); ~600 t/day (Balen Shah, quoted in the article above) | |
| Average municipal waste per person | 0.317 kg/day (household 0.17), 66% organic | ADB 2013, *Solid Waste Management in Nepal: Current Status and Policy Recommendations*, 58 municipalities |
| Organic share | 54% organic, 33% inorganic (2019/20) | CBS Waste Management Baseline Survey 2020, via Kathmandu Post, 11 May 2021 |
| Recycled | 4.1% of waste on average | same |

### How tonnage is allocated, and why there are two answers

Fohor shares the reported 1,400 t/day among the 18 local governments by population. With census population, Kathmandu Metropolitan City gets **404 t/day**. With HRSL (building-based) population it gets **624 t/day**. KMC's own figures are 500-600 t/day. Neither allocation is right: the census counts residents, but the core's waste also comes from shops, offices and the daily commuters; HRSL over-weights big buildings. Gold publishes both (`tonnes_per_day`, `tonnes_per_day_building_share`) and the blockade report uses the census one, which is conservative for KMC.

The 1,400 t also includes 3 local governments outside the valley (e.g. Panchkhal) that the reporting names but does not quantify, so valley figures are a few percent high. The implied rate, 0.478 kg/person/day, is 1.5x ADB's 2013 average, which is plausible for the capital a decade later and because it includes commercial waste; the gate warns if that ratio leaves 0.5-2.0x.

## What the data can't tell you

- **Mapped is not existing.** OSM has 23 recycling points in the valley and Overture places adds 4 more; there are certainly hundreds of kabadi shops. The access tables measure the open map's knowledge, which matters for anyone building on it (an app that says "nearest drop-off" is only as good as this), and say so in their names.
- **Straight-line distance** to drop-offs, not walking distance. It is a lower bound.
- **Haul distance is from where people live**, not from the transfer stations where trucks actually load. It is right for comparing municipalities and for truck-km totals within ~20%; it is not a route plan.
- **The blockade model is arithmetic, not a measurement.** It assumes tonnage keeps arriving at the same rate, nobody burns or dumps waste in rivers meanwhile (they do: a 2022 CBS survey reported in OnlineKhabar found 31% of urban waste ends up in rivers), and the fleet can surge to 130% after reopening. The report prints 120% and 150% alongside.
