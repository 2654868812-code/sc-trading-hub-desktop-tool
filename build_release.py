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
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP64_LIMIT, ZipFile

from upload_contract import APP_VERSION

ROOT = Path(__file__).resolve().parent
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
REQUIRED_EXECUTABLES = {"FT-DataUpload.exe", "FT-Capture.exe"}
REQUIRED_QT_RUNTIME_FILES = {
    "_internal/pyside6/qt6core.dll",
    "_internal/pyside6/qt6widgets.dll",
}
ALLOWED_ROOT_DIRECTORY = "_internal"
DENIED_NAMES = {
    "screenshots",
    "ft_upload_config.json",
    "ft_upload_history.json",
}
EXTERNAL_ICU_PATTERN = re.compile(r"(?:icuuc|icudt\d+)\.dll", re.IGNORECASE)
GPL_ONLY_QT_FRAGMENTS = (
    "canvaspainter",
    "coap",
    "graphs",
    "grpc",
    "httpserver",
    "lottie",
    "mqtt",
    "networkauth",
    "qmlcompiler",
    "quick3d",
    "quicktimeline",
    "virtualkeyboard",
    "waylandcompositor",
)
LEGAL_DOCUMENTS = (
    ("COPYING", "licenses/GPL-3.0.txt"),
    ("COPYING.LESSER", "licenses/LGPL-3.0.txt"),
    ("QT-LGPL-SOURCE.md", "licenses/RELINKING.md"),
    ("SOURCE-BUILD.md", "licenses/PRIVATE-BUILD-AUDIT.md"),
    ("THIRD-PARTY-NOTICES.md", "licenses/THIRD-PARTY-NOTICES.md"),
    ("UPSTREAM-SOURCES.json", "licenses/UPSTREAM-SOURCES.json"),
)
LEGAL_SOURCE_FILES = tuple(source for source, _destination in LEGAL_DOCUMENTS)
DESKTOP_SOURCE_FILES = (
    "app_storage.py",
    "assets/logo.ico",
    "assets/logo.png",
    "build_release.py",
    "build_installer.py",
    "fetch_upstream_sources.py",
    "capture_main.py",
    "create_shortcut.py",
    "FT-DataUpload.spec",
    "installer/FT-DataUpload.iss",
    "history.py",
    "main.py",
    "requirements.txt",
    "shutter.wav",
    "test_app_storage.py",
    "test_history.py",
    "test_installer_builder.py",
    "test_qt_migration.py",
    "test_release_builder.py",
    "test_transport_security.py",
    "test_update_checker.py",
    "test_upload_contract.py",
    "transport_security.py",
    "update_checker.py",
    "upload_contract.py",
    *LEGAL_SOURCE_FILES,
)
WEBSITE_SOURCE_FILES = (
    "ocr-service/server.py",
    "src/lib/commodity-zh.ts",
    "src/lib/location-zh.ts",
)


def sanitized_build_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Remove non-Windows PATH entries that can shadow the system ICU runtime."""
    environment = dict(os.environ if source is None else source)
    windows_root = Path(environment.get("WINDIR", r"C:\Windows")).resolve()
    clean_path: list[str] = []
    for entry in environment.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        directory = Path(entry.strip('"')).resolve()
        is_windows_directory = directory == windows_root or windows_root in directory.parents
        if not is_windows_directory and (directory / "icuuc.dll").is_file():
            continue
        clean_path.append(entry)
    environment["PATH"] = os.pathsep.join(clean_path)
    return environment


def _is_reparse_stat(info) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & flag)


def _validate_name(relative: Path) -> None:
    lowered = [part.lower() for part in relative.parts]
    if "pyqt6" in lowered:
        raise ValueError(f"PyQt6 is not releasable under the LGPL build: {relative}")
    if any(part in DENIED_NAMES for part in lowered):
        raise ValueError(f"Sensitive runtime data is not releasable: {relative}")
    if len(relative.parts) > 1 and relative.parts[0] == ALLOWED_ROOT_DIRECTORY:
        if "pyside6" in lowered and any(fragment in relative.name.lower() for fragment in GPL_ONLY_QT_FRAGMENTS):
            raise ValueError(f"GPL-only Qt module is not releasable under the LGPL build: {relative}")
        if EXTERNAL_ICU_PATTERN.fullmatch(relative.name):
            raise ValueError(f"External ICU runtime is not releasable: {relative}")
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
    found_relative_files: set[str] = set()

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
                    found_relative_files.add(relative.as_posix().lower())
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
    missing_qt = REQUIRED_QT_RUNTIME_FILES - found_relative_files
    if missing_qt:
        raise FileNotFoundError(
            "Desktop distribution is missing required dynamic Qt runtime file(s): "
            + ", ".join(sorted(missing_qt))
        )
    return files


def collect_source_files(
    desktop_root: Path = ROOT,
    website_root: Path | None = None,
) -> list[tuple[Path, Path]]:
    """Collect the fixed corresponding-source set without traversing user data."""
    desktop_root = Path(desktop_root).resolve()
    website_root = Path(website_root or desktop_root.parent / "sc-trading-hub").resolve()
    files: list[tuple[Path, Path]] = []

    for repository_name, root, relative_names in (
        ("sc-trading-hub-desktop-tool", desktop_root, DESKTOP_SOURCE_FILES),
        ("sc-trading-hub", website_root, WEBSITE_SOURCE_FILES),
    ):
        for relative_name in relative_names:
            source = root / relative_name
            try:
                info = source.lstat()
            except OSError as exc:
                raise FileNotFoundError(f"Corresponding source is missing: {source}") from exc
            if _is_reparse_stat(info) or not stat.S_ISREG(info.st_mode):
                raise ValueError(f"Corresponding source must be a regular file: {source}")
            archive_relative = Path(repository_name) / Path(relative_name)
            files.append((source, archive_relative))
    return files


def sha256_file(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return a lowercase SHA-256 digest without loading the archive into RAM."""
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text_lf(path: Path, text: str) -> None:
    """Write UTF-8 release control files with Linux-compatible LF endings."""
    with Path(path).open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


@contextmanager
def release_temporary_directory(prefix: str, parent: Path):
    """Clean staging trees despite short-lived Windows malware-scanner locks."""
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    try:
        yield path
    finally:
        for attempt in range(5):
            try:
                shutil.rmtree(path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.25 * (2 ** attempt))


def create_release_archive(
    source_dir: Path,
    output_dir: Path,
    version: str = APP_VERSION,
    generated_at: str | None = None,
    *,
    emit_metadata: bool = True,
) -> tuple[Path, Path, Path, Path, Path, dict]:
    """Emit a portable package plus a private application build-source audit bundle."""
    source_dir = Path(source_dir)
    output_dir = output_dir.resolve()
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Invalid release version: {version}")
    release_files = collect_release_files(source_dir)
    source_files = collect_source_files()
    source_dir = source_dir.resolve()

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"FT-DataUpload-v{version}.zip"
    private_dir = output_dir / "private"
    private_dir.mkdir(parents=True, exist_ok=True)
    source_archive_path = private_dir / f"FT-DataUpload-v{version}-private-build-source.zip"
    metadata_path = private_dir / "build-audit-info.json"
    checksum_path = output_dir / f"FT-DataUpload-v{version}.sha256.txt"
    source_checksum_path = private_dir / f"FT-DataUpload-v{version}-private-build-source.sha256.txt"

    with release_temporary_directory(".release-staging-", output_dir) as temp_root:
        staged_source = temp_root / "FT-DataUpload"
        for file_path, relative in release_files:
            destination = staged_source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file_path, destination)
        for source_name, destination_name in LEGAL_DOCUMENTS:
            destination = staged_source / destination_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source_name, destination)

        staged_corresponding_source = temp_root / "FT-DataUpload-source"
        for file_path, relative in source_files:
            destination = staged_corresponding_source / relative
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

        temporary_source_archive = temp_root / source_archive_path.name
        with ZipFile(
            temporary_source_archive,
            mode="w",
            compression=ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for file_path in sorted(
                path for path in staged_corresponding_source.rglob("*") if path.is_file()
            ):
                archive.write(file_path, file_path.relative_to(temp_root))
        os.replace(temporary_archive, archive_path)
        os.replace(temporary_source_archive, source_archive_path)

    # A PyInstaller directory can cross the classic ZIP threshold even if the
    # compressed archive is smaller, so keep the explicit ZIP64 guard documented.
    if archive_path.stat().st_size >= ZIP64_LIMIT:
        raise ValueError("Release archive unexpectedly exceeded the supported package size")
    if source_archive_path.stat().st_size >= ZIP64_LIMIT:
        raise ValueError("Source archive unexpectedly exceeded the supported package size")

    checksum = sha256_file(archive_path)
    source_checksum = sha256_file(source_archive_path)
    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    metadata = {
        "schemaVersion": "internal-1",
        "version": version,
        "portable": {
            "fileName": archive_path.name,
            "sizeBytes": archive_path.stat().st_size,
            "sha256": checksum,
        },
        "privateBuildSource": {
            "fileName": source_archive_path.name,
            "sizeBytes": source_archive_path.stat().st_size,
            "sha256": source_checksum,
        },
        "generatedAt": timestamp,
    }
    if emit_metadata:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".release-info-", suffix=".tmp",
            dir=output_dir, delete=False,
        ) as stream:
            temporary_metadata = Path(stream.name)
            stream.write(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        try:
            os.replace(temporary_metadata, metadata_path)
        finally:
            temporary_metadata.unlink(missing_ok=True)
    write_text_lf(checksum_path, f"{checksum}  {archive_path.name}\n")
    write_text_lf(source_checksum_path, f"{source_checksum}  {source_archive_path.name}\n")
    return (
        archive_path,
        source_archive_path,
        metadata_path,
        checksum_path,
        source_checksum_path,
        metadata,
    )


def run_pyinstaller() -> None:
    """Build both desktop executables using the checked-in PyInstaller spec."""
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "FT-DataUpload.spec", "--noconfirm", "--clean"],
        cwd=ROOT,
        env=sanitized_build_environment(),
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
    archive, source_archive, metadata, checksum, source_checksum, info = create_release_archive(
        args.source_dir,
        args.output_dir,
    )
    print(f"Release v{info['version']} ready")
    print(f"Package:  {archive}")
    print(f"Private build source: {source_archive}")
    print(f"Private audit info:   {metadata}")
    print(f"Checksum: {checksum}")
    print(f"Private source checksum: {source_checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
