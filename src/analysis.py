"""Motion metrics derived from normalized tracking data.

All metrics use ``timeStampNs``-based seconds and respect NaN gaps:
segments that touch an inactive-hand gap are never counted, and no
positions are fabricated.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .data_loader import TrackingData

POINTS = ("head", "left", "right")


@dataclass(frozen=True)
class PointSummary:
    point: str
    active_samples: int
    total_samples: int
    path_length: float
    mean_speed: float
    median_speed: float
    max_speed: float
    range_x: float
    range_y: float
    range_z: float

    def to_dict(self) -> dict[str, float | int | str]:
        return asdict(self)


def speed_over_time(positions: np.ndarray, t_s: np.ndarray) -> np.ndarray:
    """Speed between consecutive samples; NaN where either endpoint is a gap
    or the time delta is not positive."""
    speed = np.full(len(t_s), np.nan)
    if len(t_s) < 2:
        return speed
    dt = np.diff(t_s)
    step = np.linalg.norm(np.diff(positions, axis=0), axis=1)
    valid = (dt > 0) & np.isfinite(step)
    speed[1:] = np.where(valid, step / np.where(valid, dt, 1.0), np.nan)
    return speed


def displacement_from_start(positions: np.ndarray) -> np.ndarray:
    """Distance from the first valid position; NaN while in a gap."""
    out = np.full(len(positions), np.nan)
    valid = np.isfinite(positions).all(axis=1)
    if not valid.any():
        return out
    start = positions[valid][0]
    out[valid] = np.linalg.norm(positions[valid] - start, axis=1)
    return out


def path_length(positions: np.ndarray) -> float:
    """Total traveled distance, counting only consecutive valid samples."""
    if len(positions) < 2:
        return 0.0
    step = np.linalg.norm(np.diff(positions, axis=0), axis=1)
    return float(step[np.isfinite(step)].sum())


def summarize_point(point: str, positions: np.ndarray, t_s: np.ndarray) -> PointSummary:
    speed = speed_over_time(positions, t_s)
    finite_speed = speed[np.isfinite(speed)]
    valid = np.isfinite(positions).all(axis=1)
    if not finite_speed.size:
        mean_speed = median_speed = max_speed = float("nan")
    else:
        mean_speed = float(finite_speed.mean())
        median_speed = float(np.median(finite_speed))
        max_speed = float(finite_speed.max())
    if valid.any():
        span = positions[valid].max(axis=0) - positions[valid].min(axis=0)
        range_x, range_y, range_z = map(float, span)
    else:
        range_x = range_y = range_z = float("nan")
    return PointSummary(
        point=point,
        active_samples=int(valid.sum()),
        total_samples=len(positions),
        path_length=path_length(positions),
        mean_speed=mean_speed,
        median_speed=median_speed,
        max_speed=max_speed,
        range_x=range_x,
        range_y=range_y,
        range_z=range_z,
    )


def summarize(data: TrackingData) -> list[PointSummary]:
    t_s = data.t_s
    return [summarize_point(point, data.positions(point), t_s) for point in POINTS]


def timing_summary(data: TrackingData) -> dict[str, float]:
    """Sampling statistics from timeStampNs deltas."""
    dt = np.diff(data.t_s)
    positive = dt[dt > 0]
    return {
        "duration_s": data.duration_s,
        "samples": data.n_records,
        "median_dt_s": float(np.median(positive)) if positive.size else float("nan"),
        "min_dt_s": float(positive.min()) if positive.size else float("nan"),
        "max_dt_s": float(dt.max()) if dt.size else float("nan"),
        "median_rate_hz": float(1.0 / np.median(positive)) if positive.size else float("nan"),
        "nonpositive_dt_count": int((dt <= 0).sum()),
    }
