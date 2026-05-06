from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

# Make sensor_render importable when running this file directly.
sys.path.insert(0, str(Path(__file__).parent))
from sensor_render import TRAIN_DIR, get_city_from_log, list_logs

# Per-log render outputs (video.mp4 + summary.json) live under static/ so
# they can be served straight by Flask's static handler.
OUTPUT_DIR = Path(__file__).parent / "static" / "output"
SCENARIO_DATA_FILE = Path(__file__).parent / "static" / "data" / "scenario_data.json"

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_scenario_data() -> list[dict]:
    # Missing file is the normal "user hasn't run the bulk extractor yet"
    # case — return [] and let the caller decide on a fallback.
    """Load pre-generated scenario data from extract_data.py output."""
    if SCENARIO_DATA_FILE.exists():
        with open(SCENARIO_DATA_FILE) as f:
            return json.load(f)
    return []


def _rendered_rows() -> list[dict]:
    # Fallback for the graph endpoint when scenario_data.json is missing:
    # collect summaries from any logs the user has already rendered.
    rows = []
    if OUTPUT_DIR.exists():
        for d in OUTPUT_DIR.iterdir():
            json_path = d / "summary.json"
            if json_path.exists():
                with open(json_path) as f:
                    data = json.load(f)
                # Map summary.json keys onto the same shape extract_data.py
                # produces, so the graph endpoint doesn't care which source
                # the row came from. Fields without a per-render equivalent
                # are zero-filled.
                rows.append({
                    "log_id": d.name,
                    "city": data.get("city") or get_city_from_log(TRAIN_DIR / d.name),
                    "weather": "Unknown",
                    "avg_complexity": data.get("average_complexity_score", 0),
                    "max_complexity": data.get("max_frame_complexity", 0),
                    "min_complexity": data.get("min_frame_complexity", 0),
                    "complexity_std": 0,
                    "num_frames": data.get("processed_frames", 0),
                    "vehicle_count": data.get("vehicle_count", 0),
                    "pedestrian_count": data.get("pedestrian_count", 0),
                    "actor_density": 0,
                    "avg_object_distance": 0,
                    "num_unique_categories": 0,
                })
    return rows


def _graph_data() -> list[dict]:
    # Prefer the bulk extract — it covers the full dataset. Fall back to
    # rendered logs only when the user hasn't run extract_data.py yet.
    """Return scenario data: pre-generated JSON if available, else rendered summaries."""
    data = _load_scenario_data()
    return data if data else _rendered_rows()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    # Serves the single-page UI; everything else goes through /api/*.
    return render_template("index.html")


@app.route("/api/logs")
def api_logs():
    # Used by the Log dropdown — every folder under TRAIN_DIR.
    return jsonify(list_logs())


@app.route("/api/cameras/<log_id>")
def api_cameras(log_id: str):
    # Logs may have any subset of ring cameras; surface whatever this one has.
    cam_dir = TRAIN_DIR / log_id / "sensors" / "cameras"
    if cam_dir.exists():
        cameras = sorted(d.name for d in cam_dir.iterdir() if d.is_dir())
    else:
        # Sane default if the cameras directory is missing entirely.
        cameras = ["ring_front_center"]
    return jsonify(cameras)


@app.route("/api/render/<log_id>")
def api_render(log_id: str):
    camera = request.args.get("camera", "ring_front_center")
    log_dir = TRAIN_DIR / log_id
    if not log_dir.exists():
        return jsonify({"error": "Log not found"}), 404

    # Render artefacts for this log live in their own folder so re-renders
    # cleanly overwrite the previous video + summary.
    out_dir = OUTPUT_DIR / log_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_video = out_dir / "video.mp4"
    out_json = out_dir / "summary.json"

    # Run sensor_render.py as a subprocess and stream its stdout to the
    # browser as Server-Sent Events so the UI can show live progress.
    # A subprocess (rather than an in-process call) keeps the heavy
    # OpenCV/imageio work off the Flask request thread.
    def generate():
        import subprocess
        script = Path(__file__).parent / "sensor_render.py"
        cmd = [
            sys.executable, str(script),
            "--log-dir", str(log_dir),
            "--camera", camera,
            "--output-video", str(out_video),
            "--output-json", str(out_json),
            "--skip-labels",
        ]
        # Merge stderr into stdout so warnings show up in the live log too.
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        # One SSE event per output line — the frontend appends them to the panel.
        for line in proc.stdout:
            yield f"data: {json.dumps({'line': line.rstrip()})}\n\n"
        proc.wait()
        # Final event tells the frontend to load the video and pull stats.
        if proc.returncode == 0:
            yield f"data: {json.dumps({'done': True, 'log_id': log_id, 'camera': camera})}\n\n"
        else:
            yield f"data: {json.dumps({'error': f'Render failed (exit {proc.returncode})'})}\n\n"

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        # X-Accel-Buffering disables nginx buffering if the app is ever
        # proxied — without it, SSE chunks would arrive in a single burst.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/stats/<log_id>")
def api_stats(log_id: str):
    # Per-log Statistics panel reads the summary.json written during render.
    json_path = OUTPUT_DIR / log_id / "summary.json"
    if not json_path.exists():
        return jsonify({}), 404
    with open(json_path) as f:
        data = json.load(f)
    # Older summary.json files predate the city field — backfill from the map.
    data.setdefault("city", get_city_from_log(TRAIN_DIR / log_id))
    return jsonify(data)


@app.route("/api/rendered-logs")
def api_rendered_logs():
    # Debug-friendly view of what's been rendered locally.
    return jsonify(_rendered_rows())


@app.route("/api/scenario-data")
def api_scenario_data():
    # Raw bulk-extract dump, served for inspection / future frontend use.
    return jsonify(_load_scenario_data())


@app.route("/api/graph")
def api_graph():
    # X = grouping key (city / time_of_day / log_id),
    # Y = numeric metric to average per group.
    x_key = request.args.get("x", "city")
    y_key = request.args.get("y", "avg_complexity")

    rows = _graph_data()

    # Group rows by the X field and collect Y values per group;
    # the chart shows the mean of Y for each group.
    groups: dict[str, list[float]] = {}
    for row in rows:
        key = str(row.get(x_key, "Unknown"))
        try:
            val = float(row.get(y_key, 0))
        except (TypeError, ValueError):
            # Skip rows where Y isn't numeric (missing field, string, etc.).
            continue
        groups.setdefault(key, []).append(val)

    # `counts` lets the frontend tooltip show "n logs in this group".
    labels = list(groups.keys())
    values = [sum(v) / len(v) for v in groups.values()]
    counts = [len(v) for v in groups.values()]

    # Pretty axis names for the chart — fall back to the raw key if unknown.
    y_labels = {
        "avg_complexity": "Avg Complexity Score",
        "max_complexity": "Max Complexity Score",
        "complexity_std": "Complexity Variability (Std Dev)",
        "vehicle_count": "Avg Vehicles / Frame",
        "pedestrian_count": "Avg Pedestrians / Frame",
        "cyclist_count": "Avg Cyclists / Frame",
        "actor_density": "Avg Total Actors / Frame",
        "close_object_count": "Avg Close-Range Objects (<10 m)",
        "avg_object_distance": "Avg Object Distance (m)",
        "avg_object_size": "Avg Object Size (m³)",
        "lidar_density": "Avg LiDAR Points / Object",
        "num_unique_categories": "Category Diversity",
        "num_frames": "Number of Frames",
    }
    x_labels = {
        "city": "City",
        "time_of_day": "Time of Day",
        "log_id": "Log ID",
    }

    x_label = x_labels.get(x_key, x_key)
    y_label = y_labels.get(y_key, y_key)

    return jsonify({
        "labels": labels,
        "values": values,
        "counts": counts,
        "x_label": x_label,
        "y_label": y_label,
        "title": f"{y_label} by {x_label}",
    })


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # threaded=True lets the SSE stream coexist with regular API calls.
    app.run(debug=True, port=5001, threaded=True)
