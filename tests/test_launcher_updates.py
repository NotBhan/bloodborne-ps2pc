import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import bbport_launcher_win as core


class QuietUpdateCheckTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        cache = Path(self.directory.name) / 'update-check.json'
        for name, value in {'CONFIG_DIR': cache.parent, 'UPDATE_CACHE': cache,
                            'CURRENT_RELEASE_TAG': 'qml-launcher-preview-8', 'VERSION': '1.6.12'}.items():
            patcher = patch.object(core, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cache = cache

    def reply(self, tag):
        release = {'tag_name': tag, 'html_url': 'https://example.invalid/page',
                   'assets': [{'name': 'bbport-windows.zip', 'browser_download_url': 'https://example.invalid/zip'}]}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, *args): return json.dumps(release).encode()
        return patch.object(core.urllib.request, 'urlopen', return_value=Response())

    def test_newer_release_is_remembered_for_the_launcher(self):
        with self.reply('qml-launcher-preview-9'):
            self.assertTrue(core.quiet_update_check({'check_updates': True}, now=1000))
        self.assertEqual(core.remembered_update(), ('qml-launcher-preview-9', 'https://example.invalid/zip',
                                                    'https://example.invalid/page'))

    def test_current_or_older_release_is_not_offered(self):
        with self.reply('qml-launcher-preview-8'):
            core.quiet_update_check({'check_updates': True})
        self.assertIsNone(core.remembered_update())

    def test_switched_off_and_throttled(self):
        with self.reply('qml-launcher-preview-9') as urlopen:
            self.assertFalse(core.quiet_update_check({'check_updates': False}))
            self.assertTrue(core.quiet_update_check({'check_updates': True}, now=core.time.time()))
            self.assertFalse(core.quiet_update_check({'check_updates': True}, now=core.time.time() + 60))
            self.assertTrue(core.quiet_update_check({'check_updates': True},
                                                    now=core.time.time() + core.QUIET_CHECK_INTERVAL + 1))
        self.assertEqual(urlopen.call_count, 2)

    def test_network_failure_is_silent_and_corrupt_cache_ignored(self):
        self.cache.write_text('not json', encoding='utf-8')
        self.assertIsNone(core.remembered_update())
        with patch.object(core.urllib.request, 'urlopen', side_effect=OSError('offline')):
            self.assertFalse(core.quiet_update_check({'check_updates': True}))


class ForkReleaseTests(unittest.TestCase):
    def test_updates_come_from_this_fork(self):
        self.assertIn('NotBhan/bloodborne-ps2pc', core.RELEASES_API)
        self.assertIn('NotBhan/bloodborne-ps2pc', core.RELEASES_PAGE)

    def test_release_tags_compare_against_the_installed_tag(self):
        with patch.object(core, 'CURRENT_RELEASE_TAG', 'v1.10.8'):
            self.assertFalse(core.release_is_newer('v1.10.8'))
            self.assertFalse(core.release_is_newer('v1.10.7'))
            self.assertTrue(core.release_is_newer('v1.10.9'))
            self.assertTrue(core.release_is_newer('v1.11.0'))


if __name__ == '__main__':
    unittest.main()
