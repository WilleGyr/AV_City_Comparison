from __future__ import annotations

from pathlib import Path
import math
import csv
import statistics
from collections import defaultdict
from itertools import combinations

from av2.datasets.motion_forecasting import scenario_serialization


# =========================
# Config
# =========================
PROJECT_ROOT = Path(__file__).resolve().parent
DATASET_ROOT = PROJECT_ROOT / "datasets"
SPLIT = "val"                  # "train", "val", or "test"
OUTPUT_CSV = PROJECT_ROOT / "av2_scenario_summary.csv"
MAX_SCENARIOS = 50             # set to None for all scenarios
INTERACTION_DISTANCE_M = 5.0
USE_ONLY_VEHICLE_INTERACTIONS = False


# =========================
# File discovery
# =========================
def get_scenario_files(split_dir: Path) -> list[Path]:
    return sorted(split_dir.rglob("scenario_*.parquet"))


# =========================
# Type helpers
# =========================
def object_type_str(track) -> str:
    return str(track.object_type)


def is_vehicle(track) -> bool:
    return "VEHICLE" in object_type_str(track)


def is_pedestrian(track) -> bool:
    return "PEDESTRIAN" in object_type_str(track)


# =========================
# Speed helpers
# =========================
def compute_speed_mps(state) -> float | None:
    if getattr(state, "velocity", None) is None:
        return None

    vx, vy = state.velocity
    if vx is None or vy is None:
        return None

    return math.hypot(vx, vy)


# =========================
# Interaction helpers
# =========================
def build_actor_positions_by_timestep(scenario) -> dict[int, list[tuple[str, str, float, float]]]:
    by_time = defaultdict(list)

    for track in scenario.tracks:
        track_id = str(track.track_id)
        ttype = object_type_str(track)

        for state in track.object_states:
            if getattr(state, "position", None) is None:
                continue

            timestep = int(state.timestep)
            x, y = float(state.position[0]), float(state.position[1])
            by_time[timestep].append((track_id, ttype, x, y))

    return by_time


def count_interactions(
    scenario,
    distance_threshold: float = 5.0,
    vehicle_only: bool = False,
) -> int:
    by_time = build_actor_positions_by_timestep(scenario)
    interacting_pairs = set()

    for actors in by_time.values():
        for a, b in combinations(actors, 2):
            track_id_a, type_a, xa, ya = a
            track_id_b, type_b, xb, yb = b

            if vehicle_only and ("VEHICLE" not in type_a or "VEHICLE" not in type_b):
                continue

            dist = math.hypot(xa - xb, ya - yb)
            if dist <= distance_threshold:
                interacting_pairs.add(tuple(sorted((track_id_a, track_id_b))))

    return len(interacting_pairs)


# =========================
# Scenario summary
# =========================
def summarize_scenario(scenario) -> dict:
    vehicle_count = 0
    pedestrian_count = 0
    vehicle_speeds = []
    unique_object_types = set()

    for track in scenario.tracks:
        ttype = object_type_str(track)
        unique_object_types.add(ttype)

        if is_vehicle(track):
            vehicle_count += 1
            for state in track.object_states:
                speed = compute_speed_mps(state)
                if speed is not None:
                    vehicle_speeds.append(speed)

        elif is_pedestrian(track):
            pedestrian_count += 1

    avg_vehicle_speed = sum(vehicle_speeds) / len(vehicle_speeds) if vehicle_speeds else 0.0
    speed_std = statistics.pstdev(vehicle_speeds) if len(vehicle_speeds) > 1 else 0.0

    interaction_count = count_interactions(
        scenario,
        distance_threshold=INTERACTION_DISTANCE_M,
        vehicle_only=USE_ONLY_VEHICLE_INTERACTIONS,
    )

    diversity_count = len(unique_object_types)

    return {
        "scenario_id": str(scenario.scenario_id),
        "city": str(scenario.city_name),
        "vehicle_count": vehicle_count,
        "pedestrian_count": pedestrian_count,
        "avg_vehicle_speed_mps": round(avg_vehicle_speed, 4),
        "speed_std": round(speed_std, 4),
        "interaction_count": interaction_count,
        "diversity_count": diversity_count,
    }


# =========================
# Main
# =========================
def main():
    split_dir = DATASET_ROOT / SPLIT

    if not split_dir.exists():
        raise FileNotFoundError(f"Split folder does not exist: {split_dir}")

    scenario_files = get_scenario_files(split_dir)

    if not scenario_files:
        raise FileNotFoundError(f"No scenario parquet files found under: {split_dir}")

    if MAX_SCENARIOS is not None:
        scenario_files = scenario_files[:MAX_SCENARIOS]

    rows = []

    for i, scenario_path in enumerate(scenario_files, start=1):
        try:
            scenario = scenario_serialization.load_argoverse_scenario_parquet(scenario_path)
            row = summarize_scenario(scenario)
            rows.append(row)

            if i % 10 == 0 or i == len(scenario_files):
                print(
                    f"Processed {i}/{len(scenario_files)} | "
                    f"{row['scenario_id']} | "
                    f"interactions={row['interaction_count']}"
                )
        except Exception as e:
            print(f"Failed on {scenario_path}: {e}")

    fieldnames = [
        "scenario_id",
        "city",
        "vehicle_count",
        "pedestrian_count",
        "avg_vehicle_speed_mps",
        "speed_std",
        "interaction_count",
        "diversity_count",
    ]

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved {len(rows)} rows to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()