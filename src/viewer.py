"""Interactive 3D viewer: export playback data and assemble the web bundle.

Produces a self-contained folder (default ``output/viewer``) that runs from
``file://`` with no server and no build step:

* ``index.html`` / ``app.js`` / ``lib/`` — copied from the source ``viewer/``
  directory (three.js r147 UMD build + OrbitControls, vendored locally).
* ``data.js`` — downsampled playback payload (Float32 arrays, base64-encoded).

Rendering assumptions are documented in the README; the joint topology and
quaternion layout were verified against the data (rigid-bone CV test, face
axis points at the hands in 100% of frames).
"""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

import numpy as np

from .data_loader import TrackingData, TrackingDataError

JOINT_COUNT = 26
HEAD_STRIDE = 7  # x, y, z, qx, qy, qz, qw
DEFAULT_FPS = 30

_SOURCE_DIR = Path(__file__).resolve().parent.parent / "viewer"
_STATIC_NAMES = ("index.html", "app.js")


def downsample_indices(t_s: np.ndarray, fps: int) -> np.ndarray:
    """Indices keeping the first sample and then >= 1/fps spacing."""
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    min_dt = 1.0 / fps
    keep = [0]
    last = t_s[0]
    for i in range(1, len(t_s)):
        if t_s[i] - last >= min_dt:
            keep.append(i)
            last = t_s[i]
    return np.asarray(keep, dtype=np.int64)


def _encode(array: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(array, dtype=np.float32)
    return base64.b64encode(contiguous.tobytes()).decode("ascii")


def build_payload(data: TrackingData, fps: int = DEFAULT_FPS) -> dict:
    """Downsample and pack the playback payload for the viewer."""
    if data.n_joints != JOINT_COUNT:
        raise TrackingDataError(
            f"viewer expects {JOINT_COUNT} hand joints, data has {data.n_joints}"
        )
    idx = downsample_indices(data.t_s, fps)
    head = np.hstack(
        [data.frame[["head_x", "head_y", "head_z"]].to_numpy()[idx],
         data.head_quat[idx]]
    ).astype(np.float32)
    left = data.left_joints[idx].reshape(len(idx), -1)
    right = data.right_joints[idx].reshape(len(idx), -1)
    times = data.t_s[idx].astype(np.float32)
    return {
        "version": 1,
        "count": int(len(idx)),
        "fps": fps,
        "duration": float(data.t_s[-1] - data.t_s[0]),
        "sourceRecords": data.n_records,
        "jointCount": data.n_joints,
        "headStride": HEAD_STRIDE,
        "unitsNote": (
            "Coordinates are the file's source units (plausibly meters, "
            "not confirmed). Gaps in a hand hide it — positions are never "
            "interpolated."
        ),
        "times": _encode(times),
        "head": _encode(head),
        "left": _encode(left),
        "right": _encode(right),
    }


def build_viewer(
    data: TrackingData,
    out_dir: str | Path,
    *,
    fps: int = DEFAULT_FPS,
    assets_dir: str | Path | None = None,
) -> Path:
    """Assemble the complete viewer folder: static assets + ``data.js``."""
    assets = Path(assets_dir) if assets_dir else _SOURCE_DIR
    missing = [name for name in (*_STATIC_NAMES, "lib") if not (assets / name).exists()]
    if missing:
        raise FileNotFoundError(f"viewer assets missing in {assets}: {', '.join(missing)}")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name in _STATIC_NAMES:
        shutil.copy2(assets / name, out / name)
    shutil.copytree(assets / "lib", out / "lib", dirs_exist_ok=True)

    payload = build_payload(data, fps=fps)
    (out / "data.js").write_text(
        "window.VIEWER_DATA = " + json.dumps(payload) + ";\n",
        encoding="utf-8",
    )
    return out
