import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import app

class ProgressTests(unittest.TestCase):
    def test_per_file_status_and_progress(self):
        ui = app.App()
        try:
            ui.files = ['first.mp4', 'second.mp4', 'third.mp4']
            ui.show_files()
            self.assertEqual(len(ui.file_progress), 3)
            ui.apply_progress(0, 42, '正在识别')
            self.assertEqual(float(ui.file_progress[0]['bar']['value']), 42)
            self.assertEqual(float(ui.file_progress[1]['bar']['value']), 0)
            ui.apply_progress(0, 100, '已完成')
            ui.apply_progress(1, 30, '失败')
            ui.apply_progress(2, None, '加载模型')
            ui.apply_progress(2, None, '已停止')
            self.assertEqual(float(ui.file_progress[0]['bar']['value']), 100)
            self.assertLess(float(ui.file_progress[1]['bar']['value']), 100)
            self.assertEqual(str(ui.file_progress[2]['bar']['mode']), 'determinate')
        finally:
            ui.root.destroy()

    def test_batch_failure_continues_and_cancel_marks_waiting(self):
        import time
        ui = app.App()
        ui.root.withdraw()
        try:
            ui.files = ['first.mp4', 'second.mp4', 'third.mp4']
            def process(source, *args, **kwargs):
                kwargs['progress'](45, '正在识别')
                if source == 'second.mp4': raise RuntimeError('test failure')
            with patch.object(app, 'transcribe', side_effect=process):
                ui.start()
                deadline = time.monotonic() + 5
                while ui.busy and time.monotonic() < deadline:
                    ui.root.update(); time.sleep(.01)
            self.assertFalse(ui.busy)
            self.assertIn('已完成', ui.file_progress[0]['status'].get())
            self.assertEqual(ui.file_progress[1]['status'].get(), '失败')
            self.assertIn('已完成', ui.file_progress[2]['status'].get())
            self.assertIn('成功 2', ui.batch_status.get())
            def cancel(source, *args, **kwargs):
                ui.cancel.set()
                raise app.Cancelled('stopped')
            with patch.object(app, 'transcribe', side_effect=cancel):
                ui.start()
                deadline = time.monotonic() + 5
                while ui.busy and time.monotonic() < deadline:
                    ui.root.update(); time.sleep(.01)
            self.assertFalse(ui.busy)
            self.assertEqual(ui.file_progress[0]['status'].get(), '已停止')
            self.assertEqual(ui.file_progress[1]['status'].get(), '未开始（已停止）')
            self.assertEqual(ui.file_progress[2]['status'].get(), '未开始（已停止）')
        finally:
            ui.root.destroy()

    def test_cpu_selection_and_gpu_fallback(self):
        import sys
        with tempfile.TemporaryDirectory(dir=app.BASE) as folder:
            cache = Path(folder)
            model = cache / 'models--Systran--faster-whisper-base' / 'snapshots' / 'test'
            model.mkdir(parents=True)
            (model / 'model.bin').touch()
            source = cache / 'sample.wav'
            source.touch()
            calls = []
            def factory(*args, **kwargs):
                calls.append(kwargs['device'])
                if kwargs['device'] == 'cuda':
                    raise RuntimeError('CUDA unavailable')
                return SimpleNamespace(transcribe=lambda *a, **k: (iter([SimpleNamespace(start=0, end=5, text='测试')]), SimpleNamespace(duration=10)))
            modules = {'faster_whisper': SimpleNamespace(WhisperModel=factory),
                       'ctranslate2': SimpleNamespace(get_cuda_device_count=lambda: 1)}
            with patch.dict(sys.modules, modules), patch.object(app, 'CACHE', cache):
                progress = []
                app.transcribe(source, 'base', output=cache, device='cpu', report=lambda x: None,
                               progress=lambda *x: progress.append(x))
                self.assertEqual(calls, ['cpu'])
                self.assertTrue(any(x[0] == 50 for x in progress))
                calls.clear()
                app.transcribe(source, 'base', output=cache, device='cuda', report=lambda x: None)
                self.assertEqual(calls, ['cuda', 'cpu'])

if __name__ == '__main__': unittest.main()
