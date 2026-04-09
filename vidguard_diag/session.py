from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import cv2

from vidguard_diag.detector import FrameAnalysis, GreenFrameDetector
from vidguard_diag.hooks.base import GreenFrameEvent, call_hook


class ScanResult:
    def __init__(
        self,
        *,
        ok: bool,
        frames_scanned: int,
        analysis: FrameAnalysis | None = None,
        error: str | None = None,
    ) -> None:
        self.ok = ok
        self.frames_scanned = frames_scanned
        self.analysis = analysis
        self.error = error


def decode_scan_video(
    video_path: str | Path,
    detector: GreenFrameDetector,
    *,
    hooks: Sequence[Any] | None = None,
    sample_every: int = 1,
    max_frames: int | None = None,
    pass_frame_to_hooks: bool = False,
) -> ScanResult:
    path = Path(video_path).expanduser().resolve()
    if not path.is_file():
        return ScanResult(ok=False, frames_scanned=0, error=f"File not found: {path}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return ScanResult(
            ok=False,
            frames_scanned=0,
            error=f"Could not open video (codec/driver?): {path}",
        )

    hooks = list(hooks or [])
    every = max(1, int(sample_every))
    scanned = 0
    idx = 0

    try:
        while True:
            if max_frames is not None and idx >= max_frames:
                break
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if idx % every == 0:
                analysis = detector.analyze(idx, frame)
                scanned += 1
                if analysis.is_suspect:
                    event = GreenFrameEvent(
                        frame_index=analysis.frame_index,
                        message=analysis.message,
                        video_path=str(path),
                        metrics=dict(analysis.metrics),
                        frame_bgr=frame if pass_frame_to_hooks else None,
                    )
                    for h in hooks:
                        call_hook(h, event)
                    return ScanResult(ok=False, frames_scanned=scanned, analysis=analysis)
            idx += 1
    finally:
        cap.release()

    return ScanResult(ok=True, frames_scanned=scanned, error=None)
