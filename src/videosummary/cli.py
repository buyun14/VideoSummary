from __future__ import annotations

import argparse
from pathlib import Path

from videosummary.pipeline_phase1 import Phase1Config, run_phase1
from videosummary.router_phase2 import RouterConfig, run_router


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="VideoSummary pipeline CLI."
    )
    parser.add_argument("--input", help="Input video path (legacy phase1 mode)")
    parser.add_argument("--output", default="outputs", help="Output root directory")
    parser.add_argument("--model", default="small", help="faster-whisper model")
    parser.add_argument("--language", default=None, help="Language code, e.g. zh/en")
    parser.add_argument("--device", default="auto", help="Compute device: auto/cuda/cpu")
    parser.add_argument("--compute-type", default="int8", help="faster-whisper compute type")

    subparsers = parser.add_subparsers(dest="command")

    phase1 = subparsers.add_parser("phase1", help="Run phase1 audio+ASR pipeline")
    phase1.add_argument("--input", required=True, help="Input video path")
    phase1.add_argument("--output", default="outputs", help="Output root directory")
    phase1.add_argument("--model", default="small", help="faster-whisper model")
    phase1.add_argument("--language", default=None, help="Language code, e.g. zh/en")
    phase1.add_argument("--device", default="auto", help="Compute device: auto/cuda/cpu")
    phase1.add_argument("--compute-type", default="int8", help="faster-whisper compute type")

    router = subparsers.add_parser("router", help="Run phase2 transcript router")
    router.add_argument("--transcript-jsonl", required=True, help="Phase1 transcript.segments.jsonl")
    router.add_argument("--output", default=None, help="Router output directory (default: sibling phase2)")
    router.add_argument("--top-k", type=int, default=18, help="Max candidate segments before merge")
    router.add_argument("--min-score", type=float, default=2.0, help="Score threshold")
    router.add_argument("--merge-gap-seconds", type=float, default=8.0, help="Merge adjacent windows")
    router.add_argument("--context-window", type=int, default=1, help="Neighbor segments for context")
    router.add_argument("--min-plan-items", type=int, default=8, help="Backfill to at least N items")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "router":
        transcript_jsonl = Path(args.transcript_jsonl).resolve()
        if args.output:
            output_root = Path(args.output).resolve()
        else:
            phase1_dir = transcript_jsonl.parent
            output_root = phase1_dir.parent / "phase2"

        run_dir = run_router(
            RouterConfig(
                transcript_jsonl=transcript_jsonl,
                output_root=output_root,
                top_k=args.top_k,
                min_score=args.min_score,
                merge_gap_seconds=args.merge_gap_seconds,
                context_window=args.context_window,
                min_plan_items=args.min_plan_items,
            )
        )
        print(f"Phase-2 router completed: {run_dir}")
        return

    phase1_input = args.input
    if args.command == "phase1":
        phase1_input = args.input

    if not phase1_input:
        raise SystemExit("Please provide phase1 input via `phase1 --input ...` or legacy `--input ...`.")

    run_dir = run_phase1(
        Phase1Config(
            input_video=Path(phase1_input).resolve(),
            output_root=Path(args.output).resolve(),
            model_name=args.model,
            language=args.language,
            device=args.device,
            compute_type=args.compute_type,
        )
    )
    print(f"Phase-1 completed: {run_dir}")


if __name__ == "__main__":
    main()
