import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
from bbport_activity import (EVENT_LIMIT, add_playtime, load_events, load_playtime,
                             record_event)


class ActivityJournalTests(unittest.TestCase):
    def test_events_are_newest_first_and_capped(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "activity.json"
            for index in range(EVENT_LIMIT + 5):
                record_event(path, "launch", f"event {index}", timestamp=1000 + index)
            events = load_events(path)
            self.assertEqual(len(events), EVENT_LIMIT)
            self.assertEqual(events[0]["text"], f"event {EVENT_LIMIT + 4}")
            self.assertEqual(events[-1]["text"], "event 5")
            self.assertEqual(events[0]["time"], 1000 + EVENT_LIMIT + 4)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["events"][0]["kind"],
                             "launch")

    def test_missing_or_malformed_journal_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "activity.json"
            self.assertEqual(load_events(path), [])
            path.write_text("[1, 2, 3]", encoding="utf-8")
            self.assertEqual(load_events(path), [])
            path.write_text('{"events": [{"time": "x", "kind": 1, "text": null}]}',
                            encoding="utf-8")
            self.assertEqual(load_events(path), [])

    def test_record_is_atomic_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "activity.json"
            record_event(path, "launch", "one", timestamp=10)
            record_event(path, "exit", "two", timestamp=11)
            self.assertEqual([event["text"] for event in load_events(path)], ["two", "one"])
            self.assertEqual(list(path.parent.glob(".activity.json.*.tmp")), [])

    def test_playtime_accumulates_and_survives_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "activity.json"
            self.assertEqual(load_playtime(path), 0)
            self.assertEqual(add_playtime(path, 90), 90)
            record_event(path, "session", "played", timestamp=20)
            self.assertEqual(load_playtime(path), 90)
            self.assertEqual(add_playtime(path, 30), 120)
            self.assertEqual(load_playtime(path), 120)
            self.assertEqual([event["text"] for event in load_events(path)], ["played"])

    def test_playtime_ignores_invalid_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "activity.json"
            path.write_text('{"playtime_seconds": "nope", "events": []}', encoding="utf-8")
            self.assertEqual(load_playtime(path), 0)
            path.write_text('{"playtime_seconds": -40, "events": []}', encoding="utf-8")
            self.assertEqual(load_playtime(path), 0)


if __name__ == "__main__":
    unittest.main()
