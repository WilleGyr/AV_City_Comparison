import os
import csv
import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtCore import Qt

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "example_data.csv")

COLUMN_MAP = {
    "Number of Vehicles": "num_vehicles",
    "Number of Pedestrians": "num_pedestrians",
    "Complexity Score": "complexity_score",
}

X_COLUMN_MAP = {
    "Weather": "weather",
    "City": "city",
}


def _load_csv():
    rows = []
    with open(DATA_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "city": row["city"],
                "weather": row["weather"],
                "num_vehicles": float(row["num_vehicles"]),
                "num_pedestrians": float(row["num_pedestrians"]),
                "complexity_score": float(row["complexity_score"]),
            })
    return rows


def _group_mean(rows, group_col, value_col):
    totals = {}
    counts = {}
    for row in rows:
        key = row[group_col]
        totals[key] = totals.get(key, 0) + row[value_col]
        counts[key] = counts.get(key, 0) + 1
    labels = list(totals.keys())
    values = [totals[k] / counts[k] for k in labels]
    return labels, values


class GraphBuilder:
    def __init__(self, x_combo, y_combo, graph_label):
        self.x_combo = x_combo
        self.y_combo = y_combo
        self.graph_label = graph_label

    def build_graph(self):
        x_selection = self.x_combo.currentText()
        y_selection = self.y_combo.currentText()

        x_col = X_COLUMN_MAP[x_selection]
        y_col = COLUMN_MAP[y_selection]

        rows = _load_csv()
        labels, values = _group_mean(rows, x_col, y_col)

        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(5.8, 5.2))
        fig.patch.set_facecolor('#252525')
        ax.set_facecolor('#1e1e1e')

        ax.bar(labels, values, color='#f5c518', edgecolor='#c9a014', width=0.6)

        ax.set_xlabel(x_selection, color='#f0f0f0', fontsize=11)
        ax.set_ylabel(y_selection, color='#f0f0f0', fontsize=11)
        ax.set_title(f"{y_selection} by {x_selection}", color='#f5c518',
                     fontsize=13, fontweight='bold', pad=12)
        ax.tick_params(colors='#f0f0f0', labelsize=10)
        for spine in ax.spines.values():
            spine.set_color('#3a3a3a')

        plt.xticks(rotation=15, ha='right')
        plt.tight_layout(pad=1.5)

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100, facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)

        image = QImage.fromData(buf.read())
        pixmap = QPixmap.fromImage(image)
        self.graph_label.setPixmap(pixmap.scaled(
            self.graph_label.width(),
            self.graph_label.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        ))
