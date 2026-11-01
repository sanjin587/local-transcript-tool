"""Local, size-checked audio extraction and GPU-first video compression."""
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
CREATE_FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

class Cancelled(Exception):
    pass

def binaries():
    # Prefer the known working distribution over the System32 entry.
    link = Path.home() / 'AppData/Local/Microsoft/WinGet/Links/ffmpeg.exe'
    encoder = link.resolve() if link.exists() else Path(shutil.which('ffmpeg') or '')
    probe = encoder.with_name('ffprobe.exe')
    if not encoder.is_file() or not probe.is_file():
        raise RuntimeError('未找到完整的本地音视频处理程序。')
    return str(encoder), str(probe)

def inspect(path):
    _, probe = binaries()
    result = subprocess.run([probe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
                            capture_output=True, encoding='utf-8', errors='replace', creationflags=CREATE_FLAGS)
    if result.returncode:
        raise RuntimeError('无法读取文件：' + result.stderr[-2000:])
    data = json.loads(result.stdout)
    duration = float(data.get('format', {}).get('duration', 0))
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError('无法确定文件时长，不能安全计算目标体积。')
    return data, duration

def encode(args, folder, report, cancel, label, duration):
    if cancel.is_set(): raise Cancelled('已停止')
    encoder, _ = binaries()
    with (folder / '处理日志.txt').open('a', encoding='utf-8') as log:
        log.write(json.dumps(args, ensure_ascii=False) + '\n'); log.flush()
        process = subprocess.Popen([encoder, '-hide_banner', '-nostdin', '-y', '-loglevel', 'warning',
                                    '-progress', 'pipe:1', '-stats_period', '2'] + args,
                                   stdout=subprocess.PIPE, stderr=log, encoding='utf-8', errors='replace',
                                   creationflags=CREATE_FLAGS)
        # Polling avoids leaving one waiting thread behind for every successful encode.
        import threading
        done = threading.Event()
        def watch():
            while not done.wait(.2):
                if cancel.is_set():
                    if process.poll() is None: process.terminate()
                    return
        watcher = threading.Thread(target=watch, daemon=True); watcher.start()
        try:
            for line in process.stdout:
                if line.startswith('out_time_us='):
                    try:
                        seconds = int(line.strip().split('=', 1)[1]) / 1e6
                        report(f'{label}：{min(100, seconds / duration * 100):.0f}%')
                    except ValueError: pass
            code = process.wait()
        finally:
            done.set(); process.stdout.close()
            if process.poll() is None: process.terminate(); process.wait()
        if cancel.is_set(): raise Cancelled('已停止，原文件保留。')
        if code: raise RuntimeError('处理失败，详情见：' + str(folder / '处理日志.txt'))

def verify(path, duration, limit, video):
    data, actual_duration = inspect(path)
    types = [s['codec_type'] for s in data['streams']]
    if ('video' if video else 'audio') not in types:
        raise RuntimeError('输出缺少需要的音视频轨道。')
    if abs(actual_duration - duration) > max(1.5, duration * .001):
        raise RuntimeError('输出时长与原文件不符，未标记为完成。')
    return path.stat().st_size <= limit, actual_duration

def compress(source, mode='audio', max_mb=200, report=print, cancel=None, output=None):
    import threading
    cancel = cancel or threading.Event()
    max_mb = float(max_mb)
    if not math.isfinite(max_mb) or not 1 <= max_mb <= 100000:
        raise ValueError('目标大小请输入1至100000之间的数字（MB）。')
    if mode not in ('audio', 'video'): raise ValueError('未知处理模式')
    limit = int(max_mb * 1_000_000)  # Decimal MB: also below an equivalent MiB cap.
    source = Path(source).resolve()
    if not source.is_file(): raise ValueError('请选择本地文件。')
    data, duration = inspect(source)
    audio = any(s['codec_type'] == 'audio' for s in data['streams'])
    videos = [s for s in data['streams'] if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic')]
    if mode == 'audio' and not audio: raise ValueError('这个文件没有音轨。')
    if mode == 'video' and not videos: raise ValueError('这个文件没有视频画面。')
    root = Path(output or BASE / '输出'); root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix=source.stem[:45] + '_压缩_', dir=root))
    manifest = {'source': str(source), 'source_bytes': source.stat().st_size, 'source_duration': duration,
                'mode': mode, 'limit_bytes_per_file': limit, 'status': 'processing', 'outputs': []}
    result_path = folder / '处理结果.json'
    def save(): result_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    report(f'原文件 {source.stat().st_size / 1e6:.1f} MB，时长 {duration / 60:.1f} 分钟；目标每个文件 ≤ {max_mb:g} MB')
    try:
        if mode == 'audio':
            manifest['audio_device'] = 'cpu'
            report('音频处理：CPU（AAC音频编码不支持本工具的GPU加速；无需处理视频画面）。')
            budget = limit * 8 * .90 / duration
            bitrate = min(64000, int(budget / 1000) * 1000)
            # Extremely long sources are split instead of destroying speech quality.
            split = bitrate < 24000
            if split: bitrate = 32000
            chunk = limit * 8 * .88 / bitrate if split else duration
            count = math.ceil(duration / chunk)
            if count > 1: report(f'为保留语音清晰度，将分成 {count} 个音频，每个不超过目标体积。')
            for index in range(count):
                start = index * chunk; length = min(chunk, duration - start)
                final = folder / (f'音频_{index + 1:03}.m4a' if count > 1 else '音频.m4a')
                temp = folder / '处理中.m4a'
                rate = bitrate
                for attempt in range(3):
                    args = ['-ss', str(start), '-i', str(source), '-t', str(length), '-map', '0:a:0',
                            '-vn', '-sn', '-dn', '-map_metadata', '-1', '-map_chapters', '-1',
                            '-c:a', 'aac', '-b:a', str(rate), '-ac', '1', '-ar', '24000',
                            '-movflags', '+faststart', str(temp)]
                    encode(args, folder, report, cancel, f'音频 {index+1}/{count}', length)
                    fits, actual = verify(temp, length, limit, False)
                    if fits: break
                    rate = int(rate * limit / temp.stat().st_size * .88)
                    report('实际体积超出目标，自动调整后重试……')
                else: raise RuntimeError('无法满足目标体积，请增大目标大小。')
                temp.rename(final)
                manifest['outputs'].append({'file': final.name, 'bytes': final.stat().st_size,
                                            'duration': actual, 'source_start': start, 'audio_bitrate': rate})
                save()
        else:
            total_rate = int(limit * 8 * .90 / duration)
            audio_rate = min(64000, max(24000, int(total_rate * .15))) if audio else 0
            video_rate = total_rate - audio_rate
            if video_rate < 30000:
                raise ValueError('目标体积过小，无法保留可用画面。请增大体积或选择提取音频。')
            width = min(1280 if video_rate >= 700000 else 854 if video_rate >= 250000 else 640,
                        int(videos[0]['width']))
            # Scale by orientation to avoid stretching portrait videos.
            height = min(width, int(videos[0]['height']))
            vf = f'scale=w={width}:h={height}:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1'
            from fractions import Fraction
            try: source_fps = float(Fraction(videos[0].get('avg_frame_rate', '30/1')))
            except (ValueError, ZeroDivisionError): source_fps = 30
            fps = min(30, max(1, source_fps or 30))
            temp = folder / '处理中.mp4'; final = folder / '压缩视频.mp4'
            use_gpu = True
            for attempt in range(3):
                common = ['-i', str(source), '-map', f'0:{videos[0]["index"]}', '-vf', vf, '-r', str(fps),
                          '-pix_fmt', 'yuv420p', '-map_metadata', '-1', '-map_chapters', '-1']
                sound = ['-map', '0:a:0', '-c:a', 'aac', '-b:a', str(audio_rate)] if audio else ['-an']
                if use_gpu:
                    report('视频编码：GPU优先（NVIDIA NVENC）；音频、缩放和读取仍由CPU协作。')
                    try:
                        encode(common + ['-c:v', 'h264_nvenc', '-preset', 'p4', '-rc', 'vbr',
                                         '-multipass', 'fullres', '-b:v', str(video_rate),
                                         '-maxrate', str(video_rate * 2), '-bufsize', str(video_rate * 4)]
                               + sound + ['-movflags', '+faststart', str(temp)],
                               folder, report, cancel, 'GPU视频压缩', duration)
                    except Cancelled:
                        raise
                    except RuntimeError as error:
                        use_gpu = False
                        manifest['gpu_fallback_reason'] = str(error)
                        report('GPU编码未能完成，自动改用CPU；详情保存在处理日志。')
                if not use_gpu:
                    cpu = common + ['-c:v', 'libx264', '-preset', 'fast', '-b:v', str(video_rate),
                                    '-passlogfile', str(folder / '编码统计')]
                    encode(cpu + ['-pass', '1', '-an', '-f', 'null', os.devnull],
                           folder, report, cancel, 'CPU视频分析（第一遍）', duration)
                    encode(cpu + ['-pass', '2'] + sound + ['-movflags', '+faststart', str(temp)],
                           folder, report, cancel, 'CPU视频压缩（第二遍）', duration)
                manifest['video_device'] = 'gpu' if use_gpu else 'cpu'
                manifest['video_encoder'] = 'h264_nvenc' if use_gpu else 'libx264'
                manifest['audio_device'] = 'cpu' if audio else None
                save()
                fits, actual = verify(temp, duration, limit, True)
                if fits: break
                video_rate = int(video_rate * limit / temp.stat().st_size * .85)
                report('实际体积超出目标，自动调整后重试……')
            else: raise RuntimeError('无法满足目标体积，请增大目标大小。')
            temp.rename(final)
            manifest['outputs'].append({'file': final.name, 'bytes': final.stat().st_size, 'duration': actual,
                                        'video_bitrate': video_rate})
            for item in folder.glob('编码统计*'): item.unlink()
        manifest['status'] = 'completed'; save()
        for item in manifest['outputs']: report(f'完成：{folder / item["file"]}（{item["bytes"]/1e6:.2f} MB）')
        return folder
    except Exception as error:
        manifest['status'] = 'cancelled' if isinstance(error, Cancelled) else 'failed'
        manifest['error'] = str(error); save()
        raise
