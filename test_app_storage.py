"""Regression tests for per-user storage and conservative migration."""

import json
import tempfile
import traceback
from pathlib import Path

from app_storage import (
    CONFIG_NAME,
    HISTORY_NAME,
    SCREENSHOT_FOLDER,
    atomic_write_json,
    migrate_legacy_storage,
    storage_root,
)


def test_storage_root_uses_local_app_data():
    root = storage_root({"LOCALAPPDATA": r"C:\Users\tester\AppData\Local"})
    assert root.parts[-2:] == ("FantianTradingHub", "DesktopAssistant")
    assert str(root).startswith(r"C:\Users\tester\AppData\Local")


def test_atomic_json_replaces_complete_document_and_leaves_no_temp_file():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "state.json"
        atomic_write_json(path, {"value": 1})
        atomic_write_json(path, {"value": 2})
        assert json.loads(path.read_text(encoding="utf-8")) == {"value": 2}
        assert list(path.parent.glob(".state.json.*.tmp")) == []


def test_migration_copies_only_parsed_state_and_referenced_safe_images():
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        legacy = base / "legacy"
        target = base / "target"
        (legacy / SCREENSHOT_FOLDER).mkdir(parents=True)
        (legacy / CONFIG_NAME).write_text('{"hotkey":"f4"}', encoding="utf-8")
        screenshot = legacy / SCREENSHOT_FOLDER / "sc_shot_20260823_120000.png"
        screenshot.write_bytes(b"png")
        orphan = legacy / SCREENSHOT_FOLDER / "sc_shot_20260823_120001.png"
        orphan.write_bytes(b"orphan")
        (legacy / HISTORY_NAME).write_text(
            json.dumps({"entries": [{"screenshot": f"{SCREENSHOT_FOLDER}/{screenshot.name}"}]}),
            encoding="utf-8",
        )

        migrate_legacy_storage(legacy, target)

        assert json.loads((target / CONFIG_NAME).read_text(encoding="utf-8"))["hotkey"] == "f4"
        assert (target / SCREENSHOT_FOLDER / screenshot.name).read_bytes() == b"png"
        assert not (target / SCREENSHOT_FOLDER / orphan.name).exists()
        assert screenshot.exists(), "migration must not destructively remove old data"


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}:")
                traceback.print_exc()
    print(f"{failed} failed")
    raise SystemExit(1 if failed else 0)
