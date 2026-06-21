"""
ndvi_analysis.py — Synthetic NDVI Grid & Vegetation Risk Assessment
====================================================================
Simulates the CubeSat's onboard vegetation sensor by generating a synthetic
Normalized Difference Vegetation Index (NDVI) grid over the satellite's current
field of view.

NDVI ranges from -1.0 to 1.0:
  > 0.6  → Dense healthy forest
  0.4–0.6 → Moderate vegetation
  0.2–0.4 → Sparse / stressed vegetation
  0.0–0.2 → Bare soil / drought stress
  < 0.0  → Water / burn scar / rock

Fire proximity reduces NDVI values to simulate heat stress and canopy damage.
"""

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# ── Grid resolution ───────────────────────────────────────────────────────────
GRID_ROWS = 64
GRID_COLS = 64


def generate_ndvi_grid(fov: dict, fires_in_fov: pd.DataFrame) -> dict:
    """
    Generate a synthetic NDVI grid for the satellite's current FOV.

    Parameters
    ----------
    fov           : dict from OrbitEngine.get_fov_bounds()
    fires_in_fov  : DataFrame of fires currently visible (may be empty)

    Returns
    -------
    dict with keys:
        grid         : np.ndarray (GRID_ROWS x GRID_COLS) of NDVI values
        lat_axis     : np.ndarray of latitude coordinates per row
        lon_axis     : np.ndarray of longitude coordinates per column
        mean_ndvi    : float  — average NDVI across FOV
        min_ndvi     : float  — minimum NDVI (indicates burn scars)
        risk_class   : str    — 'Low' | 'Moderate' | 'High' | 'Critical'
        drought_index: float  — 0.0 (no stress) → 1.0 (extreme stress)
        timestamp    : str
    """
    lat_axis = np.linspace(fov["lat_min"], fov["lat_max"], GRID_ROWS)
    lon_axis = np.linspace(fov["lon_min"], fov["lon_max"], GRID_COLS)
    lons, lats = np.meshgrid(lon_axis, lat_axis)

    # ── Base NDVI: sinusoidal variation simulating biome gradients ────────────
    # Higher NDVI near equator (tropics), lower at extreme latitudes
    lat_factor = np.cos(np.radians(lats) * 1.8)
    lon_noise  = np.sin(np.radians(lons) * 3.7) * 0.08

    rng  = np.random.default_rng(seed=int(np.abs(fov["center_lat"]) * 1000) % 2**31)
    base = 0.45 * lat_factor + lon_noise + rng.normal(0, 0.05, (GRID_ROWS, GRID_COLS))
    grid = np.clip(base, -0.3, 0.9)

    # ── Fire proximity: burn down NDVI near detected fires ────────────────────
    if not fires_in_fov.empty:
        for _, fire in fires_in_fov.iterrows():
            fire_lat = fire["latitude"]
            fire_lon = fire["longitude"]

            # Distance of each grid cell from this fire (degrees → approx km)
            dist_deg = np.sqrt((lats - fire_lat)**2 + (lons - fire_lon)**2)
            dist_km  = dist_deg * 111.0

            # Gaussian burn-down kernel: radius depends on brightness
            bright_k   = float(fire.get("brightness_K", 380))
            fire_radius = np.interp(bright_k, [310, 400, 500], [5, 15, 40])  # km
            sigma_deg  = fire_radius / 111.0

            attenuation = np.exp(-0.5 * (dist_deg / sigma_deg) ** 2)
            # Max reduction from -0.15 (low temp) to -0.6 (intense fire)
            max_drop    = np.interp(bright_k, [310, 500], [0.15, 0.60])
            grid       -= max_drop * attenuation

    grid = np.clip(grid, -1.0, 1.0)

    mean_ndvi = float(np.mean(grid))
    min_ndvi  = float(np.min(grid))

    # ── Drought stress index (0=healthy, 1=extreme stress) ────────────────────
    drought_index = float(np.clip(1.0 - (mean_ndvi + 0.3) / 1.2, 0.0, 1.0))

    # ── Risk classification ───────────────────────────────────────────────────
    n_fires    = len(fires_in_fov)
    high_conf  = int(fires_in_fov["confidence_pct"].gt(70).sum()) if not fires_in_fov.empty else 0

    if   mean_ndvi < 0.1 or (n_fires >= 5 and high_conf >= 3):
        risk_class = "Critical"
    elif mean_ndvi < 0.25 or n_fires >= 3:
        risk_class = "High"
    elif mean_ndvi < 0.40 or n_fires >= 1:
        risk_class = "Moderate"
    else:
        risk_class = "Low"

    from datetime import datetime, timezone
    result = {
        "grid":          grid,
        "lat_axis":      lat_axis,
        "lon_axis":      lon_axis,
        "mean_ndvi":     round(mean_ndvi, 4),
        "min_ndvi":      round(min_ndvi,  4),
        "risk_class":    risk_class,
        "drought_index": round(drought_index, 4),
        "fire_count":    n_fires,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"[NDVI] Mean={mean_ndvi:.3f} | MinNDVI={min_ndvi:.3f} | "
                f"Risk={risk_class} | DroughtIdx={drought_index:.3f}")
    return result


def ndvi_risk_summary(ndvi_data: dict) -> str:
    """Human-readable one-liner for dashboard display."""
    return (
        f"NDVI={ndvi_data['mean_ndvi']:+.3f} | "
        f"Drought={ndvi_data['drought_index']:.0%} | "
        f"Risk: {ndvi_data['risk_class']} | "
        f"Fires visible: {ndvi_data['fire_count']}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")
    mock_fov = {"lat_min": 30.0, "lat_max": 32.0, "lon_min": -120.0, "lon_max": -118.0,
                "center_lat": 31.0, "center_lon": -119.0}
    mock_fires = pd.DataFrame([
        {"latitude": 30.8, "longitude": -119.2, "brightness_K": 420, "confidence_pct": 85},
        {"latitude": 31.5, "longitude": -118.6, "brightness_K": 360, "confidence_pct": 62},
    ])
    ndvi = generate_ndvi_grid(mock_fov, mock_fires)
    print(f"\n🌿 NDVI Summary: {ndvi_risk_summary(ndvi)}")
    print(f"   Grid shape: {ndvi['grid'].shape}")
