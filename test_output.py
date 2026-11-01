import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from app import App, BASE

class OutputTests(unittest.TestCase):
    def test_custom_folder_used_by_all_modes_and_open_button(self):
        ui = App(); ui.root.withdraw()
        try:
            with tempfile.TemporaryDirectory(dir=BASE / '压缩验收') as temp:
                target = Path(temp) / '自定义 输出'
                with patch('app.filedialog.askdirectory', return_value=str(target)):
                    ui.select_output()
                self.assertEqual(ui.output_dir.get(), str(target))
                for mode in ('生成逐字稿', '提取小体积音频', '压缩视频'):
                    ui.files = ['sample.mp4']; ui.mode.set(mode)
                    function = 'app.transcribe' if mode == '生成逐字稿' else 'app.compress'
                    with patch(function) as process:
                        ui.start()
                        deadline = time.monotonic() + 5
                        while ui.busy and time.monotonic() < deadline:
                            ui.root.update(); time.sleep(.01)
                        self.assertFalse(ui.busy)
                        self.assertEqual(process.call_args.kwargs['output'], target.resolve())
                with patch('app.os.startfile') as open_folder:
                    ui.open_output()
                    self.assertEqual(open_folder.call_args.args[0], target.resolve())
                with patch('app.filedialog.askdirectory', return_value=''):
                    ui.select_output()
                self.assertEqual(ui.output_dir.get(), str(target))
                invalid = Path(temp) / 'file.txt'; invalid.touch()
                ui.output_dir.set(str(invalid))
                with patch('app.transcribe') as process:
                    ui.start()
                    self.assertFalse(ui.busy)
                    process.assert_not_called()
        finally:
            ui.root.destroy()

if __name__ == '__main__': unittest.main()
