"""
dashboard.py — CubeSat Wildfire Digital Twin — Flask Monitoring Dashboard
=========================================================================
Serves a stateless, dark-mode space-themed monitoring interface.

Architecture:
  - Reads outputs/state.json (written by main.py) every poll cycle
  - Serves rendered thermal/NDVI map images from outputs/
  - Zero shared state with the simulation — fully decoupled
  - Dynamic JS polling (no page refresh needed)

Run: python dashboard.py
Then open: http://localhost:5000
"""

import json
import os
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template_string, jsonify, send_from_directory

app = Flask(__name__)

OUTPUTS_DIR = Path("outputs")
STATE_FILE  = OUTPUTS_DIR / "state.json"


def read_state() -> dict:
    """Safely read the current simulation state."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"error": "Simulation not running — start main.py first.", "cycle": 0}


# ── HTML Template ────────────────────────────────────────────────────────────
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WILDFIRE_WATCH_1 — Mission Control Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;600;900&family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  /* ── Reset & Base ─────────────────────────────────────────────────────── */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg-deep:      #050810;
    --bg-panel:     #0a0f1e;
    --bg-card:      #0e1528;
    --bg-card2:     #111a30;
    --accent-cyan:  #00e5ff;
    --accent-teal:  #00bcd4;
    --accent-orange:#ff6d00;
    --accent-red:   #ff1744;
    --accent-green: #00e676;
    --accent-yellow:#ffd600;
    --text-primary: #e8ecf4;
    --text-muted:   #7a8aaa;
    --text-dim:     #4a5568;
    --border:       rgba(0,229,255,0.15);
    --glow-cyan:    0 0 20px rgba(0,229,255,0.3);
    --glow-orange:  0 0 20px rgba(255,109,0,0.4);
    --glow-red:     0 0 25px rgba(255,23,68,0.5);
    --glow-green:   0 0 15px rgba(0,230,118,0.3);
  }

  html { scroll-behavior: smooth; }

  body {
    font-family: 'Inter', sans-serif;
    background: var(--bg-deep);
    color: var(--text-primary);
    min-height: 100vh;
    overflow-x: hidden;
    background-image:
      radial-gradient(ellipse at 15% 20%, rgba(0,229,255,0.04) 0%, transparent 50%),
      radial-gradient(ellipse at 85% 80%, rgba(255,109,0,0.04) 0%, transparent 50%),
      url("data:image/svg+xml,%3Csvg width='100' height='100' xmlns='http://www.w3.org/2000/svg'%3E%3Ccircle cx='2' cy='2' r='0.5' fill='rgba(255,255,255,0.15)'/%3E%3Ccircle cx='50' cy='30' r='0.3' fill='rgba(255,255,255,0.1)'/%3E%3Ccircle cx='80' cy='70' r='0.4' fill='rgba(255,255,255,0.12)'/%3E%3Ccircle cx='30' cy='80' r='0.3' fill='rgba(255,255,255,0.08)'/%3E%3C/svg%3E");
  }

  /* ── Header ─────────────────────────────────────────────────────────────── */
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 32px;
    background: linear-gradient(90deg, rgba(0,229,255,0.06) 0%, transparent 100%);
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(12px);
  }
  .header-left { display: flex; align-items: center; gap: 16px; }
  .sat-icon { font-size: 2rem; animation: orbit 8s linear infinite; display: inline-block; }
  @keyframes orbit { 0%{transform:rotate(0deg) translateX(4px) rotate(0deg)}
                     100%{transform:rotate(360deg) translateX(4px) rotate(-360deg)} }
  .header-title { font-family: 'Orbitron', sans-serif; }
  .header-title h1 { font-size: 1.1rem; font-weight: 900; color: var(--accent-cyan);
                     text-shadow: var(--glow-cyan); letter-spacing: 2px; }
  .header-title p  { font-size: 0.7rem; color: var(--text-muted); letter-spacing: 1px; margin-top: 2px; }

  .header-status { display: flex; align-items: center; gap: 24px; }
  .status-pill {
    display: flex; align-items: center; gap: 8px;
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 6px 14px;
    font-size: 0.72rem;
    font-family: 'JetBrains Mono', monospace;
  }
  .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--accent-green);
           box-shadow: var(--glow-green); animation: pulse 2s ease-in-out infinite; }
  @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.5;transform:scale(0.8)} }
  .pulse.warn  { background: var(--accent-yellow); box-shadow: 0 0 10px rgba(255,214,0,0.5); }
  .pulse.crit  { background: var(--accent-red);    box-shadow: var(--glow-red); }

  #cycle-counter { font-family: 'Orbitron', sans-serif; font-size: 0.9rem; color: var(--accent-cyan); }

  /* ── Main grid ───────────────────────────────────────────────────────────── */
  main { display: grid; grid-template-columns: 340px 1fr; gap: 0; min-height: calc(100vh - 68px); }

  /* ── Sidebar ─────────────────────────────────────────────────────────────── */
  .sidebar {
    background: var(--bg-panel);
    border-right: 1px solid var(--border);
    padding: 20px 16px;
    display: flex; flex-direction: column; gap: 16px;
    overflow-y: auto;
  }

  /* ── Cards ───────────────────────────────────────────────────────────────── */
  .card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    position: relative;
    overflow: hidden;
    transition: border-color 0.3s, box-shadow 0.3s;
  }
  .card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--accent-cyan), transparent);
    opacity: 0.5;
  }
  .card:hover { border-color: rgba(0,229,255,0.35); box-shadow: var(--glow-cyan); }
  .card.warn::before  { background: linear-gradient(90deg, transparent, var(--accent-yellow), transparent); }
  .card.crit::before  { background: linear-gradient(90deg, transparent, var(--accent-red),    transparent); }
  .card.fire::before  { background: linear-gradient(90deg, transparent, var(--accent-orange),  transparent); }
  .card.green::before { background: linear-gradient(90deg, transparent, var(--accent-green),   transparent); }

  .card-title {
    font-family: 'Orbitron', sans-serif;
    font-size: 0.65rem;
    font-weight: 600;
    letter-spacing: 2px;
    color: var(--accent-cyan);
    text-transform: uppercase;
    margin-bottom: 12px;
    display: flex; align-items: center; gap: 8px;
  }
  .card-title .icon { font-size: 1rem; }

  /* ── Telemetry rows ─────────────────────────────────────────────────────── */
  .telem-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .telem-item { background: var(--bg-card2); border-radius: 8px; padding: 10px 12px; }
  .telem-label { font-size: 0.6rem; color: var(--text-muted); text-transform: uppercase;
                 letter-spacing: 1px; margin-bottom: 4px; }
  .telem-value { font-family: 'JetBrains Mono', monospace; font-size: 1.0rem;
                 color: var(--accent-cyan); font-weight: 500; }
  .telem-unit  { font-size: 0.65rem; color: var(--text-muted); margin-left: 3px; }

  /* ── Status badges ─────────────────────────────────────────────────────── */
  .badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.65rem;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
  }
  .badge-nominal { background: rgba(0,230,118,0.15); color: var(--accent-green);
                   border: 1px solid rgba(0,230,118,0.3); }
  .badge-warning { background: rgba(255,214,0,0.15);  color: var(--accent-yellow);
                   border: 1px solid rgba(255,214,0,0.3); }
  .badge-critical { background: rgba(255,23,68,0.15); color: var(--accent-red);
                    border: 1px solid rgba(255,23,68,0.3); }
  .badge-triggered { background: rgba(255,109,0,0.15); color: var(--accent-orange);
                     border: 1px solid rgba(255,109,0,0.3); }

  /* ── Subsystem bars ─────────────────────────────────────────────────────── */
  .subsystem-list { display: flex; flex-direction: column; gap: 6px; }
  .subsystem-row  { display: flex; align-items: center; gap: 8px; font-size: 0.72rem; }
  .sub-name  { width: 80px; color: var(--text-muted); font-family: 'JetBrains Mono', monospace; }
  .sub-bar   { flex: 1; height: 6px; background: rgba(255,255,255,0.05);
               border-radius: 3px; overflow: hidden; }
  .sub-fill  { height: 100%; border-radius: 3px; transition: width 0.8s ease;
               background: linear-gradient(90deg, var(--accent-green), var(--accent-cyan)); }
  .sub-fill.warn { background: linear-gradient(90deg, var(--accent-yellow), #ff9800); }
  .sub-fill.crit { background: linear-gradient(90deg, var(--accent-red), #ff6d00);
                   animation: flickerBar 1s ease-in-out infinite; }
  @keyframes flickerBar { 0%,100%{opacity:1} 50%{opacity:0.6} }
  .sub-val   { width: 70px; text-align: right; color: var(--text-primary);
               font-family: 'JetBrains Mono', monospace; font-size: 0.68rem; }

  /* ── Main content area ───────────────────────────────────────────────────── */
  .content { padding: 20px; display: flex; flex-direction: column; gap: 16px; overflow-y: auto; }

  /* ── Maps row ────────────────────────────────────────────────────────────── */
  .maps-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .map-container { position: relative; }
  .map-container img {
    width: 100%;
    border-radius: 10px;
    border: 1px solid var(--border);
    display: block;
    transition: transform 0.3s;
  }
  .map-container img:hover { transform: scale(1.01); }
  .map-label {
    position: absolute;
    top: 10px; left: 10px;
    background: rgba(5,8,16,0.8);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 0.62rem;
    font-family: 'Orbitron', sans-serif;
    color: var(--accent-cyan);
    letter-spacing: 1px;
    backdrop-filter: blur(8px);
  }

  /* ── Bottom row ──────────────────────────────────────────────────────────── */
  .bottom-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }

  /* ── Agent chain ─────────────────────────────────────────────────────────── */
  .agent-line {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.68rem;
    color: var(--text-muted);
    line-height: 1.6;
    border-left: 2px solid rgba(0,229,255,0.2);
    padding-left: 10px;
    margin-top: 4px;
  }
  .agent-line .hi { color: var(--accent-cyan); }
  .agent-line .warn { color: var(--accent-yellow); }
  .agent-line .err  { color: var(--accent-red); }
  .agent-line .ok   { color: var(--accent-green); }

  /* ── Oracle packets ──────────────────────────────────────────────────────── */
  .oracle-list { display: flex; flex-direction: column; gap: 8px; max-height: 260px;
                 overflow-y: auto; scrollbar-width: thin; scrollbar-color: var(--border) transparent; }
  .oracle-item {
    background: var(--bg-card2);
    border: 1px solid rgba(255,109,0,0.2);
    border-radius: 8px;
    padding: 10px 12px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.62rem;
    color: var(--text-muted);
    animation: fadeIn 0.5s ease;
  }
  @keyframes fadeIn { from{opacity:0;transform:translateY(-4px)} to{opacity:1;transform:translateY(0)} }
  .oracle-item .oracle-id   { color: var(--accent-orange); font-weight: 600; }
  .oracle-item .oracle-tx   { color: var(--text-dim); font-size: 0.58rem; }
  .oracle-item .oracle-loc  { color: var(--accent-cyan); }
  .oracle-empty { color: var(--text-dim); font-size: 0.72rem; text-align: center;
                  padding: 20px; font-style: italic; }

  /* ── Mission planning ────────────────────────────────────────────────────── */
  .feasible-yes { color: var(--accent-green); font-weight: 600; }
  .feasible-no  { color: var(--accent-red);   font-weight: 600; }
  .rec-text { font-size: 0.7rem; color: var(--text-muted); line-height: 1.6; margin-top: 8px;
              font-family: 'JetBrains Mono', monospace; }

  /* ── Ground station ──────────────────────────────────────────────────────── */
  .link-stat { display: flex; justify-content: space-between; font-size: 0.7rem;
               padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.03); }
  .link-stat:last-child { border-bottom: none; }
  .link-stat .lk { color: var(--text-muted); }
  .link-stat .lv { font-family: 'JetBrains Mono', monospace; color: var(--accent-cyan); }
  .link-stat .lv.poor  { color: var(--accent-red); }
  .link-stat .lv.marg  { color: var(--accent-yellow); }
  .link-stat .lv.good  { color: var(--accent-green); }

  /* ── NDVI risk meter ─────────────────────────────────────────────────────── */
  .risk-bar { display: flex; height: 10px; border-radius: 5px; overflow: hidden;
              background: var(--bg-card2); margin: 8px 0; }
  .risk-fill {
    height: 100%; border-radius: 5px;
    transition: width 1s ease;
  }

  /* ── Fault reasoning ─────────────────────────────────────────────────────── */
  .reason-chain { font-family: 'JetBrains Mono', monospace; font-size: 0.62rem;
                  color: var(--text-muted); line-height: 1.7; }
  .reason-chain .step { display: flex; gap: 6px; }
  .reason-chain .step::before { content: "›"; color: var(--accent-cyan); flex-shrink: 0; }

  /* ── Scrollbar styling ───────────────────────────────────────────────────── */
  ::-webkit-scrollbar { width: 5px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

  /* ── Timestamp ───────────────────────────────────────────────────────────── */
  .timestamp { font-size: 0.6rem; color: var(--text-dim);
               font-family: 'JetBrains Mono', monospace; margin-top: 8px; }

  /* ── Loading state ───────────────────────────────────────────────────────── */
  .loading { opacity: 0.5; font-style: italic; }

  /* ── Responsive ──────────────────────────────────────────────────────────── */
  @media (max-width: 1100px) {
    main { grid-template-columns: 1fr; }
    .maps-row     { grid-template-columns: 1fr; }
    .bottom-row   { grid-template-columns: 1fr; }
  }

  /* ── Animations ──────────────────────────────────────────────────────────── */
  .data-flash { animation: dataFlash 0.4s ease; }
  @keyframes dataFlash { 0%{color:var(--accent-cyan)} 100%{color:inherit} }

  /* ── FOV info strip ──────────────────────────────────────────────────────── */
  .fov-strip {
    display: flex; gap: 16px; flex-wrap: wrap;
    background: rgba(0,229,255,0.03);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 16px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.68rem;
  }
  .fov-item { display: flex; flex-direction: column; gap: 2px; }
  .fov-k { color: var(--text-muted); font-size: 0.58rem; text-transform: uppercase; }
  .fov-v { color: var(--accent-cyan); }
</style>
</head>
<body>

<!-- ── HEADER ─────────────────────────────────────────────────────────────── -->
<header>
  <div class="header-left">
    <span class="sat-icon">🛰️</span>
    <div class="header-title">
      <h1>WILDFIRE_WATCH_1</h1>
      <p>CUBESAT MISSION CONTROL · DIGITAL TWIN · REAL-TIME TELEMETRY</p>
    </div>
  </div>
  <div class="header-status">
    <div class="status-pill">
      <div class="pulse" id="health-pulse"></div>
      <span id="health-status-text">NOMINAL</span>
    </div>
    <div class="status-pill">
      <span>CYCLE</span>
      <span id="cycle-counter">---</span>
    </div>
    <div class="status-pill">
      <span id="update-time">--:--:-- UTC</span>
    </div>
  </div>
</header>

<!-- ── MAIN ───────────────────────────────────────────────────────────────── -->
<main>

  <!-- ── SIDEBAR ──────────────────────────────────────────────────────────── -->
  <aside class="sidebar">

    <!-- Orbit telemetry -->
    <div class="card" id="card-orbit">
      <div class="card-title"><span class="icon">🌍</span>Orbital State</div>
      <div class="telem-grid">
        <div class="telem-item">
          <div class="telem-label">Latitude</div>
          <div class="telem-value" id="tl-lat">—</div>
        </div>
        <div class="telem-item">
          <div class="telem-label">Longitude</div>
          <div class="telem-value" id="tl-lon">—</div>
        </div>
        <div class="telem-item">
          <div class="telem-label">Altitude</div>
          <div class="telem-value" id="tl-alt">—<span class="telem-unit">km</span></div>
        </div>
        <div class="telem-item">
          <div class="telem-label">Velocity</div>
          <div class="telem-value" id="tl-vel">—<span class="telem-unit">km/s</span></div>
        </div>
        <div class="telem-item">
          <div class="telem-label">Period</div>
          <div class="telem-value" id="tl-period">—<span class="telem-unit">min</span></div>
        </div>
        <div class="telem-item">
          <div class="telem-label">GSD</div>
          <div class="telem-value" id="tl-gsd">—<span class="telem-unit">m/px</span></div>
        </div>
      </div>
    </div>

    <!-- Subsystem health -->
    <div class="card" id="card-health">
      <div class="card-title"><span class="icon">💓</span>Subsystem Health
        <span class="badge badge-nominal" id="health-badge">NOMINAL</span>
      </div>
      <div class="subsystem-list" id="subsystem-list">
        <!-- injected by JS -->
      </div>
      <div class="timestamp" id="health-time"></div>
    </div>

    <!-- Fault diagnosis -->
    <div class="card" id="card-fault">
      <div class="card-title"><span class="icon">🔍</span>Fault Diagnosis</div>
      <div id="fault-code" style="font-family:'JetBrains Mono',monospace;font-size:0.78rem;color:var(--accent-orange);margin-bottom:8px;"></div>
      <div class="reason-chain" id="fault-chain"></div>
    </div>

    <!-- NDVI & burn summary -->
    <div class="card fire" id="card-ndvi">
      <div class="card-title"><span class="icon">🌿</span>Vegetation & Burn</div>
      <div class="telem-grid">
        <div class="telem-item">
          <div class="telem-label">NDVI Mean</div>
          <div class="telem-value" id="ndvi-mean">—</div>
        </div>
        <div class="telem-item">
          <div class="telem-label">Drought Idx</div>
          <div class="telem-value" id="ndvi-drought">—</div>
        </div>
        <div class="telem-item">
          <div class="telem-label">Burned Area</div>
          <div class="telem-value" id="burn-ha">—<span class="telem-unit">ha</span></div>
        </div>
        <div class="telem-item">
          <div class="telem-label">CO₂ Est.</div>
          <div class="telem-value" id="burn-co2">—<span class="telem-unit">t</span></div>
        </div>
      </div>
      <div style="margin-top:10px;">
        <div style="font-size:0.62rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;">
          Vegetation Risk
        </div>
        <div class="risk-bar">
          <div class="risk-fill" id="risk-fill" style="width:0%;background:var(--accent-green);"></div>
        </div>
        <div id="risk-class" style="font-family:'Orbitron',sans-serif;font-size:0.7rem;color:var(--accent-yellow);"></div>
      </div>
    </div>

    <!-- FIRMS summary -->
    <div class="card">
      <div class="card-title"><span class="icon">🔥</span>FIRMS Fire Data</div>
      <div class="telem-grid">
        <div class="telem-item">
          <div class="telem-label">Global Fires</div>
          <div class="telem-value" id="firms-total">—</div>
        </div>
        <div class="telem-item">
          <div class="telem-label">In FOV</div>
          <div class="telem-value" id="fires-fov" style="color:var(--accent-orange);">—</div>
        </div>
      </div>
    </div>

  </aside>

  <!-- ── CONTENT ────────────────────────────────────────────────────────────── -->
  <div class="content">

    <!-- FOV strip -->
    <div class="fov-strip" id="fov-strip">
      <div class="fov-item"><div class="fov-k">FOV Lat</div><div class="fov-v" id="fov-lat">—</div></div>
      <div class="fov-item"><div class="fov-k">FOV Lon</div><div class="fov-v" id="fov-lon">—</div></div>
      <div class="fov-item"><div class="fov-k">Swath</div><div class="fov-v" id="fov-swath">—</div></div>
      <div class="fov-item"><div class="fov-k">Sensor</div><div class="fov-v">MODIS-C6.1 / VIIRS</div></div>
      <div class="fov-item"><div class="fov-k">Inclination</div><div class="fov-v">97.4° SSO</div></div>
      <div class="fov-item"><div class="fov-k">NORAD ID</div><div class="fov-v">99001</div></div>
    </div>

    <!-- Maps row -->
    <div class="maps-row">
      <div class="map-container">
        <div class="map-label">🌡️ THERMAL MAP</div>
        <img id="thermal-img" src="/image/thermal_map.png" alt="Thermal Map"
             onerror="this.style.opacity='0.3'"
             style="min-height:200px;background:var(--bg-card);">
      </div>
      <div class="map-container">
        <div class="map-label">🌿 NDVI MAP</div>
        <img id="ndvi-img" src="/image/ndvi_map.png" alt="NDVI Map"
             onerror="this.style.opacity='0.3'"
             style="min-height:200px;background:var(--bg-card);">
      </div>
    </div>

    <!-- Bottom row -->
    <div class="bottom-row">

      <!-- Oracle packets -->
      <div class="card fire">
        <div class="card-title"><span class="icon">⛓️</span>Blockchain Oracle Packets</div>
        <div class="oracle-list" id="oracle-list">
          <div class="oracle-empty">No oracle events yet — awaiting fire threshold trigger…</div>
        </div>
      </div>

      <!-- Mission planning -->
      <div class="card green">
        <div class="card-title"><span class="icon">📡</span>Mission Planning Agent</div>
        <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:6px;">
          Target: <span id="mp-target" style="color:var(--accent-cyan);font-family:'JetBrains Mono',monospace;">—</span>
        </div>
        <div style="font-size:0.75rem;">
          Feasibility: <span id="mp-feasible" class="feasible-yes">—</span>
          &nbsp;<span id="mp-conf" class="badge badge-nominal">—</span>
        </div>
        <div style="margin-top:8px;font-size:0.65rem;color:var(--text-muted);">Next Pass</div>
        <div id="mp-pass" style="font-family:'JetBrains Mono',monospace;font-size:0.68rem;color:var(--accent-teal);"></div>
        <div class="rec-text" id="mp-rec"></div>
      </div>

      <!-- Ground station -->
      <div class="card">
        <div class="card-title"><span class="icon">📶</span>Ground Station Link</div>
        <div id="gs-summary" style="font-size:0.68rem;color:var(--text-muted);margin-bottom:8px;font-family:'JetBrains Mono',monospace;"></div>
        <div id="link-stats"></div>
        <div id="gs-causes" style="font-size:0.62rem;color:var(--text-muted);margin-top:8px;line-height:1.6;"></div>
      </div>

    </div>

  </div>
</main>

<script>
// ── Polling configuration ──────────────────────────────────────────────────
const POLL_INTERVAL_MS = 3000;
let lastCycle = -1;

// ── Utility helpers ────────────────────────────────────────────────────────
function set(id, val)  { const el = document.getElementById(id); if(el) el.textContent = val; }
function setHTML(id, h){ const el = document.getElementById(id); if(el) el.innerHTML = h;    }
function flash(id) {
  const el = document.getElementById(id);
  if(el){ el.classList.remove('data-flash'); void el.offsetWidth; el.classList.add('data-flash'); }
}

function statusColor(s) {
  if(s === 'NOMINAL' || s === 'EXCELLENT' || s === 'GOOD') return 'var(--accent-green)';
  if(s === 'WARNING' || s === 'MARGINAL')  return 'var(--accent-yellow)';
  return 'var(--accent-red)';
}

function formatNum(v, digits=2) {
  if(v === undefined || v === null) return '—';
  return Number(v).toFixed(digits);
}

// ── Update header ────────────────────────────────────────────────────────
function updateHeader(d) {
  set('cycle-counter', String(d.cycle).padStart(4,'0'));
  const now = new Date();
  set('update-time', now.toISOString().substring(11,19) + ' UTC');

  const hs = (d.health || {}).overall || 'NOMINAL';
  set('health-status-text', hs);
  const pulse = document.getElementById('health-pulse');
  if(pulse) {
    pulse.className = 'pulse' + (hs==='CRITICAL' ? ' crit' : hs==='WARNING' ? ' warn' : '');
  }
}

// ── Orbit telemetry ────────────────────────────────────────────────────
function updateOrbit(d) {
  const o = d.orbit || {};
  set('tl-lat',    formatNum(o.lat_deg, 3) + '°');
  set('tl-lon',    formatNum(o.lon_deg, 3) + '°');
  set('tl-alt',    formatNum(o.alt_km, 1));
  set('tl-vel',    formatNum(o.velocity_kms, 3));
  set('tl-period', formatNum(o.period_min, 1));
  set('tl-gsd',    formatNum(d.gsd_m, 1));
  flash('tl-lat'); flash('tl-lon');

  const fov = d.fov || {};
  set('fov-lat',   `${formatNum(fov.lat_min,2)}° → ${formatNum(fov.lat_max,2)}°`);
  set('fov-lon',   `${formatNum(fov.lon_min,2)}° → ${formatNum(fov.lon_max,2)}°`);
  set('fov-swath', `${formatNum(fov.width_km,0)} km × ${formatNum(fov.height_km,0)} km`);
}

// ── Subsystem health ───────────────────────────────────────────────────────
function updateHealth(d) {
  const h = d.health || {};
  const subs = h.subsystems || [];
  const overall = h.overall || 'NOMINAL';

  const badge = document.getElementById('health-badge');
  if(badge) {
    badge.className = 'badge ' + (overall==='NOMINAL' ? 'badge-nominal' :
                                   overall==='WARNING' ? 'badge-warning' : 'badge-critical');
    badge.textContent = overall;
  }

  const limits = {
    battery_v: [6.8, 8.5], solar_A: [0, 4], temp_C: [-20, 65],
    power_W: [0, 15], gyro_dps: [0, 3], mag_uT: [20, 65]
  };
  const labels = {
    battery_v:'Battery', solar_A:'Solar', temp_C:'Temp',
    power_W:'Power', gyro_dps:'Gyro', mag_uT:'Magnetom'
  };
  const units  = {
    battery_v:'V', solar_A:'A', temp_C:'°C', power_W:'W', gyro_dps:'°/s', mag_uT:'μT'
  };

  let html = '';
  for(const s of subs) {
    const [lo, hi] = limits[s.name] || [0, 100];
    const pct = Math.round(Math.min(100, Math.max(0, ((s.value - lo)/(hi - lo)) * 100)));
    const cls = s.status === 'CRITICAL' ? 'crit' : s.status === 'WARNING' ? 'warn' : '';
    html += `<div class="subsystem-row">
      <span class="sub-name">${labels[s.name]||s.name}</span>
      <div class="sub-bar"><div class="sub-fill ${cls}" style="width:${pct}%"></div></div>
      <span class="sub-val">${formatNum(s.value,2)} ${units[s.name]||''}</span>
    </div>`;
  }
  setHTML('subsystem-list', html || '<span style="color:var(--text-dim)">No data</span>');
  set('health-time', h.timestamp ? h.timestamp.substring(0,19).replace('T',' ') + ' UTC' : '');
}

// ── Fault diagnosis ─────────────────────────────────────────────────────────
function updateFault(d) {
  const f = d.fault || {};
  const ph = f.primary_hypothesis || {};
  set('fault-code', ph.code || 'ALL_NOMINAL');
  const el = document.getElementById('fault-code');
  if(el) el.style.color = f.fault_detected ? 'var(--accent-orange)' : 'var(--accent-green)';

  const chain = f.reasoning_chain || [];
  let html = chain.map(c => `<div class="step">${c}</div>`).join('');
  setHTML('fault-chain', html);
}

// ── NDVI / burn ─────────────────────────────────────────────────────────────
function updateNDVI(d) {
  const n = d.ndvi  || {};
  const b = d.burn  || {};
  set('ndvi-mean',    formatNum(n.mean_ndvi, 3));
  set('ndvi-drought', formatNum(n.drought_index, 2));
  set('burn-ha',      Number(b.total_hectares||0).toLocaleString(undefined,{maximumFractionDigits:1}));
  set('burn-co2',     Number(b.co2_est_tonnes||0).toLocaleString(undefined,{maximumFractionDigits:0}));

  const risk = n.risk_class || 'Low';
  const riskPct = {Low:15, Moderate:40, High:70, Critical:95}[risk] || 20;
  const riskColor = {Low:'var(--accent-green)', Moderate:'var(--accent-yellow)',
                     High:'var(--accent-orange)', Critical:'var(--accent-red)'}[risk];
  const fill = document.getElementById('risk-fill');
  if(fill) { fill.style.width = riskPct+'%'; fill.style.background = riskColor; }
  set('risk-class', risk.toUpperCase());
  const rc = document.getElementById('risk-class');
  if(rc) rc.style.color = riskColor;
}

// ── FIRMS ─────────────────────────────────────────────────────────────────────
function updateFirms(d) {
  set('firms-total', (d.firms_total||0).toLocaleString());
  set('fires-fov',   d.fires_in_fov || 0);
}

// ── Oracle ───────────────────────────────────────────────────────────────────
function updateOracle(d) {
  const hist = d.oracle_history || [];
  if(!hist.length) return;

  let html = '';
  for(const p of [...hist].reverse()) {
    const fe = p.fire_event || {};
    const sc = p.smart_contract || {};
    html += `<div class="oracle-item">
      <div><span class="oracle-id">Oracle#${(p.packet_id||'').substring(0,10)}</span>
           &nbsp;<span class="badge badge-triggered">${sc.status||'CONFIRMED'}</span></div>
      <div class="oracle-loc">🔥 (${formatNum(fe.lat_deg,2)}°, ${formatNum(fe.lon_deg,2)}°)
           &nbsp;Bright=${formatNum(fe.brightness_K,0)}K Conf=${fe.confidence_pct}%</div>
      <div>Area: <b style="color:var(--accent-orange)">${Number(fe.total_area_ha||0).toFixed(1)} ha</b>
           &nbsp;Severity: ${fe.dominant_severity}</div>
      <div class="oracle-tx">TX: ${(sc.tx_hash||'').substring(0,18)}… Block#${sc.block_number}</div>
      <div class="oracle-tx">${(p.trigger_timestamp||'').substring(0,19).replace('T',' ')} UTC</div>
    </div>`;
  }
  setHTML('oracle-list', html);
}

// ── Mission planning ─────────────────────────────────────────────────────────
function updateMission(d) {
  const mp = d.mission_plan || {};
  set('mp-target', mp.target_name || '—');
  const el = document.getElementById('mp-feasible');
  if(el) {
    el.textContent = mp.feasible ? 'YES ✅' : 'NO ⚠️';
    el.className = mp.feasible ? 'feasible-yes' : 'feasible-no';
  }
  const conf = document.getElementById('mp-conf');
  if(conf) {
    conf.textContent = mp.confidence || '—';
    conf.className = 'badge ' + (mp.confidence==='HIGH' ? 'badge-nominal' :
                                  mp.confidence==='LOW'  ? 'badge-critical' : 'badge-warning');
  }
  if(mp.next_pass_utc) {
    const np = new Date(mp.next_pass_utc);
    set('mp-pass', np.toISOString().substring(11,16) + ' UTC');
  }
  set('mp-rec', mp.recommendation ? mp.recommendation.substring(0, 220) : '');
}

// ── Ground station ────────────────────────────────────────────────────────────
function updateGS(d) {
  const gs = d.ground_station || {};
  set('gs-summary', gs.pass_summary || '');

  const lb = gs.link_budget || {};
  const mid = lb.MidPass || {};
  let statsHtml = '';
  const q = mid.quality || 'GOOD';
  const qClass = q==='EXCELLENT'||q==='GOOD' ? 'good' : q==='MARGINAL' ? 'marg' : 'poor';
  statsHtml += `<div class="link-stat"><span class="lk">Elevation</span><span class="lv">${formatNum(mid.elevation_deg,1)}°</span></div>`;
  statsHtml += `<div class="link-stat"><span class="lk">Slant Range</span><span class="lv">${formatNum(mid.slant_range_km,0)} km</span></div>`;
  statsHtml += `<div class="link-stat"><span class="lk">SNR</span><span class="lv ${qClass}">${formatNum(mid.rx_snr_db,1)} dB</span></div>`;
  statsHtml += `<div class="link-stat"><span class="lk">Link Margin</span><span class="lv ${qClass}">${formatNum(mid.link_margin_db,1)} dB</span></div>`;
  statsHtml += `<div class="link-stat"><span class="lk">Doppler</span><span class="lv">${formatNum(mid.doppler_khz,1)} kHz</span></div>`;
  statsHtml += `<div class="link-stat"><span class="lk">Link Quality</span><span class="lv ${qClass}">${q}</span></div>`;
  setHTML('link-stats', statsHtml);

  const causes = gs.cause_analysis || [];
  setHTML('gs-causes', causes.map(c=>`<div>${c}</div>`).join(''));
}

// ── Images refresh (bust cache) ───────────────────────────────────────────────
function refreshImages() {
  const ts = Date.now();
  const t  = document.getElementById('thermal-img');
  const n  = document.getElementById('ndvi-img');
  if(t) t.src = `/image/thermal_map.png?t=${ts}`;
  if(n) n.src = `/image/ndvi_map.png?t=${ts}`;
}

// ── Main poll loop ────────────────────────────────────────────────────────────
async function poll() {
  try {
    const resp = await fetch('/api/state');
    if(!resp.ok) return;
    const d = await resp.json();

    if(d.error) {
      setHTML('oracle-list', `<div class="oracle-empty">${d.error}</div>`);
      return;
    }

    if(d.cycle !== lastCycle) {
      lastCycle = d.cycle;
      updateHeader(d);
      updateOrbit(d);
      updateHealth(d);
      updateFault(d);
      updateNDVI(d);
      updateFirms(d);
      updateOracle(d);
      updateMission(d);
      updateGS(d);
      refreshImages();
    }
  } catch(e) {
    console.warn('Poll error:', e);
  }
}

// Start polling
poll();
setInterval(poll, POLL_INTERVAL_MS);
</script>
</body>
</html>"""


# ── Flask Routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/state")
def api_state():
    """JSON endpoint — returns current simulation state."""
    state = read_state()
    return jsonify(state)


@app.route("/image/<filename>")
def serve_image(filename: str):
    """Serve rendered images from outputs/ directory."""
    safe_names = {"thermal_map.png", "ndvi_map.png"}
    if filename not in safe_names:
        return "Not found", 404
    return send_from_directory(str(OUTPUTS_DIR.absolute()), filename)


if __name__ == "__main__":
    print("=" * 60)
    print("  🛰️  CubeSat Wildfire Dashboard")
    print("  URL: http://localhost:5000")
    print("  ⚠️  Start main.py in a separate terminal first!")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False)
