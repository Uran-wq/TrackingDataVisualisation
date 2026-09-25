"""Tests for the interactive viewer export (src/viewer.py)."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src.data_loader import TrackingDataError, load_tracking
from src.viewer import build_payload, build_viewer, downsample_indices

from tests.test_data_loader import make_record, write_file


def test_downsample_indices_spacing():
    t = np.arange(0, 1.0, 1 / 90)  # 90 Hz -> 30 Hz
    idx = downsample_indices(t, fps=30)
    assert idx[0] == 0
    assert len(idx) >= 20
    assert np.all(np.diff(t[idx]) >= 1 / 30 - 1e-9)


def test_downsample_indices_rejects_bad_fps():
    with pytest.raises(ValueError, match="positive"):
        downsample_indices(np.array([0.0, 1.0]), fps=0)


def _fixture_data(tmp_path: Path):
    records = [
        make_record(10_000_000, right_active=0),
        make_record(50_000_000, right_active=1),
        make_record(100_000_000, right_active=1),
    ]
    return load_tracking(write_file(tmp_path / "v.txt", records))


def test_build_payload_shapes_and_gaps(tmp_path: Path):
    data = _fixture_data(tmp_path)
    payload = build_payload(data, fps=50)
    times = np.frombuffer(base64.b64decode(payload["times"]), dtype=np.float32)
    head = np.frombuffer(base64.b64decode(payload["head"]), dtype=np.float32)
    left = np.frombuffer(base64.b64decode(payload["left"]), dtype=np.float32)
    right = np.frombuffer(base64.b64decode(payload["right"]), dtype=np.float32)
    n = payload["count"]
    assert n == 3  # all three fixture frames survive at 50 fps
    assert n == len(times) == head.size // 7 == left.size // 78 == right.size // 78
    assert np.all(np.diff(times) >= 1 / 50 - 1e-6)
    assert payload["duration"] == pytest.approx(0.09)
    assert np.isfinite(head).all()
    # inactive first record survives as NaN, never interpolated
    assert np.isnan(right[0:78]).all()
    assert np.isfinite(right[78:]).all()


def test_build_payload_rejects_wrong_joint_count(tmp_path: Path):
    data = _fixture_data(tmp_path)
    with pytest.raises(TrackingDataError, match="26 hand joints"):
        build_payload(replace(data, n_joints=5))


def test_build_viewer_assembles_folder(tmp_path: Path):
    data = _fixture_data(tmp_path)
    out = build_viewer(data, tmp_path / "site")
    for name in ("index.html", "app.js", "data.js", "lib/three.min.js",
                 "lib/OrbitControls.js"):
        assert (out / name).is_file(), name
    text = (out / "data.js").read_text(encoding="utf-8")
    assert text.startswith("window.VIEWER_DATA = ")
    payload = json.loads(text[len("window.VIEWER_DATA = "):].rstrip().rstrip(";"))
    assert payload["version"] == 1
    assert payload["jointCount"] == 26
    assert payload["sourceRecords"] == data.n_records


def test_build_viewer_missing_assets(tmp_path: Path):
    data = _fixture_data(tmp_path)
    with pytest.raises(FileNotFoundError, match="assets missing"):
        build_viewer(data, tmp_path / "site", assets_dir=tmp_path / "nope")
