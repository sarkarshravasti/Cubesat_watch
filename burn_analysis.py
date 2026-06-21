"""
burn_analysis.py — Burn Scar Estimation & GSD-Based Area Calculation
=====================================================================
Converts fire detection pixel counts and sensor parameters into real-world
burned area estimates (hectares), burn severity ratings, and ecosystem
recovery time projections.

Methodology:
  1. Use GSD (Ground Sampling Distance) to determine pixel footprint area
  2. Use fire brightness temperature to classify Burn Severity Index (BSI)
  3. Project recovery time based on NDVI baseline and BSI
  4. Calculate cumulative mission-wide burn scar statistics
"""

import numpy as np
import pandas as pd
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Burn severity thresholds (Brightness Temperature in Kelvin) ───────────────
BSI_THRESHOLDS = {
    "Low":      (310, 350),    # Smoldering / surface burn
    "Moderate": (350, 400),    # Surface + understory burn
    "High":     (400, 450),    # Crown fire initiation
    "Extreme":  (450, 600),    # Crown fire / high-intensity burn
}

# ── Recovery time estimates (years) by severity × biome ──────────────────────
RECOVERY_TABLE = {
    "Low":      {"forest": 2,  "shrub": 1,  "grassland": 0.5},
    "Moderate": {"forest": 8,  "shrub": 4,  "grassland": 1.5},
    "High":     {"forest": 20, "shrub": 10, "grassland": 4.0},
    "Extreme":  {"forest": 50, "shrub": 25, "grassland": 8.0},
}


def classify_burn_severity(brightness_K: float) -> str:
    """Map brightness temperature to Burn Severity Index class."""
    for label, (lo, hi) in BSI_THRESHOLDS.items():
        if lo <= brightness_K < hi:
            return label
    return "Extreme" if brightness_K >= 450 else "Low"


def estimate_burn_area(fires_df: pd.DataFrame, gsd_m: float) -> dict:
    """
    Compute total burned area and breakdown metrics from visible fire detections.

    Parameters
    ----------
    fires_df : DataFrame of fires in current FOV (from orbit_engine)
    gsd_m    : Ground Sampling Distance in metres per pixel

    Returns
    -------
    dict with keys:
        total_hectares       : float
        severity_breakdown   : dict  — count per BSI level
        fires_processed      : int
        avg_brightness_K     : float
        peak_brightness_K    : float
        dominant_severity    : str
        recovery_years       : float  — biome-weighted mean recovery
        co2_est_tonnes       : float  — simplified carbon emission estimate
        timestamp            : str
    """
    if fires_df.empty:
        return _empty_burn_result()

    pixel_area_m2      = gsd_m ** 2
    pixel_area_hectares = pixel_area_m2 / 10_000.0  # 1 ha = 10,000 m²

    total_ha    = 0.0
    sev_counts  = {"Low": 0, "Moderate": 0, "High": 0, "Extreme": 0}
    recovery_yr = []
    co2_total   = 0.0

    for _, fire in fires_df.iterrows():
        bright = float(fire.get("brightness_K", 380))
        scan   = float(fire.get("scan_km",  1.0))
        track  = float(fire.get("track_km", 1.0))

        severity = classify_burn_severity(bright)
        sev_counts[severity] += 1

        # Pixel count from scan × track dimensions (converted to pixels)
        pixels_across = max(1, int(scan  * 1000 / gsd_m))
        pixels_along  = max(1, int(track * 1000 / gsd_m))
        fire_ha = pixels_across * pixels_along * pixel_area_hectares

        # Scale by confidence (less confident = smaller effective area claim)
        conf  = fire.get("confidence_pct", 70) / 100.0
        fire_ha *= conf
        total_ha += fire_ha

        # Biome inference: simple lat-based proxy
        lat   = float(fire.get("latitude", 0))
        biome = "forest" if abs(lat) < 60 else "shrub" if abs(lat) < 70 else "grassland"
        recovery_yr.append(RECOVERY_TABLE[severity][biome])

        # CO₂ estimate: combustion factor × biomass density (t C / ha)
        # Simplified: ~100 t CO₂-eq per ha for high-severity forest fire
        biomass_factor = {"Low": 20, "Moderate": 60, "High": 120, "Extreme": 200}
        co2_total += fire_ha * biomass_factor[severity]

    dominant = max(sev_counts, key=sev_counts.get)
    mean_rec = float(np.mean(recovery_yr)) if recovery_yr else 0.0
    brightnesses = fires_df["brightness_K"].dropna()

    result = {
        "total_hectares":    round(total_ha,  2),
        "severity_breakdown": sev_counts,
        "fires_processed":   len(fires_df),
        "avg_brightness_K":  round(float(brightnesses.mean()) if not brightnesses.empty else 0, 1),
        "peak_brightness_K": round(float(brightnesses.max())  if not brightnesses.empty else 0, 1),
        "dominant_severity": dominant,
        "recovery_years":    round(mean_rec, 1),
        "co2_est_tonnes":    round(co2_total, 1),
        "gsd_m":             round(gsd_m, 2),
        "pixel_area_m2":     round(pixel_area_m2, 1),
        "timestamp":         datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"[BURN] {len(fires_df)} fires | {total_ha:.1f} ha | "
                f"Dominant: {dominant} | CO₂≈{co2_total:.0f}t | "
                f"Recovery: {mean_rec:.1f}yr")
    return result


def _empty_burn_result() -> dict:
    return {
        "total_hectares": 0.0, "severity_breakdown": {"Low":0,"Moderate":0,"High":0,"Extreme":0},
        "fires_processed": 0, "avg_brightness_K": 0.0, "peak_brightness_K": 0.0,
        "dominant_severity": "None", "recovery_years": 0.0, "co2_est_tonnes": 0.0,
        "gsd_m": 0.0, "pixel_area_m2": 0.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def burn_summary_line(burn: dict) -> str:
    """Human-readable one-liner for dashboard / log output."""
    return (
        f"{burn['fires_processed']} fires | "
        f"{burn['total_hectares']:,.1f} ha burned | "
        f"Severity: {burn['dominant_severity']} | "
        f"CO₂≈{burn['co2_est_tonnes']:,.0f}t | "
        f"Recovery: {burn['recovery_years']}yr"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")
    test_df = pd.DataFrame([
        {"brightness_K": 430, "confidence_pct": 88, "scan_km": 1.2, "track_km": 1.2, "latitude": -6.0},
        {"brightness_K": 365, "confidence_pct": 72, "scan_km": 1.0, "track_km": 1.0, "latitude": 37.5},
        {"brightness_K": 480, "confidence_pct": 95, "scan_km": 1.5, "track_km": 1.5, "latitude": 60.0},
    ])
    result = estimate_burn_area(test_df, gsd_m=30.0)
    print(f"\n🔥 Burn Analysis:")
    print(f"   {burn_summary_line(result)}")
    print(f"   Pixel area: {result['pixel_area_m2']} m²")
    print(f"   Severity breakdown: {result['severity_breakdown']}")
