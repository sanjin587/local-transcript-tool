import unittest
from app import App

class LayoutTests(unittest.TestCase):
    def test_four_long_filenames_and_progress_fit(self):
        ui = App()
        try:
            ui.files = [f'子木AI智能体_2026-11-01_20-55-23_00{i}.mp4' for i in range(4)]
            ui.show_files()
            for width in (980, 820):
                ui.root.geometry(f'{width}x780')
                ui.root.update()
                last = ui.file_progress[-1]['bar']
                bottom = last.winfo_rooty() + last.winfo_height()
                self.assertLessEqual(bottom, ui.progress_canvas.winfo_rooty() + ui.progress_canvas.winfo_height())
                self.assertGreater(last.winfo_width(), 180)
            ui.files *= 5
            ui.show_files(); ui.root.update()
            ui.progress_canvas.event_generate('<MouseWheel>', delta=-120)
            ui.root.update()
            self.assertGreater(ui.progress_canvas.yview()[0], 0)
        finally:
            ui.root.destroy()

if __name__ == '__main__': unittest.main()
