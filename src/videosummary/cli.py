from __future__ import annotations

import argparse
from pathlib import Path

from videosummary.pipeline_phase1 import Phase1Config, run_phase1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase-1 pipeline: extract audio + timestamped transcription."
    )
    parser.add_argument("--input", required=True, help="Input video path")
    parser.add_argument(
        "--output",
        default="outputs",
        help="Output root directory (default: outputs)",
    )
    parser.add_argument(
        "--model",
        default="small",
        help="faster-whisper model (tiny/base/small/medium/large-v3)",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Language code, e.g. zh/en (default: auto detect)",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="Compute device: auto/cuda/cpu",
    )
    parser.add_argument(
        "--compute-type",
        default="int8",
        help="faster-whisper compute type, e.g. int8/float16",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    run_dir = run_phase1(
        Phase1Config(
            input_video=Path(args.input).resolve(),
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
