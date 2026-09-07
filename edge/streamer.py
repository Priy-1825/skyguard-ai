import time
import requests
import random
from datetime import datetime, timezone, timedelta

API_URL = "http://localhost:3000/api/telemetry"
STATIONS = [str(s) for s in range(1, 10)]

def generate_values():
    values = {}
    for s in STATIONS:
        values[f"{s}_temp_c"] = 35.0 + random.uniform(-1, 1)
        values[f"{s}_pressure_hpa"] = 1005.0 + random.uniform(-2, 2)
        values[f"{s}_rh_pct"] = 50.0 + random.uniform(-5, 5)
    return values

print("Warming up API buffer (needs 24 ticks)...")
base_time = datetime.now(timezone.utc) - timedelta(hours=25)

# 1. Send 24 quick historical ticks to fill the sequence buffer
for i in range(1, 26):
    payload = {
        "timestamp": (base_time + timedelta(hours=i)).isoformat(),
        "values": generate_values()
    }
    requests.post(API_URL, json=payload)
    print(f"Sent warm-up tick {i}")

print("\nStarting live 9-station stream...")
tick = 25

# 2. Stream live data every second
while True:
    tick += 1
    values = generate_values()
    
    # Fault Injection: Spike Station 1 temperature
    if tick == 30:
        print("\n[!] Injecting Fault: Station 1 temperature spike (60°C)")
        values["1_temp_c"] = 60.0
        
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "values": values
    }
    
    try:
        response = requests.post(API_URL, json=payload)
        print(f"Sent tick {tick} | HTTP Status: {response.status_code}")
        
        # # Check if the AI flagged the injected fault
        # if response.status_code == 200:
        #     flags = [res for res in response.json() if res["is_anomaly"]]
        #     if flags:
        #         print(f" ---> AI Flag: {flags[0]['root_cause']} on station {flags[0]['station']}")
                
    except Exception as e:
        print(f"Connection failed: {e}")
        
    time.sleep(3)