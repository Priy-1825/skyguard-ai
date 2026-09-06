"""
Isolation Forest layer for SkyGuard AI.

Runs on the engineered feature matrix (rolling z-scores, ensemble deviations,
diff/rate-of-change, flat_run) from feature_engineering.py -- these are
already point-in-time descriptors, which is what tree-based models are good
at. This layer catches spikes and cross-station inconsistencies fast and
cheaply; the LSTM-AE handles the temporal-pattern anomalies (frozen, drift)
this layer is weak on.

Train ONLY on clean (non-injected) engineered features, same rule as the
LSTM-AE -- otherwise the model learns injected anomalies as "normal."

Usage:
    python isolation_forest_layer.py --mode train
    python isolation_forest_layer.py --mode score
"""

import argparse
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import IsolationForest

# feature suffixes to use per station/variable -- these are the columns
# feature_engineering.py produces that are most informative for point-in-time
# anomaly scoring (z-scores and rates of change), rather than raw values or
# rolling means/stds themselves
FEATURE_SUFFIXES = [
    "_z_short", "_z_day", "_z_week",
    "_diff_1h", "_diff_24h",
    "_flat_run",
    "_dev_from_ensemble", "_ensemble_z",
]


def select_feature_columns(df, stations, variables=("pressure_hpa", "temp_c", "rh_pct")):
    cols = []
    for s in stations:
        for v in variables:
            prefix = f"{s}_{v}"
            for suffix in FEATURE_SUFFIXES:
                col = f"{prefix}{suffix}"
                if col in df.columns:
                    cols.append(col)
    return cols


def train(features_csv, stations, model_out="iso_forest.joblib", contamination=0.01):
    df = pd.read_csv(features_csv)
    feature_cols = select_feature_columns(df, stations)

    X = df[feature_cols].values
    # rolling features have NaN in the warm-up window (first ~168h) -- drop
    # those rows for training, they're not real anomalies, just missing history
    valid_mask = ~np.isnan(X).any(axis=1)
    X_train = X[valid_mask]

    print(f"Training on {X_train.shape[0]} rows x {X_train.shape[1]} features")

    model = IsolationForest(
        n_estimators=200,
        contamination=contamination,  # expected anomaly rate; tune against your injection rate
        max_samples="auto",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train)

    joblib.dump({"model": model, "feature_cols": feature_cols}, model_out)
    print(f"Saved model to {model_out}")


def score(features_csv, model_path="iso_forest.joblib", out_csv="iso_forest_scores.csv"):
    bundle = joblib.load(model_path)
    model, feature_cols = bundle["model"], bundle["feature_cols"]

    df = pd.read_csv(features_csv)
    X = df[feature_cols].values
    valid_mask = ~np.isnan(X).any(axis=1)

    # decision_function: higher = more normal, lower/negative = more anomalous
    # score_samples is the raw version; we negate so higher = more anomalous,
    # matching the LSTM-AE convention (higher reconstruction error = more anomalous)
    raw_scores = np.full(len(df), np.nan)
    raw_scores[valid_mask] = -model.decision_function(X[valid_mask])

    predictions = np.full(len(df), np.nan)
    predictions[valid_mask] = (model.predict(X[valid_mask]) == -1).astype(int)  # 1 = anomaly

    out = pd.DataFrame({
        "iso_forest_score": raw_scores,
        "iso_forest_flag": predictions,
    })
    if "valid_time" in df.columns:
        out.insert(0, "valid_time", df["valid_time"])

    out.to_csv(out_csv, index=False)
    print(f"Saved Isolation Forest scores to {out_csv}")
    print(f"Flagged {int(np.nansum(predictions))} / {valid_mask.sum()} valid rows as anomalous")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["train", "score"], required=True)
    parser.add_argument("--clean_features_csv", default="features_clean.csv")
    parser.add_argument("--injected_features_csv", default="features_injected.csv")
    parser.add_argument("--stations", default="1,2,3,4,5,6,7,8,9")
    parser.add_argument("--out", default="iso_forest_scores.csv",
                         help="Output CSV for --mode score. Use a distinct name per input "
                              "so you don't overwrite the clean-data scores with the "
                              "injected-data scores or vice versa.")
    args = parser.parse_args()

    stations = args.stations.split(",")

    if args.mode == "train":
        train(args.clean_features_csv, stations)
    else:
        score(args.injected_features_csv, out_csv=args.out)