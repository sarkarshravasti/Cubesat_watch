"""
agents/ground_station_agent.py — Ground Station Link Quality Agent
==================================================================
Analyzes RF link quality parameters during a satellite pass to explain
observed communication degradation (packet loss, SNR drops, Doppler shift).

Evaluates:
  - Elevation angle (degrees above horizon)
  - Signal-to-Noise Ratio (SNR, dB)
  - Doppler shift (kHz)
  - Free-space path loss (dB)
  - Atmospheric losses (tropospheric scintillation estimate)

Example query:
  "Why did packet loss increase during yesterday's pass?"
  → Agent correlates elevation, SNR, Doppler, and weather to explain.
"""

import math
import logging
import random
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Literal

logger = logging.getLogger(__name__)

# ── RF / Link constants ───────────────────────────────────────────────────────
FREQUENCY_MHZ     = 437.525     # UHF amateur band (MHz)
WAVELENGTH_M      = 3e8 / (FREQUENCY_MHZ * 1e6)
TX_POWER_DBM      = 30.0        # 1 W transmitter power (dBm)
TX_ANTENNA_DBI    = 2.15        # Dipole gain (dBi)
RX_ANTENNA_DBI    = 7.0         # Ground Yagi gain (dBi)
NOISE_FIGURE_DB   = 3.0         # Receiver noise figure (dB)
BANDWIDTH_HZ      = 9600        # Data rate bandwidth (Hz)
EARTH_RADIUS_KM   = 6371.0
SAT_ALTITUDE_KM   = 550.0


def _free_space_path_loss(slant_range_km: float) -> float:
    """FSPL in dB = 20·log10(4π·d·f/c)"""
    d_m = slant_range_km * 1000.0
    fspl = 20 * math.log10(4 * math.pi * d_m / WAVELENGTH_M)
    return round(fspl, 2)


def _slant_range(elevation_deg: float) -> float:
    """Satellite slant range (km) from ground elevation angle."""
    el_rad = math.radians(max(elevation_deg, 0.1))
    re     = EARTH_RADIUS_KM
    h      = SAT_ALTITUDE_KM
    # Law of cosines for spherical Earth
    range_km = math.sqrt((re + h)**2 - re**2 * math.cos(el_rad)**2) - re * math.sin(el_rad)
    return max(range_km, 1.0)


def _doppler_shift_khz(elevation_deg: float, velocity_kms: float = 7.61) -> float:
    """
    Peak Doppler shift at a given elevation angle.
    Doppler = f₀ * v/c * cos(elevation_angle_from_horizon_complement)
    """
    # Effective radial velocity component
    el_rad          = math.radians(elevation_deg)
    radial_factor   = math.cos(math.pi/2 - el_rad)   # sin(el)
    doppler_hz      = (FREQUENCY_MHZ * 1e6) * (velocity_kms * 1000 / 3e8) * radial_factor
    return round(doppler_hz / 1000.0, 3)  # kHz


def _thermal_noise_floor(bandwidth_hz: float) -> float:
    """Johnson-Nyquist thermal noise floor: kTB in dBm"""
    k_B    = 1.380649e-23   # Boltzmann constant (J/K)
    T_K    = 290            # Room temperature
    noise  = k_B * T_K * bandwidth_hz   # watts
    return round(10 * math.log10(noise * 1000), 2)  # dBm


@dataclass
class LinkBudget:
    elevation_deg:   float
    slant_range_km:  float
    fspl_db:         float
    doppler_khz:     float
    rx_snr_db:       float
    noise_floor_dbm: float
    link_margin_db:  float
    expected_ber:    float
    packet_loss_pct: float
    quality:         Literal["EXCELLENT", "GOOD", "MARGINAL", "POOR"]
    explanation:     str
    timestamp:       str = ""


@dataclass
class LinkReport:
    pass_summary:     str
    link_budget:      dict
    anomaly_found:    bool
    cause_analysis:   list = field(default_factory=list)
    recommendations:  list = field(default_factory=list)
    timestamp:        str  = ""


class GroundStationAgent:
    """
    Ground Station Agent — analyzes RF link quality and explains communication
    anomalies in terms of physical parameters (elevation, SNR, Doppler, FSPL).
    """

    def __init__(self, gs_name: str = "CUBESAT-GS-CHENNAI"):
        self.name    = "GroundStationAgent"
        self.gs_name = gs_name
        logger.info(f"[{self.name}] Ground station: {gs_name}")

    def compute_link_budget(
        self,
        elevation_deg: float,
        velocity_kms: float = 7.61,
        weather_factor: float = 0.0,   # 0=clear, 1=heavy rain
    ) -> LinkBudget:
        """
        Compute full RF link budget at a given elevation angle.

        Parameters
        ----------
        elevation_deg  : Elevation above horizon (degrees)
        velocity_kms   : Satellite velocity (km/s) for Doppler
        weather_factor : 0.0 = clear, 1.0 = heavy rain/troposcatter
        """
        slant_km   = _slant_range(elevation_deg)
        fspl       = _free_space_path_loss(slant_km)
        doppler    = _doppler_shift_khz(elevation_deg, velocity_kms)
        noise_dbm  = _thermal_noise_floor(BANDWIDTH_HZ)

        # Weather-induced attenuation: up to 3 dB additional loss
        atm_loss   = weather_factor * 3.0

        # Received power = Tx + Tx_gain - FSPL - atm_loss + Rx_gain
        rx_power_dbm = TX_POWER_DBM + TX_ANTENNA_DBI - fspl - atm_loss + RX_ANTENNA_DBI

        # SNR = Rx_power - noise_floor - noise_figure
        rx_snr = rx_power_dbm - noise_dbm - NOISE_FIGURE_DB

        # Link margin = SNR - minimum demodulation threshold (assume 10 dB for GMSK)
        min_snr     = 10.0
        link_margin = rx_snr - min_snr

        # Simplified BER model (AWGN, FSK): BER ≈ 0.5 * erfc(sqrt(Eb/N0))
        eb_n0    = rx_snr  # simplified approximation
        ber      = max(0, min(0.5, 0.5 * math.exp(-0.5 * max(eb_n0, 0))))
        loss_pct = min(100.0, ber * 100.0 * 10)  # crude packet loss estimate

        # Quality classification
        if   link_margin > 15: quality = "EXCELLENT"
        elif link_margin > 6:  quality = "GOOD"
        elif link_margin > 0:  quality = "MARGINAL"
        else:                   quality = "POOR"

        # Explanation
        parts = [
            f"Elevation {elevation_deg:.1f}° → Slant {slant_km:.0f}km",
            f"FSPL={fspl:.1f}dB | SNR={rx_snr:.1f}dB | Margin={link_margin:.1f}dB",
            f"Doppler={doppler:+.1f}kHz",
        ]
        if elevation_deg < 10:
            parts.append("⚠️ Low elevation — high atmospheric path, marginal geometry.")
        if weather_factor > 0.5:
            parts.append(f"🌧️ Weather attenuation: {atm_loss:.1f}dB loss.")
        if abs(doppler) > 5:
            parts.append(f"⚠️ High Doppler rate — verify AFC tracking in transceiver.")
        explanation = " | ".join(parts)

        return LinkBudget(
            elevation_deg   = round(elevation_deg, 1),
            slant_range_km  = round(slant_km, 1),
            fspl_db         = fspl,
            doppler_khz     = doppler,
            rx_snr_db       = round(rx_snr, 2),
            noise_floor_dbm = noise_dbm,
            link_margin_db  = round(link_margin, 2),
            expected_ber    = round(ber, 8),
            packet_loss_pct = round(loss_pct, 3),
            quality         = quality,
            explanation     = explanation,
            timestamp       = datetime.now(timezone.utc).isoformat(),
        )

    def analyze_pass(
        self,
        max_elevation_deg: float = 35.0,
        weather_factor:    float = 0.0,
        observed_loss_pct: float | None = None,
    ) -> LinkReport:
        """
        Analyze a complete satellite pass and explain observed packet loss.

        Parameters
        ----------
        max_elevation_deg : Peak elevation reached during the pass
        weather_factor    : 0=clear → 1=heavy rain
        observed_loss_pct : Observed packet loss %; will be explained
        """
        # Sample link budget at AOS (3°), mid-pass (max_el), and LOS (5°)
        budgets = {
            "AOS":    self.compute_link_budget(3.0,              0.0,          weather_factor),
            "MidPass":self.compute_link_budget(max_elevation_deg, 7.61 * 0.5,  weather_factor),
            "LOS":    self.compute_link_budget(5.0,              7.61,         weather_factor),
        }

        # Determine if an anomaly explains the observed loss
        anomaly_found  = False
        cause_analysis = []
        recommendations = []

        best_margin = budgets["MidPass"].link_margin_db
        if best_margin < 6:
            anomaly_found = True
            cause_analysis.append(
                f"📡 Link margin at peak elevation was only {best_margin:.1f}dB "
                f"(recommended >6 dB for reliable comms). Packet loss expected."
            )
            recommendations.append("Upgrade ground station antenna gain by ≥3dBi.")

        if max_elevation_deg < 15:
            anomaly_found = True
            cause_analysis.append(
                f"📐 Low maximum elevation ({max_elevation_deg:.1f}°) means rapid Doppler "
                f"change and extended atmospheric path at horizon — poor pass geometry."
            )
            recommendations.append("Reposition ground station for clear south horizon view.")

        if weather_factor > 0.3:
            anomaly_found = True
            cause_analysis.append(
                f"🌧️ Weather-induced attenuation estimated at "
                f"{weather_factor * 3.0:.1f}dB — tropospheric scintillation probable."
            )
            recommendations.append("Schedule critical uplinks for clear-sky passes only.")

        if observed_loss_pct and observed_loss_pct > 20:
            cause_analysis.append(
                f"📊 Observed {observed_loss_pct:.1f}% packet loss. "
                f"Expected from link model: {budgets['AOS'].packet_loss_pct:.1f}% at AOS."
            )

        if not anomaly_found:
            cause_analysis.append(
                "✅ Link budget analysis shows no anomaly. Packet loss may be software-side "
                "or ground equipment issue."
            )
            recommendations.append("Check ground TNC buffer overruns and demodulator AFC lock status.")

        summary = (
            f"[{self.gs_name}] Pass: MaxEl={max_elevation_deg:.1f}° | "
            f"PeakSNR={budgets['MidPass'].rx_snr_db:.1f}dB | "
            f"Margin={best_margin:.1f}dB | Quality={budgets['MidPass'].quality}"
        )

        report = LinkReport(
            pass_summary    = summary,
            link_budget     = {k: asdict(v) for k, v in budgets.items()},
            anomaly_found   = anomaly_found,
            cause_analysis  = cause_analysis,
            recommendations = recommendations,
            timestamp       = datetime.now(timezone.utc).isoformat(),
        )
        logger.info(f"[{self.name}] {summary}")
        return report

    def to_dict(self, report: LinkReport) -> dict:
        return asdict(report)
