"""API Code"""

from collections import deque
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import torch
import joblib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from backend.feature_engineer import engineer_all_features, VARIABLES
from backend.lstm import LSTMAutoencoder, get_raw_columns
from backend.ensemble import robust_z, classify_root_cause_vectorized, FLAG_THRESHOLD_Z, LSTM_WEIGHT, ISO_WEIGHT
app = FastAPI(title="SkyGuard AI")

STATIONS = [str(s) for s in range(1, 10)]
BUFFER_SIZE = 200  # hours of history kept per station; must exceed the 168h weekly window
SEQ_LEN = 24

# in-memory state -- fine for a single-process demo/hackathon deployment;
# swap for Redis or a small DB (e.g. SQLite/Postgres) if this needs to survive
# restarts or run across multiple worker processes
buffer: deque = deque(maxlen=BUFFER_SIZE)
recent_flags: List[dict] = []  # rolling log, used for sensor health status

lstm_checkpoint = None
lstm_model = None
iso_bundle = None


class Reading(BaseModel):
    timestamp: str  # ISO format
    values: Dict[str, float]  # e.g. {"1_pressure_hpa": 1005.2, "1_temp_c": 24.1, ...}


class ScoreResult(BaseModel):
    station: str
    variable: str
    value: Optional[float]
    is_anomaly: bool
    confidence: float
    root_cause: str
    corrected_value: Optional[float]


@app.on_event("startup")
def load_models():
    global lstm_checkpoint, lstm_model, iso_bundle
    lstm_checkpoint = torch.load("backend/lstm_ae.pt", weights_only=False)
    lstm_model = LSTMAutoencoder(n_features=lstm_checkpoint["n_features"],
                                 seq_len=lstm_checkpoint["seq_len"])
    lstm_model.load_state_dict(lstm_checkpoint["model_state"])
    lstm_model.eval()
    iso_bundle = joblib.load("backend/iso_forest.joblib")

def suggest_correction(row: pd.Series, station: str, variable: str, stations=STATIONS):
    """Cross-station ensemble median at this single timestamp -- same logic
    as correction.py, applied to one row instead of a batch file."""
    other_cols = [f"{s}_{variable}" for s in stations if s != station and f"{s}_{variable}" in row.index]
    if not other_cols:
        return None
    values = row[other_cols].dropna()
    if len(values) == 0:
        return None
    return float(values.median())


@app.post("/ingest", response_model=List[ScoreResult])
def ingest(reading: Reading):
    """Accepts one new timestep of readings across all stations, scores it
    against recent history, and returns per-(station,variable) results."""
    if lstm_model is None:
        raise HTTPException(status_code=503, detail="Models not loaded yet")

    row = {"valid_time": pd.to_datetime(reading.timestamp)}
    row.update(reading.values)
    buffer.append(row)

    if len(buffer) < SEQ_LEN:
        raise HTTPException(
            status_code=425,  # 425 Too Early
            detail=f"Need at least {SEQ_LEN} readings of history before scoring; have {len(buffer)}."
        )

    df = pd.DataFrame(list(buffer))
    df_feat = engineer_all_features(df, STATIONS)

    latest_idx = df_feat.index[-1]
    latest_row = df_feat.iloc[latest_idx]

    results = []

    for station in STATIONS:
        for variable in VARIABLES:
            raw_col = f"{station}_{variable}"
            if raw_col not in df.columns:
                continue

            root_cause_series = classify_root_cause_vectorized(df_feat, station, variable)
            root_cause = root_cause_series.iloc[latest_idx]
            is_frozen = (root_cause == "frozen")
            is_dropout = pd.isna(latest_row[raw_col])

            confidence = 0.0
            is_anomaly = is_frozen or is_dropout

            if not is_anomaly and len(df_feat) >= SEQ_LEN:
                # LSTM-AE reconstruction error for just the latest window
                cols = get_raw_columns(STATIONS)
                mean, std = lstm_checkpoint["mean"], lstm_checkpoint["std"]
                window_vals = df[cols].values[-SEQ_LEN:].astype(np.float32)
                window_vals = pd.DataFrame(window_vals).ffill(limit=3).values
                norm_window = (window_vals - mean) / std
                norm_window = np.nan_to_num(norm_window, nan=0.0)

                with torch.no_grad():
                    x = torch.from_numpy(norm_window).unsqueeze(0)
                    recon = lstm_model(x)
                    err = ((recon - x) ** 2)[0, -1, :].numpy()

                var_idx = cols.index(raw_col)
                lstm_error = float(err[var_idx])

                # NOTE: robust_z needs a distribution to compare against --
                # in a true streaming deployment, pre-compute and freeze the
                # clean-data score distribution (mean/MAD) at calibration
                # time and reuse it here, rather than recomputing z against
                # only the current small buffer, which isn't representative
                threshold = FLAG_THRESHOLD_Z
                is_anomaly = lstm_error > threshold
                confidence = min(1.0, lstm_error / (threshold * 2))

            corrected = None
            if is_anomaly:
                corrected = suggest_correction(latest_row, station, variable)

            results.append(ScoreResult(
                station=station,
                variable=variable,
                value=None if pd.isna(latest_row[raw_col]) else float(latest_row[raw_col]),
                is_anomaly=bool(is_anomaly),
                confidence=float(confidence) if is_anomaly else 1.0 - float(confidence),
                root_cause=root_cause if is_anomaly else "normal",
                corrected_value=corrected,
            ))

            if is_anomaly:
                recent_flags.append({
                    "timestamp": reading.timestamp, "station": station,
                    "variable": variable, "root_cause": root_cause,
                })

    return results


@app.get("/health/{station}")
def station_health(station: str, window_hours: int = 168):
    """Sensor health status: rolling anomaly rate for this station over the
    last `window_hours` -- a station with a rising rate is degrading, even
    if no single reading looks catastrophic yet."""
    if station not in STATIONS:
        raise HTTPException(status_code=404, detail="Unknown station")

    cutoff = pd.Timestamp.now() - pd.Timedelta(hours=window_hours)
    station_flags = [f for f in recent_flags if f["station"] == station]

    total_readings = len(buffer)
    anomaly_count = len(station_flags)
    rate = anomaly_count / total_readings if total_readings else 0.0

    status = "healthy"
    if rate > 0.3:
        status = "degraded"
    elif rate > 0.1:
        status = "watch"

    return {
        "station": station,
        "status": status,
        "anomaly_rate": round(rate, 3),
        "flag_count": anomaly_count,
        "window_hours": window_hours,
    }


@app.get("/history/{station}")
def station_history(station: str, variable: str = "temp_c"):
    """Returns recent raw values for this station/variable, for the frontend
    to chart -- e.g. a time series with anomalies overlaid."""
    if station not in STATIONS:
        raise HTTPException(status_code=404, detail="Unknown station")

    col = f"{station}_{variable}"
    df = pd.DataFrame(list(buffer))
    if col not in df.columns:
        raise HTTPException(status_code=404, detail=f"No data for {col}")

    return {
        "station": station,
        "variable": variable,
        "timestamps": df["valid_time"].astype(str).tolist(),
        "values": df[col].tolist(),
    }


@app.get("/")
def root():
    return {"status": "SkyGuard AI backend running", "stations": STATIONS, "buffer_size": len(buffer)}