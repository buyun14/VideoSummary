from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


class VideoSummaryPanel:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("VideoSummary 控制面板")
        self.root.geometry("980x700")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None

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
        self.llm_model_var = tk.StringVar(value="Qwen/Qwen3-8B")
        self.interval_var = tk.StringVar(value="30")
        self.context_window_var = tk.StringVar(value="1")
        self.timeout_var = tk.StringVar(value="120")
        self.concurrency_var = tk.StringVar(value="3")
        self.retry_var = tk.StringVar(value="1")
        self.use_llm_polish_var = tk.BooleanVar(value=True)
        self.with_audio_summary_var = tk.BooleanVar(value=True)

        self._build_form()
        self._build_log_view()
        self.root.after(200, self._drain_log_queue)

    @property
    def _project_root(self) -> Path:
        # gui.py -> videosummary/ -> src/ -> project root
        return Path(__file__).resolve().parents[2]

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
        ttk.Combobox(frame, textvariable=self.preset_var, values=["default", "game", "speech"], width=18).grid(
            row=row, column=1, sticky=tk.W
        )

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
        ttk.Label(frame, text="LLM 模型").grid(row=row, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.llm_model_var, width=20).grid(row=row, column=1, sticky=tk.W)
        ttk.Label(frame, text="截帧间隔(s)").grid(row=row, column=1, sticky=tk.E, padx=(0, 260))
        ttk.Entry(frame, textvariable=self.interval_var, width=8).grid(row=row, column=1, sticky=tk.E)

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
        ttk.Button(btn_row, text="停止", command=self._stop).pack(side=tk.LEFT, padx=8)

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

    def _build_run_all_command(self) -> list[str]:
        input_path = self.input_var.get().strip()
        if not input_path:
            raise ValueError("请先选择输入视频")
        if not Path(input_path).exists():
            raise ValueError(f"输入文件不存在: {input_path}")

        cmd = [
            self._select_python(),
            "-m",
            "videosummary.cli",
            "--verbose",
            "run-all",
            "--input",
            input_path,
            "--output",
            self.output_var.get().strip() or "outputs",
            "--preset",
            self.preset_var.get().strip() or "default",
            "--model",
            self.asr_model_var.get().strip() or "small",
            "--hf-endpoint",
            self.hf_endpoint_var.get().strip() or "https://hf-mirror.com",
            "--vlm-model",
            self.vlm_model_var.get().strip() or "deepseek-ai/DeepSeek-OCR",
            "--llm-model",
            self.llm_model_var.get().strip() or "Qwen/Qwen3-8B",
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

        return cmd

    def _run_all(self) -> None:
        if self.process is not None and self.process.poll() is None:
            messagebox.showwarning("提示", "已有任务在运行，请先停止或等待完成。")
            return

        try:
            cmd = self._build_run_all_command()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        self._append_log("=" * 80)
        self._append_log("开始执行: " + " ".join(cmd))
        self._append_log(f"执行目录: {self._project_root}")

        def _worker() -> None:
            env = dict(**os.environ)
            src_path = str(self._project_root / "src")
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = src_path if not existing else f"{src_path};{existing}"
            env.setdefault("PYTHONIOENCODING", "utf-8")
            env.setdefault("PYTHONUTF8", "1")

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
