import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import bbport_launcher_win as core
import bbport_startup
from bbport_launcher_backend import LauncherBackend


class FirstRunWizardTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / 'out'
        parent.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.temporary.name)
        self.patches = [patch.object(core, 'CONFIG_DIR', self.root),
                        patch.object(core, 'CONFIG_FILE', self.root / 'settings.json'),
                        patch.object(core, 'DATA_DIR', self.root),
                        patch.dict(os.environ, {'BB_CONFIG': str(self.root / 'bbport.ini')}),
                        patch.dict(core.APP_DEFAULTS, {'check_updates': False,
                                                       'game_dir': str(self.root / 'missing')}),
                        patch.object(LauncherBackend, '_detect_gpu', lambda self: None)]
        for active in self.patches:
            active.start()

    def tearDown(self):
        for active in reversed(self.patches):
            active.stop()
        self.temporary.cleanup()

    def settings(self):
        return {**core.APP_DEFAULTS, **json.loads((self.root / 'settings.json').read_text(encoding='utf-8'))}

    def route(self, args=()):
        return bbport_startup.route(self.settings(), list(args), self.root, False)

    def test_wizard_survives_partial_setup_and_stops_after_finish(self):
        first = LauncherBackend()
        first.setValue('game_dir', str(self.root / 'game'))
        self.assertEqual(self.route()['page'], 'Setup')
        first.completeSetup()
        saved = self.settings()
        self.assertTrue(saved['setupCompleted'])
        self.assertEqual(saved['setupVersion'], bbport_startup.SETUP_VERSION)
        self.assertNotEqual(self.route()['page'], 'Setup')

    def test_finished_setup_with_game_launches_directly(self):
        game = self.root / 'CUSA03173'
        game.mkdir()
        (game / 'eboot.bin').write_bytes(b'\0')
        backend = LauncherBackend()
        backend.setValue('game_dir', str(game))
        backend.completeSetup()
        self.assertEqual(self.route()['mode'], 'direct')
        self.assertEqual(self.route(['--launcher'])['page'], 'Home')
        self.assertEqual(self.route(['--setup'])['page'], 'Setup')
        backend.setValue('launchDirectly', False)
        self.assertEqual(self.route()['mode'], 'launcher')

    def test_skip_opens_game_page_with_fix_banner(self):
        backend = LauncherBackend()
        backend.skipSetup()
        self.assertTrue(self.settings()['setupSkipped'])
        self.assertEqual(backend.startupProblem, 'Game files not found')
        route = self.route()
        self.assertEqual((route['page'], route['problem'], route['step']), ('Game', 'game', 1))
        backend.dismissProblem()
        self.assertEqual(backend.startupProblem, '')

    def test_fix_banner_clears_once_game_folder_is_valid(self):
        backend = LauncherBackend({'mode': 'launcher', 'page': 'Game', 'step': 1, 'problem': 'game'})
        self.assertEqual(backend.startPage, 'Game')
        self.assertEqual(backend.fixStep, 1)
        self.assertEqual(backend.startupProblem, 'Game files not found')
        game = self.root / 'game'
        game.mkdir()
        (game / 'eboot.bin').write_bytes(b'\0')
        backend.setValue('game_dir', str(game))
        self.assertEqual(backend.startupProblem, '')

    def test_bundled_xbox_prompts_are_on_by_default_and_only_on_controller_page(self):
        source = Path(__file__).resolve().parents[1] / 'packaging' / 'windows' / 'mods'
        import shutil
        shutil.copytree(source, self.root / 'mods')
        backend = LauncherBackend()
        self.assertEqual(backend.promptChoice, 'Xbox')
        self.assertEqual(backend.contentMods, [])
        backend.setPrompt('PlayStation')
        self.assertEqual(backend.promptChoice, 'PlayStation')
        # Keyboard copies in the PCBButtons images the port ships (packaging/windows/bundled),
        # enables them instead of the Xbox images and binds the keys its images show.
        self.assertIsNotNone(core.bundled_keyboard_prompts())
        backend.setPrompt('Keyboard')
        self.assertEqual(backend.promptChoice, 'Keyboard')
        profile = json.loads((self.root / 'mods.json').read_text())
        self.assertIn('Xbox 360 Prompts (Elden Ring)', profile['disabled'])
        self.assertIn(core.KEYBOARD_PROMPTS, profile['enabled'])
        self.assertTrue((self.root / 'mods' / core.KEYBOARD_PROMPTS / 'menu' / 'common.tpf.dcx').is_file())
        ini = (self.root / 'bbport.ini').read_text(encoding='utf-8')
        self.assertIn('key_roll=Left Shift', ini)
        self.assertIn('key_lock_on=Mouse3', ini)
        self.assertNotIn(core.KEYBOARD_PROMPTS, [m['name'] for m in backend.contentMods])
        # What run.py reads at every start (BB_BUTTON_PROMPTS): the key images, not the Xbox ones.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
        import mods
        in_use = mods.selected(self.root / 'mods', self.root / 'mods.json')
        self.assertIn(core.KEYBOARD_PROMPTS, in_use)
        self.assertNotIn('Xbox 360 Prompts (Elden Ring)', in_use)
        # A choice made in the game's overlay (mods.json only) shows in the launcher too.
        profile = json.loads((self.root / 'mods.json').read_text())
        profile['disabled'] = sorted(set(profile['disabled']) - {'Xbox 360 Prompts (Elden Ring)'}
                                     | {core.KEYBOARD_PROMPTS})
        (self.root / 'mods.json').write_text(json.dumps(profile))
        backend.refresh_addons()
        self.assertEqual(backend.promptChoice, 'Xbox')
        backend.setPrompt('Keyboard')  # already imported: no file dialog
        self.assertEqual(backend.promptChoice, 'Keyboard')
        backend.setPrompt('Xbox')
        profile = json.loads((self.root / 'mods.json').read_text())
        self.assertIn(core.KEYBOARD_PROMPTS, profile['disabled'])
        self.assertEqual(backend.promptChoice, 'Xbox')

    def test_keyboard_prompts_missing_from_the_copy_says_so(self):
        backend = LauncherBackend()
        original = core.bundled_keyboard_prompts
        core.bundled_keyboard_prompts = lambda: None
        try:
            backend.setPrompt('Keyboard')
        finally:
            core.bundled_keyboard_prompts = original
        self.assertNotEqual(backend.promptChoice, 'Keyboard')
        self.assertIn('latest release', backend.notice)

    def test_launch_options_moved_out_of_advanced(self):
        backend = LauncherBackend()
        keys = {field['key'] for page in ('Advanced', 'Diagnostics') for field in backend.fields(page)}
        self.assertFalse(keys & {'close_on_play', 'launchDirectly', 'check_updates'})
        self.assertEqual([f['key'] for f in backend.fields('Diagnostics')],
                         ['frame_stats', 'gpu_profile', 'vk_validation'])
        pages = ('Graphics', 'Display', 'Game', 'Controller', 'Cheats', 'Online', 'Mods', 'Advanced', 'Diagnostics')
        every = [field['key'] for page in pages for field in backend.fields(page)]
        self.assertEqual(len(every), len(set(every)), 'a setting appears on two pages')

    def test_key_bindings_are_listed_saved_and_reset(self):
        backend = LauncherBackend()
        groups = backend.keyBindings
        self.assertEqual([group['section'] for group in groups],
                         ['Movement', 'Combat and items', 'Menus and switching'])
        bindings = {binding['action']: binding for group in groups
                    for binding in group['bindings']}
        self.assertEqual(bindings['move_forward']['display'], 'W')
        self.assertEqual(bindings['attack']['display'], 'Mouse1')
        self.assertEqual(bindings['firearm']['display'], 'X + Mouse2')
        self.assertEqual(core.sdl_key_name(0x57, 'w', False), 'W')
        self.assertEqual(core.sdl_key_name(0x31, '1', True), 'Keypad 1')

        # A key already in use is taken from the action that had it.
        backend.setKeyBinding('interact', 'G', '')
        ini = (self.root / 'bbport.ini').read_text(encoding='utf-8')
        self.assertIn('key_interact=G', ini)
        self.assertIn('key_gestures=none', ini)
        bindings = {binding['action']: binding for group in backend.keyBindings
                    for binding in group['bindings']}
        self.assertEqual(bindings['interact']['display'], 'G')
        self.assertEqual(bindings['gestures']['display'], 'Unbound')

        # A mouse input replaces only the mouse part; a key replaces only the key part.
        backend.setKeyBinding('interact', 'E', 'WheelDown')
        self.assertIn('key_interact=E, WheelDown',
                      (self.root / 'bbport.ini').read_text(encoding='utf-8'))
        backend.setKeyBinding('interact', 'R', '')
        ini = (self.root / 'bbport.ini').read_text(encoding='utf-8')
        self.assertIn('key_interact=R', ini)
        self.assertIn('key_blood_vial=none', ini)

        backend.resetKeyBinding('interact')
        self.assertIn('key_interact=E', (self.root / 'bbport.ini').read_text(encoding='utf-8'))

        backend.resetKeyBindings()
        ini = (self.root / 'bbport.ini').read_text(encoding='utf-8')
        self.assertNotIn('key_interact=', ini)
        self.assertNotIn('key_gestures=', ini)


if __name__ == '__main__':
    unittest.main()
