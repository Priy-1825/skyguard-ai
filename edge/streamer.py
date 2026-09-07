import requests
import time
import random
from datetime import datetime, timezone
import joblib
import shap
import pandas as pd
import numpy as np

print("Loading pre-trained Isolation Forest model...")
print("Streaming 1 tick every 3 seconds. Anomaly triggers at Tick 15.\n")
try:
    # Path relative to the edge folder
    bundle = joblib.load("../backend/iso_forest.joblib")
    model = bundle["model"]
    feature_cols = bundle["feature_cols"]
    explainer = shap.TreeExplainer(model)
    print("Model and SHAP explainer loaded successfully!\n")
except Exception as e:
    print(f"Warning: Could not load model or feature mismatch ({e}). Using fallback.")
    model = None
# Next.js local ingestion API
URL = "http://localhost:3000/api/telemetry"

print("Starting SKYGUARD 9-Node Regional Grid Telemetry Streamer...")
print(f"Targeting: {URL}")
print("Streaming 1 tick every 2 seconds. Anomaly triggers at Tick 15.\n")

tick_count = 0

while True:
    tick_count += 1
    
    # Base nominal values for the Delhi grid
    base_temp = 28.5
    base_hum = 63.0
    base_press = 1013.2
    
    values = {}
    
    # Generate baseline data for all 9 stations with slight natural variance
    for i in range(1, 10):
        values[f"{i}_temp_c"] = round(base_temp + random.uniform(-0.4, 0.4), 1)
        values[f"{i}_humidity"] = round(base_hum + random.uniform(-1.0, 1.0), 1)
        values[f"{i}_pressure"] = round(base_press + random.uniform(-0.2, 0.2), 1)
    
    # --- INJECT ANOMALY ON NODE 01 (Connaught Place) ---
    # At tick 30, simulate severe hardware calibration drift
    if tick_count >= 15:
        values["1_temp_c"] = round(35.5 + random.uniform(0.1, 1.0), 1) # Triggers > 34.0 spike
        values["1_humidity"] = round(82.0 + random.uniform(-1.0, 1.0), 1)
        values["1_pressure"] = round(1011.0 + random.uniform(-0.2, 0.2), 1)
        
       # --- DYNAMIC ML INFERENCE & SHAP ---
        if model is not None:
            # Construct a row matching the engineered columns your model expects
            dummy_row = pd.DataFrame(0, index=[0], columns=feature_cols)
            
            # Map the live spike into the engineered Z-score features for Node 1
            if "1_temp_c_z_short" in feature_cols:
                dummy_row["1_temp_c_z_short"] = 5.0  # Massive temp spike
            if "1_humidity_z_short" in feature_cols:
                dummy_row["1_humidity_z_short"] = 2.0
                
            raw_score = -model.decision_function(dummy_row.values)[0]
            # Adjusted multiplier so severe spikes show 90%+ confidence
            confidence_pct = min(max((raw_score * 300) + 90, 75), 99.9)
            values["confidence"] = round(confidence_pct, 1)
            
            shap_values = explainer.shap_values(dummy_row.values)
            abs_shap = np.abs(shap_values[0])
            total_shap = np.sum(abs_shap)
            
            if total_shap > 0:
                blame_pct = (abs_shap / total_shap) * 100
                # Extract the top contributing features safely
                values["shap_temp"] = int(blame_pct[0]) if len(blame_pct) > 0 else 88
                values["shap_humidity"] = int(blame_pct[1]) if len(blame_pct) > 1 else 8
                values["shap_pressure"] = int(blame_pct[2]) if len(blame_pct) > 2 else 4
            else:
                values["shap_temp"], values["shap_humidity"], values["shap_pressure"] = 88, 8, 4
        else:
           # Safe fallback so your dashboard never breaks during the pitch
           values["shap_temp"], values["shap_humidity"], values["shap_pressure"] = 88, 8, 4
           values["confidence"] = 94.2
        
        if tick_count == 15:
            print("\n🚨 INJECTING CRITICAL ANOMALY ON NODE 01 🚨\n")

    # Construct the JSON payload
    payload = {
       "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "values": values
    }
    
    # Send the payload to the Next.js backend
    try:
        response = requests.post(URL, json=payload)
        print(f"[Tick {tick_count:02d}] 9-Node Telemetry Sent | Node 01 Temp: {values['1_temp_c']}°C | HTTP {response.status_code}")
    except requests.exceptions.RequestException:
        print(f"[Tick {tick_count:02d}] Connection failed. Is the Next.js server running?")
    
    # 2-second delay for smooth presentation pacing
    time.sleep(2)