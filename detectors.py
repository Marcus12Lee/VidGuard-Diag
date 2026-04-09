from __future__ import annotations

import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from scipy.signal import find_peaks


@dataclass
class ArtifactEvent:
    timestamp_ms: float
    frame_index: int
    artifact_type: str
    severity_score: float
    message: str
    metrics: dict[str, Any]
    bbox_xywh: tuple[int, int, int, int] | None = None

    def to_json_row(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "timestamp_ms": self.timestamp_ms,
            "frame_index": self.frame_index,
            "artifact_type": self.artifact_type,
            "severity_score": self.severity_score,
            "message": self.message,
            "metrics": self.metrics,
            "debug_bbox_xywh": list(self.bbox_xywh) if self.bbox_xywh else None,
        }
        return d


def _mse(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return float("inf")
    d = a.astype(np.float32) - b.astype(np.float32)
    return float(np.mean(d * d))


def _norm_severity(value: float, threshold: float) -> float:
    if threshold <= 0:
        return 1.0
    return float(min(1.0, max(0.0, value / (value + threshold))))


def open_capture(path: Path) -> tuple[cv2.VideoCapture, str]:
    p = str(path)
    if sys.platform == "win32":
        cap = cv2.VideoCapture(p, cv2.CAP_MSMF)
        backend = "CAP_MSMF"
        if not cap.isOpened():
            cap = cv2.VideoCapture(p)
            backend = "default_fallback"
    else:
        cap = cv2.VideoCapture(p)
        backend = "default"
    return cap, backend


def macroblocking_seam_ratio(gray: np.ndarray, block: int) -> float:
    """Laplacian energy along vertical block boundaries vs global mean (>=1 = stronger seams)."""
    lap = cv2.Laplacian(gray, cv2.CV_32F)
    mag = np.abs(lap)
    h, w = mag.shape
    if h < block * 2 or w < block * 2:
        return 1.0
    cols: list[float] = []
    for i in range(block - 1, w, block):
        cols.append(float(np.mean(mag[:, i])))
    if not cols:
        return 1.0
    aligned_mean = float(np.mean(cols))
    baseline = float(np.mean(mag) + 1e-6)
    return aligned_mean / baseline


def tearing_horizontal_spike(gray: np.ndarray, height: float) -> tuple[float, int]:
    g = gray.astype(np.float32)
    h, w = g.shape
    if h < 8 or w < 16:
        return 0.0, -1
    mid = w // 2
    row_score = np.abs(np.mean(g[:, :mid], axis=1) - np.mean(g[:, mid:], axis=1))
    d = np.abs(np.diff(row_score))
    if d.size == 0:
        return 0.0, -1
    peaks, props = find_peaks(d, height=height)
    if peaks.size == 0:
        return 0.0, -1
    best = int(np.argmax(props["peak_heights"]))
    idx = int(peaks[best])
    return float(d[idx]), idx + 1


class VideoValidator:
    """
    Non-reference artifact scanner over decoded frames.
    Windows: prefers MSMF. Uses YUV std, Laplacian seam ratio, tearing row metric, PTS gaps, freeze streak.
    """

    def __init__(
        self,
        video_path: str | Path,
        *,
        fast_scan_k: int = 1,
        fps_hint: float | None = None,
        max_analysis_dim: int = 1920,
        freeze_mse_threshold: float = 0.25,
        freeze_duration_frames: int = 15,
        motion_window: int = 8,
        motion_mse_min: float = 2.0,
        solid_std_threshold: float = 2.0,
        macro_seam_ratio_threshold: float = 1.32,
        tear_row_delta: float = 18.0,
        pts_gap_factor: float = 1.85,
    ) -> None:
        self.video_path = Path(video_path)
        self.fast_scan_k = max(1, int(fast_scan_k))
        self.fps_hint = fps_hint
        self.max_analysis_dim = max_analysis_dim
        self.freeze_mse_threshold = freeze_mse_threshold
        self.freeze_duration_frames = freeze_duration_frames
        self.motion_window = motion_window
        self.motion_mse_min = motion_mse_min
        self.solid_std_threshold = solid_std_threshold
        self.macro_seam_ratio_threshold = macro_seam_ratio_threshold
        self.tear_row_delta = tear_row_delta
        self.pts_gap_factor = pts_gap_factor
        self.events: list[ArtifactEvent] = []

    def _resize_for_analysis(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        m = max(h, w)
        if m <= self.max_analysis_dim:
            return frame
        scale = self.max_analysis_dim / m
        nw = max(2, int(w * scale))
        nh = max(2, int(h * scale))
        return cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _solid_chroma_metrics(small_bgr: np.ndarray) -> tuple[float, float, float, float]:
        yuv = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2YUV)
        y, u, v = cv2.split(yuv)
        return float(np.std(y)), float(np.std(u)), float(np.std(v)), float(np.std(cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)))

    def _emit(
        self,
        ev: ArtifactEvent,
        full_bgr: np.ndarray,
        on_artifact: Callable[[ArtifactEvent, np.ndarray], None] | None,
    ) -> None:
        self.events.append(ev)
        if on_artifact:
            on_artifact(ev, full_bgr)

    def run(
        self,
        *,
        on_artifact: Callable[[ArtifactEvent, np.ndarray], None] | None = None,
    ) -> tuple[list[ArtifactEvent], str]:
        if not self.video_path.is_file():
            raise FileNotFoundError(self.video_path)

        cap, backend = open_capture(self.video_path)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"OpenCV could not open: {self.video_path}")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if self.fps_hint and self.fps_hint > 1:
            fps = self.fps_hint
        if fps < 1e-3:
            fps = 30.0
        expected_dt_ms = 1000.0 / fps

        prev_small: np.ndarray | None = None
        prev_pts: float | None = None
        freeze_streak = 0
        motion_hist: deque[float] = deque(maxlen=self.motion_window)
        frame_idx = -1
        fh, fw = 0, 0

        try:
            while True:
                frame_idx += 1
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                fh, fw = frame.shape[0], frame.shape[1]

                if frame_idx % self.fast_scan_k != 0:
                    continue

                pts_ms = float(cap.get(cv2.CAP_PROP_POS_MSEC) or -1.0)

                if prev_pts is not None and pts_ms >= 0 and prev_pts >= 0:
                    dt = pts_ms - prev_pts
                    if dt < -0.5:
                        sev = _norm_severity(abs(dt), expected_dt_ms)
                        self._emit(
                            ArtifactEvent(
                                timestamp_ms=pts_ms,
                                frame_index=frame_idx,
                                artifact_type="PTS_NonMonotonic",
                                severity_score=sev,
                                message=f"Timestamp moved backward: delta_ms={dt:.2f}",
                                metrics={
                                    "prev_ms": prev_pts,
                                    "curr_ms": pts_ms,
                                    "expected_dt_ms": expected_dt_ms,
                                },
                            ),
                            frame,
                            on_artifact,
                        )
                    elif dt > expected_dt_ms * self.pts_gap_factor:
                        sev = _norm_severity(dt - expected_dt_ms, expected_dt_ms)
                        self._emit(
                            ArtifactEvent(
                                timestamp_ms=pts_ms,
                                frame_index=frame_idx,
                                artifact_type="Dropped_Frame_Suspect",
                                severity_score=sev,
                                message=f"Large PTS gap: {dt:.1f} ms (expected ~{expected_dt_ms:.1f} ms)",
                                metrics={"dt_ms": dt, "expected_dt_ms": expected_dt_ms},
                            ),
                            frame,
                            on_artifact,
                        )
                if pts_ms >= 0:
                    prev_pts = pts_ms

                small = self._resize_for_analysis(frame)
                gray_small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

                if prev_small is not None:
                    mv = _mse(gray_small, cv2.cvtColor(prev_small, cv2.COLOR_BGR2GRAY))
                    motion_hist.append(mv)

                sy, su, sv, spix = self._solid_chroma_metrics(small)
                if max(sy, su, sv, spix) < self.solid_std_threshold:
                    sev = 1.0 - max(sy, su, sv, spix) / self.solid_std_threshold
                    self._emit(
                        ArtifactEvent(
                            timestamp_ms=pts_ms,
                            frame_index=frame_idx,
                            artifact_type="Chroma_Error",
                            severity_score=float(min(1.0, max(0.0, sev))),
                            message="Low Y/U/V and luma variance — solid / collapse heuristic",
                            metrics={"std_y": sy, "std_u": su, "std_v": sv, "std_gray": spix},
                            bbox_xywh=(0, 0, fw, fh),
                        ),
                        frame,
                        on_artifact,
                    )

                mb8 = macroblocking_seam_ratio(gray_small, 8)
                mb16 = macroblocking_seam_ratio(gray_small, 16)
                mb = max(mb8, mb16)
                if mb >= self.macro_seam_ratio_threshold:
                    block = 16 if mb16 >= mb8 else 8
                    sev = _norm_severity(mb - 1.0, self.macro_seam_ratio_threshold - 1.0)
                    self._emit(
                        ArtifactEvent(
                            timestamp_ms=pts_ms,
                            frame_index=frame_idx,
                            artifact_type=f"Macroblocking_{block}",
                            severity_score=sev,
                            message=f"Block-boundary Laplacian seam ratio {mb:.3f}",
                            metrics={"seam_ratio": mb, "grid": block, "mb8": mb8, "mb16": mb16},
                            bbox_xywh=(0, 0, fw, fh),
                        ),
                        frame,
                        on_artifact,
                    )

                tear_peak, tear_row = tearing_horizontal_spike(gray_small, self.tear_row_delta)
                if tear_peak >= self.tear_row_delta and tear_row >= 0:
                    sev = _norm_severity(tear_peak, self.tear_row_delta)
                    sh = small.shape[0]
                    y0 = max(0, int(round(tear_row * (fh / max(1, sh)))) - 6)
                    self._emit(
                        ArtifactEvent(
                            timestamp_ms=pts_ms,
                            frame_index=frame_idx,
                            artifact_type="Tearing",
                            severity_score=sev,
                            message=f"Horizontal discontinuity spike (analysis row ~{tear_row})",
                            metrics={"row_index_analysis": tear_row, "delta_score": tear_peak},
                            bbox_xywh=(0, y0, fw, 12),
                        ),
                        frame,
                        on_artifact,
                    )

                if prev_small is not None:
                    mse = _mse(gray_small, cv2.cvtColor(prev_small, cv2.COLOR_BGR2GRAY))
                    if mse <= self.freeze_mse_threshold:
                        freeze_streak += 1
                    else:
                        freeze_streak = 0
                    motion_ok = len(motion_hist) >= 3 and max(motion_hist) > self.motion_mse_min
                    if freeze_streak >= self.freeze_duration_frames and motion_ok:
                        sev = _norm_severity(float(freeze_streak), float(self.freeze_duration_frames))
                        self._emit(
                            ArtifactEvent(
                                timestamp_ms=pts_ms,
                                frame_index=frame_idx,
                                artifact_type="Freeze",
                                severity_score=sev,
                                message=f"Near-identical frames for {freeze_streak} sampled steps with prior motion",
                                metrics={"mse": mse, "freeze_streak": freeze_streak},
                                bbox_xywh=(0, 0, fw, fh),
                            ),
                            frame,
                            on_artifact,
                        )
                        freeze_streak = 0

                prev_small = small

        finally:
            cap.release()

        return self.events, backend
