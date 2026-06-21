"""
orbit_engine.py — Satellite Orbital Propagator & Field-of-View Engine
======================================================================
Uses the Skyfield library with a hardcoded TLE to propagate a simulated
sun-synchronous LEO CubeSat (WILDFIRE_WATCH_1).

Data: CelesTrak TLE format (public domain, no registration required)
Library: skyfield (BSD license, no API keys)

Key outputs:
  - Subsatellite latitude / longitude at current UTC time
  - Orbital altitude (km)
  - Velocity (km/s)
  - FOV bounding box (degrees lat/lon) based on swath width
  - List of FIRMS fire detections visible inside current FOV
"""

import numpy as np
import pandas as pd
import logging
from datetime import datetime, timezone
from skyfield.api import EarthSatellite, load, wgs84

logger = logging.getLogger(__name__)

# ── Simulated TLE for WILDFIRE_WATCH_1 (sun-sync, 550 km SSO) ────────────────
# Based on a generic Landsat-8-like sun-synchronous orbit architecture.
# TLE generated for educational use; epoch is in 2024 for recency.
SAT_NAME = "WILDFIRE_WATCH_1"
TLE_LINE1 = "1 99001U 24001A   24200.50000000  .00000000  00000-0  00000-0 0  9991"
TLE_LINE2 = "2 99001  97.4000  45.0000 0001000  90.0000 270.0000 15.19000000 00001"

# ── Physical sensor parameters ────────────────────────────────────────────────
SWATH_WIDTH_KM       = 185.0    # Like Landsat-8 OLI (km)
SENSOR_PIXEL_SIZE_M  = 30.0     # Ground Sampling Distance (m/pixel)
FOCAL_LENGTH_MM      = 174.0    # Sensor focal length (mm)
SENSOR_WIDTH_MM      = 185.0    # Physical sensor width (mm)
EARTH_RADIUS_KM      = 6371.0   # Mean Earth radius (km)


class OrbitEngine:
    """
    Tracks the WILDFIRE_WATCH_1 satellite and filters fire detections
    within the sensor's current field of view.
    """

    def __init__(self):
        self.ts   = load.timescale()
        self.sat  = EarthSatellite(TLE_LINE1, TLE_LINE2, SAT_NAME, self.ts)
        logger.info(f"[ORBIT] Loaded satellite: {SAT_NAME}")

    # ──────────────────────────────────────────────────────────────────────────
    def get_position(self) -> dict:
        """
        Compute the current subsatellite point and orbital state vector.

        Returns
        -------
        dict with keys:
            lat_deg, lon_deg, alt_km, velocity_kms,
            period_min, inclination_deg, timestamp_utc
        """
        t   = self.ts.now()
        geo = self.sat.at(t)
        sub = wgs84.subpoint(geo)

        lat  = sub.latitude.degrees
        lon  = sub.longitude.degrees
        alt  = sub.elevation.km

        # Velocity magnitude from Cartesian velocity vector (km/s)
        pos_km   = geo.position.km
        vel_kms  = np.linalg.norm(geo.velocity.km_per_s)

        # Orbital period from altitude
        mu          = 398600.4418          # Earth's gravitational param (km³/s²)
        a           = EARTH_RADIUS_KM + alt
        period_min  = 2 * np.pi * np.sqrt(a**3 / mu) / 60.0

        result = {
            "lat_deg":       round(lat, 4),
            "lon_deg":       round(lon, 4),
            "alt_km":        round(alt, 2),
            "velocity_kms":  round(vel_kms, 3),
            "period_min":    round(period_min, 2),
            "inclination_deg": 97.4,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        logger.debug(f"[ORBIT] Position → lat={lat:.3f}° lon={lon:.3f}° alt={alt:.1f}km")
        return result

    # ──────────────────────────────────────────────────────────────────────────
    def get_fov_bounds(self, pos: dict | None = None) -> dict:
        """
        Compute the sensor's ground footprint as a lat/lon bounding box.

        The FOV is approximated as a rectangle derived from the swath width
        and the number of along-track pixels acquired per step.

        Returns
        -------
        dict: lat_min, lat_max, lon_min, lon_max, width_km, height_km
        """
        if pos is None:
            pos = self.get_position()

        lat  = pos["lat_deg"]
        lon  = pos["lon_deg"]
        alt  = pos["alt_km"]

        # Angular half-width of swath (degrees)
        half_swath_km = SWATH_WIDTH_KM / 2.0
        # 1 degree of latitude ≈ 111.32 km
        half_lat_deg   = half_swath_km / 111.32
        # 1 degree of longitude ≈ 111.32 * cos(lat) km
        cos_lat        = np.cos(np.radians(lat))
        half_lon_deg   = half_swath_km / (111.32 * (cos_lat if cos_lat > 0.01 else 0.01))

        # Along-track extent (same width for square-ish footprint in one sim step)
        along_km   = SWATH_WIDTH_KM
        along_deg  = along_km / 111.32

        return {
            "lat_min":   round(lat - half_lat_deg,  4),
            "lat_max":   round(lat + along_deg,      4),
            "lon_min":   round(lon - half_lon_deg,   4),
            "lon_max":   round(lon + half_lon_deg,   4),
            "width_km":  SWATH_WIDTH_KM,
            "height_km": along_km,
            "center_lat": lat,
            "center_lon": lon,
        }

    # ──────────────────────────────────────────────────────────────────────────
    def filter_fires_in_fov(self, firms_df: pd.DataFrame, fov: dict | None = None) -> pd.DataFrame:
        """
        Filter a FIRMS DataFrame to only fires visible within the current FOV.

        Parameters
        ----------
        firms_df : DataFrame from firms_api.fetch_firms_data()
        fov      : Optional precomputed FOV dict; computed fresh if None

        Returns
        -------
        DataFrame of fires inside the bounding box, may be empty.
        """
        if fov is None:
            fov = self.get_fov_bounds()

        if firms_df.empty:
            return firms_df

        mask = (
            (firms_df["latitude"]  >= fov["lat_min"]) &
            (firms_df["latitude"]  <= fov["lat_max"]) &
            (firms_df["longitude"] >= fov["lon_min"]) &
            (firms_df["longitude"] <= fov["lon_max"])
        )
        visible = firms_df[mask].copy()
        logger.info(f"[ORBIT] FOV contains {len(visible)} / {len(firms_df)} fires.")
        return visible.reset_index(drop=True)

    # ──────────────────────────────────────────────────────────────────────────
    def compute_gsd(self, alt_km: float | None = None) -> float:
        """
        Ground Sampling Distance (m/pixel) at a given orbital altitude.
        GSD = (pixel_size_m / focal_length_m) * altitude_m
        """
        if alt_km is None:
            pos    = self.get_position()
            alt_km = pos["alt_km"]

        gsd = (SENSOR_PIXEL_SIZE_M / (FOCAL_LENGTH_MM / 1000.0)) * alt_km * 1000.0 / 1000.0
        return round(gsd, 2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")
    engine = OrbitEngine()
    pos    = engine.get_position()
    fov    = engine.get_fov_bounds(pos)
    gsd    = engine.compute_gsd(pos["alt_km"])

    print(f"\n🛰️  WILDFIRE_WATCH_1 — Current State")
    print(f"   Lat/Lon:  {pos['lat_deg']}° / {pos['lon_deg']}°")
    print(f"   Altitude: {pos['alt_km']} km")
    print(f"   Velocity: {pos['velocity_kms']} km/s")
    print(f"   Period:   {pos['period_min']} min")
    print(f"\n📐 Field of View")
    print(f"   Lat range: {fov['lat_min']}° → {fov['lat_max']}°")
    print(f"   Lon range: {fov['lon_min']}° → {fov['lon_max']}°")
    print(f"   Swath:     {fov['width_km']} km × {fov['height_km']} km")
    print(f"\n🔭 GSD: {gsd} m/pixel")
