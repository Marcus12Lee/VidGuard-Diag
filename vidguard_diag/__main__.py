from __future__ import annotations

import argparse
import sys

from vidguard_diag import __version__
from vidguard_diag.detector import GreenFrameDetector
from vidguard_diag.hooks import CrashDumpStubHook, JsonlLogHook, StopNotificationHook
from vidguard_diag.hooks.base import GreenFrameEvent
from vidguard_diag.session import decode_scan_video


class StderrErrorHook:
    def on_green_frame(self, event: GreenFrameEvent) -> None:
        print(
            f"ERROR green_frame frame={event.frame_index} video={event.video_path} detail={event.message}",
            file=sys.stderr,
        )


def build_hooks(args: argparse.Namespace) -> list[object]:
    hooks: list[object] = [StderrErrorHook()]
    names = [x.strip().lower() for x in args.hooks.split(",") if x.strip()]
    for name in names:
        if name in ("stop", "stop-notify"):
            hooks.append(StopNotificationHook())
        elif name in ("crashdump", "crashdump-stub"):
            hooks.append(CrashDumpStubHook(args.dump_dir))
        elif name in ("jsonl", "log-jsonl"):
            hooks.append(JsonlLogHook(args.jsonl_log))
        else:
            raise SystemExit(f"Unknown hook: {name!r} (try: stop, crashdump-stub, jsonl)")
    return hooks


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="vidguard-diag",
        description="Scan a video while decoding; exit non-zero if green-frame heuristics trigger.",
    )
    p.add_argument("video", type=str, help="Path to video file")
    p.add_argument("--threshold", type=float, default=0.32, help="Dominant-green pixel fraction 0-1")
    p.add_argument("--sample-every", type=int, default=1, help="Analyze every Nth frame")
    p.add_argument("--max-frames", type=int, default=None, help="Stop after N frames (debug)")
    p.add_argument(
        "--no-hsv",
        action="store_true",
        help="Disable HSV green-band check",
    )
    p.add_argument(
        "--hooks",
        type=str,
        default="",
        help="Comma list: stop, crashdump-stub, jsonl",
    )
    p.add_argument("--dump-dir", type=str, default="./vidguard_dumps")
    p.add_argument("--jsonl-log", type=str, default="./vidguard_events.jsonl")
    p.add_argument("--pass-frame", action="store_true", help="Pass BGR frame to hooks (heavy)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args(argv)

    detector = GreenFrameDetector(
        threshold=args.threshold,
        hsv_green_mask_min_frac=None if args.no_hsv else 0.38,
    )
    hooks = build_hooks(args)

    result = decode_scan_video(
        args.video,
        detector,
        hooks=hooks,
        sample_every=args.sample_every,
        max_frames=args.max_frames,
        pass_frame_to_hooks=args.pass_frame,
    )

    if result.error and result.frames_scanned == 0 and result.analysis is None:
        print(result.error, file=sys.stderr)
        return 2

    if not result.ok and result.analysis:
        return 1

    print(
        f"OK — sampled {result.frames_scanned} frame(s); no green heuristic.",
        file=sys.stderr,
    )
    return 0


def run() -> None:
    sys.exit(main())


if __name__ == "__main__":
    run()
