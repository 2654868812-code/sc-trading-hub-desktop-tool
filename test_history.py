"""Tests for history module — run: python test_history.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history

def _tmp_path():
    return os.path.join(tempfile.gettempdir(), f"test_history_{os.getpid()}.json")

def test_load_missing_returns_empty():
    assert history.load_entries(_tmp_path()) == []


def test_append_then_load_roundtrip():
    p = _tmp_path()
    if os.path.exists(p):
        os.remove(p)
    entry = {"time": "2026-08-13 23:00:00", "status": "success",
             "terminal": "死局空间站", "transactionType": "buy",
             "detail": "已提交 2 条", "items": [], "screenshot": "screenshots/x.png"}
    history.append_entry(entry, p)
    entries = history.load_entries(p)
    assert entries == [entry], f"roundtrip mismatch: {entries}"
    os.remove(p)


def test_new_entry_goes_first():
    p = _tmp_path()
    if os.path.exists(p):
        os.remove(p)
    history.append_entry({"time": "old", "status": "success"}, p)
    history.append_entry({"time": "new", "status": "success"}, p)
    entries = history.load_entries(p)
    assert entries[0]["time"] == "new"
    assert entries[1]["time"] == "old"
    os.remove(p)


def test_corrupted_file_returns_empty():
    p = _tmp_path()
    with open(p, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert history.load_entries(p) == []
    os.remove(p)


def test_append_caps_entries():
    p = _tmp_path()
    if os.path.exists(p):
        os.remove(p)
    for i in range(60):
        history.append_entry({"time": str(i), "status": "success"}, p)
    entries = history.load_entries(p)
    assert len(entries) == history.MAX_ENTRIES
    assert entries[0]["time"] == "59"   # 最新在前
    assert entries[-1]["time"] == str(60 - history.MAX_ENTRIES)
    os.remove(p)


def test_pruning_never_deletes_absolute_or_parent_traversal_paths():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        screenshots = root / "screenshots"
        screenshots.mkdir()
        victim = root / "victim.txt"
        victim.write_text("keep", encoding="utf-8")
        path = root / "history.json"
        malicious = [
            {"time": "absolute", "screenshot": str(victim)},
            {"time": "traversal", "screenshot": "screenshots/../victim.txt"},
        ]
        path.write_text(json.dumps({"entries": [{}] * 48 + malicious}), encoding="utf-8")
        history.append_entry({"time": "new"}, path, screenshot_dir=screenshots)
        history.append_entry({"time": "newer"}, path, screenshot_dir=screenshots)
        assert victim.read_text(encoding="utf-8") == "keep"


def test_pruning_deletes_only_named_screenshot_and_thumbnail_inside_root():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        screenshots = root / "screenshots"
        screenshots.mkdir()
        shot = screenshots / "sc_shot_20260823_120000.png"
        thumb = screenshots / "sc_shot_20260823_120000_thumb.png"
        shot.write_bytes(b"shot")
        thumb.write_bytes(b"thumb")
        path = root / "history.json"
        old = {"time": "old", "screenshot": f"screenshots/{shot.name}"}
        path.write_text(json.dumps({"entries": [{}] * 49 + [old]}), encoding="utf-8")
        history.append_entry({"time": "new"}, path, screenshot_dir=screenshots)
        assert not shot.exists()
        assert not thumb.exists()


def test_clear_history_removes_records_and_dedicated_images_only():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        screenshots = root / "screenshots"
        screenshots.mkdir()
        shot = screenshots / "sc_shot_20260823_120000.png"
        shot.write_bytes(b"shot")
        unrelated = root / "keep.txt"
        unrelated.write_text("keep", encoding="utf-8")
        path = root / "history.json"
        history.append_entry(
            {"time": "now", "screenshot": f"screenshots/{shot.name}"},
            path,
            screenshot_dir=screenshots,
        )
        assert history.clear_entries(path, screenshot_dir=screenshots) == 1
        assert history.load_entries(path) == []
        assert not shot.exists()
        assert unrelated.exists()


def test_pruning_rejects_screenshot_symlink_when_supported():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        screenshots = root / "screenshots"
        screenshots.mkdir()
        victim = root / "victim.txt"
        victim.write_text("keep", encoding="utf-8")
        link = screenshots / "sc_shot_20260823_120000.png"
        try:
            os.symlink(victim, link)
        except (OSError, NotImplementedError):
            return
        path = root / "history.json"
        old = {"screenshot": f"screenshots/{link.name}"}
        path.write_text(json.dumps({"entries": [{}] * 49 + [old]}), encoding="utf-8")
        history.append_entry({"time": "new"}, path, screenshot_dir=screenshots)
        assert victim.read_text(encoding="utf-8") == "keep"
        assert link.exists()


if __name__ == "__main__":
    import traceback
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e}")
            except Exception:
                failed += 1
                print(f"ERROR {name}:")
                traceback.print_exc()
    print(f"{failed} failed")
    sys.exit(1 if failed else 0)
