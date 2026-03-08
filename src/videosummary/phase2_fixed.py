from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Phase2FixedConfig:
    phase1_dir: Path
    output_root: Path
    interval_seconds: float = 30.0
    start_seconds: float = 0.0
    end_trim_seconds: float = 2.0
    capture_images: bool = True
    image_format: str = "jpg"
    with_segment_text: bool = True
    context_window: int = 1
    with_audio_summary: bool = False
    summary_max_points: int = 8


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


def _format_ts(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{ms:03}"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _timestamps(start: float, stop: float, interval: float) -> list[float]:
    if interval <= 0:
        raise ValueError("interval_seconds must be > 0")
    points: list[float] = []
    t = max(0.0, start)
    while t <= stop:
        points.append(round(t, 3))
        t += interval
    return points


def _nearest_segment_index(segments: list[dict[str, Any]], timestamp: float) -> int:
    if not segments:
        return -1

    best_idx = 0
    best_distance = float("inf")
    for i, seg in enumerate(segments):
        start = float(seg["start"])
        end = float(seg["end"])
        if start <= timestamp <= end:
            return i
        center = (start + end) / 2.0
        distance = abs(center - timestamp)
        if distance < best_distance:
            best_distance = distance
            best_idx = i
    return best_idx


def _context_text(segments: list[dict[str, Any]], center_idx: int, window: int) -> str:
    if center_idx < 0:
        return ""
    left = max(0, center_idx - window)
    right = min(len(segments), center_idx + window + 1)
    lines: list[str] = []
    for i in range(left, right):
        seg = segments[i]
        lines.append(
            f"[{_format_ts(float(seg['start']))}-{_format_ts(float(seg['end']))}] {str(seg.get('text', '')).strip()}"
        )
    return "\n".join(lines)


def _build_audio_summary(segments: list[dict[str, Any]], max_points: int) -> str:
    if not segments:
        return ""
    count = max(1, min(max_points, len(segments)))
    bullets: list[str] = []
    for i in range(count):
        idx = int(i * len(segments) / count)
        seg = segments[min(idx, len(segments) - 1)]
        text = str(seg.get("text", "")).strip()
        if len(text) > 80:
            text = text[:77] + "..."
        bullets.append(f"- {_format_ts(float(seg['start']))}: {text}")
    return "\n".join(bullets)


def _capture_frame(video_path: Path, timestamp: float, image_path: Path) -> None:
    image_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        str(timestamp),
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(image_path),
    ]
    _run_cmd(command)


def run_phase2_fixed(config: Phase2FixedConfig) -> Path:
    phase1_dir = config.phase1_dir.resolve()
    if not phase1_dir.exists():
        raise FileNotFoundError(f"phase1 dir not found: {phase1_dir}")

    phase1_manifest_path = phase1_dir / "phase1_manifest.json"
    transcript_jsonl_path = phase1_dir / "transcript.segments.jsonl"
    transcript_full_path = phase1_dir / "transcript.full.json"

    if not phase1_manifest_path.exists():
        raise FileNotFoundError(f"Missing phase1 manifest: {phase1_manifest_path}")
    if not transcript_jsonl_path.exists():
        raise FileNotFoundError(f"Missing transcript jsonl: {transcript_jsonl_path}")
    if not transcript_full_path.exists():
        raise FileNotFoundError(f"Missing transcript full json: {transcript_full_path}")

    phase1_manifest = _read_json(phase1_manifest_path)
    transcript_full = _read_json(transcript_full_path)
    segments = _read_jsonl(transcript_jsonl_path)

    video_path = Path(phase1_manifest["video"])
    if not video_path.exists():
        raise FileNotFoundError(f"Original video not found: {video_path}")

    duration = float(transcript_full["meta"]["duration"])
    end_limit = max(0.0, duration - max(0.0, config.end_trim_seconds))
    timestamps = _timestamps(config.start_seconds, end_limit, config.interval_seconds)

    output_dir = config.output_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    image_dir = output_dir / "screenshots"

    audio_summary = ""
    if config.with_audio_summary:
        audio_summary = _build_audio_summary(segments, max_points=config.summary_max_points)

    plan_items: list[dict[str, Any]] = []
    for i, timestamp in enumerate(timestamps, start=1):
        center_idx = _nearest_segment_index(segments, timestamp)
        seg_text = ""
        if center_idx >= 0 and config.with_segment_text:
            seg_text = str(segments[center_idx].get("text", "")).strip()

        context_text = ""
        if center_idx >= 0 and config.context_window > 0:
            context_text = _context_text(segments, center_idx=center_idx, window=config.context_window)

        image_path = image_dir / f"frame_{i:04d}_{int(round(timestamp * 1000)):010d}.{config.image_format}"
        if config.capture_images:
            _capture_frame(video_path, timestamp, image_path)

        item: dict[str, Any] = {
            "id": i,
            "capture_time": timestamp,
            "capture_time_ts": _format_ts(timestamp),
            "relative_position": round(timestamp / duration, 6) if duration > 0 else 0.0,
            "image_path": str(image_path),
            "segment_text": seg_text,
            "context_text": context_text,
        }

        if config.with_audio_summary:
            item["audio_summary"] = audio_summary

        plan_items.append(item)

    plan_json_path = output_dir / "fixed_keyframe_plan.json"
    vlm_payload_jsonl_path = output_dir / "vlm_payload.jsonl"
    summary_txt_path = output_dir / "audio_summary.txt"
    manifest_path = output_dir / "phase2_fixed_manifest.json"

    plan_payload = {
        "meta": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "video": str(video_path),
            "phase1_dir": str(phase1_dir),
            "strategy": "fixed_interval",
            "options": {
                "interval_seconds": config.interval_seconds,
                "start_seconds": config.start_seconds,
                "end_trim_seconds": config.end_trim_seconds,
                "capture_images": config.capture_images,
                "image_format": config.image_format,
                "with_segment_text": config.with_segment_text,
                "context_window": config.context_window,
                "with_audio_summary": config.with_audio_summary,
                "summary_max_points": config.summary_max_points,
            },
        },
        "items": plan_items,
    }
    plan_json_path.write_text(
        json.dumps(plan_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with vlm_payload_jsonl_path.open("w", encoding="utf-8") as f:
        for item in plan_items:
            payload = {
                "id": item["id"],
                "image_path": item["image_path"],
                "capture_time": item["capture_time"],
                "capture_time_ts": item["capture_time_ts"],
                "relative_position": item["relative_position"],
                "segment_text": item["segment_text"],
                "context_text": item["context_text"],
            }
            if config.with_audio_summary:
                payload["audio_summary"] = item.get("audio_summary", "")
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    if config.with_audio_summary:
        summary_txt_path.write_text(audio_summary, encoding="utf-8")

    manifest = {
        "stage": "phase2_fixed",
        "status": "completed",
        "input": {
            "phase1_dir": str(phase1_dir),
            "video": str(video_path),
            "transcript_jsonl": str(transcript_jsonl_path),
        },
        "outputs": {
            "plan_json": str(plan_json_path),
            "vlm_payload_jsonl": str(vlm_payload_jsonl_path),
            "screenshots_dir": str(image_dir),
            "audio_summary_txt": str(summary_txt_path) if config.with_audio_summary else None,
        },
        "stats": {
            "duration_seconds": duration,
            "frames_planned": len(plan_items),
            "frames_captured": len(plan_items) if config.capture_images else 0,
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return output_dir
