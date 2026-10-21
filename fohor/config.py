"""Settings, pinned identifiers and the published figures the model leans on.

Every number that did not come out of a dataset is here, with where it came from,
so a reviewer can find and challenge it in one place.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

LAKE_ROOT = Path(os.environ.get("FOHOR_LAKE", "lake"))
SEEDS_DIR = Path(__file__).resolve().parent.parent / "seeds"

# Overture Maps on the AWS Open Data registry (anonymous reads, us-west-2).
OVERTURE_BUCKET = os.environ.get("FOHOR_OVERTURE_BUCKET", "overturemaps-us-west-2")
OVERTURE_REGION = "us-west-2"
RELEASE_PREFIX = "release/"

# Meta / CIESIN High Resolution Settlement Layer, 30 m population points (us-east-1).
HRSL_BUCKET = "dataforgood-fb-data"
HRSL_KEY = "csv/month=2019-06/country=NPL/type=total_population/NPL_total_population.csv.gz"
HRSL_REGION = "us-east-1"

# Kathmandu Valley plus the landfill on the Nuwakot/Dhading border.
# (xmin, ymin, xmax, ymax) in degrees. Anything that overlaps this box is extracted.
BBOX = (85.00, 27.45, 85.65, 27.95)


@dataclass(frozen=True)
class Theme:
    name: str
    path: str  # under release/<release>/
    columns: tuple[str, ...]


# Only the columns the pipeline reads. Column projection is half of the cost story:
# `sources`, `names.rules` and `addresses` are most of the bytes in places.
THEMES: dict[str, Theme] = {
    t.name: t
    for t in (
        Theme("place", "theme=places/type=place",
              ("id", "geometry", "bbox", "names", "taxonomy", "basic_category", "confidence",
               "operating_status", "sources")),
        Theme("infrastructure", "theme=base/type=infrastructure",
              ("id", "geometry", "bbox", "names", "subtype", "class", "sources")),
        Theme("land_use", "theme=base/type=land_use",
              ("id", "geometry", "bbox", "names", "subtype", "class")),
        Theme("division", "theme=divisions/type=division",
              ("id", "bbox", "names", "subtype", "local_type", "parent_division_id", "country")),
        Theme("division_area", "theme=divisions/type=division_area",
              ("id", "geometry", "bbox", "division_id", "subtype", "class", "is_land")),
        Theme("segment", "theme=transportation/type=segment",
              ("id", "geometry", "bbox", "subtype", "class", "connectors")),
    )
}


@dataclass(frozen=True)
class LocalGov:
    gers_id: str
    name_en: str
    name_ne: str
    district: str


# The 18 local governments of the Kathmandu Valley, pinned by Overture GERS id.
# Names are never used to join: in the 2026-09 release Mahalaxmi's Nepali name is
# "ललितपुर महानगरपालिका" (Lalitpur Metropolitan City's), see docs/CHALLENGES_AND_BUGS.md #2.
VALLEY_LOCAL_GOVS: tuple[LocalGov, ...] = (
    LocalGov("70636d8b-02fd-4cc8-860b-5d3aa254ee14", "Kathmandu Metropolitan City", "काठमाडौँ महानगरपालिका",
             "Kathmandu"),
    LocalGov("7fb383ed-c719-4ef2-9d7b-f0c73c9fb790", "Budhanilkantha", "बूढानीलकण्ठ नगरपालिका", "Kathmandu"),
    LocalGov("d6cb976d-8dc2-4761-9da5-17e5952a9c65", "Tarakeshwar", "तारकेश्वर नगरपालिका", "Kathmandu"),
    LocalGov("d6874532-7f6e-4ea3-a6c4-50d7ef4fdd8b", "Gokarneshwar", "गोकर्णेश्वर नगरपालिका", "Kathmandu"),
    LocalGov("d16a7f37-74e8-4dfa-8216-c0afcd3ac7a7", "Chandragiri", "चन्द्रागिरी नगरपालिका", "Kathmandu"),
    LocalGov("03e3de25-b735-41e9-88bd-f46e6bbb98b0", "Tokha", "टोखा नगरपालिका", "Kathmandu"),
    LocalGov("0100143e-2345-44db-9447-b089d5fe621e", "Kageshwori Manohara", "कागेश्वरी मनोहरा नगरपालिका", "Kathmandu"),
    LocalGov("61f1d2e9-5050-4311-9d36-bdf5d0c4554e", "Nagarjun", "नागार्जुन नगरपालिका", "Kathmandu"),
    LocalGov("4db15616-189d-416d-a2d3-abffd3160ac6", "Kirtipur", "कीर्तिपुर नगरपालिका", "Kathmandu"),
    LocalGov("95713179-021a-4381-bfcc-96b6508d3ac5", "Dakshinkali", "दक्षिणकाली नगरपालिका", "Kathmandu"),
    LocalGov("0d249953-b195-468e-92c0-c580e1f1ce72", "Shankharapur", "शङ्खरापुर नगरपालिका", "Kathmandu"),
    LocalGov("385b96f2-1032-4a2e-a18d-6876119ef5f7", "Lalitpur Metropolitan City", "ललितपुर महानगरपालिका", "Lalitpur"),
    LocalGov("b2aba803-bc64-4b9c-96c7-b3a764391676", "Mahalaxmi", "महालक्ष्मी नगरपालिका", "Lalitpur"),
    LocalGov("9d662df3-c5b5-48d0-a356-70fd776b8d8f", "Godawari", "गोदावरी नगरपालिका", "Lalitpur"),
    LocalGov("eb397ca5-5121-4bed-a6ee-a57f04d8b0bb", "Bhaktapur", "भक्तपुर नगरपालिका", "Bhaktapur"),
    LocalGov("1540b30f-f2c0-469e-9d50-b47cf118ab2f", "Madhyapur Thimi", "मध्यपुर थिमि नगरपालिका", "Bhaktapur"),
    LocalGov("0e985a8e-d55a-4f60-8bbc-62ea6ad2562f", "Changunarayan", "चाँगुनारायण नगरपालिका", "Bhaktapur"),
    LocalGov("217a311c-84f7-4171-9ab1-c2b646e54d22", "Suryabinayak", "सूर्यविनायक नगरपालिका", "Bhaktapur"),
)

# Overture's district (county) divisions, used to calibrate population.
DISTRICTS = {
    "Kathmandu": "0ab5a027-9e0d-4d88-83ac-373813660c6f",
    "Lalitpur": "1c499dc1-7c2d-42cf-9a67-4f1ba1bce6a3",
    "Bhaktapur": "2c9e0231-a3b2-43a8-8f41-c6dc04d65c2c",
}

# OpenStreetMap way w1087457069, via Overture base/land_use.
LANDFILL_GERS_ID = "40b751a5-dc9a-3c82-bc04-c36f8ddbd621"
LANDFILL_NAME = "Banchare Danda Landfill"

# --- Published figures (see docs/DATA.md for the full citations) -------------------
# OnlineKhabar English, 21 Aug 2026, "Bancharedanda was built to solve Kathmandu's
# waste problem. Four years later, it is becoming another Sisdol".
LANDFILL_TONNES_PER_DAY = 1400.0
LANDFILL_TRUCKS_PER_DAY = 200
LANDFILL_LOCAL_GOVS_SERVED = 21  # 18 valley LGs plus a few outside it (e.g. Panchkhal)
# ADB (2013), Solid Waste Management in Nepal: Current Status and Policy Recommendations.
ADB_MSW_KG_PER_CAPITA_DAY = 0.317
ADB_ORGANIC_SHARE = 0.66
# CBS Waste Management Baseline Survey 2020 (Kathmandu Post, 11 May 2021).
CBS_ORGANIC_SHARE = 0.54

# Scenario knobs for the blockade model. These are assumptions, not measurements.
FLEET_SURGE_FACTOR = 1.3  # after a blockade the fleet can move at most 130% of normal
TONNES_PER_TRUCK = LANDFILL_TONNES_PER_DAY / LANDFILL_TRUCKS_PER_DAY  # 7.0 t/trip

# Road classes a tipper truck can use.
TRUCK_ROAD_CLASSES = (
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "service", "living_street", "unknown",
)
TRUCK_AVG_KMH = 18.0  # valley traffic plus the climb over Nagarjun; assumption

ACCESS_RADII_M = (500, 1000, 2000)
