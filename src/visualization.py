"""Static (matplotlib) and interactive (plotly) figures.

Coordinate axes are shown exactly as stored in the file. No axis swaps,
sign flips, or unit conversions are applied here — preprocessing owns any
transformation, and none is currently justified by the data.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import plotly.graph_objects as go
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (registers 3D projection)

from .analysis import PointSummary, displacement_from_start, speed_over_time
from .data_loader import TrackingData

POINT_LABELS = {"head": "Head", "left": "Left hand", "right": "Right hand"}
POINT_COLORS = {"head": "#1f77b4", "left": "#d62728", "right": "#2ca02c"}
UNITS_NOTE = (
    "Coordinates are the file's source units (plausibly meters, not confirmed); "
    "gaps = inactive tracking."
)


def _segments(t_s: np.ndarray, positions: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """Split a trajectory into contiguous runs of valid samples (gap breaks)."""
    valid = np.isfinite(positions).all(axis=1)
    segments: list[tuple[np.ndarray, np.ndarray]] = []
    start: int | None = None
    for i, ok in enumerate(valid):
        if ok and start is None:
            start = i
        elif not ok and start is not None:
            segments.append((t_s[start:i], positions[start:i]))
            start = None
    if start is not None:
        segments.append((t_s[start:], positions[start:]))
    return segments


def plot_motion_statistics(
    data: TrackingData,
    summaries: list[PointSummary],
    out_path: str | Path,
) -> Path:
    """2x2 figure: speed over time, displacement, path length, summary table."""
    t_s = data.t_s
    fig, axes = plt.subplots(2, 2, figsize=(14, 8.5))

    ax = axes[0, 0]
    for point in ("head", "left", "right"):
        ax.plot(
            t_s,
            speed_over_time(data.positions(point), t_s),
            label=POINT_LABELS[point],
            color=POINT_COLORS[point],
            linewidth=1,
        )
    ax.set_title("Speed over time")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Speed (source units/s)")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)

    ax = axes[0, 1]
    for point in ("head", "left", "right"):
        ax.plot(
            t_s,
            displacement_from_start(data.positions(point)),
            label=POINT_LABELS[point],
            color=POINT_COLORS[point],
            linewidth=1,
        )
    ax.set_title("Displacement from first valid position")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Distance (source units)")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)

    ax = axes[1, 0]
    names = [POINT_LABELS[s.point] for s in summaries]
    lengths = [s.path_length for s in summaries]
    bars = ax.bar(names, lengths, color=[POINT_COLORS[s.point] for s in summaries])
    ax.bar_label(bars, fmt="%.3f")
    ax.set_title("Total path length")
    ax.set_ylabel("Distance (source units)")
    ax.grid(True, axis="y", alpha=0.3)

    ax = axes[1, 1]
    ax.axis("off")
    header = f"{'point':<11}{'active':>8}{'mean v':>9}{'median v':>10}{'max v':>9}{'range x/y/z':>22}"
    lines = [header, "-" * len(header)]
    for s in summaries:
        lines.append(
            f"{s.point:<11}{s.active_samples:>8}{s.mean_speed:>9.3f}"
            f"{s.median_speed:>10.3f}{s.max_speed:>9.3f}"
            f"{f'{s.range_x:.3f}/{s.range_y:.3f}/{s.range_z:.3f}':>22}"
        )
    timing = data.frame["t_s"].diff().dropna()
    lines.append("")
    lines.append(f"samples: {data.n_records}   duration: {data.duration_s:.1f} s   "
                 f"median rate: {1.0 / timing.median():.1f} Hz")
    ax.text(0.0, 1.0, "\n".join(lines), family="monospace", fontsize=9, va="top")
    ax.set_title("Summary statistics (speeds: source units/s)")

    fig.suptitle("VR tracking: motion statistics", fontsize=13)
    fig.text(0.5, 0.005, UNITS_NOTE, ha="center", fontsize=8, style="italic")
    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    out_path = Path(out_path)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def plot_trajectory_3d(
    data: TrackingData,
    png_path: str | Path,
    html_path: str | Path,
) -> tuple[Path, Path]:
    """3D spatial trajectories of head, left hand, and right hand.

    Writes a static PNG (README example) and a self-contained interactive
    HTML (time shown on hover). Gaps are rendered as breaks, never
    interpolated. Axes are the raw stored coordinates, unmodified.
    """
    positions = {p: data.positions(p) for p in POINT_LABELS}

    def axis_range(axis: int) -> float:
        spans = []
        for pos in positions.values():
            col = pos[:, axis]
            col = col[np.isfinite(col)]
            if col.size:
                spans.append(float(col.max() - col.min()))
        return max(max(spans, default=0.0), 1e-6)

    box = [axis_range(axis) for axis in range(3)]

    handles = [
        plt.Line2D([], [], color=POINT_COLORS[p], label=POINT_LABELS[p])
        for p in POINT_LABELS
    ]
    fig = plt.figure(figsize=(9, 7.5))
    ax = fig.add_subplot(111, projection="3d")
    for point in POINT_LABELS:
        for _, pos_seg in _segments(data.t_s, positions[point]):
            ax.plot(pos_seg[:, 0], pos_seg[:, 1], pos_seg[:, 2],
                    color=POINT_COLORS[point], linewidth=1.2)
    ax.set_xlabel("x (source units)")
    ax.set_ylabel("y (source units)")
    ax.set_zlabel("z (source units)")
    ax.set_title("Head and hand spatial trajectories")
    ax.set_box_aspect(box)
    ax.legend(handles=handles, loc="upper left")
    fig.text(0.5, 0.01, UNITS_NOTE, ha="center", fontsize=8, style="italic")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    png_path = Path(png_path)
    fig.savefig(png_path, dpi=150)
    plt.close(fig)

    def rgb(hex_color: str) -> str:
        return f"rgb({int(hex_color[1:3], 16)},{int(hex_color[3:5], 16)},{int(hex_color[5:7], 16)})"

    fig3d = go.Figure()
    for point, label in POINT_LABELS.items():
        pos = positions[point]
        fig3d.add_trace(
            go.Scatter3d(
                x=pos[:, 0],
                y=pos[:, 1],
                z=pos[:, 2],
                customdata=data.t_s,
                mode="lines",
                name=label,
                line=dict(color=rgb(POINT_COLORS[point]), width=4),
                hovertemplate="x=%{x:.3f}<br>y=%{y:.3f}<br>z=%{z:.3f}"
                              "<br>t=%{customdata:.2f} s<extra></extra>",
            )
        )
    fig3d.update_layout(
        title="Head and hand spatial trajectories",
        scene=dict(
            xaxis_title="x (source units)",
            yaxis_title="y (source units)",
            zaxis_title="z (source units)",
        ),
        margin=dict(l=0, r=0, b=0, t=40),
        legend=dict(yanchor="top", y=0.99, x=0.01),
    )
    html_path = Path(html_path)
    fig3d.write_html(html_path, include_plotlyjs=True)
    return png_path, html_path
