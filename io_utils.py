from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import colorama
import cv2
import numpy as np


def init_console() -> None:
    colorama.just_fix_windows_console()


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.INFO: colorama.Fore.GREEN,
        logging.WARNING: colorama.Fore.YELLOW,
        logging.ERROR: colorama.Fore.RED,
        logging.CRITICAL: colorama.Fore.RED + colorama.Style.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        prefix = self.COLORS.get(record.levelno, "")
        reset = colorama.Style.RESET_ALL
        line = super().format(record)
        return f"{prefix}{line}{reset}"


def setup_logger(name: str = "vidguard", level: int = logging.INFO) -> logging.Logger:
    init_console()
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(level)
    h = logging.StreamHandler()
    h.setLevel(level)
    h.setFormatter(ColorFormatter("%(levelname)s: %(message)s"))
    log.addHandler(h)
    return log


def write_json_report(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_debug_frame(
    out_dir: str | Path,
    frame_bgr: np.ndarray,
    *,
    frame_index: int,
    artifact_type: str,
    bbox_xywh: tuple[int, int, int, int] | None = None,
    overlay_lines: list[tuple[tuple[int, int], tuple[int, int]]] | None = None,
    overlay_text: str | None = None,
) -> Path:
    """Save artifact frame with optional bbox / lines for investigation."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    vis = frame_bgr.copy()
    if bbox_xywh is not None:
        x, y, w, h = bbox_xywh
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), max(2, vis.shape[0] // 480))
    if overlay_lines:
        for p0, p1 in overlay_lines:
            cv2.line(vis, p0, p1, (0, 165, 255), max(1, vis.shape[0] // 720))
    if overlay_text:
        cv2.putText(
            vis,
            overlay_text[:200],
            (16, 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (40, 40, 255),
            2,
            cv2.LINE_AA,
        )
    safe = artifact_type.replace("/", "-").replace(" ", "_")
    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    out = out_dir / f"f{frame_index:06d}_{safe}_{ts}.jpg"
    cv2.imwrite(str(out), vis)
    return out


def build_report_document(
    *,
    video_path: str,
    fps_nominal: float,
    fast_scan_k: int,
    backend: str,
    events: list[dict[str, Any]],
    pass_ok: bool,
) -> dict[str, Any]:
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "video_path": str(video_path),
        "fps_nominal": fps_nominal,
        "fast_scan_k": fast_scan_k,
        "backend": backend,
        "pass": pass_ok,
        "artifact_count": len(events),
        "events": events,
    }
