from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from videosummary.logging_utils import log_phase, timed_step


VISUAL_CUE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"如图|见图|如下图|看图|图上|图里|图中",
        r"表格|如下表|见表|表中",
        r"看这个|这里|这一页|这个页面|这一段",
        r"代码|函数|报错|终端|控制台",
        r"曲线|柱状|折线|饼图|坐标轴|趋势",
        r"screenshot|figure|diagram|chart|graph|as shown",
        r"this page|this slide|as you can see|on screen",
    ]
]

STRUCTURE_CUE_PATTERN = re.compile(
    r"第一部分|第二部分|第三部分|接下来|本部分|总结|结果分析|实验结果|对比|overview|next|summary",
    re.IGNORECASE,
)

NUMBER_DENSE_PATTERN = re.compile(r"\d+(?:\.\d+)?")
AMBIGUOUS_PRONOUN_PATTERN = re.compile(r"这个|那个|这里|那边|it|this|that", re.IGNORECASE)


@dataclass
class RouterConfig:
    transcript_jsonl: Path
    output_root: Path
    top_k: int = 18
    min_score: float = 2.0
    merge_gap_seconds: float = 8.0
    context_window: int = 1
    min_plan_items: int = 8


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            segments.append(json.loads(line))
    return segments


def _score_segment(text: str) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    cue_hits = 0
    for pattern in VISUAL_CUE_PATTERNS:
        if pattern.search(text):
            cue_hits += 1

    if cue_hits > 0:
        visual_score = min(4.0, cue_hits * 1.5)
        score += visual_score
        reasons.append(f"visual_cues={cue_hits}")

    number_hits = len(NUMBER_DENSE_PATTERN.findall(text))
    if number_hits >= 3:
        score += 1.0
        reasons.append(f"number_dense={number_hits}")

    if AMBIGUOUS_PRONOUN_PATTERN.search(text):
        score += 0.5
        reasons.append("ambiguous_reference")

    if STRUCTURE_CUE_PATTERN.search(text):
        score += 0.8
        reasons.append("structure_cue")

    text_len = len(text.strip())
    if 10 <= text_len <= 45:
        score += 0.4
        reasons.append("concise_explanation")

    return round(score, 2), reasons


def _build_intent(text: str, reasons: list[str]) -> str:
    if ("代码" in text) or re.search(r"code|函数|报错|终端", text, re.IGNORECASE):
        return "Capture code/terminal state and explain missing technical details."
    if re.search(r"图|表|chart|graph|diagram|trend", text, re.IGNORECASE):
        return "Capture chart/table and extract concrete numbers or structure."
    if "ambiguous_reference" in reasons:
        return "Capture visual context to resolve ambiguous references in speech."
    return "Capture frame for visual grounding and potential missing context."


def _format_ts(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{ms:03}"


def _neighbor_text(segments: list[dict[str, Any]], index: int, window: int) -> str:
    left = max(0, index - window)
    right = min(len(segments), index + window + 1)
    samples: list[str] = []
    for i in range(left, right):
        segment = segments[i]
        samples.append(
            f"[{_format_ts(float(segment['start']))}-{_format_ts(float(segment['end']))}] {segment['text'].strip()}"
        )
    return "\n".join(samples)


def _merge_candidates(candidates: list[dict[str, Any]], merge_gap_seconds: float) -> list[dict[str, Any]]:
    if not candidates:
        return []

    merged: list[dict[str, Any]] = []
    current = candidates[0].copy()

    for candidate in candidates[1:]:
        if float(candidate["start"]) - float(current["end"]) <= merge_gap_seconds:
            current["end"] = max(float(current["end"]), float(candidate["end"]))
            current["score"] = max(float(current["score"]), float(candidate["score"]))
            current["reasons"] = sorted(
                set(list(current["reasons"]) + list(candidate["reasons"]))
            )
            current["text"] = f"{current['text']} / {candidate['text']}"
        else:
            merged.append(current)
            current = candidate.copy()

    merged.append(current)
    return merged


def _backfill_evenly(
    scored: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    min_plan_items: int,
) -> list[dict[str, Any]]:
    if len(selected) >= min_plan_items or not scored:
        return selected

    selected_ids = {int(x["index"]) for x in selected}
    needed = max(0, min_plan_items - len(selected))
    candidate_count = len(scored)
    if needed == 0:
        return selected

    # Evenly sample timeline bins, then pick top score inside each bin.
    for i in range(needed):
        left = int(i * candidate_count / needed)
        right = int((i + 1) * candidate_count / needed)
        bucket = scored[left:right] if right > left else scored[left : left + 1]
        ranked_bucket = sorted(bucket, key=lambda x: (-float(x["score"]), float(x["start"])))
        pick = None
        for row in ranked_bucket:
            idx = int(row["index"])
            if idx not in selected_ids:
                pick = row
                break
        if pick is not None:
            selected.append(pick)
            selected_ids.add(int(pick["index"]))

    return sorted(selected, key=lambda x: float(x["start"]))


def run_router(config: RouterConfig) -> Path:
    phase = "phase2-router"
    if not config.transcript_jsonl.exists():
        raise FileNotFoundError(f"Transcript JSONL not found: {config.transcript_jsonl}")

    with timed_step(phase, "读取 transcript"):
        segments = _read_jsonl(config.transcript_jsonl)
    log_phase(phase, f"片段总数: {len(segments)}")
    scored: list[dict[str, Any]] = []

    with timed_step(phase, "规则打分与候选筛选"):
        for idx, segment in enumerate(segments):
            text = str(segment.get("text", "")).strip()
            score, reasons = _score_segment(text)
            scored.append(
                {
                    "id": segment.get("id", idx),
                    "index": idx,
                    "start": float(segment["start"]),
                    "end": float(segment["end"]),
                    "text": text,
                    "score": score,
                    "reasons": reasons,
                }
            )

        high_value = [x for x in scored if x["score"] >= config.min_score]
        ranked = sorted(high_value, key=lambda x: (-float(x["score"]), float(x["start"])))
        top_ranked = ranked[: config.top_k]
        merged = _merge_candidates(
            sorted(top_ranked, key=lambda x: float(x["start"])),
            merge_gap_seconds=config.merge_gap_seconds,
        )
        merged = _backfill_evenly(
            scored=sorted(scored, key=lambda x: float(x["start"])),
            selected=merged,
            min_plan_items=config.min_plan_items,
        )
    log_phase(phase, f"阈值命中={len(high_value)}，最终计划项={len(merged)}")

    phase2_dir = config.output_root
    phase2_dir.mkdir(parents=True, exist_ok=True)

    scored_path = phase2_dir / "router.scored_segments.jsonl"
    plan_path = phase2_dir / "keyframe_plan.json"
    notes_path = phase2_dir / "keyframe_plan.md"
    manifest_path = phase2_dir / "phase2_router_manifest.json"

    with scored_path.open("w", encoding="utf-8") as f:
        for row in scored:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    plan_items: list[dict[str, Any]] = []
    for i, item in enumerate(merged, start=1):
        center = round((float(item["start"]) + float(item["end"])) / 2.0, 3)
        context = _neighbor_text(segments, int(item["index"]), config.context_window)
        plan_items.append(
            {
                "id": i,
                "capture_time": center,
                "capture_time_ts": _format_ts(center),
                "window_start": float(item["start"]),
                "window_end": float(item["end"]),
                "score": float(item["score"]),
                "reasons": item["reasons"],
                "query_intent": _build_intent(str(item["text"]), list(item["reasons"])),
                "source_text": item["text"],
                "context": context,
                "selection_type": "rule" if float(item["score"]) >= config.min_score else "fallback",
            }
        )

    plan_payload = {
        "meta": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "transcript_jsonl": str(config.transcript_jsonl),
            "selection": {
                "top_k": config.top_k,
                "min_score": config.min_score,
                "merge_gap_seconds": config.merge_gap_seconds,
                "context_window": config.context_window,
                "min_plan_items": config.min_plan_items,
            },
        },
        "items": plan_items,
    }
    plan_path.write_text(json.dumps(plan_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Keyframe Plan", "", "由 transcript 路由生成的关键截图建议。", ""]
    for item in plan_items:
        lines.append(f"## {item['id']}. {item['capture_time_ts']} (score={item['score']})")
        lines.append(f"- window: {_format_ts(item['window_start'])} - {_format_ts(item['window_end'])}")
        lines.append(f"- reasons: {', '.join(item['reasons']) if item['reasons'] else 'none'}")
        lines.append(f"- intent: {item['query_intent']}")
        lines.append(f"- source: {item['source_text']}")
        lines.append("")
    notes_path.write_text("\n".join(lines), encoding="utf-8")

    manifest_payload = {
        "stage": "phase2_router",
        "status": "completed",
        "input": str(config.transcript_jsonl),
        "outputs": {
            "scored_segments": str(scored_path),
            "keyframe_plan_json": str(plan_path),
            "keyframe_plan_markdown": str(notes_path),
        },
        "stats": {
            "segments_total": len(scored),
            "segments_over_threshold": len(high_value),
            "selected_after_merge": len(plan_items),
            "fallback_selected": sum(1 for x in plan_items if x["selection_type"] == "fallback"),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log_phase(phase, f"阶段完成，manifest: {manifest_path}")

    return phase2_dir
