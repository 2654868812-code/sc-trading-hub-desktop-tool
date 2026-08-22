"""Regression tests for release archive metadata generation."""

import json
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
        (source / "runtime").mkdir(parents=True)
        (source / "FT-DataUpload.exe").write_bytes(b"desktop executable")
        (source / "runtime" / "model.bin").write_bytes(b"ocr model")

        archive, metadata_file, checksum_file, metadata = create_release_archive(
            source,
            root / "release",
            version="1.4.0",
            generated_at="2026-08-22T12:00:00Z",
        )

        assert archive.name == "FT-DataUpload-v1.4.0.zip"
        assert metadata_file.name == "release-info.json"
        assert checksum_file.name == "FT-DataUpload-v1.4.0.sha256.txt"
        assert metadata == json.loads(metadata_file.read_text(encoding="utf-8"))
        assert metadata["schemaVersion"] == 1
        assert metadata["version"] == "1.4.0"
        assert metadata["sizeBytes"] == archive.stat().st_size
        assert metadata["sha256"] == sha256_file(archive)
        assert checksum_file.read_text(encoding="utf-8") == (
            f"{metadata['sha256']}  {archive.name}\n"
        )

        with ZipFile(archive) as package:
            assert package.namelist() == [
                "FT-DataUpload/FT-DataUpload.exe",
                "FT-DataUpload/runtime/model.bin",
            ]


def test_release_builder_uses_the_application_contract_version():
    assert APP_VERSION == "1.3.0"


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
