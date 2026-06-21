"""
agents/anomaly_agent.py — Anomaly Investigation Agent
======================================================
Post-hoc investigation agent that analyzes telemetry history to identify
likely causes of communication outages or unexpected system states.

When communication is lost, this agent:
  1. Searches the telemetry history for pre-anomaly signatures
  2. Correlates power, temperature, and attitude data
  3. Proposes ranked hypotheses with supporting evidence
  4. Suggests recovery procedures

Notable scenarios handled:
  - Communication blackout (antenna pointing loss, ADCS failure)
  - Unexpected reboot / watchdog reset
  - Power brownout during high-activity period
  - Thermal-induced hardware fault
"""

import logging
import statistics
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class AnomalyHypothesis:
    code:        str
    cause:       str
    confidence:  Literal["HIGH", "MEDIUM", "LOW"]
    evidence:    list = field(default_factory=list)
    recovery:    str  = ""


@dataclass
class AnomalyReport:
    event_type:     str
    severity:       Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    hypotheses:     list = field(default_factory=list)
    timeline:       list = field(default_factory=list)
    primary_cause:  str  = ""
    recovery_plan:  str  = ""
    timestamp:      str  = ""


class AnomalyInvestigationAgent:
    """
    Anomaly Investigation Agent — retrospective analysis of telemetry history
    to diagnose communication loss and other anomalous system behaviors.
    """

    def __init__(self):
        self.name = "AnomalyInvestigationAgent"
        self._telemetry_history: list[dict] = []
        logger.info(f"[{self.name}] Initialized.")

    def record_telemetry(self, telem: dict):
        """Add a telemetry snapshot to the rolling history (last 50 samples)."""
        self._telemetry_history.append(telem)
        if len(self._telemetry_history) > 50:
            self._telemetry_history.pop(0)

    def investigate_comm_loss(
        self,
        event_description: str = "Communication blackout detected",
        duration_min: float = 15.0,
    ) -> AnomalyReport:
        """
        Investigate a communication loss event using telemetry history.

        Parameters
        ----------
        event_description : Human-readable description of the anomaly
        duration_min      : Duration of the communication outage (minutes)
        """
        history = self._telemetry_history
        hypotheses = []
        timeline   = []

        # ── Analyze pre-event telemetry ───────────────────────────────────────
        if history:
            batts  = [t.get("battery_v", 8.0) for t in history]
            temps  = [t.get("temp_C",    25.0) for t in history]
            gyros  = [t.get("gyro_dps",  0.1)  for t in history]
            solars = [t.get("solar_A",   2.0)  for t in history]

            mean_batt  = statistics.mean(batts)
            mean_temp  = statistics.mean(temps)
            mean_gyro  = statistics.mean(gyros)
            trend_batt = batts[-1] - batts[0] if len(batts) > 1 else 0.0

            timeline.append(f"T-{len(history)} samples: Mean battery={mean_batt:.2f}V, "
                            f"Temp={mean_temp:.1f}°C")
            if trend_batt < -0.3:
                timeline.append(f"⚠️ Battery declining trend: {trend_batt:+.2f}V over history window")
            timeline.append(f"Pre-anomaly gyro mean: {mean_gyro:.4f}°/s")
        else:
            batts  = [8.0]; temps = [25.0]; gyros = [0.1]; solars = [2.0]
            mean_batt = 8.0; mean_temp = 25.0; mean_gyro = 0.1; trend_batt = 0.0
            timeline.append("No prior telemetry history available for correlation.")

        # ── Hypothesis generation ─────────────────────────────────────────────

        # H1: Antenna pointing loss (ADCS failure)
        if mean_gyro > 0.8 or (history and gyros[-1] > 1.5):
            hypotheses.append(AnomalyHypothesis(
                code="ADCS_POINTING_LOSS",
                cause="Attitude control failure caused antenna to lose ground station lock.",
                confidence="HIGH",
                evidence=[
                    f"Mean gyro rate: {mean_gyro:.3f}°/s (nominal < 0.3°/s)",
                    f"Pre-event gyro spike detected: {gyros[-1]:.3f}°/s" if history else "Gyro elevated",
                ],
                recovery=(
                    "1. Send ADCS reset command on next pass. "
                    "2. Use magnetorquers for detumbling if gyro unavailable. "
                    "3. Verify TLE and attitude quaternion after recovery."
                ),
            ))

        # H2: Power brownout / watchdog reset
        if mean_batt < 7.2 or trend_batt < -0.4:
            hypotheses.append(AnomalyHypothesis(
                code="POWER_BROWNOUT_RESET",
                cause="Low battery voltage triggered OBC watchdog reset, causing transceiver outage.",
                confidence="HIGH",
                evidence=[
                    f"Battery mean: {mean_batt:.2f}V (warning at 7.2V)",
                    f"Voltage trend: {trend_batt:+.2f}V (declining)" if trend_batt < 0 else "Low voltage",
                ],
                recovery=(
                    "1. Allow solar recharge through next eclipse exit. "
                    "2. Send Safe Mode command when link restored. "
                    "3. Reduce payload duty cycle to <30% until battery >8.0V."
                ),
            ))

        # H3: Thermal-induced transceiver shutdown
        if mean_temp > 50 and duration_min > 10:
            hypotheses.append(AnomalyHypothesis(
                code="THERMAL_TRANSCEIVER_FAULT",
                cause="Elevated temperature triggered thermal protection shutdown of UHF transceiver.",
                confidence="MEDIUM",
                evidence=[
                    f"Pre-anomaly mean temperature: {mean_temp:.1f}°C (thermal limit ~60°C)",
                    f"Outage persisted {duration_min:.0f} min (consistent with cooldown time)",
                ],
                recovery=(
                    "1. Orient panels edge-on to reduce solar heating. "
                    "2. Attempt contact after 1 full orbit to allow cooldown. "
                    "3. Schedule thermal diagnostic on restored comms."
                ),
            ))

        # H4: Eclipse shadow (benign explanation)
        if any(t.get("solar_A", 2.0) < 0.2 for t in history) and duration_min < 40:
            hypotheses.append(AnomalyHypothesis(
                code="ECLIPSE_NOMINAL",
                cause="Satellite was in Earth shadow — no anomaly, reduced ground station link.",
                confidence="MEDIUM",
                evidence=[
                    f"Solar current near zero in pre-event history",
                    f"Duration {duration_min:.0f} min consistent with eclipse segment (~35 min)"
                ],
                recovery="No recovery needed — monitor for next pass establishment.",
            ))

        # H5: Fallback — unknown
        if not hypotheses:
            hypotheses.append(AnomalyHypothesis(
                code="UNKNOWN_COMM_LOSS",
                cause="Insufficient telemetry to determine root cause definitively.",
                confidence="LOW",
                evidence=["No correlated anomaly signatures found in telemetry window"],
                recovery=(
                    "1. Attempt contact on next 3 passes at multiple frequencies. "
                    "2. Request emergency ranging from backup ground station. "
                    "3. If no contact after 24h, declare anomaly investigation board."
                ),
            ))

        primary = hypotheses[0]
        severity = "CRITICAL" if primary.confidence == "HIGH" else "HIGH"

        timeline.append(f"Anomaly: {event_description}")
        timeline.append(f"Duration: {duration_min:.0f} min")
        timeline.append(f"Primary diagnosis: {primary.code} — {primary.cause}")

        report = AnomalyReport(
            event_type    = event_description,
            severity      = severity,
            hypotheses    = [asdict(h) for h in hypotheses],
            timeline      = timeline,
            primary_cause = primary.cause,
            recovery_plan = primary.recovery,
            timestamp     = datetime.now(timezone.utc).isoformat(),
        )
        logger.info(f"[{self.name}] Event='{event_description}' | "
                    f"Primary={primary.code} | Hypotheses={len(hypotheses)}")
        return report

    def to_dict(self, report: AnomalyReport) -> dict:
        return asdict(report)
