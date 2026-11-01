import os
import sys
import json
import queue
import re
import threading
import traceback
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES, COPY, REFUSE_DROP
from compress import compress, Cancelled

MEDIA_EXTENSIONS = {'.mp4', '.mkv', '.mov', '.avi', '.webm', '.m4v', '.mp3', '.wav', '.m4a', '.aac', '.flac'}
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

def transcribe(source, quality='medium', output=None, report=print, device=None, cancel=None, progress=None):
    progress = progress or (lambda value, status: None)
    if cancel and cancel.is_set(): raise Cancelled("已停止转写")
    from faster_whisper import WhisperModel
    import ctranslate2
    candidates = list((CACHE / f'models--Systran--faster-whisper-{quality}' / 'snapshots').glob('*/model.bin'))
    if not candidates:
        raise RuntimeError('本地模型不存在：' + quality + '。请先运行 python download_models.py ' + quality)
    if device not in (None, 'cpu', 'cuda'): raise ValueError('未知转写设备')
    if device != 'cpu':
        try:
            device = 'cuda' if ctranslate2.get_cuda_device_count() else 'cpu'
        except Exception:
            device = 'cpu'
    if device == 'cpu': report('本次转写使用 CPU。')
    progress(None, f'加载模型 · {device.upper()}')
    report(f'加载本地 {quality} 模型，使用 {device}……')
    def load(selected):
        return WhisperModel(str(candidates[0].parent), device=selected,
                            compute_type='int8_float16' if selected == 'cuda' else 'int8', local_files_only=True)
    try:
        model = load(device)
    except Exception:
        if device != 'cuda': raise
        report('显卡模型加载失败，自动改用 CPU。')
        device = 'cpu'
        progress(None, '显卡不可用，加载 CPU 模型')
        model = load(device)
    if cancel and cancel.is_set(): raise Cancelled('已停止转写')
    source = Path(source).resolve()
    root = Path(output or BASE / '输出')
    root.mkdir(parents=True, exist_ok=True)
    import tempfile
    target = Path(tempfile.mkdtemp(prefix=source.stem[:60] + '_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_', dir=root))
    progress(None, f'读取音频 · {device.upper()}')
    segments, info = model.transcribe(str(source), language='zh', vad_filter=True, beam_size=5)
    progress(0, f'正在识别 · {device.upper()}')
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
            progress(min(99, seg.end / info.duration * 100) if info.duration > 0 else 0,
                     f'{device.upper()} · {stamp(seg.end)} / {stamp(info.duration)}')
    if cancel and cancel.is_set(): raise Cancelled('已停止转写，部分结果保留。')
    manifest = {'source': str(source), 'source_bytes': source.stat().st_size,
                'duration_seconds': info.duration, 'model': quality, 'device': device,
                'status': 'completed', 'human_reviewed': False, 'segments': rows}
    (target / '识别结果.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    progress(100, '已完成')
    report(f'完成：{target}（{len(rows)} 个片段）')
    return target

class App:
    def __init__(self):
        self.root = TkinterDnD.Tk(); self.dnd_enabled = True; self.root.title('本地视频工具：压缩 / 音频 / 逐字稿'); self.root.geometry('980x780'); self.root.minsize(820, 650)
        self.events = queue.Queue(); self.files = []; self.cancel = threading.Event(); self.busy = False
        self.file_progress = []
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.bind('<Destroy>', self.on_destroy)
        ttk.Label(self.root, text='本地视频工具：提取音频、压缩视频、生成逐字稿', font=('Microsoft YaHei', 15)).pack(pady=15)
        ttk.Label(self.root, text='无需上传 · 不消耗对话 token · 另存结果，保留原文件').pack()
        ttk.Label(self.root, text='转写设备可选；视频编码优先 NVIDIA 显卡，音频编码使用 CPU。').pack()
        options = ttk.Frame(self.root); options.pack(pady=10)
        ttk.Label(options, text='功能：').pack(side='left')
        self.mode = tk.StringVar(value='生成逐字稿')
        self.mode_combo = ttk.Combobox(options, textvariable=self.mode, values=['提取小体积音频', '压缩视频', '生成逐字稿'], state='readonly', width=20)
        self.mode_combo.pack(side='left', padx=5)
        ttk.Label(options, text='每个文件最大 MB：').pack(side='left')
        self.max_mb = tk.StringVar(value='200'); self.size_entry = ttk.Entry(options, textvariable=self.max_mb, width=8); self.size_entry.pack(side='left', padx=5)
        device_row = ttk.Frame(self.root); device_row.pack(pady=4)
        ttk.Label(device_row, text='逐字稿转写设备：').pack(side='left')
        self.device = tk.StringVar(value='优先显卡')
        self.device_combo = ttk.Combobox(device_row, textvariable=self.device,
            values=['优先显卡', '优先 CPU'], state='readonly', width=16)
        self.device_combo.pack(side='left', padx=5)
        ttk.Label(device_row, text='显卡不可用时自动改用 CPU；仅影响逐字稿').pack(side='left')
        bar = ttk.Frame(self.root); bar.pack(pady=15)
        self.choose = ttk.Button(bar, text='选择视频 / 音频（可多选）', command=self.select); self.choose.pack(side='left', padx=5)
        self.quality = tk.StringVar(value='medium')
        self.combo = ttk.Combobox(bar, textvariable=self.quality, values=['medium', 'small', 'base'], state='readonly', width=9); self.combo.pack(side='left', padx=5)
        self.run = ttk.Button(bar, text='开始处理', command=self.start); self.run.pack(side='left', padx=5)
        self.stop = ttk.Button(bar, text='停止', command=self.cancel.set, state='disabled'); self.stop.pack(side='left', padx=5)
        ttk.Button(bar, text='打开输出文件夹', command=self.open_output).pack(side='left', padx=5)
        output_row = ttk.Frame(self.root); output_row.pack(fill='x', padx=15, pady=(0, 8))
        ttk.Label(output_row, text='输出文件夹：').pack(side='left')
        self.output_dir = tk.StringVar(value=str(BASE / '输出'))
        self.output_entry = ttk.Entry(output_row, textvariable=self.output_dir)
        self.output_entry.pack(side='left', fill='x', expand=True, padx=6)
        self.output_choose = ttk.Button(output_row, text='选择文件夹…', command=self.select_output)
        self.output_choose.pack(side='left')
        ttk.Label(self.root, text='音频适合口播保存；超长音频自动分段。压缩视频保留完整时长，目标越小，画质越低。').pack()
        ttk.Label(self.root, text='逐字稿模型：medium 优先质量 / small 优先速度 / base 粗稿；MB设置仅用于音频和视频压缩。').pack()
        self.drop_zone = ttk.Label(self.root,
            text='将视频 / 音频拖到这里添加（支持多个文件） · 本地处理，无需上传',
            anchor='center', padding=12, relief='groove')
        self.drop_zone.pack(fill='x', padx=15, pady=(8, 2))
        self.batch_status = tk.StringVar(value='请选择文件，每个文件的进度将在下方显示')
        ttk.Label(self.root, textvariable=self.batch_status).pack(anchor='w', padx=15, pady=(10, 3))
        progress_frame = ttk.Frame(self.root); progress_frame.pack(fill='x', padx=15)
        self.progress_canvas = tk.Canvas(progress_frame, height=280, highlightthickness=0)
        scroll = ttk.Scrollbar(progress_frame, orient='vertical', command=self.progress_canvas.yview)
        self.progress_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); self.progress_canvas.pack(side='left', fill='x', expand=True)
        self.progress_canvas.bind('<MouseWheel>', self.scroll_files)
        self.progress_rows = ttk.Frame(self.progress_canvas)
        window = self.progress_canvas.create_window((0, 0), window=self.progress_rows, anchor='nw')
        self.progress_rows.bind('<Configure>', lambda e: self.progress_canvas.configure(scrollregion=self.progress_canvas.bbox('all')))
        self.progress_canvas.bind('<Configure>', lambda e: self.progress_canvas.itemconfigure(window, width=e.width))
        self.log = tk.Text(self.root, wrap='word', height=8); self.log.pack(fill='both', expand=True, padx=15, pady=15)
        for target in (self.root, self.drop_zone, self.progress_canvas):
            target.drop_target_register(DND_FILES)
            target.dnd_bind('<<Drop>>', self.on_drop)
        self.poll_job = self.root.after(200, self.poll)
    def on_drop(self, event):
        if self.busy:
            self.events.put('正在处理，请等本批完成或停止后再拖入文件。')
            return REFUSE_DROP
        try:
            paths = self.root.tk.splitlist(event.data)
        except tk.TclError:
            self.events.put('无法读取拖入的文件，请使用“选择视频 / 音频”。')
            return REFUSE_DROP
        known = {os.path.normcase(str(Path(file).resolve())) for file in self.files}
        added = []; rejected = 0
        for raw in paths:
            try:
                path = Path(raw).resolve()
                if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
                    rejected += 1
                    continue
            except (OSError, ValueError):
                rejected += 1
                continue
            key = os.path.normcase(str(path))
            if key not in known:
                known.add(key); added.append(str(path))
        if added:
            self.files.extend(added)
            self.show_files()
            self.events.put(f'拖拽添加 {len(added)} 个文件，当前共 {len(self.files)} 个。')
        elif not rejected:
            self.events.put('拖入的文件已在列表中，无需重复添加。')
        if rejected:
            self.events.put(f'已忽略 {rejected} 项：仅支持本地视频和音频文件，不支持文件夹。')
        return COPY if added or (paths and not rejected) else REFUSE_DROP
    def select_output(self):
        if self.busy: return
        folder = filedialog.askdirectory(title='选择输出文件夹', parent=self.root)
        if folder: self.output_dir.set(folder)
    def prepare_output(self):
        raw = self.output_dir.get().strip()
        if not raw: raise ValueError('请选择输出文件夹。')
        folder = Path(raw).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        # Confirm write access before starting a potentially long batch.
        import tempfile
        with tempfile.TemporaryFile(dir=folder): pass
        return folder
    def open_output(self):
        try:
            os.startfile(self.prepare_output())
        except (OSError, ValueError) as error:
            self.events.put('无法打开输出文件夹：' + str(error))
    def scroll_files(self, event):
        if event.delta:
            self.progress_canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        return 'break'
    def show_files(self):
        for row in self.file_progress: row['bar'].stop()
        for child in self.progress_rows.winfo_children(): child.destroy()
        self.file_progress = []
        for index, file in enumerate(self.files):
            row = ttk.Frame(self.progress_rows); row.pack(fill='x', pady=5, padx=3)
            row.columnconfigure(0, weight=1)
            name = ttk.Label(row, text=f'{index + 1}. {Path(file).name}', width=1, anchor='w')
            name.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 4))
            row.bind('<Configure>', lambda e, label=name: label.configure(wraplength=max(100, e.width - 8)))
            bar = ttk.Progressbar(row, maximum=100, mode='determinate', length=200)
            bar.grid(row=1, column=0, sticky='ew')
            status = tk.StringVar(value='等待中')
            status_label = ttk.Label(row, textvariable=status, width=36, anchor='w')
            status_label.grid(row=1, column=1, padx=(12, 0), sticky='w')
            for widget in (row, name, bar, status_label):
                widget.bind('<MouseWheel>', self.scroll_files)
            self.file_progress.append({'bar': bar, 'status': status, 'value': 0})
        self.batch_status.set(f'共 {len(self.files)} 个文件 · 顺序处理')
        self.progress_canvas.yview_moveto(0)
    def apply_progress(self, index, value, status):
        row = self.file_progress[index]
        bar = row['bar']; bar.stop()
        terminal = status in ('失败', '已停止', '未开始（已停止）')
        if value is None and not terminal:
            bar.configure(mode='indeterminate'); bar.start(15)
            row['status'].set(status)
        else:
            if value is not None: row['value'] = max(0, min(100, value))
            bar.configure(mode='determinate', value=row['value'])
            row['status'].set(status if terminal else f"{row['value']:.0f}% · {status}")
    def select(self):
        files = list(filedialog.askopenfilenames(filetypes=[('视频和音频', '*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.mp3 *.wav *.m4a *.aac *.flac'), ('所有文件', '*.*')]))
        if files:
            self.files = files
            self.show_files()
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
        try:
            output = self.prepare_output()
        except (OSError, ValueError) as error:
            self.events.put('输出文件夹不可用：' + str(error)); return
        device = 'cpu' if self.device.get() == '优先 CPU' else 'cuda'
        self.show_files()
        self.cancel.clear(); self.busy = True
        self.output_entry.config(state='disabled'); self.output_choose.config(state='disabled')
        self.device_combo.config(state='disabled')
        self.run.config(state='disabled'); self.choose.config(state='disabled'); self.combo.config(state='disabled')
        self.mode_combo.config(state='disabled'); self.size_entry.config(state='disabled'); self.stop.config(state='normal')
        def work():
            completed = failed = 0
            for index, file in enumerate(files):
                if self.cancel.is_set():
                    for remaining in range(index, len(files)):
                        self.events.put(('progress', remaining, None, '未开始（已停止）'))
                    break
                self.events.put(('batch', f'正在处理 {index + 1}/{len(files)} · 成功 {completed} · 失败 {failed}'))
                def progress(value, status):
                    self.events.put(('progress', index, value, status))
                def report(message):
                    self.events.put(message)
                    if mode != '生成逐字稿':
                        match = re.search(r'(.+)：(\d+)%$', message)
                        if match:
                            progress(min(99, int(match.group(2))), match.group(1))
                        elif message.startswith(('GPU编码未能', '视频编码：', '音频处理：', '实际体积超出')):
                            progress(None, message.split('；')[0])
                try:
                    progress(None, '准备处理')
                    report('开始：' + file)
                    if mode == '生成逐字稿':
                        transcribe(file, quality, report=report, device=device,
                                   cancel=self.cancel, progress=progress, output=output)
                    else:
                        compress(file, 'audio' if mode == '提取小体积音频' else 'video', limit,
                                 report=report, cancel=self.cancel, output=output)
                    progress(100, '已完成')
                    completed += 1
                except Cancelled as error:
                    progress(None, '已停止')
                    report(str(error))
                    for remaining in range(index + 1, len(files)):
                        self.events.put(('progress', remaining, None, '未开始（已停止）'))
                    break
                except Exception:
                    failed += 1
                    progress(None, '失败')
                    error = traceback.format_exc()
                    report('处理失败，已保留原文件和部分输出；详情：\n' + error)
                    with (BASE / '错误日志.txt').open('a', encoding='utf-8') as f: f.write(error + '\n')
            title = '已停止' if self.cancel.is_set() else '处理结束'
            self.events.put(('batch', f'{title} · 成功 {completed} · 失败 {failed} · 未完成 {len(files) - completed - failed}'))
            self.events.put(None)
        threading.Thread(target=work, daemon=True).start()
    def poll(self):
        try:
            while True:
                msg = self.events.get_nowait()
                if msg is None:
                    self.busy = False
                    self.output_entry.config(state='normal'); self.output_choose.config(state='normal')
                    self.device_combo.config(state='readonly')
                    self.run.config(state='normal'); self.choose.config(state='normal'); self.combo.config(state='readonly')
                    self.mode_combo.config(state='readonly'); self.size_entry.config(state='normal'); self.stop.config(state='disabled')
                elif isinstance(msg, tuple):
                    if msg[0] == 'progress': self.apply_progress(*msg[1:])
                    elif msg[0] == 'batch': self.batch_status.set(msg[1])
                else:
                    self.log.insert('end', msg + '\n'); self.log.see('end')
        except queue.Empty: pass
        self.poll_job = self.root.after(200, self.poll)
    def on_destroy(self, event):
        if event.widget == self.root and hasattr(self, 'poll_job'):
            self.root.after_cancel(self.poll_job)
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
