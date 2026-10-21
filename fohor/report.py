"""The blockade report: what N days without the landfill means, in English and Nepali.

Written for a ward office or a newsroom on day one of a blockade, when the question is
"how bad will this get, and where first?".
"""
from __future__ import annotations

import pandas as pd

from fohor import config

_NE_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")
VALLEY = "Kathmandu Valley (18 local governments)"


def ne(n: float | int) -> str:
    return f"{n:,.0f}".translate(_NE_DIGITS)


def blockade_report(backlog: pd.DataFrame, waste: pd.DataFrame, days: int, release: str, top: int = 5) -> str:
    if not 1 <= days <= int(backlog["days_blocked"].max()):
        raise ValueError(f"days must be between 1 and {int(backlog['days_blocked'].max())}")
    b = backlog[backlog["days_blocked"] == days]
    valley = b[b["name_en"] == VALLEY].iloc[0]
    rows = b[b["name_en"] != VALLEY].sort_values("backlog_tonnes", ascending=False).head(top)
    far = waste.sort_values("round_trip_hours", ascending=False).iloc[0]

    lines = [
        f"Fohor blockade report: Bancharedanda closed for {days} day{'s' if days != 1 else ''} (map data {release})",
        "",
        f"  {valley.backlog_tonnes:,.0f} t of waste uncollected across the valley, "
        f"about {valley.truckloads:,.0f} truckloads;",
        f"  {valley.organic_tonnes:,.0f} t of it food and other organic waste that starts to rot within days.",
        f"  Clearing it takes ~{valley.days_to_clear_after_reopening:.0f} days after the road opens if trucks can do "
        f"{config.FLEET_SURGE_FACTOR:.0%} of normal trips",
        f"  ({valley.days_to_clear_if_surge_150pct:.0f} days at 150%, "
        f"{valley.days_to_clear_if_surge_120pct:.0f} at 120%).",
        "",
        "  Largest piles:",
    ]
    for r in rows.itertuples():
        lines.append(f"    {r.name_en:<30} {r.backlog_tonnes:>7,.0f} t  {r.truckloads:>5,.0f} truckloads")
    lines += [
        f"  Longest haul once open: {far.name_en}, ~{far.haul_km_mean:.0f} km each way, "
        f"{far.round_trip_hours:.1f} h per round trip.",
        "",
        f"  फोहोर प्रतिवेदन: बन्चरेडाँडा {ne(days)} दिन बन्द हुँदा उपत्यकामा {ne(valley.backlog_tonnes)} टन फोहोर "
        f"(करिब {ne(valley.truckloads)} ट्रक) थुप्रिन्छ, जसमध्ये {ne(valley.organic_tonnes)} टन कुहिने फोहोर हो।",
        f"  बाटो खुलेपछि सफा गर्न करिब {ne(valley.days_to_clear_after_reopening)} दिन लाग्छ।",
        "",
        "  Basis: 1,400 t/day reaching the landfill (OnlineKhabar, Aug 2026), shared by 2021 census population;",
        "  7 t per truck; 54% organic (CBS 2020). An estimate for planning, not a measurement.",
    ]
    return "\n".join(lines)
