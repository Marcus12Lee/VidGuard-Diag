from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass
class FrameAnalysis:
    """Result of analyzing one frame for green corruption heuristics."""

    frame_index: int
    is_suspect: bool
    green_fraction: float
    mean_g: float
    mean_r: float
    mean_b: float
    message: str
    metrics: dict[str, Any]


class GreenFrameDetector:
    """
    Heuristic detector for common "green frame" decode glitches (H.264/H.265/VP9, etc.):
    large regions where the green channel dominates R/B (solid lime, macroblocks, or heavy tint).
    Tune thresholds for your content; chroma-key green may false-positive if threshold is low.
    """

    def __init__(
        self,
        *,
        threshold: float = 0.32,
        channel_margin: int = 40,
        min_channel: int = 28,
        hsv_green_mask_min_frac: float | None = 0.38,
    ) -> None:
        self.threshold = threshold
        self.channel_margin = channel_margin
        self.min_channel = min_channel
        self.hsv_green_mask_min_frac = hsv_green_mask_min_frac

    def analyze(self, frame_index: int, frame_bgr: np.ndarray) -> FrameAnalysis:
        if frame_bgr is None or frame_bgr.size == 0:
            return FrameAnalysis(
                frame_index=frame_index,
                is_suspect=False,
                green_fraction=0.0,
                mean_g=0.0,
                mean_r=0.0,
                mean_b=0.0,
                message="",
                metrics={"error": "empty_frame"},
            )

        b, g, r = cv2.split(frame_bgr)
        g_f = g.astype(np.float32)
        r_f = r.astype(np.float32)
        b_f = b.astype(np.float32)

        margin = float(self.channel_margin)
        # Dominant green: G clearly above R and B (typical decoder corruption pattern)
        dom = (g_f > r_f + margin) & (g_f > b_f + margin) & (g_f > float(self.min_channel))
        green_fraction = float(np.mean(dom))

        mean_b = float(np.mean(b_f))
        mean_g = float(np.mean(g_f))
        mean_r = float(np.mean(r_f))

        hsv_frac = 0.0
        if self.hsv_green_mask_min_frac is not None:
            hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
            h = hsv[:, :, 0]
            s = hsv[:, :, 1]
            v = hsv[:, :, 2]
            # OpenCV H: 0–179. Broad green band + sufficient saturation/value.
            green_hue = ((h >= 35) & (h <= 95)) & (s > 60) & (v > 50)
            hsv_frac = float(np.mean(green_hue))

        metrics: dict[str, Any] = {
            "green_dominant_fraction": green_fraction,
            "hsv_green_fraction": hsv_frac,
            "mean_bgr": [mean_b, mean_g, mean_r],
        }

        reasons: list[str] = []
        suspect = False
        if green_fraction >= self.threshold:
            suspect = True
            reasons.append(
                f"channel-domination green pattern on {green_fraction:.1%} of pixels "
                f"(threshold {self.threshold:.0%})"
            )
        if (
            self.hsv_green_mask_min_frac is not None
            and hsv_frac >= self.hsv_green_mask_min_frac
            and mean_g > max(mean_r, mean_b) + 15
        ):
            suspect = True
            reasons.append(
                f"HSV green-band coverage {hsv_frac:.1%} with elevated G mean — possible green tint / corruption"
            )

        message = "; ".join(reasons) if reasons else ""
        return FrameAnalysis(
            frame_index=frame_index,
            is_suspect=suspect,
            green_fraction=green_fraction,
            mean_g=mean_g,
            mean_r=mean_r,
            mean_b=mean_b,
            message=message,
            metrics=metrics,
        )
