"""
firms_api.py — NASA FIRMS Wildfire Data Ingestion
==================================================
Fetches real-time wildfire hotspot data from NASA FIRMS open-data CSV endpoints.
No API key required — uses publicly accessible 24-hour global CSVs.

Data source: https://firms.modaps.eosdis.nasa.gov/active_fire/
Sensors supported: MODIS (Terra/Aqua), VIIRS SNPP, VIIRS NOAA-20
"""

import requests
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timezone
from io import StringIO

logger = logging.getLogger(__name__)

# ── Public CSV endpoints (no API key required) ────────────────────────────────
FIRMS_ENDPOINTS = {
    "MODIS_NRT": "https://firms.modaps.eosdis.nasa.gov/active_fire/modis-c6.1/csv/MODIS_C6_1_Global_24h.csv",
    "VIIRS_SNPP": "https://firms.modaps.eosdis.nasa.gov/active_fire/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Global_24h.csv",
    "VIIRS_NOAA20": "https://firms.modaps.eosdis.nasa.gov/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Global_24h.csv",
}

# Column name maps for each sensor type
MODIS_COLS = {
    "latitude": "latitude", "longitude": "longitude",
    "brightness": "brightness", "confidence": "confidence", "scan": "scan", "track": "track"
}
VIIRS_COLS = {
    "latitude": "latitude", "longitude": "longitude",
    "brightness": "bright_ti4", "confidence": "confidence", "scan": "scan", "track": "track"
}


def _normalize(df: pd.DataFrame, col_map: dict, sensor: str) -> pd.DataFrame:
    """Normalize raw FIRMS columns to a standard schema."""
    out = pd.DataFrame()
    out["latitude"]     = pd.to_numeric(df[col_map["latitude"]],  errors="coerce")
    out["longitude"]    = pd.to_numeric(df[col_map["longitude"]], errors="coerce")
    out["brightness_K"] = pd.to_numeric(df[col_map["brightness"]], errors="coerce")
    out["scan_km"]      = pd.to_numeric(df.get(col_map["scan"], pd.Series(dtype=float)), errors="coerce")
    out["track_km"]     = pd.to_numeric(df.get(col_map["track"], pd.Series(dtype=float)), errors="coerce")
    # Confidence: MODIS gives 0-100 int, VIIRS gives "nominal/high/low"
    raw_conf = df[col_map["confidence"]].astype(str).str.lower()
    out["confidence_pct"] = raw_conf.map(
        lambda v: 90 if v == "high" else (50 if v == "nominal" else 20 if v == "low" else _safe_int(v))
    )
    out["sensor"] = sensor
    out["acq_datetime"] = pd.Timestamp.now(tz="UTC")
    return out.dropna(subset=["latitude", "longitude"])


def _safe_int(v: str) -> int:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 50  # default nominal


def fetch_firms_data(sensor: str = "MODIS_NRT", timeout: int = 15) -> pd.DataFrame:
    """
    Download the latest 24-hour global hotspot CSV from NASA FIRMS.

    Parameters
    ----------
    sensor  : One of 'MODIS_NRT', 'VIIRS_SNPP', 'VIIRS_NOAA20'
    timeout : HTTP timeout in seconds

    Returns
    -------
    pd.DataFrame with columns: latitude, longitude, brightness_K,
                                confidence_pct, sensor, acq_datetime
    """
    url = FIRMS_ENDPOINTS.get(sensor, FIRMS_ENDPOINTS["MODIS_NRT"])
    col_map = MODIS_COLS if "MODIS" in sensor else VIIRS_COLS

    logger.info(f"[FIRMS] Fetching {sensor} data from: {url}")
    try:
        resp = requests.get(url, timeout=timeout,
                            headers={"User-Agent": "CubeSat-WildfireDigitalTwin/1.0"})
        resp.raise_for_status()
        df_raw = pd.read_csv(StringIO(resp.text))
        logger.info(f"[FIRMS] Downloaded {len(df_raw):,} hotspot records.")
        return _normalize(df_raw, col_map, sensor)

    except requests.exceptions.Timeout:
        logger.warning("[FIRMS] Request timed out — generating synthetic fallback data.")
    except requests.exceptions.RequestException as exc:
        logger.warning(f"[FIRMS] Network error: {exc} — using synthetic fallback.")
    except Exception as exc:
        logger.warning(f"[FIRMS] Parse error: {exc} — using synthetic fallback.")

    return _generate_synthetic_fires()


def _generate_synthetic_fires(n: int = 120) -> pd.DataFrame:
    """
    Generate realistic synthetic wildfire hotspot data for offline / testing use.
    Clusters fires in known high-risk biomes: Amazon, Australia, California, Siberia, SE Asia.
    """
    rng = np.random.default_rng(seed=42)
    clusters = [
        (-6.0, -55.0, 25),    # Amazon Basin
        (-25.0, 133.0, 20),   # Central Australia
        (37.5, -120.0, 20),   # California
        (60.0, 110.0, 20),    # Siberia / Boreal
        (15.0, 100.0, 15),    # Southeast Asia
        (-15.0, 32.0, 10),    # Southern Africa
        (40.0, 28.0, 10),     # Mediterranean / Turkey
    ]
    rows = []
    for lat_c, lon_c, count in clusters:
        count = min(count, n)  # guard
        lats = rng.normal(lat_c, 2.5, count)
        lons = rng.normal(lon_c, 3.0, count)
        for lat, lon in zip(lats, lons):
            rows.append({
                "latitude":       float(np.clip(lat, -85, 85)),
                "longitude":      float(np.clip(lon, -180, 180)),
                "brightness_K":   float(rng.uniform(320, 500)),
                "confidence_pct": int(rng.integers(45, 100)),
                "scan_km":        float(rng.uniform(0.5, 2.0)),
                "track_km":       float(rng.uniform(0.5, 2.0)),
                "sensor":         "SYNTHETIC",
                "acq_datetime":   pd.Timestamp.now(tz="UTC"),
            })
    df = pd.DataFrame(rows)
    logger.info(f"[FIRMS] Synthetic fallback: generated {len(df)} hotspot records.")
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")
    df = fetch_firms_data("MODIS_NRT")
    print(f"\n✅ FIRMS Data — {len(df)} records\n")
    print(df.head(10).to_string(index=False))
