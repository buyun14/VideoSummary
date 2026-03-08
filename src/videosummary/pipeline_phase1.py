from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel


@dataclass
class Phase1Config:
    input_video: Path
    output_root: Path
    model_name: str = "small"
    language: str | None = None
    device: str = "auto"
    compute_type: str = "int8"


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
    if not config.input_video.exists():
        raise FileNotFoundError(f"Input video not found: {config.input_video}")

    video_stem = config.input_video.stem
    run_dir = config.output_root / video_stem / "phase1"
    run_dir.mkdir(parents=True, exist_ok=True)

    audio_path = run_dir / "audio_16k_mono.wav"
    _extract_audio(config.input_video, audio_path)

    model = WhisperModel(
        config.model_name,
        device=config.device,
        compute_type=config.compute_type,
    )

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
            "model": config.model_name,
            "language": info.language,
            "language_probability": float(info.language_probability),
            "duration": float(info.duration),
        },
        "segments": segments,
    }

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

    return run_dir
