from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk


class VideoSummaryPanel:
    BUILTIN_PRESETS = ["default", "game", "speech"]
    PROVIDER_DEFAULT_BASE = {
        "siliconflow": "https://api.siliconflow.cn/v1",
        "openai": "https://api.openai.com/v1",
        "lmstudio": "http://127.0.0.1:1234/v1",
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("VideoSummary 控制面板")
        self.root.geometry("1080x760")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.custom_presets: dict[str, dict[str, object]] = {}

        self.input_var = tk.StringVar(value="")
        self.output_var = tk.StringVar(value="outputs")
        self.preset_var = tk.StringVar(value="default")
        self.asr_model_var = tk.StringVar(value="small")
        self.asr_model_path_var = tk.StringVar(value="")
        self.hf_endpoint_var = tk.StringVar(value="https://hf-mirror.com")
        self.http_proxy_var = tk.StringVar(value="")
        self.https_proxy_var = tk.StringVar(value="")
        self.hf_home_var = tk.StringVar(value="")
        self.offline_var = tk.BooleanVar(value=False)
        self.vlm_model_var = tk.StringVar(value="deepseek-ai/DeepSeek-OCR")
        self.vlm_provider_var = tk.StringVar(value="siliconflow")
        self.vlm_api_base_var = tk.StringVar(value="https://api.siliconflow.cn/v1")
        self.vlm_api_key_var = tk.StringVar(value="")
        self.vlm_api_key_env_var = tk.StringVar(value="SILICONFLOW_API_KEY")
        self.vlm_no_auth_var = tk.BooleanVar(value=False)
        self.llm_model_var = tk.StringVar(value="Qwen/Qwen3-8B")
        self.llm_provider_var = tk.StringVar(value="siliconflow")
        self.llm_api_base_var = tk.StringVar(value="https://api.siliconflow.cn/v1")
        self.llm_api_key_var = tk.StringVar(value="")
        self.llm_api_key_env_var = tk.StringVar(value="SILICONFLOW_API_KEY")
        self.llm_no_auth_var = tk.BooleanVar(value=False)
        self.interval_var = tk.StringVar(value="30")
        self.context_window_var = tk.StringVar(value="1")
        self.timeout_var = tk.StringVar(value="120")
        self.concurrency_var = tk.StringVar(value="3")
        self.retry_var = tk.StringVar(value="1")
        self.use_llm_polish_var = tk.BooleanVar(value=True)
        self.with_audio_summary_var = tk.BooleanVar(value=True)

        self._load_settings()
        self._build_form()
        self._sync_channel_base_url("vlm", force=False)
        self._sync_channel_base_url("llm", force=False)
        self._build_log_view()
        self._refresh_preset_values()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(200, self._drain_log_queue)

    @property
    def _project_root(self) -> Path:
        # gui.py -> videosummary/ -> src/ -> project root
        return Path(__file__).resolve().parents[2]

    @property
    def _settings_path(self) -> Path:
        return self._project_root / ".videosummary_gui.json"

    @property
    def _builtin_presets(self) -> list[str]:
        return list(self.BUILTIN_PRESETS)

    def _collect_state(self) -> dict[str, object]:
        return {
            "input": self.input_var.get().strip(),
            "output": self.output_var.get().strip() or "outputs",
            "preset": self.preset_var.get().strip() or "default",
            "asr_model": self.asr_model_var.get().strip() or "small",
            "asr_model_path": self.asr_model_path_var.get().strip(),
            "hf_endpoint": self.hf_endpoint_var.get().strip() or "https://hf-mirror.com",
            "http_proxy": self.http_proxy_var.get().strip(),
            "https_proxy": self.https_proxy_var.get().strip(),
            "hf_home": self.hf_home_var.get().strip(),
            "offline": bool(self.offline_var.get()),
            "vlm_model": self.vlm_model_var.get().strip() or "deepseek-ai/DeepSeek-OCR",
            "llm_model": self.llm_model_var.get().strip() or "Qwen/Qwen3-8B",
            "vlm_provider": self.vlm_provider_var.get().strip() or "siliconflow",
            "vlm_api_base": self.vlm_api_base_var.get().strip() or "https://api.siliconflow.cn/v1",
            "vlm_api_key_env": self.vlm_api_key_env_var.get().strip() or "SILICONFLOW_API_KEY",
            "vlm_no_auth": bool(self.vlm_no_auth_var.get()),
            "llm_provider": self.llm_provider_var.get().strip() or "siliconflow",
            "llm_api_base": self.llm_api_base_var.get().strip() or "https://api.siliconflow.cn/v1",
            "llm_api_key_env": self.llm_api_key_env_var.get().strip() or "SILICONFLOW_API_KEY",
            "llm_no_auth": bool(self.llm_no_auth_var.get()),
            "interval_seconds": self.interval_var.get().strip() or "30",
            "context_window": self.context_window_var.get().strip() or "1",
            "timeout_seconds": self.timeout_var.get().strip() or "120",
            "concurrency": self.concurrency_var.get().strip() or "3",
            "max_retries": self.retry_var.get().strip() or "1",
            "use_llm_polish": bool(self.use_llm_polish_var.get()),
            "with_audio_summary": bool(self.with_audio_summary_var.get()),
        }

    def _apply_state(self, state: dict[str, object], *, include_input_output: bool = True) -> None:
        if include_input_output:
            self.input_var.set(str(state.get("input", self.input_var.get())))
            self.output_var.set(str(state.get("output", self.output_var.get())))

        self.preset_var.set(str(state.get("preset", self.preset_var.get())))
        self.asr_model_var.set(str(state.get("asr_model", self.asr_model_var.get())))
        self.asr_model_path_var.set(str(state.get("asr_model_path", self.asr_model_path_var.get())))
        self.hf_endpoint_var.set(str(state.get("hf_endpoint", self.hf_endpoint_var.get())))
        self.http_proxy_var.set(str(state.get("http_proxy", self.http_proxy_var.get())))
        self.https_proxy_var.set(str(state.get("https_proxy", self.https_proxy_var.get())))
        self.hf_home_var.set(str(state.get("hf_home", self.hf_home_var.get())))
        self.offline_var.set(bool(state.get("offline", self.offline_var.get())))
        self.vlm_model_var.set(str(state.get("vlm_model", self.vlm_model_var.get())))
        self.llm_model_var.set(str(state.get("llm_model", self.llm_model_var.get())))
        self.vlm_provider_var.set(str(state.get("vlm_provider", self.vlm_provider_var.get())))
        self.vlm_api_base_var.set(str(state.get("vlm_api_base", self.vlm_api_base_var.get())))
        self.vlm_api_key_env_var.set(str(state.get("vlm_api_key_env", self.vlm_api_key_env_var.get())))
        self.vlm_no_auth_var.set(bool(state.get("vlm_no_auth", self.vlm_no_auth_var.get())))
        self.llm_provider_var.set(str(state.get("llm_provider", self.llm_provider_var.get())))
        self.llm_api_base_var.set(str(state.get("llm_api_base", self.llm_api_base_var.get())))
        self.llm_api_key_env_var.set(str(state.get("llm_api_key_env", self.llm_api_key_env_var.get())))
        self.llm_no_auth_var.set(bool(state.get("llm_no_auth", self.llm_no_auth_var.get())))
        self._sync_channel_base_url("vlm", force=False)
        self._sync_channel_base_url("llm", force=False)
        self.interval_var.set(str(state.get("interval_seconds", self.interval_var.get())))
        self.context_window_var.set(str(state.get("context_window", self.context_window_var.get())))
        self.timeout_var.set(str(state.get("timeout_seconds", self.timeout_var.get())))
        self.concurrency_var.set(str(state.get("concurrency", self.concurrency_var.get())))
        self.retry_var.set(str(state.get("max_retries", self.retry_var.get())))
        self.use_llm_polish_var.set(bool(state.get("use_llm_polish", self.use_llm_polish_var.get())))
        self.with_audio_summary_var.set(bool(state.get("with_audio_summary", self.with_audio_summary_var.get())))

    def _load_settings(self) -> None:
        path = self._settings_path
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return

        custom = payload.get("custom_presets")
        if isinstance(custom, dict):
            self.custom_presets = {
                str(name): preset
                for name, preset in custom.items()
                if isinstance(preset, dict)
            }
        last = payload.get("last_config")
        if isinstance(last, dict):
            self._apply_state(last, include_input_output=True)

    def _save_settings(self) -> None:
        path = self._settings_path
        payload = {
            "version": 1,
            "last_config": self._collect_state(),
            "custom_presets": self.custom_presets,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _on_close(self) -> None:
        try:
            self._save_settings()
        except Exception as exc:
            self._append_log(f"保存配置失败: {exc}")
        self.root.destroy()

    def _select_python(self) -> str:
        venv_python = self._project_root / ".venv" / "Scripts" / "python.exe"
        if venv_python.exists():
            return str(venv_python)
        return sys.executable

    def _build_form(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill=tk.X)

        row = 0
        ttk.Label(frame, text="输入视频").grid(row=row, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.input_var, width=92).grid(row=row, column=1, sticky=tk.W)
        ttk.Button(frame, text="浏览", command=self._pick_input).grid(row=row, column=2, padx=8)

        row += 1
        ttk.Label(frame, text="输出目录").grid(row=row, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.output_var, width=92).grid(row=row, column=1, sticky=tk.W)
        ttk.Button(frame, text="浏览", command=self._pick_output).grid(row=row, column=2, padx=8)

        row += 1
        ttk.Label(frame, text="预设").grid(row=row, column=0, sticky=tk.W)
        self.preset_combo = ttk.Combobox(frame, textvariable=self.preset_var, values=self._builtin_presets, width=18)
        self.preset_combo.grid(row=row, column=1, sticky=tk.W)
        ttk.Button(frame, text="载入预设", command=self._load_selected_preset).grid(row=row, column=1, sticky=tk.W, padx=(170, 0))
        ttk.Button(frame, text="另存预设", command=self._save_as_preset).grid(row=row, column=1, sticky=tk.W, padx=(255, 0))
        ttk.Button(frame, text="删除预设", command=self._delete_selected_preset).grid(row=row, column=1, sticky=tk.W, padx=(340, 0))

        row += 1
        ttk.Label(frame, text="ASR 模型").grid(row=row, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.asr_model_var, width=20).grid(row=row, column=1, sticky=tk.W)
        ttk.Label(frame, text="VLM 模型").grid(row=row, column=1, sticky=tk.E, padx=(0, 260))
        ttk.Entry(frame, textvariable=self.vlm_model_var, width=34).grid(row=row, column=1, sticky=tk.E)

        row += 1
        ttk.Label(frame, text="ASR 本地模型目录").grid(row=row, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.asr_model_path_var, width=92).grid(row=row, column=1, sticky=tk.W)
        ttk.Button(frame, text="浏览", command=self._pick_model_dir).grid(row=row, column=2, padx=8)

        row += 1
        ttk.Label(frame, text="HF 镜像地址").grid(row=row, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.hf_endpoint_var, width=30).grid(row=row, column=1, sticky=tk.W)
        ttk.Label(frame, text="HTTP 代理").grid(row=row, column=1, sticky=tk.E, padx=(0, 260))
        ttk.Entry(frame, textvariable=self.http_proxy_var, width=34).grid(row=row, column=1, sticky=tk.E)

        row += 1
        ttk.Label(frame, text="HTTPS 代理").grid(row=row, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.https_proxy_var, width=30).grid(row=row, column=1, sticky=tk.W)
        ttk.Label(frame, text="HF 缓存目录").grid(row=row, column=1, sticky=tk.E, padx=(0, 260))
        ttk.Entry(frame, textvariable=self.hf_home_var, width=34).grid(row=row, column=1, sticky=tk.E)

        row += 1
        ttk.Checkbutton(frame, text="ASR 离线模式", variable=self.offline_var).grid(row=row, column=1, sticky=tk.W)

        row += 1
        ttk.Label(frame, text="VLM 提供商").grid(row=row, column=0, sticky=tk.W)
        self.vlm_provider_combo = ttk.Combobox(
            frame,
            textvariable=self.vlm_provider_var,
            values=["siliconflow", "openai", "lmstudio", "custom"],
            width=18,
        )
        self.vlm_provider_combo.grid(row=row, column=1, sticky=tk.W)
        self.vlm_provider_combo.bind("<<ComboboxSelected>>", self._on_vlm_provider_changed)
        ttk.Checkbutton(frame, text="VLM 禁用鉴权头(no-auth)", variable=self.vlm_no_auth_var).grid(row=row, column=1, sticky=tk.E)

        row += 1
        ttk.Label(frame, text="VLM API Base").grid(row=row, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.vlm_api_base_var, width=30).grid(row=row, column=1, sticky=tk.W)
        ttk.Button(frame, text="测试 VLM 连接", command=self._test_vlm_connection).grid(row=row, column=2, padx=8)
        ttk.Label(frame, text="VLM API Key Env").grid(row=row, column=1, sticky=tk.E, padx=(0, 260))
        ttk.Entry(frame, textvariable=self.vlm_api_key_env_var, width=34).grid(row=row, column=1, sticky=tk.E)

        row += 1
        ttk.Label(frame, text="VLM API Key(可选)").grid(row=row, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.vlm_api_key_var, width=30, show="*").grid(row=row, column=1, sticky=tk.W)
        ttk.Label(frame, text="LLM 提供商").grid(row=row, column=1, sticky=tk.E, padx=(0, 260))
        self.llm_provider_combo = ttk.Combobox(
            frame,
            textvariable=self.llm_provider_var,
            values=["siliconflow", "openai", "lmstudio", "custom"],
            width=18,
        )
        self.llm_provider_combo.grid(row=row, column=1, sticky=tk.E)
        self.llm_provider_combo.bind("<<ComboboxSelected>>", self._on_llm_provider_changed)

        row += 1
        ttk.Label(frame, text="LLM 模型").grid(row=row, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.llm_model_var, width=20).grid(row=row, column=1, sticky=tk.W)
        ttk.Label(frame, text="截帧间隔(s)").grid(row=row, column=1, sticky=tk.E, padx=(0, 260))
        ttk.Entry(frame, textvariable=self.interval_var, width=8).grid(row=row, column=1, sticky=tk.E)

        row += 1
        ttk.Label(frame, text="LLM API Base").grid(row=row, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.llm_api_base_var, width=30).grid(row=row, column=1, sticky=tk.W)
        ttk.Button(frame, text="测试 LLM 连接", command=self._test_llm_connection).grid(row=row, column=2, padx=8)
        ttk.Label(frame, text="LLM API Key Env").grid(row=row, column=1, sticky=tk.E, padx=(0, 260))
        ttk.Entry(frame, textvariable=self.llm_api_key_env_var, width=34).grid(row=row, column=1, sticky=tk.E)

        row += 1
        ttk.Label(frame, text="LLM API Key(可选)").grid(row=row, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.llm_api_key_var, width=30, show="*").grid(row=row, column=1, sticky=tk.W)
        ttk.Checkbutton(frame, text="LLM 禁用鉴权头(no-auth)", variable=self.llm_no_auth_var).grid(row=row, column=1, sticky=tk.E)

        row += 1
        ttk.Label(frame, text="上下文窗口").grid(row=row, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.context_window_var, width=8).grid(row=row, column=1, sticky=tk.W)
        ttk.Label(frame, text="API 超时(s)").grid(row=row, column=1, sticky=tk.E, padx=(0, 260))
        ttk.Entry(frame, textvariable=self.timeout_var, width=8).grid(row=row, column=1, sticky=tk.E)

        row += 1
        ttk.Label(frame, text="并发请求数").grid(row=row, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.concurrency_var, width=8).grid(row=row, column=1, sticky=tk.W)
        ttk.Label(frame, text="重试次数").grid(row=row, column=1, sticky=tk.E, padx=(0, 260))
        ttk.Entry(frame, textvariable=self.retry_var, width=8).grid(row=row, column=1, sticky=tk.E)

        row += 1
        ttk.Checkbutton(frame, text="附加音频摘要", variable=self.with_audio_summary_var).grid(row=row, column=1, sticky=tk.E, padx=(0, 165))
        ttk.Checkbutton(frame, text="启用 LLM 优化", variable=self.use_llm_polish_var).grid(row=row, column=1, sticky=tk.E)

        row += 1
        btn_row = ttk.Frame(frame)
        btn_row.grid(row=row, column=0, columnspan=3, pady=(10, 0), sticky=tk.W)
        ttk.Button(btn_row, text="运行全流程", command=self._run_all).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="仅 Phase1", command=self._run_phase1).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_row, text="仅 Phase2", command=self._run_phase2).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="仅 Phase3", command=self._run_phase3).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_row, text="仅 Phase4", command=self._run_phase4).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="停止", command=self._stop).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_row, text="保存当前配置", command=self._save_current_config).pack(side=tk.LEFT)

    def _build_log_view(self) -> None:
        frame = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(frame, wrap=tk.WORD, height=28)
        self.log_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        scrollbar = ttk.Scrollbar(frame, command=self.log_text.yview)
        scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.log_text.config(yscrollcommand=scrollbar.set)

    def _pick_input(self) -> None:
        path = filedialog.askopenfilename(title="选择视频文件")
        if path:
            self.input_var.set(path)

    def _pick_output(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_var.set(path)

    def _pick_model_dir(self) -> None:
        path = filedialog.askdirectory(title="选择 Whisper 本地模型目录")
        if path:
            self.asr_model_path_var.set(path)

    def _append_log(self, line: str) -> None:
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)

    def _drain_log_queue(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)
        self.root.after(200, self._drain_log_queue)

    def _provider_default_base(self, provider: str) -> str:
        return self.PROVIDER_DEFAULT_BASE.get(provider.strip(), "")

    def _known_default_bases(self) -> set[str]:
        return set(self.PROVIDER_DEFAULT_BASE.values())

    def _sync_channel_base_url(self, channel: str, *, force: bool) -> None:
        if channel == "vlm":
            provider = self.vlm_provider_var.get().strip() or "siliconflow"
            base_var = self.vlm_api_base_var
        else:
            provider = self.llm_provider_var.get().strip() or "siliconflow"
            base_var = self.llm_api_base_var

        default_base = self._provider_default_base(provider)
        if not default_base:
            return

        current = base_var.get().strip()
        if force or (not current) or (current in self._known_default_bases()):
            base_var.set(default_base)

    def _on_vlm_provider_changed(self, _event: object | None = None) -> None:
        self._sync_channel_base_url("vlm", force=True)

    def _on_llm_provider_changed(self, _event: object | None = None) -> None:
        self._sync_channel_base_url("llm", force=True)

    def _resolve_channel_runtime_key(self, channel: str) -> tuple[str, str, bool, str, str]:
        if channel == "vlm":
            provider = self.vlm_provider_var.get().strip() or "siliconflow"
            api_base = self.vlm_api_base_var.get().strip() or self._provider_default_base(provider)
            api_key_env = self.vlm_api_key_env_var.get().strip() or "SILICONFLOW_API_KEY"
            no_auth = bool(self.vlm_no_auth_var.get())
            model = self.vlm_model_var.get().strip() or "deepseek-ai/DeepSeek-OCR"
            key_text = self.vlm_api_key_var.get().strip()
        else:
            provider = self.llm_provider_var.get().strip() or "siliconflow"
            api_base = self.llm_api_base_var.get().strip() or self._provider_default_base(provider)
            api_key_env = self.llm_api_key_env_var.get().strip() or "SILICONFLOW_API_KEY"
            no_auth = bool(self.llm_no_auth_var.get())
            model = self.llm_model_var.get().strip() or "Qwen/Qwen3-8B"
            key_text = self.llm_api_key_var.get().strip()

        runtime_key = key_text or os.environ.get(api_key_env, "")
        return api_base, runtime_key, no_auth, model, provider

    def _json_post(self, url: str, payload: dict[str, object], headers: dict[str, str], timeout: float) -> dict[str, object]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read().decode("utf-8", errors="replace")
        return json.loads(content) if content else {}

    def _json_get(self, url: str, headers: dict[str, str], timeout: float) -> dict[str, object]:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read().decode("utf-8", errors="replace")
        return json.loads(content) if content else {}

    def _run_connection_test(self, channel: str) -> None:
        api_base, runtime_key, no_auth, model, provider = self._resolve_channel_runtime_key(channel)
        timeout = float(self.timeout_var.get().strip() or "120")
        base_url = api_base.rstrip("/")
        models_url = base_url + "/models"
        chat_url = base_url + "/chat/completions"

        if not base_url:
            messagebox.showerror("参数错误", f"{channel.upper()} API Base 不能为空")
            return

        self._append_log("=" * 80)
        self._append_log(f"开始测试 {channel.upper()} 连接: provider={provider}, base={base_url}, model={model}")

        def _worker() -> None:
            headers = {"Content-Type": "application/json"}
            if not no_auth:
                if not runtime_key:
                    self.log_queue.put(
                        f"{channel.upper()} 连接测试失败: 需要鉴权但未提供 API Key（可填 API Key 或设置环境变量）"
                    )
                    return
                headers["Authorization"] = f"Bearer {runtime_key}"

            try:
                models_data = self._json_get(models_url, headers=headers, timeout=timeout)
                model_ids: list[str] = []
                for row in models_data.get("data", []) if isinstance(models_data, dict) else []:
                    model_id = str((row or {}).get("id", "")).strip()
                    if model_id:
                        model_ids.append(model_id)
                preview = ", ".join(model_ids[:5]) if model_ids else "(空)"
                self.log_queue.put(f"{channel.upper()} /v1/models 成功，可用模型示例: {preview}")
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                self.log_queue.put(f"{channel.upper()} /v1/models 失败: HTTP {exc.code} {body[:200]}")
                return
            except Exception as exc:
                self.log_queue.put(f"{channel.upper()} /v1/models 失败: {exc}")
                return

            try:
                payload = {
                    "model": model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": "You are a connectivity test assistant."},
                        {"role": "user", "content": "Reply with OK only."},
                    ],
                }
                result = self._json_post(chat_url, payload=payload, headers=headers, timeout=timeout)
                choices = result.get("choices", []) if isinstance(result, dict) else []
                preview = ""
                if choices:
                    message = (choices[0] or {}).get("message", {})
                    preview = str(message.get("content", "")).strip().replace("\n", " ")[:80]
                self.log_queue.put(
                    f"{channel.upper()} 最小 chat 请求成功，返回片段: {preview or '(空返回但请求成功)'}"
                )
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                self.log_queue.put(
                    f"{channel.upper()} 最小 chat 请求失败: HTTP {exc.code} {body[:260]}"
                )
            except Exception as exc:
                self.log_queue.put(f"{channel.upper()} 最小 chat 请求失败: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    def _test_vlm_connection(self) -> None:
        self._run_connection_test("vlm")

    def _test_llm_connection(self) -> None:
        self._run_connection_test("llm")

    def _refresh_preset_values(self) -> None:
        names = self._builtin_presets + sorted(self.custom_presets.keys())
        self.preset_combo["values"] = names
        if self.preset_var.get().strip() not in names:
            self.preset_var.set("default")

    def _save_as_preset(self) -> None:
        name = simpledialog.askstring("保存预设", "请输入预设名称（不能覆盖 default/game/speech）")
        if name is None:
            return
        preset_name = name.strip()
        if not preset_name:
            messagebox.showerror("预设错误", "预设名称不能为空。")
            return
        if preset_name in self._builtin_presets:
            messagebox.showerror("预设错误", "不能覆盖内置预设。")
            return
        self.custom_presets[preset_name] = self._collect_state()
        self.preset_var.set(preset_name)
        self._refresh_preset_values()
        self._save_settings()
        self._append_log(f"已保存自定义预设: {preset_name}")

    def _load_selected_preset(self) -> None:
        name = self.preset_var.get().strip()
        if not name:
            messagebox.showerror("预设错误", "请先选择预设。")
            return
        if name in self._builtin_presets:
            self._append_log(f"已选择内置预设: {name}（运行时由 CLI 自动应用参数）")
            self._save_settings()
            return
        preset = self.custom_presets.get(name)
        if not isinstance(preset, dict):
            messagebox.showerror("预设错误", f"预设不存在: {name}")
            return
        self._apply_state(preset, include_input_output=False)
        self.preset_var.set(name)
        self._save_settings()
        self._append_log(f"已加载自定义预设: {name}")

    def _delete_selected_preset(self) -> None:
        name = self.preset_var.get().strip()
        if not name:
            return
        if name in self._builtin_presets:
            messagebox.showerror("预设错误", "内置预设不能删除。")
            return
        if name not in self.custom_presets:
            messagebox.showerror("预设错误", f"预设不存在: {name}")
            return
        if not messagebox.askyesno("确认删除", f"确定删除预设 {name} 吗？"):
            return
        del self.custom_presets[name]
        self.preset_var.set("default")
        self._refresh_preset_values()
        self._save_settings()
        self._append_log(f"已删除自定义预设: {name}")

    def _pipeline_paths(self) -> dict[str, Path]:
        input_path = self.input_var.get().strip()
        if not input_path:
            raise ValueError("请先选择输入视频")
        input_video = Path(input_path)
        if not input_video.exists():
            raise ValueError(f"输入文件不存在: {input_path}")

        output_root = Path(self.output_var.get().strip() or "outputs")
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

    def _phase1_flags(self) -> list[str]:
        flags = [
            "--model",
            self.asr_model_var.get().strip() or "small",
            "--hf-endpoint",
            self.hf_endpoint_var.get().strip() or "https://hf-mirror.com",
        ]

        if self.asr_model_path_var.get().strip():
            flags.extend(["--model-path", self.asr_model_path_var.get().strip()])
        if self.http_proxy_var.get().strip():
            flags.extend(["--http-proxy", self.http_proxy_var.get().strip()])
        if self.https_proxy_var.get().strip():
            flags.extend(["--https-proxy", self.https_proxy_var.get().strip()])
        if self.hf_home_var.get().strip():
            flags.extend(["--hf-home", self.hf_home_var.get().strip()])
        if self.offline_var.get():
            flags.append("--offline")
        return flags

    def _phase2_flags(self) -> list[str]:
        flags = [
            "--interval-seconds",
            self.interval_var.get().strip() or "30",
            "--context-window",
            self.context_window_var.get().strip() or "1",
            "--preset",
            self.preset_var.get().strip() or "default",
        ]
        if self.with_audio_summary_var.get():
            flags.append("--with-audio-summary")
        return flags

    def _phase3_flags(self) -> list[str]:
        flags = [
            "--model",
            self.vlm_model_var.get().strip() or "deepseek-ai/DeepSeek-OCR",
            "--api-base",
            self.vlm_api_base_var.get().strip() or "https://api.siliconflow.cn/v1",
            "--api-key-env",
            self.vlm_api_key_env_var.get().strip() or "SILICONFLOW_API_KEY",
            "--concurrency",
            self.concurrency_var.get().strip() or "3",
            "--max-retries",
            self.retry_var.get().strip() or "1",
            "--timeout-seconds",
            self.timeout_var.get().strip() or "120",
            "--provider",
            self.vlm_provider_var.get().strip() or "siliconflow",
            "--preset",
            self.preset_var.get().strip() or "default",
        ]
        if self.vlm_no_auth_var.get():
            flags.append("--no-auth")
        return flags

    def _phase4_flags(self) -> list[str]:
        flags = [
            "--llm-model",
            self.llm_model_var.get().strip() or "Qwen/Qwen3-8B",
            "--api-base",
            self.llm_api_base_var.get().strip() or "https://api.siliconflow.cn/v1",
            "--api-key-env",
            self.llm_api_key_env_var.get().strip() or "SILICONFLOW_API_KEY",
            "--provider",
            self.llm_provider_var.get().strip() or "siliconflow",
            "--preset",
            self.preset_var.get().strip() or "default",
            "--timeout-seconds",
            self.timeout_var.get().strip() or "120",
        ]
        if self.use_llm_polish_var.get():
            flags.append("--use-llm-polish")
        if self.llm_no_auth_var.get():
            flags.append("--no-auth")
        return flags

    def _base_cmd(self) -> list[str]:
        return [
            self._select_python(),
            "-m",
            "videosummary.cli",
            "--verbose",
        ]

    def _build_run_all_command(self) -> list[str]:
        paths = self._pipeline_paths()

        cmd = self._base_cmd() + [
            "run-all",
            "--input",
            str(paths["input"]),
            "--output",
            self.output_var.get().strip() or "outputs",
            "--preset",
            self.preset_var.get().strip() or "default",
            "--model",
            self.asr_model_var.get().strip() or "small",
            "--provider",
            self.vlm_provider_var.get().strip() or "siliconflow",
            "--api-base",
            self.vlm_api_base_var.get().strip() or "https://api.siliconflow.cn/v1",
            "--api-key-env",
            self.vlm_api_key_env_var.get().strip() or "SILICONFLOW_API_KEY",
            "--hf-endpoint",
            self.hf_endpoint_var.get().strip() or "https://hf-mirror.com",
            "--vlm-model",
            self.vlm_model_var.get().strip() or "deepseek-ai/DeepSeek-OCR",
            "--vlm-provider",
            self.vlm_provider_var.get().strip() or "siliconflow",
            "--vlm-api-base",
            self.vlm_api_base_var.get().strip() or "https://api.siliconflow.cn/v1",
            "--vlm-api-key-env",
            self.vlm_api_key_env_var.get().strip() or "SILICONFLOW_API_KEY",
            "--llm-model",
            self.llm_model_var.get().strip() or "Qwen/Qwen3-8B",
            "--llm-provider",
            self.llm_provider_var.get().strip() or "siliconflow",
            "--llm-api-base",
            self.llm_api_base_var.get().strip() or "https://api.siliconflow.cn/v1",
            "--llm-api-key-env",
            self.llm_api_key_env_var.get().strip() or "SILICONFLOW_API_KEY",
            "--interval-seconds",
            self.interval_var.get().strip() or "30",
            "--context-window",
            self.context_window_var.get().strip() or "1",
            "--timeout-seconds",
            self.timeout_var.get().strip() or "120",
            "--concurrency",
            self.concurrency_var.get().strip() or "3",
            "--max-retries",
            self.retry_var.get().strip() or "1",
        ]

        if self.with_audio_summary_var.get():
            cmd.append("--with-audio-summary")
        if self.use_llm_polish_var.get():
            cmd.append("--use-llm-polish")
        if self.asr_model_path_var.get().strip():
            cmd.extend(["--model-path", self.asr_model_path_var.get().strip()])
        if self.http_proxy_var.get().strip():
            cmd.extend(["--http-proxy", self.http_proxy_var.get().strip()])
        if self.https_proxy_var.get().strip():
            cmd.extend(["--https-proxy", self.https_proxy_var.get().strip()])
        if self.hf_home_var.get().strip():
            cmd.extend(["--hf-home", self.hf_home_var.get().strip()])
        if self.offline_var.get():
            cmd.append("--offline")
        if self.vlm_no_auth_var.get():
            cmd.append("--no-auth")
            cmd.append("--vlm-no-auth")
        if self.llm_no_auth_var.get():
            cmd.append("--llm-no-auth")

        return cmd

    def _build_phase1_command(self) -> list[str]:
        paths = self._pipeline_paths()
        cmd = self._base_cmd() + [
            "phase1",
            "--input",
            str(paths["input"]),
            "--output",
            self.output_var.get().strip() or "outputs",
        ]
        cmd.extend(self._phase1_flags())
        return cmd

    def _build_phase2_command(self) -> list[str]:
        paths = self._pipeline_paths()
        phase1_dir = paths["phase1_dir"]
        if not (phase1_dir / "phase1_manifest.json").exists():
            raise ValueError(f"未找到 Phase1 产物，请先执行 Phase1: {phase1_dir}")
        cmd = self._base_cmd() + [
            "phase2-fixed",
            "--phase1-dir",
            str(phase1_dir),
            "--output",
            str(paths["phase2_dir"]),
        ]
        cmd.extend(self._phase2_flags())
        return cmd

    def _build_phase3_command(self) -> list[str]:
        paths = self._pipeline_paths()
        payload_jsonl = paths["phase2_payload_jsonl"]
        if not payload_jsonl.exists():
            raise ValueError(f"未找到 Phase2 payload，请先执行 Phase2: {payload_jsonl}")
        cmd = self._base_cmd() + [
            "phase3-vlm",
            "--vlm-payload-jsonl",
            str(payload_jsonl),
            "--output",
            str(paths["phase3_dir"]),
        ]
        cmd.extend(self._phase3_flags())
        return cmd

    def _build_phase4_command(self) -> list[str]:
        paths = self._pipeline_paths()
        phase1_dir = paths["phase1_dir"]
        phase3_jsonl = paths["phase3_jsonl"]
        phase2_payload_jsonl = paths["phase2_payload_jsonl"]
        if not phase1_dir.exists():
            raise ValueError(f"未找到 Phase1 目录，请先执行 Phase1: {phase1_dir}")
        if not phase3_jsonl.exists():
            raise ValueError(f"未找到 Phase3 产物，请先执行 Phase3: {phase3_jsonl}")
        cmd = self._base_cmd() + [
            "phase4-summary",
            "--phase1-dir",
            str(phase1_dir),
            "--phase3-jsonl",
            str(phase3_jsonl),
            "--phase2-payload-jsonl",
            str(phase2_payload_jsonl),
            "--output",
            str(paths["phase4_dir"]),
        ]
        cmd.extend(self._phase4_flags())
        return cmd

    def _runtime_api_key_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        vlm_key = self.vlm_api_key_var.get().strip()
        llm_key = self.llm_api_key_var.get().strip()
        vlm_env = self.vlm_api_key_env_var.get().strip() or "SILICONFLOW_API_KEY"
        llm_env = self.llm_api_key_env_var.get().strip() or "SILICONFLOW_API_KEY"
        if vlm_key:
            env[vlm_env] = vlm_key
        if llm_key:
            env[llm_env] = llm_key
        return env

    def _start_command(self, cmd: list[str], title: str) -> None:
        self._save_settings()

        self._append_log("=" * 80)
        self._append_log(f"开始执行[{title}]: " + " ".join(cmd))
        self._append_log(f"执行目录: {self._project_root}")

        def _worker() -> None:
            env = dict(**os.environ)
            src_path = str(self._project_root / "src")
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = src_path if not existing else f"{src_path};{existing}"
            env.setdefault("PYTHONIOENCODING", "utf-8")
            env.setdefault("PYTHONUTF8", "1")
            env.update(self._runtime_api_key_env())

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(self._project_root),
                env=env,
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.log_queue.put(line.rstrip("\n"))
            code = self.process.wait()
            self.log_queue.put(f"任务结束，退出码: {code}")
            self.process = None

        threading.Thread(target=_worker, daemon=True).start()

    def _run_all(self) -> None:
        if self.process is not None and self.process.poll() is None:
            messagebox.showwarning("提示", "已有任务在运行，请先停止或等待完成。")
            return

        try:
            cmd = self._build_run_all_command()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self._start_command(cmd, "run-all")

    def _run_phase1(self) -> None:
        if self.process is not None and self.process.poll() is None:
            messagebox.showwarning("提示", "已有任务在运行，请先停止或等待完成。")
            return
        try:
            cmd = self._build_phase1_command()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self._start_command(cmd, "phase1")

    def _run_phase2(self) -> None:
        if self.process is not None and self.process.poll() is None:
            messagebox.showwarning("提示", "已有任务在运行，请先停止或等待完成。")
            return
        try:
            cmd = self._build_phase2_command()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self._start_command(cmd, "phase2-fixed")

    def _run_phase3(self) -> None:
        if self.process is not None and self.process.poll() is None:
            messagebox.showwarning("提示", "已有任务在运行，请先停止或等待完成。")
            return
        try:
            cmd = self._build_phase3_command()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self._start_command(cmd, "phase3-vlm")

    def _run_phase4(self) -> None:
        if self.process is not None and self.process.poll() is None:
            messagebox.showwarning("提示", "已有任务在运行，请先停止或等待完成。")
            return
        try:
            cmd = self._build_phase4_command()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        self._start_command(cmd, "phase4-summary")

    def _save_current_config(self) -> None:
        try:
            self._save_settings()
        except Exception as exc:
            messagebox.showerror("保存失败", f"保存配置失败: {exc}")
            return
        self._append_log(f"已保存当前配置到: {self._settings_path}")

    def _stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            self._append_log("当前没有运行中的任务。")
            return
        self.process.terminate()
        self._append_log("已请求停止当前任务。")


def main() -> None:
    root = tk.Tk()
    app = VideoSummaryPanel(root)
    _ = app
    root.mainloop()


if __name__ == "__main__":
    main()
