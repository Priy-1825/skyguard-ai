"""Correlation .py"""
import pandas as pd
import numpy as np


def suggest_corrections(df, flags, stations, time_col="valid_time"):
    """
    df: the (possibly anomalous) wide dataframe with <station>_<variable> columns
    flags: dataframe with columns [idx, station, variable]
    stations: full list of station ids, used to build the ensemble excluding
              the flagged station itself
    """
    if flags.empty:
        return pd.DataFrame()

    corrections_list = []
    
    # Pre-extract timestamps array once if present
    timestamps = df[time_col].values if time_col in df.columns else None

    # Group flags by (station, variable) to process thousands of rows in bulk
    for (station, variable), group in flags.groupby(["station", "variable"]):
        indices = group["idx"].astype(int).values
        orig_col = f"{station}_{variable}"

        # Determine target columns once per group instead of per row
        other_stations = [s for s in stations if s != station]
        other_cols = [f"{s}_{variable}" for s in other_stations if f"{s}_{variable}" in df.columns]

        if not other_cols:
            continue

        # Extract batch sub-dataframe for all flagged indices in this group at once
        sub_df = df.loc[indices, other_cols]

        # Vectorized row-wise median (axis=1) across healthy stations
        corrected_values = sub_df.median(axis=1).values
        n_available = sub_df.notna().sum(axis=1).values
        orig_values = df.loc[indices, orig_col].values if orig_col in df.columns else np.nan

        group_corrections = pd.DataFrame({
            "idx": indices,
            "timestamp": timestamps[indices] if timestamps is not None else None,
            "station": station,
            "variable": variable,
            "original_value": orig_values,
            "corrected_value": corrected_values,
            "n_stations_used": n_available,
        })
        corrections_list.append(group_corrections)

    if not corrections_list:
        return pd.DataFrame()

    # Combine results and sort back by original index order
    return pd.concat(corrections_list, ignore_index=True).sort_values("idx").reset_index(drop=True)


if __name__ == "__main__":
    df = pd.read_csv("features.csv", parse_dates=["valid_time"])
    labels = pd.read_csv("anomaly_labels.csv")

    # Vectorized range expansion replacing slow nested loops
    idx_list = []
    station_list = []
    var_list = []

    for _, r in labels.iterrows():
        start, end = int(r["start_idx"]), int(r["end_idx"])
        run_indices = np.arange(start, end + 1)
        idx_list.append(run_indices)
        station_list.append(np.full(len(run_indices), r["station"]))
        var_list.append(np.full(len(run_indices), r["variable"]))

    flags = pd.DataFrame({
        "idx": np.concatenate(idx_list),
        "station": np.concatenate(station_list),
        "variable": np.concatenate(var_list),
    })

    stations = list(range(1, 10))
    corrected = suggest_corrections(df, flags, stations)
    corrected.to_csv("corrected_values.csv", index=False)
    print(f"Suggested corrections for {len(corrected)} flagged points")
    print(corrected.head())