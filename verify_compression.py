"""Integration checks with real locally generated media."""
import hashlib
import json
import subprocess
import threading
from pathlib import Path
from compress import BASE, binaries, compress, inspect, Cancelled

def run():
    folder = BASE / '压缩验收'; folder.mkdir(exist_ok=True)
    encoder, _ = binaries()
    source = folder / '测试视频20秒.mp4'
    subprocess.run([encoder, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=25',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=24000', '-t', '20', '-c:v', 'libx264',
                    '-crf', '12', '-c:a', 'aac', str(source)], check=True)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    results = []
    for mode in ('audio', 'video'):
        target = compress(source, mode, 1, output=folder, report=lambda msg: None)
        manifest = json.loads((target / '处理结果.json').read_text(encoding='utf-8'))
        assert manifest['status'] == 'completed'
        for item in manifest['outputs']:
            path = target / item['file']
            assert path.stat().st_size <= 1_000_000
            subprocess.run([encoder, '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'], check=True)
        results.append(manifest)
    long_audio = folder / '分段测试400秒.wav'
    subprocess.run([encoder, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=24000',
                    '-t', '400', str(long_audio)], check=True)
    target = compress(long_audio, 'audio', 1, output=folder, report=lambda msg: None)
    manifest = json.loads((target / '处理结果.json').read_text(encoding='utf-8'))
    assert len(manifest['outputs']) == 2
    assert abs(sum(item['duration'] for item in manifest['outputs']) - 400) < 1
    for item in manifest['outputs']:
        assert item['bytes'] <= 1_000_000
        subprocess.run([encoder, '-v', 'error', '-xerror', '-i', str(target / item['file']), '-f', 'null', '-'], check=True)
    results.append(manifest)
    stop = threading.Event(); stop.set()
    try: compress(source, 'video', 1, output=folder, cancel=stop, report=lambda msg: None)
    except Cancelled: pass
    else: raise AssertionError('Cancellation did not stop processing')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    # A silent video remains silent; audio extraction must explain the missing track.
    silent = folder / '无声视频.mp4'
    subprocess.run([encoder, '-v', 'error', '-y', '-i', str(source), '-an', '-c:v', 'copy', str(silent)], check=True)
    target = compress(silent, 'video', 1, output=folder, report=lambda msg: None)
    assert not any(s['codec_type'] == 'audio' for s in inspect(target / '压缩视频.mp4')[0]['streams'])
    try: compress(silent, 'audio', 1, output=folder, report=lambda msg: None)
    except ValueError as error: assert '没有音轨' in str(error)
    else: raise AssertionError('Missing audio was not detected')
    (folder / '验收报告.json').write_text(json.dumps({'status': 'passed', 'original_hash_unchanged': True,
        'checks': ['audio', 'two_pass_video', 'split_audio', 'full_decode', 'duration', 'size', 'cancel', 'silent_video'],
        'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS', source.stat().st_size, [(r['mode'], [o['bytes'] for o in r['outputs']]) for r in results])

if __name__ == '__main__': run()
