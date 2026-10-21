# Challenges and bugs

The real ones, in the order they bit. Each says what I saw, why it happened, the fix, and what guards it now.

## 1. Fifty recycling points "closed" and fifty "opened" overnight

**Saw:** After ingesting `2026-09-23.0` and then the patch `2026-09-23.1`, the first version of `facility_changes` listed 50 facilities removed and 50 added. Same names, same coordinates: Kauda Kawadi, the Recyclo kiosks in Balkumari, the public dustbins in Kirtipur.

**Why:** Every OSM-derived base feature in the valley got a new GERS id in the patch. The `.0` ids are odd: their bytes are almost all ASCII hex digits (`38303034-3233-3162-…`), as if a text id had been hex-encoded; `.1` has ordinary UUIDs. I keyed facility history on GERS id because that's what GERS ids are for.

**Fix:** A facility's identity is its upstream record, `osm:n2082987863` or `meta:1630814040547643`, with the `@version` suffix removed. The GERS id is kept as an attribute, and a changed one is reported as `rekeyed`.

**Guard:** `test_facility_key_survives_rekeying`, `test_rekeyed_release_reports_rekeys_not_churn`. The real run now reports 50 `rekeyed`, 0 added, 0 removed.

## 2. Mahalaxmi is called Lalitpur, Dudhauli is called Dhulikhel

**Saw:** Looking up the valley's municipalities by name, "ललितपुर महानगरपालिका" (Lalitpur Metropolitan City) matched two divisions. One is Mahalaxmi Municipality: its English name is right and its Nepali primary name is Lalitpur's. Nearby, the division whose Nepali name is दुधौली नगरपालिका (Dudhauli, which is in Sindhuli) has the English name "Dhulikhel". And तारकेश्वर गाउँपालिका (a rural municipality in Nuwakot) sits next to तारकेश्वर नगरपालिका (Tarakeshwar Municipality, Kathmandu).

**Why:** Names in open data are typed by people, merged from several sources, and Nepal has many homonyms.

**Fix:** The 18 local governments are pinned by GERS id in `config.py`, with our own Nepali and English names. The source name is only compared, after Unicode normalisation, and a mismatch is a warning. If an id disappears there is a name fallback inside the right district, which warns, or blocks if it's ambiguous.

**Guard:** `test_local_govs_pinned_by_id_and_bad_source_name_is_flagged`, `test_missing_local_gov_blocks`. The Mahalaxmi warning appears on every real run.

Along the way: Dakshinkali's source name contains a zero-width joiner (`दक्षि‍णकाली`). Without normalisation that would have been a false "name changed" warning on every run.

## 3. HRSL says Kathmandu has twice as many people as the census does

**Saw:** Summing HRSL cells inside KMC's polygon gives 1,673,756. The 2021 census says 845,767. Dakshinkali and Shankharapur are out by 1.6-1.9x too; Tarakeshwar and Kageshwori Manohara go the other way.

**Why:** HRSL spreads an older census over building footprints. The core's big commercial buildings look like dense housing. The national total is close (28.5 M vs 29.2 M), so it's an allocation error, not a scale error.

**Fix:** Totals from the census, the pattern inside each municipality from HRSL, point weights rescaled to the totals. Where we have no sourced municipal figure, the district's census residual is shared by HRSL weight, including with the rural municipalities outside the valley, so Lalitpur's residual doesn't all land on Godawari and Mahalaxmi.

**What it changed:** Tonnage allocated to KMC is 404 t/day on census population and 624 t/day on HRSL. KMC's own figures are 500-600. Both allocations are published, and the docs say why neither is the truth.

## 4. Momo shops and fireflies in the recycling registry

**Saw:** My first filter for waste places matched `junk`, `dump`, `waste` and `recycl` anywhere in the name or category. It returned "Dumpling Fast Food Restro", "DUmpling Mo:Mo", "Gym Junkies", and six businesses named Junkiri (जुनकिरी, firefly), including a lodge, a preschool and a trekking company.

It also showed the opposite problem: real recyclers in the wrong category. "Boudha Garbage Recycling" is filed as `tour_operator`, "Dasna Recycling Centre" as `mattress_manufacturing`, "Rikishi Compost" as `agricultural_service`.

**Fix:** Category first (`recycling_center`, `garbage_collection_service`). Then a word-boundary name pattern (`recycl…`, `kabad…`, `kawadi`, `scrap`, `compost`, `रिसाइक्लो`, `कबाडी`, …) for places in any category except lodging and restaurants, recorded with evidence `name (category was …)` so a reviewer can see why.

**Guard:** `test_facility_rules`.

## 5. OSM `recycling` tags on a sand works, a garage and a house

**Saw:** 26 OSM points are tagged `amenity=recycling` in the box. Three are not: "Salambu Devi Baluwa Prasodhan Udyog" (*baluwa prasodhan* is sand processing), "Shree Balkhu Ganesh Recondition House" (a vehicle workshop) and "shrestha nibas" (*nibas* means residence).

**Fix:** `seeds/facility_overrides.csv`: a reviewed, versioned list of exclusions and reclassifications, each with a reason, keyed on the OSM record id without its version so an upstream edit doesn't silently undo it. An override that matches nothing warns. The right long-term fix is to correct the tags in OSM, which then flows back through Overture.

## 6. Every truck route was "unreachable"

**Saw:** The first haul calculation snapped the landfill to its nearest road connector (83 m away) and returned no route for anyone.

**Why:** That connector is on a service road inside the landfill that the extract doesn't join to the public network; it's in a 2-node island. The road graph has 541 components; the main one holds 74,605 of 76,703 nodes.

**Fix:** Snap only to the largest connected component (the gate now snaps 220 m from the landfill centroid), warn if that component holds less than 90% of nodes, block if the gate is more than 500 m from it.

**Guard:** The test fixture has the same trap, an unconnected service road nearer the landfill than the grid: `test_landfill_snaps_past_the_unconnected_service_road`.

## 7. The first extract dropped the districts

**Saw:** My first extraction kept rows whose bbox was *inside* the valley box. It returned 2 district polygons instead of 3 and 482 division areas instead of 627.

**Why:** Kathmandu, Lalitpur and Nuwakot districts are bigger than the box. "Inside" drops anything that crosses the edge, which is exactly the large features you need for calibration.

**Fix:** Keep rows whose bbox *overlaps* the box, then clip later. Row-group pruning uses the same overlap test.

## 8. A patch release that changed nothing (for one theme)

**Saw:** `2026-09-23.1` appeared two days after `.0`. Its `places` files have the same names, sizes and ETags as `.0`'s. Its `base` files are different (and carry the re-keyed ids from #1).

**Fix:** Bronze is keyed by a fingerprint of (file name, ETag) per theme, not by release name, so the patch cost two theme extractions instead of six.

**Guard:** `test_ingest_is_idempotent_and_patch_release_reuses_unchanged_themes`.

## 9. 55 seconds to read 63 MB

**Saw:** The road-segment theme is 128 files. Reading each footer sequentially, then its overlapping row groups, took 55 s from outside AWS.

**Fix:** Plan and read files on a 16-thread pool. Same bytes, 7.6 s. In Lambda in us-west-2 the latency per GET is lower still.

## 10. Six parallel writers, one manifest

**Saw (in design, before it happened):** The ingest originally kept one `bronze/_manifest.json` that each run read, updated and wrote back. Fine for a CLI; once the state machine ran the six themes in a Map state, six Lambdas would read the same old manifest and the last writer would win, and silver would then fail with "themes not ingested".

**Fix:** One small JSON per (release, theme); `load_manifest` lists the prefix. No shared state, nothing to lock.

**Guard:** `test_parallel_theme_ingest_does_not_lose_manifest_entries` (against mocked S3).

## 11. The census doesn't add up

**Saw:** Kathmandu district's 11 municipal 2021 figures sum to 1,987,138; the district total is 2,041,587 (2.7% more). Bhaktapur's 2021 total is 432,132 in one table and 430,408 in another.

**Fix:** Don't pick silently. The seed file records both and where each came from; the pipeline uses municipal figures where they exist and warns on every run that the two published figures disagree.

## 12. 9,801 tonnes

**Saw:** The 7-day valley backlog said 9,801 t, from 1,400 t/day.

**Why:** The valley row summed the per-municipality tonnages, each already rounded to 0.1 t.

**Fix:** The valley row uses the reported intake directly; per-municipality rows are rounded only for display. `test_end_to_end_publishes` checks 9,800 t and 1,400 truckloads exactly.

## Smaller ones

- HRSL's `.csv` files are tab-separated.
- DuckDB's spatial extension downloads at runtime, which failed in the build environment and is fragile in Lambda; point-in-polygon and distances use shapely and a KD-tree instead.
- `pandas.DataFrame.itertuples` renames a column called `class` (a Python keyword), so infrastructure classes are read by position with a comment.
