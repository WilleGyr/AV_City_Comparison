import sqlite3

DB_NAME = "traffic_data.db"


def connect():
    """Create and return a database connection."""
    return sqlite3.connect(DB_NAME)


def create_table():
    """Create all database tables if they do not exist."""
    conn = connect()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scenarios (
        scenario_id TEXT PRIMARY KEY,
        city TEXT NOT NULL,
        complexity_score REAL NOT NULL,
        complexity_label TEXT NOT NULL,
        source_dataset TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scenario_metrics (
        scenario_id TEXT PRIMARY KEY,
        vehicle_count INTEGER NOT NULL,
        pedestrian_count INTEGER NOT NULL,
        avg_vehicle_speed_mps REAL NOT NULL,
        speed_std REAL NOT NULL,
        interaction_count INTEGER NOT NULL,
        diversity_count INTEGER NOT NULL,
        FOREIGN KEY (scenario_id) REFERENCES scenarios(scenario_id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS city_summary (
        city TEXT PRIMARY KEY,
        mean_complexity REAL NOT NULL,
        mean_vehicle_count REAL NOT NULL,
        mean_pedestrian_count REAL NOT NULL,
        mean_speed REAL NOT NULL
    )
    """)

    conn.commit()
    conn.close()


def add_scenario(scenario_id, city, complexity_score, complexity_label, source_dataset):
    """Insert one row into scenarios."""
    conn = connect()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT OR REPLACE INTO scenarios (
        scenario_id,
        city,
        complexity_score,
        complexity_label,
        source_dataset
    )
    VALUES (?, ?, ?, ?, ?)
    """, (scenario_id, city, complexity_score, complexity_label, source_dataset))

    conn.commit()
    conn.close()


def add_scenario_metrics(
    scenario_id,
    vehicle_count,
    pedestrian_count,
    avg_vehicle_speed_mps,
    speed_std,
    interaction_count,
    diversity_count
):
    """Insert one row into scenario_metrics."""
    conn = connect()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT OR REPLACE INTO scenario_metrics (
        scenario_id,
        vehicle_count,
        pedestrian_count,
        avg_vehicle_speed_mps,
        speed_std,
        interaction_count,
        diversity_count
    )
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        scenario_id,
        vehicle_count,
        pedestrian_count,
        avg_vehicle_speed_mps,
        speed_std,
        interaction_count,
        diversity_count
    ))

    conn.commit()
    conn.close()


def add_city_summary(city, mean_complexity, mean_vehicle_count, mean_pedestrian_count, mean_speed):
    """Insert one row into city_summary."""
    conn = connect()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT OR REPLACE INTO city_summary (
        city,
        mean_complexity,
        mean_vehicle_count,
        mean_pedestrian_count,
        mean_speed
    )
    VALUES (?, ?, ?, ?, ?)
    """, (
        city,
        mean_complexity,
        mean_vehicle_count,
        mean_pedestrian_count,
        mean_speed
    ))

    conn.commit()
    conn.close()