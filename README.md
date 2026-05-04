<div align="center">

<h1>AV City Comparison</h1>

<br/>

<p>
  <b>Argoverse 2 sensor logs · Per-frame complexity · City-by-city analysis.</b><br/>
  A local web app that renders annotated camera videos and compares driving difficulty across cities.
</p>

<p>
  <a href="#overview">Overview</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#how-it-works">How It Works</a> ·
  <a href="#license">License</a>
</p>

</div>

---

## Overview

**AV City Comparison** is a local research tool for the [Argoverse 2 Sensor Dataset](https://www.argoverse.org/av2.html).
Point it at a folder of AV2 logs and it will, for any chosen log, project the 3D cuboid
annotations into a camera image, write an annotated MP4, and score every frame for scene
complexity — number of actors, their categories, distances, sizes, and LiDAR density.

A second pass (`extract_data.py`) walks every log in the dataset, computes the same
metrics in bulk, and dumps a single `scenario_data.json` that powers a graph builder for
city-vs-city or time-of-day-vs-complexity comparisons.

No cloud. No account. The app is a Flask server that talks to local `.feather` files and
serves a single-page UI.

<div align="center">

<table>
<tr>
<td align="center" width="33%">
<h3>Project</h3>
<sub>3D cuboids → camera frames via AV2 calibration + ego pose.</sub>
</td>
<td align="center" width="33%">
<h3>Score</h3>
<sub>Per-frame complexity from category, distance, size, density.</sub>
</td>
<td align="center" width="33%">
<h3>Compare</h3>
<sub>Bulk-extract every log → grouped bar charts per city / time of day.</sub>
</td>
</tr>
</table>

</div>

---

---

## Quick Start

> AV City Comparison is local-first — it expects an unzipped Argoverse 2 sensor split
> on disk and points to it via an env var.

```bash
# 1. Install Python deps
pip install flask opencv-python "imageio[ffmpeg]" numpy pandas scipy pyarrow matplotlib

# 2. Point the app at your AV2 split
export AV2_TRAIN_DIR=/path/to/av2/sensor/train

# 3. (Optional but recommended) Bulk-extract scenario stats once
python extract_data.py            # → static/data/scenario_data.json

# 4. Start the app
python app.py
```

Open <http://127.0.0.1:5001> and pick a log.

> macOS note: port 5000 is hijacked by AirPlay Receiver. The app uses `:5001` by default.

---

## How It Works

Two pipelines feed one Flask app — a **per-log render** that produces an annotated MP4,
and a **bulk extractor** that aggregates every log into a single comparison dataset.

### The complexity score

Every actor in every frame contributes to that frame's score. Frame totals are summed
from per-actor contributions:

```
actor_score = category_weight × distance_falloff × volume_factor × lidar_density_factor
frame_score = Σ actor_score   (over every cuboid visible at that timestamp)
```

| Term | Source | Intuition |
|---|---|---|
| `category_weight` | `CATEGORY_WEIGHTS` in [`sensor_render.py`](sensor_render.py) | A bus matters more than a sign. |
| `distance_falloff` | euclidean distance from ego in metres | Close actors dominate; far ones decay. |
| `volume_factor` | `length × width × height` | Bigger boxes = more presence. |
| `lidar_density_factor` | `num_interior_pts` per cuboid | High point counts mean the actor is well-resolved. |

Tweak the weights, re-run the bulk extractor, and the graph builder picks up the new
numbers immediately.

[`sensor_render.py`](sensor_render.py) loads the feather files for one log, walks each
timestamp, projects every 3D cuboid into the chosen camera using the intrinsics +
ego→sensor extrinsics, draws the 8 box edges plus a short label, scores the frame, and
streams everything to disk via `imageio[ffmpeg]`.

[`extract_data.py`](extract_data.py) skips the image and projection work — it only needs
`annotations.feather` to score frames — and writes one row per log to
[`static/data/scenario_data.json`](static/data/scenario_data.json). The Flask app
([`app.py`](app.py)) serves the SPA, streams render subprocess output as Server-Sent
Events, and renders comparison graphs on demand. If `scenario_data.json` is missing it
falls back to whatever logs you've already rendered.

---

## Tech Stack

<table>
<tr>
<td valign="top">

**Backend**
- Python 3.10+
- [Flask 3](https://flask.palletsprojects.com/) — routing + SSE
- [Matplotlib](https://matplotlib.org/) — graph rendering (`Agg` backend)

</td>
<td valign="top">

**Data + render**
- [NumPy](https://numpy.org/) / [pandas](https://pandas.pydata.org/) — feather + tabular ops
- [PyArrow](https://arrow.apache.org/docs/python/) — `.feather` reader
- [SciPy](https://scipy.org/) — `Rotation` for SE3 → matrix
- [OpenCV](https://opencv.org/) — image draw + I/O
- [imageio + ffmpeg](https://imageio.readthedocs.io/) — MP4 writer

</td>
<td valign="top">

**Frontend**
- Vanilla HTML / CSS / JS (no build step)
- Server-Sent Events for live render log
- Single `style.css` — minimal dark theme, indigo accent

</td>
</tr>
</table>

---

## Project Structure

```
.
├── app.py                          # Flask server: routes, SSE, graph endpoint
├── sensor_render.py                # AV2 → annotated MP4 + summary.json (per-log)
├── extract_data.py                 # bulk per-log metrics → scenario_data.json
├── templates/
│   └── index.html                  # single-page layout
├── static/
│   ├── style.css                   # theme + layout
│   ├── app.js                      # log/camera selector, render SSE, stats, graph
│   ├── data/
│   │   └── scenario_data.json      # generated by extract_data.py
│   └── output/<log_id>/
│       ├── video.mp4               # rendered annotated video
│       └── summary.json            # per-render frame scores + averages
├── train/                          # AV2 logs (git-ignored)
└── README.md
```

---

## Scripts

| Command | What it does |
|---|---|
| `python app.py` | Start the Flask app on `:5001`. |
| `python extract_data.py` | Walk every log in `$AV2_TRAIN_DIR` and write `static/data/scenario_data.json`. |
| `python sensor_render.py --log-dir <path> --camera ring_front_center --output-video out.mp4 --output-json out.json` | Render one log directly from the CLI. |

---

## License

See the [MIT](LICENSE) file for details