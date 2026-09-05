import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from backend.engine import SkyGuardEngine

app = FastAPI(title="SkyGuard AI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = SkyGuardEngine()

# Track UI subscribers separately from ingestion sources
subscribers: list[WebSocket] = []

@app.get("/")
def read_root():
    return {
        "status": "online",
        "service": "SkyGuard AI Ingestion & Inference Engine",
        "subscribers_connected": len(subscribers)
    }

# 1. Dedicated endpoint for Frontend Dashboards to receive live telemetry
@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    await websocket.accept()
    subscribers.append(websocket)
    print(f"[UI] Dashboard connected. Active viewers: {len(subscribers)}")
    try:
        while True:
            # Keep connection open awaiting disconnects
            await websocket.receive_text()
    except WebSocketDisconnect:
        subscribers.remove(websocket)
        print(f"[UI] Dashboard disconnected. Remaining: {len(subscribers)}")

# 2. Ingestion endpoint strictly for Edge Streamers / ESP32
@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    await websocket.accept()
    print("[EDGE] Station connected to ingestion pipeline.")
    try:
        while True:
            raw_text = await websocket.receive_text()
            data = json.loads(raw_text)
            
            telemetry = data.get("telemetry", {})
            if not telemetry:
                continue

            # Run ML Inference & SHAP Attribution
            diagnostic = engine.process_reading(telemetry)

            enriched_payload = {
                "timestamp": data.get("timestamp"),
                "sensor_id": data.get("sensor_id", "AWS-ESP32-001"),
                "raw_telemetry": telemetry,
                "ai_diagnostics": diagnostic
            }

            # Broadcast ONLY to UI subscribers (never back to the streamer)
            dead_clients = []
            for client in subscribers:
                try:
                    await client.send_text(json.dumps(enriched_payload))
                except Exception:
                    dead_clients.append(client)
            
            for dead in dead_clients:
                subscribers.remove(dead)

    except WebSocketDisconnect:
        print("[EDGE] Station disconnected.")