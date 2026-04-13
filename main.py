from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from detectors import ArtifactEvent, VideoValidator
from io_utils import build_report_document, save_debug_frame, setup_logger, write_json_report


PROFILE_DEFAULTS: dict[str, dict[str, float | int]] = {
    "balanced": {
        "max_analysis_px": 3840,
        "macro_ratio": 1.34,
        "tear_delta": 24.0,
        "tear_consecutive": 2,
        "tear_row_tol": 12,
        "tear_ignore_top_pct": 0.05,
        "tear_ignore_bottom_pct": 0.12,
        "tear_static_row_frames": 8,
        "freeze_mse": 1.0,
        "freeze_frames": 30,
        "solid_std": 4.0,
    },
    "strict": {
        "max_analysis_px": 7680,
        "macro_ratio": 1.22,
        "tear_delta": 18.0,
        "tear_consecutive": 2,
        "tear_row_tol": 10,
        "tear_ignore_top_pct": 0.04,
        "tear_ignore_bottom_pct": 0.10,
        "tear_static_row_frames": 8,
        "freeze_mse": 0.7,
        "freeze_frames": 20,
        "solid_std": 3.0,
    },
    "robust": {
        "max_analysis_px": 3840,
        "macro_ratio": 1.42,
        "tear_delta": 28.0,
        "tear_consecutive": 3,
        "tear_row_tol": 16,
        "tear_ignore_top_pct": 0.07,
        "tear_ignore_bottom_pct": 0.15,
        "tear_static_row_frames": 6,
        "freeze_mse": 1.8,
        "freeze_frames": 45,
        "solid_std": 5.0,
    },
    "8k": {
        "max_analysis_px": 7680,
        "macro_ratio": 1.34,
        "tear_delta": 24.0,
        "tear_consecutive": 2,
        "tear_row_tol": 12,
        "tear_ignore_top_pct": 0.05,
        "tear_ignore_bottom_pct": 0.12,
        "tear_static_row_frames": 8,
        "freeze_mse": 1.2,
        "freeze_frames": 30,
        "solid_std": 4.0,
    },
}


def apply_profile_defaults(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    profile = getattr(args, "profile", "balanced")
    defaults = PROFILE_DEFAULTS.get(profile, PROFILE_DEFAULTS["balanced"])
    changed = {action.dest for action in parser._actions if action.dest != "help"}
    for key, value in defaults.items():
        if key in changed and getattr(args, key) == parser.get_default(key):
            setattr(args, key, value)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="NR video artifact diagnostic (Windows: MSMF preferred).",
    )
    p.add_argument("video", type=str, help="Video path (supports spaces; use quotes on Windows)")
    p.add_argument(
        "--profile",
        type=str,
        default="balanced",
        choices=sorted(PROFILE_DEFAULTS.keys()),
        help="Threshold profile: balanced, strict, robust, 8k",
    )
    p.add_argument("--fast-scan", type=int, default=1, metavar="K", help="Analyze every K-th frame")
    p.add_argument("--fps-hint", type=float, default=None, help="Override FPS for PTS expectation if container lies")
    p.add_argument("--report", type=str, default=None, help="Write JSON report to this path")
    p.add_argument("--debug", type=str, default=None, help="Directory to save annotated JPEGs for hits")
    p.add_argument("--freeze-frames", type=int, default=15, help="Consecutive low-MSE samples to flag Freeze")
    p.add_argument("--freeze-mse", type=float, default=0.25, help="MSE threshold (grayscale) for freeze streak")
    p.add_argument("--solid-std", type=float, default=2.0, help="Max std (Y/U/V/gray) before Chroma_Error")
    p.add_argument("--macro-ratio", type=float, default=1.32, help="Min seam ratio for macroblocking")
    p.add_argument("--tear-delta", type=float, default=18.0, help="Min Sobel row discontinuity for Tearing")
    p.add_argument(
        "--tear-consecutive",
        type=int,
        default=2,
        help="Require this many consecutive tearing hits near same row",
    )
    p.add_argument(
        "--tear-row-tol",
        type=int,
        default=10,
        help="Allowed row drift (analysis pixels) for consecutive tearing hits",
    )
    p.add_argument(
        "--tear-ignore-top-pct",
        type=float,
        default=0.0,
        help="Ignore top image fraction [0..0.95] in tearing detector (logo-safe)",
    )
    p.add_argument(
        "--tear-ignore-bottom-pct",
        type=float,
        default=0.0,
        help="Ignore bottom image fraction [0..0.95] in tearing detector (subtitle-safe)",
    )
    p.add_argument(
        "--tear-static-row-frames",
        type=int,
        default=10,
        help="Suppress tearing if same row repeats this many sampled frames",
    )
    p.add_argument("--pts-gap-factor", type=float, default=1.85, help="PTS gap vs expected interval")
    p.add_argument("--max-analysis-px", type=int, default=1920, help="Longest side for analysis downscale")
    p.add_argument("-q", "--quiet", action="store_true", help="Less console output")
    args = p.parse_args(argv)
    apply_profile_defaults(args, p)

    log = setup_logger(level=logging.WARNING if args.quiet else logging.INFO)
    if not args.quiet:
        log.info(
            "Effective settings: profile=%s fast_scan=%d fps_hint=%s freeze_mse=%.3f "
            "freeze_frames=%d solid_std=%.3f macro_ratio=%.3f tear_delta=%.3f "
            "tear_consecutive=%d tear_row_tol=%d tear_ignore_top_pct=%.3f tear_ignore_bottom_pct=%.3f "
            "tear_static_row_frames=%d pts_gap_factor=%.3f max_analysis_px=%d",
            args.profile,
            args.fast_scan,
            "auto" if args.fps_hint is None else f"{args.fps_hint:.3f}",
            args.freeze_mse,
            args.freeze_frames,
            args.solid_std,
            args.macro_ratio,
            args.tear_delta,
            args.tear_consecutive,
            args.tear_row_tol,
            args.tear_ignore_top_pct,
            args.tear_ignore_bottom_pct,
            args.tear_static_row_frames,
            args.pts_gap_factor,
            args.max_analysis_px,
        )
    video_path = Path(args.video).expanduser()
    if not video_path.is_file():
        log.error("File not found: %s", video_path)
        return 2

    debug_dir = Path(args.debug).expanduser() if args.debug else None

    def on_artifact(ev: ArtifactEvent, frame_bgr) -> None:
        if not args.quiet:
            log.error(
                "FAIL [%s] frame=%d ts_ms=%.1f sev=%.2f — %s",
                ev.artifact_type,
                ev.frame_index,
                ev.timestamp_ms,
                ev.severity_score,
                ev.message,
            )
        if debug_dir is not None:
            out = save_debug_frame(
                debug_dir,
                frame_bgr,
                frame_index=ev.frame_index,
                artifact_type=ev.artifact_type,
                bbox_xywh=ev.bbox_xywh,
                overlay_text=f"{ev.artifact_type} sev={ev.severity_score:.2f}",
            )
            if not args.quiet:
                log.info("Debug frame: %s", out)

    validator = VideoValidator(
        video_path,
        fast_scan_k=args.fast_scan,
        fps_hint=args.fps_hint,
        max_analysis_dim=args.max_analysis_px,
        freeze_mse_threshold=args.freeze_mse,
        freeze_duration_frames=args.freeze_frames,
        solid_std_threshold=args.solid_std,
        macro_seam_ratio_threshold=args.macro_ratio,
        tear_row_delta=args.tear_delta,
        tear_min_consecutive=args.tear_consecutive,
        tear_row_tolerance_px=args.tear_row_tol,
        tear_ignore_top_pct=args.tear_ignore_top_pct,
        tear_ignore_bottom_pct=args.tear_ignore_bottom_pct,
        tear_static_row_frames=args.tear_static_row_frames,
        pts_gap_factor=args.pts_gap_factor,
    )

    try:
        events, backend = validator.run(
            on_artifact=on_artifact if (not args.quiet or debug_dir is not None) else None,
        )
    except Exception as e:
        log.error("%s", e)
        return 2

    rows = [e.to_json_row() for e in events]
    pass_ok = len(events) == 0
    if pass_ok:
        log.info("PASS — no artifacts above thresholds (backend=%s)", backend)
    else:
        log.error("FAIL — %d artifact event(s) (backend=%s)", len(events), backend)

    if args.report:
        fps_nom = float(args.fps_hint or 30.0)
        doc = build_report_document(
            video_path=str(video_path.resolve()),
            fps_nominal=fps_nom,
            fast_scan_k=args.fast_scan,
            backend=backend,
            events=rows,
            pass_ok=pass_ok,
        )
        write_json_report(Path(args.report).expanduser(), doc)
        log.info("Report: %s", args.report)

    return 0 if pass_ok else 1


if __name__ == "__main__":
    sys.exit(main())
