"""
LSTM-Autoencoder for SkyGuard AI.

Learns normal temporal/diurnal behavior of raw (pressure, temp, rh) sequences
across all 9 stations, then flags timesteps where reconstruction error is
high -- this is what catches frozen sensors, drift, and diurnal-pattern
breaks that point-in-time statistical checks miss.

IMPORTANT: train this ONLY on clean (non-injected) data. It should never see
injected anomalies during training -- otherwise it learns to reconstruct
them as "normal" and you lose your ability to detect them.

Architecture: single-layer LSTM encoder -> latent vector -> single-layer LSTM
decoder. Kept deliberately small (64 hidden units) per the earlier
lightweight-vs-accuracy discussion -- this is the "keep it lean but keep the
LSTM" version, not the ESP32-tier version.

Usage:
    python lstm_autoencoder.py --mode train   # trains on clean data
    python lstm_autoencoder.py --mode score   # scores injected data using saved model
"""

import argparse
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

SEQ_LEN = 24  # hours; revisit based on your ACF/PACF result (24-48h typical)
HIDDEN_SIZE = 64
LATENT_SIZE = 32
BATCH_SIZE = 256
EPOCHS = 15
LEARNING_RATE = 1e-3


def get_raw_columns(stations, variables=("pressure_hpa", "temp_c", "rh_pct")):
    return [f"{s}_{v}" for s in stations for v in variables]


class SequenceDataset(Dataset):
    """Memory-efficient sliding windows: stores only the normalized array and
    computes window views on the fly, rather than materializing every window
    as a separate copy (which would be seq_len x larger in memory)."""

    def __init__(self, values, seq_len):
        self.values = values.astype(np.float32)
        self.seq_len = seq_len
        self.n_windows = len(values) - seq_len + 1

    def __len__(self):
        return max(0, self.n_windows)

    def __getitem__(self, idx):
        window = self.values[idx: idx + self.seq_len]
        return torch.from_numpy(window)


class LSTMAutoencoder(nn.Module):
    def __init__(self, n_features, hidden_size=HIDDEN_SIZE, latent_size=LATENT_SIZE, seq_len=SEQ_LEN):
        super().__init__()
        self.seq_len = seq_len
        self.encoder_lstm = nn.LSTM(n_features, hidden_size, batch_first=True)
        self.to_latent = nn.Linear(hidden_size, latent_size)
        self.from_latent = nn.Linear(latent_size, hidden_size)
        self.decoder_lstm = nn.LSTM(hidden_size, hidden_size, batch_first=True)
        self.output_layer = nn.Linear(hidden_size, n_features)

    def forward(self, x):
        # x: (batch, seq_len, n_features)
        _, (h_n, _) = self.encoder_lstm(x)
        latent = self.to_latent(h_n[-1])  # (batch, latent_size)

        decoder_input = self.from_latent(latent).unsqueeze(1).repeat(1, self.seq_len, 1)
        decoded, _ = self.decoder_lstm(decoder_input)
        reconstruction = self.output_layer(decoded)  # (batch, seq_len, n_features)
        return reconstruction


def normalize(train_values, *other_arrays):
    """Fit mean/std on training (clean) data only, apply to all arrays.
    Fitting normalization on clean data only avoids anomalies skewing the
    scale the model judges 'normal' against."""
    mean = np.nanmean(train_values, axis=0)
    std = np.nanstd(train_values, axis=0)
    std[std == 0] = 1.0

    def apply(arr):
        return (arr - mean) / std

    return (apply(train_values),) + tuple(apply(a) for a in other_arrays), mean, std


def train(clean_csv, stations, time_col="valid_time", model_out="lstm_ae.pt",
          seq_len=SEQ_LEN, epochs=EPOCHS, val_frac=0.1):
    df = pd.read_csv(clean_csv, parse_dates=[time_col])
    cols = get_raw_columns(stations)
    values = df[cols].values.astype(np.float32)

    # forward-fill small gaps, drop rows that still have NaN (real dropouts
    # too long to fill) -- the LSTM-AE needs contiguous sequences
    values = pd.DataFrame(values).ffill(limit=3).values
    valid_mask = ~np.isnan(values).any(axis=1)
    values = values[valid_mask]

    split = int(len(values) * (1 - val_frac))
    train_vals, val_vals = values[:split], values[split:]

    (train_norm, val_norm), mean, std = normalize(train_vals, val_vals)

    train_ds = SequenceDataset(train_norm, seq_len)
    val_ds = SequenceDataset(val_norm, seq_len)
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = LSTMAutoencoder(n_features=len(cols), seq_len=seq_len).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.MSELoss()

    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for batch in train_loader:
            batch = batch.to(device)
            optimizer.zero_grad()
            recon = model(batch)
            loss = criterion(recon, batch)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(batch)
        train_loss /= len(train_ds)

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for batch in val_loader:
                batch = batch.to(device)
                recon = model(batch)
                val_loss += criterion(recon, batch).item() * len(batch)
        val_loss /= max(1, len(val_ds))

        print(f"Epoch {epoch+1}/{epochs}  train_loss={train_loss:.5f}  val_loss={val_loss:.5f}")

    torch.save({
        "model_state": model.state_dict(),
        "n_features": len(cols),
        "seq_len": seq_len,
        "columns": cols,
        "mean": mean,
        "std": std,
    }, model_out)
    print(f"Saved model to {model_out}")


def score(injected_csv, stations, time_col="valid_time", model_path="lstm_ae.pt",
          out_csv="lstm_scores.csv"):
    """Computes per-timestep, per-feature reconstruction error on
    (possibly-anomalous) data using a trained model. Higher error = more
    anomalous. Output aligns each window's error to its LAST timestep, since
    at deployment time you only have data up to 'now', matching real-time use."""
    checkpoint = torch.load(model_path, weights_only=False)
    cols = checkpoint["columns"]
    seq_len = checkpoint["seq_len"]
    mean, std = checkpoint["mean"], checkpoint["std"]

    df = pd.read_csv(injected_csv, parse_dates=[time_col])
    values = df[cols].values.astype(np.float32)
    values = pd.DataFrame(values).ffill(limit=3).values
    norm_values = (values - mean) / std
    # NaNs beyond the ffill limit stay NaN -- replace with 0 post-normalization
    # so the model still runs; those rows should be flagged separately as
    # 'dropout' before this stage anyway (handled by your rule-based check)
    nan_mask = np.isnan(norm_values).any(axis=1)
    norm_values = np.nan_to_num(norm_values, nan=0.0)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = LSTMAutoencoder(n_features=checkpoint["n_features"], seq_len=seq_len).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    ds = SequenceDataset(norm_values, seq_len)
    loader = DataLoader(ds, batch_size=BATCH_SIZE, shuffle=False)

    all_errors = []
    with torch.no_grad():
        for batch in loader:
            batch = batch.to(device)
            recon = model(batch)
            # per-timestep, per-feature squared error, take last timestep of window
            err = ((recon - batch) ** 2)[:, -1, :].cpu().numpy()
            all_errors.append(err)

    errors = np.concatenate(all_errors, axis=0)  # (n_windows, n_features)

    # pad the first (seq_len - 1) rows, which have no completed window yet
    pad = np.full((seq_len - 1, errors.shape[1]), np.nan)
    errors_full = np.vstack([pad, errors])

    error_df = pd.DataFrame(errors_full, columns=[f"{c}_recon_error" for c in cols])
    error_df[time_col] = df[time_col].values
    error_df.loc[nan_mask, :] = np.nan  # don't score rows that were dropout-imputed

    error_df.to_csv(out_csv, index=False)
    print(f"Saved reconstruction errors to {out_csv}")
    return error_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["train", "score"], required=True)
    parser.add_argument("--clean_csv", default="combined_stations_1990on.csv")
    parser.add_argument("--injected_csv", default="injected.csv")
    parser.add_argument("--stations", default="1,2,3,4,5,6,7,8,9")
    parser.add_argument("--out", default="lstm_scores.csv",
                         help="Output CSV for --mode score. Use a distinct name per input "
                              "(e.g. lstm_scores_clean.csv vs lstm_scores_injected.csv) so "
                              "you don't overwrite one with the other.")
    args = parser.parse_args()

    stations = args.stations.split(",")

    if args.mode == "train":
        train(args.clean_csv, stations)
    else:
        score(args.injected_csv, stations, out_csv=args.out)