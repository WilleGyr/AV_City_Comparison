import sqlite3
from database import create_table, add_scenario, add_scenario_metrics, add_city_summary, connect

def main():
    create_table()

if __name__ == "__main__":
    main()