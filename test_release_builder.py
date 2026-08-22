"""Regression tests for release archive metadata generation."""

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from zipfile import ZipFile

from build_release import create_release_archive, sha256_file
from upload_contract import APP_VERSION


def test_release_archive_emits_importable_metadata_and_checksum():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "FT-DataUpload"
        (source / "_internal" / "runtime").mkdir(parents=True)
        (source / "FT-DataUpload.exe").write_bytes(b"desktop executable")
        (source / "FT-Capture.exe").write_bytes(b"capture executable")
        (source / "_internal" / "runtime" / "model.bin").write_bytes(b"ocr model")

        archive, metadata_file, checksum_file, metadata = create_release_archive(
            source,
            root / "release",
            version="1.5.0",
            generated_at="2026-08-22T12:00:00Z",
        )

        assert archive.name == "FT-DataUpload-v1.5.0.zip"
        assert metadata_file.name == "release-info.json"
        assert checksum_file.name == "FT-DataUpload-v1.5.0.sha256.txt"
        assert metadata == json.loads(metadata_file.read_text(encoding="utf-8"))
        assert metadata["schemaVersion"] == 1
        assert metadata["version"] == "1.5.0"
        assert metadata["sizeBytes"] == archive.stat().st_size
        assert metadata["sha256"] == sha256_file(archive)
        assert checksum_file.read_text(encoding="utf-8") == (
            f"{metadata['sha256']}  {archive.name}\n"
        )

        with ZipFile(archive) as package:
            assert set(package.namelist()) == {
                "FT-DataUpload/FT-Capture.exe",
                "FT-DataUpload/FT-DataUpload.exe",
                "FT-DataUpload/_internal/runtime/model.bin",
            }


def test_release_builder_uses_the_application_contract_version():
    assert APP_VERSION == "1.5.0"


def test_release_builder_rejects_invalid_version_and_empty_distribution():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        empty = root / "empty"
        empty.mkdir()
        try:
            create_release_archive(empty, root / "release", version="not-a-version")
            raise AssertionError("invalid version should fail")
        except ValueError:
            pass


def _valid_distribution(root: Path) -> Path:
    source = root / "FT-DataUpload"
    (source / "_internal").mkdir(parents=True)
    (source / "FT-DataUpload.exe").write_bytes(b"app")
    (source / "FT-Capture.exe").write_bytes(b"capture")
    (source / "_internal" / "runtime.dll").write_bytes(b"runtime")
    return source


def test_release_builder_rejects_missing_helper_and_sensitive_runtime_data():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = _valid_distribution(root)
        (source / "FT-Capture.exe").unlink()
        try:
            create_release_archive(source, root / "release")
            raise AssertionError("missing capture helper should fail")
        except FileNotFoundError:
            pass

    for relative in ("ft_ocr.log", "ft_upload_config.json", "screenshots/shot.png", "unknown.txt"):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _valid_distribution(root)
            extra = source / relative
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_bytes(b"private")
            try:
                create_release_archive(source, root / "release")
                raise AssertionError(f"sensitive/unknown path should fail: {relative}")
            except ValueError:
                pass


def test_release_builder_rejects_symlinks_when_supported():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = _valid_distribution(root)
        target = root / "outside.dll"
        target.write_bytes(b"outside")
        link = source / "_internal" / "linked.dll"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            return
        try:
            create_release_archive(source, root / "release")
            raise AssertionError("release must reject symlinks")
        except ValueError:
            pass


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
    sys.exit(1 if failed else 0)
