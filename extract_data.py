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

from sensor_render import (
    TRAIN_DIR,
    PEDESTRIAN_CATEGORIES,
    VEHICLE_CATEGORIES,
    actor_score,
    get_city_from_log,
    list_logs,
    load_annotations,
)

OUTPUT_FILE = Path(__file__).parent / "static" / "data" / "scenario_data.json"

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
    offset_h = CITY_UTC_OFFSET.get(city, 0)
    dt = datetime.fromtimestamp(first_timestamp_ns / 1e9, tz=timezone.utc) \
         + timedelta(hours=offset_h)
    h = dt.hour
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
    annotations_path = log_dir / "annotations.feather"
    if not annotations_path.exists():
        return None

    try:
        annotations = load_annotations(annotations_path)
    except Exception as exc:
        print(f"  Warning: could not load {annotations_path}: {exc}")
        return None

    timestamps = sorted(annotations["timestamp_ns"].unique())
    if not timestamps:
        return None

    city = get_city_from_log(log_dir)

    frame_scores: list[float] = []
    frame_vehicles: list[int] = []
    frame_peds: list[int] = []
    frame_cyclists: list[int] = []
    frame_actors: list[int] = []
    frame_distances: list[float] = []
    frame_close: list[int] = []
    all_volumes: list[float] = []
    all_lidar_pts: list[float] = []
    category_set: set[str] = set()

    for ts in timestamps:
        frame_ann = annotations[annotations["timestamp_ns"] == ts]
        frame_score = 0.0
        n_veh = n_ped = n_cyc = n_close = 0
        dists: list[float] = []

        for _, row in frame_ann.iterrows():
            category = str(row["category"])
            category_set.add(category)

            score, _ = actor_score(row)
            frame_score += score

            x, y, z = float(row["tx_m"]), float(row["ty_m"]), float(row["tz_m"])
            dist = math.sqrt(x * x + y * y + z * z)
            dists.append(dist)
            if dist < 10:
                n_close += 1

            vol = float(row["length_m"]) * float(row["width_m"]) * float(row["height_m"])
            all_volumes.append(vol)

            pts = float(row.get("num_interior_pts", 0))
            all_lidar_pts.append(pts)

            if category in VEHICLE_CATEGORIES:
                n_veh += 1
            elif category in PEDESTRIAN_CATEGORIES:
                n_ped += 1
            if category in CYCLIST_CATEGORIES:
                n_cyc += 1

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
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    logs = list_logs()
    if not logs:
        print(f"No logs found in TRAIN_DIR: {TRAIN_DIR}")
        return

    print(f"Found {len(logs)} logs in {TRAIN_DIR}")
    print("Extracting statistics (no video rendering) ...\n")

    results: list[dict] = []
    for i, log in enumerate(logs, 1):
        log_dir = Path(log["path"])
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

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nDone. Wrote {len(results)} records to:\n  {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
