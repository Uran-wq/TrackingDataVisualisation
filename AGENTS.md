# AGENTS.md

## Project

Solution to a VR motion-data visualization test assignment. Deliverables required by the assignment: working code, a README with launch instructions, an example result, and a short description of approach, observations, and difficulties.

Input files (in repo root):

- `trackingData_20260505_165740.txt` — 258 MB, VR tracking data. Source of truth.
- `CameraRecord_20260505_165740.mp4` — 199 MB, camera recording. Not needed for the chosen visualizations.

## Repo status (verified)

- Implemented: `src/` (`data_loader`, `analysis`, `visualization`, `viewer`, `main`), static assets in `viewer/` (three.js r147 vendored in `viewer/lib/`), `tests/` (37 pytest tests), `README.md` (English, default) + `README.ru.md`, `media/` (pre-recorded demo gif/mp4), `requirements.txt`, `.gitignore`.
- Not a git repository yet.
- Available: Python 3.14.7, git 2.55. No ffprobe observed.

## Tracking data format (verified by parsing the file)

- UTF-8 JSON Lines, one JSON object per line, no overall header.
- Line 1 is a metadata record: `notice` (states it holds the first frame's timestamp/head pose), `timeStampNs`, `cameraExtrinsics`, `cameraIntrinsics`. Lines 2–21787 are 21,787 tracking records with keys: `predictTime`, `appState`, `Head`, `Hand`, `Body`, `timeStampNs`, `Input`.
- All 21,788 lines parse with `json.loads`; no malformed lines observed.
- **Locale trap:** the whole file uses comma as decimal separator inside the string fields `Head.pose`, `Hand.*.HandJointLocations[].p`, `Body.joints[].p`, `va`, `wva`. `float()` on these fails; JSON numbers (`predictTime`, `s`, `r`, `timeStampNs`) use dots and are fine.
  - `pose` / `p` strings are always exactly 14 comma-tokens = 7 numbers: `x,y,z,qx,qy,qz,qw`. Reliable parse: split on `,`, merge token pairs, replace `,` with `.` (e.g. `-0,08517717` → `-0.08517717`). Verified for every record.
  - `va` / `wva` mix comma decimals with `E±` notation (e.g. `4,71379326525243E+18`) → separator/decimal ambiguity is unresolvable without a spec. Do not use these fields.
- Timestamps: use `timeStampNs` (monotonic, ns epoch, no non-positive deltas). Median dt ≈ 11.1 ms (~90 Hz), range 6.2–67.4 ms, duration ≈ 242.5 s. `predictTime` units are unverified — do not derive metrics from it.
- Structure per record: `Head.pose` (7 values), `Head.status` (always 3); `Hand.leftHand`/`rightHand` each `isActive`, `count`=26, 26 joints with `p`/`s`/`r`; `Body` = 24 joints. Right hand is inactive for the first 0.81 s (records 0–66) and the last 0.76 s; left hand always active.
- Coordinate facts: all positions span < 1 m from a near-head origin (plausibly meters, head near origin, hands below head). Axis convention, origin, and units are NOT proven — establish before transforming, or label honestly in the README. Never invent a unit conversion or axis swap.
- Format resembles OpenXR-style poses; XR-Robotics GitHub docs may help only if a detail stays unclear. The file itself overrides any documentation on conflict.

## Scope

Three deliverables (first two = the assignment, finished and verified first; third requested afterwards):

1. Motion graphs / statistics (position/speed over time, path length, summary stats — only metrics the data supports).
2. 2D or 3D visualization of head + left hand + right hand (3D: reliable XYZ exists).
3. Interactive 3D viewer: `output/viewer/index.html`, built by `src/viewer.py` from static assets in `viewer/` (three.js vendored, no build step, works from `file://`). Head oriented by the head quaternion (layout verified: xyzw, head→world, face = local −Z), 26-joint hand skeletons using the verified OpenXR-style bone edges, inactive hands hidden as NaN gaps (never interpolated).

Do not add: video overlay/sync, ML classification, streaming, web frameworks or npm/bundler toolchains.

## Rules that matter here

- Inspect the real data before coding; never write a parser from guesses. After any parsing change, re-run it on the real file.
- Never invent fields, units, semantics, or behavioral claims ("the person did X"). Separate measured facts from interpretation.
- Parse once in preprocessing; no scattered axis/sign/unit hacks in plotting code.
- Handle gaps explicitly (right-hand inactive windows are real gaps — do not fabricate positions). Fail clearly on missing file/empty data; no bare `except Exception`.
- Keep parsing / analysis / visualization in separate modules. Small finished > large fragile.

## Stack and structure

- Minimal deps: `numpy`, `pandas`, `matplotlib`, `plotly` (interactive 3D), `pytest`. Viewer is dependency-free static JS: vendored three.js r147 (MIT) in `viewer/lib/`.
- Layout: `src/{data_loader,analysis,visualization,viewer,main}.py`, `viewer/{index.html,app.js,lib/}`, `tests/`, `media/` (committed demo video assets), `output/` (figures + `viewer/` bundle), `README.md`, `README.ru.md`, `requirements.txt`, `.gitignore`.
- Provide one tested CLI, configurable paths: `python -m src.main --input trackingData_20260505_165740.txt --output output`. The README command must have been run successfully.
- Tests focus on fragile logic only: locale-comma parsing, timestamp conversion, head/hand extraction (incl. quaternions and full joint arrays), speed/path math, inactive-hand gaps, malformed input, viewer export. Always finish with a real end-to-end run on the supplied file.

## Large files / GitHub

Both inputs exceed GitHub's 100 MB per-file limit. Decide early: Git LFS, or exclude them via `.gitignore` and document in the README exactly where a reviewer must place them. Never commit `.venv/`, caches, machine-specific paths, or generated debug output.

## README (deliverable)

`README.md` is English and is the default (GitHub shows it first); `README.ru.md` is the Russian mirror — keep the two in sync. Concise and reviewer-oriented: what it does, demo video (inline GIF `media/viewer_demo.gif` + MP4 link — GitHub does not inline repo-hosted mp4, only uploaded assets or GIF), example result images, input format (note the comma-decimal quirk), install, the one run command, outputs, key observations, assumptions/limitations, difficulties. Keep observations factual and quantified.

## Definition of done

A reviewer can clone, follow the README, run one documented command, and get: (1) a motion/statistics visualization, (2) a clear head/left/right-hand 2D or 3D visualization, (3) an example result, (4) documentation of data treatment, assumptions, observations, limitations, (5) a working interactive viewer (`output/viewer/index.html`) — all verified by an actual run, not claimed.
