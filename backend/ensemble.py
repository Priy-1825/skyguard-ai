"""
Ensemble combiner for SkyGuard AI.

Merges the LSTM-AE's per-(station,variable) reconstruction error with the
Isolation Forest's per-row anomaly score into a single combined confidence
score per (timestamp, station, variable), plus a rule-based root-cause label
(spike / frozen / drift / dropout / inconsistent).

Scoring approach: robust z-score (median/MAD, not mean/std -- resistant to
the anomalies themselves skewing the baseline) on each signal independently,
then a weighted combination. Weights default to 0.6 LSTM / 0.4 IsoForest --
the LSTM is the stronger signal for temporal anomalies (frozen, drift), the
IsoForest catches point-in-time/cross-station ones (spike, inconsistent) that
the LSTM alone under-weights since it's judged over a whole window.

Root-cause classification is a first-pass RULE-BASED layer using features
you already computed (flat_run, diff_1h, ensemble_z) -- not a trained
classifier. Treat it as a reasonable starting heuristic; once you have
enough flagged/labeled examples, a small trained multiclass model on top of
these same features would likely do better.

Usage:
    python ensemble.py --lstm_scores lstm_scores.csv --iso_scores iso_forest_scores.csv \
        --features features_injected.csv --stations 1,2,3,4,5,6,7,8,9 --out flags.csv
"""

import argparse
import numpy as np
import pandas as pd

VARIABLES = ["pressure_hpa", "temp_c", "rh_pct"]

LSTM_WEIGHT = 0.6
ISO_WEIGHT = 0.4
FLAG_THRESHOLD_Z = 3.0  # combined robust z-score above which a point is flagged

FROZEN_FLAT_RUN_THRESHOLD = 6       # hours stuck flat
DRIFT_WEEK_Z_THRESHOLD = 3.0        # sustained deviation over the week window
INCONSISTENT_ENSEMBLE_Z_THRESHOLD = 4.0


def robust_z(series):
    """Median/MAD-based z-score -- resistant to anomalies themselves
    skewing the mean/std baseline, unlike a standard z-score."""
    median = series.median()
    mad = (series - median).abs().median()
    mad_scaled = mad * 1.4826  # scale factor so MAD approximates std for normal data
    if mad_scaled == 0 or np.isnan(mad_scaled):
        return pd.Series(0.0, index=series.index)
    return (series - median) / mad_scaled


def classify_root_cause(feat_row, station, variable):
    """Rule-based root-cause label using engineered features for a single
    (station, variable) at one timestamp."""
    prefix = f"{station}_{variable}"

    flat_run = feat_row.get(f"{prefix}_flat_run", 0)
    if pd.notna(flat_run) and flat_run >= FROZEN_FLAT_RUN_THRESHOLD:
        return "frozen"

    raw_value = feat_row.get(prefix, None)
    if raw_value is not None and pd.isna(raw_value):
        return "dropout"

    z_week = feat_row.get(f"{prefix}_z_week", 0)
    diff_1h = feat_row.get(f"{prefix}_diff_1h", 0)
    if pd.notna(z_week) and abs(z_week) > DRIFT_WEEK_Z_THRESHOLD and pd.notna(diff_1h) and abs(diff_1h) < 2:
        return "drift"

    z_short = feat_row.get(f"{prefix}_z_short", 0)
    if pd.notna(z_short) and abs(z_short) > 5 and pd.notna(diff_1h) and abs(diff_1h) > 3:
        return "spike"

    ensemble_z = feat_row.get(f"{prefix}_ensemble_z", 0)
    if pd.notna(ensemble_z) and abs(ensemble_z) > INCONSISTENT_ENSEMBLE_Z_THRESHOLD:
        return "inconsistent"

    return "unknown"


def classify_root_cause_vectorized(feat_df, station, variable):
    """Vectorized version of the root-cause rules -- computes a label for
    EVERY row at once using boolean masks, instead of looping row-by-row with
    .iloc (which is what made this slow at real dataset scale: hundreds of
    thousands of individual row lookups across a 400+ column dataframe).
    Returns a pandas Series of labels aligned to feat_df's index."""
    prefix = f"{station}_{variable}"

    def col(name, default=0.0):
        c = f"{prefix}{name}"
        return feat_df[c] if c in feat_df.columns else pd.Series(default, index=feat_df.index)

    flat_run = col("_flat_run")
    raw_is_nan = feat_df[prefix].isna() if prefix in feat_df.columns else pd.Series(False, index=feat_df.index)
    z_week = col("_z_week")
    diff_1h = col("_diff_1h")
    z_short = col("_z_short")
    ensemble_z = col("_ensemble_z")

    is_frozen = flat_run.fillna(0) >= FROZEN_FLAT_RUN_THRESHOLD
    is_dropout = raw_is_nan
    is_drift = (z_week.abs() > DRIFT_WEEK_Z_THRESHOLD) & (diff_1h.abs() < 2)
    is_spike = (z_short.abs() > 5) & (diff_1h.abs() > 3)
    is_inconsistent = ensemble_z.abs() > INCONSISTENT_ENSEMBLE_Z_THRESHOLD

    # priority order matches the original rule order: frozen > dropout > drift > spike > inconsistent
    labels = pd.Series("unknown", index=feat_df.index)
    labels[is_inconsistent] = "inconsistent"
    labels[is_spike] = "spike"
    labels[is_drift] = "drift"
    labels[is_dropout] = "dropout"
    labels[is_frozen] = "frozen"

    return labels


def calibrate_threshold(lstm_clean_path, iso_clean_path, stations, variables=VARIABLES,
                         time_col="valid_time", lstm_weight=LSTM_WEIGHT, iso_weight=ISO_WEIGHT,
                         percentile=99.0):
    """Determines the flag threshold empirically from CLEAN (non-injected)
    data's own score distribution, instead of assuming a fixed z-value means
    the same thing on a skewed score distribution as it would on a normal
    one. LSTM reconstruction error is >=0 and right-skewed (it's a squared-
    error measure), so 'z > 3.0' does NOT mean 'top ~0.1%' the way it would
    for a truly Gaussian quantity -- it can flag a much larger, non-rare
    fraction of ordinary points. Setting the threshold at, say, the 99th
    percentile of the CLEAN data's own combined score directly targets
    'rarer than 99% of known-normal readings', regardless of the score's
    actual shape."""
    lstm_clean = pd.read_csv(lstm_clean_path, parse_dates=[time_col])
    iso_clean = pd.read_csv(iso_clean_path, parse_dates=[time_col])

    iso_z_clean = robust_z(iso_clean["iso_forest_score"])

    all_combined = []
    for station in stations:
        for variable in variables:
            lstm_col = f"{station}_{variable}_recon_error"
            if lstm_col not in lstm_clean.columns:
                continue
            lstm_z_clean = robust_z(lstm_clean[lstm_col])
            combined = lstm_weight * lstm_z_clean + iso_weight * iso_z_clean
            all_combined.append(combined)

    all_combined = pd.concat(all_combined, ignore_index=True)
    threshold = np.nanpercentile(all_combined, percentile)
    print(f"Calibrated threshold (percentile={percentile}): {threshold:.3f} "
          f"(fixed default was {FLAG_THRESHOLD_Z})")
    return threshold


def build_ensemble(lstm_scores_path, iso_scores_path, features_path, stations,
                    time_col="valid_time", variables=VARIABLES,
                    lstm_weight=LSTM_WEIGHT, iso_weight=ISO_WEIGHT,
                    flag_threshold=FLAG_THRESHOLD_Z):
    lstm_df = pd.read_csv(lstm_scores_path, parse_dates=[time_col])
    iso_df = pd.read_csv(iso_scores_path, parse_dates=[time_col])
    feat_df = pd.read_csv(features_path, parse_dates=[time_col])

    n = len(feat_df)
    iso_z = robust_z(iso_df["iso_forest_score"])

    all_frames = []

    for station in stations:
        for variable in variables:
            lstm_col = f"{station}_{variable}_recon_error"
            raw_col = f"{station}_{variable}"
            if lstm_col not in lstm_df.columns:
                continue

            root_cause_series = classify_root_cause_vectorized(feat_df, station, variable)

            # dropout: rule-based, bypasses the score entirely (see note above
            # build_ensemble in the module docstring -- neither model can see
            # a NaN, so this can't be threshold-based)
            dropout_mask = feat_df[raw_col].isna() if raw_col in feat_df.columns else pd.Series(False, index=feat_df.index)

            lstm_z = robust_z(lstm_df[lstm_col])
            combined_z = lstm_weight * lstm_z + iso_weight * iso_z
            confidence = 1 / (1 + np.exp(-(combined_z - flag_threshold)))

            score_flag_mask = (combined_z > flag_threshold) & (~dropout_mask)

            var_flags = pd.DataFrame({
                "idx": feat_df.index,
                "timestamp": feat_df[time_col] if time_col in feat_df.columns else pd.NaT,
                "station": station,
                "variable": variable,
                "combined_z": combined_z,
                "confidence": confidence,
                "root_cause": root_cause_series,
            })

            dropout_rows = var_flags.loc[dropout_mask].copy()
            dropout_rows["confidence"] = 1.0
            dropout_rows["combined_z"] = np.nan
            dropout_rows["root_cause"] = "dropout"

            scored_rows = var_flags.loc[score_flag_mask]

            all_frames.append(dropout_rows)
            all_frames.append(scored_rows)

    flags_df = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame()
    return flags_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lstm_scores", default="lstm_scores_injected.csv")
    parser.add_argument("--iso_scores", default="iso_forest_scores_injected.csv")
    parser.add_argument("--features", default="features_injected.csv")
    parser.add_argument("--stations", default="1,2,3,4,5,6,7,8,9")
    parser.add_argument("--out", default="flags.csv")
    parser.add_argument("--lstm_scores_clean", default=None,
                         help="LSTM scores computed on CLEAN data. If given (along with "
                              "--iso_scores_clean), the flag threshold is calibrated from "
                              "the clean score distribution instead of using the fixed "
                              "default -- strongly recommended, see calibrate_threshold().")
    parser.add_argument("--iso_scores_clean", default=None)
    parser.add_argument("--percentile", type=float, default=99.0,
                         help="Percentile of the clean score distribution to flag above. "
                              "Higher = fewer, more confident flags (less noise, more misses).")
    args = parser.parse_args()

    stations = args.stations.split(",")

    if args.lstm_scores_clean and args.iso_scores_clean:
        threshold = calibrate_threshold(args.lstm_scores_clean, args.iso_scores_clean,
                                         stations, percentile=args.percentile)
    else:
        threshold = FLAG_THRESHOLD_Z
        print(f"WARNING: no clean-data scores given, using fixed threshold={threshold}. "
              f"This is what produced a 4.6% precision run -- pass --lstm_scores_clean "
              f"and --iso_scores_clean to calibrate properly.")

    flags_df = build_ensemble(args.lstm_scores, args.iso_scores, args.features, stations,
                               flag_threshold=threshold)
    flags_df.to_csv(args.out, index=False)
    print(f"Flagged {len(flags_df)} (station, variable, timestamp) anomalies")
    print(flags_df["root_cause"].value_counts())