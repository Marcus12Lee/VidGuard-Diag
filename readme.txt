================================================================================
VidGuard-Diag
================================================================================

Cross-platform video decode diagnostics:

  1) vidguard-diag  — Scan decoded frames for green-frame style corruption
                      (heuristic; exits non-zero if triggered).

  2) main.py        — NR (no-reference) artifact check: freezes, solid/chroma
                      errors, macroblocking seams, tearing, PTS gaps. Optional
                      JSON report and debug JPEG dumps.

Requires Python 3.10 or newer.

--------------------------------------------------------------------------------
What to install
--------------------------------------------------------------------------------

  - Python 3.10+ (with pip and venv recommended)

  System libraries: OpenCV’s Python wheels usually bundle what you need on
  Windows/macOS/Linux. If VideoCapture fails to open files, install OS codecs
  or a full OpenCV build per your platform docs.

  Python packages (full project, including main.py):

    numpy>=1.24
    opencv-python>=4.8
    scipy>=1.10
    colorama>=0.4.6

  The minimal set for only the "vidguard-diag" package entrypoint is
  numpy + opencv-python (see pyproject.toml).

--------------------------------------------------------------------------------
Install (recommended: virtual environment)
--------------------------------------------------------------------------------

  cd /path/to/VidGuard-Diag

  python3 -m venv .venv

  Linux / macOS:
    source .venv/bin/activate

  Windows (cmd):
    .venv\Scripts\activate.bat

  Windows (PowerShell):
    .venv\Scripts\Activate.ps1

  pip install --upgrade pip
  pip install -r requirements.txt

  Optional: install the package in editable mode so the "vidguard-diag"
  command is on your PATH (same shell, venv active):

    pip install -e .

--------------------------------------------------------------------------------
How to use (quick steps)
--------------------------------------------------------------------------------

  1) Open a terminal, activate your venv (see "Install" above).

  2) Go to the folder that contains your video, or use a full path to the file.

  3) Run ONE of the tools:
       - vidguard-diag   → fast green-frame style check
       - python main.py  → deeper NR artifact scan

  4) Read the last lines printed: PASS/OK vs FAIL/ERROR, and the exit code
     (see "Checking the exit code" below).

  Paths with spaces must be quoted, e.g. "my clip.mp4".

--------------------------------------------------------------------------------
Tool A — green-frame scan (vidguard-diag)
--------------------------------------------------------------------------------

  Basic command (after: pip install -e .):

    vidguard-diag /path/to/clip.mp4

  Same thing without installing the package (from repo root):

    python -m vidguard_diag /path/to/clip.mp4

  Faster scan (analyze every 2nd decoded frame):

    vidguard-diag clip.mp4 --sample-every 2

  Stricter or looser green detection (default threshold is 0.32):

    vidguard-diag clip.mp4 --threshold 0.25

  Log each hit to a JSON Lines file:

    vidguard-diag clip.mp4 --hooks jsonl --jsonl-log ./vidguard_events.jsonl

  Example — clean file (exit code 0). Typical stderr line:

    OK — sampled 1200 frame(s); no green heuristic.

  Example — heuristic triggered (exit code 1). Stderr includes the frame
  index, path, and the detector’s reason, for example:

    ERROR green_frame frame=842 video=/path/to/clip.mp4 detail=channel-domination green pattern on 38.0% of pixels (threshold 32%)

  (If the HSV check also fires, "detail=" can list two reasons separated by "; ".)

  Example — cannot open file (exit code 2):

    File not found: /path/to/missing.mp4
    (or)
    Could not open video (codec/driver?): /path/to/clip.mp4

  Other useful flags:

    vidguard-diag clip.mp4 --max-frames 500
    vidguard-diag clip.mp4 --no-hsv
    vidguard-diag clip.mp4 --hooks stop,crashdump-stub --dump-dir ./dumps
    vidguard-diag --version

  Exit codes: 0 = OK, 1 = green heuristic triggered, 2 = missing file or
              decode open failure.

--------------------------------------------------------------------------------
Tool B — NR artifact diagnostic (main.py)
--------------------------------------------------------------------------------

  Run from anywhere if you use an absolute path to main.py, or from repo root:

    python main.py /path/to/clip.mp4

  Faster analysis (every 2nd frame in the scan loop):

    python main.py clip.mp4 --fast-scan 2

  Write a machine-readable JSON report:

    python main.py clip.mp4 --report ./report.json

  Save annotated JPEGs when an artifact is detected:

    python main.py clip.mp4 --debug ./debug_frames

  Combine report + debug + less console noise:

    python main.py clip.mp4 --report ./report.json --debug ./debug_frames -q

  If the container lies about timing, hint FPS for PTS checks:

    python main.py clip.mp4 --fps-hint 29.97

  Example — PASS (exit code 0). Console (INFO):

    PASS — no artifacts above thresholds (backend=default)

    On Windows you may see backend=CAP_MSMF or default_fallback instead.

  Example — FAIL (exit code 1). For each event you get an ERROR line, e.g.:

    FAIL [Freeze] frame=120 ts_ms=4000.0 sev=0.41 — Near-identical frames for 15 sampled steps with prior motion
    FAIL — 3 artifact event(s) (backend=default)

  With --report, you also get:

    Report: ./report.json

  Example — missing file (exit code 2):

    File not found: /path/to/missing.mp4

  Exit codes: 0 = PASS, 1 = FAIL (one or more artifacts), 2 = error.

--------------------------------------------------------------------------------
Checking the exit code
--------------------------------------------------------------------------------

  Linux / macOS (bash):

    vidguard-diag clip.mp4
    echo $?
    (0 = success, non-zero = problem or finding)

  Windows cmd after the command:

    echo %ERRORLEVEL%

  Windows PowerShell:

    $LASTEXITCODE

--------------------------------------------------------------------------------
Project layout (short)
--------------------------------------------------------------------------------

  vidguard_diag/     Packaged green-frame scanner (CLI: vidguard-diag)
  main.py            NR artifact CLI (standalone)
  detectors.py       VideoValidator and artifact detectors for main.py
  io_utils.py        Logging, JSON report, debug frame export for main.py
  requirements.txt   All dependencies for main.py + package
  pyproject.toml     Package metadata and vidguard-diag script entry

================================================================================
