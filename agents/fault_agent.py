"""
agents/fault_agent.py — Fault Diagnosis Agent
==============================================
Uses heuristic reasoning over multi-variate telemetry patterns to identify
likely root causes of subsystem anomalies.

The agent applies a prioritized rule base that goes well beyond simple
threshold checks — it correlates multiple signals (e.g., low battery +
low solar + high temperature → eclipse with possible thermal runaway).

Output is a structured FaultReport with likely cause, confidence, and
recommended action.
"""

import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Literal

logger = logging.getLogger(__name__)

CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW")


@dataclass
class FaultHypothesis:
    code:        str
    description: str
    confidence:  Literal["HIGH", "MEDIUM", "LOW"]
    evidence:    list = field(default_factory=list)
    action:      str  = ""


@dataclass
class FaultReport:
    fault_detected:     bool
    primary_hypothesis: FaultHypothesis | None
    all_hypotheses:     list = field(default_factory=list)
    reasoning_chain:    list = field(default_factory=list)
    timestamp:          str  = ""


# ── Rule definitions ──────────────────────────────────────────────────────────
#  Each rule is: (name, test_fn, code, description, confidence, action)

def _rules(t: dict):
    """
    Evaluate all diagnostic rules against telemetry dict t.
    Returns list of matching FaultHypothesis objects.
    """
    hyps = []

    batt  = t.get("battery_v", 8.4)
    solar = t.get("solar_A",   2.0)
    temp  = t.get("temp_C",    25.0)
    gyro  = t.get("gyro_dps",  0.1)
    power = t.get("power_W",   5.0)

    # ── Rule 1: Eclipse ───────────────────────────────────────────────────────
    if solar < 0.3 and batt > 7.0:
        hyps.append(FaultHypothesis(
            code="ECLIPSE_NOMINAL",
            description="Satellite in eclipse — solar current expected near zero.",
            confidence="HIGH",
            evidence=[f"solar_A={solar}A < 0.3A", f"battery_v={batt}V (healthy)"],
            action="Monitor battery drain rate; nominal operations continue.",
        ))

    # ── Rule 2: Solar panel degradation ──────────────────────────────────────
    if solar < 0.5 and batt < 7.5 and temp < 40:
        hyps.append(FaultHypothesis(
            code="SOLAR_DEGRADATION",
            description="Solar panel efficiency loss — low current in daylight.",
            confidence="MEDIUM",
            evidence=[f"solar_A={solar}A (daylight expected ≥1.5A)", f"battery_v={batt}V (depleting)"],
            action="Run solar diagnostics. Consider entering safe mode to conserve power.",
        ))

    # ── Rule 3: Battery cell failure ─────────────────────────────────────────
    if batt < 6.9:
        hyps.append(FaultHypothesis(
            code="BATTERY_CELL_FAILURE",
            description="Critical battery voltage — possible cell failure or deep discharge.",
            confidence="HIGH",
            evidence=[f"battery_v={batt}V << 7.2V warning threshold"],
            action="⚠️ IMMEDIATE: Enter low-power safe mode. Reduce non-essential loads.",
        ))

    # ── Rule 4: Thermal runaway ───────────────────────────────────────────────
    if temp > 55 and power > 8:
        hyps.append(FaultHypothesis(
            code="THERMAL_RUNAWAY",
            description="Elevated temperature correlated with high power consumption.",
            confidence="HIGH",
            evidence=[f"temp_C={temp}°C > 55°C", f"power_W={power}W > 8W"],
            action="⚠️ Thermal emergency: shed payload loads immediately. Check battery heaters.",
        ))
    elif temp > 45:
        hyps.append(FaultHypothesis(
            code="THERMAL_ELEVATED",
            description="Temperature above warning threshold — monitor closely.",
            confidence="MEDIUM",
            evidence=[f"temp_C={temp}°C > 45°C warn threshold"],
            action="Increase telemetry cadence. Reduce duty cycle of high-power payloads.",
        ))

    # ── Rule 5: ADCS anomaly (gyro drift) ────────────────────────────────────
    if gyro > 1.5:
        confidence = "HIGH" if gyro > 2.5 else "MEDIUM"
        hyps.append(FaultHypothesis(
            code="ADCS_GYRO_DRIFT",
            description="Excessive gyroscope drift — attitude control system anomaly.",
            confidence=confidence,
            evidence=[f"gyro_dps={gyro:.3f}°/s > 1.5°/s nominal max"],
            action="Initiate ADCS reset sequence. Cross-check with magnetometer attitude.",
        ))

    # ── Rule 6: Eclipse + low battery + high temp = potential charging fault ──
    if solar < 0.3 and batt < 7.4 and temp > 40:
        hyps.append(FaultHypothesis(
            code="CHARGING_FAULT_DURING_ECLIPSE",
            description="Battery depleting faster than expected during eclipse with thermal stress.",
            confidence="MEDIUM",
            evidence=[
                f"solar_A={solar}A (eclipse)",
                f"battery_v={batt}V (low)",
                f"temp_C={temp}°C (elevated)",
            ],
            action="Reduce payload duty cycle. Schedule attitude maneuver to solar-facing on exit.",
        ))

    # ── Rule 7: Nominal — no faults found ────────────────────────────────────
    if not hyps:
        hyps.append(FaultHypothesis(
            code="ALL_NOMINAL",
            description="No anomalies detected across all monitored subsystems.",
            confidence="HIGH",
            evidence=["All parameters within nominal bounds"],
            action="Continue nominal operations.",
        ))

    return hyps


class FaultDiagnosisAgent:
    """
    Fault Diagnosis Agent — reasons over correlated multi-variate telemetry
    to identify and rank likely root causes of observed anomalies.
    """

    def __init__(self):
        self.name = "FaultDiagnosisAgent"
        logger.info(f"[{self.name}] Initialized with {len(_rules({}))} default rules.")

    def run(self, telemetry: dict) -> FaultReport:
        """
        Analyze telemetry and return a ranked FaultReport.

        Parameters
        ----------
        telemetry : dict of sensor readings (from HealthMonitoringAgent.telemetry)
        """
        hypotheses = _rules(telemetry)

        # Sort by confidence priority
        priority = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        hypotheses.sort(key=lambda h: priority.get(h.confidence, 3))

        primary = hypotheses[0] if hypotheses else None
        fault_detected = primary is not None and primary.code != "ALL_NOMINAL"

        # Build reasoning chain (for dashboard display)
        chain = []
        chain.append(f"Telemetry received: batt={telemetry.get('battery_v',0)}V | "
                     f"solar={telemetry.get('solar_A',0)}A | temp={telemetry.get('temp_C',0)}°C | "
                     f"gyro={telemetry.get('gyro_dps',0):.3f}°/s")
        chain.append(f"Rule base evaluated: {len(hypotheses)} hypothesis/es generated.")
        if primary:
            chain.append(f"Primary: [{primary.code}] — {primary.description}")
            chain.append(f"Confidence: {primary.confidence} | Evidence: {'; '.join(primary.evidence)}")
            chain.append(f"Recommended action: {primary.action}")

        report = FaultReport(
            fault_detected     = fault_detected,
            primary_hypothesis = primary,
            all_hypotheses     = [asdict(h) for h in hypotheses],
            reasoning_chain    = chain,
            timestamp          = datetime.now(timezone.utc).isoformat(),
        )
        logger.info(f"[{self.name}] FaultDetected={fault_detected} | "
                    f"Primary={primary.code if primary else 'N/A'}")
        return report

    def to_dict(self, report: FaultReport) -> dict:
        d = asdict(report)
        return d
