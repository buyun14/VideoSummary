from __future__ import annotations

from pathlib import Path
from typing import Any

"""Reusable path and runtime-env builders for GUI command execution."""


def pipeline_paths(input_path: str, output_path: str) -> dict[str, Path]:
    # Keep phase output layout deterministic so users can resume per stage.
    if not input_path.strip():
        raise ValueError("请先选择输入视频")
    input_video = Path(input_path)
    if not input_video.exists():
        raise ValueError(f"输入文件不存在: {input_path}")

    output_root = Path(output_path.strip() or "outputs")
    video_stem = input_video.stem
    phase1_dir = output_root / video_stem / "phase1"
    phase2_dir = output_root / video_stem / "phase2_fixed"
    phase3_dir = phase2_dir / "phase3_vlm"
    phase4_dir = phase3_dir / "phase4_summary"
    return {
        "input": input_video,
        "phase1_dir": phase1_dir,
        "phase2_dir": phase2_dir,
        "phase3_dir": phase3_dir,
        "phase4_dir": phase4_dir,
        "phase2_payload_jsonl": phase2_dir / "vlm_payload.jsonl",
        "phase3_jsonl": phase3_dir / "visual_analysis.jsonl",
    }


def runtime_api_key_env(config: dict[str, Any]) -> dict[str, str]:
    env: dict[str, str] = {}
    vlm_key = str(config.get("vlm_api_key", "")).strip()
    llm_key = str(config.get("llm_api_key", "")).strip()
    vlm_env = str(config.get("vlm_api_key_env", "SILICONFLOW_API_KEY")).strip() or "SILICONFLOW_API_KEY"
    llm_env = str(config.get("llm_api_key_env", "SILICONFLOW_API_KEY")).strip() or "SILICONFLOW_API_KEY"
    if vlm_key:
        env[vlm_env] = vlm_key
    if llm_key:
        env[llm_env] = llm_key
    return env
