from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from videosummary.logging_utils import log_phase, timed_step


@dataclass
class Phase4SummaryConfig:
    phase1_dir: Path
    phase3_jsonl: Path
    output_root: Path
    phase2_payload_jsonl: Path | None = None
    use_llm_polish: bool = False
    api_base: str = "https://api.siliconflow.cn/v1"
    api_key: str | None = None
    api_key_env: str = "SILICONFLOW_API_KEY"
    llm_model: str = "Qwen/Qwen3-8B"
    timeout_seconds: float = 120.0
    max_key_moments: int = 12


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


def _format_ts(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{ms:03}"


def _truncate_text(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _build_audio_timeline(segments: list[dict[str, Any]], max_points: int = 16) -> str:
    if not segments:
        return ""

    points = max(1, min(max_points, len(segments)))
    lines: list[str] = []
    for i in range(points):
        idx = int(i * len(segments) / points)
        seg = segments[min(idx, len(segments) - 1)]
        text = str(seg.get("text", "")).strip().replace("\n", " ")
        lines.append(f"- {_format_ts(float(seg.get('start', 0.0)))}: {_truncate_text(text, 100)}")
    return "\n".join(lines)


def _build_transcript_excerpt(segments: list[dict[str, Any]], max_chars: int = 10000) -> str:
    lines: list[str] = []
    for seg in segments:
        start = _format_ts(float(seg.get("start", 0.0)))
        end = _format_ts(float(seg.get("end", 0.0)))
        text = str(seg.get("text", "")).strip().replace("\n", " ")
        lines.append(f"[{start}-{end}] {text}")
    return _truncate_text("\n".join(lines), max_chars)


def _llm_chat(
    api_base: str,
    api_key: str,
    model: str,
    timeout_seconds: float,
    system_prompt: str,
    user_prompt: str,
) -> str:
    endpoint = api_base.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    return str(content).strip()


def _build_audio_summary_markdown(
    transcript_meta: dict[str, Any],
    timeline: str,
    transcript_excerpt: str,
    polished_summary: str | None,
) -> str:
    language = transcript_meta.get("language", "unknown")
    duration_seconds = float(transcript_meta.get("duration", 0.0))
    lines = [
        "# 原始音频总结（优化版）",
        "",
        f"- 识别语言: {language}",
        f"- 时长: {duration_seconds:.1f}s",
        "",
    ]
    if polished_summary:
        lines += ["## 纠错与优化总结", "", polished_summary, ""]

    lines += ["## 时间线要点", "", timeline or "(无可用时间线数据)", ""]
    lines += ["## 转写摘录（供核对）", "", transcript_excerpt or "(无可用转写数据)", ""]
    return "\n".join(lines)


def _pick_key_moments(
    phase3_rows: list[dict[str, Any]],
    payload_rows_by_id: dict[int, dict[str, Any]],
    max_key_moments: int,
) -> list[dict[str, Any]]:
    ok_rows = [row for row in phase3_rows if row.get("status") == "ok"]
    if not ok_rows:
        ok_rows = phase3_rows
    if not ok_rows:
        return []

    count = max(1, min(max_key_moments, len(ok_rows)))
    picked: list[dict[str, Any]] = []
    for i in range(count):
        idx = int(i * len(ok_rows) / count)
        row = ok_rows[min(idx, len(ok_rows) - 1)]
        row_id = int(row.get("id", 0) or 0)
        payload = payload_rows_by_id.get(row_id, {})
        picked.append(
            {
                "id": row.get("id"),
                "capture_time": row.get("capture_time"),
                "capture_time_ts": row.get("capture_time_ts") or _format_ts(float(row.get("capture_time", 0.0))),
                "image_path": row.get("image_path"),
                "analysis": str(row.get("analysis", "")).strip(),
                "segment_text": str(payload.get("segment_text", "")).strip(),
                "context_text": str(payload.get("context_text", "")).strip(),
            }
        )
    return picked


def _build_key_moments_markdown(moments: list[dict[str, Any]], output_dir: Path) -> str:
    lines = [
        "# 关键时间戳总结（含截图索引）",
        "",
        "说明：优先保留原始单帧理解，同时附上可用于二次优化的文本上下文。",
        "",
    ]
    if not moments:
        lines.append("(无可用关键帧数据)")
        return "\n".join(lines)

    for moment in moments:
        image_path = Path(str(moment.get("image_path", "")))
        image_display = str(image_path)
        if image_path.exists():
            try:
                image_display = str(image_path.resolve().relative_to(output_dir.resolve()))
            except Exception:
                image_display = str(image_path)

        lines += [
            f"## [{moment.get('capture_time_ts', '')}] 片段 {moment.get('id', '')}",
            "",
            f"- 截图: `{image_display}`",
            f"- 单帧理解: {moment.get('analysis', '') or '(空)'}",
            f"- 对齐文本: {moment.get('segment_text', '') or '(空)'}",
            f"- 上下文窗口: {moment.get('context_text', '') or '(空)'}",
            "",
        ]

    return "\n".join(lines)


def _build_final_summary_prompt(
    audio_summary_markdown: str,
    key_moments_markdown: str,
) -> str:
    return (
        "请基于以下两部分信息，生成最终视频总结。\n"
        "输出要求：\n"
        "1) 主题与目标（2-4条）\n"
        "2) 核心内容分段总结（按时间线）\n"
        "3) 关键结论/行动项\n"
        "4) 不确定性与可能遗漏\n\n"
        "[原始音频总结]\n"
        f"{_truncate_text(audio_summary_markdown, 9000)}\n\n"
        "[关键时间戳总结]\n"
        f"{_truncate_text(key_moments_markdown, 9000)}"
    )


def _build_final_summary_fallback(
    audio_summary_markdown: str,
    moments: list[dict[str, Any]],
) -> str:
    lines = [
        "# 最终视频总结",
        "",
        "## 主题与目标",
        "- 基于音频转写与关键帧分析，形成视频主线理解。",
        "",
        "## 核心内容分段总结",
    ]
    if moments:
        for moment in moments:
            ts = moment.get("capture_time_ts", "")
            analysis = _truncate_text(str(moment.get("analysis", "")).replace("\n", " "), 160)
            lines.append(f"- {ts}: {analysis}")
    else:
        lines.append("- 暂无可用关键帧分析，当前仅可依赖音频转写。")

    lines += [
        "",
        "## 关键结论/行动项",
        "- 建议结合 `关键时间戳总结` 中的截图进行人工复核后再对外分发。",
        "",
        "## 不确定性与可能遗漏",
        "- 固定间隔采样可能遗漏短时高价值画面。",
        "- 单帧分析可能受转场、遮挡和画质影响。",
        "",
        "## 附：音频总结摘要",
        _truncate_text(audio_summary_markdown, 3000),
        "",
    ]
    return "\n".join(lines)


def run_phase4_summary(config: Phase4SummaryConfig) -> Path:
    phase = "phase4-summary"
    phase1_dir = config.phase1_dir.resolve()
    phase3_jsonl = config.phase3_jsonl.resolve()
    if not phase1_dir.exists():
        raise FileNotFoundError(f"phase1 dir not found: {phase1_dir}")
    if not phase3_jsonl.exists():
        raise FileNotFoundError(f"phase3 jsonl not found: {phase3_jsonl}")

    transcript_full_path = phase1_dir / "transcript.full.json"
    if not transcript_full_path.exists():
        raise FileNotFoundError(f"Missing transcript full json: {transcript_full_path}")

    transcript_full = _read_json(transcript_full_path)
    transcript_meta = transcript_full.get("meta", {})
    segments = list(transcript_full.get("segments", []))
    phase3_rows = _read_jsonl(phase3_jsonl)
    log_phase(phase, f"读取输入完成: transcript_segments={len(segments)}, phase3_items={len(phase3_rows)}")

    payload_rows_by_id: dict[int, dict[str, Any]] = {}
    if config.phase2_payload_jsonl and config.phase2_payload_jsonl.exists():
        payload_rows = _read_jsonl(config.phase2_payload_jsonl.resolve())
        for row in payload_rows:
            row_id = int(row.get("id", 0) or 0)
            payload_rows_by_id[row_id] = row

    output_dir = config.output_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    log_phase(phase, f"输出目录: {output_dir}")

    timeline = _build_audio_timeline(segments)
    transcript_excerpt = _build_transcript_excerpt(segments)

    api_key = config.api_key or os.getenv(config.api_key_env)
    llm_available = bool(config.use_llm_polish and api_key)
    if config.use_llm_polish and not api_key:
        log_phase(phase, f"未检测到 API Key ({config.api_key_env})，自动回退为无模型润色模式")

    polished_audio_summary: str | None = None
    audio_error: str | None = None
    if llm_available:
        audio_prompt = (
            "请基于以下转写内容生成中文总结。要求：\n"
            "1) 进行必要的文本纠错（口误、冗余口语）\n"
            "2) 保留核心观点，不捏造信息\n"
            "3) 输出结构化要点（5-10条）\n\n"
            "[转写摘录]\n"
            f"{transcript_excerpt}"
        )
        with timed_step(phase, "生成音频纠错总结 (LLM)"):
            try:
                polished_audio_summary = _llm_chat(
                    api_base=config.api_base,
                    api_key=str(api_key),
                    model=config.llm_model,
                    timeout_seconds=config.timeout_seconds,
                    system_prompt="You are a precise Chinese meeting/video summarizer.",
                    user_prompt=audio_prompt,
                )
            except Exception as exc:
                audio_error = str(exc)
                log_phase(phase, f"音频总结 LLM 失败: {audio_error}")

    audio_summary_md = _build_audio_summary_markdown(
        transcript_meta=transcript_meta,
        timeline=timeline,
        transcript_excerpt=transcript_excerpt,
        polished_summary=polished_audio_summary,
    )

    moments = _pick_key_moments(
        phase3_rows=phase3_rows,
        payload_rows_by_id=payload_rows_by_id,
        max_key_moments=config.max_key_moments,
    )
    key_moments_md = _build_key_moments_markdown(moments, output_dir)

    final_summary_md: str
    final_error: str | None = None
    if llm_available:
        with timed_step(phase, "生成最终视频总结 (LLM)"):
            try:
                final_summary_md = _llm_chat(
                    api_base=config.api_base,
                    api_key=str(api_key),
                    model=config.llm_model,
                    timeout_seconds=config.timeout_seconds,
                    system_prompt="You are a rigorous Chinese video summarization assistant.",
                    user_prompt=_build_final_summary_prompt(audio_summary_md, key_moments_md),
                )
                if not final_summary_md.startswith("#"):
                    final_summary_md = "# 最终视频总结\n\n" + final_summary_md
            except Exception as exc:
                final_error = str(exc)
                log_phase(phase, f"最终总结 LLM 失败，回退 fallback: {final_error}")
                final_summary_md = _build_final_summary_fallback(audio_summary_md, moments)
    else:
        final_summary_md = _build_final_summary_fallback(audio_summary_md, moments)

    audio_summary_path = output_dir / "audio_summary_optimized.md"
    key_moments_path = output_dir / "key_moments_summary.md"
    final_summary_path = output_dir / "final_video_summary.md"
    manifest_path = output_dir / "phase4_summary_manifest.json"

    audio_summary_path.write_text(audio_summary_md, encoding="utf-8")
    key_moments_path.write_text(key_moments_md, encoding="utf-8")
    final_summary_path.write_text(final_summary_md, encoding="utf-8")
    log_phase(phase, f"产物写入完成: {audio_summary_path.name}, {key_moments_path.name}, {final_summary_path.name}")

    manifest = {
        "stage": "phase4_summary",
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "phase1_dir": str(phase1_dir),
            "phase3_jsonl": str(phase3_jsonl),
            "phase2_payload_jsonl": str(config.phase2_payload_jsonl) if config.phase2_payload_jsonl else None,
        },
        "request": {
            "use_llm_polish": config.use_llm_polish,
            "api_base": config.api_base,
            "llm_model": config.llm_model,
            "api_key_env": config.api_key_env,
            "timeout_seconds": config.timeout_seconds,
            "max_key_moments": config.max_key_moments,
        },
        "outputs": {
            "audio_summary_optimized": str(audio_summary_path),
            "key_moments_summary": str(key_moments_path),
            "final_video_summary": str(final_summary_path),
        },
        "stats": {
            "transcript_segments": len(segments),
            "phase3_items": len(phase3_rows),
            "key_moments": len(moments),
        },
        "llm": {
            "available": llm_available,
            "audio_summary_error": audio_error,
            "final_summary_error": final_error,
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log_phase(phase, f"阶段完成，manifest: {manifest_path}")

    return output_dir
