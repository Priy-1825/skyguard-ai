"""
Evaluation for SkyGuard AI.

Compares ensemble flags.csv against your injected ground truth
(anomaly_labels.csv) and reports precision/recall/F1 -- both overall and
broken down PER anomaly type, since overall accuracy hides whether you're
actually catching frozen/drift anomalies or just spikes.

Also reports root-cause classification accuracy: among correctly-flagged
points, what fraction did the rule-based classifier assign the correct type.

Usage:
    python evaluate.py --flags flags.csv --labels anomaly_labels.csv
"""

import argparse
import pandas as pd


def expand_labels_to_points(labels_df):
    """Expand each labeled anomaly run (start_idx..end_idx) into one row per
    affected timestamp, so it can be matched 1:1 against flags."""
    rows = []
    for _, r in labels_df.iterrows():
        for idx in range(int(r["start_idx"]), int(r["end_idx"]) + 1):
            rows.append({
                "idx": idx,
                "station": str(r["station"]),
                "variable": r["variable"],
                "anomaly_type": r["anomaly_type"],
            })
    return pd.DataFrame(rows)


def evaluate(flags_df, labels_df):
    flags_df = flags_df.copy()
    flags_df["station"] = flags_df["station"].astype(str)

    true_points = expand_labels_to_points(labels_df)
    true_points["station"] = true_points["station"].astype(str)

    key_cols = ["idx", "station", "variable"]
    flags_keyed = flags_df.set_index(key_cols)
    true_keyed = true_points.set_index(key_cols)

    flagged_set = set(flags_keyed.index)
    true_set = set(true_keyed.index)

    tp_keys = flagged_set & true_set
    fp_keys = flagged_set - true_set
    fn_keys = true_set - flagged_set

    tp, fp, fn = len(tp_keys), len(fp_keys), len(fn_keys)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print("=== Overall ===")
    print(f"TP={tp}  FP={fp}  FN={fn}")
    print(f"Precision={precision:.3f}  Recall={recall:.3f}  F1={f1:.3f}")

    # per anomaly-type recall: of all true points of this type, how many were flagged
    print("\n=== Per anomaly type (recall) ===")
    per_type_recall = {}
    for anomaly_type, group in true_points.groupby("anomaly_type"):
        type_keys = set(group.set_index(key_cols).index)
        type_tp = len(type_keys & flagged_set)
        type_recall = type_tp / len(type_keys) if len(type_keys) else 0.0
        per_type_recall[anomaly_type] = type_recall
        print(f"{anomaly_type:15s} recall={type_recall:.3f}  ({type_tp}/{len(type_keys)})")

    # root-cause classification accuracy on true positives
    print("\n=== Root-cause classification accuracy (on true positives) ===")
    tp_df = flags_keyed.loc[list(tp_keys)].reset_index()
    tp_df = tp_df.merge(
        true_points, on=key_cols, how="left", suffixes=("", "_true")
    )
    if len(tp_df):
        correct = (tp_df["root_cause"] == tp_df["anomaly_type"]).sum()
        print(f"Accuracy: {correct}/{len(tp_df)} = {correct/len(tp_df):.3f}")
        print("\nConfusion (predicted root_cause vs true anomaly_type):")
        print(pd.crosstab(tp_df["anomaly_type"], tp_df["root_cause"]))
    else:
        print("No true positives to evaluate root-cause accuracy on.")

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "per_type_recall": per_type_recall,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--flags", default="flags.csv")
    parser.add_argument("--labels", default="anomaly_labels.csv")
    args = parser.parse_args()

    flags_df = pd.read_csv(args.flags)
    labels_df = pd.read_csv(args.labels)
    evaluate(flags_df, labels_df)