from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from videosummary.gui_mod.commands import pipeline_paths, runtime_api_key_env
from videosummary.gui_mod.config_store import default_base_for_provider, load_settings, save_settings, sync_base_url
from videosummary.gui_mod.connectivity import run_connection_probe


class VideoSummaryPanel:
    BUILTIN_PRESETS = ["default", "game", "speech"]

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("VideoSummary 控制面板")
        self.root.geometry("1220x820")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.custom_presets: dict[str, dict[str, object]] = {}
        self.control_widgets: list[tk.Widget] = []
        self.status_var = tk.StringVar(value="空闲")
        self.log_history: list[str] = []
        self.log_window: tk.Toplevel | None = None
        self.log_popup_text: tk.Text | None = None
        self.left_section_frame: ttk.LabelFrame | None = None
        self.right_section_frame: ttk.LabelFrame | None = None
        self.log_preview_frame: ttk.Frame | None = None
        self.toggle_left_btn: ttk.Button | None = None
        self.toggle_right_btn: ttk.Button | None = None
        self.toggle_log_btn: ttk.Button | None = None

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
        last, custom = load_settings(self._settings_path)
        if custom:
            self.custom_presets = custom
        if last:
            self._apply_state(last, include_input_output=True)

    def _save_settings(self) -> None:
        save_settings(self._settings_path, self._collect_state(), self.custom_presets)

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
        root_frame = ttk.Frame(self.root, padding=12)
        root_frame.pack(fill=tk.X)
        root_frame.columnconfigure(0, weight=1)

        top = ttk.LabelFrame(root_frame, text="输入与预设", padding=10)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="输入视频").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(top, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        pick_input_btn = ttk.Button(top, text="浏览", command=self._pick_input)
        pick_input_btn.grid(row=0, column=2)

        ttk.Label(top, text="输出目录").grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(top, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
        pick_output_btn = ttk.Button(top, text="浏览", command=self._pick_output)
        pick_output_btn.grid(row=1, column=2, pady=(8, 0))

        ttk.Label(top, text="预设").grid(row=2, column=0, sticky=tk.W, pady=(8, 0))
        self.preset_combo = ttk.Combobox(top, textvariable=self.preset_var, values=self._builtin_presets, width=18)
        self.preset_combo.grid(row=2, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))
        preset_btn_row = ttk.Frame(top)
        preset_btn_row.grid(row=2, column=2, sticky=tk.E, pady=(8, 0))
        load_preset_btn = ttk.Button(preset_btn_row, text="载入预设", command=self._load_selected_preset)
        save_preset_btn = ttk.Button(preset_btn_row, text="另存预设", command=self._save_as_preset)
        del_preset_btn = ttk.Button(preset_btn_row, text="删除预设", command=self._delete_selected_preset)
        load_preset_btn.pack(side=tk.LEFT)
        save_preset_btn.pack(side=tk.LEFT, padx=6)
        del_preset_btn.pack(side=tk.LEFT)

        layout_tools = ttk.Frame(top)
        layout_tools.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(8, 0))
        self.toggle_left_btn = ttk.Button(layout_tools, text="收起ASR区", command=self._toggle_left_section)
        self.toggle_right_btn = ttk.Button(layout_tools, text="收起模型区", command=self._toggle_right_section)
        self.toggle_log_btn = ttk.Button(layout_tools, text="收起日志预览", command=self._toggle_log_preview)
        top_log_btn = ttk.Button(layout_tools, text="打开日志窗口", command=self._open_log_window)
        self.toggle_left_btn.pack(side=tk.LEFT)
        self.toggle_right_btn.pack(side=tk.LEFT, padx=6)
        self.toggle_log_btn.pack(side=tk.LEFT)
        top_log_btn.pack(side=tk.LEFT, padx=6)

        middle = ttk.Frame(root_frame)
        middle.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        middle.columnconfigure(0, weight=1)
        middle.columnconfigure(1, weight=1)

        left = ttk.LabelFrame(middle, text="ASR 与流程", padding=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.columnconfigure(1, weight=1)
        self.left_section_frame = left

        ttk.Label(left, text="ASR 模型").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(left, textvariable=self.asr_model_var).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        ttk.Label(left, text="ASR 本地模型目录").grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(left, textvariable=self.asr_model_path_var).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        pick_model_btn = ttk.Button(left, text="浏览", command=self._pick_model_dir)
        pick_model_btn.grid(row=1, column=2, padx=(8, 0), pady=(8, 0))

        ttk.Label(left, text="HF 镜像地址").grid(row=2, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(left, textvariable=self.hf_endpoint_var).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        ttk.Label(left, text="HTTP 代理").grid(row=3, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(left, textvariable=self.http_proxy_var).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        ttk.Label(left, text="HTTPS 代理").grid(row=4, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(left, textvariable=self.https_proxy_var).grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        ttk.Label(left, text="HF 缓存目录").grid(row=5, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(left, textvariable=self.hf_home_var).grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        ttk.Checkbutton(left, text="ASR 离线模式", variable=self.offline_var).grid(row=6, column=1, sticky=tk.W, pady=(8, 0))

        ttk.Label(left, text="截帧间隔(s)").grid(row=7, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(left, textvariable=self.interval_var, width=10).grid(row=7, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))

        ttk.Label(left, text="上下文窗口").grid(row=8, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(left, textvariable=self.context_window_var, width=10).grid(row=8, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))

        ttk.Label(left, text="API 超时(s)").grid(row=9, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(left, textvariable=self.timeout_var, width=10).grid(row=9, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))

        ttk.Label(left, text="并发请求数").grid(row=10, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(left, textvariable=self.concurrency_var, width=10).grid(row=10, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))

        ttk.Label(left, text="重试次数").grid(row=11, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(left, textvariable=self.retry_var, width=10).grid(row=11, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))

        ttk.Checkbutton(left, text="附加音频摘要", variable=self.with_audio_summary_var).grid(row=12, column=1, sticky=tk.W, pady=(8, 0))
        ttk.Checkbutton(left, text="启用 LLM 优化", variable=self.use_llm_polish_var).grid(row=13, column=1, sticky=tk.W, pady=(4, 0))

        right = ttk.LabelFrame(middle, text="模型通道", padding=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.columnconfigure(1, weight=1)
        self.right_section_frame = right

        ttk.Label(right, text="VLM 模型").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(right, textvariable=self.vlm_model_var).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(right, text="LLM 模型").grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(right, textvariable=self.llm_model_var).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        ttk.Label(right, text="VLM 提供商").grid(row=2, column=0, sticky=tk.W, pady=(8, 0))
        self.vlm_provider_combo = ttk.Combobox(
            right,
            textvariable=self.vlm_provider_var,
            values=["siliconflow", "openai", "lmstudio", "custom"],
            width=18,
        )
        self.vlm_provider_combo.grid(row=2, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))
        self.vlm_provider_combo.bind("<<ComboboxSelected>>", self._on_vlm_provider_changed)

        ttk.Label(right, text="VLM API Base").grid(row=3, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(right, textvariable=self.vlm_api_base_var).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(right, text="VLM API Key Env").grid(row=4, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(right, textvariable=self.vlm_api_key_env_var).grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(right, text="VLM API Key(可选)").grid(row=5, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(right, textvariable=self.vlm_api_key_var, show="*").grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Checkbutton(right, text="VLM 禁用鉴权头(no-auth)", variable=self.vlm_no_auth_var).grid(row=6, column=1, sticky=tk.W, pady=(4, 0))

        ttk.Label(right, text="LLM 提供商").grid(row=7, column=0, sticky=tk.W, pady=(8, 0))
        self.llm_provider_combo = ttk.Combobox(
            right,
            textvariable=self.llm_provider_var,
            values=["siliconflow", "openai", "lmstudio", "custom"],
            width=18,
        )
        self.llm_provider_combo.grid(row=7, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))
        self.llm_provider_combo.bind("<<ComboboxSelected>>", self._on_llm_provider_changed)

        ttk.Label(right, text="LLM API Base").grid(row=8, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(right, textvariable=self.llm_api_base_var).grid(row=8, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(right, text="LLM API Key Env").grid(row=9, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(right, textvariable=self.llm_api_key_env_var).grid(row=9, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(right, text="LLM API Key(可选)").grid(row=10, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(right, textvariable=self.llm_api_key_var, show="*").grid(row=10, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Checkbutton(right, text="LLM 禁用鉴权头(no-auth)", variable=self.llm_no_auth_var).grid(row=11, column=1, sticky=tk.W, pady=(4, 0))

        test_row = ttk.Frame(right)
        test_row.grid(row=12, column=1, sticky=tk.W, pady=(10, 0))
        test_vlm_btn = ttk.Button(test_row, text="测试 VLM 连接", command=self._test_vlm_connection)
        test_llm_btn = ttk.Button(test_row, text="测试 LLM 连接", command=self._test_llm_connection)
        test_vlm_btn.pack(side=tk.LEFT)
        test_llm_btn.pack(side=tk.LEFT, padx=6)

        actions = ttk.LabelFrame(root_frame, text="执行控制", padding=10)
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        btn_row = ttk.Frame(actions)
        btn_row.pack(anchor=tk.W)
        run_all_btn = ttk.Button(btn_row, text="运行全流程", command=self._run_all)
        run_p1_btn = ttk.Button(btn_row, text="仅 Phase1", command=self._run_phase1)
        run_p2_btn = ttk.Button(btn_row, text="仅 Phase2", command=self._run_phase2)
        run_p3_btn = ttk.Button(btn_row, text="仅 Phase3", command=self._run_phase3)
        run_p4_btn = ttk.Button(btn_row, text="仅 Phase4", command=self._run_phase4)
        stop_btn = ttk.Button(btn_row, text="停止", command=self._stop)
        save_cfg_btn = ttk.Button(btn_row, text="保存当前配置", command=self._save_current_config)
        run_all_btn.pack(side=tk.LEFT)
        run_p1_btn.pack(side=tk.LEFT, padx=6)
        run_p2_btn.pack(side=tk.LEFT)
        run_p3_btn.pack(side=tk.LEFT, padx=6)
        run_p4_btn.pack(side=tk.LEFT)
        stop_btn.pack(side=tk.LEFT, padx=6)
        save_cfg_btn.pack(side=tk.LEFT)

        self.control_widgets.extend(
            [
                pick_input_btn,
                pick_output_btn,
                load_preset_btn,
                save_preset_btn,
                del_preset_btn,
                pick_model_btn,
                test_vlm_btn,
                test_llm_btn,
                run_all_btn,
                run_p1_btn,
                run_p2_btn,
                run_p3_btn,
                run_p4_btn,
                save_cfg_btn,
            ]
        )

        status_frame = ttk.Frame(root_frame, padding=(0, 8, 0, 0))
        status_frame.grid(row=3, column=0, sticky="ew")
        ttk.Label(status_frame, text="状态:").pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT, padx=(6, 0))

    def _build_log_view(self) -> None:
        frame = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        frame.pack(fill=tk.BOTH, expand=True)

        tools = ttk.Frame(frame)
        tools.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(tools, text="弹出日志窗口", command=self._open_log_window).pack(side=tk.LEFT)
        ttk.Button(tools, text="清空日志", command=self._clear_logs).pack(side=tk.LEFT, padx=6)

        self.log_preview_frame = ttk.Frame(frame)
        self.log_preview_frame.pack(fill=tk.BOTH, expand=True)

        # Keep a compact in-panel preview; full logs are available in popup window.
        self.log_text = tk.Text(self.log_preview_frame, wrap=tk.WORD, height=8)
        self.log_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        scrollbar = ttk.Scrollbar(self.log_preview_frame, command=self.log_text.yview)
        scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.log_text.config(yscrollcommand=scrollbar.set)

    def _toggle_left_section(self) -> None:
        if self.left_section_frame is None or self.toggle_left_btn is None:
            return
        if self.left_section_frame.winfo_ismapped():
            self.left_section_frame.grid_remove()
            self.toggle_left_btn.configure(text="展开ASR区")
        else:
            self.left_section_frame.grid()
            self.toggle_left_btn.configure(text="收起ASR区")

    def _toggle_right_section(self) -> None:
        if self.right_section_frame is None or self.toggle_right_btn is None:
            return
        if self.right_section_frame.winfo_ismapped():
            self.right_section_frame.grid_remove()
            self.toggle_right_btn.configure(text="展开模型区")
        else:
            self.right_section_frame.grid()
            self.toggle_right_btn.configure(text="收起模型区")

    def _toggle_log_preview(self) -> None:
        if self.log_preview_frame is None or self.toggle_log_btn is None:
            return
        if self.log_preview_frame.winfo_ismapped():
            self.log_preview_frame.pack_forget()
            self.toggle_log_btn.configure(text="展开日志预览")
        else:
            self.log_preview_frame.pack(fill=tk.BOTH, expand=True)
            self.toggle_log_btn.configure(text="收起日志预览")

    def _open_log_window(self) -> None:
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.deiconify()
            self.log_window.lift()
            return

        window = tk.Toplevel(self.root)
        window.title("VideoSummary 日志")
        window.geometry("1100x620")

        text = tk.Text(window, wrap=tk.WORD)
        text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        scrollbar = ttk.Scrollbar(window, command=text.yview)
        scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        text.config(yscrollcommand=scrollbar.set)

        if self.log_history:
            text.insert(tk.END, "\n".join(self.log_history) + "\n")
            text.see(tk.END)

        def _on_close() -> None:
            self.log_window = None
            self.log_popup_text = None
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", _on_close)
        self.log_window = window
        self.log_popup_text = text

    def _clear_logs(self) -> None:
        self.log_history.clear()
        self.log_text.delete("1.0", tk.END)
        if self.log_popup_text is not None:
            self.log_popup_text.delete("1.0", tk.END)

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
        self.log_history.append(line)
        if len(self.log_history) > 5000:
            self.log_history = self.log_history[-5000:]
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        if self.log_popup_text is not None:
            self.log_popup_text.insert(tk.END, line + "\n")
            self.log_popup_text.see(tk.END)

    def _drain_log_queue(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if line == "__GUI_STATE_IDLE__":
                self._set_running_state(False, "空闲")
                continue
            self._append_log(line)
        self.root.after(200, self._drain_log_queue)

    def _provider_default_base(self, provider: str) -> str:
        return default_base_for_provider(provider)

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
        base_var.set(sync_base_url(provider, base_var.get(), force=force))

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

    def _run_connection_test(self, channel: str) -> None:
        api_base, runtime_key, no_auth, model, provider = self._resolve_channel_runtime_key(channel)
        timeout = float(self.timeout_var.get().strip() or "120")
        base_url = api_base.rstrip("/")

        if not base_url:
            messagebox.showerror("参数错误", f"{channel.upper()} API Base 不能为空")
            return

        self._append_log("=" * 80)
        self._append_log(f"开始测试 {channel.upper()} 连接: provider={provider}, base={base_url}, model={model}")
        self.status_var.set(f"测试中: {channel.upper()}")

        def _worker() -> None:
            logs = run_connection_probe(
                channel=channel,
                api_base=base_url,
                model=model,
                timeout_seconds=timeout,
                api_key=runtime_key,
                send_auth_header=not no_auth,
            )
            for line in logs:
                self.log_queue.put(line)
            self.log_queue.put("__GUI_STATE_IDLE__")

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
        return pipeline_paths(self.input_var.get().strip(), self.output_var.get().strip() or "outputs")

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
        return runtime_api_key_env(
            {
                "vlm_api_key": self.vlm_api_key_var.get().strip(),
                "llm_api_key": self.llm_api_key_var.get().strip(),
                "vlm_api_key_env": self.vlm_api_key_env_var.get().strip(),
                "llm_api_key_env": self.llm_api_key_env_var.get().strip(),
            }
        )

    def _start_command(self, cmd: list[str], title: str) -> None:
        self._save_settings()
        self._set_running_state(True, f"运行中: {title}")

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
            self.log_queue.put("__GUI_STATE_IDLE__")

        threading.Thread(target=_worker, daemon=True).start()

    def _set_running_state(self, running: bool, status_text: str | None = None) -> None:
        for widget in self.control_widgets:
            try:
                widget.configure(state=("disabled" if running else "normal"))
            except Exception:
                continue
        if status_text is not None:
            self.status_var.set(status_text)

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
        self.status_var.set("停止中...")


def main() -> None:
    root = tk.Tk()
    app = VideoSummaryPanel(root)
    _ = app
    root.mainloop()


if __name__ == "__main__":
    main()
