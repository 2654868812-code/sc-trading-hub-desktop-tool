"""Stage and compile the Windows x64 installer with Inno Setup."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from build_release import (
    LEGAL_DOCUMENTS,
    ROOT,
    VERSION_PATTERN,
    collect_release_files,
    create_release_archive,
    release_temporary_directory,
    run_pyinstaller,
    sha256_file,
    write_text_lf,
)
from upload_contract import APP_VERSION

APP_ID = "{B85B27CF-32C2-4F80-A187-27B0FA7E0A15}"
INSTALLER_SCRIPT = ROOT / "installer" / "FT-DataUpload.iss"
Runner = Callable[..., object]


def atomic_replace_with_exact_case(source: Path, destination: Path) -> None:
    """Replace a file while forcing its exact directory-entry casing on Windows."""
    source = Path(source)
    destination = Path(destination)
    existing = next(
        (Path(entry.path) for entry in os.scandir(destination.parent)
         if entry.name.casefold() == destination.name.casefold()),
        None,
    )
    if existing is None or existing.name == destination.name:
        os.replace(source, destination)
        return

    backup = destination.parent / f".{destination.name}.case-backup"
    if backup.exists():
        raise FileExistsError(f"Case-normalization backup already exists: {backup}")
    os.replace(existing, backup)
    try:
        os.replace(source, destination)
    except Exception:
        os.replace(backup, existing)
        raise
    backup.unlink()


def stage_installer_tree(source_dir: Path, stage_dir: Path) -> Path:
    """Copy the allowlisted runtime and LGPL notices into a fresh staging tree."""
    source_dir = Path(source_dir)
    stage_dir = Path(stage_dir)
    if stage_dir.exists():
        raise FileExistsError(f"Installer staging directory already exists: {stage_dir}")
    release_files = collect_release_files(source_dir)
    stage_dir.mkdir(parents=True)
    for file_path, relative in release_files:
        destination = stage_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, destination)
    for source_name, destination_name in LEGAL_DOCUMENTS:
        destination = stage_dir / destination_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / source_name, destination)
    return stage_dir


def find_iscc() -> Path:
    """Locate a supported Inno Setup compiler installation."""
    configured = os.environ.get("INNO_SETUP_COMPILER")
    local_programs = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"
    candidates = [
        Path(configured) if configured else None,
        local_programs / "Inno Setup 7" / "ISCC.exe",
        local_programs / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 7" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 7" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "Inno Setup compiler not found. Install Inno Setup 6/7 or set INNO_SETUP_COMPILER."
    )


def compile_installer(
    source_dir: Path,
    output_dir: Path,
    *,
    version: str = APP_VERSION,
    iscc_path: Path | None = None,
    runner: Runner = subprocess.run,
) -> Path:
    """Compile one installer and atomically publish it into the release directory."""
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Invalid release version: {version}")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    compiler = Path(iscc_path) if iscc_path is not None else find_iscc()
    installer_name = f"FT-DataUpload-v{version}-setup.exe"
    destination = output_dir / installer_name

    with release_temporary_directory(".installer-staging-", output_dir) as temp_root:
        staged_source = stage_installer_tree(source_dir, temp_root / "app")
        compiler_output = temp_root / "output"
        compiler_output.mkdir()
        command = [
            str(compiler),
            f"/DAppVersion={version}",
            f"/DSourceDir={staged_source}",
            f"/DOutputDir={compiler_output}",
            f"/DSetupIcon={ROOT / 'assets' / 'logo.ico'}",
            str(INSTALLER_SCRIPT),
        ]
        runner(command, cwd=ROOT, check=True)
        compiled = compiler_output / installer_name
        if (not compiled.is_file() or compiled.stat().st_size < 64 * 1024
                or compiled.stat().st_size >= 2 * 1024 * 1024 * 1024):
            raise FileNotFoundError(f"Inno Setup did not emit the expected installer: {compiled}")
        with compiled.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError(f"Inno Setup output is not a Windows PE executable: {compiled}")
        atomic_replace_with_exact_case(compiled, destination)
    return destination


def write_installer_release_metadata(
    installer_path: Path,
    upstream_source_dir: Path,
    output_dir: Path,
    *,
    version: str = APP_VERSION,
    generated_at: str | None = None,
    manifest_path: Path = ROOT / "UPSTREAM-SOURCES.json",
) -> tuple[Path, dict]:
    """Atomically write schema-v4 metadata for the installer and controlled LGPL sources."""
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Invalid release version: {version}")
    installer_path = Path(installer_path).resolve()
    upstream_source_dir = Path(upstream_source_dir).resolve()
    manifest_path = Path(manifest_path).resolve()
    expected_installer = f"FT-DataUpload-v{version}-setup.exe"
    if installer_path.name != expected_installer or not installer_path.is_file():
        raise FileNotFoundError(f"Expected installer is missing: {expected_installer}")
    if installer_path.stat().st_size <= 0:
        raise ValueError("Installer cannot be empty")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1 or manifest.get("releaseVersion") != version:
        raise ValueError("Upstream source manifest does not match the release")
    manifest_archives = {
        item.get("fileName"): item
        for item in manifest.get("archives", [])
        if isinstance(item, dict)
    }
    requirements = (
        ("qt", "Qt", "6.11.2", "qt-everywhere-src-6.11.2.zip"),
        ("pyside6", "PySide6 and Shiboken6", "6.11.2", "pyside-setup-everywhere-src-6.11.2.tar.xz"),
    )
    components = []
    for component_id, name, component_version, file_name in requirements:
        archive = upstream_source_dir / file_name
        facts = manifest_archives.get(file_name)
        if not archive.is_file() or not facts:
            raise FileNotFoundError(f"Controlled upstream source is missing: {file_name}")
        if archive.stat().st_size != facts.get("sizeBytes") or sha256_file(archive) != facts.get("sha256"):
            raise ValueError(f"Controlled upstream source failed verification: {file_name}")
        components.append({
            "id": component_id,
            "name": name,
            "version": component_version,
            "source": {
                "fileName": file_name,
                "sizeBytes": archive.stat().st_size,
                "sha256": facts["sha256"],
            },
        })

    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    metadata = {
        "schemaVersion": 4,
        "version": version,
        "installer": {
            "fileName": installer_path.name,
            "sizeBytes": installer_path.stat().st_size,
            "sha256": sha256_file(installer_path),
            "signed": False,
        },
        "openSourceComponents": components,
        "generatedAt": timestamp,
    }
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / "release-info.json"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=".release-info-", suffix=".tmp",
        dir=output_dir, delete=False,
    ) as stream:
        temporary_path = Path(stream.name)
        json.dump(metadata, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    try:
        os.replace(temporary_path, metadata_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return metadata_path, metadata


def build_installer_release(
    source_dir: Path,
    output_dir: Path,
    *,
    version: str = APP_VERSION,
    iscc_path: Path | None = None,
    runner: Runner = subprocess.run,
    upstream_source_dir: Path | None = None,
    upstream_manifest_path: Path = ROOT / "UPSTREAM-SOURCES.json",
) -> dict[str, Path]:
    """Create the installer, private audit source, and public schema-v4 metadata."""
    (
        portable,
        private_source_archive,
        _legacy_metadata,
        portable_checksum,
        private_source_checksum,
        _legacy_info,
    ) = create_release_archive(source_dir, output_dir, version=version, emit_metadata=False)
    installer = compile_installer(
        source_dir,
        output_dir,
        version=version,
        iscc_path=iscc_path,
        runner=runner,
    )
    installer_checksum = Path(output_dir).resolve() / f"FT-DataUpload-v{version}-setup.sha256.txt"
    checksum_text = f"{sha256_file(installer)}  {installer.name}\n"
    with tempfile.NamedTemporaryFile(
        prefix=".installer-checksum-", suffix=".tmp",
        dir=installer_checksum.parent, delete=False,
    ) as stream:
        temporary_checksum = Path(stream.name)
    try:
        write_text_lf(temporary_checksum, checksum_text)
        atomic_replace_with_exact_case(temporary_checksum, installer_checksum)
    finally:
        temporary_checksum.unlink(missing_ok=True)
    metadata, _info = write_installer_release_metadata(
        installer,
        upstream_source_dir or Path(output_dir).resolve() / "upstream-sources",
        output_dir,
        version=version,
        manifest_path=upstream_manifest_path,
    )
    return {
        "installer": installer,
        "portable": portable,
        "private_source": private_source_archive,
        "metadata": metadata,
        "installer_checksum": installer_checksum,
        "portable_checksum": portable_checksum,
        "private_source_checksum": private_source_checksum,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compile the FT-DataUpload Windows installer.")
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Reuse an existing dist/FT-DataUpload directory instead of running PyInstaller.",
    )
    parser.add_argument("--source-dir", type=Path, default=ROOT / "dist" / "FT-DataUpload")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "release")
    parser.add_argument("--iscc", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.skip_build:
        run_pyinstaller()
    result = build_installer_release(args.source_dir, args.output_dir, iscc_path=args.iscc)
    print(f"Installer: {result['installer']}")
    print(f"Portable:  {result['portable']}")
    print(f"Private build source: {result['private_source']}")
    print(f"Metadata:  {result['metadata']}")
    print(f"Installer checksum: {result['installer_checksum']}")
    print(f"Private source checksum: {result['private_source_checksum']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
