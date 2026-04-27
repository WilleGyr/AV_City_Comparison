from __future__ import annotations

import argparse
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import imageio.v2 as imageio
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation as R


# ---------------------------------------------------------------------------
# Train-000 dataset location — override with env var AV2_TRAIN_DIR
# ---------------------------------------------------------------------------
_DEFAULT_TRAIN_DIR = Path("train")
TRAIN_DIR: Path = Path(os.environ.get("AV2_TRAIN_DIR", str(_DEFAULT_TRAIN_DIR)))


# ============================================================
# AV2 SENSOR DATASET: CAMERA-VIEW COMPLEXITY VIDEO RENDERER
# ============================================================
#
# What this script does:
# 1. Reads AV2 Sensor Dataset annotations.feather (3D cuboids in ego frame).
# 2. Reads calibration.feather and poses.feather.
# 3. Reads images from one camera stream.
# 4. Projects each 3D cuboid into the chosen camera image.
# 5. Draws 3D box outlines and a short text label per actor.
# 6. Computes a real-time per-frame complexity score.
# 7. Writes an annotated MP4 and a JSON summary with frame scores and average score.
#
# Assumptions:
# - Images are from a single AV2 log directory.
# - Cuboids in annotations.feather are indexed by timestamp_ns.
# - calibration.feather contains camera intrinsics and extrinsics.
# - poses.feather contains ego pose in city/world frame by timestamp_ns.
#
# You may need to adjust column names slightly depending on your local AV2 release.
# A helper is included to handle common alternative names.
#
# ============================================================


# -----------------------------
# User-tunable scoring weights
# -----------------------------
CATEGORY_WEIGHTS = {
    "REGULAR_VEHICLE": 3.0,
    "LARGE_VEHICLE": 3.8,
    "BUS": 4.0,
    "BOX_TRUCK": 3.8,
    "TRUCK": 3.8,
    "TRAILER": 2.8,
    "BICYCLE": 2.5,
    "BICYCLIST": 3.0,
    "MOTORCYCLE": 3.0,
    "MOTORCYCLIST": 3.4,
    "PEDESTRIAN": 2.8,
    "WHEELED_RIDER": 2.8,
    "WHEELED_DEVICE": 1.2,
    "WHEELCHAIR": 1.5,
    "STROLLER": 1.4,
    "DOG": 1.6,
    "CONSTRUCTION_CONE": 0.7,
    "BOLLARD": 0.6,
    "SIGN": 0.4,
    "STOP_SIGN": 0.8,
    "MOBILE_PEDESTRIAN_CROSSING_SIGN": 0.9,
    "MESSAGE_BOARD_TRAILER": 1.0,
    "TRAFFIC_LIGHT_TRAILER": 1.0,
    "ARTICULATED_BUS": 4.5,
    "SCHOOL_BUS": 4.2,
    "VEHICULAR_TRAILER": 2.8,
    "UNKNOWN": 1.0,
}

LINE_COLORS = {
    "REGULAR_VEHICLE": (0, 215, 255),
    "LARGE_VEHICLE": (0, 165, 255),
    "BUS": (0, 100, 255),
    "BOX_TRUCK": (0, 130, 255),
    "TRUCK": (0, 130, 255),
    "TRAILER": (0, 80, 255),
    "BICYCLE": (255, 220, 0),
    "BICYCLIST": (255, 220, 0),
    "MOTORCYCLE": (255, 180, 0),
    "MOTORCYCLIST": (255, 160, 0),
    "PEDESTRIAN": (0, 255, 0),
    "WHEELED_RIDER": (80, 255, 80),
    "WHEELED_DEVICE": (180, 255, 180),
    "WHEELCHAIR": (140, 255, 140),
    "STROLLER": (120, 255, 120),
    "DOG": (100, 220, 100),
    "CONSTRUCTION_CONE": (255, 0, 255),
    "BOLLARD": (190, 190, 190),
    "SIGN": (170, 170, 170),
    "STOP_SIGN": (0, 0, 255),
    "MOBILE_PEDESTRIAN_CROSSING_SIGN": (100, 100, 255),
    "MESSAGE_BOARD_TRAILER": (255, 100, 255),
    "TRAFFIC_LIGHT_TRAILER": (255, 120, 255),
    "ARTICULATED_BUS": (0, 80, 255),
    "SCHOOL_BUS": (0, 120, 255),
    "VEHICULAR_TRAILER": (0, 80, 255),
    "UNKNOWN": (255, 255, 255),
}

VEHICLE_CATEGORIES = frozenset({
    "REGULAR_VEHICLE", "LARGE_VEHICLE", "BUS", "BOX_TRUCK", "TRUCK",
    "TRAILER", "ARTICULATED_BUS", "SCHOOL_BUS", "VEHICULAR_TRAILER",
})

PEDESTRIAN_CATEGORIES = frozenset({
    "PEDESTRIAN", "WHEELED_RIDER", "WHEELED_DEVICE", "WHEELCHAIR",
    "STROLLER", "DOG",
})

def get_city_from_log(log_dir: Path) -> str:
    """Extract AV2 city code from a log's map directory filename (e.g. PIT, MIA, WDC)."""
    map_dir = log_dir / "map"
    if map_dir.exists():
        for f in map_dir.iterdir():
            m = re.search(r"____([A-Z]{2,5})[_.]", f.name)
            if m:
                return m.group(1)
    return "UNKNOWN"


def list_logs(train_dir: Optional[Path] = None) -> List[Dict]:
    """Return a list of {id, path, city} dicts for every log in train_dir."""
    d = train_dir or TRAIN_DIR
    if not d.exists():
        return []
    return [
        {"id": p.name, "path": str(p), "city": get_city_from_log(p)}
        for p in sorted(d.iterdir())
        if p.is_dir()
    ]


# 3D cuboid edge connectivity for 8 corners.
BOX_EDGES = [
    (0, 1), (1, 2), (2, 3), (3, 0),  # top face
    (4, 5), (5, 6), (6, 7), (7, 4),  # bottom face
    (0, 4), (1, 5), (2, 6), (3, 7),  # verticals
]


@dataclass
class CameraCalibration:
    camera_name: str
    K: np.ndarray               # (3, 3)
    ego_T_cam: np.ndarray       # (4, 4) transform camera -> ego
    cam_T_ego: np.ndarray       # (4, 4) transform ego -> camera


@dataclass
class EgoPose:
    timestamp_ns: int
    city_T_ego: np.ndarray      # (4, 4)
    ego_T_city: np.ndarray      # (4, 4)


def pick_column(df: pd.DataFrame, candidates: List[str], required: bool = True) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    if required:
        raise KeyError(f"Could not find any of these columns: {candidates}\nAvailable: {list(df.columns)}")
    return None


def quat_to_rotmat(qw: float, qx: float, qy: float, qz: float) -> np.ndarray:
    return R.from_quat([qx, qy, qz, qw]).as_matrix()


def make_se3(Rm: np.ndarray, t: np.ndarray) -> np.ndarray:
    T = np.eye(4, dtype=float)
    T[:3, :3] = Rm
    T[:3, 3] = t
    return T


def invert_se3(T: np.ndarray) -> np.ndarray:
    Rm = T[:3, :3]
    t = T[:3, 3]
    T_inv = np.eye(4, dtype=float)
    T_inv[:3, :3] = Rm.T
    T_inv[:3, 3] = -Rm.T @ t
    return T_inv


def transform_points(T: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """
    T: (4,4), pts: (N,3)
    Returns transformed pts: (N,3)
    """
    pts_h = np.concatenate([pts, np.ones((len(pts), 1), dtype=float)], axis=1)
    out = (T @ pts_h.T).T
    return out[:, :3]


def project_points(K: np.ndarray, pts_cam: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    pts_cam: (N,3) in camera coordinates
    Returns:
      uv: (N,2)
      valid: (N,) where z > 0
    """
    z = pts_cam[:, 2]
    valid = z > 1e-4
    uv = np.full((len(pts_cam), 2), np.nan, dtype=float)
    if np.any(valid):
        xyz = pts_cam[valid]
        pix = (K @ xyz.T).T
        uv[valid, 0] = pix[:, 0] / pix[:, 2]
        uv[valid, 1] = pix[:, 1] / pix[:, 2]
    return uv, valid


def cuboid_corners_ego(length_m: float, width_m: float, height_m: float,
                       qw: float, qx: float, qy: float, qz: float,
                       tx_m: float, ty_m: float, tz_m: float) -> np.ndarray:
    """
    Build 8 cuboid corners in ego frame using cuboid pose.
    Centered at (tx,ty,tz), oriented by quaternion.
    """
    l = length_m
    w = width_m
    h = height_m

    # Local box corners centered at origin.
    # Convention: top face first, then bottom face.
    local = np.array([
        [ l/2,  w/2,  h/2],
        [ l/2, -w/2,  h/2],
        [-l/2, -w/2,  h/2],
        [-l/2,  w/2,  h/2],
        [ l/2,  w/2, -h/2],
        [ l/2, -w/2, -h/2],
        [-l/2, -w/2, -h/2],
        [-l/2,  w/2, -h/2],
    ], dtype=float)

    Rm = quat_to_rotmat(qw, qx, qy, qz)
    t = np.array([tx_m, ty_m, tz_m], dtype=float)
    return (Rm @ local.T).T + t


def load_calibration(intrinsics_path: Path, extrinsics_path: Path, camera_name: str) -> CameraCalibration:
    intr_df = pd.read_feather(intrinsics_path)
    ext_df = pd.read_feather(extrinsics_path)

    intr_camera_col = pick_column(intr_df, ["sensor_name", "camera_name", "name", "channel"])
    ext_camera_col = pick_column(ext_df, ["sensor_name", "camera_name", "name", "channel"])

    intr_row = intr_df[intr_df[intr_camera_col] == camera_name]
    ext_row = ext_df[ext_df[ext_camera_col] == camera_name]

    if len(intr_row) == 0:
        raise ValueError(f"Camera '{camera_name}' not found in {intrinsics_path}")
    if len(ext_row) == 0:
        raise ValueError(f"Camera '{camera_name}' not found in {extrinsics_path}")

    intr_row = intr_row.iloc[0]
    ext_row = ext_row.iloc[0]

    fx_col = pick_column(intr_df, ["fx_px", "fx", "focal_length_x_px"])
    fy_col = pick_column(intr_df, ["fy_px", "fy", "focal_length_y_px"])
    cx_col = pick_column(intr_df, ["cx_px", "cx", "principal_point_x_px"])
    cy_col = pick_column(intr_df, ["cy_px", "cy", "principal_point_y_px"])

    fx = float(intr_row[fx_col])
    fy = float(intr_row[fy_col])
    cx = float(intr_row[cx_col])
    cy = float(intr_row[cy_col])

    K = np.array([
        [fx, 0.0, cx],
        [0.0, fy, cy],
        [0.0, 0.0, 1.0]
    ], dtype=float)

    qw_col = pick_column(ext_df, ["qw"])
    qx_col = pick_column(ext_df, ["qx"])
    qy_col = pick_column(ext_df, ["qy"])
    qz_col = pick_column(ext_df, ["qz"])
    tx_col = pick_column(ext_df, ["tx_m"])
    ty_col = pick_column(ext_df, ["ty_m"])
    tz_col = pick_column(ext_df, ["tz_m"])

    # AV2 stores egovehicle_SE3_sensor, i.e. sensor -> ego
    Rm = quat_to_rotmat(
        float(ext_row[qw_col]),
        float(ext_row[qx_col]),
        float(ext_row[qy_col]),
        float(ext_row[qz_col]),
    )
    t = np.array([
        float(ext_row[tx_col]),
        float(ext_row[ty_col]),
        float(ext_row[tz_col]),
    ], dtype=float)

    ego_T_cam = make_se3(Rm, t)
    cam_T_ego = invert_se3(ego_T_cam)

    return CameraCalibration(
        camera_name=camera_name,
        K=K,
        ego_T_cam=ego_T_cam,
        cam_T_ego=cam_T_ego,
    )


def load_poses(poses_path: Path) -> Dict[int, EgoPose]:
    df = pd.read_feather(poses_path)

    ts_col = pick_column(df, ["timestamp_ns"])
    qw_col = pick_column(df, ["qw", "ego_city_qw", "city_SE3_ego_qw"])
    qx_col = pick_column(df, ["qx", "ego_city_qx", "city_SE3_ego_qx"])
    qy_col = pick_column(df, ["qy", "ego_city_qy", "city_SE3_ego_qy"])
    qz_col = pick_column(df, ["qz", "ego_city_qz", "city_SE3_ego_qz"])
    tx_col = pick_column(df, ["tx_m", "ego_city_tx_m", "city_SE3_ego_tx_m"])
    ty_col = pick_column(df, ["ty_m", "ego_city_ty_m", "city_SE3_ego_ty_m"])
    tz_col = pick_column(df, ["tz_m", "ego_city_tz_m", "city_SE3_ego_tz_m"])

    poses: Dict[int, EgoPose] = {}
    for _, row in df.iterrows():
        Rm = quat_to_rotmat(float(row[qw_col]), float(row[qx_col]), float(row[qy_col]), float(row[qz_col]))
        t = np.array([float(row[tx_col]), float(row[ty_col]), float(row[tz_col])], dtype=float)
        city_T_ego = make_se3(Rm, t)
        ego_T_city = invert_se3(city_T_ego)
        ts = int(row[ts_col])
        poses[ts] = EgoPose(timestamp_ns=ts, city_T_ego=city_T_ego, ego_T_city=ego_T_city)

    return poses


def load_annotations(annotations_path: Path) -> pd.DataFrame:
    df = pd.read_feather(annotations_path)

    # Normalize a few expected columns.
    rename_map = {}
    for old, new in [
        ("category", "category"),
        ("track_uuid", "track_uuid"),
        ("timestamp_ns", "timestamp_ns"),
        ("length_m", "length_m"),
        ("width_m", "width_m"),
        ("height_m", "height_m"),
        ("qw", "qw"),
        ("qx", "qx"),
        ("qy", "qy"),
        ("qz", "qz"),
        ("tx_m", "tx_m"),
        ("ty_m", "ty_m"),
        ("tz_m", "tz_m"),
        ("num_interior_pts", "num_interior_pts"),
    ]:
        if old in df.columns:
            rename_map[old] = new

    df = df.rename(columns=rename_map)

    required = [
        "timestamp_ns", "track_uuid", "category",
        "length_m", "width_m", "height_m",
        "qw", "qx", "qy", "qz",
        "tx_m", "ty_m", "tz_m",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"annotations.feather is missing required columns: {missing}")

    if "num_interior_pts" not in df.columns:
        df["num_interior_pts"] = 0

    return df


def parse_image_timestamp_ns(path: Path) -> int:
    stem = path.stem
    digits = "".join(ch for ch in stem if ch.isdigit())
    if not digits:
        raise ValueError(f"Could not parse timestamp from image filename: {path.name}")
    return int(digits)


def list_camera_images(log_dir: Path, camera_name: str) -> List[Path]:
    """
    Tries common AV2 image directory layouts.
    """
    candidates = [
        log_dir / "sensors" / "cameras" / camera_name,
        log_dir / "cameras" / camera_name,
        log_dir / camera_name,
    ]
    for d in candidates:
        if d.exists() and d.is_dir():
            images = sorted(
                [p for p in d.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}],
                key=lambda p: parse_image_timestamp_ns(p)
            )
            if images:
                return images
    raise FileNotFoundError(
        f"Could not find images for camera '{camera_name}'. "
        f"Tried: {[str(x) for x in candidates]}"
    )


def nearest_timestamp(target: int, available: np.ndarray, max_delta_ns: int) -> Optional[int]:
    idx = np.searchsorted(available, target)
    candidates = []
    if idx < len(available):
        candidates.append(int(available[idx]))
    if idx > 0:
        candidates.append(int(available[idx - 1]))
    if not candidates:
        return None
    best = min(candidates, key=lambda x: abs(x - target))
    if abs(best - target) <= max_delta_ns:
        return best
    return None


def draw_translucent_panel(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, alpha: float = 0.45) -> None:
    overlay = img.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 0, 0), -1)
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)


def clamp_int(x: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, x)))


def actor_score(row: pd.Series) -> Tuple[float, str]:
    """
    Simple, transparent heuristic score.
    Uses:
      - category weight
      - distance to ego
      - object volume
      - amount of LiDAR support (num interior pts)
    """
    category = str(row["category"])
    base = CATEGORY_WEIGHTS.get(category, CATEGORY_WEIGHTS["UNKNOWN"])

    x = float(row["tx_m"])
    y = float(row["ty_m"])
    z = float(row["tz_m"])
    dist = math.sqrt(x * x + y * y + z * z)

    length = float(row["length_m"])
    width = float(row["width_m"])
    height = float(row["height_m"])
    volume = max(length * width * height, 0.01)

    interior_pts = float(row.get("num_interior_pts", 0.0))

    # Distance emphasis: nearer objects are usually more relevant/complex.
    if dist < 10:
        proximity = 1.0
    elif dist < 20:
        proximity = 0.7
    elif dist < 35:
        proximity = 0.4
    elif dist < 50:
        proximity = 0.2
    else:
        proximity = 0.0

    # Size emphasis: very large objects matter more, but keep bounded.
    size_boost = min(volume / 30.0, 0.8)

    # LiDAR support: a weak confidence-style factor.
    support_boost = min(interior_pts / 30.0, 0.5)

    score = base * (1.0 + proximity + size_boost + support_boost)

    reason = (
        f"{category} | +{score:.1f} "
        f"(base={base:.1f}, d={dist:.1f}m, prox={proximity:.1f}, "
        f"size={size_boost:.1f}, pts={support_boost:.1f})"
    )
    return score, reason


def project_cuboid_to_image(row: pd.Series, calib: CameraCalibration) -> Tuple[np.ndarray, np.ndarray]:
    corners_ego = cuboid_corners_ego(
        length_m=float(row["length_m"]),
        width_m=float(row["width_m"]),
        height_m=float(row["height_m"]),
        qw=float(row["qw"]),
        qx=float(row["qx"]),
        qy=float(row["qy"]),
        qz=float(row["qz"]),
        tx_m=float(row["tx_m"]),
        ty_m=float(row["ty_m"]),
        tz_m=float(row["tz_m"]),
    )
    corners_cam = transform_points(calib.cam_T_ego, corners_ego)
    uv, valid = project_points(calib.K, corners_cam)
    return uv, valid


def draw_projected_cuboid(img: np.ndarray, uv: np.ndarray, valid: np.ndarray, color: Tuple[int, int, int], thickness: int = 2) -> bool:
    """
    Draws cuboid edges if enough corners are in front of the camera.
    Returns True if anything was drawn.
    """
    drawn = False
    for a, b in BOX_EDGES:
        if valid[a] and valid[b]:
            p1 = tuple(np.round(uv[a]).astype(int))
            p2 = tuple(np.round(uv[b]).astype(int))
            cv2.line(img, p1, p2, color, thickness, cv2.LINE_AA)
            drawn = True
    return drawn


def draw_actor_label(img: np.ndarray, uv: np.ndarray, valid: np.ndarray, label: str, color: Tuple[int, int, int]) -> None:
    if not np.any(valid):
        return
    pts = uv[valid]
    x = int(np.nanmin(pts[:, 0]))
    y = int(np.nanmin(pts[:, 1])) - 8
    y = max(18, y)

    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    x = max(2, min(img.shape[1] - tw - 4, x))
    y0 = max(2, y - th - 4)
    cv2.rectangle(img, (x, y0), (x + tw + 4, y0 + th + 6), (0, 0, 0), -1)
    cv2.putText(img, label, (x + 2, y0 + th + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)


def overlay_score_panel(
    img: np.ndarray,
    camera_name: str,
    frame_idx: int,
    num_frames: int,
    actor_count: int,
    frame_score: float,
    running_avg: float,
) -> None:
    panel_w = 460
    panel_h = 150
    draw_translucent_panel(img, 15, 15, 15 + panel_w, 15 + panel_h, alpha=0.45)

    lines = [
        f"Camera: {camera_name}",
        f"Frame: {frame_idx + 1}/{num_frames}",
        f"Actors in view: {actor_count}",
        f"Frame complexity: {frame_score:.2f}",
        f"Running average: {running_avg:.2f}",
    ]

    y = 45
    for line in lines:
        cv2.putText(img, line, (30, y), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
        y += 25


def resolve_file(log_dir: Path, names: List[str]) -> Path:
    for name in names:
        p = log_dir / name
        if p.exists():
            return p
    raise FileNotFoundError(f"Could not find any of these files in {log_dir}: {names}")


def main(log_dir: Path, camera_name: str, output_video: Path, output_json: Path, font_scale: float = 0.45, skip_labels: bool = True) -> bool:
    max_delta_ns = 60 * 1e6 # Max timestamp mismatch for annotation/image pairing converted to ns

    annotations_path = resolve_file(log_dir, ["annotations.feather"])
    intrinsics_path = resolve_file(log_dir, ["calibration/intrinsics.feather"])
    extrinsics_path = resolve_file(log_dir, ["calibration/egovehicle_SE3_sensor.feather"])
    poses_path = resolve_file(log_dir, ["city_SE3_egovehicle.feather", "poses.feather"])

    print(f"Loading annotations from: {annotations_path}")
    annotations = load_annotations(annotations_path)

    print(f"Loading calibration from: {intrinsics_path} and {extrinsics_path}")
    calib = load_calibration(intrinsics_path, extrinsics_path, camera_name)

    print(f"Loading poses from: {poses_path}")
    poses = load_poses(poses_path)
    if not poses:
        raise ValueError("No poses found in poses.feather")

    print(f"Locating images for camera: {camera_name}")
    image_paths = list_camera_images(log_dir, camera_name)
    image_ts = np.array([parse_image_timestamp_ns(p) for p in image_paths], dtype=np.int64)

    ann_ts = np.sort(annotations["timestamp_ns"].unique().astype(np.int64))
    pose_ts = np.array(sorted(poses.keys()), dtype=np.int64)

    ann_by_ts = {int(ts): df for ts, df in annotations.groupby("timestamp_ns")}

    output_video.parent.mkdir(parents=True, exist_ok=True)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    writer = None
    frame_scores: List[float] = []
    frame_vehicle_counts: List[int] = []
    frame_pedestrian_counts: List[int] = []
    processed_frames = 0

    try:
        for frame_idx, img_path in enumerate(image_paths):
            ts_img = int(image_ts[frame_idx])

            # Find nearest annotation timestamp and pose timestamp.
            ts_ann = nearest_timestamp(ts_img, ann_ts, max_delta_ns)
            ts_pose = nearest_timestamp(ts_img, pose_ts, max_delta_ns)

            img = cv2.imread(str(img_path))
            if img is None:
                print(f"Warning: failed to read image {img_path}")
                continue

            if writer is None:
                h, w = img.shape[:2]
                writer = imageio.get_writer(
                    output_video,
                    fps=20,
                    codec="libx264",
                    quality=8,
                    ffmpeg_log_level="error",
                    output_params=["-preset", "ultrafast"],
                )

            if ts_ann is None or ts_pose is None:
                overlay_score_panel(
                    img=img,
                    camera_name=camera_name,
                    frame_idx=frame_idx,
                    num_frames=len(image_paths),
                    actor_count=0,
                    frame_score=0.0,
                    running_avg=float(np.mean(frame_scores)) if frame_scores else 0.0,
                )
                cv2.putText(
                    img,
                    "No matching annotation/pose timestamp",
                    (30, img.shape[0] - 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
                writer.append_data(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                processed_frames += 1
                continue

            # If desired later, you can use poses[ts_pose] for world/ego alignment.
            # For annotation projection into camera, cuboids are already in ego frame,
            # so pose is not needed unless you compute temporal tracking in world coords.
            _pose = poses[ts_pose]

            frame_ann = ann_by_ts.get(int(ts_ann))
            if frame_ann is None:
                continue

            frame_score = 0.0
            visible_actor_count = 0
            frame_vehicles = 0
            frame_peds = 0

            for _, row in frame_ann.iterrows():
                category = str(row["category"])
                color = LINE_COLORS.get(category, LINE_COLORS["UNKNOWN"])

                uv, valid = project_cuboid_to_image(row, calib)

                # Require at least 2 projected corners in front of camera.
                if np.sum(valid) < 2:
                    continue

                # Optionally, filter out boxes that are fully off-screen.
                pts_valid = uv[valid]
                xs = pts_valid[:, 0]
                ys = pts_valid[:, 1]
                if np.all(xs < 0) or np.all(xs >= img.shape[1]) or np.all(ys < 0) or np.all(ys >= img.shape[0]):
                    continue

                drawn = draw_projected_cuboid(img, uv, valid, color=color, thickness=2)
                if not drawn:
                    continue

                visible_actor_count += 1
                if category in VEHICLE_CATEGORIES:
                    frame_vehicles += 1
                elif category in PEDESTRIAN_CATEGORIES:
                    frame_peds += 1

                score, reason = actor_score(row)
                frame_score += score

                if not skip_labels:
                    draw_actor_label(img, uv, valid, reason[:110], color)

            frame_scores.append(frame_score)
            frame_vehicle_counts.append(frame_vehicles)
            frame_pedestrian_counts.append(frame_peds)
            running_avg = float(np.mean(frame_scores))

            overlay_score_panel(
                img=img,
                camera_name=camera_name,
                frame_idx=frame_idx,
                num_frames=len(image_paths),
                actor_count=visible_actor_count,
                frame_score=frame_score,
                running_avg=running_avg,
            )

            writer.append_data(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            processed_frames += 1

    finally:
        if writer is not None:
            writer.close()

    summary = {
        "log_dir": str(log_dir),
        "log_id": log_dir.name,
        "city": get_city_from_log(log_dir),
        "camera_name": camera_name,
        "processed_frames": processed_frames,
        "average_complexity_score": float(np.mean(frame_scores)) if frame_scores else 0.0,
        "max_frame_complexity": float(np.max(frame_scores)) if frame_scores else 0.0,
        "min_frame_complexity": float(np.min(frame_scores)) if frame_scores else 0.0,
        "vehicle_count": float(np.mean(frame_vehicle_counts)) if frame_vehicle_counts else 0.0,
        "pedestrian_count": float(np.mean(frame_pedestrian_counts)) if frame_pedestrian_counts else 0.0,
        "frame_scores": [float(x) for x in frame_scores],
        "notes": {
            "score_definition": "Per-frame score is the sum of per-actor heuristic scores over visible projected cuboids.",
            "per_actor_terms": ["category weight", "distance to ego", "cuboid volume", "lidar interior point count"],
            "timestamp_matching": "nearest annotation and pose timestamps within 60 ms",
        },
    }

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\nDone.")
    print(f"Annotated video: {output_video}")
    print(f"Summary JSON:    {output_json}")
    print(f"Average score:   {summary['average_complexity_score']:.3f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render AV2 Sensor Dataset camera-view complexity video.")
    parser.add_argument("--log-dir", required=True,
                        help="Path to one AV2 sensor log directory, or a log UUID resolved against TRAIN_DIR.")
    parser.add_argument("--camera", default="ring_front_center")
    parser.add_argument("--output-video", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--font-scale", type=float, default=0.45)
    parser.add_argument("--skip-labels", action="store_true")
    args = parser.parse_args()

    candidate = Path(args.log_dir)
    if candidate.exists():
        log_dir = candidate
    else:
        log_dir = TRAIN_DIR / args.log_dir
        if not log_dir.exists():
            raise FileNotFoundError(
                f"Log directory not found: tried '{candidate}' and '{log_dir}'"
            )

    main(log_dir, args.camera, args.output_video, args.output_json, args.font_scale, args.skip_labels)