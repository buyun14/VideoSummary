from __future__ import annotations

import argparse
import os
from pathlib import Path

from videosummary.logging_utils import configure_logging, log_phase
from videosummary.phase2_fixed import Phase2FixedConfig, run_phase2_fixed
from videosummary.phase3_vlm import Phase3VlmConfig, run_phase3_vlm
from videosummary.phase4_summary import Phase4SummaryConfig, run_phase4_summary
from videosummary.pipeline_phase1 import Phase1Config, run_phase1
from videosummary.router_phase2 import RouterConfig, run_router


def _apply_phase2_preset(args: argparse.Namespace) -> None:
    preset = getattr(args, "preset", "default")
    if preset == "game":
        if args.interval_seconds == 30.0:
            args.interval_seconds = 8.0
        if args.context_window == 1:
            args.context_window = 2
        args.with_audio_summary = True
    elif preset == "speech":
        if args.interval_seconds == 30.0:
            args.interval_seconds = 45.0
        if args.context_window == 1:
            args.context_window = 1


def _apply_phase3_preset(args: argparse.Namespace) -> None:
    preset = getattr(args, "preset", "default")
    if not hasattr(args, "temperature"):
        return
    if preset == "game":
        if args.timeout_seconds == 120.0:
            args.timeout_seconds = 180.0
        if args.temperature == 0.2:
            args.temperature = 0.1
        if hasattr(args, "concurrency") and args.concurrency == 3:
            args.concurrency = 4
    elif preset == "speech":
        if args.temperature == 0.2:
            args.temperature = 0.3
        if hasattr(args, "concurrency") and args.concurrency == 3:
            args.concurrency = 2


def _apply_phase4_preset(args: argparse.Namespace) -> None:
    preset = getattr(args, "preset", "default")
    if preset == "game" and args.max_key_moments == 12:
        args.max_key_moments = 16
    if preset == "speech" and args.max_key_moments == 12:
        args.max_key_moments = 10


def _apply_provider_defaults(args: argparse.Namespace) -> None:
    provider = getattr(args, "provider", "siliconflow")
    if not hasattr(args, "api_base"):
        return

    current_base = str(getattr(args, "api_base", "")).strip()
    current_key_env = str(getattr(args, "api_key_env", "")).strip() if hasattr(args, "api_key_env") else ""

    if provider == "openai":
        if current_base == "https://api.siliconflow.cn/v1":
            args.api_base = "https://api.openai.com/v1"
        if current_key_env == "SILICONFLOW_API_KEY":
            args.api_key_env = "OPENAI_API_KEY"
    elif provider == "lmstudio":
        if current_base == "https://api.siliconflow.cn/v1":
            args.api_base = "http://127.0.0.1:1234/v1"
        if hasattr(args, "send_auth_header") and args.send_auth_header is True:
            args.send_auth_header = False
    elif provider == "custom":
        # Respect user-specified api_base/api_key_env for custom providers.
        pass


def _load_dotenv_if_present(dotenv_path: Path = Path(".env")) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if (not line) or line.startswith("#") or ("=" not in line):
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (key not in os.environ):
            os.environ[key] = value


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
    parser.add_argument("--model-path", default=None, help="Local whisper model directory path")
    parser.add_argument("--hf-endpoint", default=None, help="HF endpoint/mirror, e.g. https://hf-mirror.com")
    parser.add_argument("--http-proxy", default=None, help="HTTP proxy URL")
    parser.add_argument("--https-proxy", default=None, help="HTTPS proxy URL")
    parser.add_argument("--hf-home", default=None, help="HF cache directory")
    parser.add_argument("--offline", action="store_true", help="Offline mode, disable online model download")
    parser.add_argument("--verbose", action="store_true", help="Enable friendly progress logs")
    parser.add_argument("--debug", action="store_true", help="Enable debug logs")
    parser.add_argument("--log-file", default=None, help="Write logs to file")

    subparsers = parser.add_subparsers(dest="command")

    phase1 = subparsers.add_parser("phase1", help="Run phase1 audio+ASR pipeline")
    phase1.add_argument("--input", required=True, help="Input video path")
    phase1.add_argument("--output", default="outputs", help="Output root directory")
    phase1.add_argument("--model", default="small", help="faster-whisper model")
    phase1.add_argument("--model-path", default=None, help="Local whisper model directory path")
    phase1.add_argument("--language", default=None, help="Language code, e.g. zh/en")
    phase1.add_argument("--device", default="auto", help="Compute device: auto/cuda/cpu")
    phase1.add_argument("--compute-type", default="int8", help="faster-whisper compute type")
    phase1.add_argument("--hf-endpoint", default=None, help="HF endpoint/mirror, e.g. https://hf-mirror.com")
    phase1.add_argument("--http-proxy", default=None, help="HTTP proxy URL")
    phase1.add_argument("--https-proxy", default=None, help="HTTPS proxy URL")
    phase1.add_argument("--hf-home", default=None, help="HF cache directory")
    phase1.add_argument("--offline", action="store_true", help="Offline mode, disable online model download")

    router = subparsers.add_parser("router", help="Run phase2 transcript router")
    router.add_argument("--transcript-jsonl", required=True, help="Phase1 transcript.segments.jsonl")
    router.add_argument("--output", default=None, help="Router output directory (default: sibling phase2)")
    router.add_argument("--top-k", type=int, default=18, help="Max candidate segments before merge")
    router.add_argument("--min-score", type=float, default=2.0, help="Score threshold")
    router.add_argument("--merge-gap-seconds", type=float, default=8.0, help="Merge adjacent windows")
    router.add_argument("--context-window", type=int, default=1, help="Neighbor segments for context")
    router.add_argument("--min-plan-items", type=int, default=8, help="Backfill to at least N items")

    phase2_fixed = subparsers.add_parser(
        "phase2-fixed",
        help="Run phase2 fixed-interval screenshot + VLM payload preparation",
    )
    phase2_fixed.add_argument("--phase1-dir", required=True, help="Phase1 output directory")
    phase2_fixed.add_argument(
        "--output",
        default=None,
        help="Phase2 output directory (default: sibling phase2_fixed)",
    )
    phase2_fixed.add_argument("--interval-seconds", type=float, default=30.0, help="Fixed capture interval")
    phase2_fixed.add_argument(
        "--preset",
        default="default",
        choices=["default", "game", "speech"],
        help="Friendly preset: default/game/speech",
    )
    phase2_fixed.add_argument("--start-seconds", type=float, default=0.0, help="Capture start")
    phase2_fixed.add_argument("--end-trim-seconds", type=float, default=2.0, help="Skip tail seconds")
    phase2_fixed.add_argument(
        "--no-capture-images",
        action="store_true",
        help="Only generate plan/payload without ffmpeg screenshots",
    )
    phase2_fixed.add_argument("--image-format", default="jpg", choices=["jpg", "png"], help="Image format")
    phase2_fixed.add_argument(
        "--without-segment-text",
        action="store_true",
        help="Disable aligned transcript segment text",
    )
    phase2_fixed.add_argument("--context-window", type=int, default=1, help="Neighbor transcript window size")
    phase2_fixed.add_argument(
        "--with-audio-summary",
        action="store_true",
        help="Attach compact phase1 audio summary to each payload",
    )
    phase2_fixed.add_argument(
        "--summary-max-points",
        type=int,
        default=8,
        help="Max timeline bullets for generated audio summary",
    )

    phase3_vlm = subparsers.add_parser(
        "phase3-vlm",
        help="Run phase3 VLM analysis on phase2 payload",
    )
    phase3_vlm.add_argument("--vlm-payload-jsonl", required=True, help="Input payload from phase2-fixed")
    phase3_vlm.add_argument(
        "--output",
        default=None,
        help="Phase3 output directory (default: sibling phase3_vlm)",
    )
    phase3_vlm.add_argument("--api-base", default="https://api.siliconflow.cn/v1", help="API base URL")
    phase3_vlm.add_argument(
        "--provider",
        default="siliconflow",
        choices=["siliconflow", "openai", "lmstudio", "custom"],
        help="OpenAI-compatible provider preset",
    )
    phase3_vlm.add_argument(
        "--preset",
        default="default",
        choices=["default", "game", "speech"],
        help="Friendly preset: default/game/speech",
    )
    phase3_vlm.add_argument("--model", default="deepseek-ai/DeepSeek-OCR", help="VLM model name")
    phase3_vlm.add_argument("--api-key", default=None, help="API key (prefer environment variable)")
    phase3_vlm.add_argument(
        "--api-key-env",
        default="SILICONFLOW_API_KEY",
        help="Environment variable that stores API key",
    )
    phase3_vlm.add_argument(
        "--no-auth",
        action="store_false",
        dest="send_auth_header",
        help="Disable Authorization header (for local LM Studio, etc.)",
    )
    phase3_vlm.set_defaults(send_auth_header=True)
    phase3_vlm.add_argument(
        "--without-image",
        action="store_true",
        help="Send text-only context without image to compare effect",
    )
    phase3_vlm.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature")
    phase3_vlm.add_argument("--timeout-seconds", type=float, default=120.0, help="HTTP timeout")
    phase3_vlm.add_argument("--concurrency", type=int, default=3, help="Concurrent API requests")
    phase3_vlm.add_argument("--max-retries", type=int, default=1, help="Retries for failed API calls")
    phase3_vlm.add_argument("--retry-backoff-seconds", type=float, default=2.0, help="Retry backoff seconds")
    phase3_vlm.add_argument(
        "--max-items",
        type=int,
        default=0,
        help="Limit processed items (0 means all)",
    )

    phase4_summary = subparsers.add_parser(
        "phase4-summary",
        help="Generate final summaries from phase1 + phase3 outputs",
    )
    phase4_summary.add_argument("--phase1-dir", required=True, help="Phase1 output directory")
    phase4_summary.add_argument(
        "--phase3-jsonl",
        required=True,
        help="Phase3 visual_analysis.jsonl path",
    )
    phase4_summary.add_argument(
        "--phase2-payload-jsonl",
        default=None,
        help="Optional phase2 vlm_payload.jsonl to enrich context",
    )
    phase4_summary.add_argument(
        "--preset",
        default="default",
        choices=["default", "game", "speech"],
        help="Friendly preset: default/game/speech",
    )
    phase4_summary.add_argument(
        "--output",
        default=None,
        help="Phase4 output directory (default: sibling phase4_summary)",
    )
    phase4_summary.add_argument(
        "--use-llm-polish",
        action="store_true",
        help="Use LLM to polish audio summary and final summary",
    )
    phase4_summary.add_argument("--api-base", default="https://api.siliconflow.cn/v1", help="API base URL")
    phase4_summary.add_argument(
        "--provider",
        default="siliconflow",
        choices=["siliconflow", "openai", "lmstudio", "custom"],
        help="OpenAI-compatible provider preset",
    )
    phase4_summary.add_argument("--llm-model", default="Qwen/Qwen3-8B", help="Text model name")
    phase4_summary.add_argument("--api-key", default=None, help="API key (prefer environment variable)")
    phase4_summary.add_argument(
        "--api-key-env",
        default="SILICONFLOW_API_KEY",
        help="Environment variable that stores API key",
    )
    phase4_summary.add_argument(
        "--no-auth",
        action="store_false",
        dest="send_auth_header",
        help="Disable Authorization header (for local LM Studio, etc.)",
    )
    phase4_summary.set_defaults(send_auth_header=True)
    phase4_summary.add_argument("--timeout-seconds", type=float, default=120.0, help="HTTP timeout")
    phase4_summary.add_argument(
        "--max-key-moments",
        type=int,
        default=12,
        help="Max key timestamps in key_moments_summary",
    )

    run_all = subparsers.add_parser("run-all", help="Run phase1 -> phase2-fixed -> phase3-vlm -> phase4-summary")
    run_all.add_argument("--input", required=True, help="Input video path")
    run_all.add_argument("--output", default="outputs", help="Output root directory")
    run_all.add_argument("--model", default="small", help="faster-whisper model")
    run_all.add_argument("--model-path", default=None, help="Local whisper model directory path")
    run_all.add_argument("--device", default="auto", help="Compute device")
    run_all.add_argument("--compute-type", default="int8", help="faster-whisper compute type")
    run_all.add_argument("--language", default=None, help="Language code")
    run_all.add_argument("--hf-endpoint", default=None, help="HF endpoint/mirror, e.g. https://hf-mirror.com")
    run_all.add_argument("--http-proxy", default=None, help="HTTP proxy URL")
    run_all.add_argument("--https-proxy", default=None, help="HTTPS proxy URL")
    run_all.add_argument("--hf-home", default=None, help="HF cache directory")
    run_all.add_argument("--offline", action="store_true", help="Offline mode, disable online model download")
    run_all.add_argument("--interval-seconds", type=float, default=30.0, help="Phase2 fixed capture interval")
    run_all.add_argument("--context-window", type=int, default=1, help="Phase2 context window")
    run_all.add_argument("--with-audio-summary", action="store_true", help="Attach phase1 summary to phase2 payload")
    run_all.add_argument("--api-base", default="https://api.siliconflow.cn/v1", help="API base URL")
    run_all.add_argument(
        "--provider",
        default="siliconflow",
        choices=["siliconflow", "openai", "lmstudio", "custom"],
        help="OpenAI-compatible provider preset",
    )
    run_all.add_argument("--vlm-model", default="deepseek-ai/DeepSeek-OCR", help="Phase3 VLM model")
    run_all.add_argument("--temperature", type=float, default=0.2, help="Phase3 sampling temperature")
    run_all.add_argument("--concurrency", type=int, default=3, help="Phase3 concurrent API requests")
    run_all.add_argument("--llm-model", default="Qwen/Qwen3-8B", help="Phase4 text model")
    run_all.add_argument("--api-key", default=None, help="API key")
    run_all.add_argument("--api-key-env", default="SILICONFLOW_API_KEY", help="API key env var")
    run_all.add_argument(
        "--no-auth",
        action="store_false",
        dest="send_auth_header",
        help="Disable Authorization header (for local LM Studio, etc.)",
    )
    run_all.set_defaults(send_auth_header=True)
    run_all.add_argument("--timeout-seconds", type=float, default=120.0, help="HTTP timeout")
    run_all.add_argument("--max-retries", type=int, default=1, help="Phase3 retries")
    run_all.add_argument("--retry-backoff-seconds", type=float, default=2.0, help="Phase3 retry backoff")
    run_all.add_argument("--use-llm-polish", action="store_true", help="Enable phase4 polishing")
    run_all.add_argument("--max-key-moments", type=int, default=12, help="Phase4 key moments")
    run_all.add_argument(
        "--preset",
        default="default",
        choices=["default", "game", "speech"],
        help="Friendly preset for phase2/3/4",
    )

    subparsers.add_parser("gui", help="Launch simple GUI control panel")
    return parser


def main() -> None:
    _load_dotenv_if_present()
    args = build_parser().parse_args()
    configure_logging(verbose=args.verbose, debug=args.debug, log_file=args.log_file)

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

    if args.command == "phase2-fixed":
        _apply_phase2_preset(args)
        phase1_dir = Path(args.phase1_dir).resolve()
        if args.output:
            output_root = Path(args.output).resolve()
        else:
            output_root = phase1_dir.parent / "phase2_fixed"

        run_dir = run_phase2_fixed(
            Phase2FixedConfig(
                phase1_dir=phase1_dir,
                output_root=output_root,
                interval_seconds=args.interval_seconds,
                start_seconds=args.start_seconds,
                end_trim_seconds=args.end_trim_seconds,
                capture_images=not args.no_capture_images,
                image_format=args.image_format,
                with_segment_text=not args.without_segment_text,
                context_window=args.context_window,
                with_audio_summary=args.with_audio_summary,
                summary_max_points=args.summary_max_points,
            )
        )
        print(f"Phase-2 fixed completed: {run_dir}")
        return

    if args.command == "phase3-vlm":
        _apply_provider_defaults(args)
        _apply_phase3_preset(args)
        payload_jsonl = Path(args.vlm_payload_jsonl).resolve()
        if args.output:
            output_root = Path(args.output).resolve()
        else:
            output_root = payload_jsonl.parent / "phase3_vlm"

        run_dir = run_phase3_vlm(
            Phase3VlmConfig(
                vlm_payload_jsonl=payload_jsonl,
                output_root=output_root,
                api_base=args.api_base,
                model=args.model,
                api_key=args.api_key,
                api_key_env=args.api_key_env,
                send_auth_header=args.send_auth_header,
                include_image=not args.without_image,
                temperature=args.temperature,
                timeout_seconds=args.timeout_seconds,
                max_items=args.max_items,
                max_retries=args.max_retries,
                retry_backoff_seconds=args.retry_backoff_seconds,
                concurrency=args.concurrency,
            )
        )
        print(f"Phase-3 VLM completed: {run_dir}")
        return

    if args.command == "phase4-summary":
        _apply_provider_defaults(args)
        _apply_phase4_preset(args)
        phase1_dir = Path(args.phase1_dir).resolve()
        phase3_jsonl = Path(args.phase3_jsonl).resolve()

        if args.output:
            output_root = Path(args.output).resolve()
        else:
            output_root = phase3_jsonl.parent / "phase4_summary"

        phase2_payload_jsonl = Path(args.phase2_payload_jsonl).resolve() if args.phase2_payload_jsonl else None

        run_dir = run_phase4_summary(
            Phase4SummaryConfig(
                phase1_dir=phase1_dir,
                phase3_jsonl=phase3_jsonl,
                phase2_payload_jsonl=phase2_payload_jsonl,
                output_root=output_root,
                use_llm_polish=args.use_llm_polish,
                api_base=args.api_base,
                llm_model=args.llm_model,
                api_key=args.api_key,
                api_key_env=args.api_key_env,
                send_auth_header=args.send_auth_header,
                timeout_seconds=args.timeout_seconds,
                max_key_moments=args.max_key_moments,
            )
        )
        print(f"Phase-4 summary completed: {run_dir}")
        return

    if args.command == "run-all":
        _apply_provider_defaults(args)
        _apply_phase2_preset(args)
        _apply_phase3_preset(args)
        _apply_phase4_preset(args)

        input_video = Path(args.input).resolve()
        output_root = Path(args.output).resolve()
        log_phase("run-all", f"开始端到端流程: {input_video.name}")

        phase1_dir = run_phase1(
            Phase1Config(
                input_video=input_video,
                output_root=output_root,
                model_name=args.model,
                model_path=Path(args.model_path).resolve() if args.model_path else None,
                language=args.language,
                device=args.device,
                compute_type=args.compute_type,
                hf_endpoint=args.hf_endpoint,
                http_proxy=args.http_proxy,
                https_proxy=args.https_proxy,
                hf_home=Path(args.hf_home).resolve() if args.hf_home else None,
                offline=args.offline,
            )
        )
        phase2_dir = run_phase2_fixed(
            Phase2FixedConfig(
                phase1_dir=phase1_dir,
                output_root=phase1_dir.parent / "phase2_fixed",
                interval_seconds=args.interval_seconds,
                context_window=args.context_window,
                with_audio_summary=args.with_audio_summary,
            )
        )
        phase3_dir = run_phase3_vlm(
            Phase3VlmConfig(
                vlm_payload_jsonl=phase2_dir / "vlm_payload.jsonl",
                output_root=phase2_dir / "phase3_vlm",
                api_base=args.api_base,
                model=args.vlm_model,
                api_key=args.api_key,
                api_key_env=args.api_key_env,
                send_auth_header=args.send_auth_header,
                temperature=args.temperature,
                timeout_seconds=args.timeout_seconds,
                max_retries=args.max_retries,
                retry_backoff_seconds=args.retry_backoff_seconds,
                concurrency=args.concurrency,
            )
        )
        phase4_dir = run_phase4_summary(
            Phase4SummaryConfig(
                phase1_dir=phase1_dir,
                phase3_jsonl=phase3_dir / "visual_analysis.jsonl",
                phase2_payload_jsonl=phase2_dir / "vlm_payload.jsonl",
                output_root=phase3_dir / "phase4_summary",
                use_llm_polish=args.use_llm_polish,
                api_base=args.api_base,
                llm_model=args.llm_model,
                api_key=args.api_key,
                api_key_env=args.api_key_env,
                send_auth_header=args.send_auth_header,
                timeout_seconds=args.timeout_seconds,
                max_key_moments=args.max_key_moments,
            )
        )
        print(f"Run-all completed: phase1={phase1_dir} | phase2={phase2_dir} | phase3={phase3_dir} | phase4={phase4_dir}")
        return

    if args.command == "gui":
        from videosummary.gui import main as run_gui

        run_gui()
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
            model_path=Path(args.model_path).resolve() if hasattr(args, "model_path") and args.model_path else None,
            language=args.language,
            device=args.device,
            compute_type=args.compute_type,
            hf_endpoint=args.hf_endpoint if hasattr(args, "hf_endpoint") else None,
            http_proxy=args.http_proxy if hasattr(args, "http_proxy") else None,
            https_proxy=args.https_proxy if hasattr(args, "https_proxy") else None,
            hf_home=Path(args.hf_home).resolve() if hasattr(args, "hf_home") and args.hf_home else None,
            offline=bool(args.offline) if hasattr(args, "offline") else False,
        )
    )
    print(f"Phase-1 completed: {run_dir}")


if __name__ == "__main__":
    main()
