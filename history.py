"""Upload history persistence — JSON file, newest entry first.

Pure functions, path injectable for tests. Default file lives next to
this module (project root): ft_upload_history.json
"""
import json
import os
import sys

if getattr(sys, 'frozen', False):
    # 打包后 __file__ 指向临时目录，历史文件必须放 exe 旁边
    _HISTORY_PATH = os.path.join(os.path.dirname(sys.executable),
                                 "ft_upload_history.json")
else:
    _HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "ft_upload_history.json")

# 日志条数上限 — 每条带缩略图 ~1MB，不封顶内存会随截图次数无限涨
MAX_ENTRIES = 50


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
    """Insert entry at front (newest first), persist, return full list.

    Capped at MAX_ENTRIES — dropped entries' screenshot files are removed.
    """
    path = path or _HISTORY_PATH
    entries = load_entries(path)
    entries.insert(0, entry)
    dropped = entries[MAX_ENTRIES:]
    entries = entries[:MAX_ENTRIES]
    for old in dropped:
        shot = old.get("screenshot", "")
        try:
            base = os.path.dirname(path) if path else os.path.dirname(_HISTORY_PATH)
            fp = shot if os.path.isabs(shot) else os.path.join(base, shot)
            if os.path.exists(fp):
                os.remove(fp)
        except Exception:
            pass
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"entries": entries}, f, ensure_ascii=False, indent=2)
    return entries
