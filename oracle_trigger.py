"""
oracle_trigger.py — Blockchain Oracle Payload Generator
========================================================
When a wildfire detection exceeds the confidence threshold, this module
constructs a structured Oracle Packet — a realistic JSON payload that simulates
what a real satellite-blockchain oracle system would transmit.

The Oracle Packet contains:
  - Geospatial coordinates and fire telemetry
  - Satellite state vector at time of detection
  - Burn analysis summary
  - Simulated smart contract execution and Ethereum-style TX hash

In a production system, this payload would be signed with a private key and
broadcast to a Chainlink External Adapter or similar oracle network.
"""

import hashlib
import json
import logging
import random
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────
CONFIDENCE_THRESHOLD_PCT = 70     # Minimum confidence to trigger oracle
BRIGHTNESS_THRESHOLD_K   = 340    # Minimum brightness temperature (K)
MIN_FIRES_TO_TRIGGER     = 1      # Minimum number of qualifying fires

# ── Simulated smart contract parameters ───────────────────────────────────────
CONTRACT_ADDRESS     = "0xDeadBeef4WildfireWatch1CubeSat000001"
ORACLE_OPERATOR_ADDR = "0xCubeSat99001OrbitWildfire2024NodeOp"
PAYOUT_ETH           = 0.05       # Mock ETH paid to data consumer on trigger
CHAIN_ID             = 80001      # Mumbai testnet (Polygon) — free testnet


def _make_tx_hash(payload: dict) -> str:
    """Generate a deterministic mock Ethereum transaction hash from payload content."""
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return "0x" + hashlib.sha256(raw).hexdigest()


def _select_qualifying_fires(fires_df, confidence_thresh: int, brightness_thresh: float):
    """Filter fires meeting the oracle trigger criteria."""
    if fires_df is None or fires_df.empty:
        return None, []
    qualifying = fires_df[
        (fires_df["confidence_pct"] >= confidence_thresh) &
        (fires_df["brightness_K"]   >= brightness_thresh)
    ]
    if qualifying.empty:
        return None, []
    # Primary fire = brightest qualifying detection
    primary = qualifying.loc[qualifying["brightness_K"].idxmax()]
    return primary, qualifying.to_dict("records")


def build_oracle_packet(
    fires_df,
    orbit_pos: dict,
    burn_data: dict,
    ndvi_data: dict,
    mission_cycle: int = 0,
) -> Optional[dict]:
    """
    Build a complete Oracle Packet if any fires meet the trigger criteria.

    Parameters
    ----------
    fires_df      : pd.DataFrame — fires from orbit_engine FOV filter
    orbit_pos     : dict — from OrbitEngine.get_position()
    burn_data     : dict — from burn_analysis.estimate_burn_area()
    ndvi_data     : dict — from ndvi_analysis.generate_ndvi_grid()
    mission_cycle : int  — current simulation cycle number

    Returns
    -------
    dict (oracle packet) if triggered, None otherwise.
    """
    primary, all_qualifying = _select_qualifying_fires(
        fires_df, CONFIDENCE_THRESHOLD_PCT, BRIGHTNESS_THRESHOLD_K
    )

    if primary is None:
        logger.info("[ORACLE] No qualifying fires — threshold not exceeded.")
        return None

    ts_utc = datetime.now(timezone.utc).isoformat()
    mock_simulated_latency_ms = random.randint(85, 340)   # Simulated comms delay

    # ── Core telemetry block ──────────────────────────────────────────────────
    telemetry = {
        "satellite_id":       "WILDFIRE_WATCH_1",
        "norad_id":           99001,
        "mission_cycle":      mission_cycle,
        "lat_deg":            orbit_pos["lat_deg"],
        "lon_deg":            orbit_pos["lon_deg"],
        "altitude_km":        orbit_pos["alt_km"],
        "velocity_kms":       orbit_pos["velocity_kms"],
        "orbital_period_min": orbit_pos["period_min"],
        "gsd_m":              burn_data.get("gsd_m", 30.0),
        "obs_timestamp_utc":  ts_utc,
    }

    # ── Primary fire event block ──────────────────────────────────────────────
    fire_event = {
        "lat_deg":             float(primary["latitude"]),
        "lon_deg":             float(primary["longitude"]),
        "brightness_K":        float(primary["brightness_K"]),
        "confidence_pct":      int(primary["confidence_pct"]),
        "sensor":              str(primary.get("sensor", "MODIS")),
        "total_qualifying":    len(all_qualifying),
        "total_area_ha":       burn_data["total_hectares"],
        "dominant_severity":   burn_data["dominant_severity"],
        "co2_est_tonnes":      burn_data["co2_est_tonnes"],
        "recovery_est_years":  burn_data["recovery_years"],
    }

    # ── Vegetation risk block ─────────────────────────────────────────────────
    vegetation = {
        "ndvi_mean":        ndvi_data["mean_ndvi"],
        "ndvi_min":         ndvi_data["min_ndvi"],
        "drought_index":    ndvi_data["drought_index"],
        "risk_class":       ndvi_data["risk_class"],
    }

    # ── Smart contract simulation ─────────────────────────────────────────────
    interim_payload = {**telemetry, **fire_event, **vegetation}
    tx_hash = _make_tx_hash(interim_payload)

    smart_contract = {
        "contract_address":   CONTRACT_ADDRESS,
        "oracle_operator":    ORACLE_OPERATOR_ADDR,
        "chain_id":           CHAIN_ID,
        "network":            "Polygon Mumbai Testnet",
        "payout_eth":         PAYOUT_ETH,
        "tx_hash":            tx_hash,
        "gas_estimated_gwei": random.randint(50, 200),
        "latency_ms":         mock_simulated_latency_ms,
        "status":             "CONFIRMED",
        "block_number":       random.randint(38_000_000, 42_000_000),
    }

    packet = {
        "oracle_version":   "1.0.0",
        "packet_id":        tx_hash[:18],
        "trigger_timestamp": ts_utc,
        "telemetry":        telemetry,
        "fire_event":       fire_event,
        "vegetation":       vegetation,
        "smart_contract":   smart_contract,
        "qualifying_fires": all_qualifying[:5],  # Cap at 5 for readability
    }

    logger.info(
        f"[ORACLE] 🔔 Triggered! Packet={packet['packet_id']} | "
        f"Primary fire @ ({fire_event['lat_deg']:.3f}°, {fire_event['lon_deg']:.3f}°) | "
        f"Brightness={fire_event['brightness_K']:.0f}K | "
        f"TX={smart_contract['tx_hash'][:14]}…"
    )
    return packet


def oracle_summary_line(packet: dict) -> str:
    """Human-readable one-liner for telemetry log / dashboard."""
    fe = packet["fire_event"]
    sc = packet["smart_contract"]
    return (
        f"Oracle#{packet['packet_id'][:8]} | "
        f"Fire@({fe['lat_deg']:.2f}°,{fe['lon_deg']:.2f}°) "
        f"Bright={fe['brightness_K']:.0f}K Conf={fe['confidence_pct']}% | "
        f"Area={fe['total_area_ha']:.1f}ha | "
        f"TX:{sc['tx_hash'][:12]}… [{sc['status']}]"
    )


if __name__ == "__main__":
    import pandas as pd
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")

    mock_fires = pd.DataFrame([
        {"latitude": 37.2, "longitude": -118.5, "brightness_K": 445, "confidence_pct": 88,
         "scan_km": 1.2, "track_km": 1.2, "sensor": "MODIS_NRT"},
    ])
    mock_orbit  = {"lat_deg": 38.0, "lon_deg": -119.0, "alt_km": 550.0,
                   "velocity_kms": 7.61, "period_min": 95.4}
    mock_burn   = {"total_hectares": 1250.0, "dominant_severity": "High",
                   "co2_est_tonnes": 150000.0, "recovery_years": 20.0, "gsd_m": 30.0}
    mock_ndvi   = {"mean_ndvi": 0.18, "min_ndvi": -0.34, "drought_index": 0.72,
                   "risk_class": "Critical"}

    packet = build_oracle_packet(mock_fires, mock_orbit, mock_burn, mock_ndvi, mission_cycle=1)
    if packet:
        print(f"\n⛓️  Oracle Packet Generated:")
        print(f"   {oracle_summary_line(packet)}")
        print(f"\n   Full JSON (truncated):")
        print(json.dumps({k: v for k, v in packet.items() if k != "qualifying_fires"},
                         indent=2, default=str))
