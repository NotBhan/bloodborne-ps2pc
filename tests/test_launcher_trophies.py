import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
from bbport_trophies import load_trophy_report


def write_metadata(user: Path, entries, *, version=2, complete=True, source_size=1234,
                   title="Bloodborne", description="A hunter must hunt."):
    folder = user / "trophy_cache"
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "version": version,
        "source_size": source_size,
        "source_modified": 1,
        "language": 1,
        "complete": complete,
        "title": title,
        "description": description,
        "entries": entries,
    }
    (folder / "metadata.json").write_text(json.dumps(data), encoding="utf-8")


def write_icons(user: Path, *names):
    folder = user / "trophy_cache" / "icons"
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"\x89PNG\r\n\x1a\n")


def write_history(user: Path, text: str):
    (user / "trophies.txt").write_text(text, encoding="utf-8")


class TrophyReportTests(unittest.TestCase):
    def test_complete_v2_cache_joins_unlocks_and_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            user = Path(temporary)
            write_icons(user, "TROP000.PNG", "TROP001.PNG")
            write_metadata(user, [
                {"id": 0, "name": "Bloodborne", "description": "All trophies.",
                 "grade": "P", "hidden": False, "score": 300, "icon": "TROP000.PNG"},
                {"id": 1, "name": "Yharnam Sunrise", "description": "Ascend.",
                 "grade": "G", "hidden": False, "score": 90, "icon": "TROP001.PNG"},
                {"id": 2, "name": "Secret Hunt", "description": "Hidden.",
                 "grade": "S", "hidden": True, "score": 30, "icon": "TROP002.PNG"},
            ])
            write_history(user, "0 1000\n2 2000\n99 3000\n")
            report = load_trophy_report(user)
            self.assertTrue(report.metadata_available)
            self.assertTrue(report.metadata_complete)
            self.assertIsNone(report.reason)
            self.assertEqual(report.total, 3)
            self.assertEqual(report.earned, 2)
            self.assertEqual(report.completion, 66)
            self.assertEqual(report.grade_counts, {"B": 0, "S": 1, "G": 1, "P": 1})
            self.assertEqual(report.local_unlocks, 3)
            self.assertEqual(report.orphan_unlocks, (99,))
            self.assertFalse(report.stale)
            self.assertEqual(report.set_title, "Bloodborne")
            entries = {entry.id: entry for entry in report.entries}
            self.assertTrue(entries[0].earned)
            self.assertEqual(entries[0].unlocked_at, 1000)
            self.assertTrue(entries[1].icon.is_file())
            self.assertTrue(entries[2].hidden)
            self.assertEqual(entries[2].grade, "S")

    def test_v1_placeholder_cache_is_unavailable_and_never_named(self):
        with tempfile.TemporaryDirectory() as temporary:
            user = Path(temporary)
            write_metadata(user, [
                {"id": 0, "name": "Trophy #0", "description": "", "grade": "?",
                 "hidden": False, "score": -1},
            ], version=1, complete=False)
            write_history(user, "0 1234\n")
            report = load_trophy_report(user)
            self.assertFalse(report.metadata_available)
            self.assertFalse(report.metadata_complete)
            self.assertIsNone(report.total)
            self.assertIsNone(report.completion)
            self.assertEqual(report.local_unlocks, 1)
            self.assertIn("older format", report.reason)
            self.assertFalse(any(entry.name_available for entry in report.entries))

    def test_incomplete_v2_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            user = Path(temporary)
            write_metadata(user, [
                {"id": 0, "name": "Trophy #0", "description": "", "grade": "?",
                 "hidden": False, "score": -1},
            ], complete=False)
            report = load_trophy_report(user)
            self.assertFalse(report.metadata_available)
            self.assertIsNone(report.completion)
            self.assertIn("not decrypted", report.reason)

    def test_history_is_strict_and_last_duplicate_wins(self):
        with tempfile.TemporaryDirectory() as temporary:
            user = Path(temporary)
            write_metadata(user, [
                {"id": 5, "name": "Five", "description": "", "grade": "B", "hidden": False},
            ])
            write_history(user, "5 100\n5 200\n2 nope\n3 0\n6 200 extra\n-1 100\n")
            report = load_trophy_report(user)
            entry = report.entries[0]
            self.assertTrue(entry.earned)
            self.assertEqual(entry.unlocked_at, 200)
            self.assertEqual(report.local_unlocks, 1)

    def test_pack_size_mismatch_marks_stale(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user, game = root / "user", root / "CUSA03173"
            write_metadata(user, [
                {"id": 0, "name": "One", "description": "", "grade": "B", "hidden": False},
            ], source_size=999)
            (game / "sce_sys" / "trophy").mkdir(parents=True)
            (game / "sce_sys" / "trophy" / "trophy00.trp").write_bytes(b"DCA24D00")
            report = load_trophy_report(user, game)
            self.assertTrue(report.stale)
            self.assertTrue(report.metadata_available)

    def test_missing_cache_reports_a_truthful_empty_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = load_trophy_report(Path(temporary))
            self.assertFalse(report.metadata_available)
            self.assertEqual(report.entries, ())
            self.assertEqual(report.local_unlocks, 0)
            self.assertIn("No trophy cache", report.reason)

    def test_icon_paths_are_confined_to_the_icon_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            user = Path(temporary)
            outside = user / "outside.png"
            outside.write_bytes(b"not an icon")
            write_icons(user, "inside.png")
            write_metadata(user, [
                {"id": 0, "name": "One", "description": "", "grade": "B",
                 "hidden": False, "icon": "../../outside.png"},
                {"id": 1, "name": "Two", "description": "", "grade": "B",
                 "hidden": False, "icon": "inside.png"},
            ])
            report = load_trophy_report(user)
            self.assertIsNone(report.entries[0].icon)
            self.assertEqual(report.entries[1].icon, user / "trophy_cache" / "icons" / "inside.png")


if __name__ == "__main__":
    unittest.main()
