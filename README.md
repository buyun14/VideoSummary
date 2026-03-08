# VideoSummary

基于你的规划，这个仓库先落地第一阶段：
- 音画分离（`ffmpeg`）
- 带时间戳 ASR（`faster-whisper`）
- 标准化输出（`json/jsonl/txt/srt/manifest`）

## 1. 环境准备

### 必备
- Python 3.10+
- `ffmpeg`（确保命令行可直接运行 `ffmpeg -version`）

Windows 可通过 `winget` 安装：

```powershell
winget install Gyan.FFmpeg
```

### 安装依赖

```powershell
.\.venv\Scripts\python -m pip install -e .
```

## 2. 运行第一阶段

```powershell
.\.venv\Scripts\python -m videosummary.cli --input "data_test/屏幕录制 2025-04-17 193845.mp4" --output outputs --model small --device auto --compute-type int8
```

通用可观测参数（所有子命令可用）：
- `--verbose`：显示中文友好进度日志
- `--debug`：显示更详细调试日志
- `--log-file logs/run.log`：落盘日志文件，便于排障

可选参数：
- `--language zh`：固定中文识别（不填则自动检测）
- `--model tiny|base|small|medium|large-v3`：模型大小与成本/精度可权衡
- `--device cpu|cuda|auto`：运行设备
- `--model-path <本地模型目录>`：使用本地 Whisper 模型，避免联网下载
- `--hf-endpoint https://hf-mirror.com`：使用镜像源（国内推荐）
- `--http-proxy` / `--https-proxy`：代理配置
- `--hf-home <缓存目录>`：指定模型缓存目录
- `--offline`：离线模式（仅使用本地缓存/本地模型）

### 2.1 网络不稳定时的建议（Phase1）

常见错误：`httpx.ConnectTimeout: [WinError 10060]`、`LocalEntryNotFoundError`

推荐命令：

```powershell
.\.venv\Scripts\python -m videosummary.cli --verbose phase1 --input "data_test/Base Profile 2025.07.09 - 17.20.58.03.mp4" --model small --hf-endpoint "https://hf-mirror.com" --https-proxy "http://127.0.0.1:7890"
```

若已有本地模型目录：

```powershell
.\.venv\Scripts\python -m videosummary.cli --verbose phase1 --input "data_test/Base Profile 2025.07.09 - 17.20.58.03.mp4" --model-path "D:/models/faster-whisper-small" --offline
```

日志默认使用 UTF-8 输出；Windows 终端若仍乱码，建议在 PowerShell 先执行：

```powershell
chcp 65001
```

## 3. 输出目录说明

运行后会生成：

- `outputs/<视频名>/phase1/audio_16k_mono.wav`
- `outputs/<视频名>/phase1/transcript.full.json`
- `outputs/<视频名>/phase1/transcript.segments.jsonl`
- `outputs/<视频名>/phase1/transcript.txt`
- `outputs/<视频名>/phase1/transcript.srt`
- `outputs/<视频名>/phase1/phase1_manifest.json`

## 4. 为什么这样设计

第一阶段核心目标是把视频压缩为可计算的“文本时间轴骨架”，为后续“智能路由 + 按需视觉增强”做输入。

当前设计做了三件事：
- 可重放：保留标准化中间产物（wav + jsonl + manifest）
- 可追踪：每次运行输出检测语言、时长、片段数
- 可扩展：第二阶段可直接消费 `transcript.segments.jsonl` 做关键时间戳筛选

## 5. 下一步（接第二阶段）

建议新增：
- `router` 模块：对转录文本打“视觉依赖分数”
- `keyframe planner`：按分数生成截图时间戳与上下文窗口
- 轻量规则 + LLM 混合策略，避免全量 VLM 成本

## 6. 运行第二阶段（默认：固定间隔采样）

先采用固定时间戳截屏，不做意图识别。该步骤会生成：
- 固定间隔关键帧计划
- 截图文件（可关闭）
- 给视觉模型使用的载荷 `vlm_payload.jsonl`
- 可选附加：对应分片文本、上下文窗口文本、音频摘要

```powershell
.\.venv\Scripts\python -m videosummary.cli phase2-fixed --phase1-dir "outputs/屏幕录制 2025-04-17 193845/phase1" --interval-seconds 30 --context-window 1 --with-audio-summary
```

可选参数：
- `--preset default|game|speech`：友好预设（游戏/讲解视频）
- `--no-capture-images`：只生成计划和载荷，不实际截图
- `--without-segment-text`：不附加当前时间点分片文本
- `--context-window 0|1|2...`：附加前后分片窗口
- `--with-audio-summary`：附加 phase1 音频摘要（用于缓解断章截屏）
- `--summary-max-points 8`：摘要时间线要点条数
- `--start-seconds` / `--end-trim-seconds`：控制采样范围

默认输出目录：`outputs/<视频名>/phase2_fixed/`

主要产物：
- `fixed_keyframe_plan.json`
- `vlm_payload.jsonl`
- `screenshots/`
- `phase2_fixed_manifest.json`

## 7. 可选高级模式（Router）

在你确认固定采样基线后，再使用 router 进行更精细筛选：

```powershell
.\.venv\Scripts\python -m videosummary.cli router --transcript-jsonl "outputs/屏幕录制 2025-04-17 193845/phase1/transcript.segments.jsonl"
```

可选参数：
- `--top-k 18`：候选上限（合并前）
- `--min-score 2.0`：视觉依赖阈值
- `--merge-gap-seconds 8`：时间相邻窗口合并阈值
- `--context-window 1`：输出上下文片段数
- `--min-plan-items 8`：若规则命中过少，自动按时间轴均匀补采样

默认会输出到同视频目录下：`outputs/<视频名>/phase2/`

主要产物：
- `router.scored_segments.jsonl`：每条转录片段的路由分数
- `keyframe_plan.json`：可被后续截图/VLM模块直接消费
- `keyframe_plan.md`：人可读的关键帧说明
- `phase2_router_manifest.json`：运行统计与产物路径

## 8. 第三阶段（VLM 分析）

基于第二阶段 `vlm_payload.jsonl` 调用 OpenAI 兼容接口（如 SiliconFlow）进行逐帧分析。

先设置环境变量（推荐，不把 key 写进命令）：

```powershell
$env:SILICONFLOW_API_KEY="<your_api_key>"
```

也支持在项目根目录放置 `.env`（例如 `SILICONFLOW_API_KEY=...`），CLI 会自动读取。

执行：

```powershell
.\.venv\Scripts\python -m videosummary.cli phase3-vlm --vlm-payload-jsonl "outputs/屏幕录制 2025-04-17 193845/phase2_fixed/vlm_payload.jsonl" --api-base "https://api.siliconflow.cn/v1" --model "deepseek-ai/DeepSeek-OCR" --max-items 3
```

说明：`deepseek-ai/DeepSeek-OCR` 更偏 OCR/文档抽取，若用于“画面理解+解释”可能返回过短。建议在第三阶段优先选用通用视觉对话模型，OCR 模型作为补充通道。

可选参数：
- `--preset default|game|speech`：友好预设（会调整超时、温度等）
- `--without-image`：仅发送文本上下文用于对照实验
- `--max-items N`：只跑前 N 条，便于快速调试
- `--temperature 0.2`：采样温度
- `--timeout-seconds 120`
- `--concurrency 3`：并发请求数（建议 2~6）
- `--max-retries 1`：失败重试次数
- `--retry-backoff-seconds 2`：重试等待秒数

输出目录（默认）：`outputs/<视频名>/phase2_fixed/phase3_vlm/`

主要产物：
- `visual_analysis.jsonl`：每帧的视觉分析结果
- `phase3_vlm_manifest.json`：调用统计（成功/失败）

## 9. 第四阶段（最终总结聚合）

第四阶段会基于 `phase1 + phase3` 直接生成你关注的三类结果：
- 优化/纠错后的原始音频总结
- 关键时间戳总结文本（含截图路径、单帧理解、上下文）
- 最终视频总结

命令示例：

```powershell
.\.venv\Scripts\python -m videosummary.cli phase4-summary --phase1-dir "outputs/屏幕录制 2025-04-17 193845/phase1" --phase3-jsonl "outputs/屏幕录制 2025-04-17 193845/phase2_fixed/phase3_vlm_qwen3vl8b_dotenv/visual_analysis.jsonl" --phase2-payload-jsonl "outputs/屏幕录制 2025-04-17 193845/phase2_fixed/vlm_payload.jsonl" --use-llm-polish --llm-model "Qwen/Qwen3-8B"
```

可选参数：
- `--preset default|game|speech`：友好预设（会调整关键时刻数量）
- `--use-llm-polish`：开启模型优化总结（不开启也会产出可读 fallback）
- `--max-key-moments 12`：关键时间戳条目上限
- `--api-base` / `--api-key` / `--api-key-env`：模型调用配置

默认输出目录：`<phase3目录>/phase4_summary/`

主要产物：
- `audio_summary_optimized.md`
- `key_moments_summary.md`
- `final_video_summary.md`
- `phase4_summary_manifest.json`

## 10. 一键运行全流程（推荐）

```powershell
.\.venv\Scripts\python -m videosummary.cli --verbose --log-file "logs/game_run.log" run-all --input "data_test/Base Profile 2025.07.09 - 17.20.58.03.mp4" --preset game --with-audio-summary --use-llm-polish
```

可追加参数：
- `--concurrency 4`：提高 phase3 并发度
- `--max-retries 1 --retry-backoff-seconds 2`：控制失败重试策略

说明：`run-all` 会自动顺序执行 phase1 -> phase2-fixed -> phase3-vlm -> phase4-summary。

## 11. 简易 GUI 控制面板

```powershell
.\.venv\Scripts\python -m videosummary.cli gui
```

GUI 功能：
- 选择视频和输出目录
- 选择预设与模型参数
- 配置 HF 镜像、代理、本地模型目录、离线模式
- 一键运行全流程
- 实时查看日志并可手动停止
