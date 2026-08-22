"""Build the desktop distribution and its website release metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP64_LIMIT, ZipFile

from upload_contract import APP_VERSION

ROOT = Path(__file__).resolve().parent
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


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
    """Zip a PyInstaller directory and emit JSON/checksum metadata beside it."""
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Invalid release version: {version}")
    if not source_dir.is_dir() or not any(path.is_file() for path in source_dir.rglob("*")):
        raise FileNotFoundError(f"Desktop distribution is empty or missing: {source_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"FT-DataUpload-v{version}.zip"
    metadata_path = output_dir / "release-info.json"
    checksum_path = output_dir / f"FT-DataUpload-v{version}.sha256.txt"

    archive_path.unlink(missing_ok=True)
    with ZipFile(
        archive_path,
        mode="w",
        compression=ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=True,
    ) as archive:
        for file_path in sorted(path for path in source_dir.rglob("*") if path.is_file()):
            relative = file_path.relative_to(source_dir)
            archive.write(file_path, Path(source_dir.name) / relative)

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
