"""Private per-user storage helpers for the desktop assistant.

Runtime state must never live beside the executable: an installation directory
can be shared, replaced during an update, or writable by another local process.
All mutable data is kept below the current Windows user's Local AppData folder.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path


APP_DIR_PARTS = ("FantianTradingHub", "DesktopAssistant")
CONFIG_NAME = "ft_upload_config.json"
HISTORY_NAME = "ft_upload_history.json"
SCREENSHOT_FOLDER = "screenshots"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_SCREENSHOT_BYTES = 64 * 1024 * 1024
SCREENSHOT_NAME_RE = re.compile(
    r"^sc_shot_\d{8}_\d{6}(?:_[0-9a-f]{8})?(?:_thumb)?\.png$",
    re.IGNORECASE,
)


def storage_root(environ: dict[str, str] | None = None) -> Path:
    """Return the per-user application directory without creating it."""
    values = os.environ if environ is None else environ
    local_app_data = values.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base.joinpath(*APP_DIR_PARTS)


DATA_DIR = storage_root()
CONFIG_PATH = DATA_DIR / CONFIG_NAME
HISTORY_PATH = DATA_DIR / HISTORY_NAME
SCREENSHOT_DIR = DATA_DIR / SCREENSHOT_FOLDER


def is_reparse_point(path: Path) -> bool:
    """Return True for symlinks and Windows junction/reparse entries."""
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _ensure_plain_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if is_reparse_point(path) or not path.is_dir():
        raise RuntimeError(f"Refusing unsafe application data directory: {path}")


def ensure_storage(root: Path | None = None) -> tuple[Path, Path]:
    """Create and validate the application and screenshot directories."""
    app_dir = Path(root) if root is not None else DATA_DIR
    screenshots = app_dir / SCREENSHOT_FOLDER
    _ensure_plain_directory(app_dir)
    _ensure_plain_directory(screenshots)
    return app_dir, screenshots


def atomic_write_json(path: Path | str, payload: object) -> None:
    """Durably replace a JSON file without exposing a partially written file."""
    destination = Path(path)
    _ensure_plain_directory(destination.parent)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, destination)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def load_json_object(path: Path | str, max_bytes: int = MAX_JSON_BYTES) -> dict | None:
    """Read a small, plain JSON object; unsafe/corrupt inputs return None."""
    source = Path(path)
    try:
        info = source.lstat()
        if is_reparse_point(source) or not stat.S_ISREG(info.st_mode):
            return None
        if info.st_size < 0 or info.st_size > max_bytes:
            return None
        with source.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _legacy_screenshot_name(value: object) -> str | None:
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
    return name if SCREENSHOT_NAME_RE.fullmatch(name) else None


def _copy_plain_screenshot(source: Path, destination: Path) -> None:
    try:
        info = source.lstat()
    except OSError:
        return
    if is_reparse_point(source) or not stat.S_ISREG(info.st_mode):
        return
    if info.st_size <= 0 or info.st_size > MAX_SCREENSHOT_BYTES:
        return
    if destination.exists():
        return
    shutil.copyfile(source, destination)


def migrate_legacy_storage(legacy_dir: Path | str, root: Path | None = None) -> None:
    """Copy validated legacy data into Local AppData without deleting originals.

    Migration is deliberately conservative. It never follows links and only
    copies screenshots referenced by the parsed history document.
    """
    legacy = Path(legacy_dir)
    app_dir, screenshots = ensure_storage(root)
    try:
        if legacy.resolve() == app_dir.resolve():
            return
    except OSError:
        return
    if not legacy.is_dir() or is_reparse_point(legacy):
        return

    config_source = legacy / CONFIG_NAME
    config_destination = app_dir / CONFIG_NAME
    if not config_destination.exists():
        config = load_json_object(config_source)
        if config is not None:
            atomic_write_json(config_destination, config)

    history_source = legacy / HISTORY_NAME
    history_destination = app_dir / HISTORY_NAME
    history = load_json_object(history_source)
    if not history_destination.exists() and history is not None:
        entries = history.get("entries")
        if isinstance(entries, list):
            atomic_write_json(history_destination, {"entries": entries})

    entries = history.get("entries", []) if history else []
    if not isinstance(entries, list):
        return
    legacy_screenshots = legacy / SCREENSHOT_FOLDER
    if not legacy_screenshots.is_dir() or is_reparse_point(legacy_screenshots):
        return
    for entry in entries:
        name = _legacy_screenshot_name(entry.get("screenshot")) if isinstance(entry, dict) else None
        if not name:
            continue
        _copy_plain_screenshot(legacy_screenshots / name, screenshots / name)
        thumb_name = f"{Path(name).stem}_thumb.png"
        if SCREENSHOT_NAME_RE.fullmatch(thumb_name):
            _copy_plain_screenshot(legacy_screenshots / thumb_name, screenshots / thumb_name)
