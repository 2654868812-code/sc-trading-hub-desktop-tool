"""Tests for history module — run: python test_history.py"""
import json
import os
import sys
import tempfile

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
