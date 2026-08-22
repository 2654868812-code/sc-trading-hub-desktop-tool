"""Bounded, path-safe upload history persistence."""

from __future__ import annotations

from pathlib import Path

from app_storage import (
    HISTORY_PATH,
    MAX_JSON_BYTES,
    SCREENSHOT_DIR,
    SCREENSHOT_FOLDER,
    SCREENSHOT_NAME_RE,
    atomic_write_json,
    is_reparse_point,
    load_json_object,
)


MAX_ENTRIES = 50
_HISTORY_PATH = str(HISTORY_PATH)


def _screenshot_root(history_path: Path, screenshot_dir: Path | str | None) -> Path:
    if screenshot_dir is not None:
        return Path(screenshot_dir)
    try:
        if history_path.resolve() == HISTORY_PATH.resolve():
            return SCREENSHOT_DIR
    except OSError:
        pass
    return history_path.parent / SCREENSHOT_FOLDER


def _screenshot_name(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    if len(candidate.parts) == 2 and candidate.parts[0].lower() == SCREENSHOT_FOLDER:
        name = candidate.parts[1]
    elif len(candidate.parts) == 1:
        name = candidate.name
    else:
        return None
    if not SCREENSHOT_NAME_RE.fullmatch(name) or name.lower().endswith("_thumb.png"):
        return None
    return name


def resolve_screenshot_path(
    value: object,
    *,
    history_path: Path | str | None = None,
    screenshot_dir: Path | str | None = None,
    must_exist: bool = True,
) -> Path | None:
    """Resolve a history screenshot strictly inside its dedicated directory."""
    name = _screenshot_name(value)
    if name is None:
        return None
    history_file = Path(history_path or HISTORY_PATH)
    root = _screenshot_root(history_file, screenshot_dir)
    try:
        if is_reparse_point(root) or not root.is_dir():
            return None
        resolved_root = root.resolve(strict=True)
        candidate = root / name
        if candidate.resolve(strict=False).parent != resolved_root:
            return None
        if candidate.exists():
            if is_reparse_point(candidate) or not candidate.is_file():
                return None
        elif must_exist:
            return None
        return candidate
    except OSError:
        return None


def thumbnail_path(screenshot: Path) -> Path:
    return screenshot.with_name(f"{screenshot.stem}_thumb.png")


def load_entries(path: str | Path | None = None) -> list[dict]:
    """Load at most MAX_ENTRIES well-formed records; corrupt files become empty."""
    data = load_json_object(Path(path or HISTORY_PATH), max_bytes=MAX_JSON_BYTES)
    entries = data.get("entries") if data else None
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)][:MAX_ENTRIES]


def _delete_entry_images(
    entry: dict,
    history_path: Path,
    screenshot_dir: Path | str | None,
) -> None:
    screenshot = resolve_screenshot_path(
        entry.get("screenshot"),
        history_path=history_path,
        screenshot_dir=screenshot_dir,
        must_exist=True,
    )
    if screenshot is None:
        return
    for candidate in (screenshot, thumbnail_path(screenshot)):
        try:
            if candidate.exists() and not is_reparse_point(candidate) and candidate.is_file():
                candidate.unlink()
        except OSError:
            pass


def append_entry(
    entry: dict,
    path: str | Path | None = None,
    *,
    screenshot_dir: Path | str | None = None,
) -> list[dict]:
    """Insert newest first, atomically persist, and safely prune old images."""
    if not isinstance(entry, dict):
        raise TypeError("history entry must be a dictionary")
    history_path = Path(path or HISTORY_PATH)
    entries = load_entries(history_path)
    entries.insert(0, entry)
    dropped = entries[MAX_ENTRIES:]
    entries = entries[:MAX_ENTRIES]
    atomic_write_json(history_path, {"entries": entries})
    for old in dropped:
        _delete_entry_images(old, history_path, screenshot_dir)
    return entries


def clear_entries(
    path: str | Path | None = None,
    *,
    screenshot_dir: Path | str | None = None,
) -> int:
    """Clear history and all plain PNGs in the dedicated screenshot folder."""
    history_path = Path(path or HISTORY_PATH)
    entries = load_entries(history_path)
    atomic_write_json(history_path, {"entries": []})
    root = _screenshot_root(history_path, screenshot_dir)
    if root.is_dir() and not is_reparse_point(root):
        try:
            for candidate in root.iterdir():
                if (
                    SCREENSHOT_NAME_RE.fullmatch(candidate.name)
                    and candidate.is_file()
                    and not is_reparse_point(candidate)
                ):
                    try:
                        candidate.unlink()
                    except OSError:
                        pass
        except OSError:
            pass
    return len(entries)
