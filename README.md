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
