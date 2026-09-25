"""Command-line entry point: parse -> analyze -> visualize.

Run from the repository root:

    python -m src.main --input trackingData_20260505_165740.txt --output output
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis import summarize, timing_summary
from .data_loader import TrackingDataError, load_tracking
from .viewer import build_viewer
from .visualization import plot_motion_statistics, plot_trajectory_3d


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.main",
        description="Visualize VR tracking data: motion statistics and 3D "
                    "head/hand trajectories.",
    )
    parser.add_argument(
        "--input",
        default="trackingData_20260505_165740.txt",
        help="tracking data file (JSON Lines) [default: %(default)s]",
    )
    parser.add_argument(
        "--output",
        default="output",
        help="directory for generated figures and stats [default: %(default)s]",
    )
    return parser


def run(input_path: str | Path, output_dir: str | Path) -> dict:
    data = load_tracking(input_path)
    summaries = summarize(data)
    timing = timing_summary(data)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    motion_png = plot_motion_statistics(data, summaries, out / "motion_statistics.png")
    traj_png, traj_html = plot_trajectory_3d(
        data, out / "trajectory_3d.png", out / "trajectory_3d.html"
    )
    viewer_dir = build_viewer(data, out / "viewer")

    result = {
        "input": str(input_path),
        "records": data.n_records,
        "timing": timing,
        "points": [s.to_dict() for s in summaries],
        "outputs": [str(motion_png), str(traj_png), str(traj_html), str(viewer_dir)],
        "viewer": str(viewer_dir),
    }
    stats_path = out / "summary_stats.json"
    stats_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["outputs"].append(str(stats_path))
    return result


def _print_summary(result: dict) -> None:
    timing = result["timing"]
    print(f"records: {result['records']}   duration: {timing['duration_s']:.1f} s   "
          f"median rate: {timing['median_rate_hz']:.1f} Hz   "
          f"non-positive dt: {timing['nonpositive_dt_count']}")
    for point in result["points"]:
        inactive = point["total_samples"] - point["active_samples"]
        print(f"  {point['point']:<6} path={point['path_length']:.3f}  "
              f"mean v={point['mean_speed']:.3f}  median v={point['median_speed']:.3f}  "
              f"max v={point['max_speed']:.3f}  inactive={inactive}")
    print("outputs:")
    for path in result["outputs"]:
        print(f"  {path}")
    print(f"  interactive viewer: open {result['viewer']}/index.html in a browser")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args.input, args.output)
    except (FileNotFoundError, TrackingDataError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
