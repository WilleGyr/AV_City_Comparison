import csv
from collections import defaultdict

from database import create_table, add_scenario, add_scenario_metrics, add_city_summary


CSV_FILE = "av2_scenario_summary.csv"
SOURCE_DATASET = "argoverse2_val"


def compute_complexity_score(row):
    """
    Simple weighted score based on your computed metrics.
    Adjust weights however you want.
    """
    return (
        row["vehicle_count"] * 1.0 +
        row["pedestrian_count"] * 1.2 +
        row["interaction_count"] * 2.0 +
        row["diversity_count"] * 1.5 +
        row["speed_std"] * 0.8
    )


def complexity_label(score):
    if score < 15:
        return "low"
    if score < 35:
        return "medium"
    return "high"


def main():
    create_table()

    city_groups = defaultdict(list)

    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for raw in reader:
            row = {
                "scenario_id": raw["scenario_id"],
                "city": raw["city"],
                "vehicle_count": int(raw["vehicle_count"]),
                "pedestrian_count": int(raw["pedestrian_count"]),
                "avg_vehicle_speed_mps": float(raw["avg_vehicle_speed_mps"]),
                "speed_std": float(raw["speed_std"]),
                "interaction_count": int(raw["interaction_count"]),
                "diversity_count": int(raw["diversity_count"]),
            }

            score = compute_complexity_score(row)
            label = complexity_label(score)

            add_scenario(
                scenario_id=row["scenario_id"],
                city=row["city"],
                complexity_score=score,
                complexity_label=label,
                source_dataset=SOURCE_DATASET,
            )

            add_scenario_metrics(
                scenario_id=row["scenario_id"],
                vehicle_count=row["vehicle_count"],
                pedestrian_count=row["pedestrian_count"],
                avg_vehicle_speed_mps=row["avg_vehicle_speed_mps"],
                speed_std=row["speed_std"],
                interaction_count=row["interaction_count"],
                diversity_count=row["diversity_count"],
            )

            city_groups[row["city"]].append({
                "complexity_score": score,
                "vehicle_count": row["vehicle_count"],
                "pedestrian_count": row["pedestrian_count"],
                "avg_vehicle_speed_mps": row["avg_vehicle_speed_mps"],
            })

    for city, rows in city_groups.items():
        mean_complexity = sum(r["complexity_score"] for r in rows) / len(rows)
        mean_vehicle_count = sum(r["vehicle_count"] for r in rows) / len(rows)
        mean_pedestrian_count = sum(r["pedestrian_count"] for r in rows) / len(rows)
        mean_speed = sum(r["avg_vehicle_speed_mps"] for r in rows) / len(rows)

        add_city_summary(
            city=city,
            mean_complexity=mean_complexity,
            mean_vehicle_count=mean_vehicle_count,
            mean_pedestrian_count=mean_pedestrian_count,
            mean_speed=mean_speed,
        )

    print("Import complete: CSV data inserted into traffic_data.db")


if __name__ == "__main__":
    main()