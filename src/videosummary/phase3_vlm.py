from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from videosummary.logging_utils import log_phase, timed_step


@dataclass
class Phase3VlmConfig:
    vlm_payload_jsonl: Path
    output_root: Path
    api_base: str = "https://api.siliconflow.cn/v1"
    model: str = "deepseek-ai/DeepSeek-OCR"
    api_key: str | None = None
    api_key_env: str = "SILICONFLOW_API_KEY"
    send_auth_header: bool = True
    include_image: bool = True
    temperature: float = 0.2
    timeout_seconds: float = 120.0
    max_items: int = 0
    max_retries: int = 1
    retry_backoff_seconds: float = 2.0
    concurrency: int = 3


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


def _is_local_lmstudio_base(api_base: str) -> bool:
    base = api_base.strip().lower()
    return ("127.0.0.1:1234" in base) or ("localhost:1234" in base)


def _fetch_available_model_ids(api_base: str, timeout_seconds: float) -> list[str]:
    url = api_base.rstrip("/") + "/models"
    with httpx.Client(timeout=timeout_seconds) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()

    rows = data.get("data", []) if isinstance(data, dict) else []
    model_ids: list[str] = []
    for row in rows:
        model_id = str((row or {}).get("id", "")).strip()
        if model_id:
            model_ids.append(model_id)
    return model_ids


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


async def _request_one(
    client: httpx.AsyncClient,
    endpoint: str,
    api_key: str | None,
    send_auth_header: bool,
    row: dict[str, Any],
    config: Phase3VlmConfig,
) -> tuple[dict[str, Any], float]:
    image_enabled = config.include_image
    degraded_no_image = False

    attempt = 0
    last_error = ""
    start = time.perf_counter()

    while attempt <= config.max_retries:
        attempt += 1
        try:
            request_messages = _build_messages(row, include_image=image_enabled)
            request_payload = {
                "model": config.model,
                "messages": request_messages,
                "temperature": config.temperature,
            }

            headers = {"Content-Type": "application/json"}
            if send_auth_header:
                headers["Authorization"] = f"Bearer {api_key or ''}"

            resp = await client.post(
                endpoint,
                headers=headers,
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
                "attempt": attempt,
                "degraded_no_image": degraded_no_image,
            }
            return record, time.perf_counter() - start
        except Exception as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                status_code = exc.response.status_code
                body = exc.response.text[:400]
                last_error = f"HTTP {status_code}: {body}"
                if (
                    image_enabled
                    and status_code == 400
                    and ("failed to process image" in body.lower())
                ):
                    # LM Studio may reject specific frames; fallback to text-only context for this item.
                    image_enabled = False
                    degraded_no_image = True
                    log_phase(
                        "phase3-vlm",
                        f"条目 {row.get('id')} 图像处理失败，自动降级为文本模式重试。",
                    )
                    attempt -= 1
                    continue
                if status_code == 400:
                    last_error += " | 提示: 可能是模型不支持当前多模态消息格式，请更换支持 image_url 的模型。"
            else:
                last_error = str(exc)

            if attempt <= config.max_retries:
                await asyncio.sleep(max(0.0, config.retry_backoff_seconds))
            else:
                record = {
                    "id": row.get("id"),
                    "image_path": row.get("image_path"),
                    "capture_time": row.get("capture_time"),
                    "capture_time_ts": row.get("capture_time_ts"),
                    "model": config.model,
                    "analysis": "",
                    "error": last_error,
                    "status": "error",
                    "attempt": attempt,
                    "degraded_no_image": degraded_no_image,
                }
                return record, time.perf_counter() - start

    # Defensive fallback, should never hit.
    fallback = {
        "id": row.get("id"),
        "image_path": row.get("image_path"),
        "capture_time": row.get("capture_time"),
        "capture_time_ts": row.get("capture_time_ts"),
        "model": config.model,
        "analysis": "",
        "error": "Unknown error",
        "status": "error",
        "attempt": attempt,
        "degraded_no_image": degraded_no_image,
    }
    return fallback, time.perf_counter() - start


async def _run_requests_concurrently(
    rows: list[dict[str, Any]],
    endpoint: str,
    api_key: str | None,
    send_auth_header: bool,
    config: Phase3VlmConfig,
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(max(1, config.concurrency))
    done = 0
    total = len(rows)
    done_lock = asyncio.Lock()
    results: list[dict[str, Any] | None] = [None] * total

    async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:

        async def _worker(index: int, row: dict[str, Any]) -> None:
            nonlocal done
            async with semaphore:
                record, elapsed = await _request_one(client, endpoint, api_key, send_auth_header, row, config)
            results[index] = record
            async with done_lock:
                done += 1
                log_phase(
                    "phase3-vlm",
                    f"进度: {done}/{total} | 状态={record['status']} | 耗时={elapsed:.2f}s | 并发={max(1, config.concurrency)}",
                )

        tasks = [asyncio.create_task(_worker(i, row)) for i, row in enumerate(rows)]
        await asyncio.gather(*tasks)

    return [x for x in results if x is not None]


def run_phase3_vlm(config: Phase3VlmConfig) -> Path:
    phase = "phase3-vlm"
    payload_path = config.vlm_payload_jsonl.resolve()
    if not payload_path.exists():
        raise FileNotFoundError(f"VLM payload not found: {payload_path}")

    api_key = config.api_key or os.getenv(config.api_key_env)
    if config.send_auth_header and not api_key:
        raise RuntimeError(
            f"Missing API key. Provide --api-key or set environment variable {config.api_key_env}."
        )
    if not config.send_auth_header:
        log_phase(phase, "已禁用 Authorization 请求头（适配本地/无鉴权 OpenAI 兼容接口）")

    if _is_local_lmstudio_base(config.api_base):
        if config.include_image and config.concurrency > 1:
            log_phase(
                phase,
                "检测到 LM Studio + 图像输入 + 并发>1，已自动降为串行并发=1，避免 Channel Error。",
            )
            config.concurrency = 1

        with timed_step(phase, "预检本地模型可用性"):
            try:
                model_ids = _fetch_available_model_ids(config.api_base, timeout_seconds=min(20.0, config.timeout_seconds))
            except Exception as exc:
                raise RuntimeError(
                    f"无法读取 LM Studio 模型列表: {exc}. 请确认 LM Studio 服务已启动且端口为 1234。"
                ) from exc

            if config.model not in model_ids:
                sample = ", ".join(model_ids[:8]) if model_ids else "(空)"
                raise RuntimeError(
                    "LM Studio 模型名不匹配。"
                    f" 当前配置: {config.model}\n"
                    f" 可用模型(前8个): {sample}\n"
                    "请在 GUI/CLI 中使用 /v1/models 返回的 정확 id，例如 qwen3.5-4b。"
                )

    rows = _read_jsonl(payload_path)
    if config.max_items > 0:
        rows = rows[: config.max_items]
    log_phase(phase, f"待分析条目: {len(rows)}")
    log_phase(phase, f"并发设置: {max(1, config.concurrency)}")

    output_dir = config.output_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    log_phase(phase, f"输出目录: {output_dir}")

    analysis_jsonl_path = output_dir / "visual_analysis.jsonl"
    manifest_path = output_dir / "phase3_vlm_manifest.json"

    endpoint = config.api_base.rstrip("/") + "/chat/completions"
    with timed_step(phase, "执行视觉模型调用"):
        records = asyncio.run(
            _run_requests_concurrently(
                rows=rows,
                endpoint=endpoint,
                api_key=api_key,
                send_auth_header=config.send_auth_header,
                config=config,
            )
        )

    success = sum(1 for x in records if x.get("status") == "ok")
    failed = len(records) - success

    with analysis_jsonl_path.open("w", encoding="utf-8") as out:
        for record in records:
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
            "send_auth_header": config.send_auth_header,
            "max_retries": config.max_retries,
            "retry_backoff_seconds": config.retry_backoff_seconds,
            "concurrency": max(1, config.concurrency),
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
    log_phase(phase, f"阶段完成: success={success}, failed={failed}, manifest={manifest_path}")

    return output_dir
