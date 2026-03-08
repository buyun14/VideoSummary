from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


@dataclass
class Phase3VlmConfig:
    vlm_payload_jsonl: Path
    output_root: Path
    api_base: str = "https://api.siliconflow.cn/v1"
    model: str = "deepseek-ai/DeepSeek-OCR"
    api_key: str | None = None
    api_key_env: str = "SILICONFLOW_API_KEY"
    include_image: bool = True
    temperature: float = 0.2
    timeout_seconds: float = 120.0
    max_items: int = 0


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _format_context(item: dict[str, Any]) -> str:
    lines = [
        f"capture_time_ts: {item.get('capture_time_ts', '')}",
        f"relative_position: {item.get('relative_position', '')}",
        f"segment_text: {item.get('segment_text', '')}",
        f"context_text: {item.get('context_text', '')}",
    ]
    if "audio_summary" in item:
        lines.append(f"audio_summary: {item.get('audio_summary', '')}")
    return "\n".join(lines)


def _mime_from_path(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    return "image/jpeg"


def _image_to_data_uri(image_path: Path) -> str:
    data = image_path.read_bytes()
    mime = _mime_from_path(image_path)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _extract_content_text(message_content: Any) -> str:
    if isinstance(message_content, str):
        return message_content
    if isinstance(message_content, list):
        chunks: list[str] = []
        for item in message_content:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text", "")))
        return "\n".join(chunks).strip()
    return str(message_content)


def _build_messages(item: dict[str, Any], include_image: bool) -> list[dict[str, Any]]:
    system_text = (
        "You are a video-frame analysis assistant. "
        "Use screenshot evidence first, then use transcript context to reduce ambiguity. "
        "Return concise, factual observations in Chinese."
    )

    user_text = (
        "请分析这一帧截图，并结合附加上下文给出：\n"
        "1) 画面中可见的关键元素\n"
        "2) 与文本上下文一致的解释\n"
        "3) 不确定项（如果有）\n\n"
        "附加上下文:\n"
        f"{_format_context(item)}"
    )

    user_content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]

    if include_image:
        image_path = Path(str(item["image_path"]))
        if image_path.exists():
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _image_to_data_uri(image_path)},
                }
            )

    return [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_content},
    ]


def run_phase3_vlm(config: Phase3VlmConfig) -> Path:
    payload_path = config.vlm_payload_jsonl.resolve()
    if not payload_path.exists():
        raise FileNotFoundError(f"VLM payload not found: {payload_path}")

    api_key = config.api_key or os.getenv(config.api_key_env)
    if not api_key:
        raise RuntimeError(
            f"Missing API key. Provide --api-key or set environment variable {config.api_key_env}."
        )

    rows = _read_jsonl(payload_path)
    if config.max_items > 0:
        rows = rows[: config.max_items]

    output_dir = config.output_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    analysis_jsonl_path = output_dir / "visual_analysis.jsonl"
    manifest_path = output_dir / "phase3_vlm_manifest.json"

    endpoint = config.api_base.rstrip("/") + "/chat/completions"
    success = 0
    failed = 0

    with httpx.Client(timeout=config.timeout_seconds) as client, analysis_jsonl_path.open(
        "w", encoding="utf-8"
    ) as out:
        for row in rows:
            request_messages = _build_messages(row, include_image=config.include_image)
            request_payload = {
                "model": config.model,
                "messages": request_messages,
                "temperature": config.temperature,
            }

            try:
                resp = client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_payload,
                )
                resp.raise_for_status()
                data = resp.json()
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                content_text = _extract_content_text(message.get("content", ""))
                usage = data.get("usage", {})

                record = {
                    "id": row.get("id"),
                    "image_path": row.get("image_path"),
                    "capture_time": row.get("capture_time"),
                    "capture_time_ts": row.get("capture_time_ts"),
                    "model": config.model,
                    "analysis": content_text,
                    "usage": usage,
                    "status": "ok",
                }
                success += 1
            except Exception as exc:
                record = {
                    "id": row.get("id"),
                    "image_path": row.get("image_path"),
                    "capture_time": row.get("capture_time"),
                    "capture_time_ts": row.get("capture_time_ts"),
                    "model": config.model,
                    "analysis": "",
                    "error": str(exc),
                    "status": "error",
                }
                failed += 1

            out.write(json.dumps(record, ensure_ascii=False) + "\n")

    manifest = {
        "stage": "phase3_vlm",
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "vlm_payload_jsonl": str(payload_path),
            "items": len(rows),
        },
        "request": {
            "api_base": config.api_base,
            "model": config.model,
            "include_image": config.include_image,
            "temperature": config.temperature,
            "timeout_seconds": config.timeout_seconds,
            "api_key_env": config.api_key_env,
        },
        "outputs": {
            "visual_analysis_jsonl": str(analysis_jsonl_path),
        },
        "stats": {
            "success": success,
            "failed": failed,
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return output_dir
