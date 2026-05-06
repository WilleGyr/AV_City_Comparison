#!/usr/bin/env python3
"""Scan all AV2 log directories and extract scenario statistics WITHOUT rendering video.

Reads annotations.feather from every log in TRAIN_DIR and computes per-log metrics.
Results are written to static/data/scenario_data.json for use by the graph builder.

Run once (takes a few minutes for large datasets):
    python extract_data.py
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

# Reuse the scoring + categorisation from the renderer so per-log stats here
# stay consistent with what the renderer writes into summary.json.
from sensor_render import (
    TRAIN_DIR,
    PEDESTRIAN_CATEGORIES,
    VEHICLE_CATEGORIES,
    actor_score,
    get_city_from_log,
    list_logs,
    load_annotations,
)

# Single output file the Flask graph endpoint reads from.
OUTPUT_FILE = Path(__file__).parent / "static" / "data" / "scenario_data.json"

# Two-wheelers grouped together — AV2 splits them across several labels.
CYCLIST_CATEGORIES = frozenset({
    "BICYCLE", "BICYCLIST", "MOTORCYCLE", "MOTORCYCLIST", "WHEELED_RIDER",
})

# Approximate UTC offsets per AV2 city code (ignores DST — close enough for binning)
CITY_UTC_OFFSET: dict[str, int] = {
    "PIT": -5, "WDC": -5, "MIA": -5, "DTW": -5,  # Eastern
    "ATX": -6,                                      # Central
    "PAO": -8,                                      # Pacific
}


def _time_of_day(first_timestamp_ns: int, city: str) -> str:
    # Convert the log's first sensor timestamp to local time, then bin
    # into a coarse label used as an X-axis option in the graph builder.
    offset_h = CITY_UTC_OFFSET.get(city, 0)
    # AV2 timestamps are nanoseconds since epoch.
    dt = datetime.fromtimestamp(first_timestamp_ns / 1e9, tz=timezone.utc) \
         + timedelta(hours=offset_h)
    h = dt.hour
    # Coarse buckets — fine enough for grouping, robust to DST drift.
    if 5 <= h < 9:
        return "Dawn"
    elif 9 <= h < 12:
        return "Morning"
    elif 12 <= h < 17:
        return "Afternoon"
    elif 17 <= h < 21:
        return "Evening"
    else:
        return "Night"


def _extract_log_stats(log_dir: Path) -> dict | None:
    # Stats-only pass: no image projection, no MP4 — annotations.feather
    # alone carries everything needed to score frames.
    annotations_path = log_dir / "annotations.feather"
    if not annotations_path.exists():
        # Some test logs ship without annotations; just skip them.
        return None

    try:
        annotations = load_annotations(annotations_path)
    except Exception as exc:
        # Don't abort the whole run for one bad log — log and move on.
        print(f"  Warning: could not load {annotations_path}: {exc}")
        return None

    # One frame per unique timestamp.
    timestamps = sorted(annotations["timestamp_ns"].unique())
    if not timestamps:
        return None

    city = get_city_from_log(log_dir)

    # Per-frame accumulators (averaged at the end).
    frame_scores: list[float] = []
    frame_vehicles: list[int] = []
    frame_peds: list[int] = []
    frame_cyclists: list[int] = []
    frame_actors: list[int] = []
    frame_distances: list[float] = []
    frame_close: list[int] = []
    # All-actor accumulators — averaged across the whole log, not per frame.
    all_volumes: list[float] = []
    all_lidar_pts: list[float] = []
    category_set: set[str] = set()

    # Walk one timestamp at a time: every cuboid contributes to that frame's totals.
    for ts in timestamps:
        frame_ann = annotations[annotations["timestamp_ns"] == ts]
        frame_score = 0.0
        n_veh = n_ped = n_cyc = n_close = 0
        dists: list[float] = []

        for _, row in frame_ann.iterrows():
            category = str(row["category"])
            category_set.add(category)

            # Same scoring function the renderer uses — keeps the two pipelines aligned.
            score, _ = actor_score(row)
            frame_score += score

            # Distance from ego — cuboid centres are already in ego frame.
            x, y, z = float(row["tx_m"]), float(row["ty_m"]), float(row["tz_m"])
            dist = math.sqrt(x * x + y * y + z * z)
            dists.append(dist)
            # 10 m is a rough "in the danger zone" threshold for close-range counts.
            if dist < 10:
                n_close += 1

            # Cuboid volume in m³ — useful as a "how big is the average actor" metric.
            vol = float(row["length_m"]) * float(row["width_m"]) * float(row["height_m"])
            all_volumes.append(vol)

            # LiDAR returns inside the cuboid — proxy for how well-resolved an actor is.
            pts = float(row.get("num_interior_pts", 0))
            all_lidar_pts.append(pts)

            # Vehicle and pedestrian sets are mutually exclusive; cyclists can overlap.
            if category in VEHICLE_CATEGORIES:
                n_veh += 1
            elif category in PEDESTRIAN_CATEGORIES:
                n_ped += 1
            if category in CYCLIST_CATEGORIES:
                n_cyc += 1

        # Flush this frame's totals into the per-frame accumulators.
        frame_scores.append(frame_score)
        frame_vehicles.append(n_veh)
        frame_peds.append(n_ped)
        frame_cyclists.append(n_cyc)
        frame_actors.append(len(frame_ann))
        frame_close.append(n_close)
        if dists:
            frame_distances.append(float(np.mean(dists)))

    if not frame_scores:
        return None

    # One row per log: aggregates that the graph builder groups by city / time of day.
    # Rounding keeps the JSON small and human-readable.
    return {
        "log_id": log_dir.name,
        "city": city,
        "time_of_day": _time_of_day(int(timestamps[0]), city),
        "avg_complexity": round(float(np.mean(frame_scores)), 3),
        "max_complexity": round(float(np.max(frame_scores)), 3),
        "min_complexity": round(float(np.min(frame_scores)), 3),
        "complexity_std": round(float(np.std(frame_scores)), 3),
        "vehicle_count": round(float(np.mean(frame_vehicles)), 2),
        "pedestrian_count": round(float(np.mean(frame_peds)), 2),
        "cyclist_count": round(float(np.mean(frame_cyclists)), 2),
        "actor_density": round(float(np.mean(frame_actors)), 2),
        "close_object_count": round(float(np.mean(frame_close)), 2),
        "avg_object_distance": round(float(np.mean(frame_distances)) if frame_distances else 0.0, 2),
        "avg_object_size": round(float(np.mean(all_volumes)) if all_volumes else 0.0, 3),
        "lidar_density": round(float(np.mean(all_lidar_pts)) if all_lidar_pts else 0.0, 2),
        "num_unique_categories": len(category_set),
        "num_frames": int(len(timestamps)),
    }


def main() -> None:
    # Make sure static/data/ exists before we try to write into it.
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    logs = list_logs()
    if not logs:
        print(f"No logs found in TRAIN_DIR: {TRAIN_DIR}")
        return

    print(f"Found {len(logs)} logs in {TRAIN_DIR}")
    print("Extracting statistics (no video rendering) ...\n")

    # Process logs serially — disk I/O on the .feather files dominates,
    # so parallelising wouldn't help much without a reader pool.
    results: list[dict] = []
    for i, log in enumerate(logs, 1):
        log_dir = Path(log["path"])
        # Progress line is printed before stats so a long-running log is visible.
        print(f"[{i:>4}/{len(logs)}] {log['city']:<8}  {log['id'][:16]}…", end="  ", flush=True)
        stats = _extract_log_stats(log_dir)
        if stats:
            results.append(stats)
            print(f"avg_complexity={stats['avg_complexity']:.2f}  "
                  f"vehicles={stats['vehicle_count']:.1f}  "
                  f"peds={stats['pedestrian_count']:.1f}  "
                  f"time={stats['time_of_day']}")
        else:
            print("skipped (no annotations)")

    # Single dump at the end — partial files would confuse the graph endpoint.
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nDone. Wrote {len(results)} records to:\n  {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
