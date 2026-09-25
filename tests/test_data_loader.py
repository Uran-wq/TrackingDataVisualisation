"""Tests for the fragile parsing layer: locale decimals, timestamps, gaps."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.data_loader import (
    TrackingData,
    TrackingDataError,
    load_tracking,
    parse_locale_numbers,
)

# A real Head.pose value from trackingData_20260505_165740.txt (line 2).
REAL_POSE = (
    "-0,08517717,-0,02745685,-0,0058761,0,162562191,"
    "-0,2861428,-0,116477557,-0,9370853"
)


def pose_str(x: str, y: str, z: str) -> str:
    """Build a 14-token (7-value) pose string in the file's locale format:
    x, y, z, then four dummy quaternion values."""
    return ",".join([x, y, z, "0,0", "0,0", "0,0", "0,1"])


def make_record(
    ts: int,
    head_pose: str = pose_str("-0,10", "-0,20", "-0,30"),
    left_active: int = 1,
    right_active: int = 1,
    left_p: str = pose_str("-0,40", "-0,50", "-0,60"),
    right_p: str = pose_str("0,40", "-0,50", "-0,60"),
    **extra,
) -> dict:
    left_joint = {"p": left_p, "s": 15.0, "r": 0.0}
    right_joint = {"p": right_p, "s": 0.0, "r": 0.0}
    return {
        "predictTime": 1.0,
        "appState": {"focus": True},
        "Head": {"pose": head_pose, "status": 3},
        "Hand": {
            "leftHand": {
                "isActive": left_active,
                "count": 26,
                "HandJointLocations": [left_joint] * 26,
            },
            "rightHand": {
                "isActive": right_active,
                "count": 26,
                "HandJointLocations": [right_joint] * 26,
            },
        },
        "Body": {"joints": []},
        "timeStampNs": ts,
        "Input": 2,
        **extra,
    }


META_LINE = {
    "notice": "This is the timestamp and head pose information when obtaining the image for the first frame.",
    "timeStampNs": 1_000_000_000,
    "cameraExtrinsics": "[...]",
    "cameraIntrinsics": "[1079.5, 404.5, 1373.668, 686.868]",
}


def write_file(path: Path, records: list[dict], include_meta: bool = True) -> Path:
    lines = []
    if include_meta:
        lines.append(json.dumps(META_LINE))
    lines.extend(json.dumps(r) for r in records)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestParseLocaleNumbers:
    def test_pair_merging(self):
        assert parse_locale_numbers("-0,08517717,0,5") == [-0.08517717, 0.5]

    def test_real_pose(self):
        values = parse_locale_numbers(REAL_POSE)
        assert len(values) == 7
        assert values[0] == pytest.approx(-0.08517717)
        assert values[6] == pytest.approx(-0.9370853)

    def test_leading_zero_fraction(self):
        assert parse_locale_numbers("0,00140838465") == [0.00140838465]

    def test_odd_token_count_rejected(self):
        with pytest.raises(TrackingDataError):
            parse_locale_numbers("-0,085,0,9,x")

    def test_too_few_tokens_rejected(self):
        with pytest.raises(TrackingDataError):
            parse_locale_numbers("123")

    def test_non_numeric_rejected(self):
        with pytest.raises(TrackingDataError):
            parse_locale_numbers("abc,def")


class TestLoadTracking:
    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_tracking(tmp_path / "nope.txt")

    def test_empty_file(self, tmp_path: Path):
        (tmp_path / "empty.txt").write_text("", encoding="utf-8")
        with pytest.raises(TrackingDataError, match="no tracking records"):
            load_tracking(tmp_path / "empty.txt")

    def test_malformed_json_reports_line(self, tmp_path: Path):
        path = tmp_path / "bad.txt"
        path.write_text(
            json.dumps(META_LINE) + "\n" + json.dumps(make_record(10)) + "\n{not json\n",
            encoding="utf-8",
        )
        with pytest.raises(TrackingDataError, match="line 3"):
            load_tracking(path)

    def test_metadata_and_record_counts(self, tmp_path: Path):
        path = write_file(tmp_path / "ok.txt", [make_record(10), make_record(20)])
        data = load_tracking(path)
        assert data.n_records == 2
        assert data.n_lines == 3
        assert data.meta == META_LINE

    def test_timestamp_conversion(self, tmp_path: Path):
        path = write_file(
            tmp_path / "t.txt",
            [make_record(1_000_000_000), make_record(1_500_000_000)],
        )
        data = load_tracking(path)
        np.testing.assert_allclose(data.t_s, [0.0, 0.5])

    def test_non_monotonic_timestamps_rejected(self, tmp_path: Path):
        path = write_file(tmp_path / "t.txt", [make_record(100), make_record(50)])
        with pytest.raises(TrackingDataError, match="monotonic"):
            load_tracking(path)

    def test_missing_field_reports_line(self, tmp_path: Path):
        record = make_record(10)
        del record["Head"]
        path = write_file(tmp_path / "missing.txt", [record])
        with pytest.raises(TrackingDataError, match="line 2.*Head"):
            load_tracking(path)

    def test_inactive_hand_becomes_nan(self, tmp_path: Path):
        path = write_file(
            tmp_path / "gap.txt",
            [make_record(10, right_active=0), make_record(20, right_active=1)],
        )
        data = load_tracking(path)
        right = data.positions("right")
        assert np.isnan(right[0]).all()
        assert np.isfinite(right[1]).all()
        left = data.positions("left")
        assert np.isfinite(left).all()

    def test_head_pose_extracts_xyz_only(self, tmp_path: Path):
        path = write_file(tmp_path / "head.txt", [make_record(10, head_pose=REAL_POSE)])
        head = load_tracking(path).positions("head")
        assert head[0] == pytest.approx([-0.08517717, -0.02745685, -0.0058761])

    def test_positions_rejects_unknown_point(self, tmp_path: Path):
        path = write_file(tmp_path / "p.txt", [make_record(10)])
        data = load_tracking(path)
        assert isinstance(data, TrackingData)
        with pytest.raises(ValueError):
            data.positions("torso")

    def test_head_quat_extracted(self, tmp_path: Path):
        path = write_file(tmp_path / "q.txt", [make_record(10, head_pose=REAL_POSE)])
        data = load_tracking(path)
        assert data.head_quat.shape == (1, 4)
        assert data.head_quat[0] == pytest.approx(
            [0.162562191, -0.2861428, -0.116477557, -0.9370853]
        )

    def test_full_joint_arrays(self, tmp_path: Path):
        path = write_file(
            tmp_path / "j.txt",
            [make_record(10, right_active=0), make_record(20, right_active=1)],
        )
        data = load_tracking(path)
        assert data.n_joints == 26
        assert data.left_joints.shape == (2, 26, 3)
        assert data.right_joints.shape == (2, 26, 3)
        assert np.isfinite(data.left_joints).all()
        assert np.isnan(data.right_joints[0]).all()
        assert np.isfinite(data.right_joints[1]).all()
        np.testing.assert_allclose(
            data.left_joints[0, 0], [-0.4, -0.5, -0.6], rtol=1e-6
        )

    def test_joint_count_mismatch_rejected(self, tmp_path: Path):
        record = make_record(10)
        record["Hand"]["leftHand"]["HandJointLocations"] = [
            {"p": pose_str("-0,4", "-0,5", "-0,6"), "s": 15.0, "r": 0.0}
        ]
        path = write_file(tmp_path / "mm.txt", [record])
        with pytest.raises(TrackingDataError, match="count=26 but 1"):
            load_tracking(path)
