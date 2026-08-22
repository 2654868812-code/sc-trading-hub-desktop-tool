"""Build the desktop distribution and its website release metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP64_LIMIT, ZipFile

from upload_contract import APP_VERSION

ROOT = Path(__file__).resolve().parent
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
REQUIRED_EXECUTABLES = {"FT-DataUpload.exe", "FT-Capture.exe"}
ALLOWED_ROOT_DIRECTORY = "_internal"
DENIED_NAMES = {
    "screenshots",
    "ft_upload_config.json",
    "ft_upload_history.json",
}


def _is_reparse_stat(info) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & flag)


def _validate_name(relative: Path) -> None:
    lowered = [part.lower() for part in relative.parts]
    if any(part in DENIED_NAMES for part in lowered):
        raise ValueError(f"Sensitive runtime data is not releasable: {relative}")
    if relative.suffix.lower() == ".log":
        raise ValueError(f"Log files are not releasable: {relative}")
    if len(relative.parts) == 1:
        if relative.name not in REQUIRED_EXECUTABLES | {ALLOWED_ROOT_DIRECTORY}:
            raise ValueError(f"Unexpected release root entry: {relative}")
    elif relative.parts[0] != ALLOWED_ROOT_DIRECTORY:
        raise ValueError(f"Unexpected release directory: {relative.parts[0]}")


def collect_release_files(source_dir: Path) -> list[tuple[Path, Path]]:
    """Return the explicit release allowlist while rejecting links and extras."""
    source_dir = Path(source_dir)
    try:
        source_info = source_dir.lstat()
    except OSError as exc:
        raise FileNotFoundError(f"Desktop distribution is missing: {source_dir}") from exc
    if _is_reparse_stat(source_info):
        raise ValueError(f"Release source cannot be a link or reparse point: {source_dir}")
    source_dir = source_dir.resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Desktop distribution is missing: {source_dir}")
    files: list[tuple[Path, Path]] = []
    found_executables: set[str] = set()

    def visit(directory: Path) -> None:
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name.lower()):
                path = Path(entry.path)
                relative = path.relative_to(source_dir)
                info = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or _is_reparse_stat(info):
                    raise ValueError(f"Links and reparse points are not releasable: {relative}")
                _validate_name(relative)
                if stat.S_ISDIR(info.st_mode):
                    if len(relative.parts) == 1 and relative.name != ALLOWED_ROOT_DIRECTORY:
                        raise ValueError(f"Unexpected release root directory: {relative}")
                    visit(path)
                elif stat.S_ISREG(info.st_mode):
                    if len(relative.parts) == 1 and relative.name not in REQUIRED_EXECUTABLES:
                        raise ValueError(f"Unexpected release root file: {relative}")
                    files.append((path, relative))
                    if len(relative.parts) == 1:
                        found_executables.add(relative.name)
                else:
                    raise ValueError(f"Unsupported release entry: {relative}")

    visit(source_dir)
    missing = REQUIRED_EXECUTABLES - found_executables
    if missing:
        raise FileNotFoundError(
            "Desktop distribution is missing required executable(s): " + ", ".join(sorted(missing))
        )
    if not any(relative.parts[0] == ALLOWED_ROOT_DIRECTORY for _, relative in files):
        raise FileNotFoundError("Desktop runtime directory is empty or missing: _internal")
    return files


def sha256_file(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return a lowercase SHA-256 digest without loading the archive into RAM."""
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_release_archive(
    source_dir: Path,
    output_dir: Path,
    version: str = APP_VERSION,
    generated_at: str | None = None,
) -> tuple[Path, Path, Path, dict]:
    """Stage an allowlisted PyInstaller tree and emit release metadata."""
    source_dir = Path(source_dir)
    output_dir = output_dir.resolve()
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Invalid release version: {version}")
    release_files = collect_release_files(source_dir)
    source_dir = source_dir.resolve()

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"FT-DataUpload-v{version}.zip"
    metadata_path = output_dir / "release-info.json"
    checksum_path = output_dir / f"FT-DataUpload-v{version}.sha256.txt"

    with tempfile.TemporaryDirectory(prefix=".release-staging-", dir=output_dir) as temp:
        temp_root = Path(temp)
        staged_source = temp_root / "FT-DataUpload"
        for file_path, relative in release_files:
            destination = staged_source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file_path, destination)

        temporary_archive = temp_root / archive_path.name
        with ZipFile(
            temporary_archive,
            mode="w",
            compression=ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for file_path in sorted(path for path in staged_source.rglob("*") if path.is_file()):
                archive.write(file_path, file_path.relative_to(temp_root))
        os.replace(temporary_archive, archive_path)

    # A PyInstaller directory can cross the classic ZIP threshold even if the
    # compressed archive is smaller, so keep the explicit ZIP64 guard documented.
    if archive_path.stat().st_size >= ZIP64_LIMIT:
        raise ValueError("Release archive unexpectedly exceeded the supported package size")

    checksum = sha256_file(archive_path)
    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    metadata = {
        "schemaVersion": 1,
        "version": version,
        "fileName": archive_path.name,
        "sizeBytes": archive_path.stat().st_size,
        "sha256": checksum,
        "generatedAt": timestamp,
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    checksum_path.write_text(f"{checksum}  {archive_path.name}\n", encoding="utf-8")
    return archive_path, metadata_path, checksum_path, metadata


def run_pyinstaller() -> None:
    """Build both desktop executables using the checked-in PyInstaller spec."""
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "FT-DataUpload.spec", "--noconfirm"],
        cwd=ROOT,
        check=True,
    )
    main_dist = ROOT / "dist" / "FT-DataUpload"
    capture_executable = ROOT / "dist" / "FT-Capture" / "FT-Capture.exe"
    if not capture_executable.is_file():
        raise FileNotFoundError(f"Capture executable is missing: {capture_executable}")
    shutil.copyfile(capture_executable, main_dist / "FT-Capture.exe")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build FT-DataUpload and generate website release metadata.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Reuse an existing dist/FT-DataUpload directory.",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=ROOT / "dist" / "FT-DataUpload",
        help="PyInstaller distribution directory (default: dist/FT-DataUpload).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "release",
        help="Release output directory (default: release).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.skip_build:
        run_pyinstaller()
    archive, metadata, checksum, info = create_release_archive(
        args.source_dir,
        args.output_dir,
    )
    print(f"Release v{info['version']} ready")
    print(f"Package:  {archive}")
    print(f"Metadata: {metadata}")
    print(f"Checksum: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
