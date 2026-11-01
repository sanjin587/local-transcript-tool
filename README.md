# 本地逐字稿转换工具

Windows 桌面工具，将本地视频或音频转换为中文逐字稿，也支持音频提取和视频压缩。Python + Tkinter 界面，使用 faster-whisper 和 FFmpeg。

## 功能

- 批量中文转写：纯文字 TXT、带时间戳 TXT、SRT、JSON 和增量 JSONL。
- medium / small / base 模型；检测到 NVIDIA CUDA 时优先 GPU，否则使用 CPU。
- 提取单声道 M4A，超长音频自动分段并检查每个文件大小。
- 压缩 MP4：优先 NVENC，失败时回退 CPU 两遍编码，检查体积与时长。
- 另存结果，保留原文件；支持停止处理。

## 安装（Windows / Python 3.12）

先安装 Python（包含 Tkinter）和完整的 FFmpeg，确保 `ffmpeg`、`ffprobe` 可在命令行使用。也支持 WinGet 的 FFmpeg 快捷链接。

```powershell
git clone https://github.com/sanjin587/local-transcript-tool.git
cd local-transcript-tool
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe download_models.py medium
.\.venv\Scripts\python.exe app.py
```

首次下载模型需要联网且有足够磁盘空间。模型默认放在仓库下 `models/hub`，不随代码发布。设置环境变量 `TRANSCRIPT_MODEL_CACHE` 可指向已有 Hugging Face hub 缓存，格式为 `models--Systran--faster-whisper-medium/snapshots/<版本>/model.bin`。

```powershell
$env:TRANSCRIPT_MODEL_CACHE = 'E:\AI-Models\hub'
```

CPU 无需安装 CUDA；GPU 转写需安装与 CTranslate2 匹配的 NVIDIA 驱动、CUDA 12 和 cuDNN 9。GPU 库加载失败时会报告错误，当前仅在未检测到 GPU 时自动选择 CPU。依赖说明见 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)。

## 使用

双击 `打开逐字稿工具.cmd` 或运行 `python app.py`。选择“生成逐字稿”，选择音视频后点击“开始处理”。默认功能是“提取小体积音频”，请按需切换。结果保存在工具目录的 `输出` 文件夹。

命令行转写：

```powershell
.\.venv\Scripts\python.exe app.py "E:\Media\example.mp4" medium
```

转写只读取本地模型，不上传媒体，不调用云端模型 API。下载脚本需要联网。结果中包含输入文件的本地路径；分享生成结果前请自行检查。压缩按十进制 MB 限制每个输出文件；视频只保留主画面和第一条音轨，不保留独立字幕轨、额外音轨和章节。

## 验证与限制

```powershell
.\.venv\Scripts\python.exe verify_compression.py
```

验收脚本生成合成媒体，检查音频、视频、长音频分段、大小、时长、完整解码、取消、无声视频和原文件哈希。验收文件仅保存在本地，不提交仓库。

机器识别未经人工校对，可能错识人名、数字、口音与重叠讲话；当前仅识别中文，不区分说话人，不支持断点续写。停止转写需等待当前片段返回。只有 `识别结果.json` 中 `status=completed` 才代表转写完整执行。数 GB / 数小时媒体未作完整验收，音画质量需自行确认。本项目提供源码，不包含独立安装包、模型、FFmpeg 或 CUDA。

## 开源许可

原创工具代码以 [MIT](LICENSE) 许可发布。faster-whisper、模型、FFmpeg 及其他依赖各自遵循上游许可，并不由本项目的 MIT 许可覆盖。
