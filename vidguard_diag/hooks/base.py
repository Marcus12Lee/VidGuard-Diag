from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


@dataclass
class GreenFrameEvent:
    """Payload passed to hooks when a suspect frame is found."""

    frame_index: int
    message: str
    video_path: str
    metrics: dict[str, Any]
    frame_bgr: np.ndarray | None = None


class GreenFrameHook(Protocol):
    """Implement `__call__` or add a subclass with on_green_frame."""

    def on_green_frame(self, event: GreenFrameEvent) -> None: ...


def call_hook(hook: Any, event: GreenFrameEvent) -> None:
    if hasattr(hook, "on_green_frame"):
        hook.on_green_frame(event)
    elif callable(hook):
        hook(event)
    else:
        raise TypeError(f"Hook must be callable or have on_green_frame: {hook!r}")
