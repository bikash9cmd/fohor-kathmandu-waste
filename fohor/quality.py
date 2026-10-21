"""The gate between a built release and what Athena and the report read.

Builders raise issues as they go (silver.py, analysis.py). This module adds checks on
the gold output and on the change from the last published release, then decides.
A blocking issue means gold/_current.json keeps pointing at the last good release.
"""
from __future__ import annotations

import pandas as pd

from fohor import config

MAX_FACILITY_DROP = 0.30


def _issue(check: str, severity: str, detail: str) -> dict:
    return {"check": check, "severity": severity, "detail": detail}


def gold_checks(gold: dict[str, pd.DataFrame], previous_gold: dict[str, pd.DataFrame] | None) -> list[dict]:
    issues = []
    mw = gold["municipality_waste"]
    expected = len(config.VALLEY_LOCAL_GOVS)
    if len(mw) != expected:
        issues.append(_issue("local_gov_count", "block", f"{len(mw)} local governments, expected {expected}"))
    if (mw["population"] <= 0).any():
        issues.append(_issue("population_positive", "block",
                             f"no population for {list(mw.loc[mw['population'] <= 0, 'name_en'])}"))
    total = mw["population"].sum()
    if not 2_500_000 <= total <= 3_500_000:
        issues.append(_issue("population_total", "block", f"valley population {total:,} is implausible"))
    missing_haul = mw[mw["haul_km_mean"].isna()]
    if len(missing_haul):
        issues.append(_issue("haul_present", "block", f"no route for {list(missing_haul['name_en'])}"))
    odd = mw[(mw["haul_km_mean"] < 5) | (mw["haul_km_mean"] > 80)]
    if len(odd):
        bad = dict(zip(odd["name_en"], odd["haul_km_mean"], strict=True))
        issues.append(_issue("haul_range", "block", f"haul outside 5-80 km: {bad}"))
    tpd = mw["tonnes_per_day"].sum()
    if abs(tpd - config.LANDFILL_TONNES_PER_DAY) > 1:
        issues.append(_issue("tonnage_conserved", "block",
                             f"tonnes sum to {tpd}, expected {config.LANDFILL_TONNES_PER_DAY}"))
    implied = float(mw["implied_kg_per_person_day"].iloc[0]) if len(mw) else 0.0
    ratio = implied / config.ADB_MSW_KG_PER_CAPITA_DAY
    if not 0.5 <= ratio <= 2.0:
        issues.append(_issue("kg_per_person", "warn",
                             f"implied {implied:.3f} kg/person/day is {ratio:.1f}x ADB's 0.317"))

    reg = gold["facility_registry"]
    active = int(reg["active"].sum())
    if active == 0:
        issues.append(_issue("facilities_active", "block", "no active facilities"))
    if previous_gold is not None and "facility_registry" in previous_gold:
        before = int(previous_gold["facility_registry"]["active"].sum())
        if before and (before - active) / before > MAX_FACILITY_DROP:
            issues.append(_issue("facility_drop", "block",
                                 f"active facilities fell from {before} to {active}; upstream conflation change?"))
    return issues


def decide(issues: list[dict]) -> dict:
    blocking = [i for i in issues if i["severity"] == "block"]
    return {"passed": not blocking, "blocking": blocking,
            "warnings": [i for i in issues if i["severity"] == "warn"]}
