"""
main.py — CubeSat Wildfire Digital Twin — Mission Integration Loop
==================================================================
Orchestrates all modules in a continuous simulation loop:

  1. Fetch NASA FIRMS wildfire hotspot data (or synthetic fallback)
  2. Propagate WILDFIRE_WATCH_1 orbital position via Skyfield
  3. Filter fires within the sensor FOV
  4. Run NDVI vegetation analysis
  5. Run burn scar / GSD estimation
  6. Trigger blockchain Oracle packets for high-confidence fires
  7. Run all 5 AI agents
  8. Render thermal map to disk (Agg backend — no GUI threads)
  9. Serialize state to outputs/state.json (dashboard reads this)
  10. Log to outputs/telemetry.log

Run: python main.py
Stop: Ctrl+C
Dashboard (separate terminal): python dashboard.py
"""

import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import asdict

# ── Non-interactive Matplotlib backend MUST be set before any other imports ───
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np

# ── Project modules ────────────────────────────────────────────────────────────
from firms_api      import fetch_firms_data
from orbit_engine   import OrbitEngine
from ndvi_analysis  import generate_ndvi_grid, ndvi_risk_summary
from burn_analysis  import estimate_burn_area, burn_summary_line
from oracle_trigger import build_oracle_packet, oracle_summary_line

from agents import (
    HealthMonitoringAgent,
    FaultDiagnosisAgent,
    MissionPlanningAgent,
    AnomalyInvestigationAgent,
    GroundStationAgent,
)

# ── Configuration ─────────────────────────────────────────────────────────────
LOOP_INTERVAL_SEC    = 30        # Seconds between simulation steps
FIRMS_SENSOR         = "MODIS_NRT"
LOG_DIR              = Path("outputs")
STATE_FILE           = LOG_DIR / "state.json"
THERMAL_MAP_FILE     = LOG_DIR / "thermal_map.png"
NDVI_MAP_FILE        = LOG_DIR / "ndvi_map.png"
TELEMETRY_LOG        = LOG_DIR / "telemetry.log"
MAX_ORACLE_HISTORY   = 20       # Keep last N oracle packets in state.json

# ── Imaging mission targets (used by Mission Planning Agent) ──────────────────
MISSION_TARGETS = [
    {"name": "Chennai",          "lat": 13.09, "lon": 80.27},
    {"name": "Amazon Basin",     "lat": -6.0,  "lon": -55.0},
    {"name": "California NF",    "lat": 38.5,  "lon": -120.8},
    {"name": "Siberian Taiga",   "lat": 61.0,  "lon": 107.0},
]


def setup_logging():
    """Configure dual-stream logging to console + telemetry.log."""
    LOG_DIR.mkdir(exist_ok=True)
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(TELEMETRY_LOG), encoding="utf-8"),
    ]
    logging.basicConfig(
        level   = logging.INFO,
        format  = "%(asctime)s  %(levelname)-8s  %(name)-25s  %(message)s",
        handlers = handlers,
    )


def render_thermal_map(fires_in_fov, fov: dict, orbit_pos: dict, cycle: int):
    """
    Render a publication-quality thermal map of visible fires within the FOV.
    Saved to disk using the Agg backend (no GUI, no threading conflicts).
    """
    fig, ax = plt.subplots(figsize=(10, 8), facecolor="#0d1117")
    ax.set_facecolor("#0d1117")

    # ── FOV background ────────────────────────────────────────────────────────
    lon_span = np.linspace(fov["lon_min"], fov["lon_max"], 200)
    lat_span = np.linspace(fov["lat_min"], fov["lat_max"], 200)
    lons, lats = np.meshgrid(lon_span, lat_span)

    # Synthetic thermal background
    thermal_bg = (
        np.random.default_rng(cycle).normal(0, 1, lons.shape) * 5 + 295
    )
    img = ax.pcolormesh(
        lons, lats, thermal_bg,
        cmap="inferno", alpha=0.4, shading="auto",
        vmin=280, vmax=400,
    )

    # ── Fire detections ───────────────────────────────────────────────────────
    if not fires_in_fov.empty:
        bright = fires_in_fov["brightness_K"].values
        conf   = fires_in_fov["confidence_pct"].values / 100.0
        sizes  = (bright - 300) * 0.8 + 30
        sizes  = np.clip(sizes, 20, 300)

        sc = ax.scatter(
            fires_in_fov["longitude"],
            fires_in_fov["latitude"],
            c=bright, cmap="plasma",
            vmin=320, vmax=500,
            s=sizes, alpha=conf, zorder=5,
            edgecolors="#ff6600", linewidths=0.8,
        )
        cb2 = plt.colorbar(sc, ax=ax, shrink=0.6, pad=0.01)
        cb2.set_label("Brightness Temp (K)", color="#aaaaaa", fontsize=9)
        cb2.ax.yaxis.set_tick_params(color="#aaaaaa")
        plt.setp(plt.getp(cb2.ax.axes, "yticklabels"), color="#aaaaaa")

    # ── Satellite ground track marker ─────────────────────────────────────────
    ax.plot(
        orbit_pos["lon_deg"], orbit_pos["lat_deg"],
        marker="^", color="#00ffff", markersize=14,
        markeredgecolor="white", markeredgewidth=1.5,
        zorder=10, label="WILDFIRE_WATCH_1",
    )

    # ── FOV bounding box ──────────────────────────────────────────────────────
    rect_lons = [fov["lon_min"], fov["lon_max"], fov["lon_max"], fov["lon_min"], fov["lon_min"]]
    rect_lats = [fov["lat_min"], fov["lat_min"], fov["lat_max"], fov["lat_max"], fov["lat_min"]]
    ax.plot(rect_lons, rect_lats, "--", color="#00ffff", linewidth=1.2, alpha=0.7, label="Sensor FOV")

    # ── Labels & cosmetics ────────────────────────────────────────────────────
    ax.set_xlabel("Longitude (°)", color="#aaaaaa")
    ax.set_ylabel("Latitude (°)",  color="#aaaaaa")
    title = (
        f"WILDFIRE_WATCH_1  |  Thermal Map  |  Cycle {cycle:03d}\n"
        f"Lat {orbit_pos['lat_deg']:.2f}° Lon {orbit_pos['lon_deg']:.2f}°  "
        f"Alt {orbit_pos['alt_km']:.0f}km  |  {fires_in_fov.shape[0]} fires detected"
    )
    ax.set_title(title, color="white", fontsize=10, pad=10)
    ax.tick_params(colors="#aaaaaa")
    for spine in ax.spines.values():
        spine.set_edgecolor("#333344")
    ax.legend(facecolor="#1a1a2e", edgecolor="#444", labelcolor="#cccccc", fontsize=8)

    plt.tight_layout()
    plt.savefig(str(THERMAL_MAP_FILE), dpi=120, bbox_inches="tight")
    plt.close(fig)


def render_ndvi_map(ndvi_data: dict, fov: dict, cycle: int):
    """Render synthetic NDVI grid map to disk."""
    fig, ax = plt.subplots(figsize=(8, 6), facecolor="#0d1117")
    ax.set_facecolor("#0d1117")

    grid = ndvi_data["grid"]
    lons = ndvi_data["lon_axis"]
    lats = ndvi_data["lat_axis"]
    L, Lo = np.meshgrid(lons, lats)

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "ndvi", ["#8B0000", "#D2691E", "#F5DEB3", "#90EE90", "#006400"], N=256
    )
    img = ax.pcolormesh(Lo, L, grid, cmap=cmap, vmin=-0.5, vmax=0.9, shading="auto")
    cb  = plt.colorbar(img, ax=ax, shrink=0.7)
    cb.set_label("NDVI", color="#aaaaaa")
    cb.ax.yaxis.set_tick_params(color="#aaaaaa")
    plt.setp(plt.getp(cb.ax.axes, "yticklabels"), color="#aaaaaa")

    ax.set_title(
        f"Synthetic NDVI — Cycle {cycle:03d} | FOV: {fov['center_lat']:.2f}°, {fov['center_lon']:.2f}° | "
        f"Risk: {ndvi_data['risk_class']}",
        color="white", fontsize=9
    )
    ax.tick_params(colors="#aaaaaa")
    for sp in ax.spines.values():
        sp.set_edgecolor("#333344")
    ax.set_xlabel("Longitude (°)", color="#aaaaaa")
    ax.set_ylabel("Latitude (°)",  color="#aaaaaa")

    plt.tight_layout()
    plt.savefig(str(NDVI_MAP_FILE), dpi=110, bbox_inches="tight")
    plt.close(fig)


def serialize_state(state: dict):
    """Write state dict to outputs/state.json (atomic-ish via write+rename)."""
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)
    tmp.replace(STATE_FILE)


def main():
    setup_logging()
    log = logging.getLogger("main")
    log.info("=" * 70)
    log.info("  🛰️  CubeSat Wildfire Digital Twin — Mission Start")
    log.info("=" * 70)

    # ── Initialize modules ────────────────────────────────────────────────────
    orbit   = OrbitEngine()
    health  = HealthMonitoringAgent()
    fault   = FaultDiagnosisAgent()
    mission = MissionPlanningAgent()
    anomaly = AnomalyInvestigationAgent()
    gs      = GroundStationAgent("CUBESAT-GS-BANGALORE")

    # ── Fetch FIRMS data once (refreshed every 30 min in real ops) ────────────
    log.info("[MAIN] Fetching NASA FIRMS global fire data …")
    firms_df = fetch_firms_data(FIRMS_SENSOR)
    log.info(f"[MAIN] FIRMS: {len(firms_df)} total hotspot records loaded.")

    oracle_history = []
    cycle = 0

    log.info(f"[MAIN] Starting mission loop (interval={LOOP_INTERVAL_SEC}s). Press Ctrl+C to stop.")
    log.info("[MAIN] Dashboard: run  python dashboard.py  in a separate terminal.")

    try:
        while True:
            cycle += 1
            log.info(f"\n{'─'*60}")
            log.info(f"  MISSION CYCLE {cycle:04d}  |  {datetime.now(timezone.utc).isoformat()}")
            log.info(f"{'─'*60}")

            # ── 1. Orbital position ───────────────────────────────────────────
            orbit_pos = orbit.get_position()
            fov       = orbit.get_fov_bounds(orbit_pos)
            gsd_m     = orbit.compute_gsd(orbit_pos["alt_km"])

            # ── 2. Refresh FIRMS every 30 cycles (~15 min at 30s intervals) ───
            if cycle % 30 == 1 and cycle > 1:
                log.info("[MAIN] Refreshing FIRMS data …")
                firms_df = fetch_firms_data(FIRMS_SENSOR)

            # ── 3. Filter visible fires ───────────────────────────────────────
            fires_in_fov = orbit.filter_fires_in_fov(firms_df, fov)

            # ── 4. NDVI analysis ──────────────────────────────────────────────
            ndvi_data = generate_ndvi_grid(fov, fires_in_fov)
            log.info(f"[MAIN] NDVI: {ndvi_risk_summary(ndvi_data)}")

            # ── 5. Burn analysis ──────────────────────────────────────────────
            burn_data = estimate_burn_area(fires_in_fov, gsd_m)
            log.info(f"[MAIN] BURN: {burn_summary_line(burn_data)}")

            # ── 6. Oracle trigger ─────────────────────────────────────────────
            oracle_packet = build_oracle_packet(
                fires_in_fov, orbit_pos, burn_data, ndvi_data, cycle
            )
            if oracle_packet:
                log.info(f"[MAIN] ⛓️  ORACLE: {oracle_summary_line(oracle_packet)}")
                oracle_history.append(oracle_packet)
                if len(oracle_history) > MAX_ORACLE_HISTORY:
                    oracle_history.pop(0)

            # ── 7. Health monitoring agent ────────────────────────────────────
            health_report = health.run()
            log.info(f"[MAIN] HEALTH: {health_report.overall} | {health_report.summary[:80]}")

            # ── 8. Fault diagnosis agent ──────────────────────────────────────
            fault_report  = fault.run(health_report.telemetry)
            if fault_report.fault_detected:
                primary = fault_report.primary_hypothesis
                if primary:
                    pcode = primary.code if hasattr(primary, 'code') else primary.get('code', '?')
                    pdesc = primary.description if hasattr(primary, 'description') else primary.get('description', '')
                    log.warning(f"[MAIN] FAULT: {pcode} — {str(pdesc)[:70]}")

            # ── 9. Record telemetry for anomaly agent ─────────────────────────
            anomaly.record_telemetry(health_report.telemetry)

            # ── 10. Mission planning (rotating target) ─────────────────────────
            target = MISSION_TARGETS[cycle % len(MISSION_TARGETS)]
            mp_result = mission.run(
                target_lat   = target["lat"],
                target_lon   = target["lon"],
                target_name  = target["name"],
                orbit_pos    = orbit_pos,
                health_report = health_report,
            )
            log.info(f"[MAIN] MISSION [{target['name']}]: Feasible={mp_result.feasible}")

            # ── 11. Ground station analysis ────────────────────────────────────
            import random
            el_deg       = random.uniform(5, 65)
            weather_fac  = random.uniform(0.0, 0.4)
            gs_report    = gs.analyze_pass(el_deg, weather_fac)
            log.info(f"[MAIN] GS: {gs_report.pass_summary[:80]}")

            # ── 12. Render plots ───────────────────────────────────────────────
            render_thermal_map(fires_in_fov, fov, orbit_pos, cycle)
            render_ndvi_map(ndvi_data, fov, cycle)

            # ── 13. Serialize state ────────────────────────────────────────────
            state = {
                "cycle":         cycle,
                "timestamp":     datetime.now(timezone.utc).isoformat(),
                "orbit":         orbit_pos,
                "fov":           fov,
                "gsd_m":         gsd_m,
                "firms_total":   len(firms_df),
                "fires_in_fov":  len(fires_in_fov),
                "ndvi":          {k: v for k, v in ndvi_data.items() if k != "grid"},
                "burn":          burn_data,
                "oracle_latest": oracle_packet,
                "oracle_history": oracle_history[-5:],
                "health":        health.to_dict(health_report),
                "fault":         fault.to_dict(fault_report),
                "mission_plan":  mission.to_dict(mp_result),
                "ground_station": gs.to_dict(gs_report),
                "thermal_map":   THERMAL_MAP_FILE.name,
                "ndvi_map":      NDVI_MAP_FILE.name,
            }
            serialize_state(state)
            log.info(f"[MAIN] State saved → {STATE_FILE}")

            # ── 14. Wait ──────────────────────────────────────────────────────
            log.info(f"[MAIN] Sleeping {LOOP_INTERVAL_SEC}s until next cycle …\n")
            time.sleep(LOOP_INTERVAL_SEC)

    except KeyboardInterrupt:
        log.info("\n[MAIN] Mission loop stopped by user (Ctrl+C). Goodbye! 🛰️")
    except Exception as exc:
        log.exception(f"[MAIN] Unhandled exception in mission loop: {exc}")
        raise


if __name__ == "__main__":
    main()
