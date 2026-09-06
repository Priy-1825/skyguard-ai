"""Raw Data to combined.csv"""
import glob
import os
import re
import pandas as pd
import numpy as np

# ---- CONFIG: edit these to match your actual filenames/folders ----
DATA_DIR = "rawdata"
STATIONS = ["1", "2" , "3" , "4" , "5" , "6" , "7" , "8" , "9"]

PRESSURE_FILE_PATTERN = os.path.join(DATA_DIR, "{station}_pressure_data.csv")
TEMP_DEWPOINT_FILE_PATTERN = os.path.join(DATA_DIR, "{station}_temperature_data.csv")

# Column names as they appear in your raw CSVs — change if different
TIME_COL = "valid_time"          # or "valid_time" for some CDS exports
PRESSURE_COL = "sp"        # surface pressure
TEMP_COL = "t2m"           # 2m temperature
DEWPOINT_COL = "d2m"       # 2m dewpoint temperature

# Units in your raw files — CDS ERA5(-Land) defaults to Kelvin and Pa
PRESSURE_IN_PA = True      # True if pressure column is in Pascals -> converts to hPa
TEMP_IN_KELVIN = True      # True if temp/dewpoint are in Kelvin -> converts to Celsius


def to_celsius(series_kelvin):
    return series_kelvin - 273.15


def to_hpa(series_pa):
    return series_pa / 100.0


def relative_humidity_magnus(temp_c, dewpoint_c):
    """Magnus-Tetens approximation. temp_c and dewpoint_c in Celsius."""
    a, b = 17.625, 243.04
    numerator = np.exp((a * dewpoint_c) / (b + dewpoint_c))
    denominator = np.exp((a * temp_c) / (b + temp_c))
    rh = 100.0 * (numerator / denominator)
    return rh.clip(0, 100)  # guard against numerical overshoot


def load_station(station):
    # --- pressure file ---
    p_path = PRESSURE_FILE_PATTERN.format(station=station)
    p_df = pd.read_csv(p_path)
    p_df[TIME_COL] = pd.to_datetime(p_df[TIME_COL])
    pressure = to_hpa(p_df[PRESSURE_COL]) if PRESSURE_IN_PA else p_df[PRESSURE_COL]

    # --- temp/dewpoint file ---
    t_path = TEMP_DEWPOINT_FILE_PATTERN.format(station=station)
    t_df = pd.read_csv(t_path)
    t_df[TIME_COL] = pd.to_datetime(t_df[TIME_COL])
    temp_c = to_celsius(t_df[TEMP_COL]) if TEMP_IN_KELVIN else t_df[TEMP_COL]
    dew_c = to_celsius(t_df[DEWPOINT_COL]) if TEMP_IN_KELVIN else t_df[DEWPOINT_COL]
    rh = relative_humidity_magnus(temp_c, dew_c)

    merged = pd.DataFrame({
        TIME_COL: t_df[TIME_COL],
        f"{station}_temp_c": temp_c,
        f"{station}_rh_pct": rh,
    })

    p_series = pd.DataFrame({TIME_COL: p_df[TIME_COL], f"{station}_pressure_hpa": pressure})

    merged = merged.merge(p_series, on=TIME_COL, how="outer")
    return merged.sort_values(TIME_COL)


def main():
    combined = None
    for station in STATIONS:
        print(f"Loading station: {station}")
        station_df = load_station(station)
        combined = station_df if combined is None else combined.merge(station_df, on=TIME_COL, how="outer")

    combined = combined.sort_values(TIME_COL).reset_index(drop=True)

    # reorder columns so it's time, then pressure/temp/rh grouped per station
    ordered_cols = [TIME_COL]
    for station in STATIONS:
        ordered_cols += [f"{station}_pressure_hpa", f"{station}_temp_c", f"{station}_rh_pct"]
    combined = combined[ordered_cols]

    out_path = "combined_stations.csv"
    combined.to_csv(out_path, index=False)
    print(f"\nSaved: {out_path}")
    print(f"Rows: {len(combined)}, Columns: {len(combined.columns)}")
    print(combined.head())


if __name__ == "__main__":
    main()

