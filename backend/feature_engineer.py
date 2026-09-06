"""
Feature engineering for SkyGuard AI.

Computes multi-timescale rolling features per station per variable:
    - 3h, 24h, 168h (7-day) rolling mean, std, z-score, rate-of-change
    - lag features (t-1h, t-24h)
    - cross-station agreement features (deviation from ensemble mean)

All rolling windows are causal (past-only) since this must match real-time
deployment where future values aren't available.

PERFORMANCE NOTE: at ~300K+ rows x 9 stations, assigning ~150+ new columns
one at a time (df[col] = ...) causes pandas to repeatedly fragment and
reallocate the whole dataframe -- effectively O(n^2) and slow/freezing at
this scale. This version instead accumulates every new column in a plain
dict and does a single pd.concat at the end.

Usage:
    df = pd.read_csv("combined_stations_1990on.csv", parse_dates=["valid_time"])
    df_feat = engineer_all_features(df, stations=range(1, 10))
    df_feat.to_csv("features.csv", index=False)
"""

import pandas as pd
import numpy as np

WINDOWS_HOURS = {
    "short": 3,     # spikes / frozen values
    "day": 24,      # diurnal cycle
    "week": 168,    # synoptic-scale trend / drift
}

VARIABLES = ["pressure_hpa", "temp_c", "rh_pct"]


def build_rolling_features(df, station, variable):
    """Returns a dict of {col_name: series} for one station/variable -- does
    NOT write into df."""
    col = f"{station}_{variable}"
    prefix = f"{station}_{variable}"
    out = {}
    series = df[col]

    for window_name, hours in WINDOWS_HOURS.items():
        roll = series.rolling(window=hours, min_periods=max(2, hours // 2))
        mean = roll.mean()
        std = roll.std()
        safe_std = std.replace(0, np.nan)
        z = ((series - mean) / safe_std).clip(-10, 10)

        out[f"{prefix}_mean_{window_name}"] = mean
        out[f"{prefix}_std_{window_name}"] = std
        out[f"{prefix}_z_{window_name}"] = z

    out[f"{prefix}_diff_1h"] = series.diff(1)
    out[f"{prefix}_diff_24h"] = series - series.shift(24)
    out[f"{prefix}_lag_1h"] = series.shift(1)
    out[f"{prefix}_lag_24h"] = series.shift(24)

    diff = series.diff()
    out[f"{prefix}_flat_run"] = (
        diff.eq(0).astype(int).groupby(diff.ne(0).cumsum()).cumsum()
    )

    return out


def build_cross_station_features(df, stations, variable):
    """How far each station deviates from the 9-station ensemble mean at each
    timestamp. Returns a dict of {col_name: series} -- does NOT write into df."""
    cols = [f"{s}_{variable}" for s in stations if f"{s}_{variable}" in df.columns]
    sub = df[cols]
    ensemble_mean = sub.mean(axis=1)
    ensemble_std = sub.std(axis=1)
    safe_std = ensemble_std.replace(0, np.nan)

    out = {}
    for s in stations:
        col = f"{s}_{variable}"
        if col not in df.columns:
            continue
        dev = df[col] - ensemble_mean
        out[f"{s}_{variable}_dev_from_ensemble"] = dev
        out[f"{s}_{variable}_ensemble_z"] = (dev / safe_std).clip(-10, 10)

    return out


def build_temporal_features(df, time_col="valid_time"):
    dt = df[time_col]
    hour = dt.dt.hour
    day_of_year = dt.dt.dayofyear

    return {
        "hour_sin": np.sin(2 * np.pi * hour / 24),
        "hour_cos": np.cos(2 * np.pi * hour / 24),
        "doy_sin": np.sin(2 * np.pi * day_of_year / 365.25),
        "doy_cos": np.cos(2 * np.pi * day_of_year / 365.25),
    }


def engineer_all_features(df, stations, time_col="valid_time", dtype="float32"):
    df = df.sort_values(time_col).reset_index(drop=True)

    new_columns = {}

    for station in stations:
        for variable in VARIABLES:
            col = f"{station}_{variable}"
            if col not in df.columns:
                continue
            new_columns.update(build_rolling_features(df, station, variable))

    for variable in VARIABLES:
        new_columns.update(build_cross_station_features(df, stations, variable))

    new_columns.update(build_temporal_features(df, time_col))

    # IMPORTANT: pd.DataFrame(dict_of_series) does an internal reindex/align
    # pass per column that can blow up memory well beyond the data's actual
    # size at this many columns/rows. Building each Series individually and
    # concatenating them (all sharing df's index already, so no realignment
    # needed) is far cheaper. Downcasting to float32 roughly halves memory
    # too -- fine here since these are anomaly-detection features, not
    # values you need full float64 precision on.
    series_list = [s.astype(dtype).rename(name) for name, s in new_columns.items()]
    features_df = pd.concat(series_list, axis=1)
    result = pd.concat([df, features_df], axis=1)

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input CSV (e.g. combined_stations.csv or injected.csv)")
    parser.add_argument("--output", required=True, help="Output CSV path for engineered features")
    parser.add_argument("--stations", default="1,2,3,4,5,6,7,8,9")
    args = parser.parse_args()

    stations = args.stations.split(",")
    df = pd.read_csv(args.input, parse_dates=["valid_time"])
    df_feat = engineer_all_features(df, stations)
    df_feat.to_csv(args.output, index=False)
    print(f"Feature matrix: {df_feat.shape[0]} rows, {df_feat.shape[1]} columns")
    print(f"Saved to {args.output}")


def check_cross_station_correlation(df, stations, variable="temp_c"):
    """Sanity check before modeling: confirms stations are correlated enough
    for cross-station consistency features to be meaningful. Run this on the
    INJECTED data to also see whether injected anomalies visibly break
    correlation (they should, for spike/frozen/drift/inconsistent types)."""
    cols = [f"{s}_{variable}" for s in stations if f"{s}_{variable}" in df.columns]
    corr = df[cols].corr()
    print(f"\nCross-station correlation ({variable}):")
    print(corr.round(3))
    print(f"\nMean pairwise correlation: {corr.values[np.triu_indices(len(cols), k=1)].mean():.3f}")
    return corr