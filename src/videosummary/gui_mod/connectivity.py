from __future__ import annotations

import json
import urllib.error
import urllib.request

"""HTTP probes for GUI connection test buttons."""


def _json_get(url: str, headers: dict[str, str], timeout: float) -> dict[str, object]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read().decode("utf-8", errors="replace")
    return json.loads(content) if content else {}


def _json_post(url: str, payload: dict[str, object], headers: dict[str, str], timeout: float) -> dict[str, object]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read().decode("utf-8", errors="replace")
    return json.loads(content) if content else {}


def run_connection_probe(
    *,
    channel: str,
    api_base: str,
    model: str,
    timeout_seconds: float,
    api_key: str,
    send_auth_header: bool,
) -> list[str]:
    # Probe in two steps: model listing then a minimal chat request.
    logs: list[str] = []
    headers = {"Content-Type": "application/json"}
    if send_auth_header:
        if not api_key:
            return [f"{channel.upper()} 连接测试失败: 需要鉴权但未提供 API Key"]
        headers["Authorization"] = f"Bearer {api_key}"

    base = api_base.rstrip("/")
    models_url = base + "/models"
    chat_url = base + "/chat/completions"

    try:
        models_data = _json_get(models_url, headers=headers, timeout=timeout_seconds)
        model_ids: list[str] = []
        for row in models_data.get("data", []) if isinstance(models_data, dict) else []:
            model_id = str((row or {}).get("id", "")).strip()
            if model_id:
                model_ids.append(model_id)
        sample = ", ".join(model_ids[:5]) if model_ids else "(空)"
        logs.append(f"{channel.upper()} /v1/models 成功，可用模型示例: {sample}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return [f"{channel.upper()} /v1/models 失败: HTTP {exc.code} {body[:220]}"]
    except Exception as exc:
        return [f"{channel.upper()} /v1/models 失败: {exc}"]

    try:
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "You are a connectivity test assistant."},
                {"role": "user", "content": "Reply with OK only."},
            ],
        }
        result = _json_post(chat_url, payload=payload, headers=headers, timeout=timeout_seconds)
        choices = result.get("choices", []) if isinstance(result, dict) else []
        preview = ""
        if choices:
            message = (choices[0] or {}).get("message", {})
            preview = str(message.get("content", "")).strip().replace("\n", " ")[:80]
        logs.append(f"{channel.upper()} 最小 chat 请求成功，返回片段: {preview or '(空返回但请求成功)'}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        logs.append(f"{channel.upper()} 最小 chat 请求失败: HTTP {exc.code} {body[:260]}")
    except Exception as exc:
        logs.append(f"{channel.upper()} 最小 chat 请求失败: {exc}")
    return logs
