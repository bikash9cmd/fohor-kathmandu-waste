# What breaks, and what happens

Each row says what the pipeline does and which test proves it. "Last good" means `gold/_current.json` keeps pointing at the previous release, so readers see last month's numbers, not broken ones.

| What breaks | What happens | Severity | Test |
|---|---|---|---|
| **Overture re-keys features** (it did: every OSM-derived waste point in `2026-09-23.1`) | Facilities are matched by upstream record id; `facility_changes` reports `rekeyed`, not 50 closures and 50 openings | none | `test_rekeyed_release_reports_rekeys_not_churn`, `test_facility_key_survives_rekeying` |
| **The landfill's id changes** (it did, between `.0` and `.1`) | Falls back to `landuse=landfill` named "Banchare Danda Landfill" and warns | warn | `test_landfill_rekey_falls_back_to_name_with_warning` |
| **A local government's id disappears** | Name fallback within the right district; if that's ambiguous or empty, block | block | `test_missing_local_gov_blocks` |
| **Source names are wrong** (Mahalaxmi carries Lalitpur Metro's Nepali name) | We never join on names; it's reported as a warning on every run until fixed upstream | warn | `test_local_govs_pinned_by_id_and_bad_source_name_is_flagged` |
| **A theme is missing or renamed** | Ingest raises `ThemeMissing` naming the path; the Map state fails; SNS | fail | `test_missing_theme_fails_loudly` |
| **The bbox matches nothing** (coordinates swapped, Overture re-partitions) | Ingest refuses to write an empty theme | fail | covered by the same code path |
| **Row groups without statistics** | Treated as "may overlap" and read; correct, just slower | none | `test_row_group_without_statistics_is_read_not_skipped` |
| **Waste facilities collapse** (a conflation change drops most OSM points) | More than a 30% drop in active facilities blocks the release | block | `test_facility_collapse_blocks_and_keeps_last_good` |
| **No waste facilities at all** | Blocks in silver | block | same |
| **The road graph splits** (an edit disconnects the landfill road) | Snapping uses the largest component only; if the gate is >500 m from it, block; if >2% of people can't reach a road, warn | block / warn | `test_landfill_snaps_past_the_unconnected_service_road` |
| **Haul distances come out absurd** | Any local government outside 5-80 km blocks | block | gold checks |
| **Tonnage isn't conserved** (a join drops a municipality) | Tonnes must sum to 1,400 ± 1 | block | `test_end_to_end_publishes` |
| **The census pieces disagree** (Kathmandu's municipalities sum 2.7% under the district) | Warn every run; use the municipal figures | warn | `test_population_uses_census_and_shares_the_residual` |
| **HRSL and census disagree by >1.5x for a municipality** | Warn (KMC, Dakshinkali, Shankharapur today) | warn | same |
| **The HRSL file is gone** | Ingest raises; nothing downstream runs | fail | `test_hrsl_missing_is_an_error` |
| **Same release run twice** | Bronze reused by fingerprint, silver/gold skipped by input signature: `"status": "unchanged"` | none | `test_rerun_with_same_inputs_does_nothing`, `test_ingest_is_idempotent_and_patch_release_reuses_unchanged_themes` |
| **A patch release with identical files** | Every unchanged theme is reused; only changed themes are read | none | same |
| **Six ingests write state at once** | Each writes its own manifest entry; none are lost | none | `test_parallel_theme_ingest_does_not_lose_manifest_entries` |
| **A Lambda times out or S3 throttles** | Step Functions retries with backoff and jitter; the step is idempotent | none | state machine definition |
| **The schedule stops, or Overture stops publishing, or changes its layout so we list nothing new** | `ReleaseAgeDays` > 60 alarms, and a missing metric counts as breaching, so a dead sensor alarms too | alarm | template |
| **A scheduled run is dropped** | It goes to the scheduler DLQ, which alarms | alarm | template |
| **Someone edits an override's OSM node** | Overrides match the record id without its `@version`, so they keep matching; an override that matches nothing warns | warn | `test_facility_rules` |
| **A bad quality rule blocks a good release** | Gold stays on last good; the report in `quality/` names the check; fix the rule and `make rebuild RELEASE=…` (no upstream reads) | - | - |

## Recovery

- **Rebuild a release without touching upstream:** `python -m fohor rebuild --release 2026-09-23.1` (or invoke the Silver then Gold Lambda with `{"release": …, "run_id": "manual"}`).
- **Roll back what readers see:** write the previous release into `gold/_current.json` (versioned bucket, so the old object is also there).
- **Rebuild a release Overture has deleted:** bronze still has it; the manifest entries say which fingerprints.
