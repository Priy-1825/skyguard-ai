"""
Anomaly injection for SkyGuard AI.

Injects labeled synthetic anomalies into clean AWS data so you have ground
truth to evaluate detection models against. Run this BEFORE feature
engineering on the copy you intend to use for evaluation -- rolling features
need to be computed on the already-injected series to reflect the anomaly's
real effect on local statistics.

Anomaly types:
    spike       - single-sample extreme jump, recovers next step
    frozen      - value stuck flat for N consecutive hours
    drift       - slow linear bias accumulating over a window
    dropout     - missing/NaN run (communication failure)
    inconsistent- one variable jumps while others at same station stay normal
                  (a physically implausible combination -> tests multivariate check)

Usage:
    df = pd.read_csv("combined_stations_1990on.csv", parse_dates=["valid_time"])
    df_injected, labels = inject_anomalies(df, stations=range(1, 10), seed=42)
    df_injected.to_csv("injected.csv", index=False)
    labels.to_csv("anomaly_labels.csv", index=False)
"""

import pandas as pd
import numpy as np

VARIABLES = ["pressure_hpa", "temp_c", "rh_pct"]

# realistic magnitude ranges per variable, used to scale anomaly severity
TYPICAL_STD = {
    "pressure_hpa": 5.0,
    "temp_c": 5.0,
    "rh_pct": 15.0,
}


def _new_label_row(time_col_val, station, variable, anomaly_type, start_idx, end_idx, severity_std):
    return {
        "timestamp": time_col_val,
        "station": station,
        "variable": variable,
        "anomaly_type": anomaly_type,
        "start_idx": start_idx,
        "end_idx": end_idx,
        "severity_std": severity_std,  # injected magnitude in units of local std dev
    }


def inject_spikes(df, col, rng, n_events=50, magnitude_std=6.0):
    labels = []  # (start_idx, end_idx, severity_std)
    n = len(df)
    idxs = rng.choice(n, size=n_events, replace=False)
    std = df[col].std()
    for idx in idxs:
        sign = rng.choice([-1, 1])
        df.loc[idx, col] = df.loc[idx, col] + sign * magnitude_std * std
        labels.append((idx, idx, magnitude_std))
    return df, labels


def inject_frozen(df, col, rng, n_events=20, min_len=6, max_len=48):
    labels = []
    n = len(df)
    for _ in range(n_events):
        start = rng.integers(0, n - max_len)
        length = rng.integers(min_len, max_len)
        frozen_value = df.loc[start, col]
        df.loc[start:start + length, col] = frozen_value
        # severity for frozen = duration in hours (longer stuck = more severe)
        labels.append((start, start + length, float(length)))
    return df, labels


def inject_drift(df, col, rng, n_events=15, min_len=24, max_len=168, max_bias_std=4.0):
    labels = []
    n = len(df)
    std = df[col].std()
    for _ in range(n_events):
        start = rng.integers(0, n - max_len)
        length = rng.integers(min_len, max_len)
        bias = np.linspace(0, max_bias_std * std, length + 1)
        df.loc[start:start + length, col] = df.loc[start:start + length, col].values + bias
        labels.append((start, start + length, max_bias_std))
    return df, labels


def inject_dropout(df, col, rng, n_events=25, min_len=1, max_len=12):
    labels = []
    n = len(df)
    for _ in range(n_events):
        start = rng.integers(0, n - max_len)
        length = rng.integers(min_len, max_len)
        df.loc[start:start + length, col] = np.nan
        # severity for dropout = gap duration in hours
        labels.append((start, start + length, float(length)))
    return df, labels


def inject_inconsistent(df, station, rng, n_events=15, magnitude_std=7.0):
    """Perturb ONE variable at a station while leaving the others (and other
    stations) untouched -- tests whether the multivariate/cross-station
    consistency checks catch a physically implausible single-variable jump."""
    labels = []
    n = len(df)
    target_var = "temp_c"  # most physically constrained by pressure/humidity
    col = f"{station}_{target_var}"
    std = df[col].std()
    idxs = rng.choice(n, size=n_events, replace=False)
    for idx in idxs:
        sign = rng.choice([-1, 1])
        df.loc[idx, col] = df.loc[idx, col] + sign * magnitude_std * std
        labels.append((idx, idx, magnitude_std))
    return df, labels, target_var


def inject_anomalies(df, stations, time_col="valid_time", seed=42):
    df = df.copy().sort_values(time_col).reset_index(drop=True)
    rng = np.random.default_rng(seed)
    all_labels = []

    for station in stations:
        for variable in VARIABLES:
            col = f"{station}_{variable}"
            if col not in df.columns:
                continue

            df, spike_labels = inject_spikes(df, col, rng)
            for s, e, sev in spike_labels:
                all_labels.append(_new_label_row(df.loc[s, time_col], station, variable, "spike", s, e, sev))

            df, frozen_labels = inject_frozen(df, col, rng)
            for s, e, sev in frozen_labels:
                all_labels.append(_new_label_row(df.loc[s, time_col], station, variable, "frozen", s, e, sev))

            df, drift_labels = inject_drift(df, col, rng)
            for s, e, sev in drift_labels:
                all_labels.append(_new_label_row(df.loc[s, time_col], station, variable, "drift", s, e, sev))

            df, dropout_labels = inject_dropout(df, col, rng)
            for s, e, sev in dropout_labels:
                all_labels.append(_new_label_row(df.loc[s, time_col], station, variable, "dropout", s, e, sev))

        df, inconsistent_labels, target_var = inject_inconsistent(df, station, rng)
        for s, e, sev in inconsistent_labels:
            all_labels.append(_new_label_row(df.loc[s, time_col], station, target_var, "inconsistent", s, e, sev))

    labels_df = pd.DataFrame(all_labels)
    return df, labels_df


if __name__ == "__main__":
    df = pd.read_csv("combined_stations.csv", parse_dates=["valid_time"])
    stations = list(range(1, 10))
    df_injected, labels = inject_anomalies(df, stations, seed=42)
    df_injected.to_csv("injected.csv", index=False)
    labels.to_csv("anomaly_labels.csv", index=False)
    print(f"Injected {len(labels)} labeled anomalies across {len(stations)} stations")
    print(labels["anomaly_type"].value_counts())