from paths import ROOT
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('run', ROOT / 'run.py')
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


class RunScriptTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        port = Path(folder.name)
        (port / 'scripts').mkdir()
        (port / 'scripts' / 'ok.py').write_text("print('made')\n")
        (port / 'scripts' / 'fails.py').write_text("raise SystemExit(3)\n")
        for patch in (mock.patch.object(run, 'PORT', port), mock.patch.object(run, 'no_console', lambda: 0)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_success_gives_the_output_or_an_empty_string(self):
        self.assertEqual(run.run_script('ok.py', capture=True), 'made\n')
        self.assertEqual(run.run_script('ok.py', capture=True, optional=True), 'made\n')

    def test_a_failure_stops_the_start_unless_the_script_is_optional(self):
        # Issue #8: the PC enhancements' failure stopped the game.
        with self.assertRaises(SystemExit) as stop:
            run.run_script('fails.py', capture=True)
        self.assertEqual(stop.exception.code, 3)
        self.assertIsNone(run.run_script('fails.py', capture=True, optional=True))

    def test_companion_program_accepts_linux_and_windows_names(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        spec = {'name': 'Test', 'exe': 'BloodborneRPC.exe'}
        program = folder / 'BloodborneRPC'
        program.write_text('', encoding='utf-8')
        self.assertEqual(run.companion_program(folder, spec), program)
        program.unlink()
        windows = folder / 'BloodborneRPC.exe'
        windows.write_text('', encoding='utf-8')
        self.assertEqual(run.companion_program(folder, spec), windows)


if __name__ == '__main__':
    unittest.main()
