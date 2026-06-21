"""
agents/mission_agent.py — Mission Planning Agent
=================================================
Evaluates whether an imaging task over a target location is feasible given
the current power budget, memory availability, and upcoming orbital pass timing.

The agent reasons over:
  - Power budget (available vs. required for imaging session)
  - Onboard memory availability
  - Next orbital overpass timing over target (estimated)
  - Ground station visibility window

Example query:
  "Can we schedule imaging over Chennai tomorrow?"
  → Agent considers power, memory, orbit timing, downlink window
  → Returns feasibility recommendation with confidence level
"""

import logging
import math
import random
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Literal

logger = logging.getLogger(__name__)

# ── Satellite capability constants ────────────────────────────────────────────
BATTERY_CAPACITY_WH       = 40.0    # Watt-hours total battery capacity
IMAGING_POWER_W           = 8.0     # Power consumed during imaging (W)
IMAGING_DURATION_MIN      = 5.0     # Typical imaging pass duration (min)
IMAGING_ENERGY_WH         = IMAGING_POWER_W * (IMAGING_DURATION_MIN / 60.0)  # ~0.67 Wh
MEMORY_CAPACITY_GB        = 16.0    # Flash storage (GB)
IMAGE_SIZE_MB             = 320.0   # Per imaging session ~320 MB (multispectral)
ORBIT_PERIOD_MIN          = 95.4    # Approximate orbit period
EARTH_RADIUS_KM           = 6371.0
SAT_ALTITUDE_KM           = 550.0


@dataclass
class MissionFeasibility:
    target_lat:       float
    target_lon:       float
    target_name:      str
    feasible:         bool
    confidence:       Literal["HIGH", "MEDIUM", "LOW"]
    recommendation:   str
    constraints:      list = field(default_factory=list)
    next_pass_utc:    str = ""
    power_available_wh: float = 0.0
    memory_free_gb:   float = 0.0
    timestamp:        str = ""


def _estimate_next_pass(target_lat: float, target_lon: float,
                        orbit_pos: dict) -> datetime:
    """
    Simplified next-pass estimator.
    Approximates overpass time based on orbital period and angular separation.
    (A full SGP4 propagation is done in orbit_engine; this is quick planning.)
    """
    sat_lat = orbit_pos.get("lat_deg", 0.0)
    sat_lon = orbit_pos.get("lon_deg", 0.0)

    # Great-circle angular distance (degrees)
    dlat = math.radians(target_lat - sat_lat)
    dlon = math.radians(target_lon - sat_lon)
    a    = math.sin(dlat/2)**2 + math.cos(math.radians(sat_lat)) \
           * math.cos(math.radians(target_lat)) * math.sin(dlon/2)**2
    angle_deg = math.degrees(2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

    # Fraction of orbit until overpass
    frac_orbit = angle_deg / 360.0
    minutes_to_pass = frac_orbit * ORBIT_PERIOD_MIN

    # If target is at high latitude, the orbit may not reach it → add a full orbit
    if abs(target_lat) > 85:
        minutes_to_pass += ORBIT_PERIOD_MIN

    now = datetime.now(timezone.utc)
    return now + timedelta(minutes=minutes_to_pass)


class MissionPlanningAgent:
    """
    Mission Planning Agent — evaluates imaging task feasibility by reasoning
    over power budget, memory, orbital geometry, and ground station windows.
    """

    def __init__(self):
        self.name = "MissionPlanningAgent"
        logger.info(f"[{self.name}] Initialized.")

    def run(
        self,
        target_lat: float,
        target_lon: float,
        target_name: str,
        orbit_pos: dict,
        health_report,
        current_memory_used_gb: float | None = None,
    ) -> MissionFeasibility:
        """
        Evaluate imaging feasibility for a given target.

        Parameters
        ----------
        target_lat, target_lon : Geographic coordinates of imaging target
        target_name            : Human-readable name (e.g. "Chennai")
        orbit_pos              : from OrbitEngine.get_position()
        health_report          : HealthReport from HealthMonitoringAgent
        current_memory_used_gb : Optional; simulated if None
        """
        telem  = health_report.telemetry
        batt_v = telem.get("battery_v", 8.0)
        solar  = telem.get("solar_A",   2.0)

        # ── Power budget ──────────────────────────────────────────────────────
        # State of charge estimate (simplified linear model)
        soc_pct          = max(0.0, min(1.0, (batt_v - 6.8) / (8.4 - 6.8)))
        available_wh     = soc_pct * BATTERY_CAPACITY_WH
        solar_income_wh  = solar * (IMAGING_DURATION_MIN / 60.0)  # solar during pass
        net_energy_wh    = available_wh + solar_income_wh          # simplified
        power_feasible   = net_energy_wh > IMAGING_ENERGY_WH * 1.5  # 1.5× safety margin

        # ── Memory budget ─────────────────────────────────────────────────────
        if current_memory_used_gb is None:
            current_memory_used_gb = random.uniform(2.0, 12.0)
        free_gb          = MEMORY_CAPACITY_GB - current_memory_used_gb
        mem_feasible     = free_gb > (IMAGE_SIZE_MB / 1024.0)

        # ── Orbital geometry ──────────────────────────────────────────────────
        next_pass = _estimate_next_pass(target_lat, target_lon, orbit_pos)
        minutes_until = (next_pass - datetime.now(timezone.utc)).total_seconds() / 60.0
        orbit_feasible = minutes_until < (ORBIT_PERIOD_MIN * 2)  # accessible within 2 orbits

        # ── Ground station visibility (mock) ─────────────────────────────────
        # Simplified: assume downlink window available if next pass is < 100 min
        gs_feasible = minutes_until < 100.0

        # ── Constraint list ───────────────────────────────────────────────────
        constraints = []
        if not power_feasible:
            constraints.append(
                f"🔋 Insufficient power: {available_wh:.1f}Wh available, "
                f"{IMAGING_ENERGY_WH:.1f}Wh required (need 1.5× margin)."
            )
        if not mem_feasible:
            constraints.append(
                f"💾 Memory nearly full: {free_gb:.2f}GB free, "
                f"need {IMAGE_SIZE_MB/1024:.2f}GB per session."
            )
        if not orbit_feasible:
            constraints.append(
                f"🛰️ Next pass over {target_name} is in {minutes_until:.0f} min "
                f"(>{ORBIT_PERIOD_MIN*2:.0f} min threshold)."
            )

        feasible = power_feasible and mem_feasible and orbit_feasible

        # ── Confidence ────────────────────────────────────────────────────────
        n_ok = sum([power_feasible, mem_feasible, orbit_feasible, gs_feasible])
        confidence = "HIGH" if n_ok == 4 else "MEDIUM" if n_ok >= 2 else "LOW"

        # ── Recommendation ────────────────────────────────────────────────────
        if feasible:
            rec = (
                f"✅ Imaging over {target_name} is FEASIBLE. "
                f"Next pass in ≈{minutes_until:.0f} min "
                f"[{next_pass.strftime('%H:%M UTC')}]. "
                f"Power available: {available_wh:.1f}Wh. "
                f"Memory free: {free_gb:.2f}GB. "
                f"Recommend scheduling at next pass window."
            )
        else:
            rec = (
                f"⚠️ Imaging over {target_name} NOT recommended at this time. "
                + " | ".join(constraints)
            )
            if not power_feasible:
                rec += " Consider waiting for eclipse exit and battery recharge."
            if not mem_feasible:
                rec += " Downlink stored data first to free memory."

        result = MissionFeasibility(
            target_lat        = target_lat,
            target_lon        = target_lon,
            target_name       = target_name,
            feasible          = feasible,
            confidence        = confidence,
            recommendation    = rec,
            constraints       = constraints,
            next_pass_utc     = next_pass.isoformat(),
            power_available_wh = round(available_wh, 2),
            memory_free_gb    = round(free_gb, 3),
            timestamp         = datetime.now(timezone.utc).isoformat(),
        )
        logger.info(f"[{self.name}] Target={target_name} | Feasible={feasible} | "
                    f"Confidence={confidence} | NextPass≈{minutes_until:.0f}min")
        return result

    def to_dict(self, report: MissionFeasibility) -> dict:
        return asdict(report)
