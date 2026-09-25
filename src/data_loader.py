"""Load and normalize the VR tracking file.

Format facts (verified against trackingData_20260505_165740.txt):

* UTF-8 JSON Lines, one object per line.
* Line 1 is a metadata record (``notice`` + first-frame camera info);
  subsequent lines are tracking records.
* Pose strings (``Head.pose``, ``...HandJointLocations[].p``) use a locale
  decimal comma AND comma as the value separator, so every value is written
  as two comma-tokens: ``-0,08517717`` -> ``(-0, 08517717)``. Values must be
  re-assembled by merging token pairs before ``float()``.
* A pose/p string always holds 7 values: x, y, z, qx, qy, qz, qw.
* ``timeStampNs`` is a monotonic nanosecond epoch clock. ``predictTime``
  has unverified units and is never used for metrics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

POSE_VALUE_COUNT = 7  # x, y, z, qx, qy, qz, qw


class TrackingDataError(ValueError):
    """Raised when the tracking file is missing, malformed, or unusable."""


def parse_locale_numbers(text: str) -> list[float]:
    """Parse a comma-decimal, comma-separated numeric string.

    ``"-0,08517717,0,5"`` -> ``[-0.08517717, 0.5]``. Token pairs are merged
    into one dot-decimal number each, so the token count must be even.
    """
    tokens = text.split(",")
    if len(tokens) < 2 or len(tokens) % 2 != 0:
        raise TrackingDataError(
            f"expected an even number of comma-tokens (>=2), got {len(tokens)} in {text!r}"
        )
    values: list[float] = []
    for i in range(0, len(tokens), 2):
        try:
            values.append(float(f"{tokens[i]}.{tokens[i + 1]}"))
        except ValueError as exc:
            raise TrackingDataError(f"cannot parse number from {text!r}") from exc
    return values


def _pose7(text: str, where: str) -> tuple[float, ...]:
    """Extract all 7 values (x, y, z, qx, qy, qz, qw) from a pose/p string."""
    values = parse_locale_numbers(text)
    if len(values) != POSE_VALUE_COUNT:
        raise TrackingDataError(
            f"{where}: expected {POSE_VALUE_COUNT} values, got {len(values)} in {text!r}"
        )
    return tuple(values)


def _hand_joints(
    hand: dict[str, Any], where: str, n_joints: int | None
) -> tuple[np.ndarray, int]:
    """(J, 3) joint positions; all-NaN when the hand is inactive.

    Returns the joint count actually present so the caller can enforce
    consistency across records.
    """
    joints = hand.get("HandJointLocations") or []
    count = int(hand["count"]) if "count" in hand else len(joints)
    if joints and len(joints) != count:
        raise TrackingDataError(
            f"{where}: count={count} but {len(joints)} HandJointLocations"
        )
    if n_joints is not None and count and count != n_joints:
        raise TrackingDataError(
            f"{where}: joint count changed from {n_joints} to {count}"
        )
    if not hand.get("isActive"):
        size = n_joints or count
        if not size:
            raise TrackingDataError(
                f"{where}: inactive hand with unknown joint count "
                "(no 'count' field and no earlier record to infer it from)"
            )
        return np.full((size, 3), np.nan), count
    if not joints:
        raise TrackingDataError(f"{where}: isActive but no HandJointLocations")
    positions = np.array(
        [_pose7(j["p"], f"{where} joint {i}")[:3] for i, j in enumerate(joints)],
        dtype=np.float64,
    )
    return positions, count


@dataclass(frozen=True)
class TrackingData:
    """Normalized tracking data plus file-level bookkeeping.

    ``frame`` holds per-record joint-0 positions for analysis; ``head_quat``,
    ``left_joints`` and ``right_joints`` carry the full pose/orientation data
    needed by the 3D viewer (NaN rows mark inactive-hand gaps).
    """

    frame: pd.DataFrame  # columns: t_ns, t_s, head_x/y/z, left_x/y/z, right_x/y/z
    head_quat: np.ndarray  # (N, 4) qx, qy, qz, qw
    left_joints: np.ndarray  # (N, J, 3)
    right_joints: np.ndarray  # (N, J, 3)
    meta: dict[str, Any] | None
    n_lines: int
    n_records: int
    n_joints: int

    @property
    def t_s(self) -> np.ndarray:
        return self.frame["t_s"].to_numpy()

    @property
    def t_ns(self) -> np.ndarray:
        return self.frame["t_ns"].to_numpy()

    def positions(self, point: str) -> np.ndarray:
        """(N, 3) array for 'head', 'left', or 'right'. NaN marks gaps."""
        if point not in ("head", "left", "right"):
            raise ValueError(f"unknown point {point!r}")
        return self.frame[[f"{point}_x", f"{point}_y", f"{point}_z"]].to_numpy()

    @property
    def duration_s(self) -> float:
        return float(self.t_s[-1] - self.t_s[0])


def load_tracking(path: str | Path) -> TrackingData:
    """Parse the tracking file into a normalized DataFrame.

    Fails clearly on missing file, malformed JSON, missing required fields,
    non-monotonic timestamps, or zero tracking records.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"tracking file not found: {path}")

    meta: dict[str, Any] | None = None
    t_ns: list[int] = []
    rows: list[dict[str, float]] = []
    quats: list[tuple[float, ...]] = []
    left_frames: list[np.ndarray] = []
    right_frames: list[np.ndarray] = []
    n_joints: int | None = None
    n_lines = 0

    with path.open("r", encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            n_lines += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TrackingDataError(f"line {lineno}: invalid JSON: {exc}") from exc

            if "notice" in record:
                meta = record
                continue

            try:
                timestamp = record["timeStampNs"]
                head = _pose7(record["Head"]["pose"], f"line {lineno} Head.pose")
                left, n_joints = _hand_joints(
                    record["Hand"]["leftHand"], f"line {lineno} leftHand", n_joints
                )
                right, n_joints = _hand_joints(
                    record["Hand"]["rightHand"], f"line {lineno} rightHand", n_joints
                )
            except KeyError as exc:
                raise TrackingDataError(f"line {lineno}: missing field {exc}") from exc

            t_ns.append(int(timestamp))
            quats.append(head[3:])
            left_frames.append(left)
            right_frames.append(right)
            rows.append(
                {
                    "head_x": head[0], "head_y": head[1], "head_z": head[2],
                    "left_x": left[0, 0], "left_y": left[0, 1], "left_z": left[0, 2],
                    "right_x": right[0, 0], "right_y": right[0, 1], "right_z": right[0, 2],
                }
            )

    if not rows:
        raise TrackingDataError(f"{path}: no tracking records found")

    t_ns_arr = np.asarray(t_ns, dtype=np.int64)
    if np.any(np.diff(t_ns_arr) < 0):
        raise TrackingDataError(f"{path}: timeStampNs is not monotonic")

    frame = pd.DataFrame(rows)
    frame.insert(0, "t_ns", t_ns_arr)
    frame.insert(1, "t_s", (t_ns_arr - t_ns_arr[0]) / 1e9)
    return TrackingData(
        frame=frame,
        head_quat=np.asarray(quats, dtype=np.float64),
        left_joints=np.stack(left_frames),
        right_joints=np.stack(right_frames),
        meta=meta,
        n_lines=n_lines,
        n_records=len(rows),
        n_joints=n_joints or 0,
    )
