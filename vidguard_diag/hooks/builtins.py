from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from vidguard_diag.hooks.base import GreenFrameEvent


class StopNotificationHook:
    """Placeholder for future orchestration (stop player process, interrupt pipeline)."""

    def __init__(self, stream=None) -> None:
        self.stream = stream or sys.stderr

    def on_green_frame(self, event: GreenFrameEvent) -> None:
        print(
            f"[VidGuard-Diag] STOP hook: green frame at index {event.frame_index} — {event.message}",
            file=self.stream,
        )


class CrashDumpStubHook:
    """
    Writes a small diagnostic stub file. Replace later with real crashdump / minidump
    integration (Windows) or sample bundle (macOS).
    """

    def __init__(self, dump_dir: str | Path) -> None:
        self.dump_dir = Path(dump_dir)
        self.dump_dir.mkdir(parents=True, exist_ok=True)

    def on_green_frame(self, event: GreenFrameEvent) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.dump_dir / f"vidguard_stub_{ts}_f{event.frame_index}.txt"
        lines = [
            f"VidGuard-Diag crashdump stub (replace with real dump later)",
            f"time_utc={ts}",
            f"video={event.video_path}",
            f"frame_index={event.frame_index}",
            f"message={event.message}",
            f"metrics={json.dumps(event.metrics)}",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class JsonlLogHook:
    """Append one JSON line per detection for downstream tooling."""

    def __init__(self, log_path: str | Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def on_green_frame(self, event: GreenFrameEvent) -> None:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "video": event.video_path,
            "frame_index": event.frame_index,
            "message": event.message,
            "metrics": event.metrics,
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
