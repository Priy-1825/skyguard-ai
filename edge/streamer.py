import time
import json
import random
from datetime import datetime, timezone

class VirtualWeatherStation:
    def __init__(self):
        self.temp = 35.0      # °C
        self.pressure = 1005.0 # hPa
        self.humidity = 50.0   # %
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

if __name__ == "__main__":
    station = VirtualWeatherStation()
    print("Skyguard Virtual AWS Streamer active. Press Ctrl+C to stop.\n")
    tick = 0
    try:
        while True:
            tick += 1
            if tick == 5:
                station.fault_state = "SPIKE"
            elif tick == 10:
                station.fault_state = "DRIFT"
            data = station.generate_payload()
            print(json.dumps(data))
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStreamer stopped.")