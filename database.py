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
        city TEXT NOT NULL REFERENCES city_summary(city),
        complexity_score REAL NOT NULL,
        vehicle_count INTEGER NOT NULL,
        pedestrian_count INTEGER NOT NULL,
        avg_vehicle_speed_mps REAL NOT NULL,
        interaction_count INTEGER NOT NULL,
        diversity_count INTEGER NOT NULL
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


def add_scenario(scenario_id, city, complexity_score, vehicle_count, pedestrian_count, avg_vehicle_speed_mps, interaction_count, diversity_count):
    """Insert one row into scenarios."""
    conn = connect()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT OR REPLACE INTO scenarios (
        scenario_id,
        city,
        complexity_score,
        vehicle_count,
        pedestrian_count,
        avg_vehicle_speed_mps,
        interaction_count,
        diversity_count
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (scenario_id, city, complexity_score, vehicle_count, pedestrian_count, avg_vehicle_speed_mps, interaction_count, diversity_count))

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
