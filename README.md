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

可选参数：
- `--language zh`：固定中文识别（不填则自动检测）
- `--model tiny|base|small|medium|large-v3`：模型大小与成本/精度可权衡
- `--device cpu|cuda|auto`：运行设备

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
- `--without-image`：仅发送文本上下文用于对照实验
- `--max-items N`：只跑前 N 条，便于快速调试
- `--temperature 0.2`：采样温度
- `--timeout-seconds 120`

输出目录（默认）：`outputs/<视频名>/phase2_fixed/phase3_vlm/`

主要产物：
- `visual_analysis.jsonl`：每帧的视觉分析结果
- `phase3_vlm_manifest.json`：调用统计（成功/失败）
