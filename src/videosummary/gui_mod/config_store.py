from __future__ import annotations

import json
from pathlib import Path
from typing import Any

"""Persistence and provider-default helpers for GUI configuration."""

PROVIDER_DEFAULT_BASE = {
    "siliconflow": "https://api.siliconflow.cn/v1",
    "openai": "https://api.openai.com/v1",
    "lmstudio": "http://127.0.0.1:1234/v1",
}


def load_settings(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    # Keep loading resilient: broken JSON should not block GUI startup.
    if not path.exists():
        return {}, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}

    last_config = payload.get("last_config") if isinstance(payload.get("last_config"), dict) else {}
    custom_raw = payload.get("custom_presets")
    custom: dict[str, dict[str, Any]] = {}
    if isinstance(custom_raw, dict):
        for name, preset in custom_raw.items():
            if isinstance(preset, dict):
                custom[str(name)] = preset
    return last_config, custom


def save_settings(path: Path, last_config: dict[str, Any], custom_presets: dict[str, dict[str, Any]]) -> None:
    # Persist only non-sensitive GUI state; runtime API keys are excluded.
    payload = {
        "version": 1,
        "last_config": last_config,
        "custom_presets": custom_presets,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_base_for_provider(provider: str) -> str:
    return PROVIDER_DEFAULT_BASE.get(provider.strip(), "")


def sync_base_url(provider: str, current_base: str, *, force: bool) -> str:
    # Auto-fill provider defaults, while preserving custom endpoints unless forced.
    default_base = default_base_for_provider(provider)
    if not default_base:
        return current_base
    known = set(PROVIDER_DEFAULT_BASE.values())
    current = current_base.strip()
    if force or (not current) or (current in known):
        return default_base
    return current_base
