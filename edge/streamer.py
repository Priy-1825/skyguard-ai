import asyncio
import json
import random
from datetime import datetime, timezone
import websockets

class VirtualWeatherStation:
    def __init__(self):
        self.temp = 35.0
        self.pressure = 1005.0
        self.humidity = 50.0
        self.fault_state = "NORMAL"
        self.drift_counter = 0

    def get_normal_reading(self):
        self.temp += random.uniform(-0.1, 0.1)
        self.pressure += random.uniform(-0.5, 0.5)
        self.humidity += random.uniform(-0.5, 0.5)
        self.humidity = max(0, min(100, self.humidity))
        return self.temp, self.pressure, self.humidity

    def apply_fault(self, t, p, h):
        if self.fault_state == "SPIKE":
            t = 55.0
            self.fault_state = "NORMAL"
        elif self.fault_state == "DRIFT":
            self.drift_counter += 1
            t += (0.5 * self.drift_counter)
        elif self.fault_state == "FROZEN":
            p = 1013.25
        return t, p, h

    def generate_payload(self):
        t, p, h = self.get_normal_reading()
        t, p, h = self.apply_fault(t, p, h)
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sensor_id": "AWS-ESP32-001",
            "telemetry": {
                "temperature_c": round(t, 2),
                "pressure_hpa": round(p, 2),
                "humidity_percent": round(h, 2)
            },
            "status": "active"
        }
async def stream_telemetry():
    uri = "ws://127.0.0.1:8000/ws/telemetry"
    station = VirtualWeatherStation()
    
    while True:
        try:
            print(f"Connecting to SkyGuard Backend at {uri}...")
            # ping_interval=None prevents client-side heartbeat timeouts during continuous push
            async with websockets.connect(uri, ping_interval=None, ping_timeout=None) as websocket:
                print("Connected! Streaming telemetry every 1s...")
                tick = 0
                while True:
                    tick += 1
                    
                    if tick == 5:
                        print("\n[!] Injecting Fault: 55°C Spike")
                        station.fault_state = "SPIKE"
                    elif tick == 10:
                        print("\n[!] Injecting Fault: Sensor Drift Started")
                        station.fault_state = "DRIFT"
                        
                    payload = station.generate_payload()
                    await websocket.send(json.dumps(payload))
                    print(f"Sent tick {tick}: {payload['telemetry']}")
                    await asyncio.sleep(1)

        except (websockets.exceptions.ConnectionClosedError, ConnectionRefusedError) as e:
            print(f"Connection dropped ({e}). Reconnecting in 2 seconds...")
            await asyncio.sleep(2)

if __name__ == "__main__":
    try:
        asyncio.run(stream_telemetry())
    except KeyboardInterrupt:
        print("\nStreamer stopped.")