from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from detectors import ArtifactEvent, VideoValidator
from io_utils import build_report_document, save_debug_frame, setup_logger, write_json_report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="NR video artifact diagnostic (Windows: MSMF preferred).",
    )
    p.add_argument("video", type=str, help="Video path (supports spaces; use quotes on Windows)")
    p.add_argument("--fast-scan", type=int, default=1, metavar="K", help="Analyze every K-th frame")
    p.add_argument("--fps-hint", type=float, default=None, help="Override FPS for PTS expectation if container lies")
    p.add_argument("--report", type=str, default=None, help="Write JSON report to this path")
    p.add_argument("--debug", type=str, default=None, help="Directory to save annotated JPEGs for hits")
    p.add_argument("--freeze-frames", type=int, default=15, help="Consecutive low-MSE samples to flag Freeze")
    p.add_argument("--freeze-mse", type=float, default=0.25, help="MSE threshold (grayscale) for freeze streak")
    p.add_argument("--solid-std", type=float, default=2.0, help="Max std (Y/U/V/gray) before Chroma_Error")
    p.add_argument("--macro-ratio", type=float, default=1.32, help="Min seam ratio for macroblocking")
    p.add_argument("--tear-delta", type=float, default=18.0, help="Min Sobel row discontinuity for Tearing")
    p.add_argument("--pts-gap-factor", type=float, default=1.85, help="PTS gap vs expected interval")
    p.add_argument("--max-analysis-px", type=int, default=1920, help="Longest side for analysis downscale")
    p.add_argument("-q", "--quiet", action="store_true", help="Less console output")
    args = p.parse_args(argv)

    log = setup_logger(level=logging.WARNING if args.quiet else logging.INFO)
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
