"""
agents/health_agent.py — CubeSat Health Monitoring Agent
=========================================================
Continuously evaluates subsystem telemetry against nominal operating limits.
Outputs structured health reports with status, confidence, and explanations.

Monitors:
  - Battery voltage (V)
  - Solar panel current (A)
  - Internal temperature (°C)
  - Power draw (W)
  - Gyroscope drift (°/s)
  - Magnetometer deviation (μT)
"""

import logging
import random
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Literal

logger = logging.getLogger(__name__)

# ── Nominal operating limits ──────────────────────────────────────────────────
LIMITS = {
    "battery_v":    {"min": 6.8, "warn": 7.2, "nominal": 8.4,  "max": 8.5},
    "solar_A":      {"min": 0.0, "warn": 0.5, "nominal": 2.5,  "max": 4.0},
    "temp_C":       {"min": -20, "warn": 40,  "nominal": 20,   "max": 65},
    "power_W":      {"min": 0.5, "warn": 0.5, "nominal": 5.0,  "max": 15.0},
    "gyro_dps":     {"min": 0.0, "warn": 1.5, "nominal": 0.1,  "max": 3.0},
    "mag_uT":       {"min": 20,  "warn": 45,  "nominal": 30,   "max": 65},
}


@dataclass
class SubsystemStatus:
    name:       str
    value:      float
    unit:       str
    status:     Literal["NOMINAL", "WARNING", "CRITICAL", "UNKNOWN"] = "UNKNOWN"
    message:    str = ""


@dataclass
class HealthReport:
    overall:      Literal["NOMINAL", "WARNING", "CRITICAL"]
    subsystems:   list = field(default_factory=list)
    anomalies:    list = field(default_factory=list)
    summary:      str  = ""
    telemetry:    dict = field(default_factory=dict)
    timestamp:    str  = ""


def _simulate_telemetry(prev: dict | None = None) -> dict:
    """
    Simulate realistic CubeSat telemetry readings.
    Introduces occasional anomalies for agent testing (10% chance).
    """
    rng = random.Random()
    is_eclipse     = rng.random() < 0.3   # 30% chance of being in eclipse
    has_fault      = rng.random() < 0.10  # 10% chance of a subsystem fault

    battery_v  = rng.uniform(7.8, 8.4) if not has_fault else rng.uniform(6.5, 7.1)
    solar_A    = rng.uniform(1.8, 2.8) if not is_eclipse else rng.uniform(0.0, 0.3)
    temp_C     = rng.uniform(15, 35)   if not has_fault else rng.uniform(45, 62)
    power_W    = rng.uniform(3.5, 6.5)
    gyro_dps   = rng.uniform(0.01, 0.3) if not has_fault else rng.uniform(1.8, 2.8)
    mag_uT     = rng.uniform(25, 42)

    return {
        "battery_v":  round(battery_v, 3),
        "solar_A":    round(solar_A,   3),
        "temp_C":     round(temp_C,    1),
        "power_W":    round(power_W,   2),
        "gyro_dps":   round(gyro_dps,  4),
        "mag_uT":     round(mag_uT,    1),
        "is_eclipse":  is_eclipse,
        "has_fault":   has_fault,
    }


def _evaluate_subsystem(name: str, value: float, unit: str) -> SubsystemStatus:
    lim = LIMITS.get(name, {})
    if not lim:
        return SubsystemStatus(name, value, unit, "UNKNOWN", "No limits defined")

    if value < lim["min"]:
        return SubsystemStatus(name, value, unit, "CRITICAL",
                               f"Value {value}{unit} BELOW minimum {lim['min']}{unit}")
    if value > lim["max"]:
        return SubsystemStatus(name, value, unit, "CRITICAL",
                               f"Value {value}{unit} ABOVE maximum {lim['max']}{unit}")
    if name == "battery_v" and value < lim["warn"]:
        return SubsystemStatus(name, value, unit, "WARNING",
                               f"Battery low: {value}V (warn threshold: {lim['warn']}V)")
    if name == "temp_C" and value > lim["warn"]:
        return SubsystemStatus(name, value, unit, "WARNING",
                               f"Thermal elevated: {value}°C (warn threshold: {lim['warn']}°C)")
    if name == "gyro_dps" and value > lim["warn"]:
        return SubsystemStatus(name, value, unit, "WARNING",
                               f"Gyro drift elevated: {value}°/s")
    return SubsystemStatus(name, value, unit, "NOMINAL",
                           f"Within limits ({lim['min']}–{lim['max']}{unit})")


class HealthMonitoringAgent:
    """
    Health Monitoring Agent — evaluates all subsystem vitals and generates
    a structured HealthReport with overall system status.
    """

    def __init__(self):
        self.name = "HealthMonitoringAgent"
        self._prev_telemetry: dict | None = None
        logger.info(f"[{self.name}] Initialized.")

    def run(self, telemetry: dict | None = None) -> HealthReport:
        """
        Evaluate current telemetry and return a HealthReport.

        Parameters
        ----------
        telemetry : Optional dict of raw sensor readings.
                    If None, simulated readings are generated.
        """
        telem = telemetry or _simulate_telemetry(self._prev_telemetry)
        self._prev_telemetry = telem

        checks = [
            ("battery_v",  telem["battery_v"], "V"),
            ("solar_A",    telem["solar_A"],   "A"),
            ("temp_C",     telem["temp_C"],    "°C"),
            ("power_W",    telem["power_W"],   "W"),
            ("gyro_dps",   telem["gyro_dps"],  "°/s"),
            ("mag_uT",     telem["mag_uT"],    "μT"),
        ]

        statuses  = [_evaluate_subsystem(n, v, u) for n, v, u in checks]
        anomalies = [s for s in statuses if s.status in ("WARNING", "CRITICAL")]

        # Overall status: worst single subsystem
        if any(s.status == "CRITICAL" for s in statuses):
            overall = "CRITICAL"
        elif any(s.status == "WARNING" for s in statuses):
            overall = "WARNING"
        else:
            overall = "NOMINAL"

        lines = []
        if overall == "NOMINAL":
            lines.append("✅ Battery healthy. Thermal conditions nominal.")
            lines.append("   All subsystems within operating limits.")
        else:
            for a in anomalies:
                icon = "🔴" if a.status == "CRITICAL" else "🟡"
                lines.append(f"{icon} {a.name}: {a.message}")

        if telem.get("is_eclipse"):
            lines.append("🌑 Satellite is in eclipse — solar current expected low.")

        summary = " | ".join(lines) if lines else "Status: NOMINAL"

        report = HealthReport(
            overall    = overall,
            subsystems = [asdict(s) for s in statuses],
            anomalies  = [asdict(a) for a in anomalies],
            summary    = summary,
            telemetry  = telem,
            timestamp  = datetime.now(timezone.utc).isoformat(),
        )
        logger.info(f"[{self.name}] Health={overall} | Anomalies={len(anomalies)}")
        return report

    def to_dict(self, report: HealthReport) -> dict:
        return asdict(report)
