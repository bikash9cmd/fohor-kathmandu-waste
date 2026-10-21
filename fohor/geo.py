"""Small geometry helpers. Everything here is plain shapely and numpy, so it runs in Lambda
without the DuckDB spatial extension (which has to be downloaded at runtime)."""
from __future__ import annotations

import math

import numpy as np
import shapely

EARTH_R = 6_371_008.8
LAT0 = 27.7  # the valley; an equirectangular projection about it is good to ~0.1% over 50 km
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))


def to_metres(lon, lat):
    return np.asarray(lon) * M_PER_DEG_LON, np.asarray(lat) * M_PER_DEG_LAT


def project(geom: shapely.Geometry) -> shapely.Geometry:
    return shapely.transform(geom, lambda xy: np.column_stack(to_metres(xy[:, 0], xy[:, 1])))


def area_km2(geom: shapely.Geometry) -> float:
    return project(geom).area / 1e6


def haversine_m(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, (lon1, lat1, lon2, lat2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))


def line_length_m(line: shapely.LineString) -> float:
    xy = shapely.get_coordinates(line)
    if len(xy) < 2:
        return 0.0
    return float(haversine_m(xy[:-1, 0], xy[:-1, 1], xy[1:, 0], xy[1:, 1]).sum())


def from_wkb(values) -> np.ndarray:
    return shapely.from_wkb([bytes(v) if v is not None else None for v in values])
