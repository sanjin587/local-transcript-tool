import os
import sys
import json
import queue
import threading
import traceback
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from compress import compress, Cancelled

BASE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get('TRANSCRIPT_MODEL_CACHE', str(BASE / 'models' / 'hub'))).expanduser()
DLL_HANDLES = []
for folder in (Path(sys.prefix) / 'Lib/site-packages/nvidia').glob('*/bin'):
    os.environ['PATH'] = str(folder) + os.pathsep + os.environ.get('PATH', '')
    if hasattr(os, 'add_dll_directory'):
        DLL_HANDLES.append(os.add_dll_directory(str(folder)))

def stamp(seconds, srt=False):
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02}{"," if srt else "."}{ms:03}'

def transcribe(source, quality='medium', output=None, report=print, device=None, cancel=None):
    from faster_whisper import WhisperModel
    import ctranslate2
    candidates = list((CACHE / f'models--Systran--faster-whisper-{quality}' / 'snapshots').glob('*/model.bin'))
    if not candidates:
        raise RuntimeError('本地模型不存在：' + quality + '。请先运行 python download_models.py ' + quality)
    device = device or ('cuda' if ctranslate2.get_cuda_device_count() else 'cpu')
    if device == 'cpu': report('没有检测到可用GPU，本次转写使用CPU。')
    report(f'加载本地 {quality} 模型，使用 {device}……')
    model = WhisperModel(str(candidates[0].parent), device=device,
                         compute_type='int8_float16' if device == 'cuda' else 'int8', local_files_only=True)
    source = Path(source).resolve()
    root = Path(output or BASE / '输出')
    root.mkdir(parents=True, exist_ok=True)
    import tempfile
    target = Path(tempfile.mkdtemp(prefix=source.stem[:60] + '_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_', dir=root))
    segments, info = model.transcribe(str(source), language='zh', vad_filter=True, beam_size=5)
    rows = []
    with (target / '纯文字.txt').open('w', encoding='utf-8') as plain, \
         (target / '带时间戳逐字稿.txt').open('w', encoding='utf-8') as timed, \
         (target / '字幕.srt').open('w', encoding='utf-8') as srt, \
         (target / '识别片段.jsonl').open('w', encoding='utf-8') as live:
        timed.write('机器识别，未经人工校对\n原文件：' + str(source) + '\n\n')
        for i, seg in enumerate(segments, 1):
            if cancel and cancel.is_set(): raise Cancelled('已停止转写，部分结果保留。')
            row = {'start': seg.start, 'end': seg.end, 'text': seg.text.strip()}
            rows.append(row)
            plain.write(row['text'] + '\n'); plain.flush()
            timed.write(f'[{stamp(seg.start)} → {stamp(seg.end)}] {row["text"]}\n'); timed.flush()
            srt.write(f'{i}\n{stamp(seg.start, True)} --> {stamp(seg.end, True)}\n{row["text"]}\n\n'); srt.flush()
            live.write(json.dumps(row, ensure_ascii=False) + '\n'); live.flush()
            report(f'已识别 {stamp(seg.end)} / 总时长 {stamp(info.duration)}')
    manifest = {'source': str(source), 'source_bytes': source.stat().st_size,
                'duration_seconds': info.duration, 'model': quality, 'device': device,
                'status': 'completed', 'human_reviewed': False, 'segments': rows}
    (target / '识别结果.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    report(f'完成：{target}（{len(rows)} 个片段）')
    return target

class App:
    def __init__(self):
        self.root = tk.Tk(); self.root.title('本地视频工具：压缩 / 音频 / 逐字稿'); self.root.geometry('880x620')
        self.events = queue.Queue(); self.files = []; self.cancel = threading.Event(); self.busy = False
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        ttk.Label(self.root, text='本地视频工具：提取音频、压缩视频、生成逐字稿', font=('Microsoft YaHei', 15)).pack(pady=15)
        ttk.Label(self.root, text='无需上传 · 不消耗对话 token · 另存结果，保留原文件').pack()
        ttk.Label(self.root, text='默认GPU优先：逐字稿和视频编码；音频编码使用CPU。GPU不可用时会提示。').pack()
        options = ttk.Frame(self.root); options.pack(pady=10)
        ttk.Label(options, text='功能：').pack(side='left')
        self.mode = tk.StringVar(value='提取小体积音频')
        self.mode_combo = ttk.Combobox(options, textvariable=self.mode, values=['提取小体积音频', '压缩视频', '生成逐字稿'], state='readonly', width=20)
        self.mode_combo.pack(side='left', padx=5)
        ttk.Label(options, text='每个文件最大 MB：').pack(side='left')
        self.max_mb = tk.StringVar(value='200'); self.size_entry = ttk.Entry(options, textvariable=self.max_mb, width=8); self.size_entry.pack(side='left', padx=5)
        bar = ttk.Frame(self.root); bar.pack(pady=15)
        self.choose = ttk.Button(bar, text='选择视频 / 音频（可多选）', command=self.select); self.choose.pack(side='left', padx=5)
        self.quality = tk.StringVar(value='medium')
        self.combo = ttk.Combobox(bar, textvariable=self.quality, values=['medium', 'small', 'base'], state='readonly', width=9); self.combo.pack(side='left', padx=5)
        self.run = ttk.Button(bar, text='开始处理', command=self.start); self.run.pack(side='left', padx=5)
        self.stop = ttk.Button(bar, text='停止', command=self.cancel.set, state='disabled'); self.stop.pack(side='left', padx=5)
        ttk.Button(bar, text='打开输出文件夹', command=self.open_output).pack(side='left', padx=5)
        ttk.Label(self.root, text='音频适合口播保存；超长音频自动分段。压缩视频保留完整时长，目标越小，画质越低。').pack()
        ttk.Label(self.root, text='逐字稿模型：medium 优先质量 / small 优先速度 / base 粗稿；MB设置仅用于音频和视频压缩。').pack()
        self.log = tk.Text(self.root, wrap='word', height=20); self.log.pack(fill='both', expand=True, padx=15, pady=15)
        self.root.after(200, self.poll)
    def open_output(self):
        folder = BASE / '输出'; folder.mkdir(exist_ok=True); os.startfile(folder)
    def select(self):
        self.files = list(filedialog.askopenfilenames(filetypes=[('视频和音频', '*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.mp3 *.wav *.m4a *.aac *.flac'), ('所有文件', '*.*')]))
        self.events.put('已选择：\n' + '\n'.join(self.files))
    def start(self):
        if not self.files:
            self.events.put('请先选择文件。'); return
        files = self.files.copy(); quality = self.quality.get(); mode = self.mode.get()
        try:
            limit = 200 if mode == '生成逐字稿' else float(self.max_mb.get())
            import math
            if mode != '生成逐字稿' and (not math.isfinite(limit) or not 1 <= limit <= 100000): raise ValueError()
        except ValueError:
            self.events.put('最大体积请输入1至100000之间的数字。'); return
        self.cancel.clear(); self.busy = True
        self.run.config(state='disabled'); self.choose.config(state='disabled'); self.combo.config(state='disabled')
        self.mode_combo.config(state='disabled'); self.size_entry.config(state='disabled'); self.stop.config(state='normal')
        def work():
            for file in files:
                if self.cancel.is_set(): break
                try:
                    self.events.put('开始：' + file)
                    if mode == '生成逐字稿':
                        transcribe(file, quality, report=self.events.put, cancel=self.cancel)
                    else:
                        compress(file, 'audio' if mode == '提取小体积音频' else 'video', limit, report=self.events.put, cancel=self.cancel)
                except Cancelled as error:
                    self.events.put(str(error)); break
                except Exception:
                    error = traceback.format_exc()
                    self.events.put('处理失败，已保留原文件和部分输出；详情：\n' + error)
                    with (BASE / '错误日志.txt').open('a', encoding='utf-8') as f: f.write(error + '\n')
            self.events.put(None)
        threading.Thread(target=work, daemon=True).start()
    def poll(self):
        try:
            while True:
                msg = self.events.get_nowait()
                if msg is None:
                    self.busy = False
                    self.run.config(state='normal'); self.choose.config(state='normal'); self.combo.config(state='readonly')
                    self.mode_combo.config(state='readonly'); self.size_entry.config(state='normal'); self.stop.config(state='disabled')
                else:
                    self.log.insert('end', msg + '\n'); self.log.see('end')
        except queue.Empty: pass
        self.root.after(200, self.poll)
    def close(self):
        if self.busy:
            if messagebox.askyesno('正在处理', '停止当前任务？部分结果会保留。停止完成后可关闭窗口。'):
                self.cancel.set()
        else:
            self.root.destroy()
    def main(self): self.root.mainloop()

if __name__ == '__main__':
    if len(sys.argv) > 1:
        transcribe(sys.argv[1], quality=sys.argv[2] if len(sys.argv) > 2 else 'medium')
    else:
        App().main()
