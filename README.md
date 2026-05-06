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

**AV City Comparison** is a local research tool built for working with and analyzing scenarios from the Argoverse 2 Sensor Dataset. The tool can be pointed to a folder containing AV2 logs, and for a selected scenario it projects the 3D cuboid annotations onto the camera image, creates an annotated MP4 video, and calculates a scene-complexity score for every frame.

**The complexity score** is based on several factors, such as the number of actors in the scene, their categories, distances from the ego vehicle, object sizes, and LiDAR density. This makes it possible to compare how complex different traffic situations are across scenarios.

We also use [extract_data.py](extract_data.py) to process the dataset in bulk. The script goes through all logs, extracts the relevant metrics, and saves them into a single [scenario_data.json](static/data/scenario_data.json) file. This JSON file is then used by the graph builder to create comparisons, for example between different cities, time of day, complexity scores, and actor counts such as cars or pedestrians. 

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

Download and unzip one or more of the train parts in the sensor dataset from [Argoverse 2](https://www.argoverse.org/av2.html).

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

> macOS note: port 5000 is used by AirPlay Receiver. The app uses `:5001` by default.

---

## How It Works

Two pipelines feed one Flask app — a **per-log render** that produces an annotated MP4,
and a **bulk extractor** that aggregates every log into a single comparison dataset.

### The complexity score

Every actor in a given frame contributes to that frame's score. Frame totals are summed
from per-actor contributions:

```
actor_score = category_weight × (1 + distance_falloff × volume_factor × lidar_density_factor)
frame_score = Σ actor_score   (over every cuboid visible at that timestamp)
```

| Term | Source | Intuition |
|---|---|---|
| `category_weight` | `CATEGORY_WEIGHTS` in [`sensor_render.py`](sensor_render.py) | A bus matters more than a sign. |
| `distance_falloff` | euclidean distance from ego in metres | Close actors dominate; far ones decay. |
| `volume_factor` | `length × width × height` | Bigger boxes = more presence. |
| `lidar_density_factor` | `num_interior_pts` per cuboid | High point counts mean the actor is well-resolved. |

[`sensor_render.py`](sensor_render.py) loads the feather files for a selected log, walks each
timestamp, projects every 3D cuboid onto the chosen camera view using the intrinsics +
ego→sensor extrinsics, draws the 8 box edges plus an optional label, scores the frame, and
streams everything to disk via `imageio[ffmpeg]`.

[`extract_data.py`](extract_data.py) skips the image and projection work — it only needs
`annotations.feather` to score frames — and writes one row per log to
[`static/data/scenario_data.json`](static/data/scenario_data.json). The Flask app
([`app.py`](app.py)) serves the SPA, streams render subprocess output as Server-Sent
Events, and renders comparison graphs on demand. If `scenario_data.json` is missing it
falls back to whatever logs you've already rendered.

---

## Application Instructions

1. **Pick a log and camera** from the dropdowns on the left.
2. **Click ▶ Render.** Watch the live log; when it finishes, the annotated
   video plays and the Statistics panel fills in (city, frame counts, avg /
   max / min complexity, vehicles, pedestrians).
3. **Build a graph.** In the Graph Builder, choose an X axis (City or Time of
   Day) and a Y axis (complexity, actor counts, distance, etc.) and click
   **Generate** to compare across the dataset.

> The graph uses `static/data/scenario_data.json` if present, otherwise only
> the logs you've rendered. Run `python extract_data.py` once for the full view.

---

## Personal usage and modification

### Adjusting the complexity score
The complexity score is calculated in the `actore_score` function in [`sensor_render.py`](sensor_render.py)

### Changing line colors
Changing the line colors of the outlines for each actor category can be done by changing the `LINE_COLORS` dictionary in [`sensor_render.py`](sensor_render.py)

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
<td valign="top">an unzipp

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

## License

See the [MIT](LICENSE) file for details
