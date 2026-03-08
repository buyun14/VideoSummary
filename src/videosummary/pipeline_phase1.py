from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel

from videosummary.logging_utils import log_phase, timed_step


@dataclass
class Phase1Config:
    input_video: Path
    output_root: Path
    model_name: str = "small"
    language: str | None = None
    device: str = "auto"
    compute_type: str = "int8"
    model_path: Path | None = None
    hf_endpoint: str | None = None
    http_proxy: str | None = None
    https_proxy: str | None = None
    hf_home: Path | None = None
    offline: bool = False


def _configure_model_download_env(config: Phase1Config) -> None:
    # Configure Hugging Face and proxy environment for model download reliability.
    if config.hf_endpoint:
        os.environ["HF_ENDPOINT"] = config.hf_endpoint
    if config.http_proxy:
        os.environ["HTTP_PROXY"] = config.http_proxy
    if config.https_proxy:
        os.environ["HTTPS_PROXY"] = config.https_proxy
    if config.hf_home:
        os.environ["HF_HOME"] = str(config.hf_home)
    if config.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"


def _build_phase1_error_hint(config: Phase1Config, err: Exception) -> str:
    err_text = str(err)
    tips: list[str] = []
    if ("ConnectTimeout" in err_text) or ("WinError 10060" in err_text):
        tips.append("网络连接超时，建议设置 --hf-endpoint https://hf-mirror.com 或配置 --https-proxy。")
    if ("LocalEntryNotFoundError" in err_text) or ("cannot find" in err_text.lower()):
        tips.append("本地缓存未命中，建议指定 --model-path <本地whisper模型目录> 或关闭 --offline。")
    tips.append("可选：指定 --hf-home <缓存目录>，减少重复下载。")
    tips.append("可选：先用 tiny/base 预热模型，再切 small/medium。")
    return "\n".join([f"模型加载失败: {err_text}", *tips])


def _run_cmd(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(command)
            + "\n\nSTDOUT:\n"
            + result.stdout
            + "\nSTDERR:\n"
            + result.stderr
        )


def _format_ts_srt(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, rem = divmod(milliseconds, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def _format_ts_compact(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, rem = divmod(milliseconds, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{ms:03}"


def _extract_audio(input_video: Path, audio_path: Path) -> None:
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(audio_path),
    ]
    _run_cmd(command)


def _save_srt(segments: list[dict[str, Any]], path: Path) -> None:
    lines: list[str] = []
    for i, segment in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(
            f"{_format_ts_srt(segment['start'])} --> {_format_ts_srt(segment['end'])}"
        )
        lines.append(segment["text"].strip())
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _save_text(segments: list[dict[str, Any]], path: Path) -> None:
    lines: list[str] = []
    for segment in segments:
        start = _format_ts_compact(segment["start"])
        end = _format_ts_compact(segment["end"])
        lines.append(f"[{start} - {end}] {segment['text'].strip()}")
    path.write_text("\n".join(lines), encoding="utf-8")


def _serialize_segments(raw_segments: list[Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for segment in raw_segments:
        words_payload: list[dict[str, Any]] = []
        if segment.words:
            for word in segment.words:
                words_payload.append(
                    {
                        "word": word.word,
                        "start": float(word.start) if word.start is not None else None,
                        "end": float(word.end) if word.end is not None else None,
                        "probability": float(word.probability),
                    }
                )
        segments.append(
            {
                "id": segment.id,
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text,
                "avg_logprob": float(segment.avg_logprob),
                "no_speech_prob": float(segment.no_speech_prob),
                "words": words_payload,
            }
        )
    return segments


def run_phase1(config: Phase1Config) -> Path:
    phase = "phase1"
    if not config.input_video.exists():
        raise FileNotFoundError(f"Input video not found: {config.input_video}")

    video_stem = config.input_video.stem
    run_dir = config.output_root / video_stem / "phase1"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_phase(phase, f"输出目录: {run_dir}")

    audio_path = run_dir / "audio_16k_mono.wav"
    with timed_step(phase, "音频提取 (ffmpeg)"):
        _extract_audio(config.input_video, audio_path)

    _configure_model_download_env(config)
    model_ref = str(config.model_path) if config.model_path else config.model_name
    if config.model_path:
        model_dir = config.model_path.resolve()
        if not model_dir.exists():
            raise FileNotFoundError(f"指定的本地模型目录不存在: {model_dir}")
        log_phase(phase, f"使用本地模型目录: {model_dir}")
    if config.hf_endpoint:
        log_phase(phase, f"HF 镜像源: {config.hf_endpoint}")
    if config.http_proxy or config.https_proxy:
        log_phase(phase, "已启用代理配置")
    if config.offline:
        log_phase(phase, "离线模式已启用 (HF_HUB_OFFLINE=1)")

    with timed_step(phase, f"加载 ASR 模型: {model_ref}"):
        try:
            model = WhisperModel(
                model_ref,
                device=config.device,
                compute_type=config.compute_type,
            )
        except Exception as exc:
            raise RuntimeError(_build_phase1_error_hint(config, exc)) from exc

    with timed_step(phase, "执行 ASR 转写"):
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=config.language,
            vad_filter=True,
            word_timestamps=True,
            beam_size=5,
            condition_on_previous_text=False,
        )
        raw_segments = list(segments_iter)
        segments = _serialize_segments(raw_segments)
    log_phase(phase, f"ASR 完成: 片段数={len(segments)}, 语言={info.language}, 时长={float(info.duration):.2f}s")

    transcript_json_path = run_dir / "transcript.full.json"
    transcript_jsonl_path = run_dir / "transcript.segments.jsonl"
    transcript_txt_path = run_dir / "transcript.txt"
    transcript_srt_path = run_dir / "transcript.srt"
    manifest_path = run_dir / "phase1_manifest.json"

    transcript_payload = {
        "meta": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "video": str(config.input_video),
            "audio": str(audio_path),
            "model": model_ref,
            "language": info.language,
            "language_probability": float(info.language_probability),
            "duration": float(info.duration),
            "network": {
                "hf_endpoint": config.hf_endpoint,
                "hf_home": str(config.hf_home) if config.hf_home else None,
                "offline": config.offline,
                "proxy_enabled": bool(config.http_proxy or config.https_proxy),
            },
        },
        "segments": segments,
    }

    with timed_step(phase, "写入转写产物 (json/jsonl/txt/srt)"):
        transcript_json_path.write_text(
            json.dumps(transcript_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with transcript_jsonl_path.open("w", encoding="utf-8") as f:
            for segment in segments:
                f.write(json.dumps(segment, ensure_ascii=False) + "\n")

        _save_text(segments, transcript_txt_path)
        _save_srt(segments, transcript_srt_path)

    manifest = {
        "stage": "phase1",
        "status": "completed",
        "video": str(config.input_video),
        "audio": str(audio_path),
        "outputs": {
            "transcript_json": str(transcript_json_path),
            "transcript_jsonl": str(transcript_jsonl_path),
            "transcript_text": str(transcript_txt_path),
            "transcript_srt": str(transcript_srt_path),
        },
        "stats": {
            "segment_count": len(segments),
            "detected_language": info.language,
            "duration_seconds": float(info.duration),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log_phase(phase, f"阶段完成，manifest: {manifest_path}")

    return run_dir
