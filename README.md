# 🛰️ WILDFIRE_WATCH

### AI-Powered CubeSat Digital Twin for Autonomous Wildfire Detection and Response



## Overview

**WILDFIRE_WATCH_1** is a high-fidelity digital twin of an Earth-observing CubeSat designed for autonomous wildfire monitoring, onboard decision-making, and decentralized event reporting.

The system combines:

* Orbital mechanics
* Live NASA wildfire data
* Multispectral vegetation analysis
* Burn scar estimation
* Multi-Agent spacecraft autonomy
* RF communication modeling
* Blockchain oracle triggering
* Real-time command center dashboard

Unlike traditional monolithic simulations, the architecture is fully decoupled, ensuring stability, scalability, and fault isolation.

---

# System Architecture

```
                    ┌────────────────────┐
                    │  NASA FIRMS APIs   │
                    │ (MODIS + VIIRS)    │
                    └─────────┬──────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │      main.py            │
                 │ Simulation Engine       │
                 └─────────┬───────────────┘
                           │
          ┌────────────────┼─────────────────┐
          │                │                 │
          ▼                ▼                 ▼
  Orbit Engine      Sensor Analysis     Multi-Agent System
 (Skyfield)         (NDVI + Burn)          (5 Agents)
          │                │                 │
          └────────────────┼─────────────────┘
                           ▼
                   state.json (Shared State)
                           ▼
                 ┌──────────────────────┐
                 │   Flask Dashboard    │
                 │  Real-Time UI Layer  │
                 └──────────────────────┘
```

---

# Key Features

## 🛰 Accurate Orbital Propagation

Using the **Skyfield** library, the satellite is propagated in a realistic Sun-Synchronous Orbit (~550 km altitude).

Calculated every simulation tick:

* Latitude
* Longitude
* Altitude
* Velocity
* Ground track
* Sensor Field of View

---

## 🔥 Live NASA Wildfire Data

Real wildfire hotspots are fetched from NASA FIRMS public endpoints:

* MODIS
* VIIRS

Features:

* Last 24-hour wildfire observations
* No API key required
* Automatic synthetic-fire fallback
* Continuous data updates

---

## 🌎 Dynamic Field of View Filtering

The sensor swath (~185 km) is computed in real time.

Only hotspots inside the satellite's instantaneous footprint are processed, allowing the digital twin to mimic what the spacecraft would physically observe.

---

## 🌿 NDVI Vegetation Risk Analysis

Simulated multispectral imaging computes:

### Normalized Difference Vegetation Index (NDVI)

Active fires induce:

* Drought stress
* Vegetation degradation
* Canopy damage

Result:

* Dynamic vegetation health maps
* Real-time risk visualization

---

## 🔥 Burn Scar Estimation

Ground Sampling Distance (GSD) is calculated from orbital altitude.

From detected hotspots, the system estimates:

* Burned area (hectares)
* Carbon emissions
* Ecosystem recovery time
* Spatial impact

---

# Autonomous Multi-Agent System

Instead of relying on thousands of hardcoded rules, spacecraft operations are managed by five specialized AI agents.

---

## Health Monitoring Agent

Continuously audits:

* Battery
* Solar array
* Power system
* Temperature
* Gyroscope
* Magnetometer

---

## Fault Diagnosis Agent

Performs correlated anomaly analysis.

Examples:

### Eclipse Detection

```
Solar Current ↓
Battery Normal
Temperature Stable

→ Eclipse Condition
```

### Thermal Runaway Detection

```
Temperature ↑
Power Consumption ↑

→ Thermal Anomaly
```

---

## Mission Planning Agent

Evaluates imaging requests by checking:

* Orbital geometry
* Angular separation
* Battery availability
* Memory capacity

---

## Ground Station Agent

Simulates realistic communications.

Computes:

* Free Space Path Loss (FSPL)
* Doppler shift
* Signal-to-Noise Ratio
* Packet loss probability

---

## Anomaly Investigation Agent

Acts as a post-event forensic engine.

Analyzes telemetry history to determine the root cause of:

* Communication blackouts
* Power anomalies
* Thermal excursions
* Sensor failures

---

# Blockchain Oracle Layer

When wildfire confidence exceeds 70%, the payload subsystem creates an **Oracle Packet** containing:

* Coordinates
* Thermal measurements
* Satellite state
* Detection confidence

In a real deployment, this packet could be cryptographically signed and transmitted to smart contracts on networks such as:

* Polygon
* Ethereum Layer-2

Potential applications:

* Parametric insurance payouts
* Disaster-response funding
* Environmental monitoring incentives

---

# Real-Time Dashboard

The Flask-based command center provides:

* Live telemetry
* Health monitoring
* Orbit information
* Thermal maps
* NDVI maps
* AI agent status
* Fire detections

The dashboard is completely stateless and refreshes automatically without interrupting the simulation engine.

---

# Decoupled Architecture

The simulation backend and UI operate independently.

```
main.py
    ↓
state.json
    ↓
dashboard.py
```

### Advantages

✔ Prevents UI crashes from affecting the simulation

✔ Thread-safe architecture

✔ Better scalability

✔ Easier debugging

✔ Real-time responsiveness

---

# Project Structure

```
WILDFIRE_WATCH_1/
│
├── main.py
├── dashboard.py
├── orbit_engine.py
├── firms_api.py
├── ndvi_analysis.py
├── burn_analysis.py
├── oracle_trigger.py
│
├── agents/
│   ├── health_monitor_agent.py
│   ├── fault_diagnosis_agent.py
│   ├── mission_planner_agent.py
│   ├── ground_station_agent.py
│   └── anomaly_investigation_agent.py
│
├── assets/
│   ├── thermal_map.png
│   ├── ndvi_map.png
│   └── banner.png
│
├── state.json
├── requirements.txt
└── README.md
```

---

# Technologies Used

### Aerospace & Simulation

* Skyfield
* NumPy
* Pandas

### Data Sources

* NASA FIRMS
* MODIS
* VIIRS

### Visualization

* Matplotlib (Agg backend)

### Backend

* Python
* Flask

### Spacecraft Analytics

* Orbital propagation
* GSD estimation
* Link budget analysis
* Doppler modeling

### AI Architecture

* Multi-Agent Systems

### Web3

* Polygon Oracle Concept

---

# Applications

* Wildfire monitoring
* Disaster management
* Climate resilience
* Autonomous CubeSat operations
* Environmental digital twins
* Space situational awareness
* Decentralized insurance systems

---

# Future Work

* SGP4 propagation
* STK/Cesium integration
* Reinforcement-learning mission planner
* Kalman-filter attitude estimation
* CCSDS packet simulation
* LoRa/UHF radio models
* Cloud deployment
* Real blockchain oracle execution
* Integration with ISRO datasets

---

# Author

Developed as an experimental autonomous Earth-observation CubeSat digital twin demonstrating the convergence of:

> Aerospace Engineering × AI × Remote Sensing × Multi-Agent Systems × Web3
