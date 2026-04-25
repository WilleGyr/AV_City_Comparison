from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context

sys.path.insert(0, str(Path(__file__).parent))
from sensor_render import TRAIN_DIR, get_city_from_log, list_logs

OUTPUT_DIR = Path(__file__).parent / "static" / "output"
SCENARIO_DATA_FILE = Path(__file__).parent / "static" / "data" / "scenario_data.json"

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_scenario_data() -> list[dict]:
    """Load pre-generated scenario data from extract_data.py output."""
    if SCENARIO_DATA_FILE.exists():
        with open(SCENARIO_DATA_FILE) as f:
            return json.load(f)
    return []


def _rendered_rows() -> list[dict]:
    rows = []
    if OUTPUT_DIR.exists():
        for d in OUTPUT_DIR.iterdir():
            json_path = d / "summary.json"
            if json_path.exists():
                with open(json_path) as f:
                    data = json.load(f)
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
    """Return scenario data: pre-generated JSON if available, else rendered summaries."""
    data = _load_scenario_data()
    return data if data else _rendered_rows()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/logs")
def api_logs():
    return jsonify(list_logs())


@app.route("/api/cameras/<log_id>")
def api_cameras(log_id: str):
    cam_dir = TRAIN_DIR / log_id / "sensors" / "cameras"
    if cam_dir.exists():
        cameras = sorted(d.name for d in cam_dir.iterdir() if d.is_dir())
    else:
        cameras = ["ring_front_center"]
    return jsonify(cameras)


@app.route("/api/render/<log_id>")
def api_render(log_id: str):
    camera = request.args.get("camera", "ring_front_center")
    log_dir = TRAIN_DIR / log_id
    if not log_dir.exists():
        return jsonify({"error": "Log not found"}), 404

    out_dir = OUTPUT_DIR / log_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_video = out_dir / "video.mp4"
    out_json = out_dir / "summary.json"

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
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            yield f"data: {json.dumps({'line': line.rstrip()})}\n\n"
        proc.wait()
        if proc.returncode == 0:
            yield f"data: {json.dumps({'done': True, 'log_id': log_id, 'camera': camera})}\n\n"
        else:
            yield f"data: {json.dumps({'error': f'Render failed (exit {proc.returncode})'})}\n\n"

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/stats/<log_id>")
def api_stats(log_id: str):
    json_path = OUTPUT_DIR / log_id / "summary.json"
    if not json_path.exists():
        return jsonify({}), 404
    with open(json_path) as f:
        data = json.load(f)
    data.setdefault("city", get_city_from_log(TRAIN_DIR / log_id))
    return jsonify(data)


@app.route("/api/rendered-logs")
def api_rendered_logs():
    return jsonify(_rendered_rows())


@app.route("/api/scenario-data")
def api_scenario_data():
    return jsonify(_load_scenario_data())


@app.route("/api/graph")
def api_graph():
    x_key = request.args.get("x", "city")
    y_key = request.args.get("y", "avg_complexity")

    rows = _graph_data()

    groups: dict[str, list[float]] = {}
    for row in rows:
        key = str(row.get(x_key, "Unknown"))
        try:
            val = float(row.get(y_key, 0))
        except (TypeError, ValueError):
            continue
        groups.setdefault(key, []).append(val)

    labels = list(groups.keys()) or ["No data"]
    values = [sum(v) / len(v) if v else 0 for v in groups.values()] or [0]

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

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(8.0, 3.2))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#12121f")

    bars = ax.bar(labels, values, color="#f5c518", edgecolor="#c9a014", width=0.55)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(values) * 0.02,
            f"{val:.1f}",
            ha="center", va="bottom",
            color="#f0f0f0", fontsize=9,
        )

    ax.set_xlabel(x_labels.get(x_key, x_key), color="#8080b0", fontsize=10)
    ax.set_ylabel(y_labels.get(y_key, y_key), color="#8080b0", fontsize=10)
    ax.set_title(
        f"{y_labels.get(y_key, y_key)} by {x_labels.get(x_key, x_key)}",
        color="#f5c518", fontsize=12, fontweight="bold", pad=10,
    )
    ax.tick_params(colors="#a0a0c0", labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#2e2e50")
    ax.set_ylim(bottom=0, top=max(values) * 1.18 if values else 1)
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout(pad=1.2)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app.run(debug=True, port=5001, threaded=True)
