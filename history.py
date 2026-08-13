"""Upload history persistence — JSON file, newest entry first.

Pure functions, path injectable for tests. Default file lives next to
this module (project root): ft_upload_history.json
"""
import json
import os

_HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "ft_upload_history.json")


def load_entries(path: str | None = None) -> list[dict]:
    """Load all entries, oldest to newest order as stored. Missing/corrupt → []."""
    path = path or _HISTORY_PATH
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("entries", [])
    except Exception:
        return []


def append_entry(entry: dict, path: str | None = None) -> list[dict]:
    """Insert entry at front (newest first), persist, return full list."""
    path = path or _HISTORY_PATH
    entries = load_entries(path)
    entries.insert(0, entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"entries": entries}, f, ensure_ascii=False, indent=2)
    return entries
