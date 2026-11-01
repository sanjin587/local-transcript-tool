import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from app import App, BASE

class DropTests(unittest.TestCase):
    def setUp(self):
        self.ui = App()
        self.ui.root.withdraw()
        self.temp = tempfile.TemporaryDirectory(dir=BASE / '压缩验收')
        self.folder = Path(self.temp.name)
    def tearDown(self):
        self.ui.root.destroy()
        self.temp.cleanup()
    def drop(self, paths):
        payload = self.ui.root.tk.call('format', '%s', self.ui.root.tk.call('list', *map(str, paths)))
        return self.ui.on_drop(SimpleNamespace(data=payload))
    def test_drop_zone_click_opens_file_picker(self):
        from unittest.mock import patch
        video = self.folder / '点击选择.mp4'; video.touch()
        self.ui.root.deiconify(); self.ui.root.update()
        with patch('app.filedialog.askopenfilenames', return_value=(str(video),)) as picker:
            self.ui.drop_zone.event_generate('<Button-1>', x=10, y=10)
            self.ui.root.update()
            picker.assert_called_once()
        self.assertEqual(self.ui.files, [str(video)])
        self.ui.busy = True
        with patch('app.filedialog.askopenfilenames') as picker:
            self.ui.drop_zone.event_generate('<Button-1>', x=10, y=10)
            self.ui.root.update()
            picker.assert_not_called()

    def test_native_extension_registered(self):
        self.assertTrue(self.ui.dnd_enabled)
        self.assertTrue(self.ui.root.tk.call('package', 'present', 'tkdnd'))
        self.assertTrue(self.ui.drop_zone.dnd_bind('<<Drop>>'))
    def test_multiple_unicode_space_paths_append_and_deduplicate(self):
        first = self.folder / '中文 视频.MP4'
        second = self.folder / '录音 空格.wav'
        first.touch(); second.touch()
        self.drop([first])
        self.drop([first, second])
        self.assertEqual(self.ui.files, [str(first.resolve()), str(second.resolve())])
        self.assertEqual(len(self.ui.file_progress), 2)
    def test_reject_folder_unsupported_and_missing(self):
        text = self.folder / 'note.txt'; text.touch()
        result = self.drop([self.folder, text, self.folder / 'missing.mp4'])
        self.assertEqual(self.ui.files, [])
        self.assertEqual(result, 'refuse_drop')
    def test_busy_drop_does_not_change_progress(self):
        video = self.folder / 'test.mp4'; video.touch()
        self.drop([video])
        self.ui.apply_progress(0, 45, '正在识别')
        self.ui.busy = True
        self.assertEqual(self.drop([video]), 'refuse_drop')
        self.assertEqual(float(self.ui.file_progress[0]['bar']['value']), 45)

if __name__ == '__main__': unittest.main()
