# 本地逐字稿转换工具

Windows 桌面工具，将本地视频或音频转换为中文逐字稿，也支持音频提取和视频压缩。Python + Tkinter 界面，使用 faster-whisper 和 FFmpeg。

## 功能

- 拖拽导入多个本地视频或音频，追加到列表并自动去重。
- 批量中文转写：纯文字 TXT、带时间戳 TXT、SRT、JSON 和增量 JSONL。
- medium / small / base 模型；界面可选“优先显卡”或“优先 CPU”；显卡检测或模型加载失败时自动回退 CPU。
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

CPU 无需安装 CUDA；GPU 转写需安装与 CTranslate2 匹配的 NVIDIA 驱动、CUDA 12 和 cuDNN 9。显卡模型加载失败时自动改用 CPU；推理过程中的其他错误仍会报告失败。依赖说明见 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)。

## 使用

双击 `打开逐字稿工具.cmd` 或运行 `python app.py`。选择“生成逐字稿”，选择音视频后点击“开始处理”。默认功能是“生成逐字稿”，请按需切换。结果保存在工具目录的 `输出` 文件夹。

可将多个文件从资源管理器拖到窗口内的拖拽区域，追加到当前列表；支持中文、空格路径，自动忽略重复文件、文件夹和不支持的格式。处理期间不能新增文件，需等待结束或停止后再添加。也可继续用选择按钮重新选择整批文件。Windows 下请用普通权限启动工具，资源管理器不能向以管理员权限运行的窗口拖入文件。

所有选中文件会显示在可滚动列表中，每个文件独立显示进度条和状态。批量顺序处理；转写进度按已返回片段在原音频中的位置估算，加载模型与读取音频时显示等待动画，最后写出结果后才显示 100%。压缩显示当前编码阶段进度，CPU 两遍编码、分段或重试时会重新计进度。停止和失败不会显示为完成。

命令行转写：

```powershell
.\.venv\Scripts\python.exe app.py "E:\Media\example.mp4" medium
```

转写只读取本地模型，不上传媒体，不调用云端模型 API。下载脚本需要联网。结果中包含输入文件的本地路径；分享生成结果前请自行检查。压缩按十进制 MB 限制每个输出文件；视频只保留主画面和第一条音轨，不保留独立字幕轨、额外音轨和章节。

## 验证与限制

运行 `python -m unittest test_progress test_drop -v` 检查逐文件界面进度、设备选择、显卡加载失败回退，以及批量失败和取消状态。设备测试使用模拟模型；不替代真实模型推理验收。

```powershell
.\.venv\Scripts\python.exe verify_compression.py
```

验收脚本生成合成媒体，检查音频、视频、长音频分段、大小、时长、完整解码、取消、无声视频和原文件哈希。验收文件仅保存在本地，不提交仓库。

机器识别未经人工校对，可能错识人名、数字、口音与重叠讲话；当前仅识别中文，不区分说话人，不支持断点续写。停止转写需等待当前片段返回。只有 `识别结果.json` 中 `status=completed` 才代表转写完整执行。数 GB / 数小时媒体未作完整验收，音画质量需自行确认。本项目提供源码，不包含独立安装包、模型、FFmpeg 或 CUDA。

拖拽功能使用 [tkinterdnd2](https://github.com/Eliav2/tkinterdnd2)，安装依赖后即可使用。

## 开源许可

原创工具代码以 [MIT](LICENSE) 许可发布。faster-whisper、模型、FFmpeg 及其他依赖各自遵循上游许可，并不由本项目的 MIT 许可覆盖。
