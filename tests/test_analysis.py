"""Tests for motion math: speed, displacement, path length, gap handling."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.analysis import (
    displacement_from_start,
    path_length,
    speed_over_time,
    summarize,
    summarize_point,
    timing_summary,
)
from src.data_loader import load_tracking
from tests.test_data_loader import make_record, write_file

NAN = np.nan


class TestSpeed:
    def test_constant_motion(self):
        pos = np.array([[0.0, 0, 0], [3.0, 4, 0], [6.0, 8, 0]])
        t = np.array([0.0, 1.0, 2.0])
        speed = speed_over_time(pos, t)
        np.testing.assert_allclose(speed, [NAN, 5.0, 5.0], equal_nan=True)

    def test_zero_dt_yields_nan(self):
        pos = np.array([[0.0, 0, 0], [1.0, 0, 0], [2.0, 0, 0]])
        t = np.array([0.0, 1.0, 1.0])
        speed = speed_over_time(pos, t)
        assert np.isnan(speed[0])
        assert speed[1] == pytest.approx(1.0)
        assert np.isnan(speed[2])  # dt == 0 must not divide

    def test_gap_breaks_speed(self):
        pos = np.array([[0.0, 0, 0], [NAN, NAN, NAN], [3.0, 4, 0]])
        t = np.array([0.0, 1.0, 2.0])
        speed = speed_over_time(pos, t)
        assert np.isnan(speed).all()  # no speed may be derived across a gap

    def test_single_sample(self):
        speed = speed_over_time(np.array([[0.0, 0, 0]]), np.array([0.0]))
        assert speed.shape == (1,)
        assert np.isnan(speed[0])


class TestPathLength:
    def test_straight_line(self):
        pos = np.array([[0.0, 0, 0], [1.0, 0, 0], [1.0, 1.0, 0]])
        assert path_length(pos) == pytest.approx(2.0)

    def test_gap_is_not_bridged(self):
        pos = np.array([[0.0, 0, 0], [1.0, 0, 0], [NAN, NAN, NAN], [10.0, 0, 0]])
        # Only the 0->1 segment counts; the jump across the gap must not.
        assert path_length(pos) == pytest.approx(1.0)

    def test_all_nan(self):
        pos = np.full((4, 3), NAN)
        assert path_length(pos) == 0.0


class TestDisplacement:
    def test_relative_to_first_valid(self):
        pos = np.array([[NAN, NAN, NAN], [5.0, 0, 0], [8.0, 4, 0]])
        disp = displacement_from_start(pos)
        assert np.isnan(disp[0])
        assert disp[1] == pytest.approx(0.0)
        assert disp[2] == pytest.approx(5.0)


class TestSummaries:
    def test_summarize_point_all_gap(self):
        pos = np.full((5, 3), NAN)
        s = summarize_point("right", pos, np.arange(5, dtype=float))
        assert s.active_samples == 0
        assert s.path_length == 0.0
        assert np.isnan(s.mean_speed)

    def test_timing_summary_counts(self, tmp_path: Path):
        path = write_file(
            tmp_path / "t.txt",
            [make_record(1_000_000_000), make_record(1_011_000_000),
             make_record(1_022_000_000)],
        )
        data = load_tracking(path)
        timing = timing_summary(data)
        assert timing["samples"] == 3
        assert timing["duration_s"] == pytest.approx(0.022)
        assert timing["nonpositive_dt_count"] == 0
        assert timing["median_rate_hz"] == pytest.approx(1 / 0.011, rel=1e-6)

    def test_summarize_covers_all_points(self, tmp_path: Path):
        path = write_file(tmp_path / "s.txt", [make_record(10), make_record(20)])
        summaries = summarize(load_tracking(path))
        assert [s.point for s in summaries] == ["head", "left", "right"]
        assert all(s.active_samples == 2 for s in summaries)


def test_end_to_end_smoke(tmp_path: Path):
    """run() on a tiny fixture produces every declared output."""
    from src.main import run

    path = write_file(
        tmp_path / "smoke.txt",
        [
            make_record(1_000_000_000, right_active=0),
            make_record(1_012_000_000),
            make_record(1_024_000_000),
        ],
    )
    result = run(path, tmp_path / "out")
    assert result["records"] == 3
    for file in result["outputs"]:
        path_out = Path(file)
        if path_out.name == "viewer":
            assert (path_out / "index.html").is_file()
            assert (path_out / "data.js").is_file()
        else:
            assert path_out.is_file(), file
    stats = json.loads((tmp_path / "out" / "summary_stats.json").read_text("utf-8"))
    assert stats["records"] == 3
